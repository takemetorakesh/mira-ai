"""End-to-end turns through the real orchestrator, tools and database, with a scripted model.
Verifies the plumbing and guardrails deterministically; model quality is measured by the evals."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from app.agent.orchestrator import TurnInProgress, run_turn
from app.agent.state import BookingState
from app.config import get_settings, today
from app.db.models import Conversation
from app.db.session import get_sessionmaker
from app.llm.base import LLMResult, ToolCall
from app.tools.base import ToolContext
from app.tools.registry import execute
from seed.seed import main as seed


class ScriptedLLM:
    """Each step is a function(messages) -> list of (tool_name, args) to call."""

    model = "scripted"

    def __init__(self, steps):
        self.steps = list(steps)

    async def complete(self, messages, tools, tool_choice="auto", session_id=None):
        calls = self.steps.pop(0)(messages)
        # args=None stands for malformed JSON from the model
        return LLMResult(
            None,
            [ToolCall(f"c{uuid.uuid4().hex[:6]}", n, "{bad json" if a is None else json.dumps(a)) for n, a in calls],
        )


def last_result(messages, name=None):
    for m in reversed(messages):
        if m.role == "tool":
            return json.loads(m.content)


def call(name, **args):
    return lambda messages: [(name, args)]


def respond(fn, action="answer_question"):
    return lambda messages: [("respond", {"message": fn(last_result(messages)), "next_action": action})]


@pytest.fixture(scope="module", autouse=True)
async def seeded():
    await seed()


async def new_conversation() -> uuid.UUID:
    cid = uuid.uuid4()
    async with get_sessionmaker()() as s, s.begin():
        s.add(Conversation(id=cid, state=BookingState().model_dump(mode="json")))
    return cid


async def ignore_events(event, data):
    pass


async def turn(cid, text, steps):
    events = []

    async def emit(e, d):
        events.append((e, d))

    return await run_turn(cid, text, ScriptedLLM(steps), emit), events


async def test_happy_path_search_quote_hold():
    cid = await new_conversation()

    out, events = await turn(
        cid,
        "Goa this weekend for me and 2 friends, something private",
        [
            call(
                "update_booking_state",
                city="goa",
                dates={"kind": "weekend", "which": "this"},
                adults=3,
                preferences=["standalone_unit"],
            ),
            call("search_properties"),
            respond(
                lambda r: "{room_name} at {property_name}: ₹{avg_room_cost_per_night:,}/night".format(
                    **r["options"][0]
                ),
                "present_options",
            ),
        ],
    )
    st = out["state"]
    assert (st["city"], st["check_in"], st["check_out"], st["guests"]) == ("Goa", "2026-10-09", "2026-10-11", 3)
    search = next(c for c in out["tool_calls"] if c["name"] == "search_properties")["result"]
    ids = [o["room_type_id"] for o in search["options"]]
    assert "goa-casa-azul-pool-villa-1br" not in ids  # sold out this weekend
    assert "goa-casa-azul-pool-villa-1br" in [s["room_type_id"] for s in search["sold_out_matches"]]
    assert ids[0] == "goa-sossego-plunge-cottage"  # cheapest private fit for 3
    assert out["errors"] == [] and out["next_action"] == "present_options"
    assert {e for e, _ in events} >= {"tool_call", "tool_result", "state", "done"}

    out, _ = await turn(
        cid,
        "The plunge pool cottage. Name is Asha Rao",
        [
            call("update_booking_state", selected_room_type_id="goa-sossego-plunge-cottage", guest_name="Asha Rao"),
            call("calculate_quote", room_type_id="goa-sossego-plunge-cottage"),
            # Trying to hold in the same turn as the first quote must be refused.
            call("create_booking_hold", room_type_id="goa-sossego-plunge-cottage"),
            respond(lambda r: "Shall I hold it?", "confirm_hold"),
        ],
    )
    quote, early_hold = [c for c in out["tool_calls"] if c["name"] in ("calculate_quote", "create_booking_hold")]
    assert early_hold["result"]["error"] == "confirmation_required"
    total = quote["result"]["total"]
    assert total == quote["result"]["total_before_tax"] + quote["result"]["total_tax"]

    out, _ = await turn(
        cid,
        "yes please hold it",
        [
            call("create_booking_hold", room_type_id="goa-sossego-plunge-cottage"),
            respond(
                lambda r: f"Done, I've reserved it. Total ₹{r['total']:,}, reference {r['hold_reference']}.",
                "hold_created",
            ),
        ],
    )
    assert out["errors"] == []
    assert out["state"]["hold"]["total"] == total


async def test_change_party_and_extend_invalidates_quote():
    cid = await new_conversation()
    await turn(
        cid,
        "Udaipur next weekend, 2 of us, the lake suite",
        [
            call(
                "update_booking_state",
                city="Udaipur",
                dates={"kind": "weekend", "which": "next"},
                adults=2,
                selected_room_type_id="udaipur-jharokha-lake-suite",
            ),
            call("calculate_quote", room_type_id="udaipur-jharokha-lake-suite"),
            respond(lambda r: f"₹{r['total']:,} in total"),
        ],
    )
    out, _ = await turn(
        cid,
        "Actually make that 4 people and stay one more night",
        [
            call("update_booking_state", adults=4, dates={"kind": "extend", "nights": 1}),
            respond(lambda r: "Noted"),
        ],
    )
    st = out["state"]
    assert (st["guests"], st["check_out"], st["nights"]) == (4, "2026-10-19", 3)
    assert st["last_quote"] is None
    issues = out["tool_calls"][0]["result"]["issues"]
    assert issues == [
        {
            "code": "over_capacity",
            "room_type_id": "udaipur-jharokha-lake-suite",
            "max_guests_per_room": 3,
            "guests": 4,
            "rooms": 1,
            "rooms_needed": 2,
        }
    ]


async def test_ungrounded_reply_is_retried_then_replaced():
    cid = await new_conversation()
    out, _ = await turn(
        cid,
        "Is the pool at Snowline heated?",
        [
            respond(lambda r: "Yes, heated, and only ₹5,000 a night!"),
            respond(lambda r: "Still ₹5,000!"),
        ],
    )
    assert out["next_action"] == "handoff_to_staff"
    assert [e["kind"] for e in out["errors"]] == ["grounding", "grounding"]


async def test_unserved_city_and_bad_tool_args_become_results():
    cid = await new_conversation()
    out, _ = await turn(
        cid,
        "Jaipur tomorrow",
        [
            lambda m: [
                ("update_booking_state", {"city": "Jaipur"}),
                ("search_properties", {"max_nightly_rate": "cheap"}),
            ],
            respond(lambda r: "Sorry, we're not in Jaipur yet."),
        ],
    )
    upd, search = out["tool_calls"]
    assert upd["result"]["issues"][0]["code"] == "city_not_served"
    assert search["result"]["error"] == "invalid_arguments"


async def test_malformed_json_is_echoed_back():
    cid = await new_conversation()
    out, _ = await turn(
        cid,
        "Is the villa free?",
        [
            lambda m: [("check_availability", None)],
            respond(lambda r: "Let me check that."),
        ],
    )
    assert out["tool_calls"][0]["result"]["received"] == "{bad json"
    assert out["state"]["city"] is None


async def test_concurrent_holds_for_last_unit():
    """The 3BR villa has one unit: two guests confirming at once → exactly one hold."""

    async def ready_ctx():
        cid = await new_conversation()
        st = BookingState(
            city="Goa",
            adults=6,
            guest_name="Guest",
            check_in=today().replace(day=20),
            check_out=today().replace(day=22),
        )
        s = get_sessionmaker()()
        ctx = ToolContext(s, get_sessionmaker(), st, cid, 1, today(), get_settings())
        await execute(
            ctx, ToolCall("q", "calculate_quote", json.dumps({"room_type_id": "goa-casa-azul-pool-villa-3br"}))
        )
        ctx.turn_seq = 2
        return ctx

    a, b = await ready_ctx(), await ready_ctx()
    hold = ToolCall("h", "create_booking_hold", json.dumps({"room_type_id": "goa-casa-azul-pool-villa-3br"}))
    runs = await asyncio.gather(execute(a, hold), execute(b, hold))
    assert sorted(r.status for r in runs) == ["error", "ok"]
    assert next(r.result for r in runs if r.status == "error")["error"] == "unavailable"
    for ctx in (a, b):
        await ctx.session.close()


async def test_duplicate_calls_are_cached_and_reply_gets_a_second_try():
    cid = await new_conversation()
    lookup = call("get_property_details", property_id="manali-snowline-spa")
    garbled_reply = lambda m: [("respond", None)]  # noqa: E731
    llm = ScriptedLLM(
        [lookup] * 5 + [garbled_reply, respond(lambda r: "Snowline has an indoor pool; heating isn't on file.")]
    )
    choices = []
    original = llm.complete

    async def spy(messages, tools, tool_choice="auto", session_id=None):
        choices.append([t.name for t in tools])
        return await original(messages, tools, tool_choice, session_id)

    llm.complete = spy
    out = await run_turn(cid, "Is Snowline's pool heated?", llm, ignore_events)
    assert [c["name"] for c in out["tool_calls"]] == ["get_property_details"]  # 4 duplicates served from cache
    assert choices[-2:] == [["respond"], ["respond"]] and len(choices[0]) > 1
    assert [e["kind"] for e in out["errors"]] == ["invalid_reply"]
    assert out["next_action"] == "answer_question"  # got a real reply on the second reply-only call


async def test_rehold_same_room_replaces_own_hold():
    """Re-holding the last unit (e.g. after adding an add-on) must not be blocked by the guest's own hold."""
    cid = await new_conversation()
    st = BookingState(
        city="Goa", adults=6, guest_name="Guest", check_in=today().replace(day=26), check_out=today().replace(day=28)
    )
    async with get_sessionmaker()() as s:
        ctx = ToolContext(s, get_sessionmaker(), st, cid, 1, today(), get_settings())
        villa = "goa-casa-azul-pool-villa-3br"
        for seq, addons in ((1, []), (3, ["goa-casa-azul-breakfast"])):
            ctx.turn_seq = seq
            await execute(
                ctx, ToolCall("q", "calculate_quote", json.dumps({"room_type_id": villa, "addon_ids": addons}))
            )
            ctx.turn_seq = seq + 1
            run = await execute(
                ctx, ToolCall("h", "create_booking_hold", json.dumps({"room_type_id": villa, "addon_ids": addons}))
            )
            assert run.status == "ok", run.result


async def test_second_message_while_turn_running_is_rejected():
    cid = await new_conversation()
    async with get_sessionmaker()() as s, s.begin():
        await s.execute(select(Conversation).where(Conversation.id == cid).with_for_update())  # a turn in flight
        with pytest.raises(TurnInProgress):
            await turn(cid, "hello?", [])

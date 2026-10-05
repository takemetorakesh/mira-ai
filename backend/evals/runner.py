"""Run the scripted conversations in evals/cases against the real model and score each turn.

  make eval                       # all cases
  make eval ARGS="-k cheaper"     # cases whose file name contains "cheaper"

Each case starts from a freshly seeded eval database with today frozen to Tue 6 Oct 2026, so
results are comparable across runs and models. Writes evals/report.md and evals/results.json.
"""

import argparse
import asyncio
import json
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path

from app.config import eval_database_url

os.environ["DATABASE_URL"] = eval_database_url()
os.environ.setdefault("MIRA_TODAY", "2026-10-06")

import yaml

from app.agent.orchestrator import FALLBACK_REPLY, run_turn
from app.agent.state import BookingState
from app.config import get_settings
from app.db.models import Conversation
from app.db.session import get_sessionmaker
from app.llm.factory import create_llm_client
from seed.seed import main as reseed

EVAL_DIR = Path(__file__).parent
DIMENSIONS = [
    "tool_selection",
    "state",
    "recommendation",
    "pricing",
    "hallucination",
    "next_action",
    "response_content",
]


def check_turn(expect: dict, out: dict) -> list[dict]:
    """Returns one {dimension, check, passed, detail} per expectation, plus always-on grounding checks."""
    called = [c["name"] for c in out["tool_calls"]]
    ok_calls = {c["name"] for c in out["tool_calls"] if c["status"] == "ok"}
    reply = out["reply"].lower()
    state = out["state"]
    checks = []

    def add(dim, name, passed, detail=""):
        checks.append({"dimension": dim, "check": name, "passed": bool(passed), "detail": detail})

    for field, want in (expect.get("state") or {}).items():
        got = state.get(field)
        same = sorted(got) == sorted(want) if isinstance(want, list) and isinstance(got, list) else got == want
        add("state", f"state.{field}", same, f"want {want!r}, got {got!r}")
    for name in expect.get("tools_called", []):
        add("tool_selection", f"called {name}", name in ok_calls, f"called: {called}")
    if anyof := expect.get("tools_called_any"):
        add("tool_selection", f"called one of {anyof}", ok_calls & set(anyof), f"called: {called}")
    for name in expect.get("tools_not_called", []):
        add("tool_selection", f"did not call {name}", name not in ok_calls, f"called: {called}")
    if "hold_created" in expect:
        add(
            "tool_selection",
            f"hold_created={expect['hold_created']}",
            ("create_booking_hold" in ok_calls) == expect["hold_created"],
            f"called: {called}",
        )
    if want := expect.get("top_option"):
        searches = [c["result"] for c in out["tool_calls"] if c["name"] == "search_properties" and c["status"] == "ok"]
        got = searches[0]["options"][0]["room_type_id"] if searches and searches[0]["options"] else None
        add("recommendation", "top option", got == want, f"want {want}, got {got}")
    if want := expect.get("quote_total"):
        quotes = [
            c["result"]["total"] for c in out["tool_calls"] if c["name"] == "calculate_quote" and c["status"] == "ok"
        ]
        add("pricing", "quote total", want in quotes, f"want {want}, quotes {quotes}")
        add(
            "pricing",
            "reply states the quoted total",
            f"{want:,}" in out["reply"] or str(want) in out["reply"],
            out["reply"][:160],
        )
    if want := expect.get("next_action"):
        add("next_action", "next_action", out["next_action"] in want, f"want one of {want}, got {out['next_action']}")
    if any_of := expect.get("reply_mentions_any"):
        add(
            "response_content",
            "reply mentions",
            any(s.lower() in reply for s in any_of),
            f"any of {any_of}: {out['reply'][:200]}",
        )
    for phrase in expect.get("reply_excludes", []):
        add("hallucination", f"reply excludes '{phrase}'", phrase.lower() not in reply, out["reply"][:200])

    # The guest only sees the final reply; drafts rejected by the grounding check and then fixed are
    # counted separately (report: "caught by grounding check") rather than as failures.
    grounding = [e for e in out["errors"] if e["kind"] == "grounding"]
    add(
        "hallucination",
        "final reply grounded",
        out["reply"] != FALLBACK_REPLY or not grounding,
        json.dumps([v for e in grounding for v in e["violations"]])[:300],
    )
    add("hallucination", "no fallback reply", out["reply"] != FALLBACK_REPLY, json.dumps(out["errors"])[:300])
    return checks


async def run_case(path: Path, llm) -> dict:
    case = yaml.safe_load(path.read_text())
    await reseed()
    cid = uuid.uuid4()
    async with get_sessionmaker()() as s, s.begin():
        s.add(Conversation(id=cid, state=BookingState().model_dump(mode="json")))

    async def emit(event, data):
        pass

    turns = []
    for i, t in enumerate(case["turns"], 1):
        started = time.perf_counter()
        try:
            out = await run_turn(cid, t["user"], llm, emit)
        except Exception as e:  # a crash fails the turn, not the whole run
            out = {
                "reply": "",
                "next_action": "",
                "tool_calls": [],
                "errors": [{"kind": "crash", "message": repr(e)}],
                "state": {},
            }
        seconds = round(time.perf_counter() - started, 1)
        checks = check_turn(t.get("expect", {}), out)
        turns.append(
            {
                "turn": i,
                "user": t["user"],
                "reply": out["reply"],
                "next_action": out["next_action"],
                "tools": [c["name"] for c in out["tool_calls"]],
                "seconds": seconds,
                "checks": checks,
                "trace": [
                    {"name": c["name"], "args": c["args"], "status": c["status"]}
                    | ({"error": c["result"]} if c["status"] == "error" else {})
                    for c in out["tool_calls"]
                ],
                "errors": out["errors"],
            }
        )
        failed = [c for c in checks if not c["passed"]]
        print(
            f"  turn {i} ({seconds}s): {len(checks) - len(failed)}/{len(checks)} checks"
            + (f", failed: {', '.join(c['check'] for c in failed)}" if failed else "")
        )
    return {"file": path.name, "name": case["name"], "turns": turns}


def write_report(results: list[dict], model: str) -> str:
    by_dim = defaultdict(lambda: [0, 0])
    for r in results:
        for t in r["turns"]:
            for c in t["checks"]:
                by_dim[c["dimension"]][0] += c["passed"]
                by_dim[c["dimension"]][1] += 1
    all_turns = [t for r in results for t in r["turns"]]
    passed_turns = sum(all(c["passed"] for c in t["checks"]) for t in all_turns)
    passed_cases = sum(all(c["passed"] for t in r["turns"] for c in t["checks"]) for r in results)
    latencies = sorted(t["seconds"] for t in all_turns)
    caught = sum(1 for t in all_turns for e in t.get("errors", []) if e["kind"] == "grounding")

    lines = [
        "# Eval report",
        "",
        f"Model: `{model}` · today frozen to 2026-10-06 · {len(results)} conversations, {len(all_turns)} turns",
        "",
        f"- Conversations fully passing: **{passed_cases}/{len(results)}**",
        f"- Turns fully passing: **{passed_turns}/{len(all_turns)}**",
        f"- Turn latency: median {latencies[len(latencies) // 2]}s, max {latencies[-1]}s" if latencies else "",
        f"- Ungrounded drafts caught by the grounding check before reaching the guest: {caught}",
        "",
        "| Dimension | Passed | Rate |",
        "|---|---|---|",
    ]
    for d in DIMENSIONS:
        if d in by_dim:
            p, n = by_dim[d]
            lines.append(f"| {d.replace('_', ' ')} | {p}/{n} | {p / n:.0%} |")
    lines += ["", "## Conversations", ""]
    for r in results:
        ok = all(c["passed"] for t in r["turns"] for c in t["checks"])
        lines.append(f"### {'✅' if ok else '❌'} {r['name']} (`{r['file']}`)")
        for t in r["turns"]:
            lines.append(f"- **Guest:** {t['user']}")
            tools = ", ".join(t["tools"]) or "none"
            lines.append(f"  - **Mira** (`{t['next_action']}`, {t['seconds']}s, tools: {tools}): {t['reply']}")
            for e in t.get("errors", []):
                if e["kind"] == "grounding":
                    lines.append(
                        f"  - 🛡️ grounding check rejected a draft: {'; '.join(v['message'] for v in e['violations'])}"
                    )
            for c in t["checks"]:
                if not c["passed"]:
                    lines.append(f"  - ❌ {c['dimension']} · {c['check']}: {c['detail']}")
        lines.append("")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", default="", help="only run cases whose file name contains this")
    args = parser.parse_args()

    settings = get_settings()
    llm = create_llm_client(settings)
    results = []
    for path in sorted((EVAL_DIR / "cases").glob("*.yaml")):
        if args.k in path.name:
            print(path.name)
            results.append(await run_case(path, llm))

    report = write_report(results, settings.llm_model)
    (EVAL_DIR / "report.md").write_text(report)
    (EVAL_DIR / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print("\n" + "\n".join(report.splitlines()[:16]))


if __name__ == "__main__":
    asyncio.run(main())

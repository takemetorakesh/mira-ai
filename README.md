# Mira

A small version of Mehman's guest-facing booking agent. A guest chats in plain language and Mira figures out what they want, keeps track of it across the conversation, looks things up in a Postgres catalog through tools, quotes exact prices, and puts a time-limited hold on the room.

The main idea: the model handles language, and code handles every fact, date, price and rule. The model never does arithmetic, never computes a date and never invents availability. It calls tools for all of that, and the reply is checked against what the tools returned before the guest sees it.

Design notes are in [ENGINEERING_NOTE.md](ENGINEERING_NOTE.md), and the latest eval run is in [backend/evals/report.md](backend/evals/report.md).

## Running it

You need Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 20+ with pnpm, and Postgres 15+ on localhost:5432.

```bash
make setup      # installs backend + frontend deps, copies .env.example to .env
                # then put your LLM_API_KEY in .env
make db         # creates the rakesh/pass1234 role if missing, plus databases mira and mira_eval
make migrate    # runs the Alembic migration on both databases
make seed       # loads the catalog and generates the nightly rate calendar
make dev        # API on :8000, UI on http://localhost:5173
```

```bash
make test       # 39 tests, no LLM calls (uses mira_eval)
make eval       # 16 scripted conversations against the real model, writes backend/evals/report.md
```

### Environment

| Variable | Default | |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://rakesh:pass1234@localhost:5432/mira` | Tests and evals use the same credentials against `mira_eval` |
| `LLM_PROVIDER` | `opencode_go` | or `openai`, or `openai_compatible` together with `LLM_BASE_URL` |
| `LLM_API_KEY` | | |
| `LLM_MODEL` | `deepseek-v4.1-flash` | any chat model with tool calling |
| `LLM_BASE_URL` | from the provider preset | |
| `MIRA_TODAY` | `2026-10-06` in `.env.example` | the date relative dates are resolved against. Pinned so the demo matches the seeded data (e.g. the villa sold out "this weekend"); remove it to use the real date in IST |
| `HOLD_TTL_MINUTES` | `15` | |

## How it works

```
React console ──POST /messages──► FastAPI ──► run_turn()
   chat            ◄── SSE ──        1. lock the conversation row (one turn at a time)
   booking state   tool calls,       2. prompt = rules + property index + booking state + last 8 turns
   trace           state, errors,    3. loop (≤ 6 tool steps): model picks tools → we validate + run them
                   reply             4. model calls respond() → grounding check → one retry if it fails
                                     5. save the turn and the new state in one transaction
```

**State.** Booking state (city, dates, guests, budget, preferences, chosen room, last quote, hold) is a Pydantic model stored as JSONB on the conversation. The model updates it with `update_booking_state`, sending only what changed. Dates are sent as a description (`{"kind": "weekend", "which": "next"}`, `{"kind": "extend", "nights": 1}`) and resolved in `domain/dates.py`. Old tool results aren't replayed into the prompt; the state carries what matters, including the options last shown, which is what "the other one" refers to.

**Tools** (`backend/app/tools/`): `update_booking_state`, `search_properties`, `check_availability`, `get_property_details`, `get_policy`, `get_addons`, `calculate_quote`, `create_booking_hold`, `respond`. Search, availability, quote and hold read the trip details from state rather than taking them as arguments. If something is missing they return `missing_fields`, and the model asks the guest. That keeps the search and the state from drifting apart.

**Guardrails.**
- Bad arguments, unknown ids and tool exceptions come back to the model as error results instead of crashing the turn.
- A hold is refused unless the guest saw that exact quote in an earlier message and gave a name.
- Holds lock the inventory rows, so two guests can't both get the last room.
- The reply is rejected if it contains a ₹ amount no tool returned, a room name that was never looked up, or a "you're booked" claim without a successful hold.

**Data** (`backend/app/db/models.py`). `properties`, `room_types`, `room_inventory` (one row per room type per night: rate and units open), `policies`, `addons`, `booking_holds`, `conversations`, `turns`. Free units for a night = `units_open` minus active holds, so an expired hold frees the room without a cleanup job. Ids are readable strings (`goa-casa-azul-pool-villa-1br`) because the model passes them around.

**Pricing** (`backend/app/domain/pricing.py`). Rate per room per night at base occupancy, plus `extra_guest_fee` per extra guest. GST per room-night by slab (up to ₹1,000: 0%, up to ₹7,500: 5%, above: 18%), 18% on add-ons. Integer rupees throughout.

**LLM.** The agent only knows `LLMClient`, `Message` and `ToolSpec` (`backend/app/llm/base.py`). `factory.py` picks a provider preset from `LLM_PROVIDER`. OpenCode Go needs a client User-Agent and an `x-opencode-session` header per conversation; requests without the header are rejected.

**UI** (`frontend/src/`).
- **Header:** shows the date relative dates are resolved against.
- **Chat:** plain text, because WhatsApp and Instagram are text.
- **Booking state:** fields changed this turn are highlighted, and fields still needed for a search are marked.
- **Trace:** each turn's tool calls with arguments, results, timing, next action and errors (including replies the grounding check rejected), streamed live.

## Edge cases

- Relative dates: "this weekend", "next weekend", "till the 13th", "one more night", and dates that have already passed this year (moved to next year, and Mira says so).
- Changing requirements: "make that 4 people and stay one more night" updates the state in place. An old quote is dropped when its inputs change, and the chosen room is flagged if it no longer fits.
- No availability: sold-out rooms that match are reported with the next date they're free, alongside ranked alternatives.
- Conflicting requirements: 5 guests asking for a 2-person room gets bigger rooms first, then splitting into more rooms, clearly labelled.
- Unknown information: the catalog only lists what a property has, so anything not listed (pool heating, a pet policy that isn't on file) is answered as unknown and handed to staff.
- Also: unserved cities, budgets below anything available, "anything cheaper?", "whichever is better", repeated messages while a turn is running, two guests holding the last unit.

Seed data is set up to exercise these. Casa Azul's One-Bedroom Pool Villa is sold out on Oct 9 and 10, Snowline's pool heating isn't specified, Sossego has no pet policy and no airport transfer, and there's nothing in Jaipur.

## Assumptions

- Fictional catalog: 9 properties across Goa, Udaipur, Manali and Alleppey, 22 room types, rates from 1 Oct 2026 to 31 Mar 2027.
- "This weekend" is Friday to Sunday of the current week (on a Saturday it starts today, on a Sunday it means the coming one). "Next weekend" is the one after. Mira always repeats the actual dates back.
- Budget is the room cost per night for the whole party, before tax.
- Children count as guests for capacity and extra-guest fees; child policies are text only.
- A hold isn't a booking. There's no payment step.

## Known limitations

- The grounding check covers prices, room names and booking claims. A made-up amenity ("yes, it's heated") isn't blocked in code; the prompt and the "unknown" data handle it, and the evals check for it.
- Nothing forces the model to call `update_booking_state`. Tools refuse to run on missing state, and the evals track how often it slips.
- City matching is exact, with no aliases like "Alappuzha" or "North Goa".
- With a flash-tier model results vary between runs: 14 to 16 of 16 eval conversations over nine full runs (latest: 16/16).
- A turn takes about 7 s at the median, since tool calls happen one round-trip at a time. The provider occasionally has a slow call (up to about a minute).
- No auth.

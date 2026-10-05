# Engineering note

The rule behind every decision: **the model handles language, code handles facts.** The LLM understands "me and my 2 friends, something private". Prices, dates, availability and booking rules are deterministic code, tested without a model.

## Architecture

FastAPI, Postgres and a small React console. Each guest message is one turn:

1. Lock the conversation row.
2. Build the prompt: rules, property index, booking state and the last 8 turns.
3. Run a tool-calling loop until the model calls `respond`.
4. Check the reply against what the tools returned.
5. Save the turn and the new state in one transaction.

Tool calls, results, state changes and errors stream to the UI over SSE.

## Model choice

`deepseek-v4.1-flash` on OpenCode Go, behind a small provider interface, so switching model or provider is configuration. I picked a cheap, fast model on purpose: correctness should come from the design, not from the model.

A test call before building found a quirk: DeepSeek rejects naming a specific tool in `tool_choice`. To force a final reply, I offer only the `respond` tool instead, which works on any provider.

## Agent flow and tool calling

One loop with `tool_choice=required`: up to 6 model calls for tools, then reply-only calls. The model records what the guest said with `update_booking_state`, then searches, checks availability, quotes or holds, and ends with `respond(message, next_action)`.

**Tools read trip details from state, not from their arguments.** Search, availability, quote and hold take city, dates and guests from the booking state. If something is missing they return `missing_fields` and Mira asks. That makes "ask or call a tool" a code decision, and the search can never disagree with what was recorded.

Tool errors (bad JSON, wrong arguments, unknown ids) go back to the model as results it can recover from, never as crashes. When the model sends the same call twice in a turn, it gets the earlier result back instead of looping.

## State management

`BookingState` is a Pydantic model stored as JSONB on the conversation. A `turns` table logs every turn's tool calls, state diff, next action and errors.

- The model sends changes as a patch: missing fields stay the same, and guest counts are absolute ("make that 4 people" means adults=4).
- **Dates are described, not computed.** "Next weekend" becomes `{"kind": "weekend", "which": "next"}` and code resolves it against a "today" that can be pinned. Mira always repeats the actual dates back.
- The state also remembers the options last shown, the last quote and the hold, so "the other one" and "yes" have something concrete to refer to.
- Old tool results aren't replayed into the prompt, so it stays the same size however long the chat runs.

## Hallucination prevention

- Every price comes from `domain/pricing.py`: per-night rates, extra-guest fees, GST by slab and add-ons.
- **Unknown is a real answer.** The catalog lists what a property has; anything not listed is unknown, not "no". A missing policy returns `known: false`, and Mira offers to check with the property.
- **Replies are checked before the guest sees them.** A reply is rejected if it has a ₹ amount no tool returned, names a room that was never looked up, or claims a booking without a successful hold. The model gets one retry; after that the guest gets a safe "let me check" message. In one eval run this caught the model computing "₹16,000 more" itself.
- **Holds are safe.** A hold needs the same quote to have been shown in an earlier message, plus a name. It locks the inventory rows, and two guests racing for the last unit can't both get it. Free units = units open minus active holds, so expired holds free the room with no cleanup job.

## Evaluation

- **Tests:** 39 run without the model, covering dates from every weekday, GST slab edges, ranking, the reply check, full turns with a scripted model, and the race for the last room.
- **Evals:** 16 multi-turn conversations against the real model on a freshly seeded database. They score tool selection, state, recommendation, pricing, hallucination and next action. The latest run passed 16/16, and over nine runs the score ranged from 14 to 16.
- **Fixes:** failures were fixed in the system, not the prompt. Repeated lookups now return the earlier result, a forced tool choice the provider rejects is retried, and malformed JSON is echoed back so the model corrects it.

## Tradeoffs

- **One loop instead of a separate extraction step.** Fewer calls and simpler code, but nothing forces the state update. Reading trip details from state, plus the evals, covers most of that.
- **Reply check scope.** It covers prices, room names and booking claims. Amenity claims rely on the prompt and the "unknown" data.
- **No reply streaming.** Reply tokens aren't streamed, which costs some perceived speed, but the guest never sees an unchecked message.
- **Latency.** About 7 s per turn at the median, because tool calls run one round-trip at a time.

## What I'd improve next

- Check amenity claims in the reply as well.
- Cut latency with prompt caching and parallel read-only tool calls.
- Add city aliases ("North Goa", "Alappuzha") and children's ages for pricing.
- Run the evals in CI across several models.
- Back `handoff_to_staff` with a real ticket, and turn holds into bookings with payment links.

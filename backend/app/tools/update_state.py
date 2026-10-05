from app.agent.state import StatePatch, diff, merge
from app.db import repo
from app.tools.base import Tool, ToolContext, error


class UpdateBookingState(Tool):
    name = "update_booking_state"
    description = (
        "Record what the guest just told you (destination, dates, guests, budget, preferences, choices, name). "
        "Call this FIRST whenever the guest's message adds or changes any of these. Only include changed fields. "
        "Returns the resolved state, what changed, and issues you must address with the guest."
    )
    Args = StatePatch

    async def run(self, ctx: ToolContext, patch: StatePatch) -> dict:
        capacity: dict[str, int] = {}
        selected = (
            patch.selected_room_type_id
            if "selected_room_type_id" in patch.model_fields_set
            else ctx.state.selected_room_type_id
        )
        if selected:
            found = await repo.get_room(ctx.session, selected)
            if not found:
                return error("not_found", f"Unknown room_type_id '{selected}'. Use an id from tool results.")
            capacity[selected] = found[0].max_occupancy
            if patch.addon_ids:
                valid = {a.id for a in await repo.addons_for_property(ctx.session, found[1].id)}
                bad = [a for a in patch.addon_ids if a not in valid]
                if bad:
                    return error(
                        "not_found", f"Add-ons {bad} are not offered by {found[1].name}.", valid_addon_ids=sorted(valid)
                    )
        elif patch.addon_ids:
            return error("no_room_selected", "Select a room before adding add-ons.")

        before = ctx.state
        ctx.state, issues = merge(before, patch, ctx.today, await repo.served_cities(ctx.session), capacity)
        return {"state": ctx.state.for_prompt(), "changes": diff(before, ctx.state), "issues": issues}

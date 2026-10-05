from pydantic import BaseModel

from app.db import repo
from app.domain.pricing import addon_quantity
from app.tools.base import Tool, ToolContext, error


class AddonsArgs(BaseModel):
    property_id: str


class GetAddons(Tool):
    name = "get_addons"
    description = (
        "Extras a property offers (transfers, meals, experiences, early check-in, late check-out) with their "
        "cost for this stay. Use once a room is chosen, to suggest one that fits what the guest told you."
    )
    Args = AddonsArgs

    async def run(self, ctx: ToolContext, args: AddonsArgs) -> dict:
        prop = await repo.get_property(ctx.session, args.property_id)
        if not prop:
            return error("not_found", f"Unknown property_id '{args.property_id}'.")
        st = ctx.state
        can_total = st.nights is not None and st.guests is not None
        return {
            "property_name": prop.name,
            "addons": [
                {
                    "addon_id": a.id,
                    "name": a.name,
                    "description": a.description,
                    "price": a.price,
                    "price_unit": a.price_unit,
                    "cost_for_this_stay_before_tax": (
                        a.price * addon_quantity(a.price_unit, st.nights, st.guests) if can_total else None
                    ),
                }
                for a in await repo.addons_for_property(ctx.session, prop.id)
            ],
            "note": "Add-ons are taxed at 18%; calculate_quote gives the exact total. Nothing else is offered.",
        }

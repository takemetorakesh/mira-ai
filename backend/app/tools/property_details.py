from pydantic import BaseModel

from app.db import repo
from app.tools.base import Tool, ToolContext, error


class PropertyDetailsArgs(BaseModel):
    property_id: str


class GetPropertyDetails(Tool):
    name = "get_property_details"
    description = (
        "Everything we know about a property and its room types: descriptions, capacity, amenities and which "
        "policies are on file. Use it for any question about a property or room. Anything not stated here is "
        "unknown, so say so instead of guessing."
    )
    Args = PropertyDetailsArgs

    async def run(self, ctx: ToolContext, args: PropertyDetailsArgs) -> dict:
        prop = await repo.get_property(ctx.session, args.property_id)
        if not prop:
            return error("not_found", f"Unknown property_id '{args.property_id}'. Use an id from the property index.")
        rooms = await repo.rooms_for_property(ctx.session, prop.id)
        return {
            "property_id": prop.id,
            "name": prop.name,
            "city": prop.city,
            "area": prop.area,
            "description": prop.description,
            "amenities": prop.amenities,
            "policies_on_file": await repo.policy_kinds(ctx.session, prop.id),
            "room_types": [
                {
                    "room_type_id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "rate_includes_guests": r.base_occupancy,
                    "max_guests": r.max_occupancy,
                    "extra_guest_fee_per_night": r.extra_guest_fee,
                    "amenities": r.amenities,
                }
                for r in rooms
            ],
            "note": "This is everything we know. Anything not stated (e.g. pool heating) is unknown.",
        }

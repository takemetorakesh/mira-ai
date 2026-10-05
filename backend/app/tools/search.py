from datetime import timedelta

from pydantic import BaseModel, Field

from app.agent.state import ShownOption
from app.db import repo
from app.db.models import Property, RoomType
from app.db.repo import Availability
from app.domain.pricing import RoomPricing
from app.domain.recommend import Candidate, rank, stay_nights
from app.tools.base import Tool, ToolContext, missing_trip_fields

ALT_WINDOW_DAYS = 14


class SearchArgs(BaseModel):
    max_nightly_rate: int | None = Field(
        None,
        description="One-off price ceiling for this search, e.g. when the guest asks for something cheaper. "
        "Defaults to the guest's budget.",
    )


def candidate(room: RoomType, prop: Property, availability: Availability) -> Candidate:
    return Candidate(
        property_id=prop.id,
        property_name=prop.name,
        area=prop.area,
        property_amenities=prop.amenities,
        room_type_id=room.id,
        room_name=room.name,
        room_amenities=room.amenities,
        pricing=RoomPricing(room.base_occupancy, room.max_occupancy, room.extra_guest_fee),
        availability=availability,
    )


class SearchProperties(Tool):
    name = "search_properties"
    description = (
        "Find and rank rooms in the guest's city for their dates, guests, preferences and budget, all read "
        "from booking state. Returns up to 3 options with prices, what matched and what had to be relaxed, "
        "plus matching rooms that are sold out with the nearest available dates."
    )
    Args = SearchArgs

    async def run(self, ctx: ToolContext, args: SearchArgs) -> dict:
        if missing := missing_trip_fields(ctx.state):
            return missing
        st = ctx.state
        rooms = await repo.rooms_in_city(ctx.session, st.city)
        window_start = max(ctx.today, st.check_in - timedelta(days=ALT_WINDOW_DAYS))
        avail = await repo.availability(
            ctx.session,
            [r.id for r, _ in rooms],
            window_start,
            st.check_out + timedelta(days=ALT_WINDOW_DAYS),
            own_conversation=ctx.conversation_id,
        )
        budget = args.max_nightly_rate or st.budget_per_night

        result = rank(
            [candidate(r, p, avail[r.id]) for r, p in rooms],
            stay_nights(st.check_in, st.check_out),
            guests=st.guests,
            rooms=st.rooms,
            preferences=[str(p) for p in st.preferences],
            budget_per_night=budget,
            budget_is_firm=args.max_nightly_rate is not None,
        )
        st.shown_options = [ShownOption.model_validate(o) for o in result["options"]]
        return {
            "searched": {
                "city": st.city,
                "check_in": st.check_in.isoformat(),
                "check_out": st.check_out.isoformat(),
                "nights": st.nights,
                "guests": st.guests,
                "rooms": st.rooms,
                "preferences": [str(p) for p in st.preferences],
                "budget_per_night": budget,
            },
            **result,
            "note": "stay_total_with_tax covers the rooms only, no add-ons. Use calculate_quote for a final price.",
        }

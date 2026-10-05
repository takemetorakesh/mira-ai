from datetime import timedelta

from pydantic import BaseModel

from app.db import repo
from app.domain.pricing import rooms_needed
from app.domain.recommend import blocked_nights, next_available_check_in, stay_nights
from app.tools.base import Tool, ToolContext, error
from app.tools.search import ALT_WINDOW_DAYS, candidate


class AvailabilityArgs(BaseModel):
    room_type_id: str


class CheckAvailability(Tool):
    name = "check_availability"
    description = (
        "Check night-by-night availability and rates of one room type for the dates and guests in booking state. "
        "Use when the guest asks about a specific room, or after dates/guests change for a room already chosen."
    )
    Args = AvailabilityArgs

    async def run(self, ctx: ToolContext, args: AvailabilityArgs) -> dict:
        st = ctx.state
        if st.check_in is None or st.check_out is None:
            return error("missing_fields", "Ask the guest for their dates first.", fields=["check_in", "check_out"])
        found = await repo.get_room(ctx.session, args.room_type_id)
        if not found:
            return error(
                "not_found",
                f"Unknown room_type_id '{args.room_type_id}'.",
                valid_ids=await repo.all_room_ids(ctx.session),
            )
        room, prop = found

        guests = st.guests or room.base_occupancy
        rooms = max(st.rooms, rooms_needed(guests, room.max_occupancy))
        start = max(ctx.today, st.check_in - timedelta(days=ALT_WINDOW_DAYS))
        end = st.check_out + timedelta(days=ALT_WINDOW_DAYS)
        avail = (await repo.availability(ctx.session, [room.id], start, end, own_conversation=ctx.conversation_id))[
            room.id
        ]
        c = candidate(room, prop, avail)
        nights = stay_nights(st.check_in, st.check_out)
        blocked = blocked_nights(c, nights, rooms)
        return {
            "room_type_id": room.id,
            "room_name": room.name,
            "property_name": prop.name,
            "check_in": st.check_in.isoformat(),
            "check_out": st.check_out.isoformat(),
            "rooms_required": rooms,
            "rooms_required_reason": None
            if rooms == st.rooms
            else f"{guests} guests exceed {room.max_occupancy} per room",
            "nights": [
                {"date": n.isoformat(), "rate_per_room": avail[n][0], "rooms_available": max(avail[n][1], 0)}
                if n in avail
                else {"date": n.isoformat(), "not_on_sale": True}
                for n in nights
            ],
            "available": not blocked,
            "unavailable_nights": blocked,
            "next_available_check_in": next_available_check_in(c, len(nights), rooms, st.check_in) if blocked else None,
        }

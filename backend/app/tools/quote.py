import uuid
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state import BookingState, QuoteRef
from app.db import repo
from app.db.models import Property, RoomType
from app.domain.pricing import AddonPricing, OverCapacity, PricingError, RoomPricing, quote
from app.domain.recommend import blocked_nights, stay_nights
from app.tools.base import Tool, ToolContext, error, missing_trip_fields
from app.tools.search import candidate


class QuoteArgs(BaseModel):
    room_type_id: str
    addon_ids: list[str] = Field(default_factory=list, description="Add-on ids to include, from get_addons.")


@dataclass
class PricedStay:
    quote: dict
    room: RoomType
    property: Property


async def price_stay(
    s: AsyncSession,
    st: BookingState,
    room_type_id: str,
    addon_ids: list[str],
    conversation_id: uuid.UUID,
) -> PricedStay | dict:
    """Price the stay in `st` for one room type. Returns a tool error dict if it can't be priced."""
    if missing := missing_trip_fields(st):
        return missing
    found = await repo.get_room(s, room_type_id)
    if not found:
        return error("not_found", f"Unknown room_type_id '{room_type_id}'.", valid_ids=await repo.all_room_ids(s))
    room, prop = found

    offered = {a.id: a for a in await repo.addons_for_property(s, prop.id)}
    unknown = [a for a in addon_ids if a not in offered]
    if unknown:
        return error("not_found", f"{prop.name} doesn't offer {unknown}.", valid_addon_ids=sorted(offered))

    avail = await repo.availability(s, [room.id], st.check_in, st.check_out, own_conversation=conversation_id)
    nights = stay_nights(st.check_in, st.check_out)
    blocked = blocked_nights(candidate(room, prop, avail[room.id]), nights, st.rooms)
    if blocked:
        return error(
            "unavailable",
            f"{room.name} isn't available for {st.rooms} room(s) on {', '.join(blocked)}.",
            unavailable_nights=blocked,
        )

    try:
        q = quote(
            RoomPricing(room.base_occupancy, room.max_occupancy, room.extra_guest_fee),
            [(n, avail[room.id][n][0]) for n in nights],
            guests=st.guests,
            rooms=st.rooms,
            addons=[AddonPricing(a.id, a.name, a.price, a.price_unit) for a in map(offered.get, addon_ids)],
        )
    except OverCapacity as e:
        return error("over_capacity", str(e), max_guests_per_room=room.max_occupancy, rooms_needed=e.rooms_needed)
    except PricingError as e:
        return error("invalid_party", str(e))
    return PricedStay(q, room, prop)


class CalculateQuote(Tool):
    name = "calculate_quote"
    description = (
        "Exact price for a room (plus optional add-ons) for the dates, guests and rooms in booking state: "
        "nightly breakdown, taxes and total. The only source of final prices, and required before a hold."
    )
    Args = QuoteArgs

    async def run(self, ctx: ToolContext, args: QuoteArgs) -> dict:
        priced = await price_stay(ctx.session, ctx.state, args.room_type_id, args.addon_ids, ctx.conversation_id)
        if isinstance(priced, dict):
            return priced

        st = ctx.state
        st.last_quote = QuoteRef(
            room_type_id=priced.room.id,
            addon_ids=sorted(args.addon_ids),
            check_in=st.check_in,
            check_out=st.check_out,
            guests=st.guests,
            rooms=st.rooms,
            total=priced.quote["total"],
            turn_seq=ctx.turn_seq,
        )
        return {
            "room_type_id": priced.room.id,
            "room_name": priced.room.name,
            "property_name": priced.property.name,
            "check_in": st.check_in.isoformat(),
            "check_out": st.check_out.isoformat(),
            "guests": st.guests,
            **priced.quote,
        }

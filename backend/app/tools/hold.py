from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.agent.state import HoldRef
from app.db import repo
from app.db.models import BookingHold
from app.tools.base import Tool, ToolContext, error
from app.tools.quote import QuoteArgs, price_stay


class CreateBookingHold(Tool):
    name = "create_booking_hold"
    description = (
        "Hold the room for the guest for a limited time at the quoted price. Only after the guest has seen the "
        "calculate_quote total in an earlier message, clearly said yes, and their name is recorded. "
        "Use the same room_type_id and addon_ids as that quote."
    )
    Args = QuoteArgs

    async def run(self, ctx: ToolContext, args: QuoteArgs) -> dict:
        st = ctx.state
        if not st.guest_name:
            return error("missing_fields", "Ask for the name to put the hold under.", fields=["guest_name"])

        q = st.last_quote
        quoted_this = q is not None and (
            (q.room_type_id, q.addon_ids) == (args.room_type_id, sorted(args.addon_ids))
            and (q.check_in, q.check_out, q.guests, q.rooms) == (st.check_in, st.check_out, st.guests, st.rooms)
        )
        if not quoted_this:
            return error(
                "quote_required",
                "Quote exactly this room, add-ons, dates and guests with calculate_quote first, "
                "show the guest the total and wait for them to confirm.",
            )
        if q.turn_seq >= ctx.turn_seq:
            return error(
                "confirmation_required", "The guest hasn't seen this price yet. Show it and ask them to confirm."
            )

        # Own transaction so the hold commits, and its row locks are released, right away
        # rather than when the turn finishes.
        async with ctx.sessionmaker() as s, s.begin():
            await repo.lock_inventory(s, args.room_type_id, st.check_in, st.check_out)
            priced = await price_stay(s, st, args.room_type_id, args.addon_ids, ctx.conversation_id)
            if isinstance(priced, dict):
                return priced
            if priced.quote["total"] != q.total:
                return error(
                    "price_changed",
                    "The price changed since it was quoted. Re-quote and confirm with the guest.",
                    new_total=priced.quote["total"],
                    quoted_total=q.total,
                )

            await s.execute(
                update(BookingHold)
                .where(BookingHold.conversation_id == ctx.conversation_id, BookingHold.status == "held")
                .values(status="released")
            )
            hold = BookingHold(
                conversation_id=ctx.conversation_id,
                room_type_id=args.room_type_id,
                check_in=st.check_in,
                check_out=st.check_out,
                rooms=st.rooms,
                guest_name=st.guest_name,
                quote=priced.quote
                | {"room_name": priced.room.name, "property_name": priced.property.name, "guests": st.guests},
                status="held",
                expires_at=datetime.now(UTC) + timedelta(minutes=ctx.settings.hold_ttl_minutes),
            )
            s.add(hold)

        st.hold = HoldRef(id=str(hold.id), room_type_id=hold.room_type_id, total=q.total, expires_at=hold.expires_at)
        st.selected_room_type_id = args.room_type_id
        st.addon_ids = sorted(args.addon_ids)
        return {
            "hold_reference": str(hold.id)[:8].upper(),
            "guest_name": hold.guest_name,
            "room_name": priced.room.name,
            "property_name": priced.property.name,
            "check_in": st.check_in.isoformat(),
            "check_out": st.check_out.isoformat(),
            "rooms": st.rooms,
            "total": q.total,
            "hold_minutes": ctx.settings.hold_ttl_minutes,
            "expires_at": hold.expires_at.isoformat(),
            "note": "A hold, not a confirmed booking. It's confirmed per the property's payment policy.",
        }

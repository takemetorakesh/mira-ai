"""Catalog and inventory queries."""

import uuid
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Addon, Policy, Property, RoomType

AVAILABILITY_SQL = text(
    """
    SELECT i.room_type_id, i.stay_date, i.rate,
           i.units_open - COALESCE(SUM(h.rooms), 0) AS available
    FROM room_inventory i
    LEFT JOIN booking_holds h
           ON h.room_type_id = i.room_type_id
          AND h.status = 'held' AND h.expires_at > now()
          AND h.check_in <= i.stay_date AND h.check_out > i.stay_date
          AND h.conversation_id IS DISTINCT FROM :own_conversation
    WHERE i.room_type_id = ANY(:ids) AND i.stay_date >= :start AND i.stay_date < :end
    GROUP BY i.room_type_id, i.stay_date, i.rate, i.units_open
    """
)

LOCK_INVENTORY_SQL = text(
    "SELECT 1 FROM room_inventory WHERE room_type_id = :id AND stay_date >= :start AND stay_date < :end FOR UPDATE"
)


async def served_cities(s: AsyncSession) -> list[str]:
    return list((await s.scalars(select(Property.city).distinct().order_by(Property.city))).all())


async def get_room(s: AsyncSession, room_type_id: str) -> tuple[RoomType, Property] | None:
    row = (await s.execute(select(RoomType, Property).join(Property).where(RoomType.id == room_type_id))).first()
    return (row[0], row[1]) if row else None


async def rooms_in_city(s: AsyncSession, city: str) -> list[tuple[RoomType, Property]]:
    rows = await s.execute(select(RoomType, Property).join(Property).where(Property.city == city).order_by(RoomType.id))
    return [(r, p) for r, p in rows.all()]


async def rooms_for_property(s: AsyncSession, property_id: str) -> list[RoomType]:
    return list(
        (await s.scalars(select(RoomType).where(RoomType.property_id == property_id).order_by(RoomType.id))).all()
    )


async def property_index(s: AsyncSession) -> list[Property]:
    return list((await s.scalars(select(Property).order_by(Property.city, Property.id))).all())


async def all_room_ids(s: AsyncSession) -> list[str]:
    return list((await s.scalars(select(RoomType.id).order_by(RoomType.id))).all())


async def get_property(s: AsyncSession, property_id: str) -> Property | None:
    return await s.get(Property, property_id)


Availability = dict[date, tuple[int, int]]  # night -> (rate, units available)


async def availability(
    s: AsyncSession,
    room_type_ids: list[str],
    start: date,
    end: date,
    own_conversation: uuid.UUID | None = None,
) -> dict[str, Availability]:
    """Rates and free units per night in [start, end), net of active holds.

    Holds belonging to `own_conversation` are not subtracted, so a guest re-quoting or
    re-holding never competes with their own hold.
    """
    params = {"ids": room_type_ids, "start": start, "end": end, "own_conversation": own_conversation}
    result: dict[str, Availability] = {rid: {} for rid in room_type_ids}
    for rid, night, rate, available in (await s.execute(AVAILABILITY_SQL, params)).all():
        result[rid][night] = (rate, available)
    return result


async def lock_inventory(s: AsyncSession, room_type_id: str, start: date, end: date) -> None:
    """Row-lock the nights being held so two holds on the same room are serialized."""
    await s.execute(LOCK_INVENTORY_SQL, {"id": room_type_id, "start": start, "end": end})


async def get_policy(s: AsyncSession, property_id: str, kind: str) -> str | None:
    p = await s.get(Policy, (property_id, kind))
    return p.details if p else None


async def policy_kinds(s: AsyncSession, property_id: str) -> list[str]:
    return list(
        (await s.scalars(select(Policy.kind).where(Policy.property_id == property_id).order_by(Policy.kind))).all()
    )


async def addons_for_property(s: AsyncSession, property_id: str) -> list[Addon]:
    return list((await s.scalars(select(Addon).where(Addon.property_id == property_id).order_by(Addon.id))).all())


async def room_names(s: AsyncSession) -> list[str]:
    return sorted(set((await s.scalars(select(RoomType.name))).all()))

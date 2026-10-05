"""Schema. Rule: columns hold what we query or constrain; JSONB holds only documents we display.
Money is integer rupees. Catalog ids are readable text because the LLM passes them in tool calls."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text, index=True)
    area: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    amenities: Mapped[list[str]] = mapped_column(ARRAY(Text))


class RoomType(Base):
    __tablename__ = "room_types"
    __table_args__ = (
        CheckConstraint("base_occupancy >= 1 AND base_occupancy <= max_occupancy", name="occupancy_range"),
        CheckConstraint("extra_guest_fee >= 0", name="extra_guest_fee_non_negative"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    base_occupancy: Mapped[int] = mapped_column(Integer)
    max_occupancy: Mapped[int] = mapped_column(Integer)
    extra_guest_fee: Mapped[int] = mapped_column(Integer)
    amenities: Mapped[list[str]] = mapped_column(ARRAY(Text))


class RoomInventory(Base):
    """One row per room type per night. No row = not open for sale."""

    __tablename__ = "room_inventory"
    __table_args__ = (
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("units_open >= 0", name="units_open_non_negative"),
    )

    room_type_id: Mapped[str] = mapped_column(ForeignKey("room_types.id"), primary_key=True)
    stay_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[int] = mapped_column(Integer)
    units_open: Mapped[int] = mapped_column(Integer)


POLICY_KINDS = ("cancellation", "check_in_out", "children", "pets", "smoking", "payment")


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (CheckConstraint(f"kind IN {POLICY_KINDS}", name="policy_kind"),)

    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    details: Mapped[str] = mapped_column(Text)


PRICE_UNITS = ("per_booking", "per_night", "per_guest", "per_guest_per_night")


class Addon(Base):
    __tablename__ = "addons"
    __table_args__ = (
        CheckConstraint(f"price_unit IN {PRICE_UNITS}", name="addon_price_unit"),
        CheckConstraint("price > 0", name="addon_price_positive"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[int] = mapped_column(Integer)
    price_unit: Mapped[str] = mapped_column(String)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state: Mapped[dict] = mapped_column(JSONB)


class Turn(Base):
    __tablename__ = "turns"

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_message: Mapped[str] = mapped_column(Text)
    reply: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list] = mapped_column(JSONB)
    state_diff: Mapped[list] = mapped_column(JSONB)
    next_action: Mapped[str] = mapped_column(String)
    errors: Mapped[list] = mapped_column(JSONB)


class BookingHold(Base):
    """Active = status 'held' and not expired. Expired holds free inventory without a sweeper."""

    __tablename__ = "booking_holds"
    __table_args__ = (
        CheckConstraint("status IN ('held', 'released')", name="hold_status"),
        CheckConstraint("check_out > check_in", name="hold_dates"),
        CheckConstraint("rooms >= 1", name="hold_rooms"),
        Index(
            "ix_active_holds",
            "room_type_id",
            "check_in",
            "check_out",
            postgresql_where=text("status = 'held'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    room_type_id: Mapped[str] = mapped_column(ForeignKey("room_types.id"))
    check_in: Mapped[date] = mapped_column(Date)
    check_out: Mapped[date] = mapped_column(Date)
    rooms: Mapped[int] = mapped_column(Integer)
    guest_name: Mapped[str] = mapped_column(Text)
    quote: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

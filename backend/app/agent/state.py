"""Conversation state: the agent's memory between turns.

The model writes guest-provided fields through `update_booking_state` (a StatePatch). Tools own the
derived fields (resolved dates, shown options, last quote, hold). Prior tool results are not replayed
into the prompt; this state is what carries context forward.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.domain.amenities import Amenity
from app.domain.dates import DateResolutionError, DateSpec, resolve
from app.domain.pricing import rooms_needed

MAX_NIGHTS = 30
QUOTE_INPUTS = ("check_in", "check_out", "adults", "children", "rooms", "selected_room_type_id", "addon_ids")


class ShownOption(BaseModel):
    room_type_id: str
    room_name: str
    property_name: str
    rooms: int
    avg_room_cost_per_night: int


class QuoteRef(BaseModel):
    room_type_id: str
    addon_ids: list[str]
    check_in: date
    check_out: date
    guests: int
    rooms: int
    total: int
    turn_seq: int  # the turn the guest was shown this price


class HoldRef(BaseModel):
    id: str
    room_type_id: str
    total: int
    expires_at: datetime


class BookingState(BaseModel):
    # Guest-provided (writable by the model via StatePatch)
    city: str | None = None
    check_in: date | None = None
    check_out: date | None = None
    adults: int | None = None
    children: int = 0
    rooms: int = 1
    budget_per_night: int | None = None
    preferences: list[Amenity] = []
    special_requests: list[str] = []
    selected_room_type_id: str | None = None
    addon_ids: list[str] = []
    guest_name: str | None = None
    # Tool-owned
    shown_options: list[ShownOption] = []
    last_quote: QuoteRef | None = None
    hold: HoldRef | None = None

    @property
    def nights(self) -> int | None:
        if self.check_in and self.check_out:
            return (self.check_out - self.check_in).days
        return None

    @property
    def guests(self) -> int | None:
        return None if self.adults is None else self.adults + self.children

    def missing_for_search(self) -> list[str]:
        return [
            f
            for f, v in (
                ("city", self.city),
                ("check_in", self.check_in),
                ("check_out", self.check_out),
                ("adults", self.adults),
            )
            if v is None
        ]

    def for_prompt(self) -> dict:
        stay = None
        if self.check_in and self.check_out:
            stay = f"{self.check_in:%a %-d %b %Y} → {self.check_out:%a %-d %b %Y}"
        return self.model_dump(mode="json") | {"nights": self.nights, "guests": self.guests, "stay": stay}


class StatePatch(BaseModel):
    """Only include fields the guest just provided or changed. Omitted = unchanged, null = clear.
    Lists replace the whole current list. Guest counts are absolute ('make that 4 people' → adults=4)."""

    city: str | None = Field(None, description="Destination city as the guest said it.")
    dates: DateSpec | None = Field(None, description="What the guest said about dates. Never compute dates yourself.")
    adults: int | None = Field(None, ge=1, le=20)
    children: int | None = Field(None, ge=0, le=10)
    rooms: int | None = Field(None, ge=1, le=10, description="Only when the guest asks for a number of rooms.")
    budget_per_night: int | None = Field(
        None, ge=500, description="Rupees per night for the stay's rooms, before tax. '20k' → 20000."
    )
    preferences: list[Amenity] | None = Field(
        None, description="Amenities the guest wants. 'private' → standalone_unit; 'private pool' → private_pool."
    )
    special_requests: list[str] | None = Field(
        None, description="Occasions or needs, e.g. 'anniversary', 'arriving by flight', 'early arrival'."
    )
    selected_room_type_id: str | None = Field(None, description="Room type the guest chose, by id from tool results.")
    addon_ids: list[str] | None = Field(None, description="Add-on ids the guest wants, from get_addons.")
    guest_name: str | None = Field(None, description="Name for the booking hold.")


def merge(
    state: BookingState, patch: StatePatch, today: date, served_cities: list[str], room_capacity: dict[str, int]
) -> tuple[BookingState, list[dict]]:
    """Apply a patch. Returns the new state and issues (things the agent must tell or ask the guest).
    `room_capacity` maps room_type_id → max_occupancy for the selected room (validated by the caller)."""
    new = state.model_copy(deep=True)
    issues: list[dict] = []
    given = patch.model_fields_set

    for f in (
        "adults",
        "children",
        "rooms",
        "budget_per_night",
        "preferences",
        "special_requests",
        "selected_room_type_id",
        "addon_ids",
        "guest_name",
    ):
        if f in given:
            value = getattr(patch, f)
            if value is None and f in ("children", "rooms", "preferences", "special_requests", "addon_ids"):
                value = BookingState.model_fields[f].default
            setattr(new, f, value)

    if "city" in given:
        if patch.city is None:
            new.city = None
        else:
            match = next((c for c in served_cities if c.lower() == patch.city.strip().lower()), None)
            if match:
                new.city = match
            else:
                issues.append({"code": "city_not_served", "requested": patch.city, "served_cities": served_cities})

    if "dates" in given:
        if patch.dates is None:
            new.check_in = new.check_out = None
        else:
            try:
                check_in, check_out, notes = resolve(patch.dates, today, state.check_in, state.check_out)
                issues += [{"code": "date_interpretation", "message": n} for n in notes]
                if check_in and check_in < today:
                    issues.append(
                        {"code": "date_in_past", "check_in": check_in.isoformat(), "today": today.isoformat()}
                    )
                elif check_in and check_out and check_out <= check_in:
                    issues.append(
                        {
                            "code": "check_out_not_after_check_in",
                            "check_in": check_in.isoformat(),
                            "check_out": check_out.isoformat(),
                        }
                    )
                elif check_in and check_out and (check_out - check_in).days > MAX_NIGHTS:
                    issues.append({"code": "stay_too_long", "max_nights": MAX_NIGHTS})
                else:
                    new.check_in, new.check_out = check_in, check_out
            except DateResolutionError as e:
                issues.append({"code": "date_unresolved", "message": str(e)})

    if new.guests is not None and new.rooms > new.guests:
        issues.append({"code": "more_rooms_than_guests", "rooms": new.rooms, "guests": new.guests})
        new.rooms = state.rooms if state.rooms <= new.guests else 1

    if new.selected_room_type_id and new.guests is not None:
        cap = room_capacity.get(new.selected_room_type_id)
        if cap is not None and -(-new.guests // new.rooms) > cap:
            issues.append(
                {
                    "code": "over_capacity",
                    "room_type_id": new.selected_room_type_id,
                    "max_guests_per_room": cap,
                    "guests": new.guests,
                    "rooms": new.rooms,
                    "rooms_needed": rooms_needed(new.guests, cap),
                }
            )

    # A quote or option list is only valid for the inputs it was computed with.
    if new.last_quote and any(getattr(new, f) != getattr(state, f) for f in QUOTE_INPUTS):
        new.last_quote = None
    if any(
        getattr(new, f) != getattr(state, f) for f in ("city", "check_in", "check_out", "adults", "children", "rooms")
    ):
        new.shown_options = []
    return new, issues


def diff(before: BookingState, after: BookingState) -> list[dict]:
    a, b = before.for_prompt(), after.for_prompt()
    return [{"field": k, "from": a.get(k), "to": b.get(k)} for k in b if a.get(k) != b.get(k)]

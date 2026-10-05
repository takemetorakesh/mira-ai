"""Stay pricing. Every amount the guest is quoted comes from here.

- Rates are per room per night at base occupancy; each guest above base occupancy in a room adds
  that room type's extra_guest_fee per night.
- Guests are spread as evenly as possible across rooms.
- GST on rooms is charged per room-night on the actual tariff (post Sept-2025 slabs):
  ≤ ₹1,000 → 0%, ≤ ₹7,500 → 5%, above → 18%. Add-ons are taxed at 18% (assumption).
- Amounts are integer rupees; tax is rounded half-up per line.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date

ADDON_GST_PERCENT = 18


class PricingError(ValueError):
    pass


class OverCapacity(PricingError):
    def __init__(self, guests_in_room: int, max_occupancy: int, rooms_needed: int):
        super().__init__(
            f"{guests_in_room} guests in one room exceeds the maximum of {max_occupancy}; "
            f"needs at least {rooms_needed} rooms."
        )
        self.rooms_needed = rooms_needed


@dataclass(frozen=True)
class RoomPricing:
    base_occupancy: int
    max_occupancy: int
    extra_guest_fee: int


@dataclass(frozen=True)
class AddonPricing:
    id: str
    name: str
    price: int
    price_unit: str  # per_booking | per_night | per_guest | per_guest_per_night


def room_gst_percent(tariff: int) -> int:
    if tariff <= 1000:
        return 0
    if tariff <= 7500:
        return 5
    return 18


def split_guests(guests: int, rooms: int) -> list[int]:
    if rooms < 1 or guests < 1:
        raise PricingError("Need at least one guest and one room.")
    if rooms > guests:
        raise PricingError(f"{rooms} rooms for {guests} guests would leave a room empty.")
    return [guests // rooms + (1 if i < guests % rooms else 0) for i in range(rooms)]


def rooms_needed(guests: int, max_occupancy: int) -> int:
    return -(-guests // max_occupancy)


def _tax(amount: int, percent: int) -> int:
    return (amount * percent + 50) // 100


def addon_quantity(unit: str, nights: int, guests: int) -> int:
    return {"per_booking": 1, "per_night": nights, "per_guest": guests, "per_guest_per_night": guests * nights}[unit]


def quote(
    room: RoomPricing,
    nightly_rates: list[tuple[date, int]],
    guests: int,
    rooms: int,
    addons: Sequence[AddonPricing] = (),
) -> dict:
    if not nightly_rates:
        raise PricingError("No nights to price.")
    occupancy = split_guests(guests, rooms)
    if max(occupancy) > room.max_occupancy:
        raise OverCapacity(max(occupancy), room.max_occupancy, rooms_needed(guests, room.max_occupancy))

    nights = []
    for night, rate in nightly_rates:
        subtotal = tax = extra = 0
        for in_room in occupancy:
            extra_charge = room.extra_guest_fee * max(0, in_room - room.base_occupancy)
            tariff = rate + extra_charge
            subtotal += tariff
            extra += extra_charge
            tax += _tax(tariff, room_gst_percent(tariff))
        nights.append(
            {
                "date": night.isoformat(),
                "rate_per_room": rate,
                "extra_guest_charges": extra,
                "subtotal": subtotal,
                "tax": tax,
            }
        )

    n_nights = len(nightly_rates)
    addon_lines = []
    for a in addons:
        qty = addon_quantity(a.price_unit, n_nights, guests)
        subtotal = a.price * qty
        addon_lines.append(
            asdict(a) | {"quantity": qty, "subtotal": subtotal, "tax": _tax(subtotal, ADDON_GST_PERCENT)}
        )

    room_subtotal = sum(n["subtotal"] for n in nights)
    room_tax = sum(n["tax"] for n in nights)
    addon_subtotal = sum(a["subtotal"] for a in addon_lines)
    addon_tax = sum(a["tax"] for a in addon_lines)
    return {
        "nights": nights,
        "rooms": rooms,
        "guests_per_room": occupancy,
        "room_subtotal": room_subtotal,
        "room_tax": room_tax,
        "avg_room_cost_per_night": room_subtotal // n_nights,
        "addons": addon_lines,
        "addon_subtotal": addon_subtotal,
        "addon_tax": addon_tax,
        "total_before_tax": room_subtotal + addon_subtotal,
        "total_tax": room_tax + addon_tax,
        "total": room_subtotal + room_tax + addon_subtotal + addon_tax,
    }

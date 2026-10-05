"""Room recommendation over data already loaded from the DB (no I/O here, so it's easy to test).

Exact matches (capacity, availability, preferences, budget) are ranked cheapest first. If there
are none, options are ranked by what had to give: budget first, then preferences, then splitting
the party into more rooms. When the guest has explicitly asked for something cheaper, budget is
relaxed last instead. Each option lists what was relaxed so the agent can say so.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.domain.pricing import RoomPricing, quote, rooms_needed

RELAX_COST = {"budget": 1, "preferences": 2, "rooms": 3}
# When the guest explicitly asks for something cheaper, price becomes the firm constraint.
FIRM_BUDGET_RELAX_COST = {"preferences": 1, "rooms": 2, "budget": 3}
MAX_OPTIONS = 3


@dataclass
class Candidate:
    property_id: str
    property_name: str
    area: str
    property_amenities: list[str]
    room_type_id: str
    room_name: str
    room_amenities: list[str]
    pricing: RoomPricing
    # stay_date -> (rate, available units net of active holds); missing date = not on sale
    availability: dict[date, tuple[int, int]] = field(default_factory=dict)


def stay_nights(check_in: date, check_out: date) -> list[date]:
    return [check_in + timedelta(days=i) for i in range((check_out - check_in).days)]


def blocked_nights(c: Candidate, nights: list[date], rooms: int) -> list[str]:
    return [n.isoformat() for n in nights if n not in c.availability or c.availability[n][1] < rooms]


def rank(
    candidates: list[Candidate],
    nights: list[date],
    guests: int,
    rooms: int,
    preferences: list[str],
    budget_per_night: int | None,
    budget_is_firm: bool = False,
) -> dict:
    available, sold_out = [], []
    for c in candidates:
        rooms_for_c = max(rooms, rooms_needed(guests, c.pricing.max_occupancy))
        amenities = set(c.room_amenities) | set(c.property_amenities)
        matched = [p for p in preferences if p in amenities]
        unmet = [p for p in preferences if p not in amenities]
        blocked = blocked_nights(c, nights, rooms_for_c)
        if blocked:
            if not unmet:
                sold_out.append((c, rooms_for_c, blocked))
            continue

        q = quote(c.pricing, [(n, c.availability[n][0]) for n in nights], guests, rooms_for_c)
        within_budget = budget_per_night is None or q["avg_room_cost_per_night"] <= budget_per_night
        relaxed = []
        if not within_budget:
            relaxed.append("budget")
        if unmet:
            relaxed.append("preferences")
        if rooms_for_c > rooms:
            relaxed.append("rooms")
        available.append(
            {
                "property_id": c.property_id,
                "property_name": c.property_name,
                "area": c.area,
                "room_type_id": c.room_type_id,
                "room_name": c.room_name,
                "rooms": rooms_for_c,
                "max_guests_per_room": c.pricing.max_occupancy,
                "matched_preferences": matched,
                "unmet_preferences": unmet,
                "relaxed": relaxed,
                "avg_room_cost_per_night": q["avg_room_cost_per_night"],
                "within_budget": within_budget,
                "stay_total_with_tax": q["total"],
            }
        )

    exact = sorted((o for o in available if not o["relaxed"]), key=lambda o: o["avg_room_cost_per_night"])
    if exact:
        match, options = "exact", exact[:MAX_OPTIONS]
    else:
        cost = FIRM_BUDGET_RELAX_COST if budget_is_firm else RELAX_COST

        def how_far_off(o: dict) -> tuple:
            return sum(cost[r] for r in o["relaxed"]), -len(o["matched_preferences"]), o["avg_room_cost_per_night"]

        options = sorted(available, key=how_far_off)[:MAX_OPTIONS]
        match = "relaxed" if options else "none"

    return {
        "match": match,
        "options": options,
        "sold_out_matches": [
            {
                "property_id": c.property_id,
                "property_name": c.property_name,
                "room_type_id": c.room_type_id,
                "room_name": c.room_name,
                "unavailable_nights": blocked,
                "next_available_check_in": next_available_check_in(c, len(nights), rooms_for_c, nights[0]),
            }
            for c, rooms_for_c, blocked in sold_out[:MAX_OPTIONS]
        ],
    }


def next_available_check_in(c: Candidate, n_nights: int, rooms: int, around: date, search_days: int = 14) -> str | None:
    """Nearest check-in date (later first, then earlier) where the same-length stay is fully available.
    Only looks at dates present in c.availability, so the caller decides how wide a window to load."""
    for offset in range(1, search_days + 1):
        for start in (around + timedelta(days=offset), around - timedelta(days=offset)):
            if not blocked_nights(c, stay_nights(start, start + timedelta(days=n_nights)), rooms):
                return start.isoformat()
    return None

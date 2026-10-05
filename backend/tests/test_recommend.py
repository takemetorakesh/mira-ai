from datetime import date

from app.domain.pricing import RoomPricing
from app.domain.recommend import Candidate, rank, stay_nights

NIGHTS = stay_nights(date(2026, 10, 16), date(2026, 10, 18))


def cand(room_id, rate, max_occ=3, units=2, amenities=(), blocked=()):
    return Candidate(
        property_id="p",
        property_name="P",
        area="A",
        property_amenities=["wifi"],
        room_type_id=room_id,
        room_name=room_id,
        room_amenities=list(amenities),
        pricing=RoomPricing(2, max_occ, 1000),
        availability={
            n: (rate, 0 if n.isoformat() in blocked else units)
            for n in stay_nights(date(2026, 10, 10), date(2026, 10, 31))
        },
    )


def test_exact_matches_cheapest_first():
    r = rank(
        [cand("b", 15000, amenities=["private_pool"]), cand("a", 12000, amenities=["private_pool"]), cand("c", 5000)],
        NIGHTS,
        guests=2,
        rooms=1,
        preferences=["private_pool"],
        budget_per_night=20000,
    )
    assert r["match"] == "exact"
    assert [o["room_type_id"] for o in r["options"]] == ["a", "b"]


def test_relax_budget_before_preferences():
    r = rank(
        [cand("pool", 25000, amenities=["private_pool"]), cand("plain", 8000)],
        NIGHTS,
        guests=2,
        rooms=1,
        preferences=["private_pool"],
        budget_per_night=20000,
    )
    assert r["match"] == "relaxed"
    assert r["options"][0]["room_type_id"] == "pool"
    assert r["options"][0]["relaxed"] == ["budget"]


def test_split_into_rooms_when_no_room_fits():
    r = rank(
        [cand("double", 6000, max_occ=2, units=5)], NIGHTS, guests=5, rooms=1, preferences=[], budget_per_night=None
    )
    assert r["options"][0]["rooms"] == 3
    assert r["options"][0]["relaxed"] == ["rooms"]


def test_bigger_room_preferred_over_split():
    r = rank(
        [cand("double", 6000, max_occ=2, units=5), cand("suite", 14000, max_occ=5)],
        NIGHTS,
        guests=5,
        rooms=1,
        preferences=[],
        budget_per_night=None,
    )
    assert r["match"] == "exact"
    assert r["options"][0]["room_type_id"] == "suite"


def test_sold_out_match_reports_next_window():
    r = rank(
        [cand("villa", 13000, amenities=["private_pool"], blocked=("2026-10-16", "2026-10-17"))],
        NIGHTS,
        guests=2,
        rooms=1,
        preferences=["private_pool"],
        budget_per_night=None,
    )
    assert r["match"] == "none"
    so = r["sold_out_matches"][0]
    assert so["unavailable_nights"] == ["2026-10-16", "2026-10-17"]
    assert so["next_available_check_in"] == "2026-10-18"


def test_firm_budget_relaxes_preferences_first():
    cands = [cand("pool", 12000, amenities=["private_pool"]), cand("plain", 6000)]
    soft = rank(cands, NIGHTS, guests=2, rooms=1, preferences=["private_pool"], budget_per_night=10000)
    firm = rank(
        cands, NIGHTS, guests=2, rooms=1, preferences=["private_pool"], budget_per_night=10000, budget_is_firm=True
    )
    assert soft["options"][0]["room_type_id"] == "pool"
    assert firm["options"][0]["room_type_id"] == "plain"

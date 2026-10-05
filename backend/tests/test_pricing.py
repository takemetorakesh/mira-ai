from datetime import date

import pytest

from app.domain.pricing import AddonPricing, PricingError, RoomPricing, quote, room_gst_percent, split_guests

VILLA = RoomPricing(base_occupancy=2, max_occupancy=3, extra_guest_fee=2500)
NIGHTS = [(date(2026, 10, 16), 16300), (date(2026, 10, 17), 16300)]


def test_gst_slab_boundaries():
    assert [room_gst_percent(t) for t in (1000, 1001, 7500, 7501)] == [0, 5, 5, 18]


def test_split_guests_evenly():
    assert split_guests(5, 2) == [3, 2]
    with pytest.raises(PricingError):
        split_guests(1, 2)


def test_base_occupancy_quote():
    q = quote(VILLA, NIGHTS, guests=2, rooms=1)
    assert q["room_subtotal"] == 32600
    assert q["room_tax"] == 2 * 2934  # 18% of 16,300
    assert q["total"] == 32600 + 5868


def test_extra_guest_fee_and_slab_jump():
    # 7,000 is in the 5% slab; one extra guest pushes the tariff to 8,800 → 18%.
    room = RoomPricing(base_occupancy=2, max_occupancy=3, extra_guest_fee=1800)
    q = quote(room, [(date(2026, 10, 7), 7000)], guests=3, rooms=1)
    assert q["nights"][0]["extra_guest_charges"] == 1800
    assert q["room_tax"] == 1584
    assert q["total"] == 8800 + 1584


def test_multi_room_split():
    room = RoomPricing(base_occupancy=2, max_occupancy=3, extra_guest_fee=1500)
    q = quote(room, [(date(2026, 10, 7), 8900)], guests=5, rooms=2)
    assert q["guests_per_room"] == [3, 2]
    assert q["room_subtotal"] == 8900 + 1500 + 8900


def test_over_capacity_raises():
    with pytest.raises(PricingError, match="at least 2 rooms"):
        quote(VILLA, NIGHTS, guests=5, rooms=1)


def test_addon_units():
    addons = [
        AddonPricing("a", "Transfer", 2400, "per_booking"),
        AddonPricing("b", "Breakfast", 850, "per_guest_per_night"),
        AddonPricing("c", "Cruise", 1800, "per_guest"),
        AddonPricing("d", "Heater", 300, "per_night"),
    ]
    q = quote(VILLA, NIGHTS, guests=3, rooms=1, addons=addons)
    assert [a["quantity"] for a in q["addons"]] == [1, 6, 3, 2]
    assert q["addon_subtotal"] == 2400 + 5100 + 5400 + 600
    assert q["addon_tax"] == sum((a["subtotal"] * 18 + 50) // 100 for a in q["addons"])
    assert q["total"] == q["total_before_tax"] + q["total_tax"]

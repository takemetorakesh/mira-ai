import json

from app.agent.grounding import check_reply, money_amounts

LEDGER = json.dumps(
    {
        "options": [
            {
                "room_name": "One-Bedroom Pool Villa",
                "property_name": "Casa Azul Villas",
                "avg_room_cost_per_night": 16250,
                "stay_total_with_tax": 38350,
            }
        ],
        "budget_per_night": 20000,
    }
)
NAMES = ["One-Bedroom Pool Villa", "Pool Villa", "Plunge Pool Cottage"]


def codes(reply, hold=False):
    return [v["code"] for v in check_reply(reply, LEDGER, NAMES, hold)]


def test_money_formats():
    assert [(v, t) for _, v, t in money_amounts("₹16,250 or Rs. 38350, about 16.2k, under 20k, 1.5 lakh")] == [
        (16250, 0),
        (38350, 0),
        (16200, 50),
        (20000, 500),
        (150000, 5000),
    ]


def test_grounded_reply_passes():
    assert (
        codes(
            "The One-Bedroom Pool Villa at Casa Azul Villas is ₹16,250/night (~16.2k), "
            "total ₹38,350, under your 20k budget."
        )
        == []
    )


def test_invented_and_computed_amounts_fail():
    assert codes("That's ₹16,500 a night.") == ["unsupported_amount"]
    assert codes("Split three ways that's ₹12,783 each.") == ["unsupported_amount"]


def test_unlooked_up_name_fails():
    assert codes("You could also try the Plunge Pool Cottage.") == ["unverified_name"]


def test_hold_claims():
    assert codes("Done! I've reserved the villa for you.") == ["false_hold_claim"]
    assert codes("Your booking is confirmed.") == ["false_hold_claim"]
    assert codes("Shall I put it on hold for you?") == []
    assert codes("Sadly the villa is booked out those nights.") == []
    assert codes("It's booked up that weekend, but the cottage is free.") == []
    assert codes("Done! I've reserved the villa for you.", hold=True) == []

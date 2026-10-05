from datetime import date

import pytest

from app.domain.dates import (
    CheckOutDay,
    DateResolutionError,
    ExactDates,
    ExtendStay,
    Nights,
    Weekend,
    resolve,
    this_weekend_friday,
)

TUE = date(2026, 10, 6)


@pytest.mark.parametrize(
    "today, friday",
    [
        (date(2026, 10, 5), date(2026, 10, 9)),  # Mon
        (date(2026, 10, 6), date(2026, 10, 9)),  # Tue
        (date(2026, 10, 9), date(2026, 10, 9)),  # Fri
        (date(2026, 10, 10), date(2026, 10, 9)),  # Sat: weekend in progress
        (date(2026, 10, 11), date(2026, 10, 16)),  # Sun: the coming weekend
    ],
)
def test_this_weekend_friday(today, friday):
    assert this_weekend_friday(today) == friday


def test_this_and_next_weekend():
    assert resolve(Weekend(kind="weekend", which="this"), TUE, None, None)[:2] == (
        date(2026, 10, 9),
        date(2026, 10, 11),
    )
    assert resolve(Weekend(kind="weekend", which="next"), TUE, None, None)[:2] == (
        date(2026, 10, 16),
        date(2026, 10, 18),
    )


def test_this_weekend_asked_on_saturday_starts_today():
    sat = date(2026, 10, 10)
    assert resolve(Weekend(kind="weekend", which="this"), sat, None, None)[:2] == (sat, date(2026, 10, 11))


def test_extend_and_shorten():
    ci, co = date(2026, 10, 9), date(2026, 10, 11)
    assert resolve(ExtendStay(kind="extend", nights=1), TUE, ci, co)[1] == date(2026, 10, 12)
    assert resolve(ExtendStay(kind="extend", nights=-1), TUE, ci, co)[1] == date(2026, 10, 10)
    with pytest.raises(DateResolutionError):
        resolve(ExtendStay(kind="extend", nights=-2), TUE, ci, co)
    with pytest.raises(DateResolutionError):
        resolve(ExtendStay(kind="extend", nights=1), TUE, None, None)


def test_check_out_day_rolls_into_next_month():
    assert resolve(CheckOutDay(kind="check_out_day", day=13), TUE, date(2026, 10, 9), None)[1] == date(2026, 10, 13)
    assert resolve(CheckOutDay(kind="check_out_day", day=2), TUE, date(2026, 10, 30), None)[1] == date(2026, 11, 2)
    # Nov has no 31st: next valid is Dec 31
    assert resolve(CheckOutDay(kind="check_out_day", day=31), TUE, date(2026, 11, 5), None)[1] == date(2026, 12, 31)


def test_nights():
    assert resolve(Nights(kind="nights", nights=3), TUE, date(2026, 10, 9), None)[1] == date(2026, 10, 12)


def test_exact_past_dates_roll_to_next_year():
    ci, co, notes = resolve(
        ExactDates(kind="exact", check_in=date(2026, 9, 10), check_out=date(2026, 9, 13)), TUE, None, None
    )
    assert (ci, co) == (date(2027, 9, 10), date(2027, 9, 13))
    assert notes


def test_exact_across_new_year():
    ci, co, _ = resolve(
        ExactDates(kind="exact", check_in=date(2026, 12, 30), check_out=date(2026, 1, 2)), TUE, None, None
    )
    assert (ci, co) == (date(2026, 12, 30), date(2027, 1, 2))

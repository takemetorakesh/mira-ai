"""Stay-date resolution. The model never does date arithmetic: it describes what the guest said
as a DateSpec and this module turns it into concrete dates against `today`."""

from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, Field

FRIDAY, SATURDAY, SUNDAY = 4, 5, 6


class ExactDates(BaseModel):
    """Guest gave calendar dates, e.g. 'Oct 20 to 23'. check_out may be omitted if unknown."""

    kind: Literal["exact"]
    check_in: date
    check_out: date | None = None


class Weekend(BaseModel):
    """'this weekend' / 'next weekend' → Friday night to Sunday morning."""

    kind: Literal["weekend"]
    which: Literal["this", "next"]


class ExtendStay(BaseModel):
    """'stay one more night' (+1) or 'one night less' (-1). Moves check-out only."""

    kind: Literal["extend"]
    nights: int


class CheckOutDay(BaseModel):
    """'stay till the 13th' → the first 13th after check-in."""

    kind: Literal["check_out_day"]
    day: int = Field(ge=1, le=31)


class Nights(BaseModel):
    """'for 3 nights' → check-out = check-in + n."""

    kind: Literal["nights"]
    nights: int = Field(ge=1)


DateSpec = Annotated[ExactDates | Weekend | ExtendStay | CheckOutDay | Nights, Field(discriminator="kind")]


class DateResolutionError(ValueError):
    pass


def resolve(
    spec: DateSpec, today: date, check_in: date | None, check_out: date | None
) -> tuple[date | None, date | None, list[str]]:
    """Returns (check_in, check_out, notes). Notes explain any interpretation the guest should hear."""
    notes: list[str] = []
    match spec:
        case ExactDates():
            new_in, new_out = spec.check_in, spec.check_out
            if new_in < today:
                # "Sep 10" asked in October means next September, not a date in the past.
                new_in = _add_year(new_in)
                new_out = _add_year(new_out) if new_out else None
                notes.append(f"Interpreted the dates as {new_in.year} since they had already passed this year.")
            if new_out and new_out < new_in and new_out.month < new_in.month:
                new_out = _add_year(new_out)  # stay across New Year: Dec 30 → Jan 2
            return new_in, new_out, notes

        case Weekend():
            friday = this_weekend_friday(today)
            if spec.which == "next":
                friday += timedelta(days=7)
            start = max(friday, today)  # asked on a Saturday: "this weekend" starts today
            return start, friday + timedelta(days=2), notes

        case ExtendStay():
            if check_in is None or check_out is None:
                raise DateResolutionError("Need both check-in and check-out before extending or shortening the stay.")
            new_out = check_out + timedelta(days=spec.nights)
            if new_out <= check_in:
                raise DateResolutionError("That would leave zero nights; the stay must be at least one night.")
            return check_in, new_out, notes

        case CheckOutDay():
            if check_in is None:
                raise DateResolutionError("Need a check-in date before setting the check-out day.")
            return check_in, next_day_of_month_after(check_in, spec.day), notes

        case Nights():
            if check_in is None:
                raise DateResolutionError("Need a check-in date before setting the number of nights.")
            return check_in, check_in + timedelta(days=spec.nights), notes

    raise DateResolutionError(f"Unsupported date spec: {spec!r}")


def this_weekend_friday(today: date) -> date:
    """Mon-Fri: this week's Friday. Sat: yesterday (weekend under way). Sun: the coming Friday."""
    weekday = today.weekday()
    if weekday == SATURDAY:
        return today - timedelta(days=1)
    if weekday == SUNDAY:
        return today + timedelta(days=5)
    return today + timedelta(days=FRIDAY - weekday)


def next_day_of_month_after(after: date, day: int) -> date:
    year, month = after.year, after.month
    for _ in range(13):
        try:
            candidate = date(year, month, day)
        except ValueError:  # e.g. the 31st in a 30-day month
            candidate = None
        if candidate and candidate > after:
            return candidate
        month += 1
        if month == 13:
            year, month = year + 1, 1
    raise DateResolutionError(f"No valid date with day {day} after {after}.")


def _add_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + 1, day=28)

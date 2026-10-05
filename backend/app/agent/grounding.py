"""Checks a draft reply against the facts the agent actually saw (the "ledger": recent tool
results, booking state and the guest's own message).

Three checks, aimed at the mistakes that cost a hotel money:
  - every ₹ amount must appear in the ledger (no invented or self-computed prices)
  - a room name may only be mentioned if it was looked up
  - "booked / reserved / held" may only be claimed if create_booking_hold succeeded this turn
"""

import re

MONEY = re.compile(
    r"(?:₹|\brs\.?|\binr)\s*(\d[\d,]*(?:\.\d+)?)\s*(k|l|lakh)?\b"  # ₹16,250  Rs. 16k  INR 1.5 lakh
    r"|\b(\d+(?:\.\d+)?)\s*(k|lakh)\b",  # 16.2k  2 lakh
    re.IGNORECASE,
)
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
HOLD_CLAIM = re.compile(
    r"\b(?:i'?ve|i have|we'?ve|we have|has been|have been|is now|it'?s now|you'?re|is)\s+(?:all\s+)?"
    r"(?:held|reserved|booked|confirmed|on hold)\b(?!\s+(?:out|up|solid))"  # "booked out" means sold out
    r"|\bhold reference\b|\bbooking (?:is )?confirmed\b",
    re.IGNORECASE,
)


def money_amounts(text: str) -> list[tuple[str, int, int]]:
    """Returns (as written, rupees, tolerance). "16.2k" gets ±50 because it may be a rounded 16,250."""
    amounts = []
    for m in MONEY.finditer(text):
        raw, suffix = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        value = float(raw.replace(",", ""))
        tolerance = 0
        if suffix:
            unit = 1000 if suffix.lower() == "k" else 100_000
            decimals = len(raw.split(".")[1]) if "." in raw else 0
            value *= unit
            tolerance = unit // 10**decimals // 2
        amounts.append((m.group(0).strip(), round(value), tolerance))
    return amounts


def ledger_numbers(ledger: str) -> set[int]:
    return {int(float(n)) for n in NUMBER.findall(ledger.replace(",", ""))}


def check_reply(reply: str, ledger: str, room_names: list[str], hold_created: bool) -> list[dict]:
    violations = []
    known = ledger_numbers(ledger)
    for written, value, tolerance in money_amounts(reply):
        if not any(abs(value - k) <= tolerance for k in known):
            message = f"{written} isn't in any tool result. Quote prices exactly as returned; don't compute them."
            violations.append({"code": "unsupported_amount", "amount": written, "message": message})

    reply_lower, ledger_lower = reply.lower(), ledger.lower()
    for name in room_names:
        if name.lower() in reply_lower and name.lower() not in ledger_lower:
            message = f"'{name}' hasn't been looked up in this conversation. Use a tool first or leave it out."
            violations.append({"code": "unverified_name", "name": name, "message": message})

    if not hold_created and HOLD_CLAIM.search(reply):
        message = "The reply says the room is held or booked, but create_booking_hold didn't succeed this turn."
        violations.append({"code": "false_hold_claim", "message": message})
    return violations

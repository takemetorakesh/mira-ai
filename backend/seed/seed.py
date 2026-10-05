"""Load seed/catalog.json into Postgres and generate the nightly rate/inventory calendar.

Run: uv run python -m seed.seed   (wipes catalog, conversations and holds; safe to re-run)
"""

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import insert, text

from app.db.models import Addon, Policy, Property, RoomInventory, RoomType
from app.db.session import get_engine
from app.domain.amenities import Amenity

CATALOG_PATH = Path(__file__).with_name("catalog.json")
WEEKEND_NIGHTS = {4, 5}  # Friday and Saturday nights


def nightly_rate(night: date, base_rate: int, weekend_multiplier: float, peaks: list[dict]) -> int:
    multiplier = weekend_multiplier if night.weekday() in WEEKEND_NIGHTS else 1.0
    for peak in peaks:
        if date.fromisoformat(peak["from"]) <= night <= date.fromisoformat(peak["to"]):
            multiplier *= peak["multiplier"]
    return int(base_rate * multiplier / 100 + 0.5) * 100  # nearest ₹100, half up


def is_sold_out(night: date, ranges: list[list[str]]) -> bool:
    """Ranges are [first_night, check_out): the check-out date itself stays open."""
    return any(date.fromisoformat(a) <= night < date.fromisoformat(b) for a, b in ranges)


def build_rows(catalog: dict) -> dict[type, list[dict]]:
    vocab = set(Amenity)
    start = date.fromisoformat(catalog["calendar"]["from"])
    end = date.fromisoformat(catalog["calendar"]["to"])
    nights = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    rows: dict[type, list[dict]] = {Property: [], RoomType: [], RoomInventory: [], Policy: [], Addon: []}
    for p in catalog["properties"]:
        _check_vocab(p["id"], p["amenities"], vocab)
        rows[Property].append({k: p[k] for k in ("id", "name", "city", "area", "description", "amenities")})
        rows[Policy] += [{"property_id": p["id"], "kind": k, "details": v} for k, v in p["policies"].items()]
        rows[Addon] += [{**a, "property_id": p["id"]} for a in p["addons"]]

        for r in p["room_types"]:
            _check_vocab(r["id"], r["amenities"], vocab)
            rows[RoomType].append(
                {"property_id": p["id"]}
                | {
                    k: r[k]
                    for k in (
                        "id",
                        "name",
                        "description",
                        "base_occupancy",
                        "max_occupancy",
                        "extra_guest_fee",
                        "amenities",
                    )
                }
            )
            s = r["seed"]
            rows[RoomInventory] += [
                {
                    "room_type_id": r["id"],
                    "stay_date": night,
                    "rate": nightly_rate(night, s["base_rate"], p["seed"]["weekend_multiplier"], p["seed"]["peaks"]),
                    "units_open": 0 if is_sold_out(night, s.get("sold_out", [])) else s["units"],
                }
                for night in nights
            ]
    return rows


def _check_vocab(owner: str, amenities: list[str], vocab: set[str]) -> None:
    unknown = set(amenities) - vocab
    if unknown:
        raise ValueError(f"{owner}: amenities not in vocabulary: {sorted(unknown)}")


async def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text())
    rows = build_rows(catalog)
    async with get_engine().begin() as conn:
        tables = "turns, booking_holds, conversations, room_inventory, addons, policies, room_types, properties"
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
        for model in (Property, RoomType, RoomInventory, Policy, Addon):
            await conn.execute(insert(model), rows[model])
    print({m.__tablename__: len(r) for m, r in rows.items()})


if __name__ == "__main__":
    asyncio.run(main())

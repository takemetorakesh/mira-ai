"""Controlled amenity vocabulary shared by properties and room types.

A guest preference is matched against room amenities ∪ property amenities. Anything not in a
listing is *unknown* ("not listed"), never "no". Hotels list what they have, not what they lack.
"""

from enum import StrEnum


class Amenity(StrEnum):
    # Privacy / layout
    private_pool = "private_pool"
    standalone_unit = "standalone_unit"  # an entire villa/cottage/houseboat, nothing shared
    private_garden = "private_garden"
    living_area = "living_area"
    kitchenette = "kitchenette"
    twin_beds = "twin_beds"
    workspace = "workspace"
    # Views
    sea_view = "sea_view"
    lake_view = "lake_view"
    mountain_view = "mountain_view"
    backwater_view = "backwater_view"
    # In-room comfort
    balcony = "balcony"
    bathtub = "bathtub"
    fireplace = "fireplace"
    room_heater = "room_heater"
    air_conditioning = "air_conditioning"
    # Property facilities
    pool = "pool"
    beach_access = "beach_access"
    spa = "spa"
    ayurveda = "ayurveda"
    yoga = "yoga"
    gym = "gym"
    restaurant = "restaurant"
    bar = "bar"
    kids_play_area = "kids_play_area"
    bonfire = "bonfire"
    wifi = "wifi"
    parking = "parking"

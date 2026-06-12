"""
Stage 6D — Apartment inventory tracker.

One inventory item per (property × subtype). Tracks current stock against a
min threshold and a target. When current_count <= min_threshold, an auto-task
(category=restock) is created and linked via `inventory_item_id`, mirroring
the schedule auto-task pattern from Stage 6C.

Item schema (Mongo: `inventory_items`):
{
    id, property_id, property_name,
    category, subtype, label,
    unit (e.g., "each", "box", "litre"),
    min_threshold, target_count, current_count,
    notes, active,
    last_restocked_at (iso date), last_restocked_by_name,
    linked_task_id, auto_task_lead_count (we use min threshold; lead not needed),
    created_at, updated_at,
}
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

CATEGORIES = ["linens", "toiletries", "kitchen", "cleaning", "electrical", "first_aid", "decor"]

CATEGORY_LABELS = {
    "linens": "Linens",
    "toiletries": "Toiletries",
    "kitchen": "Kitchen",
    "cleaning": "Cleaning",
    "electrical": "Electrical",
    "first_aid": "First aid",
    "decor": "Decor",
}

# Default kit: ~25 items spanning the 6 main categories.
# (subtype, label, unit, target_count, min_threshold)
DEFAULTS: List[Dict[str, Any]] = [
    # Linens
    {"category": "linens", "subtype": "bed_sheets_queen",  "label": "Bed sheets (queen)",    "unit": "each", "target_count": 3,  "min_threshold": 1},
    {"category": "linens", "subtype": "pillow_cases",      "label": "Pillow cases",           "unit": "each", "target_count": 6,  "min_threshold": 2},
    {"category": "linens", "subtype": "bath_towels",       "label": "Bath towels",            "unit": "each", "target_count": 6,  "min_threshold": 2},
    {"category": "linens", "subtype": "hand_towels",       "label": "Hand towels",            "unit": "each", "target_count": 4,  "min_threshold": 2},
    {"category": "linens", "subtype": "bath_mats",         "label": "Bath mats",              "unit": "each", "target_count": 2,  "min_threshold": 1},

    # Toiletries
    {"category": "toiletries", "subtype": "shampoo",       "label": "Shampoo",                "unit": "bottle", "target_count": 4,  "min_threshold": 2},
    {"category": "toiletries", "subtype": "conditioner",   "label": "Conditioner",            "unit": "bottle", "target_count": 4,  "min_threshold": 2},
    {"category": "toiletries", "subtype": "body_wash",     "label": "Body wash",              "unit": "bottle", "target_count": 4,  "min_threshold": 2},
    {"category": "toiletries", "subtype": "toilet_paper",  "label": "Toilet paper",           "unit": "roll",   "target_count": 12, "min_threshold": 4},
    {"category": "toiletries", "subtype": "tissue_box",    "label": "Tissue boxes",           "unit": "box",    "target_count": 4,  "min_threshold": 2},

    # Kitchen
    {"category": "kitchen", "subtype": "dish_soap",        "label": "Dish soap",              "unit": "bottle", "target_count": 2,  "min_threshold": 1},
    {"category": "kitchen", "subtype": "dish_sponges",     "label": "Dish sponges",           "unit": "each",   "target_count": 4,  "min_threshold": 2},
    {"category": "kitchen", "subtype": "tea_bags",         "label": "Tea bags",               "unit": "each",   "target_count": 50, "min_threshold": 20},
    {"category": "kitchen", "subtype": "coffee_pods",      "label": "Coffee pods",            "unit": "each",   "target_count": 30, "min_threshold": 10},
    {"category": "kitchen", "subtype": "sugar_packets",    "label": "Sugar / sweetener",      "unit": "each",   "target_count": 50, "min_threshold": 20},

    # Cleaning
    {"category": "cleaning", "subtype": "surface_cleaner", "label": "Surface cleaner",        "unit": "bottle", "target_count": 2,  "min_threshold": 1},
    {"category": "cleaning", "subtype": "bin_bags",        "label": "Bin bags",               "unit": "each",   "target_count": 20, "min_threshold": 10},
    {"category": "cleaning", "subtype": "disinfectant",    "label": "Disinfectant wipes",     "unit": "pack",   "target_count": 2,  "min_threshold": 1},
    {"category": "cleaning", "subtype": "laundry_detergent","label":"Laundry detergent",      "unit": "bottle", "target_count": 1,  "min_threshold": 0},

    # Electrical
    {"category": "electrical", "subtype": "battery_aa",    "label": "AA batteries",           "unit": "each",   "target_count": 8,  "min_threshold": 2},
    {"category": "electrical", "subtype": "battery_aaa",   "label": "AAA batteries",          "unit": "each",   "target_count": 8,  "min_threshold": 2},
    {"category": "electrical", "subtype": "light_bulbs",   "label": "Light bulbs",            "unit": "each",   "target_count": 4,  "min_threshold": 1},

    # First aid
    {"category": "first_aid", "subtype": "bandaids",       "label": "Band-aids",              "unit": "each",   "target_count": 20, "min_threshold": 5},
    {"category": "first_aid", "subtype": "pain_relief",    "label": "Pain relief tablets",    "unit": "pack",   "target_count": 1,  "min_threshold": 0},
    {"category": "first_aid", "subtype": "antiseptic",     "label": "Antiseptic cream",       "unit": "tube",   "target_count": 1,  "min_threshold": 0},
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_item(
    *,
    property_id: str,
    property_name: str,
    category: str,
    subtype: str,
    label: str,
    unit: str,
    min_threshold: int,
    target_count: int,
    current_count: Optional[int] = None,
    notes: str = "",
) -> Dict[str, Any]:
    now = now_iso()
    current = current_count if current_count is not None else target_count
    return {
        "id": str(uuid.uuid4()),
        "property_id": property_id,
        "property_name": property_name,
        "category": category,
        "subtype": subtype,
        "label": label,
        "unit": unit or "each",
        "min_threshold": int(min_threshold),
        "target_count": int(target_count),
        "current_count": int(current),
        "notes": notes or "",
        "active": True,
        "last_restocked_at": None,
        "last_restocked_by_name": "",
        "linked_task_id": None,
        "created_at": now,
        "updated_at": now,
    }


def default_items_for_property(property_id: str, property_name: str) -> List[Dict[str, Any]]:
    return [
        build_item(property_id=property_id, property_name=property_name, **spec)
        for spec in DEFAULTS
    ]


def status_for_item(item: Dict[str, Any]) -> str:
    if not item.get("active", True):
        return "inactive"
    current = int(item.get("current_count") or 0)
    minimum = int(item.get("min_threshold") or 0)
    target = int(item.get("target_count") or 0)
    if current <= minimum:
        return "low" if current > 0 else "out"
    if current < target:
        return "below_target"
    return "ok"


def needs_task(item: Dict[str, Any]) -> bool:
    if not item.get("active", True):
        return False
    if item.get("linked_task_id"):
        return False
    current = int(item.get("current_count") or 0)
    minimum = int(item.get("min_threshold") or 0)
    return current <= minimum


def task_priority(item: Dict[str, Any]) -> str:
    current = int(item.get("current_count") or 0)
    if current == 0:
        return "urgent"
    return "high"


def restock_patch(item: Dict[str, Any], new_count: int, actor_name: str) -> Dict[str, Any]:
    return {
        "current_count": int(new_count),
        "last_restocked_at": datetime.now(timezone.utc).date().isoformat(),
        "last_restocked_by_name": actor_name or "",
        "linked_task_id": None,
        "updated_at": now_iso(),
    }


def summarise(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {
        "total": 0,
        "by_status": {"ok": 0, "below_target": 0, "low": 0, "out": 0, "inactive": 0},
        "by_category": {},
    }
    for it in items:
        out["total"] += 1
        s = status_for_item(it)
        out["by_status"][s] = out["by_status"].get(s, 0) + 1
        cat = it.get("category", "other")
        out["by_category"][cat] = out["by_category"].get(cat, 0) + 1
    return out

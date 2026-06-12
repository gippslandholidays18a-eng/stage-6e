from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException, Query, Depends
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import re
import logging
import uuid
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any, Dict
from datetime import datetime, timezone, date, timedelta

import pandas as pd

from segmentation_service import (
    recompute_all_guests,
    list_segment_definitions,
)
from cancellation_service import (
    build_cancellation_summary,
    list_cancelled_reservations,
    export_cancellations_csv,
)
from scoring_service import (
    recalculate_all_scores,
    get_commission_rates,
    set_commission_rates,
    ensure_commission_settings,
    apply_commission_costs,
    commission_summary_by_source,
    estimated_savings_if_top_converted,
    DEFAULT_COMMISSION_RATES,
)
from analytics_service import (
    resolve_date_range,
    filter_reservations,
    revenue_metrics,
    booking_metrics,
    guest_metrics,
    conversion_metrics,
    clv_metrics,
)
from digest_service import (
    ensure_digest_settings,
    update_digest_settings,
    rotate_webhook_token,
    preview_digest,
    run_digest,
    list_digest_log,
    DAY_NAMES,
)
from campaign_service import (
    AUDIENCES,
    TABS,
    CSV_FIELDS,
    ensure_campaign_settings,
    list_campaign_briefs,
    build_audience,
    audience_csv_rows,
    get_offers,
    upsert_offer,
    delete_offer,
    get_target_pct,
    set_target_pct,
    get_content_overrides,
    set_content_for,
    growth_tracker,
)
from auth_service import (
    hash_password, verify_password, issue_token, safe_user,
    seed_admin, make_auth_deps, ROLES,
)
from task_service import (
    CATEGORIES as TASK_CATEGORIES,
    CATEGORY_LABELS as TASK_CATEGORY_LABELS,
    STATUSES as TASK_STATUSES,
    STATUS_LABELS as TASK_STATUS_LABELS,
    PRIORITIES as TASK_PRIORITIES,
    PRIORITY_LABELS as TASK_PRIORITY_LABELS,
    visibility_filter as task_visibility_filter,
    can_modify_task, can_update_status, can_view_task,
    build_task_doc, build_photo, build_checklist_item, build_comment,
    summarize as task_summarize,
    now_iso as task_now_iso,
    new_id as task_new_id,
)
from compliance_service import (
    COMPLIANCE_DEFAULTS, HOUSEKEEPING_DEFAULTS, DEFAULT_LEAD_DAYS,
    build_item as build_schedule_item,
    default_items_for_property,
    status_for_item, bump_after_completion, needs_task, task_priority_for,
    summarise as schedule_summarise,
)
from inventory_service import (
    CATEGORIES as INV_CATEGORIES,
    CATEGORY_LABELS as INV_CATEGORY_LABELS,
    DEFAULTS as INV_DEFAULTS,
    build_item as build_inventory_item,
    default_items_for_property as default_inventory_for_property,
    status_for_item as inv_status,
    needs_task as inv_needs_task,
    task_priority as inv_task_priority,
    restock_patch as inv_restock_patch,
    summarise as inv_summarise,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="STR Booking Analytics API")
api = APIRouter(prefix="/api")

# Auth dependencies — defined early so route decorators can reference them in
# their `dependencies=[]` clauses (FastAPI evaluates that at import time).
current_user_dep, require_role_dep = make_auth_deps(db)
AUTH_ANY = [Depends(current_user_dep)]
AUTH_MGR = [Depends(require_role_dep("admin", "manager"))]
AUTH_ADMIN = [Depends(require_role_dep("admin"))]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Booking source classification
# ---------------------------------------------------------------------------

SOURCE_CATEGORIES = [
    "Airbnb",
    "Booking.com",
    "Stayz",
    "VRBO",
    "Expedia",
    "Trip.com",
    "Other OTA",
    "Direct — Website",
    "Direct — Phone",
    "Direct — Email",
    "Direct — Repeat Guest",
    "Unknown",
]

# Known "Other OTA" tokens — anything in this set that didn't match the named OTAs.
OTHER_OTA_TOKENS = [
    "agoda", "hotels.com", "trivago", "lastminute",
    "hotwire", "kayak", "priceline", "marriott", "hilton", "ihg",
    "hostelworld", "tripadvisor", "homeaway", "flipkey", "ota",
]


def classify_source(raw: Optional[str]) -> str:
    """Map raw booking source string → standardized category (case-insensitive)."""
    if raw is None:
        return "Unknown"
    text = str(raw).strip().lower()
    if not text:
        return "Unknown"

    # Named OTAs first (most specific)
    if "airbnb" in text:
        return "Airbnb"
    if "booking" in text:  # booking.com, booking_com
        return "Booking.com"
    if "stayz" in text:
        return "Stayz"
    if "vrbo" in text:
        return "VRBO"
    if "expedia" in text:
        return "Expedia"
    if "trip.com" in text or "ctrip" in text:
        return "Trip.com"

    # Direct channels — phone before email (email contains 'mail', not 'phone')
    if "phone" in text or "call" in text:
        return "Direct — Phone"
    if "email" in text or "mail" in text:
        return "Direct — Email"
    if "repeat" in text:
        return "Direct — Repeat Guest"
    if "direct" in text or "website" in text or "own site" in text or re.search(r"\bweb\b", text):
        return "Direct — Website"

    # Other recognised OTAs
    for token in OTHER_OTA_TOKENS:
        if token in text:
            return "Other OTA"

    return "Unknown"


# ---------------------------------------------------------------------------
# CSV column normalisation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = [
    "reservation_id",
    "guest_first_name",
    "guest_last_name",
    "guest_email",
    "property_name",
    "checkin_date",
    "checkout_date",
    "booking_value",
    "raw_booking_source",
    "booking_date",
]

# Accept many likely header variants (lowercased, stripped of non-alphanumerics)
HEADER_ALIASES: Dict[str, List[str]] = {
    "reservation_id": ["reservationid", "bookingreference", "bookingref", "bookingid", "reservationreference", "confirmationcode", "confirmationnumber", "id"],
    "guest_first_name": ["guestfirstname", "firstname", "fname", "guestfirst"],
    "guest_last_name": ["guestlastname", "lastname", "lname", "surname", "guestlast"],
    "guest_email": ["guestemail", "email", "emailaddress", "guestemailaddress"],
    "property_name": ["propertyname", "property", "listing", "listingname", "unit", "unitname"],
    "checkin_date": ["checkindate", "checkin", "arrivaldate", "arrival", "startdate"],
    "checkout_date": ["checkoutdate", "checkout", "departuredate", "departure", "enddate"],
    "nights": ["nights", "numberofnights", "numnights", "lengthofstay", "los"],
    "guest_count": ["guestcount", "numberofguests", "guests", "numguests", "pax", "noofguests"],
    "booking_value": ["bookingvalue", "totalvalue", "totalbookingvalue", "total", "grossamount", "amount", "revenue", "netvalue", "payout"],
    "raw_booking_source": ["bookingsource", "source", "channel", "platform", "rawsource"],
    "booking_date": ["bookingdate", "datebooked", "reservationdate", "createddate", "createdat", "bookedon"],
    "is_cancelled": ["iscancelled", "cancelled", "canceled", "cancellationstatus", "status"],
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def detect_column_mapping(headers: List[str]) -> Dict[str, Optional[str]]:
    """Return mapping of canonical_field -> source header string (or None)."""
    norm_headers = {_norm(h): h for h in headers}
    mapping: Dict[str, Optional[str]] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        found = None
        # exact canonical first
        if _norm(canonical) in norm_headers:
            found = norm_headers[_norm(canonical)]
        else:
            for alias in aliases:
                if alias in norm_headers:
                    found = norm_headers[alias]
                    break
        mapping[canonical] = found
    return mapping


def _parse_date(v: Any) -> Optional[str]:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    try:
        d = pd.to_datetime(v, errors="coerce", dayfirst=False)
        if pd.isna(d):
            return None
        return d.date().isoformat()
    except Exception:
        return None


def _parse_float(v: Any) -> Optional[float]:
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        if isinstance(v, str):
            v = re.sub(r"[^0-9.\-]", "", v)
            if v == "" or v == "-" or v == ".":
                return None
        return float(v)
    except Exception:
        return None


def _parse_int(v: Any) -> Optional[int]:
    f = _parse_float(v)
    return int(f) if f is not None else None


def _parse_bool(v: Any) -> bool:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    s = str(v).strip().lower()
    return s in {"y", "yes", "true", "1", "cancelled", "canceled", "cancel"}


def normalise_row(row: Dict[str, Any], mapping: Dict[str, Optional[str]]) -> Dict[str, Any]:
    def get(field: str) -> Any:
        src = mapping.get(field)
        if not src:
            return None
        v = row.get(src)
        if isinstance(v, float) and pd.isna(v):
            return None
        return v

    checkin = _parse_date(get("checkin_date"))
    checkout = _parse_date(get("checkout_date"))
    nights = _parse_int(get("nights"))
    if nights is None and checkin and checkout:
        try:
            nights = (datetime.fromisoformat(checkout).date() - datetime.fromisoformat(checkin).date()).days
        except Exception:
            nights = None

    raw_source = get("raw_booking_source")
    raw_source = str(raw_source) if raw_source is not None else ""

    return {
        "reservation_id": (str(get("reservation_id")).strip() if get("reservation_id") is not None else ""),
        "guest_first_name": (str(get("guest_first_name")).strip() if get("guest_first_name") is not None else ""),
        "guest_last_name": (str(get("guest_last_name")).strip() if get("guest_last_name") is not None else ""),
        "guest_email": (str(get("guest_email")).strip() if get("guest_email") is not None else ""),
        "property_name": (str(get("property_name")).strip() if get("property_name") is not None else ""),
        "checkin_date": checkin,
        "checkout_date": checkout,
        "nights": nights,
        "guest_count": _parse_int(get("guest_count")),
        "booking_value": _parse_float(get("booking_value")) or 0.0,
        "raw_booking_source": raw_source,
        "classified_source": classify_source(raw_source),
        "booking_date": _parse_date(get("booking_date")),
        "is_cancelled": _parse_bool(get("is_cancelled")),
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Reservation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    reservation_id: str
    guest_first_name: str = ""
    guest_last_name: str = ""
    guest_email: str = ""
    property_name: str = ""
    checkin_date: Optional[str] = None
    checkout_date: Optional[str] = None
    nights: Optional[int] = None
    guest_count: Optional[int] = None
    booking_value: float = 0.0
    raw_booking_source: str = ""
    classified_source: str = "Unknown"
    booking_date: Optional[str] = None
    is_cancelled: bool = False
    imported_at: str
    manually_overridden: bool = False


class ImportLog(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    filename: str
    imported_at: str
    total_rows: int
    successful_rows: int
    failed_rows: int
    status: str


class ConfirmImportPayload(BaseModel):
    filename: str
    rows: List[Dict[str, Any]]


class SourceOverridePayload(BaseModel):
    classified_source: str


class OtaListings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    airbnb_url: Optional[str] = ""
    booking_url: Optional[str] = ""
    stayz_url: Optional[str] = ""
    vrbo_url: Optional[str] = ""
    expedia_url: Optional[str] = ""


class PropertyCreate(BaseModel):
    name: str
    property_name: Optional[str] = ""
    unit_number: Optional[str] = ""
    complex: Optional[str] = ""
    property_type: Optional[str] = ""
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    active: Optional[bool] = True
    notes: Optional[str] = ""
    # Stage 6B — Access & operations
    address: Optional[str] = ""
    key_collection_notes: Optional[str] = ""
    wifi_name: Optional[str] = ""
    wifi_password: Optional[str] = ""
    parking_notes: Optional[str] = ""
    smart_lock_code: Optional[str] = ""
    cleaner_user_id: Optional[str] = None
    manager_user_id: Optional[str] = None
    max_occupancy: Optional[int] = None
    checkin_time: Optional[str] = ""
    checkout_time: Optional[str] = ""
    ota_listings: Optional[OtaListings] = None


class PropertyUpdate(BaseModel):
    name: Optional[str] = None
    property_name: Optional[str] = None
    unit_number: Optional[str] = None
    complex: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    active: Optional[bool] = None
    notes: Optional[str] = None
    address: Optional[str] = None
    key_collection_notes: Optional[str] = None
    wifi_name: Optional[str] = None
    wifi_password: Optional[str] = None
    parking_notes: Optional[str] = None
    smart_lock_code: Optional[str] = None
    cleaner_user_id: Optional[str] = None
    manager_user_id: Optional[str] = None
    max_occupancy: Optional[int] = None
    checkin_time: Optional[str] = None
    checkout_time: Optional[str] = None
    ota_listings: Optional[OtaListings] = None


class Property(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    property_name: str = ""
    unit_number: str = ""
    complex: str = ""
    property_type: str = ""
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    active: bool = True
    notes: str = ""
    address: str = ""
    key_collection_notes: str = ""
    wifi_name: str = ""
    wifi_password: str = ""
    parking_notes: str = ""
    smart_lock_code: str = ""
    cleaner_user_id: Optional[str] = None
    manager_user_id: Optional[str] = None
    max_occupancy: Optional[int] = None
    checkin_time: str = ""
    checkout_time: str = ""
    ota_listings: Optional[OtaListings] = None
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_id(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@api.get("/")
async def root():
    return {"name": "STR Booking Analytics API", "status": "ok"}


@api.get("/sources", dependencies=AUTH_ANY)
async def list_sources():
    return {"sources": SOURCE_CATEGORIES}


@api.post("/import/preview", dependencies=AUTH_MGR)
async def import_preview(file: UploadFile = File(...)):
    """Parse uploaded CSV; return all normalised rows + column mapping + validation."""
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents), dtype=str, keep_default_na=False, na_values=[""])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    if df.empty:
        raise HTTPException(status_code=400, detail="CSV is empty")

    headers = list(df.columns)
    mapping = detect_column_mapping(headers)

    missing_required = [f for f in REQUIRED_FIELDS if mapping.get(f) is None]

    raw_rows = df.to_dict(orient="records")
    normalised: List[Dict[str, Any]] = []
    row_errors: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_rows):
        try:
            n = normalise_row(raw, mapping)
            if not n["reservation_id"]:
                row_errors.append({"row": idx + 2, "error": "Missing reservation id"})
                continue
            normalised.append(n)
        except Exception as e:
            row_errors.append({"row": idx + 2, "error": str(e)})

    return {
        "filename": file.filename,
        "headers": headers,
        "mapping": mapping,
        "missing_required": missing_required,
        "total_rows": len(raw_rows),
        "valid_rows": len(normalised),
        "row_errors": row_errors[:50],
        "rows": normalised,  # full list (frontend slices preview)
    }


@api.post("/import/confirm", dependencies=AUTH_MGR)
async def import_confirm(payload: ConfirmImportPayload):
    if not payload.rows:
        raise HTTPException(status_code=400, detail="No rows to import")

    now = _now_iso()
    docs = []
    failed = 0
    for r in payload.rows:
        try:
            rid = str(r.get("reservation_id", "")).strip()
            if not rid:
                failed += 1
                continue
            doc = {
                "id": str(uuid.uuid4()),
                "reservation_id": rid,
                "guest_first_name": r.get("guest_first_name", "") or "",
                "guest_last_name": r.get("guest_last_name", "") or "",
                "guest_email": r.get("guest_email", "") or "",
                "property_name": r.get("property_name", "") or "",
                "checkin_date": r.get("checkin_date"),
                "checkout_date": r.get("checkout_date"),
                "nights": r.get("nights"),
                "guest_count": r.get("guest_count"),
                "booking_value": float(r.get("booking_value") or 0),
                "raw_booking_source": r.get("raw_booking_source", "") or "",
                "classified_source": classify_source(r.get("raw_booking_source", "")),
                "booking_date": r.get("booking_date"),
                "is_cancelled": bool(r.get("is_cancelled", False)),
                "imported_at": now,
                "manually_overridden": False,
            }
            docs.append(doc)
        except Exception as e:
            logger.exception("row failed: %s", e)
            failed += 1

    if docs:
        # Upsert by reservation_id to allow appending without strict duplicates
        for d in docs:
            await db.reservations.update_one(
                {"reservation_id": d["reservation_id"]},
                {"$setOnInsert": d},
                upsert=True,
            )

    # Stage 2: recompute guest profiles + segments after each import
    try:
        await recompute_all_guests(db)
        # Stage 3: scores + OTA commission
        await recalculate_all_scores(db)
    except Exception as e:
        logger.exception("guest recompute failed: %s", e)

    log = {
        "id": str(uuid.uuid4()),
        "filename": payload.filename,
        "imported_at": now,
        "total_rows": len(payload.rows),
        "successful_rows": len(docs),
        "failed_rows": failed,
        "status": "completed" if failed == 0 else ("partial" if docs else "failed"),
    }
    await db.import_logs.insert_one(log.copy())
    return _strip_id(log)


@api.get("/reservations", dependencies=AUTH_MGR)
async def list_reservations(
    source: Optional[str] = None,
    property_name: Optional[str] = None,
    limit: int = Query(500, le=5000),
):
    q: Dict[str, Any] = {}
    if source and source != "all":
        q["classified_source"] = source
    if property_name and property_name != "all":
        q["property_name"] = property_name
    cursor = db.reservations.find(q, {"_id": 0}).sort("checkin_date", -1).limit(limit)
    items = await cursor.to_list(length=limit)
    return {"items": items, "count": len(items)}


@api.patch("/reservations/{rid}/source", dependencies=AUTH_MGR)
async def override_source(rid: str, payload: SourceOverridePayload):
    if payload.classified_source not in SOURCE_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid source category")
    res = await db.reservations.update_one(
        {"id": rid},
        {"$set": {"classified_source": payload.classified_source, "manually_overridden": True}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Reservation not found")
    doc = await db.reservations.find_one({"id": rid}, {"_id": 0})
    # Stage 2: source change may shift segments/scores
    try:
        await recompute_all_guests(db)
        await recalculate_all_scores(db)
    except Exception as e:
        logger.exception("guest recompute failed: %s", e)
    return doc


@api.get("/imports", dependencies=AUTH_MGR)
async def list_imports():
    cursor = db.import_logs.find({}, {"_id": 0}).sort("imported_at", -1).limit(200)
    items = await cursor.to_list(length=200)
    return {"items": items}


@api.get("/analytics/summary", dependencies=AUTH_MGR)
async def analytics_summary():
    pipeline_by_source = [
        {"$group": {
            "_id": "$classified_source",
            "bookings": {"$sum": 1},
            "revenue": {"$sum": "$booking_value"},
        }},
    ]
    by_source = []
    async for row in db.reservations.aggregate(pipeline_by_source):
        by_source.append({
            "source": row["_id"] or "Unknown",
            "bookings": row["bookings"],
            "revenue": round(float(row["revenue"] or 0), 2),
        })

    total_bookings = sum(s["bookings"] for s in by_source)
    total_revenue = round(sum(s["revenue"] for s in by_source), 2)

    direct_sources = {"Direct — Website", "Direct — Phone", "Direct — Email", "Direct — Repeat Guest"}
    ota_sources = {"Airbnb", "Booking.com", "Stayz", "VRBO", "Expedia", "Other OTA"}

    direct_bookings = sum(s["bookings"] for s in by_source if s["source"] in direct_sources)
    direct_revenue = sum(s["revenue"] for s in by_source if s["source"] in direct_sources)
    ota_bookings = sum(s["bookings"] for s in by_source if s["source"] in ota_sources)
    ota_revenue = sum(s["revenue"] for s in by_source if s["source"] in ota_sources)

    cancelled = await db.reservations.count_documents({"is_cancelled": True})

    return {
        "total_bookings": total_bookings,
        "total_revenue": total_revenue,
        "cancelled": cancelled,
        "by_source": sorted(by_source, key=lambda x: x["bookings"], reverse=True),
        "split": {
            "direct": {"bookings": direct_bookings, "revenue": round(direct_revenue, 2)},
            "ota": {"bookings": ota_bookings, "revenue": round(ota_revenue, 2)},
        },
    }


# --- Properties --------------------------------------------------------------

@api.get("/properties", dependencies=AUTH_ANY)
async def list_properties():
    cursor = db.properties.find({}, {"_id": 0}).sort("name", 1)
    items = await cursor.to_list(length=500)
    return {"items": items}


@api.post("/properties", dependencies=AUTH_MGR)
async def create_property(payload: PropertyCreate):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    existing = await db.properties.find_one({"name": name})
    if existing:
        raise HTTPException(status_code=409, detail="Property already exists")
    doc = {
        "id": str(uuid.uuid4()),
        "name": name,
        "property_name": payload.property_name or name,
        "unit_number": payload.unit_number or "",
        "complex": payload.complex or "",
        "property_type": payload.property_type or "",
        "bedrooms": payload.bedrooms,
        "bathrooms": payload.bathrooms,
        "active": True if payload.active is None else payload.active,
        "notes": payload.notes or "",
        "address": payload.address or "",
        "key_collection_notes": payload.key_collection_notes or "",
        "wifi_name": payload.wifi_name or "",
        "wifi_password": payload.wifi_password or "",
        "parking_notes": payload.parking_notes or "",
        "smart_lock_code": payload.smart_lock_code or "",
        "cleaner_user_id": payload.cleaner_user_id,
        "manager_user_id": payload.manager_user_id,
        "max_occupancy": payload.max_occupancy,
        "checkin_time": payload.checkin_time or "",
        "checkout_time": payload.checkout_time or "",
        "ota_listings": payload.ota_listings.model_dump() if payload.ota_listings else {
            "airbnb_url": "", "booking_url": "", "stayz_url": "", "vrbo_url": "", "expedia_url": ""
        },
        "created_at": _now_iso(),
    }
    await db.properties.insert_one(doc.copy())
    return _strip_id(doc)


@api.put("/properties/{pid}", dependencies=AUTH_MGR)
async def update_property(pid: str, payload: PropertyUpdate):
    existing = await db.properties.find_one({"id": pid})
    if not existing:
        raise HTTPException(status_code=404, detail="Not found")
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "name" in patch and patch["name"]:
        patch["name"] = patch["name"].strip()
        # Allow renaming but block collision with a *different* property using the same name
        clash = await db.properties.find_one({"name": patch["name"], "id": {"$ne": pid}})
        if clash:
            raise HTTPException(status_code=409, detail="Another property already uses this name")
    await db.properties.update_one({"id": pid}, {"$set": patch})
    doc = await db.properties.find_one({"id": pid}, {"_id": 0})
    return doc


@api.delete("/properties/{pid}", dependencies=AUTH_ADMIN)
async def delete_property(pid: str):
    res = await db.properties.delete_one({"id": pid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Stage 2 — Guests, Segments, Cancellations
# ---------------------------------------------------------------------------

async def _guests_by_email() -> Dict[str, Dict[str, Any]]:
    cursor = db.guests.find({}, {"_id": 0})
    items = await cursor.to_list(length=100000)
    return {g["email"]: g for g in items}


@api.post("/guests/recompute", dependencies=AUTH_MGR)
async def recompute_guests():
    result = await recompute_all_guests(db)
    return result


@api.get("/guests", dependencies=AUTH_MGR)
async def list_guests(
    segment: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(2000, le=10000),
):
    q: Dict[str, Any] = {}
    if segment and segment != "all":
        q["segments"] = segment
    cursor = db.guests.find(q, {"_id": 0}).sort("lifetime_spend", -1).limit(limit)
    items = await cursor.to_list(length=limit)
    if search:
        s = search.lower().strip()
        items = [
            g for g in items
            if s in (g.get("email") or "").lower()
            or s in (g.get("first_name") or "").lower()
            or s in (g.get("last_name") or "").lower()
        ]
    return {"items": items, "count": len(items)}


@api.get("/guests/{guest_id}", dependencies=AUTH_MGR)
async def get_guest(guest_id: str):
    # guest_id is the lowercase email
    em = guest_id.lower().strip()
    guest = await db.guests.find_one({"id": em}, {"_id": 0})
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    # Fetch this guest's reservations split into completed + cancelled
    cursor = db.reservations.find({"guest_email": em}, {"_id": 0}).sort("checkin_date", -1)
    res_list = await cursor.to_list(length=2000)
    # In case stored emails preserve case
    if not res_list:
        cursor = db.reservations.find(
            {"guest_email": {"$regex": f"^{re.escape(em)}$", "$options": "i"}}, {"_id": 0}
        ).sort("checkin_date", -1)
        res_list = await cursor.to_list(length=2000)
    completed = [r for r in res_list if not r.get("is_cancelled")]
    cancelled = [r for r in res_list if r.get("is_cancelled")]
    return {
        "guest": guest,
        "completed": completed,
        "cancelled": cancelled,
    }


@api.get("/segments", dependencies=AUTH_MGR)
async def list_segments():
    """Definitions + counts for every segment."""
    defs = list_segment_definitions()
    counts: Dict[str, int] = {d["name"]: 0 for d in defs}
    total_guests = await db.guests.count_documents({})
    async for g in db.guests.find({}, {"segments": 1}):
        for s in g.get("segments") or []:
            counts[s] = counts.get(s, 0) + 1
    unsegmented = await db.guests.count_documents({"segments": {"$size": 0}})
    return {
        "total_guests": total_guests,
        "unsegmented": unsegmented,
        "segments": [
            {**d, "guest_count": counts.get(d["name"], 0)} for d in defs
        ],
    }


@api.get("/cancellations/summary", dependencies=AUTH_MGR)
async def cancellations_summary():
    res_cursor = db.reservations.find({}, {"_id": 0})
    reservations = await res_cursor.to_list(length=100000)
    guests_map = await _guests_by_email()
    return build_cancellation_summary(reservations, guests_map)


@api.get("/cancellations", dependencies=AUTH_MGR)
async def cancellations_list(
    segment: Optional[str] = None,
    source: Optional[str] = None,
    property_name: Optional[str] = None,
):
    res_cursor = db.reservations.find({}, {"_id": 0})
    reservations = await res_cursor.to_list(length=100000)
    guests_map = await _guests_by_email()
    rows = list_cancelled_reservations(reservations, guests_map, segment, source, property_name)
    return {"items": rows, "count": len(rows)}


@api.get("/cancellations/export.csv", response_class=PlainTextResponse, dependencies=AUTH_MGR)
async def cancellations_export(
    segment: Optional[str] = None,
    source: Optional[str] = None,
    property_name: Optional[str] = None,
):
    res_cursor = db.reservations.find({}, {"_id": 0})
    reservations = await res_cursor.to_list(length=100000)
    guests_map = await _guests_by_email()
    rows = list_cancelled_reservations(reservations, guests_map, segment, source, property_name)
    csv_text = export_cancellations_csv(rows)
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="cancellation_audience.csv"'},
    )


# ---------------------------------------------------------------------------
# Stage 3 — Scoring + OTA commission
# ---------------------------------------------------------------------------

class CommissionRatesPayload(BaseModel):
    rates: Dict[str, float]


def _score_color_band(score: int) -> str:
    if score >= 75:
        return "green"
    if score >= 50:
        return "amber"
    return "red"


@api.post("/scores/recalculate", dependencies=AUTH_MGR)
async def scores_recalculate():
    return await recalculate_all_scores(db)


@api.get("/scores/summary", dependencies=AUTH_MGR)
async def scores_summary():
    g_cursor = db.guests.find({}, {"_id": 0})
    guests = await g_cursor.to_list(length=100000)
    res_cursor = db.reservations.find({}, {"_id": 0})
    reservations = await res_cursor.to_list(length=200000)

    total = len(guests)
    ota_guests = [g for g in guests if g.get("primary_channel") == "OTA"]
    avg_direct_conv = round(
        sum(g.get("direct_conversion_score", 0) for g in ota_guests) / len(ota_guests), 2
    ) if ota_guests else 0.0
    avg_rebook = round(
        sum(g.get("rebooking_score", 0) for g in guests) / total, 2
    ) if total else 0.0
    total_commission = round(
        sum(
            float(r.get("estimated_commission_cost") or 0)
            for r in reservations
            if not r.get("is_cancelled") and (r.get("classified_source") or "") in {
                "Airbnb", "Booking.com", "Stayz", "VRBO", "Expedia", "Other OTA"
            }
        ),
        2,
    )
    savings_top20 = estimated_savings_if_top_converted(guests, reservations, 20.0)

    return {
        "total_guests_scored": total,
        "ota_guest_count": len(ota_guests),
        "avg_direct_conversion_score": avg_direct_conv,
        "avg_rebooking_score": avg_rebook,
        "total_ota_commission_to_date": total_commission,
        "estimated_savings_top20_direct": savings_top20,
    }


@api.get("/scores/guests", dependencies=AUTH_MGR)
async def scores_list(
    primary_source: Optional[str] = None,
    min_score: int = 0,
    segment: Optional[str] = None,
    limit: int = Query(2000, le=10000),
):
    q: Dict[str, Any] = {}
    if primary_source and primary_source != "all":
        q["primary_channel"] = primary_source
    if segment and segment != "all":
        q["segments"] = segment
    if min_score > 0:
        q["revenue_opportunity_score"] = {"$gte": min_score}
    cursor = db.guests.find(q, {"_id": 0}).sort("revenue_opportunity_score", -1).limit(limit)
    items = await cursor.to_list(length=limit)
    return {"items": items, "count": len(items)}


@api.get("/scores/guests/export.csv", response_class=PlainTextResponse, dependencies=AUTH_MGR)
async def scores_export(
    primary_source: Optional[str] = None,
    min_score: int = 0,
    segment: Optional[str] = None,
):
    q: Dict[str, Any] = {}
    if primary_source and primary_source != "all":
        q["primary_channel"] = primary_source
    if segment and segment != "all":
        q["segments"] = segment
    if min_score > 0:
        q["revenue_opportunity_score"] = {"$gte": min_score}
    cursor = db.guests.find(q, {"_id": 0}).sort("revenue_opportunity_score", -1)
    items = await cursor.to_list(length=100000)

    buf = io.StringIO()
    fieldnames = [
        "guest_name", "email", "primary_channel", "total_stays", "lifetime_spend",
        "raw_ltv_value", "direct_conversion_score", "lifetime_value_score",
        "rebooking_score", "revenue_opportunity_score", "segments",
    ]
    import csv as _csv
    w = _csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for g in items:
        w.writerow({
            "guest_name": f"{g.get('first_name','')} {g.get('last_name','')}".strip(),
            "email": g.get("email", ""),
            "primary_channel": g.get("primary_channel", ""),
            "total_stays": g.get("total_stays", 0),
            "lifetime_spend": g.get("lifetime_spend", 0),
            "raw_ltv_value": g.get("raw_ltv_value", 0),
            "direct_conversion_score": g.get("direct_conversion_score", 0),
            "lifetime_value_score": g.get("lifetime_value_score", 0),
            "rebooking_score": g.get("rebooking_score", 0),
            "revenue_opportunity_score": g.get("revenue_opportunity_score", 0),
            "segments": "; ".join(g.get("segments") or []),
        })
    return PlainTextResponse(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="guest_scores.csv"'},
    )


@api.get("/commissions/summary", dependencies=AUTH_MGR)
async def commissions_summary():
    res_cursor = db.reservations.find({}, {"_id": 0})
    reservations = await res_cursor.to_list(length=200000)
    by_source = commission_summary_by_source(reservations)
    total = round(sum(b["commission"] for b in by_source), 2)
    total_revenue = round(sum(b["revenue"] for b in by_source), 2)
    total_bookings = sum(b["bookings"] for b in by_source)
    return {
        "by_source": by_source,
        "total_commission": total,
        "total_revenue": total_revenue,
        "total_bookings": total_bookings,
    }


@api.get("/settings/commissions", dependencies=AUTH_MGR)
async def settings_commissions_get():
    rates = await get_commission_rates(db)
    return {"rates": rates, "defaults": DEFAULT_COMMISSION_RATES}


@api.put("/settings/commissions", dependencies=AUTH_ADMIN)
async def settings_commissions_put(payload: CommissionRatesPayload):
    if not payload.rates:
        raise HTTPException(status_code=400, detail="rates is required")
    cleaned = await set_commission_rates(db, payload.rates)
    # Recompute commissions on existing reservations & scores
    await apply_commission_costs(db)
    return {"rates": cleaned}


# ---------------------------------------------------------------------------
# Stage 4 — Analytics + Reports
# ---------------------------------------------------------------------------

async def _load_all_reservations() -> List[Dict[str, Any]]:
    cursor = db.reservations.find({}, {"_id": 0})
    return await cursor.to_list(length=200000)


async def _load_all_guests() -> List[Dict[str, Any]]:
    cursor = db.guests.find({}, {"_id": 0})
    return await cursor.to_list(length=100000)


@api.get("/analytics/revenue", dependencies=AUTH_MGR)
async def analytics_revenue(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    preset: Optional[str] = None,
    property_name: Optional[str] = None,
):
    start, end = resolve_date_range(start_date, end_date, preset)
    res = await _load_all_reservations()
    scoped = filter_reservations(res, start, end, property_name)
    return {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        **revenue_metrics(scoped, start, end),
    }


@api.get("/analytics/bookings", dependencies=AUTH_MGR)
async def analytics_bookings(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    preset: Optional[str] = None,
    property_name: Optional[str] = None,
):
    start, end = resolve_date_range(start_date, end_date, preset)
    res = await _load_all_reservations()
    scoped = filter_reservations(res, start, end, property_name)
    return booking_metrics(scoped)


@api.get("/analytics/guests", dependencies=AUTH_MGR)
async def analytics_guests(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    preset: Optional[str] = None,
    property_name: Optional[str] = None,
):
    start, end = resolve_date_range(start_date, end_date, preset)
    res = await _load_all_reservations()
    guests = await _load_all_guests()
    scoped = filter_reservations(res, start, end, property_name)
    return guest_metrics(scoped, guests, start, end)


@api.get("/analytics/conversion", dependencies=AUTH_MGR)
async def analytics_conversion(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    preset: Optional[str] = None,
    property_name: Optional[str] = None,
):
    start, end = resolve_date_range(start_date, end_date, preset)
    res = await _load_all_reservations()
    guests = await _load_all_guests()
    rates = await get_commission_rates(db)
    scoped = filter_reservations(res, start, end, property_name)
    return conversion_metrics(scoped, guests, res, rates)


@api.get("/analytics/clv", dependencies=AUTH_MGR)
async def analytics_clv(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    preset: Optional[str] = None,
    property_name: Optional[str] = None,
):
    guests = await _load_all_guests()
    return clv_metrics(guests)


# --- Reports ----------------------------------------------------------------

def _csv_response(rows: List[Dict[str, Any]], fieldnames: List[str], filename: str) -> PlainTextResponse:
    import csv as _csv
    buf = io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fieldnames})
    return PlainTextResponse(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


REPORT_DEFS = {
    "full_guest_database": {
        "label": "Full guest database with scores & segments",
        "fields": ["email", "first_name", "last_name", "primary_channel", "most_used_source",
                   "total_stays", "lifetime_spend", "raw_ltv_value",
                   "direct_conversion_score", "lifetime_value_score", "rebooking_score",
                   "revenue_opportunity_score", "remarketing_priority_score",
                   "cancellation_count", "cancellation_rate", "recovered", "segments_joined"],
    },
    "ota_commission_period": {
        "label": "OTA commission cost report for period",
        "fields": ["reservation_id", "guest_email", "property_name", "checkin_date",
                   "classified_source", "booking_value", "commission_rate_used",
                   "estimated_commission_cost"],
    },
    "cancellation_period": {
        "label": "Cancellation report for period",
        "fields": ["reservation_id", "guest_email", "property_name", "checkin_date",
                   "booking_date", "booking_value", "classified_source"],
    },
    "revenue_by_source_period": {
        "label": "Revenue by source report for period",
        "fields": ["source", "bookings", "revenue"],
    },
    "top_conversion_opportunities": {
        "label": "Top OTA conversion opportunity guests (dconv ≥ 60)",
        "fields": ["email", "first_name", "last_name", "most_used_source",
                   "direct_conversion_score", "revenue_opportunity_score",
                   "lifetime_spend", "total_stays"],
    },
    "guests_at_risk_of_churning": {
        "label": "Guests at risk of churning (Direct, last stay >12mo)",
        "fields": ["email", "first_name", "last_name", "most_used_source",
                   "last_stay_date", "total_stays", "lifetime_spend"],
    },
    "high_intent_cancellations": {
        "label": "High-intent cancellation guests",
        "fields": ["email", "first_name", "last_name", "cancellation_count",
                   "remarketing_priority_score", "segments_joined"],
    },
}


@api.get("/reports", dependencies=AUTH_MGR)
async def reports_index():
    return {"reports": [{"key": k, **v} for k, v in REPORT_DEFS.items()]}


@api.get("/reports/{report_name}/count", dependencies=AUTH_MGR)
async def reports_count(
    report_name: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    preset: Optional[str] = None,
    property_name: Optional[str] = None,
):
    rows = await _build_report_rows(report_name, start_date, end_date, preset, property_name)
    return {"count": len(rows)}


@api.get("/reports/{report_name}.csv", response_class=PlainTextResponse, dependencies=AUTH_MGR)
async def reports_csv(
    report_name: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    preset: Optional[str] = None,
    property_name: Optional[str] = None,
):
    if report_name not in REPORT_DEFS:
        raise HTTPException(status_code=404, detail="Unknown report")
    rows = await _build_report_rows(report_name, start_date, end_date, preset, property_name)
    fields = REPORT_DEFS[report_name]["fields"]
    return _csv_response(rows, fields, f"{report_name}.csv")


async def _build_report_rows(
    report_name: str,
    start_date: Optional[str],
    end_date: Optional[str],
    preset: Optional[str],
    property_name: Optional[str],
) -> List[Dict[str, Any]]:
    if report_name not in REPORT_DEFS:
        raise HTTPException(status_code=404, detail="Unknown report")
    start, end = resolve_date_range(start_date, end_date, preset)

    if report_name == "full_guest_database":
        guests = await _load_all_guests()
        rows = []
        for g in guests:
            row = {**g}
            row["segments_joined"] = "; ".join(g.get("segments") or [])
            rows.append(row)
        return rows

    if report_name == "ota_commission_period":
        res = await _load_all_reservations()
        scoped = filter_reservations(res, start, end, property_name)
        return [
            r for r in scoped
            if (r.get("classified_source") or "") in {"Airbnb","Booking.com","Stayz","VRBO","Expedia","Other OTA"}
            and not r.get("is_cancelled")
        ]

    if report_name == "cancellation_period":
        res = await _load_all_reservations()
        scoped = filter_reservations(res, start, end, property_name)
        return [r for r in scoped if r.get("is_cancelled")]

    if report_name == "revenue_by_source_period":
        res = await _load_all_reservations()
        scoped = filter_reservations(res, start, end, property_name)
        agg = revenue_metrics(scoped, start, end)
        return agg["revenue_by_source"]

    if report_name == "top_conversion_opportunities":
        guests = await _load_all_guests()
        return [
            g for g in guests
            if (g.get("direct_conversion_score") or 0) >= 60
            and g.get("primary_channel") == "OTA"
        ]

    if report_name == "guests_at_risk_of_churning":
        guests = await _load_all_guests()
        return [
            g for g in guests
            if "Direct Guest at Risk of Churning" in (g.get("segments") or [])
        ]

    if report_name == "high_intent_cancellations":
        guests = await _load_all_guests()
        out = [
            {**g, "segments_joined": "; ".join(g.get("segments") or [])}
            for g in guests
            if "Cancelled — High Intent" in (g.get("segments") or [])
        ]
        out.sort(key=lambda g: g.get("remarketing_priority_score") or 0, reverse=True)
        return out

    return []


# ---------------------------------------------------------------------------
# Stage 4.5 — Weekly digest (Resend)
# ---------------------------------------------------------------------------

class DigestSettingsPayload(BaseModel):
    recipients: Optional[List[str]] = None
    send_day: Optional[int] = None
    send_hour: Optional[int] = None
    send_minute: Optional[int] = None
    timezone: Optional[str] = None
    enabled: Optional[bool] = None


def _dashboard_base() -> str:
    return os.environ.get("DASHBOARD_BASE", "").rstrip("/") or "https://example.com"


@api.get("/settings/digest", dependencies=AUTH_ADMIN)
async def settings_digest_get():
    cfg = await ensure_digest_settings(db)
    webhook_url = f"{_dashboard_base()}/api/digest/run?token={cfg.get('webhook_token','')}"
    return {
        "config": {k: v for k, v in cfg.items() if k != "_id"},
        "webhook_url": webhook_url,
        "days_of_week": DAY_NAMES,
        "sender_email": os.environ.get("SENDER_EMAIL", ""),
    }


@api.put("/settings/digest", dependencies=AUTH_ADMIN)
async def settings_digest_put(payload: DigestSettingsPayload):
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    cfg = await update_digest_settings(db, patch)
    return {k: v for k, v in cfg.items() if k != "_id"}


@api.post("/settings/digest/rotate-token", dependencies=AUTH_ADMIN)
async def settings_digest_rotate():
    token = await rotate_webhook_token(db)
    webhook_url = f"{_dashboard_base()}/api/digest/run?token={token}"
    return {"webhook_token": token, "webhook_url": webhook_url}


@api.get("/digest/preview", dependencies=AUTH_ADMIN)
async def digest_preview():
    return await preview_digest(db, _dashboard_base())


class DigestRunPayload(BaseModel):
    force: bool = False
    test_recipient: Optional[str] = None


@api.post("/digest/send-now", dependencies=AUTH_ADMIN)
async def digest_send_now(payload: DigestRunPayload):
    """Manual trigger from the UI. Always force-sends; ignores 'no new data' guard."""
    return await run_digest(
        db,
        _dashboard_base(),
        force=True,
        test_recipient=payload.test_recipient,
    )


@api.post("/digest/run", response_class=PlainTextResponse)
async def digest_webhook_run(token: str = Query(...)):
    """Webhook endpoint for cron-job.org. Skips silently if no new data."""
    cfg = await ensure_digest_settings(db)
    expected = cfg.get("webhook_token", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="Invalid token")
    result = await run_digest(db, _dashboard_base(), force=False)
    status = result.get("status", "unknown")
    detail = result.get("reason") or result.get("error") or result.get("email_id") or ""
    return PlainTextResponse(content=f"{status}: {detail}\n")


@api.get("/digest/history", dependencies=AUTH_ADMIN)
async def digest_history():
    items = await list_digest_log(db, limit=30)
    return {"items": items}


# ---------------------------------------------------------------------------
# Stage 5 — Campaign engine
# ---------------------------------------------------------------------------

class OfferPayload(BaseModel):
    code: str
    name: Optional[str] = None
    description: Optional[str] = None
    discount_type: Optional[str] = "percentage"
    discount_value: Optional[float] = 0
    applies_to: Optional[str] = "all"
    active: Optional[bool] = True
    expires_at: Optional[str] = None
    category: Optional[str] = "Custom"


class TargetPayload(BaseModel):
    target_direct_pct: float


class ContentPayload(BaseModel):
    subject_lines: List[str]
    sms: str
    key_points: List[str]
    tone: str
    send_timing: str


@api.get("/campaigns", dependencies=AUTH_MGR)
async def campaigns_list():
    briefs = await list_campaign_briefs(db)
    grouped: Dict[str, List[Dict[str, Any]]] = {t: [] for t in TABS}
    for b in briefs:
        grouped.setdefault(b["tab"], []).append(b)
    return {"tabs": TABS, "briefs": briefs, "grouped": grouped}


@api.get("/campaigns/growth-tracker", dependencies=AUTH_MGR)
async def campaigns_growth_tracker():
    return await growth_tracker(db)


@api.get("/campaigns/{key}/guests", dependencies=AUTH_MGR)
async def campaigns_guests(key: str, limit: int = Query(2000, le=10000)):
    if key not in AUDIENCES:
        raise HTTPException(status_code=404, detail="Unknown audience")
    cursor = db.guests.find({}, {"_id": 0})
    guests = await cursor.to_list(length=100000)
    audience = build_audience(key, guests)
    return {"key": key, "count": len(audience), "items": audience[:limit]}


@api.get("/campaigns/{key}/export.csv", response_class=PlainTextResponse, dependencies=AUTH_MGR)
async def campaigns_export(key: str):
    if key not in AUDIENCES:
        raise HTTPException(status_code=404, detail="Unknown audience")
    cursor = db.guests.find({}, {"_id": 0})
    guests = await cursor.to_list(length=100000)
    rows = audience_csv_rows(key, guests)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"campaign_{key}_{date_str}.csv"
    return _csv_response(rows, CSV_FIELDS, filename)


@api.put("/settings/direct-target", dependencies=AUTH_ADMIN)
async def settings_direct_target_put(payload: TargetPayload):
    v = await set_target_pct(db, payload.target_direct_pct)
    return {"target_direct_pct": v}


@api.get("/settings/offers", dependencies=AUTH_MGR)
async def settings_offers_get():
    offers = await get_offers(db)
    return {"offers": offers}


@api.post("/settings/offers", dependencies=AUTH_ADMIN)
async def settings_offers_post(payload: OfferPayload):
    try:
        offers = await upsert_offer(db, payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"offers": offers}


@api.put("/settings/offers/{code}", dependencies=AUTH_ADMIN)
async def settings_offers_put(code: str, payload: OfferPayload):
    payload.code = code
    try:
        offers = await upsert_offer(db, payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"offers": offers}


@api.delete("/settings/offers/{code}", dependencies=AUTH_ADMIN)
async def settings_offers_delete(code: str):
    offers = await delete_offer(db, code)
    return {"offers": offers}


@api.get("/settings/campaign-content/{key}", dependencies=AUTH_MGR)
async def settings_campaign_content_get(key: str):
    if key not in AUDIENCES:
        raise HTTPException(status_code=404, detail="Unknown audience")
    content = await get_content_overrides(db)
    return {"key": key, "content": content.get(key)}


@api.put("/settings/campaign-content/{key}", dependencies=AUTH_ADMIN)
async def settings_campaign_content_put(key: str, payload: ContentPayload):
    if key not in AUDIENCES:
        raise HTTPException(status_code=404, detail="Unknown audience")
    content = await set_content_for(db, key, payload.model_dump())
    return {"key": key, "content": content.get(key)}




# ---------------------------------------------------------------------------
# Wire up
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_seed():
    try:
        await ensure_commission_settings(db)
        await ensure_digest_settings(db)
        await ensure_campaign_settings(db)
        await seed_managed_properties(db)
        await seed_admin(db)
        await db.users.create_index("email", unique=True)
        await db.tasks.create_index([("created_at", -1)])
        await db.tasks.create_index("property_id")
        await db.tasks.create_index("assignee_id")
        await db.tasks.create_index("status")
        await db.schedule_items.create_index("property_id")
        await db.schedule_items.create_index([("kind", 1), ("subtype", 1)])
        await db.schedule_items.create_index("next_due_at")
        await db.inventory_items.create_index("property_id")
        await db.inventory_items.create_index([("category", 1), ("subtype", 1)])
        # Auto-seed default schedule items onto any property that doesn't have any yet.
        async for prop in db.properties.find({}, {"_id": 0, "id": 1, "name": 1}):
            exists = await db.schedule_items.find_one({"property_id": prop["id"]}, {"_id": 1})
            if not exists:
                items = default_items_for_property(prop["id"], prop.get("name", ""))
                if items:
                    await db.schedule_items.insert_many([it.copy() for it in items])
            inv_exists = await db.inventory_items.find_one({"property_id": prop["id"]}, {"_id": 1})
            if not inv_exists:
                inv_items = default_inventory_for_property(prop["id"], prop.get("name", ""))
                if inv_items:
                    await db.inventory_items.insert_many([it.copy() for it in inv_items])
    except Exception as e:
        logger.exception("startup seed failed: %s", e)


# --- Stage 6A — Auth + users ------------------------------------------------

class LoginPayload(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str  # admin | manager | staff
    assigned_properties: Optional[List[str]] = []
    active: Optional[bool] = True


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    assigned_properties: Optional[List[str]] = None
    active: Optional[bool] = None


@api.post("/auth/login")
async def auth_login(payload: LoginPayload):
    email = (payload.email or "").strip().lower()
    user = await db.users.find_one({"email": email})
    if not user or not user.get("active"):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user["_id"] = None  # avoid leaking
    token = issue_token(user)
    return {"token": token, "user": safe_user(user)}


@api.get("/auth/me")
async def auth_me(user: Dict[str, Any] = Depends(current_user_dep)):
    return user


@api.post("/auth/logout")
async def auth_logout():
    # Stateless tokens — frontend discards the token. Endpoint exists for symmetry.
    return {"ok": True}


@api.get("/users")
async def users_list(_: Dict[str, Any] = Depends(require_role_dep("admin"))):
    cursor = db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1)
    items = await cursor.to_list(length=500)
    return {"items": items}


@api.post("/users")
async def users_create(
    payload: UserCreate,
    _: Dict[str, Any] = Depends(require_role_dep("admin")),
):
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=409, detail="Email already in use")
    doc = {
        "id": str(uuid.uuid4()),
        "name": payload.name.strip(),
        "email": email,
        "password_hash": hash_password(payload.password),
        "role": payload.role,
        "assigned_properties": payload.assigned_properties or [],
        "active": True if payload.active is None else payload.active,
        "created_at": _now_iso(),
    }
    await db.users.insert_one(doc.copy())
    return safe_user(doc)


@api.put("/users/{uid}")
async def users_update(
    uid: str,
    payload: UserUpdate,
    actor: Dict[str, Any] = Depends(require_role_dep("admin")),
):
    user = await db.users.find_one({"id": uid})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    patch: Dict[str, Any] = {}
    data = payload.model_dump()
    if data.get("name") is not None:
        patch["name"] = data["name"].strip()
    if data.get("role") is not None:
        if data["role"] not in ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        # Don't allow an admin to demote themselves
        if user["id"] == actor["id"] and data["role"] != "admin":
            raise HTTPException(status_code=400, detail="You cannot demote your own admin account")
        patch["role"] = data["role"]
    if data.get("password"):
        if len(data["password"]) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        patch["password_hash"] = hash_password(data["password"])
    if data.get("assigned_properties") is not None:
        patch["assigned_properties"] = data["assigned_properties"]
    if data.get("active") is not None:
        if user["id"] == actor["id"] and not data["active"]:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
        patch["active"] = bool(data["active"])
    if patch:
        await db.users.update_one({"id": uid}, {"$set": patch})
    doc = await db.users.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
    return doc


@api.delete("/users/{uid}")
async def users_delete(
    uid: str,
    actor: Dict[str, Any] = Depends(require_role_dep("admin")),
):
    if uid == actor["id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    res = await db.users.delete_one({"id": uid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


@api.get("/users/assignable")
async def users_assignable(_: Dict[str, Any] = Depends(current_user_dep)):
    """Lightweight directory used by Tasks/Properties assignment selects."""
    cursor = db.users.find(
        {"active": True},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1},
    ).sort("name", 1)
    items = await cursor.to_list(length=500)
    return {"items": items}


# --- Stage 6B — Tasks --------------------------------------------------------

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    category: str
    priority: Optional[str] = "medium"
    status: Optional[str] = "open"
    due_date: Optional[str] = None  # YYYY-MM-DD
    property_id: Optional[str] = None
    assignee_id: Optional[str] = None
    checklist: Optional[List[str]] = None
    schedule_item_id: Optional[str] = None
    schedule_subtype: Optional[str] = None
    inventory_item_id: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[str] = None
    property_id: Optional[str] = None
    assignee_id: Optional[str] = None
    schedule_item_id: Optional[str] = None
    schedule_subtype: Optional[str] = None
    inventory_item_id: Optional[str] = None


class PhotoCreate(BaseModel):
    data_url: str
    label: Optional[str] = ""


class ChecklistCreate(BaseModel):
    text: str


class ChecklistUpdate(BaseModel):
    done: Optional[bool] = None
    text: Optional[str] = None


class CommentCreate(BaseModel):
    body: str


async def _resolve_property(pid: Optional[str]) -> tuple[Optional[str], str]:
    if not pid:
        return None, ""
    p = await db.properties.find_one({"id": pid}, {"_id": 0, "id": 1, "name": 1})
    if not p:
        raise HTTPException(status_code=400, detail="Unknown property")
    return p["id"], p.get("name", "")


async def _resolve_assignee(uid: Optional[str]) -> tuple[Optional[str], str]:
    if not uid:
        return None, ""
    u = await db.users.find_one({"id": uid, "active": True}, {"_id": 0, "id": 1, "name": 1, "email": 1})
    if not u:
        raise HTTPException(status_code=400, detail="Unknown or inactive assignee")
    return u["id"], u.get("name") or u.get("email", "")


async def _load_task(tid: str, user: Dict[str, Any]) -> Dict[str, Any]:
    t = await db.tasks.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if not can_view_task(user, t):
        raise HTTPException(status_code=403, detail="Not allowed to view this task")
    return t


@api.get("/tasks/meta")
async def tasks_meta(_: Dict[str, Any] = Depends(current_user_dep)):
    return {
        "categories": [{"key": k, "label": TASK_CATEGORY_LABELS[k]} for k in TASK_CATEGORIES],
        "statuses": [{"key": k, "label": TASK_STATUS_LABELS[k]} for k in TASK_STATUSES],
        "priorities": [{"key": k, "label": TASK_PRIORITY_LABELS[k]} for k in TASK_PRIORITIES],
    }


@api.get("/tasks/stats")
async def tasks_stats(user: Dict[str, Any] = Depends(current_user_dep)):
    q = task_visibility_filter(user)
    cursor = db.tasks.find(q, {"_id": 0})
    items = await cursor.to_list(length=5000)
    stats = task_summarize(items)
    mine = [t for t in items if t.get("assignee_id") == user.get("id")]
    stats["mine_open"] = sum(1 for t in mine if t.get("status") != "done")
    return stats


@api.get("/tasks")
async def tasks_list(
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_id: Optional[str] = None,
    property_id: Optional[str] = None,
    mine: Optional[bool] = False,
    user: Dict[str, Any] = Depends(current_user_dep),
):
    q: Dict[str, Any] = {}
    base = task_visibility_filter(user)
    if base:
        q.update(base)
    if status:
        q["status"] = status
    if category:
        q["category"] = category
    if priority:
        q["priority"] = priority
    if assignee_id:
        q["assignee_id"] = assignee_id
    if property_id:
        q["property_id"] = property_id
    if mine:
        q["assignee_id"] = user.get("id")
    cursor = db.tasks.find(q, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(length=2000)
    # Strip photo data_urls from list responses — they're heavy. Keep counts.
    for t in items:
        photos = t.get("photos") or []
        t["photo_count"] = len(photos)
        t["photos"] = [{"id": p["id"], "label": p.get("label", "")} for p in photos]
    return {"items": items}


@api.post("/tasks")
async def tasks_create(
    payload: TaskCreate,
    actor: Dict[str, Any] = Depends(require_role_dep("admin", "manager")),
):
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    if payload.category not in TASK_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    if payload.priority and payload.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")
    if payload.status and payload.status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    prop_id, prop_name = await _resolve_property(payload.property_id)
    ass_id, ass_name = await _resolve_assignee(payload.assignee_id)
    doc = build_task_doc(
        title=payload.title,
        description=payload.description or "",
        category=payload.category,
        priority=payload.priority or "medium",
        status=payload.status or "open",
        due_date=payload.due_date,
        property_id=prop_id,
        property_name=prop_name,
        assignee_id=ass_id,
        assignee_name=ass_name,
        created_by=actor["id"],
        created_by_name=actor.get("name") or actor.get("email", ""),
        checklist_items=payload.checklist or [],
        schedule_item_id=payload.schedule_item_id,
        schedule_subtype=payload.schedule_subtype,
        inventory_item_id=payload.inventory_item_id,
    )
    await db.tasks.insert_one(doc.copy())
    # Mirror the linkage onto the schedule item (so the UI can show "open task" badge)
    if payload.schedule_item_id:
        await db.schedule_items.update_one(
            {"id": payload.schedule_item_id},
            {"$set": {"linked_task_id": doc["id"], "updated_at": task_now_iso()}},
        )
    if payload.inventory_item_id:
        await db.inventory_items.update_one(
            {"id": payload.inventory_item_id},
            {"$set": {"linked_task_id": doc["id"], "updated_at": task_now_iso()}},
        )
    doc.pop("_id", None)
    return doc


@api.get("/tasks/{tid}")
async def tasks_get(tid: str, user: Dict[str, Any] = Depends(current_user_dep)):
    return await _load_task(tid, user)


@api.put("/tasks/{tid}")
async def tasks_update(
    tid: str,
    payload: TaskUpdate,
    user: Dict[str, Any] = Depends(current_user_dep),
):
    task = await _load_task(tid, user)
    data = payload.model_dump(exclude_unset=True)

    # Staff can only flip status on their own task; nothing else.
    if not can_modify_task(user, task):
        only_status = set(data.keys()) <= {"status"}
        if not only_status:
            raise HTTPException(status_code=403, detail="Only admin/manager can edit task fields")
        if not can_update_status(user, task):
            raise HTTPException(status_code=403, detail="You can only update tasks assigned to you")

    patch: Dict[str, Any] = {}
    if "title" in data and data["title"] is not None:
        if not data["title"].strip():
            raise HTTPException(status_code=400, detail="Title is required")
        patch["title"] = data["title"].strip()
    if "description" in data and data["description"] is not None:
        patch["description"] = data["description"].strip()
    if "category" in data and data["category"]:
        if data["category"] not in TASK_CATEGORIES:
            raise HTTPException(status_code=400, detail="Invalid category")
        patch["category"] = data["category"]
    if "priority" in data and data["priority"]:
        if data["priority"] not in TASK_PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority")
        patch["priority"] = data["priority"]
    if "status" in data and data["status"]:
        if data["status"] not in TASK_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        patch["status"] = data["status"]
        if data["status"] == "done":
            patch["completed_at"] = task_now_iso()
            patch["completed_by"] = user["id"]
            patch["completed_by_name"] = user.get("name") or user.get("email", "")
        else:
            patch["completed_at"] = None
            patch["completed_by"] = None
            patch["completed_by_name"] = None
    if "due_date" in data:
        patch["due_date"] = data["due_date"] or None
    if "property_id" in data:
        pid, pname = await _resolve_property(data["property_id"])
        patch["property_id"] = pid
        patch["property_name"] = pname
    if "assignee_id" in data:
        aid, aname = await _resolve_assignee(data["assignee_id"])
        patch["assignee_id"] = aid
        patch["assignee_name"] = aname
    if "schedule_item_id" in data:
        patch["schedule_item_id"] = data["schedule_item_id"] or None
    if "schedule_subtype" in data:
        patch["schedule_subtype"] = data["schedule_subtype"] or None
    if "inventory_item_id" in data:
        patch["inventory_item_id"] = data["inventory_item_id"] or None

    patch["updated_at"] = task_now_iso()
    await db.tasks.update_one({"id": tid}, {"$set": patch})

    # If status flipped to 'done', try to bump a linked schedule item.
    if patch.get("status") == "done":
        await _maybe_bump_schedule_for_task(task, patch, user)
        await _maybe_bump_inventory_for_task(task, patch, user)

    doc = await db.tasks.find_one({"id": tid}, {"_id": 0})
    return doc


async def _maybe_bump_schedule_for_task(
    prev_task: Dict[str, Any],
    patch: Dict[str, Any],
    actor: Dict[str, Any],
) -> None:
    """Advance the matching schedule item when a task is completed."""
    sid = prev_task.get("schedule_item_id")
    item = None
    if sid:
        item = await db.schedule_items.find_one({"id": sid}, {"_id": 0})
    if not item:
        # Fallback: category + subtype + property match.
        subtype = prev_task.get("schedule_subtype")
        pid = prev_task.get("property_id")
        cat = prev_task.get("category")
        if subtype and pid and cat in ("compliance", "housekeeping"):
            item = await db.schedule_items.find_one(
                {"property_id": pid, "kind": cat, "subtype": subtype},
                {"_id": 0},
            )
    if not item:
        return
    completed_at = patch.get("completed_at") or task_now_iso()
    actor_name = actor.get("name") or actor.get("email", "")
    set_patch = bump_after_completion(item, completed_at, actor_name)
    await db.schedule_items.update_one({"id": item["id"]}, {"$set": set_patch})


async def _maybe_bump_inventory_for_task(
    prev_task: Dict[str, Any],
    patch: Dict[str, Any],
    actor: Dict[str, Any],
) -> None:
    """Restock the inventory item linked to this task — bumps current_count back to target."""
    iid = prev_task.get("inventory_item_id")
    if not iid:
        return
    item = await db.inventory_items.find_one({"id": iid}, {"_id": 0})
    if not item:
        return
    actor_name = actor.get("name") or actor.get("email", "")
    set_patch = inv_restock_patch(item, item.get("target_count") or item.get("current_count") or 0, actor_name)
    await db.inventory_items.update_one({"id": iid}, {"$set": set_patch})


@api.delete("/tasks/{tid}")
async def tasks_delete(
    tid: str,
    _: Dict[str, Any] = Depends(require_role_dep("admin", "manager")),
):
    task = await db.tasks.find_one({"id": tid}, {"_id": 0, "schedule_item_id": 1, "inventory_item_id": 1})
    res = await db.tasks.delete_one({"id": tid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    if task and task.get("schedule_item_id"):
        await db.schedule_items.update_one(
            {"id": task["schedule_item_id"], "linked_task_id": tid},
            {"$set": {"linked_task_id": None, "updated_at": task_now_iso()}},
        )
    if task and task.get("inventory_item_id"):
        await db.inventory_items.update_one(
            {"id": task["inventory_item_id"], "linked_task_id": tid},
            {"$set": {"linked_task_id": None, "updated_at": task_now_iso()}},
        )
    return {"deleted": True}


# Photos

@api.post("/tasks/{tid}/photos")
async def task_photo_add(
    tid: str,
    payload: PhotoCreate,
    user: Dict[str, Any] = Depends(current_user_dep),
):
    task = await _load_task(tid, user)
    if not (can_modify_task(user, task) or task.get("assignee_id") == user.get("id")):
        raise HTTPException(status_code=403, detail="Only the assignee or admin/manager can attach photos")
    if not payload.data_url.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="Photo must be a base64 image data URL")
    # Soft cap: 1.5 MB per image, 12 photos per task.
    if len(payload.data_url) > 1_600_000:
        raise HTTPException(status_code=413, detail="Image too large after compression — try a smaller photo")
    if len(task.get("photos") or []) >= 12:
        raise HTTPException(status_code=400, detail="Maximum 12 photos per task")
    photo = build_photo(data_url=payload.data_url, label=payload.label or "", user=user)
    await db.tasks.update_one(
        {"id": tid},
        {"$push": {"photos": photo}, "$set": {"updated_at": task_now_iso()}},
    )
    return photo


@api.delete("/tasks/{tid}/photos/{photo_id}")
async def task_photo_delete(
    tid: str,
    photo_id: str,
    user: Dict[str, Any] = Depends(current_user_dep),
):
    task = await _load_task(tid, user)
    if not (can_modify_task(user, task) or task.get("assignee_id") == user.get("id")):
        raise HTTPException(status_code=403, detail="Not allowed")
    await db.tasks.update_one(
        {"id": tid},
        {"$pull": {"photos": {"id": photo_id}}, "$set": {"updated_at": task_now_iso()}},
    )
    return {"deleted": True}


# Checklist

@api.post("/tasks/{tid}/checklist")
async def task_checklist_add(
    tid: str,
    payload: ChecklistCreate,
    user: Dict[str, Any] = Depends(current_user_dep),
):
    task = await _load_task(tid, user)
    if not can_modify_task(user, task):
        raise HTTPException(status_code=403, detail="Only admin/manager can edit checklists")
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")
    item = build_checklist_item(payload.text)
    await db.tasks.update_one(
        {"id": tid},
        {"$push": {"checklist": item}, "$set": {"updated_at": task_now_iso()}},
    )
    return item


@api.put("/tasks/{tid}/checklist/{item_id}")
async def task_checklist_update(
    tid: str,
    item_id: str,
    payload: ChecklistUpdate,
    user: Dict[str, Any] = Depends(current_user_dep),
):
    task = await _load_task(tid, user)
    # Anyone with view rights can toggle done/undone if it's their assigned task; admin/manager always.
    is_assignee = task.get("assignee_id") == user.get("id")
    is_mgr = can_modify_task(user, task)
    if not (is_mgr or is_assignee):
        raise HTTPException(status_code=403, detail="Not allowed")
    set_fields: Dict[str, Any] = {"updated_at": task_now_iso()}
    if payload.done is not None:
        set_fields["checklist.$[el].done"] = bool(payload.done)
        if payload.done:
            set_fields["checklist.$[el].done_at"] = task_now_iso()
            set_fields["checklist.$[el].done_by"] = user.get("id")
            set_fields["checklist.$[el].done_by_name"] = user.get("name") or user.get("email", "")
        else:
            set_fields["checklist.$[el].done_at"] = None
            set_fields["checklist.$[el].done_by"] = None
            set_fields["checklist.$[el].done_by_name"] = None
    if payload.text is not None:
        if not is_mgr:
            raise HTTPException(status_code=403, detail="Only admin/manager can rename checklist items")
        set_fields["checklist.$[el].text"] = payload.text.strip()
    res = await db.tasks.update_one(
        {"id": tid},
        {"$set": set_fields},
        array_filters=[{"el.id": item_id}],
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    return {"updated": True}


@api.delete("/tasks/{tid}/checklist/{item_id}")
async def task_checklist_delete(
    tid: str,
    item_id: str,
    user: Dict[str, Any] = Depends(current_user_dep),
):
    task = await _load_task(tid, user)
    if not can_modify_task(user, task):
        raise HTTPException(status_code=403, detail="Only admin/manager can edit checklists")
    await db.tasks.update_one(
        {"id": tid},
        {"$pull": {"checklist": {"id": item_id}}, "$set": {"updated_at": task_now_iso()}},
    )
    return {"deleted": True}


# Comments

@api.post("/tasks/{tid}/comments")
async def task_comment_add(
    tid: str,
    payload: CommentCreate,
    user: Dict[str, Any] = Depends(current_user_dep),
):
    task = await _load_task(tid, user)  # also enforces visibility
    if not payload.body.strip():
        raise HTTPException(status_code=400, detail="Comment cannot be empty")
    c = build_comment(body=payload.body, user=user)
    await db.tasks.update_one(
        {"id": tid},
        {"$push": {"comments": c}, "$set": {"updated_at": task_now_iso()}},
    )
    return c


# --- Stage 6C — Compliance & Housekeeping schedules --------------------------

class ScheduleItemCreate(BaseModel):
    property_id: str
    kind: str  # "compliance" | "housekeeping"
    subtype: str
    label: str
    cadence_days: int
    last_done_at: Optional[str] = None
    notes: Optional[str] = ""
    auto_task_lead_days: Optional[int] = None


class ScheduleItemUpdate(BaseModel):
    label: Optional[str] = None
    cadence_days: Optional[int] = None
    last_done_at: Optional[str] = None
    next_due_at: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None
    auto_task_lead_days: Optional[int] = None


async def _auto_create_tasks_for_schedules(actor: Dict[str, Any]) -> int:
    """Find schedule items whose next_due_at is inside the lead window with no
    open task, and create one. Returns the number of tasks newly created."""
    today = datetime.now(timezone.utc).date().isoformat()
    cursor = db.schedule_items.find(
        {"active": True, "linked_task_id": None},
        {"_id": 0},
    )
    items = await cursor.to_list(length=2000)
    created = 0
    for item in items:
        if not needs_task(item, today):
            continue
        # Resolve assignee: cleaner for housekeeping, manager for compliance.
        prop = await db.properties.find_one({"id": item["property_id"]}, {"_id": 0})
        if not prop:
            continue
        assignee_id = None
        if item["kind"] == "housekeeping":
            assignee_id = prop.get("cleaner_user_id") or prop.get("manager_user_id")
        else:
            assignee_id = prop.get("manager_user_id") or prop.get("cleaner_user_id")
        assignee_name = ""
        if assignee_id:
            u = await db.users.find_one({"id": assignee_id, "active": True}, {"_id": 0, "name": 1, "email": 1})
            if u:
                assignee_name = u.get("name") or u.get("email", "")
            else:
                assignee_id = None
        title = f"{item['label']} — {item.get('property_name') or prop.get('name', '')}"
        priority = task_priority_for(item, today)
        doc = build_task_doc(
            title=title,
            description=(item.get("notes") or "") + ("\n\nAuto-generated from schedule." if item.get("notes") else "Auto-generated from schedule."),
            category=item["kind"],
            priority=priority,
            status="open",
            due_date=item.get("next_due_at"),
            property_id=item["property_id"],
            property_name=item.get("property_name") or prop.get("name", ""),
            assignee_id=assignee_id,
            assignee_name=assignee_name,
            created_by=actor["id"],
            created_by_name=actor.get("name") or actor.get("email", "system"),
            schedule_item_id=item["id"],
            schedule_subtype=item.get("subtype"),
        )
        await db.tasks.insert_one(doc.copy())
        await db.schedule_items.update_one(
            {"id": item["id"]},
            {"$set": {"linked_task_id": doc["id"], "updated_at": task_now_iso()}},
        )
        created += 1
    return created


@api.get("/schedules/meta")
async def schedules_meta(_: Dict[str, Any] = Depends(current_user_dep)):
    return {
        "compliance_defaults": COMPLIANCE_DEFAULTS,
        "housekeeping_defaults": HOUSEKEEPING_DEFAULTS,
        "default_lead_days": DEFAULT_LEAD_DAYS,
    }


@api.get("/schedules")
async def schedules_list(
    property_id: Optional[str] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    user: Dict[str, Any] = Depends(current_user_dep),
):
    # Auto-sync open tasks on every list call. Cheap for small portfolios and
    # avoids running a background worker.
    if user.get("role") in ("admin", "manager"):
        await _auto_create_tasks_for_schedules(user)

    q: Dict[str, Any] = {}
    if user.get("role") == "staff":
        q["property_id"] = {"$in": user.get("assigned_properties") or ["__none__"]}
    if property_id:
        q["property_id"] = property_id
    if kind:
        q["kind"] = kind
    cursor = db.schedule_items.find(q, {"_id": 0}).sort([("kind", 1), ("label", 1)])
    items = await cursor.to_list(length=5000)
    today = datetime.now(timezone.utc).date().isoformat()
    enriched = []
    for it in items:
        it_status = status_for_item(it, today)
        if status and it_status != status:
            continue
        it["status"] = it_status
        enriched.append(it)
    summary = schedule_summarise(items)
    return {"items": enriched, "summary": summary}


@api.post("/schedules")
async def schedules_create(
    payload: ScheduleItemCreate,
    actor: Dict[str, Any] = Depends(require_role_dep("admin", "manager")),
):
    prop = await db.properties.find_one({"id": payload.property_id}, {"_id": 0, "id": 1, "name": 1})
    if not prop:
        raise HTTPException(status_code=400, detail="Unknown property")
    if payload.kind not in ("compliance", "housekeeping"):
        raise HTTPException(status_code=400, detail="kind must be compliance or housekeeping")
    if payload.cadence_days <= 0:
        raise HTTPException(status_code=400, detail="cadence_days must be > 0")
    item = build_schedule_item(
        property_id=prop["id"], property_name=prop.get("name", ""),
        kind=payload.kind, subtype=payload.subtype.strip(),
        label=payload.label.strip(), cadence_days=payload.cadence_days,
        last_done_at=payload.last_done_at, notes=payload.notes or "",
        lead_days=payload.auto_task_lead_days or DEFAULT_LEAD_DAYS,
    )
    await db.schedule_items.insert_one(item.copy())
    item.pop("_id", None)
    return item


@api.put("/schedules/{sid}")
async def schedules_update(
    sid: str,
    payload: ScheduleItemUpdate,
    _: Dict[str, Any] = Depends(require_role_dep("admin", "manager")),
):
    item = await db.schedule_items.find_one({"id": sid}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    data = payload.model_dump(exclude_unset=True)
    patch: Dict[str, Any] = {}
    if "label" in data and data["label"]:
        patch["label"] = data["label"].strip()
    if "cadence_days" in data and data["cadence_days"]:
        if data["cadence_days"] <= 0:
            raise HTTPException(status_code=400, detail="cadence_days must be > 0")
        patch["cadence_days"] = int(data["cadence_days"])
    if "notes" in data:
        patch["notes"] = (data["notes"] or "").strip()
    if "active" in data and data["active"] is not None:
        patch["active"] = bool(data["active"])
    if "auto_task_lead_days" in data and data["auto_task_lead_days"]:
        patch["auto_task_lead_days"] = int(data["auto_task_lead_days"])
    if "last_done_at" in data:
        patch["last_done_at"] = data["last_done_at"] or None
        cadence = int(patch.get("cadence_days") or item.get("cadence_days") or 365)
        # Recompute next_due_at unless caller provides one explicitly.
        if "next_due_at" not in data:
            base = data["last_done_at"] or datetime.now(timezone.utc).date().isoformat()
            patch["next_due_at"] = (datetime.fromisoformat(base).date() + timedelta(days=cadence)).isoformat()
    if "next_due_at" in data:
        patch["next_due_at"] = data["next_due_at"] or None
    patch["updated_at"] = task_now_iso()
    await db.schedule_items.update_one({"id": sid}, {"$set": patch})
    doc = await db.schedule_items.find_one({"id": sid}, {"_id": 0})
    doc["status"] = status_for_item(doc)
    return doc


@api.delete("/schedules/{sid}")
async def schedules_delete(
    sid: str,
    _: Dict[str, Any] = Depends(require_role_dep("admin", "manager")),
):
    res = await db.schedule_items.delete_one({"id": sid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


@api.post("/schedules/{sid}/mark-done")
async def schedules_mark_done(
    sid: str,
    actor: Dict[str, Any] = Depends(require_role_dep("admin", "manager")),
):
    item = await db.schedule_items.find_one({"id": sid}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    actor_name = actor.get("name") or actor.get("email", "")
    set_patch = bump_after_completion(item, datetime.now(timezone.utc).date().isoformat(), actor_name)
    # Also close any linked open task gracefully (mark it done).
    if item.get("linked_task_id"):
        await db.tasks.update_one(
            {"id": item["linked_task_id"]},
            {"$set": {
                "status": "done",
                "completed_at": task_now_iso(),
                "completed_by": actor["id"],
                "completed_by_name": actor_name,
                "updated_at": task_now_iso(),
            }},
        )
    await db.schedule_items.update_one({"id": sid}, {"$set": set_patch})
    doc = await db.schedule_items.find_one({"id": sid}, {"_id": 0})
    doc["status"] = status_for_item(doc)
    return doc


@api.post("/schedules/seed-defaults")
async def schedules_seed_defaults(
    property_id: str,
    _: Dict[str, Any] = Depends(require_role_dep("admin", "manager")),
):
    prop = await db.properties.find_one({"id": property_id}, {"_id": 0, "id": 1, "name": 1})
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    existing = await db.schedule_items.find(
        {"property_id": property_id},
        {"_id": 0, "kind": 1, "subtype": 1},
    ).to_list(length=500)
    existing_keys = {(e["kind"], e["subtype"]) for e in existing}
    items = default_items_for_property(prop["id"], prop.get("name", ""))
    to_insert = [it for it in items if (it["kind"], it["subtype"]) not in existing_keys]
    if to_insert:
        await db.schedule_items.insert_many([it.copy() for it in to_insert])
    return {"inserted": len(to_insert), "skipped": len(items) - len(to_insert)}


# --- Stage 6D — Apartment inventory tracker ---------------------------------

class InventoryItemCreate(BaseModel):
    property_id: str
    category: str
    subtype: str
    label: str
    unit: Optional[str] = "each"
    min_threshold: int
    target_count: int
    current_count: Optional[int] = None
    notes: Optional[str] = ""


class InventoryItemUpdate(BaseModel):
    label: Optional[str] = None
    unit: Optional[str] = None
    min_threshold: Optional[int] = None
    target_count: Optional[int] = None
    current_count: Optional[int] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


class InventoryRestockPayload(BaseModel):
    new_count: int


def _inv_visibility(user: Dict[str, Any]) -> Dict[str, Any]:
    if user.get("role") in ("admin", "manager"):
        return {}
    return {"property_id": {"$in": user.get("assigned_properties") or ["__none__"]}}


async def _auto_create_tasks_for_inventory(actor: Dict[str, Any]) -> int:
    cursor = db.inventory_items.find(
        {"active": True, "linked_task_id": None},
        {"_id": 0},
    )
    items = await cursor.to_list(length=5000)
    created = 0
    for item in items:
        if not inv_needs_task(item):
            continue
        prop = await db.properties.find_one({"id": item["property_id"]}, {"_id": 0})
        if not prop:
            continue
        assignee_id = prop.get("cleaner_user_id") or prop.get("manager_user_id")
        assignee_name = ""
        if assignee_id:
            u = await db.users.find_one({"id": assignee_id, "active": True}, {"_id": 0, "name": 1, "email": 1})
            if u:
                assignee_name = u.get("name") or u.get("email", "")
            else:
                assignee_id = None
        current = int(item.get("current_count") or 0)
        target = int(item.get("target_count") or 0)
        title = f"Restock {item['label']} — {item.get('property_name') or prop.get('name', '')}"
        desc_lines = [f"{item['label']}: {current} / target {target} {item.get('unit') or ''}".strip(),
                      f"Min threshold: {item.get('min_threshold')}"]
        if item.get("notes"):
            desc_lines.append(item["notes"])
        desc_lines.append("Auto-generated from inventory tracker.")
        doc = build_task_doc(
            title=title,
            description="\n".join(desc_lines),
            category="restock",
            priority=inv_task_priority(item),
            status="open",
            due_date=None,
            property_id=item["property_id"],
            property_name=item.get("property_name") or prop.get("name", ""),
            assignee_id=assignee_id,
            assignee_name=assignee_name,
            created_by=actor["id"],
            created_by_name=actor.get("name") or actor.get("email", "system"),
            inventory_item_id=item["id"],
        )
        await db.tasks.insert_one(doc.copy())
        await db.inventory_items.update_one(
            {"id": item["id"]},
            {"$set": {"linked_task_id": doc["id"], "updated_at": task_now_iso()}},
        )
        created += 1
    return created


@api.get("/inventory/meta", dependencies=AUTH_ANY)
async def inventory_meta():
    return {
        "categories": [{"key": k, "label": INV_CATEGORY_LABELS[k]} for k in INV_CATEGORIES],
        "defaults": INV_DEFAULTS,
    }


@api.get("/inventory")
async def inventory_list(
    property_id: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    user: Dict[str, Any] = Depends(current_user_dep),
):
    # Auto-create restock tasks on admin/manager list.
    if user.get("role") in ("admin", "manager"):
        await _auto_create_tasks_for_inventory(user)

    q = _inv_visibility(user)
    if property_id:
        q["property_id"] = property_id
    if category:
        q["category"] = category
    cursor = db.inventory_items.find(q, {"_id": 0}).sort([("category", 1), ("label", 1)])
    items = await cursor.to_list(length=10000)
    enriched = []
    for it in items:
        s = inv_status(it)
        if status and s != status:
            continue
        it["status"] = s
        enriched.append(it)
    return {"items": enriched, "summary": inv_summarise(items)}


@api.post("/inventory", dependencies=AUTH_MGR)
async def inventory_create(payload: InventoryItemCreate):
    prop = await db.properties.find_one({"id": payload.property_id}, {"_id": 0, "id": 1, "name": 1})
    if not prop:
        raise HTTPException(status_code=400, detail="Unknown property")
    if payload.category not in INV_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    if payload.min_threshold < 0 or payload.target_count < 0:
        raise HTTPException(status_code=400, detail="Counts must be non-negative")
    item = build_inventory_item(
        property_id=prop["id"], property_name=prop.get("name", ""),
        category=payload.category, subtype=payload.subtype.strip(),
        label=payload.label.strip(), unit=payload.unit or "each",
        min_threshold=payload.min_threshold, target_count=payload.target_count,
        current_count=payload.current_count, notes=payload.notes or "",
    )
    await db.inventory_items.insert_one(item.copy())
    item.pop("_id", None)
    item["status"] = inv_status(item)
    return item


@api.put("/inventory/{iid}", dependencies=AUTH_MGR)
async def inventory_update(iid: str, payload: InventoryItemUpdate):
    item = await db.inventory_items.find_one({"id": iid}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    data = payload.model_dump(exclude_unset=True)
    patch: Dict[str, Any] = {}
    if "label" in data and data["label"]:
        patch["label"] = data["label"].strip()
    if "unit" in data and data["unit"]:
        patch["unit"] = data["unit"].strip()
    for k in ("min_threshold", "target_count", "current_count"):
        if k in data and data[k] is not None:
            if int(data[k]) < 0:
                raise HTTPException(status_code=400, detail=f"{k} must be non-negative")
            patch[k] = int(data[k])
    if "notes" in data:
        patch["notes"] = (data["notes"] or "").strip()
    if "active" in data and data["active"] is not None:
        patch["active"] = bool(data["active"])
    patch["updated_at"] = task_now_iso()
    await db.inventory_items.update_one({"id": iid}, {"$set": patch})
    doc = await db.inventory_items.find_one({"id": iid}, {"_id": 0})
    doc["status"] = inv_status(doc)
    return doc


@api.delete("/inventory/{iid}", dependencies=AUTH_MGR)
async def inventory_delete(iid: str):
    res = await db.inventory_items.delete_one({"id": iid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


@api.post("/inventory/{iid}/restock", dependencies=AUTH_MGR)
async def inventory_restock(
    iid: str,
    payload: InventoryRestockPayload,
    actor: Dict[str, Any] = Depends(require_role_dep("admin", "manager")),
):
    item = await db.inventory_items.find_one({"id": iid}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    if payload.new_count < 0:
        raise HTTPException(status_code=400, detail="new_count must be non-negative")
    actor_name = actor.get("name") or actor.get("email", "")
    # Close any linked open task as 'done' (mark restock complete).
    if item.get("linked_task_id"):
        await db.tasks.update_one(
            {"id": item["linked_task_id"]},
            {"$set": {
                "status": "done",
                "completed_at": task_now_iso(),
                "completed_by": actor["id"],
                "completed_by_name": actor_name,
                "updated_at": task_now_iso(),
            }},
        )
    set_patch = inv_restock_patch(item, payload.new_count, actor_name)
    await db.inventory_items.update_one({"id": iid}, {"$set": set_patch})
    doc = await db.inventory_items.find_one({"id": iid}, {"_id": 0})
    doc["status"] = inv_status(doc)
    return doc


@api.post("/inventory/seed-defaults", dependencies=AUTH_MGR)
async def inventory_seed_defaults(property_id: str):
    prop = await db.properties.find_one({"id": property_id}, {"_id": 0, "id": 1, "name": 1})
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    existing = await db.inventory_items.find(
        {"property_id": property_id}, {"_id": 0, "category": 1, "subtype": 1},
    ).to_list(length=1000)
    existing_keys = {(e["category"], e["subtype"]) for e in existing}
    items = default_inventory_for_property(prop["id"], prop.get("name", ""))
    to_insert = [it for it in items if (it["category"], it["subtype"]) not in existing_keys]
    if to_insert:
        await db.inventory_items.insert_many([it.copy() for it in to_insert])
    return {"inserted": len(to_insert), "skipped": len(items) - len(to_insert)}


MANAGED_PROPERTIES = [
    # Captains Cove
    ("All Accessible Apartment", "27",  "Captains Cove",      "Apartment"),
    ("Ground Floor Apartment",   "29",  "Captains Cove",      "Apartment"),
    ("Ground Floor Apartment",   "31",  "Captains Cove",      "Apartment"),
    ("Ground Floor Apartment",   "33",  "Captains Cove",      "Apartment"),
    ("Ground Floor Apartment",   "35",  "Captains Cove",      "Apartment"),
    ("1st Floor Spa Apartment",  "28",  "Captains Cove",      "Apartment"),
    ("1st Floor Spa Apartment",  "30",  "Captains Cove",      "Apartment"),
    ("1st Floor Spa Apartment",  "32",  "Captains Cove",      "Apartment"),
    ("1st Floor Spa Apartment",  "34",  "Captains Cove",      "Apartment"),
    ("1st Floor Spa Apartment",  "36",  "Captains Cove",      "Apartment"),
    # The View Waterfront
    ("Waterfront Apartment",     "13",  "The View Waterfront", "Apartment"),
    ("Waterfront Apartment",     "14",  "The View Waterfront", "Apartment"),
    ("Waterfront Apartment",     "23",  "The View Waterfront", "Apartment"),
    ("The View — Waterfront Apartment", "12", "The View Waterfront", "Apartment"),
    # Captains Edge
    ("Captains Edge",            "18B", "Captains Edge",      "House"),
]


async def seed_managed_properties(db):
    """One-time seed of the 15 managed properties. Idempotent — skips if any exist."""
    count = await db.properties.count_documents({})
    if count > 0:
        return
    now = _now_iso()
    docs = []
    for prop_name, unit, complex_name, prop_type in MANAGED_PROPERTIES:
        display = f"{prop_name} — Unit {unit}"
        docs.append({
            "id": str(uuid.uuid4()),
            "name": display,
            "property_name": prop_name,
            "unit_number": unit,
            "complex": complex_name,
            "property_type": prop_type,
            "bedrooms": None,
            "bathrooms": None,
            "active": True,
            "notes": "",
            "created_at": now,
        })
    await db.properties.insert_many(docs)
    logger.info("Seeded %d managed properties", len(docs))


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


# Mount the API router at the very end so all endpoints (incl. Stage 6A auth) are registered
app.include_router(api)


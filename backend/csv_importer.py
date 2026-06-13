"""
Multi-platform CSV importer.

Handles five distinct file formats produced by Tokeet, VikBooking, Preno,
Guestpoint Person Detail Report and Guestpoint Customer Export. Each file
type has its own header layout, encoding quirks (BOM / Latin-1), date
formats and column mapping. This module centralises:

    - encoding detection (UTF-8 with silent Latin-1 fallback)
    - BOM stripping
    - platform detection (returns platform name + import mode)
    - per-platform header & row parsing
    - normalisation to the canonical reservation / enrichment shape
    - tolerant fallbacks for missing reservation_id / email / value / dates

Two import modes are emitted:
    - "booking_import"      → produces reservation rows (upserted)
    - "profile_enrichment"  → produces guest enrichment rows (stored in
                              guest_enrichments collection; no reservations)
"""
from __future__ import annotations

import io
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

BOM = "\ufeff"


# ---------------------------------------------------------------------------
# Encoding + BOM handling
# ---------------------------------------------------------------------------

def decode_csv_bytes(contents: bytes) -> str:
    """Decode an uploaded CSV. Tries UTF-8 first, silently falls back to
    Latin-1 (Windows-1252). Strips a leading UTF-8 BOM if present.
    The returned text is guaranteed to be a Python str (UTF-8 in memory)."""
    # Strip UTF-8 BOM if present at byte level.
    if contents.startswith(b"\xef\xbb\xbf"):
        contents = contents[3:]
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            text = contents.decode(enc)
            # Strip stray BOM that may have survived (e.g. inside string).
            if text.startswith(BOM):
                text = text[len(BOM):]
            return text
        except UnicodeDecodeError:
            continue
    # Last resort — replace undecodable bytes so we never reject the file.
    return contents.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def _peek_lines(text: str, n: int = 6) -> List[str]:
    return text.splitlines()[:n]


def detect_platform(text: str) -> Dict[str, Any]:
    """Identify the source platform from the first few raw CSV lines.
    Returns: {platform, mode, skip_rows, header_row}
    """
    lines = _peek_lines(text, 8)
    head = "\n".join(lines).lower()
    first = lines[0].lower() if lines else ""

    # 1) Guestpoint Person Detail (row 1 contains "Person Detail Report")
    if "person detail report" in first or "person detail report" in head[:200]:
        return {"platform": "Guestpoint Person Detail",
                "mode": "profile_enrichment", "skip_rows": 3, "header_row": 3}

    # 2) Preno (row 1 contains "Guest Booking Details")
    if "guest booking details" in first or "guest booking details" in head[:200]:
        return {"platform": "Preno",
                "mode": "booking_import", "skip_rows": 2, "header_row": 2}

    # 3) Tokeet — "RENTAL NAME" + "GUEST NAME" in headers (row 1)
    if "rental name" in first and "guest name" in first:
        return {"platform": "Tokeet",
                "mode": "booking_import", "skip_rows": 0, "header_row": 0}

    # 4) VikBooking — "Booking ID" + "Primary guest first name"
    if "booking id" in first and "primary guest" in first:
        return {"platform": "VikBooking",
                "mode": "booking_import", "skip_rows": 0, "header_row": 0}

    # 5) Guestpoint Customer Export — headers contain eMail + Total Bookings + Last Name
    if "email" in first and "total bookings" in first and "last name" in first:
        return {"platform": "Guestpoint Customer Export",
                "mode": "profile_enrichment", "skip_rows": 0, "header_row": 0}

    # Default: generic CSV (fall back to existing legacy mapping)
    return {"platform": "Generic",
            "mode": "booking_import", "skip_rows": 0, "header_row": 0}


# ---------------------------------------------------------------------------
# Date / number helpers (per-platform tolerant)
# ---------------------------------------------------------------------------

def parse_date(value: Any, fmts: Optional[List[str]] = None, *, dayfirst: bool = False) -> Optional[str]:
    """Parse a date string (returns ISO yyyy-mm-dd) trying:
       1. explicit format(s) provided,
       2. fallback to pandas.to_datetime with given dayfirst preference.
    Returns None if value is empty / unparseable."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip().strip(BOM)
    if not s:
        return None
    if fmts:
        for fmt in fmts:
            try:
                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                continue
    try:
        d = pd.to_datetime(s, errors="coerce", dayfirst=dayfirst)
        if pd.isna(d):
            return None
        return d.date().isoformat()
    except Exception:
        return None


_NUM_RE = re.compile(r"[^0-9.\-]")


def parse_money(value: Any) -> Optional[float]:
    """Strip currency prefixes ('AU $', 'A$', '$'), commas and spaces."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s:
        return None
    cleaned = _NUM_RE.sub("", s)
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int(value: Any) -> Optional[int]:
    f = parse_money(value)
    return int(f) if f is not None else None


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().strip(BOM))


def split_name(full: Any) -> Tuple[str, str]:
    """Split a 'First Last' style string. Trims double spaces. Returns ('', '')
    if input is empty."""
    s = clean_text(full)
    if not s:
        return "", ""
    parts = s.split(" ", 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Pandas read with skiprows / encoding-safe text
# ---------------------------------------------------------------------------

def read_dataframe(text: str, skip_rows: int) -> pd.DataFrame:
    """Read text into a DataFrame keeping all values as strings."""
    df = pd.read_csv(
        io.StringIO(text),
        skiprows=skip_rows,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
        encoding=None,  # already decoded
    )
    # Strip BOM and whitespace from header cells.
    df.columns = [clean_text(c) for c in df.columns]
    # Drop fully empty columns (Preno / Guestpoint have them between fields).
    df = df.loc[:, [c for c in df.columns if c]]
    # Strip whitespace + BOM from string cells.
    for col in df.columns:
        df[col] = df[col].map(lambda v: clean_text(v) if isinstance(v, str) else v)
    return df


# ---------------------------------------------------------------------------
# Auto reservation id (used when missing)
# ---------------------------------------------------------------------------

def make_reservation_id(prefix: str, checkin: Optional[str], row_idx: int, extra: str = "") -> str:
    chk = (checkin or datetime.utcnow().date().isoformat()).replace("-", "")
    suffix = f"-{extra}" if extra else ""
    return f"{prefix}-{chk}{suffix}-{str(row_idx).zfill(4)}"


# ---------------------------------------------------------------------------
# Platform-specific parsers
# ---------------------------------------------------------------------------

def parse_tokeet(df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    fmts = ["%d %b, %Y", "%d %B, %Y", "%d %b %Y", "%d %B %Y"]
    for idx, raw in enumerate(df.to_dict(orient="records"), start=1):
        guest_full = raw.get("GUEST NAME") or raw.get("Guest Name") or ""
        first, last = split_name(guest_full)
        checkin = parse_date(raw.get("Arrive"), fmts) or parse_date(raw.get("Arrive"))
        checkout = parse_date(raw.get("Depart"), fmts) or parse_date(raw.get("Depart"))
        booking_date = parse_date(raw.get("Booked Date"), fmts)
        rid = make_reservation_id("TOK", checkin, idx)
        rows.append({
            "reservation_id": rid,
            "guest_first_name": first,
            "guest_last_name": last,
            "guest_email": None,
            "property_name": clean_text(raw.get("RENTAL NAME")),
            "checkin_date": checkin,
            "checkout_date": checkout,
            "nights": parse_int(raw.get("NIGHTS")),
            "guest_count": None,
            "booking_value": parse_money(raw.get("TOTAL")),
            "raw_booking_source": clean_text(raw.get("Source")),
            "booking_date": booking_date,
            "is_cancelled": False,
        })
    return rows


def parse_vikbooking(df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, raw in enumerate(df.to_dict(orient="records"), start=1):
        checkin = parse_date(raw.get("Checkin date"), ["%d/%m/%Y"], dayfirst=True)
        checkout = parse_date(raw.get("Checkout date"), ["%d/%m/%Y"], dayfirst=True)
        booking_date = parse_date(raw.get("Created at"), ["%d/%m/%Y %H:%M", "%d/%m/%Y"], dayfirst=True)
        adults = parse_int(raw.get("Adults")) or 0
        children = parse_int(raw.get("Children")) or 0
        guest_count = (adults + children) if (adults or children) else None
        status = clean_text(raw.get("Status")).lower()
        cancelled_at = clean_text(raw.get("Cancelled at"))
        is_cancelled = (status == "cancelled") or bool(cancelled_at)
        rid = clean_text(raw.get("Booking ID")) or make_reservation_id("VIK", checkin, idx)
        rows.append({
            "reservation_id": rid,
            "guest_first_name": clean_text(raw.get("Primary guest first name")),
            "guest_last_name": clean_text(raw.get("Primary guest last name")),
            "guest_email": None,
            "property_name": clean_text(raw.get("Rooms")),
            "checkin_date": checkin,
            "checkout_date": checkout,
            "nights": None,  # let downstream compute from dates if needed
            "guest_count": guest_count,
            "booking_value": parse_money(raw.get("Total")),
            "raw_booking_source": clean_text(raw.get("Source")),
            "booking_date": booking_date,
            "is_cancelled": is_cancelled,
        })
    return rows


def parse_preno(df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, raw in enumerate(df.to_dict(orient="records"), start=1):
        first = clean_text(raw.get("First Name"))
        last = clean_text(raw.get("Last Name"))
        email = clean_text(raw.get("Email")) or None
        checkin = parse_date(raw.get("Check-in"), ["%d/%m/%Y"], dayfirst=True)
        checkout = parse_date(raw.get("Depart"), ["%d/%m/%Y"], dayfirst=True)
        # Source classification rule from spec.
        if email and email.lower().endswith("@guest.booking.com"):
            raw_src = "Booking.com"
        else:
            raw_src = "Direct"
        rid = make_reservation_id("PRE", checkin, idx, (last or "GUEST").upper().replace(" ", ""))
        rows.append({
            "reservation_id": rid,
            "guest_first_name": first,
            "guest_last_name": last,
            "guest_email": email,
            "property_name": clean_text(raw.get("Type")),
            "room_number": clean_text(raw.get("Room #")) or None,
            "checkin_date": checkin,
            "checkout_date": checkout,
            "nights": parse_int(raw.get("Nights")),
            "guest_count": None,
            "booking_value": None,
            "raw_booking_source": raw_src,
            "booking_date": None,
            "is_cancelled": False,
            # Enrichment data carried along for downstream guest profile updates.
            "phone": clean_text(raw.get("Phone")) or None,
            "city": clean_text(raw.get("City")) or None,
            "state": clean_text(raw.get("State")) or None,
            "country": clean_text(raw.get("Country")) or None,
            "company": clean_text(raw.get("Company")) or None,
        })
    return rows


def parse_guestpoint_person_detail(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Profile enrichment — guest name + total stays + total spend."""
    rows: List[Dict[str, Any]] = []
    for idx, raw in enumerate(df.to_dict(orient="records"), start=1):
        full = raw.get("Name") or ""
        first, last = split_name(full)
        if not first and not last:
            continue
        spend = parse_money(raw.get("Total Spend"))
        rows.append({
            "guest_first_name": first,
            "guest_last_name": last,
            "guest_email": None,
            "address": clean_text(raw.get("Address")) or None,
            "city": clean_text(raw.get("City")) or None,
            "state": clean_text(raw.get("State")) or None,
            "postcode": clean_text(raw.get("Postcode")) or None,
            "country": clean_text(raw.get("Country")) or None,
            "first_stay": parse_date(raw.get("First Stay"), ["%d/%m/%Y"], dayfirst=True),
            "last_stay": parse_date(raw.get("Last Stay"), ["%d/%m/%Y"], dayfirst=True),
            "nights_stayed": parse_int(raw.get("Nights Stayed")),
            "lifetime_spend_reported": spend,
            "source_platform": "Guestpoint",
        })
    return rows


def parse_guestpoint_customer_export(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Profile enrichment — full guest profile with email & contact."""
    rows: List[Dict[str, Any]] = []
    for idx, raw in enumerate(df.to_dict(orient="records"), start=1):
        first = clean_text(raw.get("First Name"))
        last = clean_text(raw.get("Last Name"))
        email = clean_text(raw.get("eMail")) or clean_text(raw.get("Email")) or None
        if not first and not last and not email:
            continue
        rows.append({
            "guest_first_name": first,
            "guest_last_name": last,
            "guest_email": email,
            "phone": clean_text(raw.get("Phone")) or None,
            "address": clean_text(raw.get("Address")) or None,
            "city": clean_text(raw.get("City")) or None,
            "postcode": clean_text(raw.get("ZIP")) or None,
            "country": clean_text(raw.get("Country")) or None,
            "gender": clean_text(raw.get("Gender")) or None,
            "date_of_birth": parse_date(raw.get("Date of Birth"), ["%d/%m/%Y"], dayfirst=True),
            "total_bookings_reported": parse_int(raw.get("Total Bookings")),
            "notes": clean_text(raw.get("Notes")) or None,
            "source_platform": "Guestpoint",
        })
    return rows


# ---------------------------------------------------------------------------
# Legacy generic parser (for already-supported "standard" CSVs)
# ---------------------------------------------------------------------------

GENERIC_ALIASES: Dict[str, List[str]] = {
    "reservation_id": ["reservationid", "bookingreference", "bookingref", "bookingid",
                       "reservationreference", "confirmationcode", "confirmationnumber", "id"],
    "guest_first_name": ["guestfirstname", "firstname", "fname", "guestfirst"],
    "guest_last_name": ["guestlastname", "lastname", "lname", "surname", "guestlast"],
    "guest_email": ["guestemail", "email", "emailaddress", "guestemailaddress", "e-mail"],
    "property_name": ["propertyname", "property", "listing", "listingname", "unit", "unitname"],
    "checkin_date": ["checkindate", "checkin", "arrivaldate", "arrival", "startdate"],
    "checkout_date": ["checkoutdate", "checkout", "departuredate", "departure", "enddate"],
    "nights": ["nights", "numberofnights", "numnights", "lengthofstay", "los"],
    "guest_count": ["guestcount", "numberofguests", "guests", "numguests", "pax", "noofguests"],
    "booking_value": ["bookingvalue", "totalvalue", "totalbookingvalue", "total", "grossamount",
                      "amount", "revenue", "netvalue", "payout"],
    "raw_booking_source": ["bookingsource", "source", "channel", "platform", "rawsource"],
    "booking_date": ["bookingdate", "datebooked", "reservationdate", "createddate", "createdat", "bookedon"],
    "is_cancelled": ["iscancelled", "cancelled", "canceled", "cancellationstatus", "status"],
}


def _norm_header(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _generic_mapping(headers: List[str]) -> Dict[str, Optional[str]]:
    norm = {_norm_header(h): h for h in headers}
    mapping: Dict[str, Optional[str]] = {}
    for canonical, aliases in GENERIC_ALIASES.items():
        found = None
        if _norm_header(canonical) in norm:
            found = norm[_norm_header(canonical)]
        else:
            for alias in aliases:
                if alias in norm:
                    found = norm[alias]
                    break
        mapping[canonical] = found
    return mapping


def parse_generic(df: pd.DataFrame) -> List[Dict[str, Any]]:
    mapping = _generic_mapping(list(df.columns))
    rows: List[Dict[str, Any]] = []
    for idx, raw in enumerate(df.to_dict(orient="records"), start=1):
        def g(field: str) -> Any:
            src = mapping.get(field)
            if not src:
                return None
            return raw.get(src)
        checkin = parse_date(g("checkin_date"))
        checkout = parse_date(g("checkout_date"))
        nights = parse_int(g("nights"))
        if nights is None and checkin and checkout:
            try:
                nights = (datetime.fromisoformat(checkout).date() - datetime.fromisoformat(checkin).date()).days
            except Exception:
                nights = None
        rid = clean_text(g("reservation_id"))
        if not rid:
            rid = make_reservation_id("GEN", checkin, idx)
        cancelled_v = g("is_cancelled")
        cancelled = False
        if cancelled_v is not None:
            s = str(cancelled_v).strip().lower()
            cancelled = s in {"y", "yes", "true", "1", "cancelled", "canceled", "cancel"}
        rows.append({
            "reservation_id": rid,
            "guest_first_name": clean_text(g("guest_first_name")),
            "guest_last_name": clean_text(g("guest_last_name")),
            "guest_email": clean_text(g("guest_email")) or None,
            "property_name": clean_text(g("property_name")),
            "checkin_date": checkin,
            "checkout_date": checkout,
            "nights": nights,
            "guest_count": parse_int(g("guest_count")),
            "booking_value": parse_money(g("booking_value")),
            "raw_booking_source": clean_text(g("raw_booking_source")),
            "booking_date": parse_date(g("booking_date")),
            "is_cancelled": cancelled,
        })
    return rows


# ---------------------------------------------------------------------------
# Row-level validation: ONLY skip when name AND check-in are both missing
# ---------------------------------------------------------------------------

def keep_row(row: Dict[str, Any]) -> bool:
    has_name = bool(row.get("guest_first_name") or row.get("guest_last_name"))
    has_checkin = bool(row.get("checkin_date"))
    has_email = bool(row.get("guest_email"))
    # For enrichment-mode rows (no checkin), keep if we have a name or email.
    if "checkin_date" not in row:
        return has_name or has_email
    # For booking rows, drop only when BOTH name and checkin are missing.
    return has_name or has_checkin


# ---------------------------------------------------------------------------
# Top-level public function
# ---------------------------------------------------------------------------

def parse_upload(contents: bytes, filename: str) -> Dict[str, Any]:
    text = decode_csv_bytes(contents)
    detection = detect_platform(text)
    platform = detection["platform"]
    mode = detection["mode"]
    skip = detection["skip_rows"]

    try:
        df = read_dataframe(text, skip_rows=skip)
    except Exception as e:
        return {
            "filename": filename,
            "platform": platform,
            "mode": mode,
            "rows": [],
            "headers": [],
            "row_errors": [{"row": skip + 1, "error": f"Could not parse CSV after skip: {e}"}],
            "total_rows": 0,
            "valid_rows": 0,
        }

    if df.empty:
        return {
            "filename": filename,
            "platform": platform,
            "mode": mode,
            "rows": [],
            "headers": list(df.columns),
            "row_errors": [],
            "total_rows": 0,
            "valid_rows": 0,
        }

    parsers = {
        "Tokeet": parse_tokeet,
        "VikBooking": parse_vikbooking,
        "Preno": parse_preno,
        "Guestpoint Person Detail": parse_guestpoint_person_detail,
        "Guestpoint Customer Export": parse_guestpoint_customer_export,
        "Generic": parse_generic,
    }
    parser = parsers[platform]
    all_rows = parser(df)

    kept: List[Dict[str, Any]] = []
    row_errors: List[Dict[str, Any]] = []
    for i, r in enumerate(all_rows, start=1):
        if keep_row(r):
            kept.append(r)
        else:
            row_errors.append({"row": i + skip,
                               "error": "Skipped — guest name AND check-in both missing"})

    return {
        "filename": filename,
        "platform": platform,
        "mode": mode,
        "skip_rows": skip,
        "headers": list(df.columns),
        "total_rows": len(all_rows),
        "valid_rows": len(kept),
        "row_errors": row_errors[:50],
        "rows": kept,
    }

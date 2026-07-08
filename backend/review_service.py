"""
Stage 6E — Guest review tracker.

One review per guest × source × review_date. Reviews can be created manually,
imported via a generic CSV, and analysed across properties and sources. When a
review has rating <= 3 and response_sent = False, the priority flag is auto-set
(a manual override can force it on/off).

Collection: `reviews`
"""
from __future__ import annotations

import io
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

SOURCE_PLATFORMS = [
    "Airbnb", "Booking.com", "Stayz", "VRBO", "Expedia",
    "Trip.com", "Direct", "Google", "Other",
]

CATEGORY_TAGS = [
    "Cleanliness", "Communication", "Location", "Value",
    "Accuracy", "Check-in", "Facilities",
]

SENTIMENTS = ["Positive", "Neutral", "Negative"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def suggest_sentiment(rating: Optional[int]) -> str:
    if rating is None:
        return "Neutral"
    if rating >= 5:
        return "Positive"
    if rating >= 3:
        return "Neutral"
    return "Negative"


def compute_priority_flag(*, rating: Optional[int], response_sent: bool, manual: Optional[bool]) -> bool:
    """Effective priority = manual override if set, else auto rule."""
    if manual is not None:
        return bool(manual)
    if rating is None:
        return False
    return (rating <= 3) and (not response_sent)


def normalise_source(raw: Optional[str]) -> str:
    if not raw:
        return "Other"
    s = str(raw).strip()
    if not s:
        return "Other"
    lookup = {p.lower(): p for p in SOURCE_PLATFORMS}
    key = re.sub(r"\s+", "", s.lower()).replace(".", "")
    for platform in SOURCE_PLATFORMS:
        if key == re.sub(r"\s+", "", platform.lower()).replace(".", ""):
            return platform
    return lookup.get(s.lower(), "Other")


def normalise_categories(values: Any) -> List[str]:
    """Accept list, comma-separated string, pipe-separated string."""
    if values is None:
        return []
    if isinstance(values, list):
        parts = values
    else:
        raw = str(values).strip()
        if not raw:
            return []
        parts = re.split(r"[,;|]", raw)
    result = []
    lookup = {c.lower(): c for c in CATEGORY_TAGS}
    for p in parts:
        k = str(p).strip().lower()
        if k in lookup and lookup[k] not in result:
            result.append(lookup[k])
    return result


def build_review(
    *,
    guest_name: str,
    guest_email: Optional[str],
    property_name: str,
    property_id: Optional[str],
    reservation_id: Optional[str],
    rating: Optional[int],
    source_platform: str,
    review_text: str,
    review_date: Optional[str],
    category_tags: List[str],
    sentiment: Optional[str],
    management_response: str,
    response_sent: bool,
    internal_notes: str,
    priority_flag_manual: Optional[bool],
    created_by: str,
    created_by_name: str,
) -> Dict[str, Any]:
    now = now_iso()
    if sentiment not in SENTIMENTS:
        sentiment = suggest_sentiment(rating)
    response_status = "responded" if response_sent else "unresponded"
    return {
        "id": str(uuid.uuid4()),
        "guest_name": (guest_name or "").strip(),
        "guest_email": ((guest_email or "").strip().lower() or None),
        "property_name": (property_name or "").strip(),
        "property_id": property_id or None,
        "reservation_id": reservation_id or None,
        "rating": int(rating) if rating is not None else None,
        "source_platform": normalise_source(source_platform),
        "review_text": (review_text or "").strip(),
        "review_date": review_date or None,
        "category_tags": normalise_categories(category_tags),
        "sentiment": sentiment,
        "management_response": (management_response or "").strip(),
        "response_sent": bool(response_sent),
        "response_status": response_status,
        "internal_notes": (internal_notes or "").strip(),
        "priority_flag_manual": priority_flag_manual,
        "priority_flag": compute_priority_flag(
            rating=int(rating) if rating is not None else None,
            response_sent=bool(response_sent),
            manual=priority_flag_manual,
        ),
        "created_by": created_by,
        "created_by_name": created_by_name,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

CSV_ALIASES = {
    "guest_name": ["guestname", "name", "guest"],
    "guest_email": ["guestemail", "email", "e-mail", "guestemailaddress"],
    "rating": ["rating", "stars", "score", "starrating"],
    "source_platform": ["sourceplatform", "source", "platform", "channel"],
    "review_text": ["reviewtext", "review", "comment", "reviewcomment", "body"],
    "review_date": ["reviewdate", "date", "createddate", "created"],
    "response_status": ["responsestatus", "responded", "status"],
    "property_name": ["propertyname", "property", "listing", "unit"],
    "reservation_id": ["reservationid", "bookingid", "bookingref"],
    "category_tags": ["categorytags", "categories", "tags"],
    "sentiment": ["sentiment"],
    "management_response": ["managementresponse", "reply", "hostresponse", "response"],
    "internal_notes": ["internalnotes", "notes"],
}


def _norm_header(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _map_headers(headers: List[str]) -> Dict[str, Optional[str]]:
    norm = {_norm_header(h): h for h in headers}
    mapping: Dict[str, Optional[str]] = {}
    for canonical, aliases in CSV_ALIASES.items():
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


def _parse_rating(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        r = int(float(str(v).strip()))
    except (ValueError, TypeError):
        return None
    if r < 1 or r > 5:
        return None
    return r


def _parse_bool(v: Any) -> bool:
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in {"y", "yes", "true", "1", "responded", "replied"}


def _parse_date(v: Any) -> Optional[str]:
    if v is None or v == "":
        return None
    try:
        d = pd.to_datetime(str(v).strip(), errors="coerce", dayfirst=True)
        if pd.isna(d):
            return None
        return d.date().isoformat()
    except Exception:
        return None


def parse_reviews_csv(contents: bytes, filename: str) -> Dict[str, Any]:
    # Reuse the CSV importer's encoding fallback.
    from csv_importer import decode_csv_bytes

    text = decode_csv_bytes(contents)
    try:
        df = pd.read_csv(
            io.StringIO(text),
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        )
    except Exception as e:
        return {"filename": filename, "rows": [], "row_errors": [{"row": 1, "error": str(e)}],
                "total_rows": 0, "valid_rows": 0, "headers": []}

    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
    mapping = _map_headers(list(df.columns))
    rows: List[Dict[str, Any]] = []
    row_errors: List[Dict[str, Any]] = []

    for idx, raw in enumerate(df.to_dict(orient="records"), start=1):
        def g(k: str) -> Any:
            src = mapping.get(k)
            return raw.get(src) if src else None

        guest_name = str(g("guest_name") or "").strip()
        guest_email = str(g("guest_email") or "").strip() or None
        rating = _parse_rating(g("rating"))
        review_text = str(g("review_text") or "").strip()

        # Row is only skipped when guest_name AND review_text are both blank AND no email.
        if not guest_name and not review_text and not guest_email:
            row_errors.append({"row": idx + 1, "error": "Skipped — no guest name, email or review text"})
            continue

        response_sent = _parse_bool(g("response_status"))
        rows.append({
            "guest_name": guest_name,
            "guest_email": guest_email.lower() if guest_email else None,
            "rating": rating,
            "source_platform": normalise_source(g("source_platform") or "Other"),
            "review_text": review_text,
            "review_date": _parse_date(g("review_date")),
            "response_sent": response_sent,
            "property_name": str(g("property_name") or "").strip(),
            "reservation_id": str(g("reservation_id") or "").strip() or None,
            "category_tags": normalise_categories(g("category_tags")),
            "sentiment": (str(g("sentiment") or "").strip().capitalize() if g("sentiment") else suggest_sentiment(rating)),
            "management_response": str(g("management_response") or "").strip(),
            "internal_notes": str(g("internal_notes") or "").strip(),
        })

    return {
        "filename": filename,
        "headers": list(df.columns),
        "mapping": mapping,
        "total_rows": len(df),
        "valid_rows": len(rows),
        "row_errors": row_errors[:50],
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def build_analytics(reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(reviews)
    if total == 0:
        return {
            "total": 0, "avg_rating": None, "response_rate": None,
            "priority_open": 0, "by_month": [], "by_property": [], "by_source": [],
        }

    rated = [r for r in reviews if r.get("rating") is not None]
    avg_rating = round(sum(r["rating"] for r in rated) / len(rated), 2) if rated else None
    responded = sum(1 for r in reviews if r.get("response_sent"))
    response_rate = round(responded / total * 100, 1) if total else 0.0
    priority_open = sum(1 for r in reviews if r.get("priority_flag"))

    # By month (YYYY-MM)
    monthly: Dict[str, Dict[str, Any]] = {}
    for r in reviews:
        d = r.get("review_date") or r.get("created_at", "")[:10]
        if not d or len(d) < 7:
            continue
        m = d[:7]
        agg = monthly.setdefault(m, {"month": m, "total": 0, "rating_sum": 0, "rated_count": 0})
        agg["total"] += 1
        if r.get("rating") is not None:
            agg["rating_sum"] += r["rating"]
            agg["rated_count"] += 1
    by_month = []
    for m in sorted(monthly.keys()):
        agg = monthly[m]
        by_month.append({
            "month": m,
            "total": agg["total"],
            "avg_rating": round(agg["rating_sum"] / agg["rated_count"], 2) if agg["rated_count"] else None,
        })

    # By property
    props: Dict[str, Dict[str, Any]] = {}
    for r in reviews:
        p = (r.get("property_name") or "—").strip() or "—"
        agg = props.setdefault(p, {"property_name": p, "total": 0, "rating_sum": 0, "rated_count": 0, "priority_open": 0})
        agg["total"] += 1
        if r.get("rating") is not None:
            agg["rating_sum"] += r["rating"]
            agg["rated_count"] += 1
        if r.get("priority_flag"):
            agg["priority_open"] += 1
    by_property = []
    for name, agg in props.items():
        by_property.append({
            "property_name": name,
            "total": agg["total"],
            "avg_rating": round(agg["rating_sum"] / agg["rated_count"], 2) if agg["rated_count"] else None,
            "priority_open": agg["priority_open"],
        })
    by_property.sort(key=lambda x: (-x["total"], x["property_name"]))

    # By source
    sources: Dict[str, Dict[str, Any]] = {}
    for r in reviews:
        s = r.get("source_platform") or "Other"
        agg = sources.setdefault(s, {"source_platform": s, "total": 0, "rating_sum": 0, "rated_count": 0, "responded": 0})
        agg["total"] += 1
        if r.get("rating") is not None:
            agg["rating_sum"] += r["rating"]
            agg["rated_count"] += 1
        if r.get("response_sent"):
            agg["responded"] += 1
    by_source = []
    for name, agg in sources.items():
        by_source.append({
            "source_platform": name,
            "total": agg["total"],
            "avg_rating": round(agg["rating_sum"] / agg["rated_count"], 2) if agg["rated_count"] else None,
            "response_rate": round(agg["responded"] / agg["total"] * 100, 1) if agg["total"] else 0.0,
        })
    by_source.sort(key=lambda x: -x["total"])

    return {
        "total": total,
        "avg_rating": avg_rating,
        "response_rate": response_rate,
        "priority_open": priority_open,
        "by_month": by_month,
        "by_property": by_property,
        "by_source": by_source,
    }

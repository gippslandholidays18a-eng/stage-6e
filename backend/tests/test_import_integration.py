"""
Live API integration tests for the CSV importer pipeline.

Covers the 16 review items: 5-platform detection, tolerance, encoding fallback,
profile-enrichment vs booking-import branches, RBAC, and generic backwards-compat.
"""
import io
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://str-analytics-core.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sourcebench.local"
ADMIN_PASSWORD = "ChangeMe123!"


# ---------- fixtures ----------

@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def staff_user(admin_headers):
    """Create a TEST_ staff user for RBAC test; cleaned up after."""
    payload = {
        "email": "TEST_csvimport_staff@sourcebench.local",
        "name": "TEST CSV Staff",
        "password": "StaffPass123!",
        "role": "staff",
        "assigned_properties": [],
    }
    r = requests.post(f"{API}/users", json=payload, headers=admin_headers, timeout=15)
    if r.status_code not in (200, 201):
        pytest.skip(f"Could not create staff: {r.status_code} {r.text}")
    uid = r.json().get("id") or r.json().get("user", {}).get("id")
    # login as staff
    lr = requests.post(f"{API}/auth/login", json={"email": payload["email"], "password": payload["password"]}, timeout=15)
    assert lr.status_code == 200, lr.text
    staff_token = lr.json()["token"]
    yield {"id": uid, "token": staff_token}
    if uid:
        requests.delete(f"{API}/users/{uid}", headers=admin_headers, timeout=15)


# ---------- sample CSV factories ----------

TOKEET_BOM_CSV = (
    "\ufeffRENTAL NAME,GUEST NAME,Booked Date,NIGHTS,Arrive,Depart,Source,TAX,FEE,DISCOUNTS,TOTAL\n"
    "Spa Apartment Unit 28,Jane Doe,\"10 May, 2026\",3,\"15 May, 2026\",\"18 May, 2026\",Airbnb,30,15,0,A$540.00\n"
)

VIKBOOKING_CSV = (
    "Booking ID,Source,Source type,Reference,Status,Created at,Checkin date,Checkout date,Rooms,Room types,"
    "Primary guest first name,Primary guest last name,Country,Adults,Children,Accommodation,Total,Cancelled at\n"
    "VIK-TEST-001,Booking.com,OTA,REF1,Confirmed,22/04/2026 14:32,01/05/2026,05/05/2026,Beach Villa,Villa,"
    "Alice,Brown,AU,2,1,400.00,520.50,\n"
    "VIK-TEST-002,Direct,Direct,REF2,Cancelled,23/04/2026 09:00,10/05/2026,12/05/2026,Apt,Studio,"
    "Bob,Green,AU,1,0,200.00,250.00,24/04/2026\n"
)

PRENO_CSV = (
    ",,,,,Guest Booking Details,,,,,,,,,,,\n"
    ",,,,,\"Tuesday, May 05 2026 1:42 PM\",,,,,,,,,,,\n"
    "Last Name,First Name,Title,Email,Company,Col6,State,City,Country,Col10,Phone,Check-in,Col13,Depart,Nights,Room #,Type\n"
    "Smith,Jane,Ms,jane@guest.booking.com,,,,Sydney,AU,,+61400,15/05/2026,,18/05/2026,3,A12,Studio\n"
    "Jones,Bob,Mr,bob@example.com,,,,Melbourne,AU,,+61400,20/05/2026,,22/05/2026,2,B05,Suite\n"
)

GP_PERSON_CSV = (
    ",,Person Detail Report,,,,,,,,,\n"
    ",,\"Monday, June 08 2026 3:31 PM\",,,,,,,,,,\n"
    ",,,,,,,,,Last 12 Months,,\n"
    "Name,Address,City,State,Postcode,Country,First Stay,Last Stay,Nights Stayed,Total Spend\n"
    "Jane  Doe,12 Bay Rd,Sydney,NSW,2000,AU,01/01/2026,01/05/2026,12,\"AU $4,500.00\"\n"
)

GP_CUSTOMER_HEADER = "ID,Last Name,First Name,eMail,Phone,Address,City,ZIP,Country,Gender,Date of Birth,Total Bookings,Notes\n"
# Latin-1 encoded body with 0xe0 byte for 'à'
GP_CUSTOMER_LATIN1 = (GP_CUSTOMER_HEADER + "1,Andr\xe0,Marie,marie+TESTcsv@example.com,+61400,1 St,Sydney,2000,AU,F,01/01/1990,3,VIP\n").encode("latin-1")

GENERIC_CSV = (
    "reservation_id,first_name,last_name,email,property,checkin,checkout,total,source\n"
    "TEST-GEN-001,John,Tester,john+TESTgen@example.com,Apartment 1,2026-06-01,2026-06-04,300.00,Airbnb\n"
)


def _upload(filename, content_bytes, headers):
    files = {"file": (filename, io.BytesIO(content_bytes), "text/csv")}
    return requests.post(f"{API}/import/preview", files=files, headers=headers, timeout=30)


# ---------- TESTS ----------

def test_health_root():
    r = requests.get(f"{API}/", timeout=10)
    assert r.status_code == 200


def test_preview_tokeet_bom(admin_headers):
    r = _upload("tokeet_bom.csv", TOKEET_BOM_CSV.encode("utf-8"), admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["platform"] == "Tokeet"
    assert data["mode"] == "booking_import"
    assert data["valid_rows"] >= 1
    row = data["rows"][0]
    assert row["reservation_id"].startswith("TOK-"), row
    assert row["booking_value"] == 540.0
    assert row["checkin_date"] == "2026-05-15"
    assert row["booking_date"] == "2026-05-10"
    assert row.get("guest_email") in (None, "")
    assert row["is_cancelled"] is False
    assert row.get("raw_booking_source") == "Airbnb"


def test_preview_vikbooking(admin_headers):
    r = _upload("vikbooking.csv", VIKBOOKING_CSV.encode("utf-8"), admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["platform"] == "VikBooking"
    assert data["mode"] == "booking_import"
    assert len(data["rows"]) == 2
    r0 = data["rows"][0]
    assert r0["reservation_id"] == "VIK-TEST-001"
    assert r0["checkin_date"] == "2026-05-01"
    assert r0["guest_count"] == 3  # 2 adults + 1 child
    assert r0["is_cancelled"] is False
    r1 = data["rows"][1]
    assert r1["is_cancelled"] is True  # status Cancelled + cancelled_at non-empty


def test_preview_preno(admin_headers):
    r = _upload("preno.csv", PRENO_CSV.encode("utf-8"), admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["platform"] == "Preno"
    assert data.get("skip_rows") == 2
    r0 = data["rows"][0]
    assert r0["reservation_id"].startswith("PRE-")
    assert "SMITH" in r0["reservation_id"]
    assert r0.get("booking_value") in (None, 0, 0.0)
    assert r0.get("booking_date") in (None, "")
    assert r0["is_cancelled"] is False
    assert r0.get("raw_booking_source") == "Booking.com"
    r1 = data["rows"][1]
    assert r1.get("raw_booking_source") == "Direct"


def test_preview_guestpoint_person_detail(admin_headers):
    r = _upload("gp_person.csv", GP_PERSON_CSV.encode("utf-8"), admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["platform"] == "Guestpoint Person Detail"
    assert data["mode"] == "profile_enrichment"
    assert data.get("skip_rows") == 3
    r0 = data["rows"][0]
    assert r0.get("guest_first_name") == "Jane"
    assert r0.get("guest_last_name") == "Doe"  # double-space normalised, split on first
    assert r0.get("lifetime_spend_reported") == 4500.0
    assert r0.get("nights_stayed") in (12, "12")
    assert r0.get("first_stay") == "2026-01-01"
    assert r0.get("last_stay") == "2026-05-01"
    assert "reservation_id" not in r0 or not r0.get("reservation_id")


def test_preview_guestpoint_customer_latin1(admin_headers):
    r = _upload("gp_customer.csv", GP_CUSTOMER_LATIN1, admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["platform"] == "Guestpoint Customer Export"
    assert data["mode"] == "profile_enrichment"
    r0 = data["rows"][0]
    assert r0.get("guest_last_name") == "Andrà"
    assert r0.get("guest_email") == "marie+TESTcsv@example.com"
    assert r0.get("total_bookings_reported") in (3, "3")


def test_preview_generic(admin_headers):
    r = _upload("generic.csv", GENERIC_CSV.encode("utf-8"), admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["platform"].lower() == "generic"
    assert data["mode"] == "booking_import"
    assert len(data["rows"]) == 1
    assert data["rows"][0]["reservation_id"] == "TEST-GEN-001"


def test_preview_garbage_bytes_does_not_400(admin_headers):
    garbage = b"\xff\xfe\x00\x01\x02bad,bytes,here\n\xc3\x28\xa0\xa1,x,y\n"
    r = _upload("garbage.csv", garbage, admin_headers)
    # MUST not be a hard 400 — should parse via latin-1 replace fallback
    assert r.status_code == 200, f"garbage upload returned {r.status_code} {r.text}"
    data = r.json()
    assert "rows" in data


def test_preview_tolerance_empty_total_imports(admin_headers):
    csv = (
        "RENTAL NAME,GUEST NAME,Booked Date,NIGHTS,Arrive,Depart,Source,TAX,FEE,DISCOUNTS,TOTAL\n"
        "Spa,Sam Smith,\"10 May, 2026\",3,\"15 May, 2026\",\"18 May, 2026\",Airbnb,0,0,0,\n"
    )
    r = _upload("tokeet_empty_total.csv", csv.encode("utf-8"), admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["valid_rows"] >= 1
    row = data["rows"][0]
    assert row["booking_value"] in (None, 0, 0.0)


def test_preview_tolerance_skip_only_when_name_and_checkin_missing(admin_headers):
    csv = (
        "RENTAL NAME,GUEST NAME,Booked Date,NIGHTS,Arrive,Depart,Source,TAX,FEE,DISCOUNTS,TOTAL\n"
        "Spa,Valid Guest,\"10 May, 2026\",3,\"15 May, 2026\",\"18 May, 2026\",Airbnb,0,0,0,100\n"
        ",, ,,,,,,,,\n"
    )
    r = _upload("tokeet_skip.csv", csv.encode("utf-8"), admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["valid_rows"] == 1
    errs = data.get("row_errors") or []
    joined = " ".join(str(e) for e in errs).lower()
    assert "skipped" in joined or "missing" in joined or len(errs) >= 1


def test_confirm_profile_enrichment_does_not_create_reservations(admin_headers):
    # Get baseline reservation count
    rc0 = requests.get(f"{API}/reservations", headers=admin_headers, timeout=20)
    assert rc0.status_code == 200
    body0 = rc0.json()
    base_count = len(body0.get("items", body0) if isinstance(body0, dict) else body0)

    # Upload GP customer (enrichment)
    pr = _upload("gp_customer.csv", GP_CUSTOMER_LATIN1, admin_headers)
    assert pr.status_code == 200
    pdata = pr.json()
    payload = {
        "filename": "gp_customer.csv",
        "rows": pdata["rows"],
        "mode": "profile_enrichment",
        "platform": pdata["platform"],
    }
    cr = requests.post(f"{API}/import/confirm", json=payload, headers=admin_headers, timeout=30)
    assert cr.status_code == 200, cr.text
    cbody = cr.json()
    assert cbody.get("mode") == "profile_enrichment"
    assert cbody.get("status") == "completed"
    assert "inserted" in cbody and "updated" in cbody
    assert cbody.get("total_rows") == len(pdata["rows"])

    # Reservation count UNCHANGED
    rc1 = requests.get(f"{API}/reservations", headers=admin_headers, timeout=20)
    body1 = rc1.json()
    new_count = len(body1.get("items", body1) if isinstance(body1, dict) else body1)
    assert new_count == base_count


def test_confirm_booking_import_inserts_new_only(admin_headers):
    # Build a fresh tokeet-style row with a unique check-in date so the
    # deterministic reservation_id (TOK-{checkin}-{idx}) doesn't clash with
    # a previous test run.
    import random
    day = random.randint(1, 28)
    month = random.randint(1, 12)
    year = 2099  # far future to avoid colliding with seed data
    arrive = f"{day:02d} " + ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][month-1] + f", {year}"
    depart_day = day + 2 if day + 2 <= 28 else day - 2
    depart = f"{depart_day:02d} " + ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][month-1] + f", {year}"
    booked = arrive  # fine
    csv = (
        "RENTAL NAME,GUEST NAME,Booked Date,NIGHTS,Arrive,Depart,Source,TAX,FEE,DISCOUNTS,TOTAL\n"
        f"TestProperty,TEST_csvImp Guest,\"{booked}\",3,\"{arrive}\",\"{depart}\",Airbnb,0,0,0,300\n"
    )
    pr = _upload("tokeet_confirm.csv", csv.encode("utf-8"), admin_headers)
    assert pr.status_code == 200
    pdata = pr.json()
    rows = pdata["rows"]
    assert len(rows) == 1
    res_id = rows[0]["reservation_id"]

    # Ensure clean slate (best-effort; no DELETE endpoint exists in API).
    # The unique 2099-future date above guarantees no collisions.

    # Reservation count before
    rc0 = requests.get(f"{API}/reservations", headers=admin_headers, timeout=20)
    body0 = rc0.json()
    base = len(body0.get("items", body0) if isinstance(body0, dict) else body0)

    payload = {"filename": "tokeet_confirm.csv", "rows": rows, "mode": "booking_import", "platform": "Tokeet"}
    cr = requests.post(f"{API}/import/confirm", json=payload, headers=admin_headers, timeout=30)
    assert cr.status_code == 200, cr.text
    cbody = cr.json()
    # booking_import response uses successful_rows / skipped_existing
    inserted = cbody.get("successful_rows", cbody.get("inserted", 0))
    assert inserted >= 1

    rc1 = requests.get(f"{API}/reservations", headers=admin_headers, timeout=20)
    body1 = rc1.json()
    after = len(body1.get("items", body1) if isinstance(body1, dict) else body1)
    assert after == base + inserted

    # Second confirm of same rows: should be skipped, not inserted
    cr2 = requests.post(f"{API}/import/confirm", json=payload, headers=admin_headers, timeout=30)
    cbody2 = cr2.json()
    assert cbody2.get("successful_rows", 0) == 0
    assert cbody2.get("skipped_existing", 0) >= 1

    # Cleanup: best-effort (no DELETE endpoint, so leave 2099-dated test row).
    # Mongo-direct cleanup not done here; row is harmless (year 2099 outside any analytics window).


def test_rbac_staff_cannot_call_import_preview(staff_user):
    headers = {"Authorization": f"Bearer {staff_user['token']}"}
    r = _upload("tokeet_rbac.csv", TOKEET_BOM_CSV.encode("utf-8"), headers)
    assert r.status_code == 403, f"expected 403 for staff, got {r.status_code} {r.text}"


def test_no_auth_returns_401():
    r = _upload("tokeet_noauth.csv", TOKEET_BOM_CSV.encode("utf-8"), {})
    assert r.status_code == 401

"""
Stage 6E — Guest review tracker.

Covers:
  - /api/reviews/meta shape
  - CRUD + priority/sentiment/response_status derivation rules
  - PUT priority_flag_manual override + revert to auto
  - PUT sentiment manual override does not auto-recompute
  - Validation (rating 0/6 -> 400, invalid source -> 400)
  - GET /api/reviews filters (property_id, source_platform, sentiment, rating_min/max,
    responded=yes/no, priority_only=true, q search)
  - GET /api/reviews/analytics shape and math
  - GET /api/reviews/for-guest sort + lowercase email match
  - CSV import preview + confirm
  - RBAC: unauthenticated 401, staff visibility filter + write 403, meta available
"""
import io
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sourcebench.local"
ADMIN_PASSWORD = "ChangeMe123!"


# ---------------- fixtures ----------------

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def properties(admin_headers):
    r = requests.get(f"{API}/properties", headers=admin_headers)
    assert r.status_code == 200
    items = r.json().get("items") or []
    assert len(items) >= 2, "Need at least 2 properties for RBAC scoping tests"
    return items


@pytest.fixture(scope="module")
def manager_user(admin_headers):
    pwd = "TestPass123!"
    payload = {
        "email": f"TEST_rev_mgr_{uuid.uuid4().hex[:6]}@example.com",
        "password": pwd,
        "name": "TEST Review Manager",
        "role": "manager",
    }
    r = requests.post(f"{API}/users", json=payload, headers=admin_headers)
    assert r.status_code in (200, 201), r.text
    user = r.json()
    login = requests.post(f"{API}/auth/login", json={"email": payload["email"], "password": pwd})
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    yield {
        "id": user.get("id"),
        "email": payload["email"],
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    if user.get("id"):
        requests.delete(f"{API}/users/{user['id']}", headers=admin_headers)


@pytest.fixture(scope="module")
def staff_user(admin_headers, properties):
    pwd = "TestPass123!"
    pid = properties[0]["id"]
    payload = {
        "email": f"TEST_rev_staff_{uuid.uuid4().hex[:6]}@example.com",
        "password": pwd,
        "name": "TEST Review Staff",
        "role": "staff",
        "assigned_properties": [pid],
    }
    r = requests.post(f"{API}/users", json=payload, headers=admin_headers)
    assert r.status_code in (200, 201), r.text
    user = r.json()
    login = requests.post(f"{API}/auth/login", json={"email": payload["email"], "password": pwd})
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    yield {
        "id": user.get("id"),
        "email": payload["email"],
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
        "property_id": pid,
    }
    if user.get("id"):
        requests.delete(f"{API}/users/{user['id']}", headers=admin_headers)


@pytest.fixture(scope="module")
def created_ids(admin_headers):
    """Collect ids and clean up at end of module."""
    ids = []
    yield ids
    for rid in ids:
        try:
            requests.delete(f"{API}/reviews/{rid}", headers=admin_headers)
        except Exception:
            pass


def _mk_review(admin_headers, ids, **overrides):
    body = {
        "guest_name": "TEST Guest",
        "guest_email": f"test_{uuid.uuid4().hex[:6]}@example.com",
        "property_name": "TEST Prop",
        "rating": 5,
        "source_platform": "Airbnb",
        "review_text": "TEST review",
        "response_sent": True,
    }
    body.update(overrides)
    r = requests.post(f"{API}/reviews", json=body, headers=admin_headers)
    assert r.status_code == 200, r.text
    doc = r.json()
    ids.append(doc["id"])
    return doc


# ---------------- META ----------------

class TestMeta:
    def test_meta_shape(self, admin_headers):
        r = requests.get(f"{API}/reviews/meta", headers=admin_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["sources"]) == 9
        assert set(data["sources"]) == {
            "Airbnb", "Booking.com", "Stayz", "VRBO", "Expedia",
            "Trip.com", "Direct", "Google", "Other",
        }
        assert len(data["categories"]) == 7
        assert set(data["categories"]) == {
            "Cleanliness", "Communication", "Location", "Value",
            "Accuracy", "Check-in", "Facilities",
        }
        assert data["sentiments"] == ["Positive", "Neutral", "Negative"]

    def test_meta_requires_auth(self):
        r = requests.get(f"{API}/reviews/meta")
        assert r.status_code == 401


# ---------------- CREATE + DERIVATION ----------------

class TestCreateAndDerivation:
    def test_create_low_rating_unresponded_autoflag(self, admin_headers, created_ids):
        doc = _mk_review(
            admin_headers, created_ids,
            guest_name="Alice", rating=2, source_platform="Airbnb", response_sent=False,
        )
        assert doc["sentiment"] == "Negative"
        assert doc["priority_flag"] is True
        assert doc["response_status"] == "unresponded"
        # Verify persistence
        r = requests.get(f"{API}/reviews/{doc['id']}", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["priority_flag"] is True

    def test_category_tags_persist(self, admin_headers, created_ids):
        doc = _mk_review(
            admin_headers, created_ids,
            rating=4, response_sent=False,
            category_tags=["Cleanliness", "Communication"],
        )
        assert set(doc["category_tags"]) == {"Cleanliness", "Communication"}
        r = requests.get(f"{API}/reviews/{doc['id']}", headers=admin_headers)
        assert set(r.json()["category_tags"]) == {"Cleanliness", "Communication"}

    def test_high_rating_positive(self, admin_headers, created_ids):
        doc = _mk_review(admin_headers, created_ids, rating=5, response_sent=True)
        assert doc["sentiment"] == "Positive"
        assert doc["priority_flag"] is False
        assert doc["response_status"] == "responded"

    def test_mid_rating_neutral(self, admin_headers, created_ids):
        doc = _mk_review(admin_headers, created_ids, rating=4, response_sent=True)
        assert doc["sentiment"] == "Neutral"

    def test_rating_3_unresponded_priority(self, admin_headers, created_ids):
        doc = _mk_review(admin_headers, created_ids, rating=3, response_sent=False)
        assert doc["priority_flag"] is True  # rating<=3 and not responded


# ---------------- UPDATE RULES ----------------

class TestUpdateRules:
    def test_flip_response_sent_clears_priority_but_keeps_sentiment(self, admin_headers, created_ids):
        doc = _mk_review(
            admin_headers, created_ids,
            rating=2, source_platform="Airbnb", response_sent=False,
        )
        rid = doc["id"]
        assert doc["priority_flag"] is True
        assert doc["sentiment"] == "Negative"

        r = requests.put(f"{API}/reviews/{rid}", headers=admin_headers, json={"response_sent": True})
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["priority_flag"] is False
        assert updated["response_status"] == "responded"
        assert updated["sentiment"] == "Negative", "Sentiment must NOT be auto-recomputed on update"

    def test_manual_priority_override_forces_true(self, admin_headers, created_ids):
        # 5-star responded (auto priority = False)
        doc = _mk_review(admin_headers, created_ids, rating=5, response_sent=True)
        rid = doc["id"]
        assert doc["priority_flag"] is False

        r = requests.put(f"{API}/reviews/{rid}", headers=admin_headers, json={"priority_flag_manual": True})
        assert r.status_code == 200, r.text
        assert r.json()["priority_flag"] is True

        # Revert with null → back to auto rule
        r = requests.put(f"{API}/reviews/{rid}", headers=admin_headers, json={"priority_flag_manual": None})
        assert r.status_code == 200, r.text
        assert r.json()["priority_flag"] is False

    def test_manual_sentiment_persists(self, admin_headers, created_ids):
        doc = _mk_review(admin_headers, created_ids, rating=2, response_sent=False)
        rid = doc["id"]
        r = requests.put(f"{API}/reviews/{rid}", headers=admin_headers, json={"sentiment": "Positive"})
        assert r.status_code == 200, r.text
        assert r.json()["sentiment"] == "Positive"

    def test_delete(self, admin_headers):
        # Create outside fixture (we want to verify deletion path)
        r = requests.post(f"{API}/reviews", json={
            "guest_name": "TEST Del", "rating": 5, "source_platform": "Direct",
        }, headers=admin_headers)
        rid = r.json()["id"]
        d = requests.delete(f"{API}/reviews/{rid}", headers=admin_headers)
        assert d.status_code == 200
        g = requests.get(f"{API}/reviews/{rid}", headers=admin_headers)
        assert g.status_code == 404


# ---------------- VALIDATION ----------------

class TestValidation:
    def test_rating_zero_400(self, admin_headers):
        r = requests.post(f"{API}/reviews", headers=admin_headers, json={
            "guest_name": "TEST", "rating": 0, "source_platform": "Airbnb",
        })
        assert r.status_code == 400

    def test_rating_six_400(self, admin_headers):
        r = requests.post(f"{API}/reviews", headers=admin_headers, json={
            "guest_name": "TEST", "rating": 6, "source_platform": "Airbnb",
        })
        assert r.status_code == 400

    def test_invalid_source_400(self, admin_headers):
        r = requests.post(f"{API}/reviews", headers=admin_headers, json={
            "guest_name": "TEST", "rating": 4, "source_platform": "NonExistent",
        })
        assert r.status_code == 400


# ---------------- FILTERS ----------------

@pytest.fixture(scope="module")
def filter_seed(admin_headers, properties, created_ids):
    """Seed a small set of reviews spanning sources/ratings/response states/properties."""
    pid_a = properties[0]["id"]
    pid_b = properties[1]["id"]
    pname_a = properties[0].get("name", "PropA")
    pname_b = properties[1].get("name", "PropB")

    marker = f"TESTFILT_{uuid.uuid4().hex[:6]}"
    seeded = []
    specs = [
        # (rating, source, response_sent, property_id, name)
        (5, "Airbnb", True, pid_a, pname_a),
        (4, "Booking.com", True, pid_a, pname_a),
        (2, "Airbnb", False, pid_b, pname_b),  # priority, negative
        (1, "Google", False, pid_b, pname_b),  # priority, negative
        (3, "Expedia", True, pid_a, pname_a),
    ]
    for i, (rating, src, resp, pid, pname) in enumerate(specs):
        body = {
            "guest_name": f"{marker} Guest {i}",
            "guest_email": f"{marker}_{i}@example.com",
            "property_name": pname,
            "property_id": pid,
            "rating": rating,
            "source_platform": src,
            "review_text": f"{marker} text {i}",
            "response_sent": resp,
            "review_date": f"2026-01-{10+i:02d}",
        }
        r = requests.post(f"{API}/reviews", json=body, headers=admin_headers)
        assert r.status_code == 200, r.text
        doc = r.json()
        seeded.append(doc)
        created_ids.append(doc["id"])
    return {"marker": marker, "reviews": seeded, "pid_a": pid_a, "pid_b": pid_b}


class TestFilters:
    def test_filter_property(self, admin_headers, filter_seed):
        r = requests.get(f"{API}/reviews", headers=admin_headers, params={
            "property_id": filter_seed["pid_a"], "q": filter_seed["marker"],
        })
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 3
        for it in items:
            assert it["property_id"] == filter_seed["pid_a"]

    def test_filter_source(self, admin_headers, filter_seed):
        r = requests.get(f"{API}/reviews", headers=admin_headers, params={
            "source_platform": "Airbnb", "q": filter_seed["marker"],
        })
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        for it in items:
            assert it["source_platform"] == "Airbnb"

    def test_filter_sentiment(self, admin_headers, filter_seed):
        r = requests.get(f"{API}/reviews", headers=admin_headers, params={
            "sentiment": "Negative", "q": filter_seed["marker"],
        })
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        for it in items:
            assert it["sentiment"] == "Negative"

    def test_filter_rating_range(self, admin_headers, filter_seed):
        r = requests.get(f"{API}/reviews", headers=admin_headers, params={
            "rating_min": 4, "rating_max": 5, "q": filter_seed["marker"],
        })
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        for it in items:
            assert 4 <= it["rating"] <= 5

    def test_filter_responded_yes(self, admin_headers, filter_seed):
        r = requests.get(f"{API}/reviews", headers=admin_headers, params={
            "responded": "yes", "q": filter_seed["marker"],
        })
        items = r.json()["items"]
        assert len(items) == 3
        assert all(it["response_sent"] for it in items)

    def test_filter_responded_no(self, admin_headers, filter_seed):
        r = requests.get(f"{API}/reviews", headers=admin_headers, params={
            "responded": "no", "q": filter_seed["marker"],
        })
        items = r.json()["items"]
        assert len(items) == 2
        assert all(not it["response_sent"] for it in items)

    def test_filter_priority_only(self, admin_headers, filter_seed):
        r = requests.get(f"{API}/reviews", headers=admin_headers, params={
            "priority_only": "true", "q": filter_seed["marker"],
        })
        items = r.json()["items"]
        assert len(items) == 2
        assert all(it["priority_flag"] for it in items)

    def test_filter_search(self, admin_headers, filter_seed):
        # search by unique text
        marker = filter_seed["marker"]
        r = requests.get(f"{API}/reviews", headers=admin_headers, params={"q": marker})
        items = r.json()["items"]
        assert len(items) == 5


# ---------------- ANALYTICS ----------------

class TestAnalytics:
    def test_analytics_shape_and_math(self, admin_headers, filter_seed):
        r = requests.get(f"{API}/reviews/analytics", headers=admin_headers)
        assert r.status_code == 200
        a = r.json()
        for k in ("total", "avg_rating", "response_rate", "priority_open",
                  "by_month", "by_property", "by_source"):
            assert k in a
        assert a["total"] >= 5
        assert isinstance(a["by_month"], list)
        assert isinstance(a["by_property"], list)
        assert isinstance(a["by_source"], list)
        # response_rate is a percentage in [0,100]
        assert 0 <= a["response_rate"] <= 100
        # avg_rating within valid range
        assert 1 <= a["avg_rating"] <= 5


# ---------------- FOR-GUEST ----------------

class TestForGuest:
    def test_for_guest_lowercase_and_sort(self, admin_headers, created_ids):
        email = f"TEST_ForGuest_{uuid.uuid4().hex[:6]}@Example.COM"
        low = email.lower()
        # Create two reviews with different dates for same email
        d1 = _mk_review(admin_headers, created_ids,
                        guest_email=email, rating=5, review_date="2026-01-05")
        d2 = _mk_review(admin_headers, created_ids,
                        guest_email=email, rating=3, review_date="2026-03-15")
        # Query with mixed case, expect lowercased match
        r = requests.get(f"{API}/reviews/for-guest", headers=admin_headers, params={"email": email})
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) >= 2
        # All returned rows must have lowercase email
        for it in items:
            if it.get("guest_email"):
                assert it["guest_email"] == low
        # Sorted by review_date desc
        ours = [it for it in items if it["id"] in (d1["id"], d2["id"])]
        assert len(ours) == 2
        assert ours[0]["review_date"] >= ours[1]["review_date"]


# ---------------- CSV IMPORT ----------------

class TestCsvImport:
    def test_preview_then_confirm(self, admin_headers, created_ids):
        marker = f"TESTCSV_{uuid.uuid4().hex[:6]}"
        csv = (
            "guest_name,guest_email,rating,source_platform,review_text,review_date,response_status,property_name\n"
            f"{marker} Alice,{marker}_a@example.com,5,Airbnb,Great stay,2026-02-01,responded,PropX\n"
            f"{marker} Bob,{marker}_b@example.com,4,Booking.com,Nice place,2026-02-02,responded,PropX\n"
            f"{marker} Carl,{marker}_c@example.com,1,Google,Bad,2026-02-03,unresponded,PropY\n"
        )
        files = {"file": (f"{marker}.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")}
        r = requests.post(f"{API}/reviews/import/preview", headers=admin_headers, files=files)
        assert r.status_code == 200, r.text
        preview = r.json()
        assert preview["total_rows"] == 3
        assert preview["valid_rows"] == 3
        assert len(preview["rows"]) == 3

        # Confirm
        r = requests.post(f"{API}/reviews/import/confirm", headers=admin_headers, json={
            "filename": preview.get("filename", f"{marker}.csv"),
            "rows": preview["rows"],
        })
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["inserted"] == 3
        assert c["failed"] == 0
        assert c["total"] == 3

        # Verify inserted rows appear
        r = requests.get(f"{API}/reviews", headers=admin_headers, params={"q": marker})
        items = r.json()["items"]
        assert len(items) == 3
        for it in items:
            created_ids.append(it["id"])
        # Row with rating=1 & unresponded should have priority_flag=True
        bad = [it for it in items if it["rating"] == 1]
        assert len(bad) == 1
        assert bad[0]["priority_flag"] is True
        assert bad[0]["sentiment"] == "Negative"
        # 5-star responded should be no priority
        good = [it for it in items if it["rating"] == 5]
        assert good[0]["priority_flag"] is False
        assert good[0]["sentiment"] == "Positive"


# ---------------- RBAC ----------------

class TestRBAC:
    def test_unauthenticated_list_401(self):
        r = requests.get(f"{API}/reviews")
        assert r.status_code == 401

    def test_staff_can_get_meta(self, staff_user):
        r = requests.get(f"{API}/reviews/meta", headers=staff_user["headers"])
        assert r.status_code == 200

    def test_staff_visibility_filter(self, staff_user, admin_headers, filter_seed):
        # Staff assigned to properties[0] should see only pid_a reviews
        r = requests.get(f"{API}/reviews", headers=staff_user["headers"], params={"q": filter_seed["marker"]})
        assert r.status_code == 200
        items = r.json()["items"]
        # All returned rows must have property_id == staff_user.property_id
        for it in items:
            assert it["property_id"] == staff_user["property_id"]

    def test_staff_post_403(self, staff_user):
        r = requests.post(f"{API}/reviews", headers=staff_user["headers"], json={
            "guest_name": "Nope", "rating": 4, "source_platform": "Airbnb",
        })
        assert r.status_code == 403

    def test_staff_put_403(self, staff_user, admin_headers, created_ids):
        doc = _mk_review(admin_headers, created_ids, rating=4, response_sent=True)
        r = requests.put(f"{API}/reviews/{doc['id']}", headers=staff_user["headers"], json={"rating": 3})
        assert r.status_code == 403

    def test_staff_delete_403(self, staff_user, admin_headers, created_ids):
        doc = _mk_review(admin_headers, created_ids, rating=4, response_sent=True)
        r = requests.delete(f"{API}/reviews/{doc['id']}", headers=staff_user["headers"])
        assert r.status_code == 403

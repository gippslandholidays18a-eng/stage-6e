"""
Stage 6D — Apartment inventory tracker + Stage-wide AUTH HARDENING regression.

Covers:
  - Auth hardening (no-token 401, admin 200, manager scoped 200/403, staff 200/403)
  - /api/digest/run?token=... still anonymous
  - /api/inventory/meta (7 categories, 25 defaults)
  - /api/inventory list (375 baseline = 15 props × 25), filters
  - /api/inventory CRUD + restock + seed-defaults
  - Auto-task creation when current_count <= min_threshold (no duplicates)
  - PUT /api/tasks status=done bumps linked inventory item back to target
  - DELETE /api/tasks clears linked_task_id on its inventory item
"""
import os
import time
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
    assert len(items) >= 1
    return items


@pytest.fixture(scope="module")
def manager_user(admin_headers):
    pwd = "TestPass123!"
    payload = {
        "email": f"TEST_mgr_{uuid.uuid4().hex[:6]}@example.com",
        "password": pwd,
        "name": "TEST Manager",
        "role": "manager",
    }
    r = requests.post(f"{API}/users", json=payload, headers=admin_headers)
    assert r.status_code in (200, 201), r.text
    user = r.json()
    login = requests.post(f"{API}/auth/login", json={"email": payload["email"], "password": pwd})
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    yield {"id": user.get("id"), "email": payload["email"], "token": token, "headers": {"Authorization": f"Bearer {token}"}}
    if user.get("id"):
        requests.delete(f"{API}/users/{user['id']}", headers=admin_headers)


@pytest.fixture(scope="module")
def staff_user(admin_headers, properties):
    pwd = "TestPass123!"
    pid = properties[0]["id"]
    payload = {
        "email": f"TEST_staff_{uuid.uuid4().hex[:6]}@example.com",
        "password": pwd,
        "name": "TEST Staff",
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


# ---------------- AUTH HARDENING ----------------

PROTECTED_GETS = [
    "/properties",
    "/reservations",
    "/analytics/summary",
    "/analytics/revenue",
    "/segments",
    "/guests",
    "/cancellations",
    "/scores/summary",
    "/commissions/summary",
    "/reports",
    "/campaigns",
    "/digest/preview",
    "/digest/history",
    "/settings/digest",
    "/settings/commissions",
    "/settings/offers",
    "/inventory",
    "/schedules",
]


class TestAuthNoToken:
    @pytest.mark.parametrize("path", PROTECTED_GETS)
    def test_no_token_401(self, path):
        r = requests.get(f"{API}{path}")
        assert r.status_code == 401, f"{path} expected 401, got {r.status_code}"


class TestAuthAdminToken:
    @pytest.mark.parametrize("path", PROTECTED_GETS)
    def test_admin_200(self, admin_headers, path):
        r = requests.get(f"{API}{path}", headers=admin_headers)
        assert r.status_code == 200, f"{path} expected 200, got {r.status_code}: {r.text[:200]}"


class TestAuthManager:
    # Manager allowed GETs (reads)
    @pytest.mark.parametrize("path", [
        "/properties", "/reservations", "/analytics/summary", "/analytics/revenue",
        "/segments", "/guests", "/cancellations", "/scores/summary",
        "/commissions/summary", "/reports", "/campaigns",
        "/settings/commissions", "/settings/offers", "/inventory", "/schedules",
    ])
    def test_manager_get_200(self, manager_user, path):
        r = requests.get(f"{API}{path}", headers=manager_user["headers"])
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"

    # Manager forbidden admin-only endpoints
    @pytest.mark.parametrize("path", [
        "/users", "/settings/digest", "/digest/preview", "/digest/history",
    ])
    def test_manager_admin_only_get_403(self, manager_user, path):
        r = requests.get(f"{API}{path}", headers=manager_user["headers"])
        assert r.status_code == 403, f"{path}: {r.status_code}"

    def test_manager_admin_only_writes_403(self, manager_user):
        h = manager_user["headers"]
        r = requests.put(f"{API}/settings/commissions", json={"airbnb": 0.14}, headers=h)
        assert r.status_code == 403
        r = requests.post(f"{API}/settings/offers", json={"code": "X", "label": "x", "value": 10}, headers=h)
        assert r.status_code == 403
        r = requests.put(f"{API}/settings/direct-target", json={"target_pct": 30}, headers=h)
        assert r.status_code == 403


class TestAuthStaff:
    def test_staff_properties_get_200(self, staff_user):
        r = requests.get(f"{API}/properties", headers=staff_user["headers"])
        assert r.status_code == 200

    def test_staff_properties_post_403(self, staff_user):
        r = requests.post(f"{API}/properties", json={"name": "TEST_no"}, headers=staff_user["headers"])
        assert r.status_code == 403

    def test_staff_analytics_summary_403(self, staff_user):
        r = requests.get(f"{API}/analytics/summary", headers=staff_user["headers"])
        assert r.status_code == 403

    def test_staff_segments_403(self, staff_user):
        r = requests.get(f"{API}/segments", headers=staff_user["headers"])
        assert r.status_code == 403

    def test_staff_inventory_filtered(self, staff_user):
        r = requests.get(f"{API}/inventory", headers=staff_user["headers"])
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) > 0
        for it in items:
            assert it["property_id"] == staff_user["property_id"]

    def test_staff_inventory_post_403(self, staff_user):
        r = requests.post(f"{API}/inventory", json={
            "property_id": staff_user["property_id"],
            "category": "linens", "subtype": "TEST_no", "label": "x",
            "min_threshold": 1, "target_count": 1, "current_count": 1,
        }, headers=staff_user["headers"])
        assert r.status_code == 403


class TestAuthDigestWebhook:
    def test_digest_run_no_token_anonymous(self):
        # Hits webhook with bad token but should return 401/403 from token check, not from JWT
        # Critical: should NOT require Authorization header (no 401 from JWT dep).
        # We can't trigger a real send; we just confirm that lacking JWT auth doesn't 401 with a JWT message.
        r = requests.post(f"{API}/digest/run?token=invalid_token_xyz")
        # acceptable: 401/403 token-based, NOT JWT auth 401
        assert r.status_code in (200, 400, 401, 403), f"unexpected {r.status_code}"
        # If 401 because of JWT, the body would contain 'Not authenticated' (FastAPI default).
        # Token-based handler should reply with 'Invalid token' or similar
        body = (r.text or "").lower()
        # We just assert that 'authorization' not required-style message — best-effort check
        assert "not authenticated" not in body or "token" in body


# ---------------- INVENTORY ----------------

class TestInventoryMeta:
    def test_meta_no_token_401(self):
        r = requests.get(f"{API}/inventory/meta")
        assert r.status_code == 401

    def test_meta_returns_7_cats_and_25_defaults(self, admin_headers):
        r = requests.get(f"{API}/inventory/meta", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert len(data["categories"]) == 7
        assert len(data["defaults"]) == 25


class TestInventoryList:
    def test_list_baseline_375(self, admin_headers):
        r = requests.get(f"{API}/inventory", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "summary" in body
        # At least 375 (baseline). Could be slightly higher if other tests left customs.
        assert len(body["items"]) >= 375, f"expected ≥375 baseline, got {len(body['items'])}"
        s = body["summary"]
        assert "total" in s and "by_status" in s and "by_category" in s

    def test_filter_category(self, admin_headers):
        r = requests.get(f"{API}/inventory?category=linens", headers=admin_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) > 0
        assert all(it["category"] == "linens" for it in items)

    def test_filter_property(self, admin_headers, properties):
        pid = properties[0]["id"]
        r = requests.get(f"{API}/inventory?property_id={pid}", headers=admin_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        # Should be roughly 25 (defaults)
        assert len(items) >= 1
        assert all(it["property_id"] == pid for it in items)


class TestInventoryCRUD:
    def test_full_crud(self, admin_headers, properties):
        pid = properties[0]["id"]
        # CREATE
        payload = {
            "property_id": pid,
            "category": "decor",
            "subtype": f"TEST_item_{uuid.uuid4().hex[:6]}",
            "label": "TEST decor item",
            "unit": "each",
            "min_threshold": 2,
            "target_count": 10,
            "current_count": 10,
            "notes": "test",
        }
        r = requests.post(f"{API}/inventory", json=payload, headers=admin_headers)
        assert r.status_code == 200, r.text
        item = r.json()
        iid = item["id"]
        assert item["label"] == "TEST decor item"
        assert item["status"] in ("ok", "below_target", "low", "out", "inactive")

        # UPDATE
        r = requests.put(f"{API}/inventory/{iid}", json={"notes": "updated"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["notes"] == "updated"

        # RESTOCK
        r = requests.post(f"{API}/inventory/{iid}/restock", json={"new_count": 5}, headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["current_count"] == 5
        assert body.get("last_restocked_at")
        assert body.get("last_restocked_by_name")

        # DELETE
        r = requests.delete(f"{API}/inventory/{iid}", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["deleted"] is True

    def test_seed_defaults_idempotent(self, admin_headers, properties):
        pid = properties[0]["id"]
        r = requests.post(f"{API}/inventory/seed-defaults?property_id={pid}", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "inserted" in data and "skipped" in data
        # All defaults should already exist
        assert data["inserted"] + data["skipped"] == 25


class TestInventoryAutoTask:
    def test_low_stock_creates_restock_task_no_duplicates(self, admin_headers, properties):
        pid = properties[0]["id"]
        # Create a custom item with min=5, current=3
        subtype = f"TEST_auto_{uuid.uuid4().hex[:6]}"
        payload = {
            "property_id": pid, "category": "kitchen", "subtype": subtype,
            "label": f"TEST low {subtype}", "unit": "each",
            "min_threshold": 5, "target_count": 10, "current_count": 3,
        }
        r = requests.post(f"{API}/inventory", json=payload, headers=admin_headers)
        assert r.status_code == 200, r.text
        iid = r.json()["id"]

        try:
            # Trigger inventory list (admin) → auto-create task
            r = requests.get(f"{API}/inventory", headers=admin_headers)
            assert r.status_code == 200
            # Find the item back
            item = next((it for it in r.json()["items"] if it["id"] == iid), None)
            assert item is not None
            tid = item.get("linked_task_id")
            assert tid, f"linked_task_id should be set after low-stock list, got {item}"

            # Verify task exists with category=restock, inventory_item_id=iid
            tr = requests.get(f"{API}/tasks", headers=admin_headers)
            assert tr.status_code == 200
            tasks_body = tr.json()
            tasks = tasks_body.get("items") if isinstance(tasks_body, dict) else tasks_body
            task = next((t for t in tasks if t.get("id") == tid), None)
            assert task is not None
            assert task["category"] == "restock"
            assert task.get("inventory_item_id") == iid
            assert task["priority"] in ("urgent", "high")  # current=3 → high (not 0)
            assert task["priority"] == "high"

            # Repeated GET should NOT create a second task
            r2 = requests.get(f"{API}/inventory", headers=admin_headers)
            assert r2.status_code == 200
            tr2 = requests.get(f"{API}/tasks", headers=admin_headers)
            tasks2_body = tr2.json()
            tasks2 = tasks2_body.get("items") if isinstance(tasks2_body, dict) else tasks2_body
            same_item_tasks = [t for t in tasks2 if t.get("inventory_item_id") == iid and t.get("status") != "done"]
            assert len(same_item_tasks) == 1, f"expected 1 open restock task, got {len(same_item_tasks)}"

            # Mark task done → item should snap back to target_count
            r = requests.put(f"{API}/tasks/{tid}", json={"status": "done"}, headers=admin_headers)
            assert r.status_code == 200

            # Verify item
            r = requests.get(f"{API}/inventory?property_id={pid}", headers=admin_headers)
            item2 = next((it for it in r.json()["items"] if it["id"] == iid), None)
            assert item2 is not None
            assert item2["current_count"] == 10, f"expected snap-back to target=10, got {item2['current_count']}"
            assert item2.get("linked_task_id") in (None, "")
            assert item2.get("last_restocked_at")
        finally:
            # cleanup item
            requests.delete(f"{API}/inventory/{iid}", headers=admin_headers)

    def test_priority_urgent_when_current_zero(self, admin_headers, properties):
        pid = properties[0]["id"]
        subtype = f"TEST_urgent_{uuid.uuid4().hex[:6]}"
        payload = {
            "property_id": pid, "category": "first_aid", "subtype": subtype,
            "label": f"TEST urgent {subtype}", "unit": "each",
            "min_threshold": 2, "target_count": 5, "current_count": 0,
        }
        r = requests.post(f"{API}/inventory", json=payload, headers=admin_headers)
        assert r.status_code == 200
        iid = r.json()["id"]
        try:
            r = requests.get(f"{API}/inventory", headers=admin_headers)
            item = next((it for it in r.json()["items"] if it["id"] == iid), None)
            assert item is not None and item.get("linked_task_id")
            tid = item["linked_task_id"]
            tr = requests.get(f"{API}/tasks", headers=admin_headers)
            tasks_body = tr.json()
            tasks = tasks_body.get("items") if isinstance(tasks_body, dict) else tasks_body
            task = next((t for t in tasks if t.get("id") == tid), None)
            assert task and task["priority"] == "urgent"
        finally:
            requests.delete(f"{API}/inventory/{iid}", headers=admin_headers)

    def test_delete_task_clears_linked_id(self, admin_headers, properties):
        pid = properties[0]["id"]
        subtype = f"TEST_deltask_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/inventory", json={
            "property_id": pid, "category": "cleaning", "subtype": subtype,
            "label": "TEST", "unit": "each",
            "min_threshold": 5, "target_count": 10, "current_count": 3,
        }, headers=admin_headers)
        iid = r.json()["id"]
        try:
            requests.get(f"{API}/inventory", headers=admin_headers)  # spawn task
            r = requests.get(f"{API}/inventory?property_id={pid}", headers=admin_headers)
            item = next((it for it in r.json()["items"] if it["id"] == iid), None)
            tid = item.get("linked_task_id")
            assert tid

            # Deactivate item so a new task is NOT auto-spawned upon next list,
            # then delete the task.
            requests.put(f"{API}/inventory/{iid}", json={"active": False}, headers=admin_headers)
            dr = requests.delete(f"{API}/tasks/{tid}", headers=admin_headers)
            assert dr.status_code == 200

            r = requests.get(f"{API}/inventory?property_id={pid}", headers=admin_headers)
            item2 = next((it for it in r.json()["items"] if it["id"] == iid), None)
            assert item2.get("linked_task_id") in (None, "")
        finally:
            requests.delete(f"{API}/inventory/{iid}", headers=admin_headers)


class TestRestockRBAC:
    def test_staff_restock_403(self, admin_headers, staff_user):
        # Find an item at staff's property
        r = requests.get(f"{API}/inventory?property_id={staff_user['property_id']}", headers=admin_headers)
        items = r.json()["items"]
        assert items
        iid = items[0]["id"]
        r = requests.post(f"{API}/inventory/{iid}/restock", json={"new_count": 5}, headers=staff_user["headers"])
        assert r.status_code == 403

"""
Stage 6B — Task management service.

Tasks tie operational work (maintenance, housekeeping, compliance, etc.) to a
property and (optionally) a staff member. Categories drive icons + filters.
Authoritative source of truth for status / priority / category vocabularies.

Schema (Mongo collection: `tasks`):
{
    id, title, description, category, status, priority,
    due_date (ISO date),
    property_id, property_name (denormalized — for display & easier indexing),
    assignee_id, assignee_name,
    created_by, created_by_name, created_at, updated_at,
    completed_at, completed_by,
    photos: [{id, data_url, label, uploaded_at, uploaded_by, uploaded_by_name}],
    checklist: [{id, text, done, done_at, done_by, done_by_name}],
    comments: [{id, user_id, user_name, body, created_at}],
}
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

CATEGORIES = [
    "maintenance",
    "housekeeping",
    "compliance",
    "guest_issue",
    "restock",
    "admin",
    "inspection",
    "photo_update",
]

CATEGORY_LABELS = {
    "maintenance": "Maintenance",
    "housekeeping": "Housekeeping",
    "compliance": "Compliance",
    "guest_issue": "Guest issue",
    "restock": "Restock",
    "admin": "Admin",
    "inspection": "Inspection",
    "photo_update": "Photo update",
}

STATUSES = ["open", "in_progress", "blocked", "done"]
STATUS_LABELS = {
    "open": "Open",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "done": "Done",
}

PRIORITIES = ["low", "medium", "high", "urgent"]
PRIORITY_LABELS = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "urgent": "Urgent",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def visibility_filter(user: Dict[str, Any]) -> Dict[str, Any]:
    """Mongo filter restricting a query to tasks the user is allowed to see."""
    role = user.get("role")
    if role in ("admin", "manager"):
        return {}
    # staff: tasks at their assigned properties OR tasks assigned to them
    assigned = user.get("assigned_properties") or []
    uid = user.get("id")
    return {
        "$or": [
            {"property_id": {"$in": assigned}} if assigned else {"property_id": "__none__"},
            {"assignee_id": uid},
        ]
    }


def can_modify_task(user: Dict[str, Any], task: Dict[str, Any]) -> bool:
    """Full edit (title, description, assignee, priority, due date, delete)."""
    return user.get("role") in ("admin", "manager")


def can_update_status(user: Dict[str, Any], task: Dict[str, Any]) -> bool:
    """Status transitions: admin/manager always; staff only on tasks assigned to them."""
    if user.get("role") in ("admin", "manager"):
        return True
    return task.get("assignee_id") == user.get("id")


def can_view_task(user: Dict[str, Any], task: Dict[str, Any]) -> bool:
    if user.get("role") in ("admin", "manager"):
        return True
    assigned = user.get("assigned_properties") or []
    if task.get("assignee_id") == user.get("id"):
        return True
    if task.get("property_id") in assigned:
        return True
    return False


def build_task_doc(
    *,
    title: str,
    description: str,
    category: str,
    priority: str,
    status: str,
    due_date: Optional[str],
    property_id: Optional[str],
    property_name: str,
    assignee_id: Optional[str],
    assignee_name: str,
    created_by: str,
    created_by_name: str,
    checklist_items: Optional[List[str]] = None,
    schedule_item_id: Optional[str] = None,
    schedule_subtype: Optional[str] = None,
    inventory_item_id: Optional[str] = None,
) -> Dict[str, Any]:
    now = now_iso()
    checklist = [
        {
            "id": new_id(),
            "text": (t or "").strip(),
            "done": False,
            "done_at": None,
            "done_by": None,
            "done_by_name": None,
        }
        for t in (checklist_items or [])
        if (t or "").strip()
    ]
    return {
        "id": new_id(),
        "title": title.strip(),
        "description": (description or "").strip(),
        "category": category,
        "status": status if status in STATUSES else "open",
        "priority": priority if priority in PRIORITIES else "medium",
        "due_date": due_date or None,
        "property_id": property_id or None,
        "property_name": property_name or "",
        "assignee_id": assignee_id or None,
        "assignee_name": assignee_name or "",
        "created_by": created_by,
        "created_by_name": created_by_name,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "completed_by": None,
        "completed_by_name": None,
        "photos": [],
        "checklist": checklist,
        "comments": [],
        "schedule_item_id": schedule_item_id or None,
        "schedule_subtype": schedule_subtype or None,
        "inventory_item_id": inventory_item_id or None,
    }


def build_photo(*, data_url: str, label: str, user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": new_id(),
        "data_url": data_url,
        "label": (label or "").strip(),
        "uploaded_at": now_iso(),
        "uploaded_by": user.get("id"),
        "uploaded_by_name": user.get("name") or user.get("email", ""),
    }


def build_checklist_item(text: str) -> Dict[str, Any]:
    return {
        "id": new_id(),
        "text": text.strip(),
        "done": False,
        "done_at": None,
        "done_by": None,
        "done_by_name": None,
    }


def build_comment(*, body: str, user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": new_id(),
        "user_id": user.get("id"),
        "user_name": user.get("name") or user.get("email", ""),
        "body": body.strip(),
        "created_at": now_iso(),
    }


def summarize(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Lightweight stats — used by the dashboard widget and the Tasks page header."""
    by_status = {s: 0 for s in STATUSES}
    by_priority = {p: 0 for p in PRIORITIES}
    overdue = 0
    today = datetime.now(timezone.utc).date().isoformat()
    for t in tasks:
        s = t.get("status") or "open"
        by_status[s] = by_status.get(s, 0) + 1
        p = t.get("priority") or "medium"
        by_priority[p] = by_priority.get(p, 0) + 1
        due = t.get("due_date")
        if due and s != "done" and due < today:
            overdue += 1
    return {
        "total": len(tasks),
        "by_status": by_status,
        "by_priority": by_priority,
        "overdue": overdue,
    }

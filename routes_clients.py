"""
routes_clients.py - CLIENT ONBOARDING, a default tab of the Department Database (build 85).

The flow (from the customer workflow diagram):

  Sales user fills 2 pages ......... 1 client info + its contacts (BIN, BIN address, TIN;
                                     Client contact and HRC Technologies Ltd contacts,
                                     each account manager / technical / billing),
                                     2 services (one SOF per service, several allowed)
  Click Save ....................... the request goes to the Sales admin for approval
  Sales admin ...................... approves or rejects
      rejected ..................... goes back to the Sales user, who fixes it and saves again
      approved ..................... the client is saved and appears in the client dropdown
  Revenue Assurance ................ sees it first (view only)
  Transmission, Core, Technical .... see the full record
  SAN report ....................... ONE upload only, by any of Transmission / Core / Technical
  Revenue Assurance + Sales ........ receive the SAN report
  Revenue Assurance ................ edits each SOF's activation date after the SAN report
  Finance .......................... receives the final record

Which department plays which part is set once on the setup page (portal admin);
until it is saved, departments are matched by name (Sales, Revenue Assurance,
Transmission, Core, Technical support, Finance).

The two Add Client pages are configurable (build 93): the Sales & Marketing
admin sets each page's fields (column name, input type, required or not) on
the form setup page. The fields the client was built with are the defaults;
the activation date lives on every SOF (page 2), never on the client page.
Every SOF has its own Download PDF button (one PDF per SOF) and its own
share code HRC-##### for the QR on that PDF.

Status of a client: pending -> approved -> san_uploaded -> completed
                    pending -> rejected -> (Sales saves again) -> pending

Used by: app.py (registers it, tab link), routes_deptdb.py (list page = tab "clients").
Uses: core.py, models.py, routes_deptdb.py (file saving), utils.py
Templates: deptdb_clients, client_form, client_detail, client_setup, client_form_setup, sof_code.
"""
import calendar
import json
import os
import re
from datetime import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for

import config
import exports
import routes_deptdb
from auth import login_required
from core import ddb_is_tab_admin, ddb_shared_tabs, ddb_tabs, dept_member_ids, external_url, new_random_code_text, next_client_serial, notify
from models import get_db, log, setting_get, setting_set
from utils import is_portal_admin, like_pattern, page_info

bp = Blueprint("clients", __name__, url_prefix="/clients")

# (key, label, what the department does in the flow)
FLOW_ROLES = [
    ("sales", "Sales", "Creates the client. Its department admin approves or rejects."),
    ("revenue_assurance", "Revenue Assurance", "Sees the approved client first (view only), gets the SAN report, edits each SOF's activation date, forwards the final record to Finance."),
    ("transmission", "Transmission", "Views the full record and may upload the SAN report."),
    ("core", "Core", "Views the full record and may upload the SAN report."),
    ("technical", "Technical support", "Views the full record and may upload the SAN report."),
    ("finance", "Finance", "Receives the final record once Revenue Assurance forwards it."),
]
ROLE_KEYS = [k for k, _l, _d in FLOW_ROLES]
ROLE_LABEL = {k: label for k, label, _d in FLOW_ROLES}
SAN_ROLES = ("transmission", "core", "technical")           # may upload the one SAN report
REVIEW_ROLES = ("revenue_assurance",) + SAN_ROLES            # see a client once it is approved

STATUS_LABEL = {
    "pending": "Waiting for approval",
    "rejected": "Rejected",
    "approved": "Approved · waiting for Revenue Assurance",
    "forwarded": "Forwarded by Revenue Assurance · waiting for SAN report",
    "san_uploaded": "SAN report uploaded - waiting for Revenue Assurance",
    "completed": "Completed",
}
ALL_STATUSES = tuple(STATUS_LABEL)
APPROVED_STATES = ("approved", "forwarded", "san_uploaded", "completed")
FORWARDED_STATES = ("forwarded", "san_uploaded", "completed")  # Transmission, Core, Technical see it from here on
MAX_ROWS = 30   # services per client (the contact tables cap themselves: one row per Type)

# Build 102: every SOF has its own state. Pending (yellow) while its
# change is going through the flow again, Activated (green) once it is
# live, Terminated (red) once its termination has taken effect.
SOF_STATUSES = ("pending", "activated", "terminated")
SOF_STATUS_LABEL = {"pending": "Pending", "activated": "Activated", "terminated": "Terminated"}


@bp.app_template_filter("client_no")
def client_no(c):
    """The client's serial number, from 1 (build 96). Takes the client
    row; a row without a serial (or an id on its own) falls back to the
    id. Build 110: the serial is the client's own number, stored apart
    from the id — it closes ranks when a client is deleted, while the id
    never changes."""
    try:
        serial = c["serial"]
    except (TypeError, KeyError, IndexError):
        serial = None
    if serial:
        return str(serial)
    try:
        return str(c["id"])
    except (TypeError, KeyError, IndexError):
        return str(int(c))


@bp.app_template_filter("client_status")
def client_status(value):
    return STATUS_LABEL.get(value, value)


# ---------------------------------------------------------------- which department plays which part
def _date_or_month_start(value):
    """A YYYY-MM-DD date as-is, or a YYYY-MM month as its first day;
    anything else (including an impossible date) is dropped."""
    if not value:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            return ""
    if re.fullmatch(r"\d{4}-\d{2}", value):
        return value + "-01"
    return ""


def _date_or_month_end(value):
    """A YYYY-MM-DD date as-is, or a YYYY-MM month as its last day;
    anything else (including an impossible date) is dropped."""
    if not value:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            return ""
    if re.fullmatch(r"\d{4}-\d{2}", value):
        y, m = int(value[:4]), int(value[5:7])
        if 1 <= m <= 12:
            return "%s-%02d" % (value, calendar.monthrange(y, m)[1])
        return ""
    return ""


def _guess_dept(role, names):
    """Match a department by its name when the setup page was never saved."""
    for did, name in names:
        if role == "core":
            hit = name == "core" or name.startswith("core ") or name.endswith(" core")
        elif role == "revenue_assurance":
            hit = "revenue assurance" in name
        elif role == "technical":
            hit = "technical support" in name
        else:
            hit = role in name
        if hit:
            return did
    if role == "technical":                      # the starter department is just called "Technical"
        for did, name in names:
            if name == "technical":
                return did
    return None


def flow_depts(db):
    """{role: department id or None} for the six parts of the flow (cached per request)."""
    cached = g.get("_client_flow")
    if cached is not None:
        return cached
    saved = {r["setting_key"]: r["value"] for r in
             db.execute("SELECT setting_key, value FROM settings WHERE setting_key LIKE 'clientflow_%'").fetchall()}
    names = None
    out = {}
    for role in ROLE_KEYS:
        raw = saved.get("clientflow_" + role)
        if raw is None:                          # never set up: guess from the department names
            if names is None:
                names = [(r["id"], (r["name"] or "").strip().lower())
                         for r in db.execute("SELECT id, name FROM departments ORDER BY id").fetchall()]
            out[role] = _guess_dept(role, names)
        else:
            out[role] = int(raw) if str(raw).isdigit() else None
    g._client_flow = out
    return out


def user_roles(db, user):
    """The parts of the flow the user's department plays (a set of role keys)."""
    dept_id = user["department_id"]
    if not dept_id:
        return set()
    return {role for role, did in flow_depts(db).items() if did and did == dept_id}


def client_tab_visible(db, user):
    """Show the Client onboarding tab: the portal admin always, others only when
    their department plays a part in the flow."""
    return bool(is_portal_admin(user) or user_roles(db, user))


def _sales_dept_id(db):
    return flow_depts(db).get("sales")


def _is_sales_admin(db, user):
    """Portal admin, or a department admin / delegate of the Sales department."""
    sales = _sales_dept_id(db)
    if is_portal_admin(user):
        return True
    return bool(sales) and ddb_is_tab_admin(db, user, sales)


def _is_ra_admin(db, user):
    """Portal admin, or a department admin / delegate of the Revenue Assurance department."""
    ra = flow_depts(db).get("revenue_assurance")
    if is_portal_admin(user):
        return True
    return bool(ra) and ddb_is_tab_admin(db, user, ra)


def _sales_admin_ids(db):
    sales = _sales_dept_id(db)
    ids = set()
    if sales:
        ids.update(r[0] for r in db.execute(
            "SELECT id FROM users WHERE department_id=? AND is_dept_admin=1 AND is_active=1", (sales,)).fetchall())
        ids.update(r[0] for r in db.execute(
            "SELECT d.user_id FROM ddb_delegates d JOIN users u ON u.id=d.user_id "
            "WHERE d.department_id=? AND u.is_active=1", (sales,)).fetchall())
    ids.update(r[0] for r in db.execute(
        "SELECT id FROM users WHERE (role='admin' OR can_portal_admin=1) AND is_active=1").fetchall())
    return ids


def _client_watchers(db, c):
    """The account manager of this client plus the Sales admins: they get
    every notification about the client once it has been added (build 96).
    The actor is never told about their own action — notify() skips them."""
    ids = set(_sales_admin_ids(db))
    if c.get("account_manager_id"):
        ids.add(c["account_manager_id"])
    return ids


def _members(db, role):
    did = flow_depts(db).get(role)
    return dept_member_ids(db, did) if did else []


# ---------------------------------------------------------------- who may see / do what
def _can_view(user, roles, c):
    if is_portal_admin(user) or "sales" in roles or c["owner_id"] == user["id"]:
        return True
    if c["status"] in APPROVED_STATES and "revenue_assurance" in roles:
        return True
    if c["status"] in FORWARDED_STATES and roles.intersection(SAN_ROLES):
        return True
    if c["status"] == "completed" and "finance" in roles:
        return True
    return False


def _visible_sql(user, roles, alias="c"):
    """(sql, params) limiting a query to the clients this viewer may see.
    A client in the Recycle Bin (deleted_at set, build 108) is never
    visible — not in the list, not in the counts, not in the dropdown."""
    if is_portal_admin(user) or "sales" in roles:
        return f"{alias}.deleted_at IS NULL", []
    parts, params = [f"{alias}.owner_id=?"], [user["id"]]
    if "revenue_assurance" in roles:
        parts.append(f"{alias}.status IN ('approved','forwarded','san_uploaded','completed')")
    if roles.intersection(SAN_ROLES):
        parts.append(f"{alias}.status IN ('forwarded','san_uploaded','completed')")
    if "finance" in roles:
        parts.append(f"{alias}.status='completed'")
    return f"({alias}.deleted_at IS NULL AND (" + " OR ".join(parts) + "))", params


def _perms(db, user, roles, c):
    """What this user may do with this client right now."""
    status = c["status"]
    sales_admin = _is_sales_admin(db, user)
    owner = c["owner_id"] == user["id"]
    am = c.get("account_manager_id") == user["id"]
    # Forward to Finance needs an activation date on EVERY SOF (build 93):
    # the date moved from the client to the SOFs, so the gate moved with it.
    sof_ok = False
    if status == "san_uploaded":
        n = db.execute("SELECT COUNT(*) FROM client_services WHERE client_id=?", (c["id"],)).fetchone()[0]
        missing = db.execute("SELECT COUNT(*) FROM client_services WHERE client_id=? AND activation_date IS NULL",
                             (c["id"],)).fetchone()[0]
        sof_ok = n > 0 and missing == 0
    return {
        "approve": status == "pending" and sales_admin,
        # Build 97: a client still waiting for approval can be changed by
        # its account manager. A rejected client is still changed by the
        # owner or the Sales admin; once approved, nobody can edit it.
        "edit": (status == "rejected" and (owner or sales_admin))
                or (status == "pending" and am),
        "forward": status == "approved" and _is_ra_admin(db, user),
        # Build 110: Revenue Assurance sets a SOF's activation date only
        # while the record has not reached Finance yet. Once it is
        # completed, the date boxes lock — only the portal admin and an
        # administrative permission user may change the dates (see
        # "dates_admin" below), and a SOF with a change in flight is
        # changed through that flow, never here.
        "sof_activation": status == "san_uploaded" and _is_ra_admin(db, user),
        "forward_finance": status == "san_uploaded" and _is_ra_admin(db, user) and sof_ok,
        # The route itself (not the button): an RA admin posting while a SOF
        # is undated gets the "set the date first" message, not a 403.
        "forward_finance_admin": status == "san_uploaded" and _is_ra_admin(db, user),
        # Build 110: Revenue Assurance forwards an approved SOF change to
        # Transmission, Core and Technical support, and later forwards the
        # finished change to Finance — both only on a completed client.
        "ra_sof_forward": status == "completed" and _is_ra_admin(db, user),
        # Build 110: after the record has reached Finance, only the portal
        # admin and an administrative permission user may change a SOF's
        # activation, termination or commercial impact date.
        "dates_admin": status == "completed" and is_portal_admin(user),
        "sof_dated": sof_ok,
        "portal_admin": is_portal_admin(user),
        # Build 102: on a finished client the account manager may add
        # services and edit activated SOFs (through the approval below);
        # the portal admin may do the same. The client itself stays finished.
        "add_services": (status == "completed" and am) or is_portal_admin(user),
    }


# ---------------------------------------------------------------- the configurable Add Client form (build 93)
FIELD_TYPES = [("text", "Text"), ("longtext", "Long text"), ("number", "Number"),
               ("date", "Date"), ("dropdown", "Dropdown"), ("yesno", "Yes-No")]
STRUCTURAL_REQUIRED = {"client_name", "sof_number", "sof_service",
                       "sof_service_description", "sof_activation_date"}

# Build 95: where a deletable default field's values live. Deleting the
# field clears them, so the field is really gone (custom fields live in
# client_field_values; defaults live in these real columns).
DEFAULT_FIELD_COLUMNS = {
    "business_type": ("client_onboardings", "business_type"),
    "address": ("client_onboardings", "address"),
    "phone": ("client_onboardings", "phone"),
    "email": ("client_onboardings", "email"),
    "notes": ("client_onboardings", "notes"),
    "sof_details": ("client_services", "details"),
    "sof_service_description": ("client_services", "service_description"),
}


def _form_fields(db, page=None):
    """The fields of one Add Client page (or all pages), in the admin's order."""
    if page is None:
        rows = db.execute("SELECT * FROM client_form_fields ORDER BY page, position, id").fetchall()
    else:
        rows = db.execute("SELECT * FROM client_form_fields WHERE page=? ORDER BY position, id", (page,)).fetchall()
    return [dict(r) for r in rows]


def _load_custom(db, cid):
    """{(target_type, target_id, field_id): value} for the admin's custom fields."""
    try:
        rows = db.execute("SELECT target_type, target_id, field_id, value FROM client_field_values "
                          "WHERE client_id=?", (cid,)).fetchall()
    except Exception:
        return {}
    return {(r["target_type"], r["target_id"], r["field_id"]): (r["value"] or "") for r in rows}


def _save_custom(db, cid, target_type, target_id, values):
    for fid, val in (values or {}).items():
        if (val or "").strip() == "":
            continue
        db.execute("INSERT INTO client_field_values(client_id,target_type,target_id,field_id,value) "
                   "VALUES (?,?,?,?,?)", (cid, target_type, target_id, fid, val))


def _check_value(value, field, label):
    """(error or None) for one form field value against its type and required flag."""
    val = (value or "").strip()
    if field["required"] and not val:
        return f"{label} is required."
    if not val:
        return None
    t = field["field_type"]
    if t == "date":
        try:
            datetime.strptime(val, "%Y-%m-%d")
        except ValueError:
            return f"{label} does not look like a date."
    elif t == "number":
        try:
            float(val)
        except ValueError:
            return f"{label} must be a number."
    elif t == "dropdown" and field.get("options"):
        opts = [o.strip() for o in (field["options"] or "").splitlines() if o.strip()]
        if opts and val not in opts:
            return f"{label} must be one of the listed options."
    return None


def _history(db, cid, user, action, detail=None):
    db.execute("INSERT INTO client_history(client_id,user_id,full_name,action,detail) VALUES (?,?,?,?,?)",
               (cid, user["id"] if user else None, user["full_name"] if user else None, action, detail))


def _sof_snapshot(row):
    """The fields a SOF change carries, as a plain dict (JSON-safe)."""
    return {"sof_number": row["sof_number"] or "", "service": row["service"] or "",
            "service_type": row.get("service_type") or "",
            "billing_type": row.get("billing_type") or "",
            "service_description": row.get("service_description") or "",
            "details": row["details"] or "",
            "activation_date": str(row["activation_date"])[:10] if row.get("activation_date") else "",
            "termination_date": str(row["termination_date"])[:10] if row.get("termination_date") else "",
            "commercial_impact_date": str(row["commercial_impact_date"])[:10] if row.get("commercial_impact_date") else "",
            "termination_reason": row.get("termination_reason") or "",
            # The SOF's state before the change (build 110): not shown in
            # the change text, but the flow needs it — a rejected change
            # puts the SOF back to the state it had.
            "status": row.get("status") or ""}


_SOF_FIELD_LABELS = {"sof_number": "SOF number", "service": "Service",
                     "service_description": "Service description", "details": "Details",
                     "activation_date": "Activation date",
                     "billing_type": "Type",
                     "termination_date": "Termination date",
                     "commercial_impact_date": "Commercial impact date",
                     "termination_reason": "Termination reason"}


def _sof_change_text(old, new):
    """'Service: Internet -> IPTSP; Termination date: — -> 2026-12-01'
    — one line per field that actually changed."""
    parts = []
    for key, label in _SOF_FIELD_LABELS.items():
        o, n = (old or {}).get(key, ""), (new or {}).get(key, "")
        if o != n:
            parts.append(f"{label}: {o or '—'} -> {n or '—'}")
    return "; ".join(parts) or "No fields changed."


def _sof_new_text(new):
    """'New SOF — SOF number: SOF-999; Service: Internet; …' for an added SOF."""
    parts = [f"{label}: {new.get(key, '')}" for key, label in _SOF_FIELD_LABELS.items() if new.get(key)]
    if new.get("file_name"):
        parts.append(f"SOF file: {new['file_name']}")
    # Build 123: a new SOF that carries its Internet format says so —
    # the locations and service locations are the detail.
    if _format_has_data(new.get("format")):
        _f = new["format"]
        parts.append(f"Internet format: {len(_f['locations'])} location(s), "
                     f"{len(_f['service_locations'])} service location(s)")
    return "New SOF — " + "; ".join(parts)


# Build 110: the stages of a SOF change after the account manager saves
# it. "awaiting" waits for the Sales admin; "approved" waits for Revenue
# Assurance to forward it; "san" waits for Transmission, Core or
# Technical support to upload a new SAN report; "ra_dates" waits for
# Revenue Assurance to change the dates and forward it to Finance.
EDIT_STAGES = ("awaiting", "approved", "san", "ra_dates")
EDIT_STAGE_LABEL = {"awaiting": "Waiting for the Sales admin",
                    "approved": "Approved — waiting for Revenue Assurance to forward it",
                    "san": "Forwarded — waiting for a new SAN report",
                    "ra_dates": "SAN report uploaded — Revenue Assurance may change the dates"}


def _open_sof_edit(db, sid):
    """The SOF change still in flight for this SOF, if any (build 110).
    When more than one is open, the one furthest along the flow wins —
    the SAN upload and the RA dates belong to the change that is waiting
    for them, not to a newer change that is still waiting for approval."""
    return db.execute("SELECT * FROM client_sof_edits WHERE service_id=? AND status IN "
                      "('awaiting','approved','san','ra_dates') ORDER BY CASE status "
                      "WHEN 'ra_dates' THEN 3 WHEN 'san' THEN 2 WHEN 'approved' THEN 1 ELSE 0 END DESC, "
                      "id DESC LIMIT 1", (sid,)).fetchone()


def _link(cid):
    return url_for("clients.detail", cid=cid)


def _clean(value, limit=255):
    return " ".join((value or "").split())[:limit]


def _file_info(raw):
    """{"stored","original"} from the JSON kept in a file column, or None."""
    if not raw:
        return None
    try:
        info = json.loads(raw)
        return info if info.get("stored") else None
    except (ValueError, TypeError, AttributeError):
        return None


def _remove_files(stored_list):
    routes_deptdb._delete_ddb_files([s for s in stored_list if s])


def _record_sof_file(db, sof_id, file_json, edit_id, user_id):
    """Build 112: every SOF file a SOF ever had is kept — the first one,
    and the one uploaded for each edited SOF. The current file on
    client_services.sof_file stays the latest, and the history lists
    them all for the Download SOF column. The same file is never
    recorded twice for one SOF."""
    if not file_json:
        return
    done = db.execute("SELECT COUNT(*) FROM client_sof_file_uploads WHERE sof_id=? AND sof_file=?",
                      (sof_id, file_json)).fetchone()[0]
    if done:
        return
    db.execute("INSERT INTO client_sof_file_uploads(sof_id,edit_id,sof_file,uploaded_by) VALUES (?,?,?,?)",
               (sof_id, edit_id, file_json, user_id))


def _sof_file_uploads(db, sid):
    """Every SOF file a SOF ever had, oldest first — the history rows,
    plus the SOF's current file when no history row covers it yet, so
    the Download SOF column is never empty for a SOF that has a file.
    Build 113: the "for the edited SOF" note belongs only to a file
    uploaded by editing this SOF. A new SOF's first file is recorded
    against the edit that created it — that edit has no old values —
    so its note is dropped here, and files already live are fixed
    without a data migration."""
    row = db.execute("SELECT sof_file FROM client_services WHERE id=?", (sid,)).fetchone()
    out = [{"id": u["id"], "file": _file_info(u["sof_file"]),
            "by": (db.execute("SELECT full_name FROM users WHERE id=?", (u["uploaded_by"],)).fetchone() or {}).get("full_name") if u["uploaded_by"] else None,
            "at": u["uploaded_at"], "edit_id": u["edit_id"] if u["edit_id"] and u["edit_old"] else None}
           for u in db.execute("SELECT h.*, e.old_values AS edit_old FROM client_sof_file_uploads h "
                               "LEFT JOIN client_sof_edits e ON e.id=h.edit_id "
                               "WHERE h.sof_id=? ORDER BY h.id", (sid,)).fetchall()]
    current = _file_info(row["sof_file"]) if row else None
    if current and not any((u["file"] or {}).get("stored") == current.get("stored") for u in out):
        out.append({"id": None, "file": current, "by": None, "at": None, "edit_id": None})
    return out


def _dept_row(db, dept_id):
    return db.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone() if dept_id else None


# ---------------------------------------------------------------- list: the tab inside the Department Database
def client_tab_view(db, dept, is_admin, args, shared_owner=None, shared_id=None):
    """The Client onboarding tab (tab=clients on the Department Database page).
    shared_owner is the name of the department that shared this tab with the
    viewer (build 109): then the viewer sees every live client, view only —
    the flow roles do not cover him, so the share is what lets him see them.
    Nothing else changes: he cannot create, approve, forward, edit, upload
    a SAN or delete, because every one of those is gated on a flow role."""
    roles = user_roles(db, g.user)
    if shared_owner is not None:
        vis, vparams = "c.deleted_at IS NULL", []
    else:
        vis, vparams = _visible_sql(g.user, roles)
    sales_admin = _is_sales_admin(db, g.user)
    can_create = bool(_sales_dept_id(db)) and ("sales" in roles or is_portal_admin(g.user))

    view = args.get("view") or "all"
    if view not in ("all", "mine", "todo"):
        view = "all"
    status = args.get("status") or ""
    q = " ".join((args.get("q") or "").split())
    # Build 102 filters: the account manager, and one month with
    # Activation or Termination — the list then shows only the clients
    # with an activation (or a termination) on a date inside the chosen
    # range. Build 106 replaces the month boxes with date boxes: the
    # browser shows a calendar, and the filter compares exact dates.
    # An old single ?month= link, or a ?month_from=/?month_to= in
    # YYYY-MM form, still works: a month counts as its first day to
    # its last day.
    am = args.get("am", type=int)
    month_from = (args.get("month_from") or "").strip()
    month_to = (args.get("month_to") or "").strip()
    month = (args.get("month") or "").strip()
    if month and re.fullmatch(r"\d{4}-\d{2}", month) and not month_from and not month_to:
        month_from = month_to = month
    if month_from and month_to and month_from > month_to:
        month_from, month_to = month_to, month_from
    month_from = _date_or_month_start(month_from)
    month_to = _date_or_month_end(month_to)
    mtype = args.get("mtype") or "activation"
    if mtype not in ("activation", "termination"):
        mtype = "activation"

    # "To do": what is waiting for this viewer
    todo_parts, todo_params = [], []
    if sales_admin:
        todo_parts.append("c.status='pending'")
    todo_parts.append("(c.status='rejected' AND c.owner_id=?)")
    todo_params.append(g.user["id"])
    if roles.intersection(SAN_ROLES) or is_portal_admin(g.user):
        # A forwarded client needs a SAN report for every SOF that has none yet (build 105).
        todo_parts.append("(c.status='forwarded' AND EXISTS (SELECT 1 FROM client_services s WHERE s.client_id=c.id AND s.san_file IS NULL))")
    if "revenue_assurance" in roles:
        todo_parts.append("c.status IN ('approved','san_uploaded')")
    todo_sql = "(" + " OR ".join(todo_parts) + ")"

    def count(extra="", extra_params=()):
        return db.execute("SELECT COUNT(*) FROM client_onboardings c WHERE " + vis + extra,
                          list(vparams) + list(extra_params)).fetchone()[0]

    counts = {"all": count(), "mine": count(" AND c.owner_id=?", [g.user["id"]]),
              "todo": count(" AND " + todo_sql, todo_params)}
    for st in ALL_STATUSES:
        counts[st] = count(" AND c.status=?", [st])

    where, params = [vis], list(vparams)
    if view == "mine":
        where.append("c.owner_id=?"); params.append(g.user["id"])
    elif view == "todo":
        where.append(todo_sql); params += todo_params
    if status in ALL_STATUSES:
        where.append("c.status=?"); params.append(status)
    elif status in ("sof_pending", "sof_activated", "sof_terminated"):
        # A SOF state, not a client state: clients with at least one SOF in it.
        where.append("EXISTS (SELECT 1 FROM client_services s WHERE s.client_id=c.id AND s.status=?)")
        params.append(status[4:])
    if am:
        where.append("c.account_manager_id=?"); params.append(am)
    if month_from or month_to:
        # A client matches when one of its SOFs was activated (or
        # terminated) on a date inside the chosen range.
        col = "activation_date" if mtype == "activation" else "termination_date"
        conds, cparams = [], []
        if month_from:
            conds.append(f"s.{col}>=?")
            cparams.append(month_from)
        if month_to:
            conds.append(f"s.{col}<=?")
            cparams.append(month_to)
        where.append("EXISTS (SELECT 1 FROM client_services s WHERE s.client_id=c.id AND "
                     + " AND ".join(conds) + ")")
        params += cparams
    if q:
        like = like_pattern(q)
        digits = q.upper().replace("CL-", "").strip()
        clause = ("(c.client_name LIKE ? ESCAPE '\\' OR u.full_name LIKE ? ESCAPE '\\' "
                  "OR am.full_name LIKE ? ESCAPE '\\'")
        params += [like] * 3
        if digits.isdigit():
            # Build 110: a number searches the client's serial, not its id.
            clause += " OR c.serial=?"
            params.append(int(digits))
        where.append(clause + ")")
    sql_where = " WHERE " + " AND ".join(where)
    base = ("FROM client_onboardings c LEFT JOIN users u ON u.id=c.owner_id "
            "LEFT JOIN users am ON am.id=c.account_manager_id")
    total = db.execute("SELECT COUNT(*) " + base + sql_where, params).fetchone()[0]
    page, pages, offset = page_info(total, args.get("page", 1, type=int), config.PER_PAGE)
    rows = db.execute(
        "SELECT c.*, u.full_name AS owner_name, am.full_name AS am_name, "
        "(SELECT COUNT(*) FROM client_services s WHERE s.client_id=c.id) AS sof_count, "
        # Build 102: the Status column counts the SOFs by their own state.
        "(SELECT COUNT(*) FROM client_services s WHERE s.client_id=c.id AND s.status='activated') AS n_activated, "
        "(SELECT COUNT(*) FROM client_services s WHERE s.client_id=c.id AND s.status='terminated') AS n_terminated, "
        "(SELECT COUNT(*) FROM client_services s WHERE s.client_id=c.id AND s.status='pending') AS n_pending, "
        # Build 102: each date carries its short service name (the service
        # type) in brackets, oldest first.
        "(SELECT GROUP_CONCAT(DISTINCT CONCAT(s.activation_date, ' (', s.service_type, ')') "
        "ORDER BY s.activation_date SEPARATOR ', ') FROM client_services s "
        "WHERE s.client_id=c.id AND s.activation_date IS NOT NULL) AS sof_activations, "
        "(SELECT GROUP_CONCAT(DISTINCT CONCAT(s.termination_date, ' (', s.service_type, ')') "
        "ORDER BY s.termination_date SEPARATOR ', ') FROM client_services s "
        "WHERE s.client_id=c.id AND s.status='terminated' AND s.termination_date IS NOT NULL) AS sof_terminations "
        + base + sql_where + " ORDER BY c.id ASC LIMIT ? OFFSET ?", params + [config.PER_PAGE, offset]).fetchall()

    # Build 111: the Flow column shows where a SOF change is, not the
    # client's own status, while a change is in flight — a completed
    # client with a pending SOF change no longer reads "Completed".
    open_edits = {}
    if rows:
        _ids = [r["id"] for r in rows]
        _ph = ",".join("?" * len(_ids))
        for e in db.execute(
                "SELECT e.client_id, e.status, e.new_values, s.sof_number FROM client_sof_edits e "
                "LEFT JOIN client_services s ON s.id=e.service_id "
                "WHERE e.client_id IN (" + _ph + ") AND e.status IN ('awaiting','approved','san','ra_dates') "
                "ORDER BY e.id", _ids).fetchall():
            _num = e["sof_number"]
            if not _num:
                try:
                    _num = json.loads(e["new_values"] or "{}").get("sof_number") or ""
                except ValueError:
                    _num = ""
            open_edits.setdefault(e["client_id"], []).append((_num, e["status"]))

    # The dropdown of approved clients (everyone who can see them)
    approved = db.execute(
        "SELECT c.id, c.serial, c.client_name FROM client_onboardings c WHERE " + vis +
        " AND c.status IN ('approved','forwarded','san_uploaded','completed') ORDER BY c.client_name, c.id",
        vparams).fetchall()

    keep = {k: v for k, v in args.items() if k not in ("page",)}
    keep["tab"] = "clients"
    if is_portal_admin(g.user):
        keep["dept"] = dept["id"]
    return render_template(
        "deptdb_clients.html", dept=dept, is_admin=is_admin,
        tabs=routes_deptdb._tabs_row(ddb_tabs(db, dept["id"]), ddb_shared_tabs(db, g.user))
        + routes_deptdb._special_shared_entries(db, g.user, dept["id"], skip_key="clients"),
        rows=rows, counts=counts, view=view, status=status, q=q, am=am, month_from=month_from, month_to=month_to, mtype=mtype,
        managers=_account_managers(db), total=total, page=page, pages=pages,
        keep=keep, approved=approved, can_create=can_create, roles=roles,
        flow=flow_depts(db), role_label=ROLE_LABEL,
        can_setup=is_portal_admin(g.user), can_form_setup=_is_sales_admin(db, g.user),
        statuses=ALL_STATUSES, status_label=STATUS_LABEL,
        sof_statuses=SOF_STATUSES, sof_status_label=SOF_STATUS_LABEL,
        open_edits=open_edits, edit_stage_label=EDIT_STAGE_LABEL,
        shared_owner=shared_owner, shared_id=shared_id,
        can_manage_tab_sharing=shared_owner is None and _is_sales_admin(db, g.user))


# ---------------------------------------------------------------- one client
def _load(cid):
    """(db, client row, roles) for a client this user may see, else 404."""
    db = get_db()
    c = db.execute(
        "SELECT c.*, u.full_name AS owner_name, am.full_name AS am_name, "
        "decider.full_name AS decided_name, sb.full_name AS san_name, ab.full_name AS activation_name, "
        "d.name AS dept_name FROM client_onboardings c "
        "LEFT JOIN users u ON u.id=c.owner_id LEFT JOIN users am ON am.id=c.account_manager_id "
        "LEFT JOIN users decider ON decider.id=c.decided_by LEFT JOIN users sb ON sb.id=c.san_by "
        "LEFT JOIN users ab ON ab.id=c.activation_by LEFT JOIN departments d ON d.id=c.department_id "
        "WHERE c.id=? AND c.deleted_at IS NULL", (cid,)).fetchone()
    if c is None:
        abort(404)
    roles = user_roles(db, g.user)
    if not _can_view(g.user, roles, c):
        # Build 109: a user the Sales admin shared the Client onboarding
        # tab with sees every client, view only — the flow roles do not
        # cover him, so the share is what lets him in.
        from core import special_tab_access
        sales = flow_depts(db).get("sales")
        if not sales or special_tab_access(db, g.user, "clients", sales) is None:
            abort(404)
    return db, c, roles


def _timeline(db, c):
    """The flow of the diagram as a checklist: (label, note, state) with state done/now/todo/bad."""
    flow = flow_depts(db)
    names = {}
    for role in ROLE_KEYS:
        d = _dept_row(db, flow.get(role))
        names[role] = d["name"] if d else ROLE_LABEL[role] + " (not set)"
    st = c["status"]
    approved = st in APPROVED_STATES
    steps = [
        ("Request sent", f"{names['sales']} filled the client, contacts and services", "done"),
        ("Sales admin approval",
         {"pending": "Waiting for the Sales admin", "rejected": "Rejected: back to the Sales user"}.get(st, "Approved"),
         "now" if st == "pending" else "bad" if st == "rejected" else "done"),
        (f"{names['revenue_assurance']} sees it first", "View only", "done" if approved else "todo"),
        (f"{names['revenue_assurance']} forwards it", "Forward to Transmission, Core and Technical support, or reject it with a reason",
         "now" if st == "approved" else "done" if st in FORWARDED_STATES else "todo"),
        (f"{names['transmission']}, {names['core']}, {names['technical']}", "View the full record",
         "done" if st in FORWARDED_STATES else "todo"),
        ("SAN report uploaded", "One upload per SOF, by any of those three departments",
         "done" if st in ("san_uploaded", "completed") else "now" if st == "forwarded" else "todo"),
        (f"{names['revenue_assurance']} and {names['sales']} receive the SAN report", "",
         "done" if st in ("san_uploaded", "completed") else "todo"),
        ("Activation date set", "On every SOF — only Revenue Assurance edits it after the SAN report",
         "done" if st == "completed" else "now" if st == "san_uploaded" else "todo"),
        (f"{names['revenue_assurance']} forwards it to {names['finance']}", "Only then Finance sees the final record",
         "done" if st == "completed" else "now" if st == "san_uploaded" else "todo"),
        (f"{names['finance']} receives the final record", "", "done" if st == "completed" else "todo"),
    ]
    return steps


@bp.route("/<int:cid>")
@login_required
def detail(cid):
    db, c, roles = _load(cid)
    contacts = [dict(r) for r in db.execute(
        "SELECT * FROM client_contacts WHERE client_id=? ORDER BY position, id", (cid,)).fetchall()]
    # Build 121: the tables show the department — for an HRC row the
    # portal department's name, for a client row the department that
    # was typed on the form.
    _dept_names = {d["id"]: d["name"] for d in db.execute("SELECT id, name FROM departments").fetchall()}
    for _r in contacts:
        _r["department_name"] = (_dept_names.get(_r["department_id"]) if _r["side"] == "hrc"
                                 else (_r.get("department_name") or ""))
    services = db.execute("SELECT * FROM client_services WHERE client_id=? ORDER BY position, id", (cid,)).fetchall()
    history = db.execute("SELECT * FROM client_history WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
    # One SAN report per SOF (build 105): each SOF's file, who uploaded it,
    # and whether this viewer may upload or remove it, keyed by the SOF's id.
    # Build 110: every upload is kept, so the card lists them all — the
    # first one and the one uploaded for an edited SOF.
    san_perm = {}
    san_uploads = {}
    for s in services:
        _by = None
        if s["san_by"]:
            _u = db.execute("SELECT full_name FROM users WHERE id=?", (s["san_by"],)).fetchone()
            _by = _u["full_name"] if _u else None
        san_perm[s["id"]] = {"san": _file_info(s["san_file"]), "by": _by,
                             "upload": _can_upload_sof_san(db, g.user, roles, c, s),
                             "remove": _can_remove_sof_san(g.user, c, s)}
        san_uploads[s["id"]] = [
            {"id": u["id"], "file": _file_info(u["san_file"]),
             "by": (db.execute("SELECT full_name FROM users WHERE id=?", (u["uploaded_by"],)).fetchone() or {}).get("full_name") if u["uploaded_by"] else None,
             "at": u["uploaded_at"], "edit_id": u["edit_id"]}
            for u in db.execute("SELECT * FROM client_sof_san_uploads WHERE sof_id=? ORDER BY id", (s["id"],)).fetchall()]
    _fields = {p: _form_fields(db, p) for p in (1, 2)}
    # Build 102: the SOF changes waiting for the Sales admin to approve,
    # with the field-by-field change already worked out for the page.
    # Build 110: a change stays on the page through every stage — approval,
    # the Revenue Assurance forward, the new SAN report, the date edits —
    # until Revenue Assurance forwards it to Finance.
    edits = []
    for e in db.execute("SELECT e.*, u.full_name AS editor_name FROM client_sof_edits e "
                        "LEFT JOIN users u ON u.id=e.editor_id "
                        "WHERE e.client_id=? AND e.status IN ('awaiting','approved','san','ra_dates') "
                        "ORDER BY e.id", (cid,)).fetchall():
        new = json.loads(e["new_values"])
        old = json.loads(e["old_values"]) if e["old_values"] else {}
        _change = _sof_new_text(new) if not e["service_id"] else _sof_change_text(old, new)
        # Build 121: a change may carry contact rows too — they read
        # the same way, next to the SOF fields.
        _cdiff = _contacts_change_text((old or {}).get("contacts"), (new or {}).get("contacts"))
        if _cdiff:
            _change = (_change + "; " + _cdiff) if _change != "No fields changed." else _cdiff
        _srow = None
        if e["service_id"]:
            _srow = db.execute("SELECT * FROM client_services WHERE id=?", (e["service_id"],)).fetchone()
        edits.append({"id": e["id"], "editor_name": e["editor_name"] or "—",
                      "created_at": e["created_at"], "is_new": not e["service_id"],
                      "stage": e["status"], "stage_label": EDIT_STAGE_LABEL.get(e["status"], e["status"]),
                      "service_id": e["service_id"],
                      "activation_date": str(_srow["activation_date"])[:10] if _srow and _srow["activation_date"] else "",
                      "termination_date": str(_srow["termination_date"])[:10] if _srow and _srow["termination_date"] else "",
                      "commercial_impact_date": str(_srow["commercial_impact_date"])[:10] if _srow and _srow["commercial_impact_date"] else "",
                      # Build 112: Revenue Assurance sees the termination
                      # and commercial impact date boxes only when the
                      # account manager's change carries one of those
                      # dates — a new service never does.
                      "has_term_dates": bool((new.get("termination_date") or "")
                                             or (new.get("commercial_impact_date") or "")),
                      "num": old.get("sof_number") or new.get("sof_number") or "",
                      "change": _change})
    edit_stage = {e["service_id"]: e["stage"] for e in edits if e["service_id"]}
    return render_template(
        "client_detail.html", c=c, contacts=contacts, services=services, history=history,
        contact_sides=CONTACT_SIDES, contact_kinds=CONTACT_KINDS, contact_kind_label=CONTACT_KIND_LABEL,
        sof=[(s, _file_info(s["sof_file"])) for s in services], san_perm=san_perm, san_uploads=san_uploads,
        sof_files={s["id"]: _sof_file_uploads(db, s["id"]) for s in services},
        perm=_perms(db, g.user, roles, c), timeline=_timeline(db, c),
        fields=_fields,
        fmap={fld["field_key"]: fld for p in (1, 2) for fld in _fields[p] if fld["field_key"]},
        custom=_load_custom(db, cid), edits=edits, edit_stage=edit_stage, sof_status_label=SOF_STATUS_LABEL,
        can_approve_sof=_is_sales_admin(db, g.user),
        can_ra_sof_forward=_is_ra_admin(db, g.user),
        back=url_for("ddb.index", tab="clients", **({"dept": g.user["department_id"]} if not is_portal_admin(g.user) else {})))


@bp.route("/go")
@login_required
def go():
    """The approved-client dropdown on the tab: open the chosen client."""
    cid = request.args.get("client", type=int)
    if not cid:
        return redirect(url_for("ddb.index", tab="clients"))
    return redirect(_link(cid))


# ---------------------------------------------------------------- create / edit (3 pages, one form)
def _account_managers(db):
    sales = _sales_dept_id(db)
    if sales:
        rows = db.execute("SELECT id, full_name, designation, phone, email FROM users WHERE department_id=? AND is_active=1 "
                          "AND is_deleted=0 ORDER BY full_name", (sales,)).fetchall()
        if rows:
            return rows
    return db.execute("SELECT id, full_name, designation, phone, email FROM users WHERE is_active=1 AND is_deleted=0 "
                      "ORDER BY full_name").fetchall()


# Build 118: the two contact tables — two sides (client / HRC). Build
# 121: one row per person, and a fourth kind, 'other', which may be used
# once per table like the rest. An HRC row also carries the portal
# department and user it was picked from.
CONTACT_SIDES = (("client", "Client contacts"), ("hrc", "HRC Technologies Ltd contacts"))
CONTACT_KINDS = (("account_manager", "Account manager"), ("technical", "Technical contact"),
                 ("billing", "Billing contact"), ("other", "Others"))
CONTACT_KIND_LABEL = dict(CONTACT_KINDS)
# The three kinds that must be filled in each table (build 121): Others
# is optional, in both tables.
CONTACT_REQUIRED_KINDS = ("account_manager", "technical", "billing")

# Build 119: the HRC Department dropdown holds only the departments that
# do that job — the account manager comes from Sales & Marketing, the
# technical contact from Core, IT, Transmission or Technical support,
# the billing contact from Revenue Assurance. Names, not ids: the ids
# differ between databases, and a department that does not exist here
# simply offers nothing. Build 121: an Others row may pick any
# department, so 'other' holds no list at all.
CONTACT_HRC_DEPTS = {"account_manager": ("Sales & Marketing",),
                     "technical": ("Core", "IT", "Transmission", "Technical support"),
                     "billing": ("Revenue Assurance",),
                     "other": ()}

# Build 120: the match ignores capital letters and stray spaces — the
# live departments were typed by hand, so "Technical Support" must
# match "Technical support".
CONTACT_HRC_DEPTS_LOWER = {k: tuple(n.strip().casefold() for n in v)
                           for k, v in CONTACT_HRC_DEPTS.items()}

# Build 123: the Services page starts with a Service Type dropdown —
# the five services the portal sells. Only Internet has its SOF format
# developed so far; the other four show the contacts and the SOF row,
# and their formats come later.
SERVICE_TYPES = ("Internet/Data", "IPTSP", "Mail", "Domain Hosting")
# Build 124: Internet and Data merged into one option. A SOF whose type
# is "Internet/Data" — or the legacy "Internet" a build 123 SOF carries
# — has the SERVICE DETAILS format; the other types have none yet.
FORMAT_TYPES = ("Internet/Data", "Internet")


def _blank_format():
    """The Internet SOF format, empty (build 123, build 124): the two Add
    tables (locations, service locations), the GGC and FNA rows and the
    Data Connectivity rows (build 124), the technical details, the
    last-mile rows and the offnet support answers. A format with no
    locations and no service locations counts as empty — no row is
    stored for it."""
    return {"locations": [], "service_locations": [],
            "ggc": {"name": "GGC", "bandwidth": "", "remarks": ""},
            "fna": {"name": "FNA", "bandwidth": "", "remarks": ""},
            "data_connectivity": [],
            "bgp_peering": "", "as_number": "", "route_type": "", "prefix": "",
            "additional_ip": "", "tech_other_details": "",
            "last_mile": [{"name": "", "fiber": 0, "radio": 0, "protection": 0, "dual_pop": 0,
                           "interface": "", "media": "", "cstm_dvc": ""},
                          {"name": "", "fiber": 0, "radio": 0, "protection": 0, "dual_pop": 0,
                           "interface": "", "media": "", "cstm_dvc": ""}],
            "lm_protection_by": "", "lm_other_device": "",
            "other_isp": "", "other_isp_details": "", "more_isp": "", "more_isp_details": "",
            "off_gateway": "", "off_gateway_devices": "", "off_gateway_details": "",
            "off_wifi": "", "off_wifi_devices": "", "off_wifi_details": "",
            "off_lan_delivery": "", "off_lan_support": "", "off_lan_support_devices": "",
            "off_lan_support_details": "", "off_pc": "", "off_pc_devices": "",
            "off_pc_details": "", "off_other_details": ""}


def _format_has_data(fmt):
    if not fmt:
        return False
    if fmt.get("locations") or fmt.get("service_locations") or fmt.get("data_connectivity"):
        return True
    for _key in ("ggc", "fna"):
        _row = fmt.get(_key) or {}
        if _row.get("bandwidth") or _row.get("remarks"):
            return True
    return False


def _format_norm(fmt):
    """A format stripped of its blank last-mile rows (build 123): two
    formats count as the same when their filled rows and answers
    match, so a re-save that only re-renders the two blank rows is not
    a change."""
    f = dict(fmt or {})
    f["last_mile"] = [r for r in (fmt or {}).get("last_mile", [])
                      if any((r.get("name"), r.get("fiber"), r.get("radio"), r.get("protection"),
                              r.get("dual_pop"), r.get("interface"), r.get("media"), r.get("cstm_dvc")))]
    return f


def _format_from_db(db, sof_id):
    """The stored Internet format of one SOF (build 123): the scalar
    answers, the two Add tables in position order, and the last-mile
    rows. A SOF with no format row returns the blank format."""
    fmt = _blank_format()
    row = db.execute("SELECT * FROM client_sof_format WHERE sof_id=?", (sof_id,)).fetchone()
    if row is None:
        return fmt
    for k in ("bgp_peering", "as_number", "route_type", "prefix", "additional_ip",
              "tech_other_details", "lm_protection_by", "lm_other_device",
              "other_isp", "other_isp_details", "more_isp", "more_isp_details",
              "off_gateway", "off_gateway_devices", "off_gateway_details",
              "off_wifi", "off_wifi_devices", "off_wifi_details",
              "off_lan_delivery", "off_lan_support", "off_lan_support_devices",
              "off_lan_support_details", "off_pc", "off_pc_devices",
              "off_pc_details", "off_other_details"):
        fmt[k] = row[k] or ""
    fmt["locations"] = [dict(name=r["name"] or "", address=r["address"] or "",
                             coordinates=r["coordinates"] or "")
                        for r in db.execute("SELECT * FROM client_sof_locations "
                                           "WHERE sof_id=? ORDER BY position, id", (sof_id,)).fetchall()]
    fmt["service_locations"] = [dict(name=r["name"] or "", bandwidth=r["bandwidth"] or "",
                                     remarks=r.get("remarks") or "")
                                for r in db.execute("SELECT * FROM client_sof_service_locations "
                                                   "WHERE sof_id=? ORDER BY position, id", (sof_id,)).fetchall()]
    # Build 124: the GGC and FNA rows (one each, name fixed) and the
    # Data Connectivity rows.
    for _key, _tbl, _label in (("ggc", "client_sof_ggc", "GGC"), ("fna", "client_sof_fna", "FNA")):
        _r = db.execute("SELECT * FROM " + _tbl + " WHERE sof_id=? ORDER BY position, id LIMIT 1",
                        (sof_id,)).fetchone()
        if _r:
            fmt[_key] = {"name": _r["name"] or _label, "bandwidth": _r["bandwidth"] or "",
                         "remarks": _r.get("remarks") or ""}
    fmt["data_connectivity"] = [dict(name=r["name"] or "", bandwidth=r["bandwidth"] or "",
                                     remarks=r.get("remarks") or "")
                                for r in db.execute("SELECT * FROM client_sof_data_connectivity "
                                                   "WHERE sof_id=? ORDER BY position, id", (sof_id,)).fetchall()]
    _lm = [dict(name=r["name"] or "", fiber=r["fiber"] or 0, radio=r["radio"] or 0,
                protection=r["protection"] or 0, dual_pop=r["dual_pop"] or 0,
                interface=r["interface"] or "", media=r["media"] or "",
                cstm_dvc=r["cstm_dvc"] or "")
           for r in db.execute("SELECT * FROM client_sof_last_mile "
                              "WHERE sof_id=? ORDER BY position, id", (sof_id,)).fetchall()]
    if _lm:
        fmt["last_mile"] = _lm
        # The paper format has two last-mile rows — a stored format with
        # one filled row still shows the second, blank, row to fill.
        while len(fmt["last_mile"]) < 2:
            fmt["last_mile"].append(dict(_blank_format()["last_mile"][0]))
    return fmt


def _write_format(db, sof_id, fmt):
    """Store one SOF's Internet format (build 123, build 124): the old
    rows go first, then the new ones. A SOF with no format data keeps no
    rows — a type changed away from Internet/Data drops its format with it."""
    db.execute("DELETE FROM client_sof_format WHERE sof_id=?", (sof_id,))
    db.execute("DELETE FROM client_sof_locations WHERE sof_id=?", (sof_id,))
    db.execute("DELETE FROM client_sof_service_locations WHERE sof_id=?", (sof_id,))
    db.execute("DELETE FROM client_sof_last_mile WHERE sof_id=?", (sof_id,))
    db.execute("DELETE FROM client_sof_ggc WHERE sof_id=?", (sof_id,))
    db.execute("DELETE FROM client_sof_fna WHERE sof_id=?", (sof_id,))
    db.execute("DELETE FROM client_sof_data_connectivity WHERE sof_id=?", (sof_id,))
    if not _format_has_data(fmt):
        return
    db.execute("INSERT INTO client_sof_format(sof_id,bgp_peering,as_number,route_type,prefix,additional_ip,"
               "tech_other_details,lm_protection_by,lm_other_device,other_isp,other_isp_details,"
               "more_isp,more_isp_details,off_gateway,off_gateway_devices,off_gateway_details,"
               "off_wifi,off_wifi_devices,off_wifi_details,off_lan_delivery,off_lan_support,"
               "off_lan_support_devices,off_lan_support_details,off_pc,off_pc_devices,off_pc_details,"
               "off_other_details) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (sof_id, fmt["bgp_peering"] or None, fmt["as_number"] or None,
                fmt["route_type"] or None, fmt["prefix"] or None, fmt["additional_ip"] or None,
                fmt["tech_other_details"] or None, fmt["lm_protection_by"] or None,
                fmt["lm_other_device"] or None, fmt["other_isp"] or None,
                fmt["other_isp_details"] or None, fmt["more_isp"] or None,
                fmt["more_isp_details"] or None, fmt["off_gateway"] or None,
                fmt["off_gateway_devices"] or None, fmt["off_gateway_details"] or None,
                fmt["off_wifi"] or None, fmt["off_wifi_devices"] or None,
                fmt["off_wifi_details"] or None, fmt["off_lan_delivery"] or None,
                fmt["off_lan_support"] or None, fmt["off_lan_support_devices"] or None,
                fmt["off_lan_support_details"] or None, fmt["off_pc"] or None,
                fmt["off_pc_devices"] or None, fmt["off_pc_details"] or None,
                fmt["off_other_details"] or None))
    for i, r in enumerate(fmt["locations"]):
        db.execute("INSERT INTO client_sof_locations(sof_id,position,name,address,coordinates) "
                   "VALUES (?,?,?,?,?)",
                   (sof_id, i, r["name"] or None, r["address"] or None, r["coordinates"] or None))
    for i, r in enumerate(fmt["service_locations"]):
        db.execute("INSERT INTO client_sof_service_locations(sof_id,position,name,bandwidth,remarks) "
                   "VALUES (?,?,?,?,?)",
                   (sof_id, i, r["name"] or None, r["bandwidth"] or None, r.get("remarks") or None))
    # Build 124: the GGC and FNA rows (one each, stored only when filled)
    # and the Data Connectivity rows.
    _g = fmt.get("ggc") or {}
    if _g.get("bandwidth") or _g.get("remarks"):
        db.execute("INSERT INTO client_sof_ggc(sof_id,position,name,bandwidth,remarks) VALUES (?,?,?,?,?)",
                   (sof_id, 0, _g.get("name") or "GGC", _g.get("bandwidth") or None,
                    _g.get("remarks") or None))
    _g = fmt.get("fna") or {}
    if _g.get("bandwidth") or _g.get("remarks"):
        db.execute("INSERT INTO client_sof_fna(sof_id,position,name,bandwidth,remarks) VALUES (?,?,?,?,?)",
                   (sof_id, 0, _g.get("name") or "FNA", _g.get("bandwidth") or None,
                    _g.get("remarks") or None))
    for i, r in enumerate(fmt.get("data_connectivity") or []):
        db.execute("INSERT INTO client_sof_data_connectivity(sof_id,position,name,bandwidth,remarks) "
                   "VALUES (?,?,?,?,?)",
                   (sof_id, i, r["name"] or None, r["bandwidth"] or None, r.get("remarks") or None))
    for i, r in enumerate(fmt["last_mile"]):
        if not any((r["name"], r["fiber"], r["radio"], r["protection"], r["dual_pop"],
                    r["interface"], r["media"], r["cstm_dvc"])):
            continue
        db.execute("INSERT INTO client_sof_last_mile(sof_id,position,name,fiber,radio,protection,dual_pop,"
                   "interface,media,cstm_dvc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (sof_id, i, r["name"] or None, 1 if r["fiber"] else 0, 1 if r["radio"] else 0,
                    1 if r["protection"] else 0, 1 if r["dual_pop"] else 0,
                    r["interface"] or None, r["media"] or None, r["cstm_dvc"] or None))


def _blank_contact():
    return {"ctype": "", "department_id": None, "user_id": None, "department_name": "",
            "name": "", "designation": "", "phone": "", "email": ""}


def _blank_contacts():
    return {side: [] for side, _l in CONTACT_SIDES}


def _contacts_from_db(db, cid):
    """The client's contact rows, grouped by side in position order
    (build 121). A row with no side or kind predates the tables and is
    not shown."""
    out = {side: [] for side, _l in CONTACT_SIDES}
    for r in db.execute("SELECT * FROM client_contacts WHERE client_id=? ORDER BY position, id",
                        (cid,)).fetchall():
        if r["side"] in out and r["ctype"] in CONTACT_KIND_LABEL:
            out[r["side"]].append({"ctype": r["ctype"], "department_id": r["department_id"],
                                   "user_id": r["user_id"],
                                   "department_name": r.get("department_name") or "",
                                   "name": r["name"] or "", "designation": r["designation"] or "",
                                   "phone": r["phone"] or "", "email": r["email"] or ""})
    return out


def _read_contact_tables(db, f, label, require_kinds, allow_am=True):
    """Read the two contact tables from a posted form (build 121).
    Each side posts one row per person as parallel lists — the Type,
    then the person's details. The client side types its department;
    the HRC side picks a department and a user, and the name comes from
    that user's account (the designation, phone and email are typed,
    filled in from the account by the form). A row with nothing in it
    is the blank row and is ignored; a row with some fields filled and
    some empty, or with a value the form refuses, is kept in `edit` so
    the form can show it again as an editable row. Returns (contacts,
    edit, errors): contacts is {side: [row]} of filled rows with no
    error, edit is {side: [row]} of rows to fix. `require_kinds` are
    the Types each table must hold — Others is never required. With
    `allow_am=False` (the SOF edit) the Account manager type is not
    offered at all, and a posted one is refused."""
    contacts = {side: [] for side, _l in CONTACT_SIDES}
    edit = {side: [] for side, _l in CONTACT_SIDES}
    errors = []
    for side, side_label in CONTACT_SIDES:
        _types = f.getlist(f"c_{side}_type")
        _names = f.getlist(f"c_{side}_name") if side == "client" else []
        _depts = f.getlist(f"c_{side}_dept")
        _users = f.getlist(f"c_{side}_user") if side == "hrc" else []
        _desigs = f.getlist(f"c_{side}_designation")
        _phones = f.getlist(f"c_{side}_phone")
        _emails = f.getlist(f"c_{side}_email")
        _seen = set()
        _n = max(len(_types), len(_names), len(_depts), len(_users),
                 len(_desigs), len(_phones), len(_emails))
        for i in range(_n):
            _kind = _clean(_pick(_types, i))
            _name = _clean(_pick(_names, i)) if side == "client" else ""
            _dept_raw = _pick(_depts, i)
            _user_raw = _pick(_users, i) if side == "hrc" else ""
            _desig = _clean(_pick(_desigs, i))
            _phone = _clean(_pick(_phones, i))
            _email = _clean(_pick(_emails, i))
            _dept_txt = _clean(_dept_raw) if side == "client" else ""
            _dept = int(_dept_raw) if side == "hrc" and str(_dept_raw).isdigit() else None
            _user = int(_user_raw) if side == "hrc" and str(_user_raw).isdigit() else None
            _row = {"ctype": _kind, "department_id": _dept, "user_id": _user,
                    "department_name": _dept_txt, "name": _name,
                    "designation": _desig, "phone": _phone, "email": _email}
            _fields = [_kind, _name, _dept_txt, _desig, _phone, _email] if side == "client" \
                else [_kind, _dept_raw, _user_raw, _desig, _phone, _email]
            if not any(_fields):
                continue
            _lab = (f"{label}: {side_label} — {CONTACT_KIND_LABEL[_kind]}"
                    if _kind in CONTACT_KIND_LABEL else f"{label}: {side_label} — row {i + 1}")
            _bad = False
            if _kind not in CONTACT_KIND_LABEL:
                errors.append(f"{_lab}: pick the type.")
                _bad = True
            elif not allow_am and _kind == "account_manager":
                errors.append(f"{_lab}: the account manager cannot be changed here.")
                _bad = True
            elif _kind in _seen:
                errors.append(f"{_lab}: the {CONTACT_KIND_LABEL[_kind]} is already in this table.")
                _bad = True
            else:
                _seen.add(_kind)
            if side == "client":
                for _fld, _val in (("name", _name), ("department", _dept_txt),
                                   ("designation", _desig), ("phone", _phone), ("email", _email)):
                    if not _val:
                        errors.append(f"{_lab}: the {_fld} is required.")
                        _bad = True
            else:
                _dept_name = None
                if _dept is not None:
                    _drow = db.execute("SELECT name FROM departments WHERE id=?", (_dept,)).fetchone()
                    if _drow is None:
                        _dept = None
                    else:
                        _dept_name = _drow["name"]
                _urow = None
                if _user is not None:
                    _urow = db.execute("SELECT * FROM users WHERE id=? AND is_active=1 AND is_deleted=0",
                                       (_user,)).fetchone()
                    if _urow is None:
                        _user = None
                _wrong_dept = False
                if _dept is not None and _user is not None and db.execute(
                        "SELECT 1 FROM users WHERE id=? AND department_id=?", (_user, _dept)).fetchone() is None:
                    _wrong_dept = True
                    _user = None
                # Build 119: the department must be one of this kind's own
                # (CONTACT_HRC_DEPTS) — a posted department from another
                # job is refused, not silently kept. Build 120: the match
                # ignores capitals and stray spaces. Build 121: an Others
                # row may pick any department.
                _wrong_kind_dept = (_dept_name is not None and bool(CONTACT_HRC_DEPTS.get(_kind))
                                    and _dept_name.strip().casefold() not in CONTACT_HRC_DEPTS_LOWER[_kind])
                if _wrong_kind_dept:
                    _names = CONTACT_HRC_DEPTS[_kind]
                    _or = (" or ".join(_names) if len(_names) == 1
                           else ", ".join(_names[:-1]) + " or " + _names[-1])
                    errors.append(f"{_lab}: the department must be {_or}.")
                    _bad = True
                if _dept is None:
                    errors.append(f"{_lab}: pick the department.")
                    _bad = True
                if _user is None and not _wrong_dept:
                    errors.append(f"{_lab}: pick the user.")
                    _bad = True
                if _wrong_dept:
                    errors.append(f"{_lab}: the user is not in that department.")
                    _bad = True
                if _urow is not None:
                    _row["name"] = _urow["full_name"] or ""
                for _fld in ("designation", "phone", "email"):
                    if not _row[_fld]:
                        errors.append(f"{_lab}: the {_fld} is required.")
                        _bad = True
                _row["department_id"], _row["user_id"] = _dept, _user
            if _row["email"] and "@" not in _row["email"]:
                errors.append(f"{_lab}: the email does not look right.")
                _bad = True
            (contacts if not _bad else edit)[side].append(_row)
        _have = {r["ctype"] for r in contacts[side] + edit[side]}
        for _kind in require_kinds:
            if _kind not in _have:
                errors.append(f"{label}: {side_label} — the {CONTACT_KIND_LABEL[_kind]} is required.")
    return contacts, edit, errors


def _contacts_change_text(old, new):
    """'Contacts: Client Technical contact changed; HRC Billing contact
    added' — one phrase per contact slot that differs between the two
    tables (build 121, SOF edit). The account manager never differs
    here: it is not staged, so it is in neither table."""
    _short = {"client": "Client", "hrc": "HRC"}
    parts = []
    for side, _sl in CONTACT_SIDES:
        _o = {r["ctype"]: r for r in (old or {}).get(side, [])}
        _n = {r["ctype"]: r for r in (new or {}).get(side, [])}
        for ctype, _label in CONTACT_KINDS:
            o, n = _o.get(ctype), _n.get(ctype)
            if o == n:
                continue
            if o is None:
                parts.append(f"{_short[side]} {CONTACT_KIND_LABEL[ctype]} added")
            elif n is None:
                parts.append(f"{_short[side]} {CONTACT_KIND_LABEL[ctype]} removed")
            else:
                parts.append(f"{_short[side]} {CONTACT_KIND_LABEL[ctype]} changed")
    return ("Contacts: " + "; ".join(parts)) if parts else ""


def _apply_contacts(db, cid, staged):
    """Write the staged non-AM contact rows (build 121, SOF edit): the
    account manager rows stay exactly as they are; every other row is
    replaced by the staged ones."""
    cur = _contacts_from_db(db, cid)
    merged = {}
    for side, _sl in CONTACT_SIDES:
        merged[side] = [r for r in cur[side] if r["ctype"] == "account_manager"] + list((staged or {}).get(side, []))
    _write_contacts(db, cid, merged)


def _read_sof_format(f, i, errors):
    """Read one service's Internet format from the posted form (build 123).
    `i` is the service's index — the format fields are named fmt_*_<i>.
    The Yes/No answers and the route type are radio groups, so each is
    one value; the two Add tables are parallel lists, one row per entry.
    The last-mile checkboxes carry their row number as the value, so an
    unticked box in the first row cannot shift the second row's answer.
    A row with nothing in it is the blank row and is ignored; a row with
    some fields filled must have its name. The format needs at least one
    location and one service location — a SOF with no location to connect
    and no service to deliver is not a service. Returns the format dict."""
    fmt = _blank_format()

    def _lst(name):
        return f.getlist(f"fmt_{name}_{i}")

    def _one(name):
        return (f.get(f"fmt_{name}_{i}") or "").strip()

    def _txt(name):
        return _one(name)[:2000]

    def _pick1(name, options, label):
        v = _one(name)
        if v and v not in options:
            errors.append(f"Page 2: the {label} answer does not look right.")
            return ""
        return v

    def _checked(name):
        out = set()
        for v in _lst(name):
            if str(v).isdigit():
                out.add(int(v))
        return out

    _names = _lst("loc_name")
    _addrs = _lst("loc_address")
    _coords = _lst("loc_coords")
    for j in range(max(len(_names), len(_addrs), len(_coords))):
        _nm = _clean(_pick(_names, j))
        _ad = (_pick(_addrs, j) or "").strip()[:2000]
        _co = _clean(_pick(_coords, j))
        if not any((_nm, _ad, _co)):
            continue
        if not _nm:
            errors.append(f"Page 2: a location to be connected needs its name.")
            continue
        fmt["locations"].append({"name": _nm, "address": _ad, "coordinates": _co})
    _snames = _lst("svc_name")
    _bws = _lst("svc_bandwidth")
    _sremarks = _lst("svc_remarks")
    for j in range(max(len(_snames), len(_bws), len(_sremarks))):
        _nm = _clean(_pick(_snames, j))
        _bw = _clean(_pick(_bws, j))
        _rm = (_pick(_sremarks, j) or "").strip()[:2000]
        if not any((_nm, _bw, _rm)):
            continue
        if not _nm:
            errors.append("Page 2: a service location needs its name.")
            continue
        if not _bw:
            errors.append(f"Page 2: service location {_nm} needs its bandwidth.")
            continue
        fmt["service_locations"].append({"name": _nm, "bandwidth": _bw, "remarks": _rm})
    if not fmt["locations"]:
        errors.append("Page 2: add at least one location to be connected.")
    if not fmt["service_locations"]:
        errors.append("Page 2: add at least one service location.")
    # Build 124: GGC and FNA — one row each, the name fixed. A row with
    # a bandwidth or remarks is stored; an empty row is not.
    for _key, _label in (("ggc", "GGC"), ("fna", "FNA")):
        _bw = _clean(_one(_key + "_bandwidth"))
        _rm = _txt(_key + "_remarks")
        if _bw or _rm:
            fmt[_key] = {"name": _label, "bandwidth": _bw, "remarks": _rm}
    # Build 124: Data Connectivity — the same columns as the Internet
    # table, the name typed by hand. A row with anything in it needs
    # its name, and a named row needs its bandwidth.
    _dnames = _lst("dc_name")
    _dbws = _lst("dc_bandwidth")
    _dremarks = _lst("dc_remarks")
    for j in range(max(len(_dnames), len(_dbws), len(_dremarks))):
        _nm = _clean(_pick(_dnames, j))
        _bw = _clean(_pick(_dbws, j))
        _rm = (_pick(_dremarks, j) or "").strip()[:2000]
        if not any((_nm, _bw, _rm)):
            continue
        if not _nm:
            errors.append("Page 2: a data connectivity row needs its name.")
            continue
        if not _bw:
            errors.append(f"Page 2: data connectivity {_nm} needs its bandwidth.")
            continue
        fmt["data_connectivity"].append({"name": _nm, "bandwidth": _bw, "remarks": _rm})
    fmt["bgp_peering"] = _pick1("bgp", ("yes", "no"), "BGP peering")
    fmt["as_number"] = _clean(_one("as_number"))
    fmt["route_type"] = _pick1("route", ("default", "partial", "full"), "route type")
    fmt["prefix"] = _clean(_one("prefix"))
    fmt["additional_ip"] = _clean(_one("additional_ip"))
    if fmt["additional_ip"] and not fmt["additional_ip"].isdigit():
        errors.append("Page 2: the total number of IP required must be a number.")
        fmt["additional_ip"] = ""
    fmt["tech_other_details"] = _txt("tech_other_details")
    _lm_names = _lst("lm_name")
    _lm_iface = _lst("lm_interface")
    _lm_media = _lst("lm_media")
    _lm_cstm = _lst("lm_cstm")
    _fiber = _checked("lm_fiber")
    _radio = _checked("lm_radio")
    _prot = _checked("lm_protection")
    _dual = _checked("lm_dual_pop")
    _lm_rows = []
    for j in range(max(len(_lm_names), len(_lm_iface), len(_lm_media), len(_lm_cstm),
                       len(_fiber), len(_radio), len(_prot), len(_dual))):
        _nm = _clean(_pick(_lm_names, j))
        _iface = _clean(_pick(_lm_iface, j))
        _media = _clean(_pick(_lm_media, j))
        _cstm = _clean(_pick(_lm_cstm, j))
        _row = {"name": _nm, "fiber": 1 if j in _fiber else 0, "radio": 1 if j in _radio else 0,
                "protection": 1 if j in _prot else 0, "dual_pop": 1 if j in _dual else 0,
                "interface": _iface, "media": _media, "cstm_dvc": _cstm}
        if not any((_nm, _row["fiber"], _row["radio"], _row["protection"], _row["dual_pop"],
                    _iface, _media, _cstm)):
            continue
        if _iface and _iface not in ("FE", "GE", "OTHER"):
            errors.append("Page 2: the last-mile interface must be FE, GE or OTHER.")
            _row["interface"] = ""
        if _media and _media not in ("OPT", "ETH"):
            errors.append("Page 2: the last-mile media must be OPT or ETH.")
            _row["media"] = ""
        if not _nm:
            errors.append("Page 2: a last-mile row needs its name.")
            continue
        _lm_rows.append(_row)
    fmt["last_mile"] = _lm_rows if _lm_rows else _blank_format()["last_mile"]
    fmt["lm_protection_by"] = _pick1("lm_by", ("hrc", "customer"), "last-mile protection")
    fmt["lm_other_device"] = _txt("lm_other_device")
    fmt["other_isp"] = _pick1("other_isp", ("yes", "no"), "other ISP")
    fmt["other_isp_details"] = _txt("other_isp_details")
    fmt["more_isp"] = _pick1("more_isp", ("yes", "no"), "more ISP at the same gateway")
    fmt["more_isp_details"] = _txt("more_isp_details")
    fmt["off_gateway"] = _pick1("off_gateway", ("yes", "no"), "configuring gateway")
    fmt["off_gateway_devices"] = _clean(_one("off_gateway_devices"))
    fmt["off_gateway_details"] = _txt("off_gateway_details")
    fmt["off_wifi"] = _pick1("off_wifi", ("yes", "no"), "configuring WiFi")
    fmt["off_wifi_devices"] = _clean(_one("off_wifi_devices"))
    fmt["off_wifi_details"] = _txt("off_wifi_details")
    fmt["off_lan_delivery"] = _pick1("off_lan_delivery", ("yes", "no"), "configuring LAN during delivery")
    fmt["off_lan_support"] = _pick1("off_lan_support", ("yes", "no"), "configuring LAN during support")
    fmt["off_lan_support_devices"] = _clean(_one("off_lan_support_devices"))
    fmt["off_lan_support_details"] = _txt("off_lan_support_details")
    fmt["off_pc"] = _pick1("off_pc", ("yes", "no"), "configuring PC / laptop")
    fmt["off_pc_devices"] = _clean(_one("off_pc_devices"))
    fmt["off_pc_details"] = _txt("off_pc_details")
    fmt["off_other_details"] = _txt("off_other_details")
    return fmt


def _blank_form():
    return {"client_name": "", "business_type": "", "address": "", "phone": "", "email": "", "notes": "",
            "bin": "", "bin_address": "", "tin": "",
            "account_manager_id": None, "am_full_name": "", "am_designation": "", "am_phone": "", "am_email": "",
            "custom1": {},
            "contacts": _blank_contacts(),
            "contact_partial": {side: [] for side, _l in CONTACT_SIDES},
            "services": [{"id": "", "sof_number": "", "service": "", "service_type": "",
                          "service_description": "", "details": "", "file_name": "",
                          "activation_date": "", "billing_type": "",
                          "commercial_impact_date": "", "termination_date": "",
                          "public_code": "", "custom": {},
                          "format": _blank_format()}]}


def _form_from_db(db, c):
    form = {k: c[k] or "" for k in ("client_name", "business_type", "address", "phone", "email", "notes",
                                   "bin", "bin_address", "tin")}
    form["account_manager_id"] = c["account_manager_id"]
    # The account manager's information is this client's own copy (build 93):
    # what the Sales person typed on the form, never the manager's profile.
    form["am_full_name"] = c["am_full_name"] or ""
    form["am_designation"] = c["am_designation"] or ""
    form["am_phone"] = c["am_phone"] or ""
    form["am_email"] = c["am_email"] or ""
    custom = _load_custom(db, c["id"])
    form["custom1"] = {fid: v for (tt, _tid, fid), v in custom.items() if tt == "client"}
    # Build 118: the contact tables, in position order. A row with no
    # side or kind predates the tables and is not shown.
    form["contacts"] = _contacts_from_db(db, c["id"])
    form["contact_partial"] = {side: [] for side, _l in CONTACT_SIDES}
    form["services"] = [dict(id=r["id"], sof_number=r["sof_number"] or "", service=r["service"] or "",
                             service_type=r.get("service_type") or "",
                             service_description=r.get("service_description") or "",
                             details=r["details"] or "",
                             activation_date=str(r["activation_date"])[:10] if r["activation_date"] else "",
                             billing_type=r.get("billing_type") or "",
                             commercial_impact_date=str(r["commercial_impact_date"])[:10] if r["commercial_impact_date"] else "",
                             termination_date=str(r["termination_date"])[:10] if r["termination_date"] else "",
                             public_code=r["public_code"] or "",
                             custom={fid: v for (tt, tid, fid), v in custom.items()
                                     if tt == "service" and tid == r["id"]},
                             file_name=(_file_info(r["sof_file"]) or {}).get("original", ""),
                             format=_format_from_db(db, r["id"]))
                        for r in db.execute("SELECT * FROM client_services WHERE client_id=? ORDER BY position, id",
                                            (c["id"],)).fetchall()] or _blank_form()["services"]
    return form


def _pick(lst, i):
    return lst[i] if i < len(lst) else ""


def _read_form(db, existing, am_mode=False, contacts_locked=False,
               locked_contacts=None):
    """Read and check the posted form.
    Returns (form for redisplay, errors, contacts, services, new files saved, old files to delete after commit).
    `existing` is {service id: row} of the client being edited (empty for a new client).
    The activation date lives on every SOF (page 2, build 93) — never on the
    client page. The admin's fields are read by their id (cf1_/cf2_).
    Build 123: page 2 starts with a Service Type dropdown, and the
    contacts and the SOF rows appear only once a type is picked — so
    with no type at all there is nothing to check here but the type
    itself, and the contacts are read on page 2, not page 1. The
    service IS the picked type now (Internet/Data, IPTSP, Mail or
    Domain Hosting); the old free-text service, description and details
    boxes are gone with the old SOF block, and an Internet/Data SOF
    also carries its SERVICE DETAILS format. Build 124: the SOF row is
    the SOF number only — the activation date moved into the Dates
    block under it (Type, activation date, commercial impact date,
    service end date), which every service type has — and the SOF file
    field is gone from this page entirely, so no file is uploaded here
    any more; an existing SOF keeps the file it already has.
    `am_mode` (build 102) is the Add-services save on a finished client:
    page 1 is not changed by the account manager, and the activation date
    of a SOF is the Revenue Assurance department's — so neither is
    required here; a new SOF may be added without a date, and Revenue
    Assurance sets it once the change is approved. Build 121: the
    contacts are locked in Add-services mode for the account manager —
    after approval they cannot be changed here, they change only from a
    SOF edit — so with `contacts_locked` the contacts are not read from
    the form at all and the caller passes the rows as they stand in
    `locked_contacts` (the portal admin's Add-services form still posts
    them, and they apply at once).
    """

    f = request.form
    form = {k: _clean(f.get(k), 255) for k in ("client_name", "business_type", "phone", "email")}
    form["address"] = (f.get("address") or "").strip()[:2000]
    form["notes"] = (f.get("notes") or "").strip()[:4000]
    # Build 118: the client's tax details — optional fields on the Client page.
    form["bin"] = _clean(f.get("bin"), 255)
    form["bin_address"] = (f.get("bin_address") or "").strip()[:2000]
    form["tin"] = _clean(f.get("tin"), 255)
    errors = []

    # ---- page 1 (the fields the admin set: name, type, required or not)
    fields1 = _form_fields(db, 1)
    for fld in fields1:
        if am_mode:
            continue
        err = _check_value(form.get(fld["field_key"], ""), fld, "Page 1: " + fld["name"])
        if err:
            errors.append(err)
    if form["email"] and "@" not in form["email"]:
        errors.append("Page 1: the client email does not look right.")
    custom1 = {}
    for fld in fields1:
        if fld["is_default"]:
            continue
        val = _clean(f.get(f"cf1_{fld['id']}"), 2000)
        custom1[fld["id"]] = val
        if am_mode:
            continue
        err = _check_value(val, fld, "Page 1: " + fld["name"])
        if err:
            errors.append(err)
    form["custom1"] = custom1

    # ---- page 2 starts with the Service Type dropdown (build 123) —
    # the contacts and the SOF rows appear only once a type is picked,
    # so with no type at all there is nothing to check here but the
    # type itself. The contacts the form posts are ignored in that
    # case too — the tables were hidden, so an empty table is not a
    # missing account manager. A locked Add-services form still keeps
    # its rows (build 121), so they are returned as they stand.
    _types = f.getlist("service_type")
    # Build 124: a SOF made on an older form keeps its stored type when
    # it is re-saved — "Internet" or "Data" is not an option any more,
    # but it still counts as a picked type.
    _stored_types = {r["service"] for r in existing.values()}
    _any_type = any(t in SERVICE_TYPES or t in _stored_types for t in _types)
    if not _any_type:
        errors.append("Page 2: pick a Service Type.")
        contacts = (locked_contacts or _blank_contacts()) if contacts_locked else _blank_contacts()
        form["contacts"] = contacts
        form["contact_partial"] = {side: [] for side, _l in CONTACT_SIDES}
        _hrc_am = next((r for r in contacts.get("hrc", []) if r["ctype"] == "account_manager"), None)
        form["account_manager_id"] = _hrc_am["user_id"] if _hrc_am else None
        form["am_full_name"] = _hrc_am["name"] if _hrc_am else ""
        form["am_designation"] = _hrc_am["designation"] if _hrc_am else ""
        form["am_phone"] = _hrc_am["phone"] if _hrc_am else ""
        form["am_email"] = _hrc_am["email"] if _hrc_am else ""
        form["services"] = _blank_form()["services"]
        return form, errors, contacts, [], [], []

    # ---- the contacts: two tables on the Services page (build 123) —
    # Client contacts, then HRC Technologies Ltd contacts. Each row is
    # one person: a Type (account manager / technical / billing /
    # others, once per table), then the person's details. The HRC side
    # picks a department and a user and the four details fill in from
    # that user's account; they stay editable and change only this
    # client, never the person's own profile. The HRC account manager
    # IS the client's account manager in the portal: his user id and
    # his four details are the account_manager_id and the am_* columns
    # every notification and filter already uses. In each table the
    # account manager, technical contact and billing contact must all
    # be filled; Others is optional.
    if contacts_locked:
        contacts = locked_contacts or {side: [] for side, _l in CONTACT_SIDES}
        form["contact_partial"] = {side: [] for side, _l in CONTACT_SIDES}
    else:
        contacts, _edit, _cerr = _read_contact_tables(
            db, f, "Page 2", CONTACT_REQUIRED_KINDS, allow_am=True)
        errors.extend(_cerr)
        form["contact_partial"] = _edit
    form["contacts"] = contacts
    _hrc_am = next((r for r in contacts.get("hrc", []) if r["ctype"] == "account_manager"), None)
    form["account_manager_id"] = _hrc_am["user_id"] if _hrc_am else None
    form["am_full_name"] = _hrc_am["name"] if _hrc_am else ""
    form["am_designation"] = _hrc_am["designation"] if _hrc_am else ""
    form["am_phone"] = _hrc_am["phone"] if _hrc_am else ""
    form["am_email"] = _hrc_am["email"] if _hrc_am else ""

    # ---- page 2
    fields2 = _form_fields(db, 2)
    custom2 = {fld["id"]: f.getlist(f"cf2_{fld['id']}") for fld in fields2 if not fld["is_default"]}
    numbers = f.getlist("sof_number")
    saved_new, delete_old, services = [], [], []
    used_old = set()

    def _parse_day(vals, idx):
        """One date from a parallel list (build 124): the ISO date, or
        ('', True) when it does not parse."""
        _raw = (_pick(vals, idx) or "").strip()
        if not _raw:
            return "", False
        try:
            return datetime.strptime(_raw, "%Y-%m-%d").date().isoformat(), False
        except ValueError:
            return "", True
    for i in range(min(len(numbers), MAX_ROWS)):
        sid_raw = _pick(f.getlist("sof_existing"), i)
        sid = int(sid_raw) if str(sid_raw).isdigit() and int(sid_raw) in existing else None
        _stype = _clean(_pick(f.getlist("service_type"), i))
        row = {"id": sid or "", "sof_number": _clean(numbers[i]),
               # Build 123: the Service Type dropdown IS the service —
               # the short name the tab shows in brackets is the type
               # itself. The old free-text service, description and
               # details boxes are gone with the old SOF block, so a
               # SOF made on this form keeps no description; its
               # details live in the format instead.
               "service": _stype, "service_type": _stype,
               "service_description": "", "details": "", "file_name": "",
               "custom": {fid: _clean(_pick(vals, i), 2000) for fid, vals in custom2.items()},
               "format": _blank_format()}
        # The activation date of THIS SOF: the Sales user sets it here, and
        # it is required on every SOF — except in Add-services mode, where
        # a new SOF has no date yet and Revenue Assurance sets it once the
        # change is approved.
        raw_day = (_pick(f.getlist("sof_activation_date"), i) or "").strip()
        row["activation_date"] = ""
        bad_day = False
        if raw_day:
            try:
                row["activation_date"] = datetime.strptime(raw_day, "%Y-%m-%d").date().isoformat()
            except ValueError:
                bad_day = True
        # Build 124: the Dates block under the SOF number — the Type
        # (Prepaid/Postpaid) and the commercial impact and service end
        # dates. The Type is optional; a value that is neither is refused.
        _bt = (_pick(f.getlist("sof_billing_type"), i) or "").strip()
        bad_bt = bool(_bt and _bt not in ("Prepaid", "Postpaid"))
        row["billing_type"] = "" if bad_bt else _bt
        row["commercial_impact_date"], bad_ci = _parse_day(f.getlist("sof_commercial_impact_date"), i)
        row["termination_date"], bad_se = _parse_day(f.getlist("sof_service_end_date"), i)
        # The SOF keeps its share code across re-saves; a new SOF gets one in _write_children.
        row["public_code"] = existing[sid]["public_code"] if sid and existing[sid].get("public_code") else ""
        old_file = existing[sid]["sof_file"] if sid else None
        if not (row["sof_number"] or row["service"] or row["service_type"]
                or row["activation_date"] or row["billing_type"]
                or row["commercial_impact_date"] or row["termination_date"]
                or sid or any(row["custom"].values())):
            continue
        if sid:
            used_old.add(sid)
        n = len(services) + 1
        # Build 123: the type must be one of the four — or the value
        # this SOF already carries, so a SOF made on the old form keeps
        # its free-text service when it is re-saved. A row with no type
        # at all is not a service.
        _stored = existing[sid]["service"] if sid and sid in existing else ""
        if row["service_type"] not in SERVICE_TYPES and not (sid and row["service_type"] == _stored):
            errors.append(f"Page 2: pick a Service Type for service {n}.")
            continue
        # Build 123: an Internet/Data SOF carries its SERVICE DETAILS
        # format — a legacy "Internet" SOF too; the other types have no
        # format yet.
        if row["service_type"] in FORMAT_TYPES:
            row["format"] = _read_sof_format(f, i, errors)
        if bad_day:
            errors.append(f"Page 2: the activation date of service {n} does not look right.")
        if bad_bt:
            errors.append(f"Page 2: the Type of service {n} must be Prepaid or Postpaid.")
        if bad_ci:
            errors.append(f"Page 2: the commercial impact date of service {n} does not look right.")
        if bad_se:
            errors.append(f"Page 2: the service end date of service {n} does not look right.")
        _skey = {"sof_number": "sof_number", "sof_service": "service",
                 "sof_service_type": "service_type", "sof_service_description": "service_description",
                 "sof_details": "details", "sof_activation_date": "activation_date"}
        for fld in fields2:
            # Build 123: the service, its type, its description and its
            # details have no box on the form any more — the type is
            # checked above, the description and details are gone.
            if fld["field_key"] in ("sof_service", "sof_service_type",
                                    "sof_service_description", "sof_details"):
                continue
            if fld["field_key"] == "sof_activation_date" and (bad_day or am_mode):
                continue
            val = row.get(_skey.get(fld["field_key"], ""), "")
            err = _check_value(val, fld, f"Page 2: {fld['name']} of service {n}")
            if err:
                errors.append(err)
        for fid, val in row["custom"].items():
            fld = next(x for x in fields2 if x["id"] == fid)
            err = _check_value(val, fld, f"Page 2: {fld['name']} of service {n}")
            if err:
                errors.append(err)
        # Build 124: the SOF file field is gone from the Services page —
        # no file is uploaded here any more, and an existing SOF keeps
        # the file it already has. A file is still uploaded from the
        # SOF's own Edit page.
        row["file_json"] = old_file if sid else None
        row["file_name"] = (_file_info(old_file) or {}).get("original", "") if sid and old_file else ""
        services.append(row)
    for sid, old in existing.items():                    # a service row the user deleted from the form
        if sid not in used_old and old["sof_file"]:
            delete_old.append((_file_info(old["sof_file"]) or {}).get("stored"))
    # Build 96: a SOF number must not repeat — not twice in this client,
    # and not on any other client. The client's own SOFs (being edited)
    # do not count as repeats. The number is named in the error.
    _reported = set()
    for row in services:
        num = (row["sof_number"] or "").strip()
        if not num or num.lower() in _reported:
            continue
        if sum(1 for r in services if (r["sof_number"] or "").strip().lower() == num.lower()) > 1:
            errors.append(f"Page 2: SOF number {num} is used twice.")
            _reported.add(num.lower())
    _nums = [(r["sof_number"] or "").strip() for r in services if (r["sof_number"] or "").strip()]
    if _nums:
        _holders = ",".join("?" for _ in _nums)
        for _sid, _num in db.execute(
                "SELECT id, sof_number FROM client_services WHERE LOWER(sof_number) IN (" + _holders + ")",
                [n.lower() for n in _nums]).fetchall():
            if _sid not in existing and _num.lower() not in _reported:
                errors.append(f"Page 2: SOF number {_num} is already used on another client.")
                _reported.add(_num.lower())
    if not services and not errors:
        errors.append("Page 2: add at least one service with its SOF number.")
    form["services"] = services or _blank_form()["services"]
    return form, errors, contacts, services, saved_new, delete_old


def _write_children(db, cid, contacts, services, custom1):
    # A re-save rebuilds the SOF rows, so each rebuilt row keeps the old
    # row's own state (build 102): its short name, description, status
    # and any termination the account manager set. A new client has no
    # old rows, so a fresh SOF starts pending.
    old_sof = {r["id"]: r for r in db.execute("SELECT * FROM client_services WHERE client_id=?", (cid,)).fetchall()}
    db.execute("DELETE FROM client_services WHERE client_id=?", (cid,))
    db.execute("DELETE FROM client_field_values WHERE client_id=?", (cid,))
    _write_contacts(db, cid, contacts)
    for i, r in enumerate(services):
        code = r.get("public_code") or new_random_code_text(db)
        old = old_sof.get(r["id"]) if r.get("id") else None
        nid = db.execute("INSERT INTO client_services(client_id,position,sof_number,service,service_type,"
                         "billing_type,service_description,details,sof_file,activation_date,termination_date,"
                         "commercial_impact_date,termination_reason,status,public_code) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (cid, i, r["sof_number"], r["service"], r["service_type"],
                          r.get("billing_type") or (old.get("billing_type") if old else None),
                          r["service_description"] or None, r["details"] or None, r.get("file_json"),
                          r.get("activation_date") or None,
                          # Build 124: the Dates block posts the commercial
                          # impact and service end dates now — a blank box
                          # keeps the dates a re-saved SOF already had.
                          r.get("termination_date") or (old["termination_date"] if old else None),
                          r.get("commercial_impact_date") or (old["commercial_impact_date"] if old else None),
                          (old["termination_reason"] if old else None),
                          (old["status"] if old else "pending"), code)).lastrowid
        _save_custom(db, cid, "service", nid, r.get("custom") or {})
        # Build 123: the SOF's Internet format goes with it — the old
        # rows are gone with the rebuilt SOF, so only the new ones land.
        _write_format(db, nid, r.get("format"))
        # Build 112: the SOF's file joins its file history — the first
        # file, and the one each rebuild carries.
        if r.get("file_json"):
            _record_sof_file(db, nid, r["file_json"], None, g.user["id"])
    _save_custom(db, cid, "client", cid, custom1 or {})


def _write_contacts(db, cid, contacts):
    """Rewrite the contact rows (build 121): the two tables, client rows
    first then HRC rows, each in the order they were saved. The services
    and the client's own fields are untouched. `contacts` is the
    {side: [row]} dict from _read_contact_tables or _contacts_from_db."""
    db.execute("DELETE FROM client_contacts WHERE client_id=?", (cid,))
    pos = 0
    for side, _sl in CONTACT_SIDES:
        for r in contacts.get(side, []):
            db.execute("INSERT INTO client_contacts(client_id,position,name,designation,phone,email,"
                       "side,ctype,department_id,user_id,department_name) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (cid, pos, r["name"], r["designation"] or None, r["phone"] or None,
                        r["email"] or None, side, r["ctype"], r.get("department_id"), r.get("user_id"),
                        r.get("department_name") or None))
            pos += 1


def _contacts_form_data(db):
    """The data the contact tables need on a form (build 121): every
    department, the departments each Type may pick from (build 119/120
    — Others may pick any department), and every active portal user
    with their department, so the form can fill the four details in
    from the account when a user is picked."""
    departments = [dict(r) for r in db.execute("SELECT id, name FROM departments ORDER BY name").fetchall()]
    # Build 119: each HRC kind offers only its own departments (see
    # CONTACT_HRC_DEPTS above). Build 120: the match ignores capitals
    # and stray spaces, so a hand-typed "Technical Support" still matches.
    contact_depts = {kind: (departments if kind == "other" else
                            [d for d in departments
                             if d["name"].strip().casefold() in CONTACT_HRC_DEPTS_LOWER[kind]])
                     for kind, _kl in CONTACT_KINDS}
    users_info = {u["id"]: {"department_id": u["department_id"], "full_name": u["full_name"] or "",
                            "designation": u["designation"] or "", "phone": u["phone"] or "",
                            "email": u["email"] or ""}
                  for u in db.execute("SELECT id, department_id, full_name, designation, phone, email FROM users "
                                     "WHERE is_active=1 AND is_deleted=0 ORDER BY full_name").fetchall()}
    return departments, contact_depts, users_info


def _show_form(db, form, cid=None, c=None, errors=None, am_mode=False, page1_locked=False,
               services_blank=False):
    departments, contact_depts, users_info = _contacts_form_data(db)
    fields = {p: _form_fields(db, p) for p in (1, 2)}
    for p in (1, 2):
        for fld in fields[p]:
            fld["opts"] = [o.strip() for o in (fld["options"] or "").splitlines() if o.strip()]
    fmap = {fld["field_key"]: fld for p in (1, 2) for fld in fields[p] if fld["field_key"]}
    return render_template("client_form.html", form=form, cid=cid, c=c, errors=errors or [],
                           departments=departments, users_info=users_info, max_rows=MAX_ROWS,
                           contact_sides=CONTACT_SIDES, contact_kinds=CONTACT_KINDS,
                           contact_kind_label=CONTACT_KIND_LABEL,
                           dept_names={d["id"]: d["name"] for d in departments},
                           contact_depts=contact_depts, service_types=SERVICE_TYPES,
                           blank_service=_blank_form()["services"][0],
                           fields=fields, fmap=fmap, am_mode=am_mode, page1_locked=page1_locked,
                           services_blank=services_blank,
                           back=url_for("ddb.index", tab="clients"))


def _send_for_approval_notice(db, cid, name, resubmitted, am_id=None):
    verb = "sent the corrected client" if resubmitted else "sent a new client"
    ids = set(_sales_admin_ids(db))
    if resubmitted and am_id:
        # A re-save is a change after the client was added, so the account
        # manager is told too (build 96). The first add tells the Sales
        # admin only.
        ids.add(am_id)
    notify(db, ids, f"{g.user['full_name']} {verb} '{name}' for approval.",
           _link(cid), skip=g.user["id"])


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    db = get_db()
    roles = user_roles(db, g.user)
    sales = _sales_dept_id(db)
    if not sales:
        flash("The Sales department is not set yet. The portal admin sets it on the Client onboarding setup page.", "error")
        return redirect(url_for("ddb.index", tab="clients"))
    if "sales" not in roles and not is_portal_admin(g.user):
        abort(403)
    if request.method == "GET":
        form = _blank_form()
        # Build 122: the HRC table starts empty, like the Client table —
        # the account manager is no longer fixed as the Sales user
        # himself. The creator picks the account manager from the HRC
        # table (Type: Account manager, Department: Sales & Marketing).
        return _show_form(db, form)
    form, errors, contacts, services, saved_new, delete_old = _read_form(db, {})
    if errors:
        _remove_files(saved_new)
        return _show_form(db, form, errors=errors)
    try:
        # Build 110: a new client takes the next serial number — one past
        # the highest live serial, so it fills the first gap a deletion left.
        serial = next_client_serial(db)
        cid = db.execute(
            "INSERT INTO client_onboardings(department_id,owner_id,client_name,business_type,address,phone,email,"
            "notes,bin,bin_address,tin,account_manager_id,am_full_name,am_designation,am_phone,am_email,status,serial) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'pending', ?)",
            (sales, g.user["id"], form["client_name"], form["business_type"] or None, form["address"] or None,
             form["phone"] or None, form["email"] or None, form["notes"] or None,
             form["bin"] or None, form["bin_address"] or None, form["tin"] or None,
             form["account_manager_id"],
             form["am_full_name"] or None, form["am_designation"] or None, form["am_phone"] or None,
             form["am_email"] or None, serial)).lastrowid
        _write_children(db, cid, contacts, services, form["custom1"])
        _ncontacts = len(contacts.get("client", [])) + len(contacts.get("hrc", []))
        _history(db, cid, g.user, "sent for approval", f"{_ncontacts} contacts, {len(services)} service(s)")
        log(db, "client_new", f"{serial} {form['client_name']}")
        _send_for_approval_notice(db, cid, form["client_name"], False)
        db.commit()
    except Exception:
        db.rollback()
        _remove_files(saved_new)
        raise
    flash("Saved and sent to the Sales admin for approval.", "ok")
    return redirect(_link(cid))


def _edit_services(db, c, roles):
    """Build 102: Add services on a finished client (the account manager,
    or the portal admin). The client itself stays finished. Build 121:
    the contacts are locked here for the account manager — after approval
    they change only from a SOF edit, never from this page — while the
    portal admin's contact changes still apply at once. Every service
    change — a new SOF, or a changed one — waits for the Sales admin to
    approve it; the portal admin's changes apply at once. Build 110: the account manager CAN set the
    activation date when he adds a SOF — the date stays (Revenue Assurance may change it later in the flow).
    Build 112: the account manager's services page is blank —
    no existing SOF is shown, so a new service can only be entered as a
    new SOF; an existing SOF is changed only from its own Edit button.
    Build 124: the SOF file field is gone from this page — a new SOF
    gets its file from its own Edit page instead — and the page opens
    with the Service Type dropdown only; picking a type reveals the
    contacts and the service form."""
    cid = c["id"]
    portal_admin = is_portal_admin(g.user)
    if request.method == "GET":
        # Build 112: the account manager sees a blank services page — no
        # existing SOF is shown, so a new service can only be entered as
        # a new SOF and never typed over an old one. The portal admin
        # keeps the existing SOFs on the form, as before.
        _f = _form_from_db(db, c)
        if not portal_admin:
            _f["services"] = [_blank_form()["services"][0]]
        return _show_form(db, _f, cid=cid, c=c, am_mode=True, page1_locked=not portal_admin,
                          services_blank=not portal_admin)
    existing = {r["id"]: r for r in db.execute("SELECT * FROM client_services WHERE client_id=?", (cid,)).fetchall()}
    # Build 121: after approval the contacts cannot be changed here —
    # the account manager changes them from a SOF edit — so for him the
    # tables are read-only and the rows stand as they are. The portal
    # admin's form still posts them, and they apply at once.
    _locked_contacts = _contacts_from_db(db, cid) if not portal_admin else None
    form, errors, contacts, services, saved_new, delete_old = _read_form(
        db, existing, am_mode=True,
        contacts_locked=not portal_admin, locked_contacts=_locked_contacts)
    if errors:
        _remove_files(saved_new)
        return _show_form(db, form, cid=cid, c=c, errors=errors, am_mode=True, page1_locked=not portal_admin,
                          services_blank=not portal_admin)
    try:
        if portal_admin:
            # The portal admin is the authority: page 1 applies at once.
            db.execute("UPDATE client_onboardings SET client_name=?, business_type=?, address=?, phone=?, email=?, "
                       "notes=?, bin=?, bin_address=?, tin=?, account_manager_id=?, am_full_name=?, am_designation=?, "
                       "am_phone=?, am_email=?, updated_at=datetime('now','localtime') WHERE id=?",
                       (form["client_name"], form["business_type"] or None, form["address"] or None,
                        form["phone"] or None, form["email"] or None, form["notes"] or None,
                        form["bin"] or None, form["bin_address"] or None, form["tin"] or None,
                        form["account_manager_id"], form["am_full_name"] or None, form["am_designation"] or None,
                        form["am_phone"] or None, form["am_email"] or None, cid))
            _save_custom(db, cid, "client", cid, form["custom1"])
        else:
            # Build 121: the contacts are locked, so the account
            # manager's own details stay as they are too — the am_*
            # columns are written back unchanged.
            db.execute("UPDATE client_onboardings SET am_full_name=?, am_designation=?, am_phone=?, am_email=?, "
                       "updated_at=datetime('now','localtime') WHERE id=?",
                       (c["am_full_name"] or None, c["am_designation"] or None,
                        c["am_phone"] or None, c["am_email"] or None, cid))
        old_contacts = [(r["side"] or "", r["ctype"] or "", r["department_id"], r["user_id"],
                         r["name"] or "", r["designation"] or "", r["phone"] or "",
                         r["email"] or "", r.get("department_name") or "")
                        for r in db.execute("SELECT side, ctype, department_id, user_id, name, designation, phone, "
                                           "email, department_name FROM client_contacts WHERE client_id=? "
                                           "ORDER BY position, id", (cid,)).fetchall()]
        _write_contacts(db, cid, contacts)
        contacts_changed = ([(side, r["ctype"], r.get("department_id"), r.get("user_id"),
                              r["name"], r["designation"], r["phone"], r["email"],
                              r.get("department_name") or "")
                             for side, _sl in CONTACT_SIDES for r in contacts.get(side, [])]
                            != old_contacts)
        added, changed, skipped = [], [], []
        for row in services:
            sid = row.get("id")
            if sid and not portal_admin:
                # Build 112: the account manager changes an existing SOF
                # only from its own Edit button — the Add services form
                # shows no existing SOFs, so a row carrying one here is
                # ignored, never written over the old SOF.
                continue
            if not sid:
                new = {"sof_number": row["sof_number"], "service": row["service"],
                       "service_type": row["service_type"], "service_description": row["service_description"],
                       "details": row["details"],
                       # Build 124: the Dates block of a new SOF travels
                       # with it — its Type and its commercial impact and
                       # service end dates, as well as its activation date.
                       "termination_date": row.get("termination_date") or "",
                       "commercial_impact_date": row.get("commercial_impact_date") or "",
                       "billing_type": row.get("billing_type") or "",
                       "termination_reason": "",
                       # Build 110: the activation date the account manager
                       # set is part of the new SOF.
                       # Build 123: its Internet format travels with it
                       # (a staged new SOF is approved from this JSON).
                       "activation_date": row.get("activation_date") or "",
                       "sof_file": row.get("file_json"), "file_name": row.get("file_name") or "",
                       "format": row.get("format") or _blank_format()}
                if portal_admin:
                    pos = db.execute("SELECT COALESCE(MAX(position), -1)+1 FROM client_services WHERE client_id=?",
                                     (cid,)).fetchone()[0]
                    # The portal admin applies at once: a SOF with its
                    # activation date is live already, one without waits
                    # for the date (the portal admin sets it from the
                    # Dates form on the client page).
                    _st = "activated" if row.get("activation_date") else "pending"
                    _nid = db.execute("INSERT INTO client_services(client_id,position,sof_number,service,service_type,"
                                      "billing_type,service_description,details,sof_file,activation_date,"
                                      "termination_date,commercial_impact_date,public_code,status) "
                                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                      (cid, pos, new["sof_number"], new["service"], new["service_type"],
                                       new["billing_type"] or None,
                                       new["service_description"] or None, new["details"] or None,
                                       row.get("file_json"), row.get("activation_date") or None,
                                       new["termination_date"] or None, new["commercial_impact_date"] or None,
                                       new_random_code_text(db), _st)).lastrowid
                    # Build 112: the file joins the SOF's file history.
                    if row.get("file_json"):
                        _record_sof_file(db, _nid, row["file_json"], None, g.user["id"])
                    # Build 123: the SOF's Internet format goes with it.
                    _write_format(db, _nid, row.get("format"))
                    _history(db, cid, g.user, f"SOF {new['sof_number']} added by the portal admin",
                             "Activated." if _st == "activated" else "Pending — set its activation date from the Dates form.")
                else:
                    db.execute("INSERT INTO client_sof_edits(client_id,service_id,editor_id,old_values,new_values)"
                               " VALUES (?,?,?,NULL,?)",
                               (cid, None, g.user["id"], json.dumps(new)))
                    _history(db, cid, g.user, f"SOF {new['sof_number']} added — sent for approval")
                    notify(db, set(_sales_admin_ids(db)),
                           f"{g.user['full_name']} added SOF {new['sof_number']} to '{c['client_name']}': "
                           f"{_sof_new_text(new)} Approve or reject it from the client page.",
                           _link(cid), skip=g.user["id"])
                added.append(new["sof_number"])
                continue
            old = existing[sid]
            new = _sof_snapshot(old)
            new.update({"sof_number": row["sof_number"], "service": row["service"],
                        "service_type": row["service_type"], "service_description": row["service_description"],
                        "details": row["details"],
                        # Build 110: the activation date and the SOF file
                        # from the form are part of the change. Build 124:
                        # the Dates block is too — a blank box keeps the
                        # old date or Type rather than wiping it (build 113).
                        "activation_date": row.get("activation_date") or "",
                        "billing_type": row.get("billing_type") or old.get("billing_type") or "",
                        "termination_date": row.get("termination_date") or old.get("termination_date") or "",
                        "commercial_impact_date": row.get("commercial_impact_date") or old.get("commercial_impact_date") or "",
                        "sof_file": row.get("file_json"), "file_name": row.get("file_name") or ""})
            diff = _sof_change_text(_sof_snapshot(old), new)
            if (row.get("file_json") or None) != (old["sof_file"] or None):
                diff = (diff + "; SOF file: replaced" if diff != "No fields changed."
                        else "SOF file: replaced")
            # Build 123: a format filled in (or changed) on an existing
            # SOF counts as a change too, even when no SOF field moved.
            # A row whose type is not Internet/Data carries no format on
            # the form — it is the blank default, not a posted one — so it
            # keeps the stored format, unless the type moved away from
            # Internet/Data, which drops it.
            _fmt = row.get("format")
            if row["service_type"] not in FORMAT_TYPES:
                _fmt = None if row["service"] != old["service"] else _format_from_db(db, sid)
            _fmt_changed = _format_norm(_fmt) != _format_norm(_format_from_db(db, sid))
            if _fmt_changed:
                diff = (diff + "; Internet format: changed" if diff != "No fields changed."
                        else "Internet format: changed")
            if diff == "No fields changed.":
                continue
            # One change at a time per SOF: a SOF that already has a
            # change in flight cannot take another until that one
            # finishes — otherwise the second approval would land on
            # values the first change is still carrying through the flow.
            if _open_sof_edit(db, sid) is not None:
                skipped.append(old["sof_number"])
                continue
            if portal_admin:
                # Build 113: the activation date lands here too, as it
                # does on approval and on the portal admin's Edit save —
                # a blank box keeps the old date rather than wiping it.
                db.execute("UPDATE client_services SET sof_number=?, service=?, service_type=?, "
                           "service_description=?, details=?, sof_file=?, activation_date=?, "
                           "billing_type=?, termination_date=?, commercial_impact_date=? WHERE id=?",
                           (new["sof_number"], new["service"], new["service_type"],
                            new["service_description"] or None, new["details"] or None,
                            new.get("sof_file") or old["sof_file"],
                            new.get("activation_date") or old["activation_date"] or None,
                            new.get("billing_type") or None,
                            new.get("termination_date") or None,
                            new.get("commercial_impact_date") or None, sid))
                # Build 112: a file the portal admin replaces joins the
                # SOF's file history — the old one stays downloadable.
                if new.get("sof_file") and new["sof_file"] != (old["sof_file"] or None):
                    _record_sof_file(db, sid, new["sof_file"], None, g.user["id"])
                # Build 123: the SOF's Internet format goes with the change.
                _write_format(db, sid, _fmt)
                _history(db, cid, g.user, f"SOF {old['sof_number']} changed by the portal admin", diff)
            else:
                db.execute("INSERT INTO client_sof_edits(client_id,service_id,editor_id,old_values,new_values)"
                           " VALUES (?,?,?,?,?)",
                           (cid, sid, g.user["id"], json.dumps(_sof_snapshot(old)), json.dumps(new)))
                # Build 110: the SOF goes to pending as soon as the
                # account manager saves the change.
                if old["status"] in ("activated", "terminated"):
                    db.execute("UPDATE client_services SET status='pending' WHERE id=?", (sid,))
                _history(db, cid, g.user, f"SOF {old['sof_number']} change sent for approval", diff)
                notify(db, set(_sales_admin_ids(db)),
                       f"{g.user['full_name']} changed SOF {old['sof_number']} of '{c['client_name']}': {diff} "
                       "Approve or reject it from the client page.", _link(cid), skip=g.user["id"])
            changed.append(old["sof_number"])
        if contacts_changed:
            _history(db, cid, g.user, "contacts changed by the portal admin" if portal_admin
                     else "contacts changed by the account manager")
        log(db, "client_services_edit", f"{client_no(c)} {c['client_name']}")
        db.commit()
    except Exception:
        db.rollback()
        _remove_files(saved_new)
        raise
    if skipped:
        flash(f"SOF {', '.join(skipped)} already has a change in flight — that change was left alone.", "error")
    if portal_admin:
        flash("Saved. The changes apply at once.", "ok")
    elif added or changed:
        flash("Saved. The Sales admin will approve or reject the service changes.", "ok")
    else:
        flash("Saved.", "ok")
    return redirect(_link(cid))


@bp.route("/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def edit(cid):
    db, c, roles = _load(cid)
    perms = _perms(db, g.user, roles, c)
    am_services = perms["add_services"]
    if not perms["edit"] and not am_services:
        flash("Only a rejected client can be changed, by the Sales user who made it or the Sales admin — "
              "or a client still waiting for approval, by its account manager. "
              "On a finished client the account manager adds services from the client page.", "error")
        return redirect(_link(cid))
    if am_services and not perms["edit"]:
        # Build 102: Add services on a finished client. The client itself
        # stays finished; the account manager changes contacts and
        # services, and every service change waits for the Sales admin.
        return _edit_services(db, c, roles)
    if request.method == "GET":
        return _show_form(db, _form_from_db(db, c), cid=cid, c=c)
    existing = {r["id"]: r for r in db.execute("SELECT * FROM client_services WHERE client_id=?", (cid,)).fetchall()}
    form, errors, contacts, services, saved_new, delete_old = _read_form(db, existing)
    if errors:
        _remove_files(saved_new)
        return _show_form(db, form, cid=cid, c=c, errors=errors)
    was_rejected = c["status"] == "rejected"   # otherwise pending, edited by the account manager (build 97)
    try:
        sets = ["client_name=?", "business_type=?", "address=?", "phone=?", "email=?", "notes=?",
                "bin=?", "bin_address=?", "tin=?",
                "account_manager_id=?", "am_full_name=?", "am_designation=?", "am_phone=?", "am_email=?"]
        params = [form["client_name"], form["business_type"] or None, form["address"] or None,
                  form["phone"] or None, form["email"] or None, form["notes"] or None,
                  form["bin"] or None, form["bin_address"] or None, form["tin"] or None,
                  form["account_manager_id"],
                  form["am_full_name"] or None, form["am_designation"] or None,
                  form["am_phone"] or None, form["am_email"] or None]
        if was_rejected:
            sets.append("status='pending', reject_reason=NULL, decided_by=NULL, decided_at=NULL, "
                        "updated_at=datetime('now','localtime')")
        else:
            # The client stays waiting for approval; nothing is decided yet.
            sets.append("updated_at=datetime('now','localtime')")
        done = db.execute("UPDATE client_onboardings SET " + ", ".join(sets) + " WHERE id=? AND status=?",
                          params + [cid, c["status"]]).rowcount
        if done == 0:                                    # somebody else changed the status meanwhile
            db.rollback()
            _remove_files(saved_new)
            flash("This client is not rejected any more, so it cannot be changed." if was_rejected else
                  "This client is not waiting for approval any more, so it cannot be changed.", "error")
            return redirect(_link(cid))
        _write_children(db, cid, contacts, services, form["custom1"])
        log(db, "client_edit", f"{client_no(c)} {form['client_name']}")
        if was_rejected:
            _history(db, cid, g.user, "saved again and sent for approval")
            _send_for_approval_notice(db, cid, form["client_name"], True, form["account_manager_id"])
            flash("Saved and sent to the Sales admin for approval again.", "ok")
        else:
            _history(db, cid, g.user, "changed by the account manager")
            notify(db, {c["owner_id"]} | set(_sales_admin_ids(db)),
                   f"The client '{form['client_name']}' was changed by the account manager "
                   f"{g.user['full_name']} and is still waiting for approval.",
                   _link(cid), skip=g.user["id"])
            flash("Saved. The client is still waiting for approval.", "ok")
        db.commit()
    except Exception:
        db.rollback()
        _remove_files(saved_new)
        raise
    _remove_files(delete_old)
    return redirect(_link(cid))


# ---------------------------------------------------------------- Sales admin: approve / reject
@bp.route("/<int:cid>/approve", methods=["POST"])
@login_required
def approve(cid):
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["approve"]:
        abort(403)
    done = db.execute("UPDATE client_onboardings SET status='approved', decided_by=?, "
                      "decided_at=datetime('now','localtime'), updated_at=datetime('now','localtime') "
                      "WHERE id=? AND status='pending'", (g.user["id"], cid)).rowcount
    if done:
        _history(db, cid, g.user, "approved")
        log(db, "client_approve", f"{client_no(c)} {c['client_name']}")
        text = f"The client '{c['client_name']}' was approved."
        notify(db, {c["owner_id"]} | _client_watchers(db, c), text, _link(cid), skip=g.user["id"])
        # Revenue Assurance sees it first (view only). The three technical departments
        # see it only once Revenue Assurance forwards it, so they are told then.
        # The forward/reject instruction goes to Revenue Assurance only (build 105):
        # the watchers already got the plain message above, and telling the
        # account manager to forward it was showing them Revenue Assurance's job.
        notify(db, set(_members(db, "revenue_assurance")),
               text + " You can view it (view only). Forward it to Transmission, Core and Technical support when ready, or reject it with a reason.",
               _link(cid), skip=g.user["id"])
        db.commit()
        flash("Approved. Revenue Assurance can see it; Transmission, Core and Technical support will see it once Revenue Assurance forwards it.", "ok")
    else:
        db.rollback()
        flash("This client was already decided.", "error")
    return redirect(_link(cid))


@bp.route("/<int:cid>/reject", methods=["POST"])
@login_required
def reject(cid):
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["approve"]:
        abort(403)
    reason = " ".join((request.form.get("reason") or "").split())[:1000]
    if not reason:
        flash("Type the reason, so the Sales user knows what to fix.", "error")
        return redirect(_link(cid))
    done = db.execute("UPDATE client_onboardings SET status='rejected', reject_reason=?, decided_by=?, "
                      "decided_at=datetime('now','localtime'), updated_at=datetime('now','localtime') "
                      "WHERE id=? AND status='pending'", (reason, g.user["id"], cid)).rowcount
    if done:
        _history(db, cid, g.user, "rejected", reason)
        log(db, "client_reject", f"{client_no(c)} {c['client_name']}")
        notify(db, {c["owner_id"]} | _client_watchers(db, c), f"The client '{c['client_name']}' was rejected: {reason}", _link(cid), skip=g.user["id"])
        db.commit()
        flash("Rejected. It went back to the Sales user.", "ok")
    else:
        db.rollback()
        flash("This client was already decided.", "error")
    return redirect(_link(cid))


# ---------------------------------------------------------------- Revenue Assurance decision: forward or reject
@bp.route("/<int:cid>/ra-decision", methods=["POST"])
@login_required
def ra_decision(cid):
    """The Revenue Assurance admin forwards the approved client to
    Transmission, Core and Technical support, or rejects it with a reason
    and it goes back to the Sales user (build 89)."""
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["forward"]:
        abort(403)
    decision = (request.form.get("decision") or "").strip()
    if decision == "forward":
        done = db.execute("UPDATE client_onboardings SET status='forwarded', decided_by=?, "
                          "decided_at=datetime('now','localtime'), updated_at=datetime('now','localtime') "
                          "WHERE id=? AND status='approved'", (g.user["id"], cid)).rowcount
        if done:
            _history(db, cid, g.user, "forwarded")
            log(db, "client_forward", f"{client_no(c)} {c['client_name']}")
            text = f"The client '{c['client_name']}' was forwarded by Revenue Assurance."
            for role in SAN_ROLES:
                notify(db, _members(db, role), text + " View the record; each SOF needs its own SAN report from one of you.",
                       _link(cid), skip=g.user["id"])
            # The account manager and the Sales admin are told once, not
            # once per technical department (build 96).
            notify(db, _client_watchers(db, c), text, _link(cid), skip=g.user["id"])
            db.commit()
            flash("Forwarded. Transmission, Core and Technical support can now see it.", "ok")
        else:
            db.rollback()
            flash("This client was already decided.", "error")
    elif decision == "reject":
        reason = " ".join((request.form.get("reason") or "").split())[:1000]
        if not reason:
            flash("Type the reason, so the Sales user knows what to fix.", "error")
            return redirect(_link(cid))
        done = db.execute("UPDATE client_onboardings SET status='rejected', reject_reason=?, decided_by=?, "
                          "decided_at=datetime('now','localtime'), updated_at=datetime('now','localtime') "
                          "WHERE id=? AND status='approved'", (reason, g.user["id"], cid)).rowcount
        if done:
            _history(db, cid, g.user, "rejected", reason)
            log(db, "client_reject", f"{client_no(c)} {c['client_name']}")
            notify(db, {c["owner_id"]} | _client_watchers(db, c), f"The client '{c['client_name']}' was rejected by Revenue Assurance: {reason}",
                   _link(cid), skip=g.user["id"])
            db.commit()
            flash("Rejected. It went back to the Sales user.", "ok")
        else:
            db.rollback()
            flash("This client was already decided.", "error")
        # A rejected client is invisible to Revenue Assurance (only Sales, its
        # owner and the portal admin can open it), so sending them back to the
        # client page would land on a 404. Take them to the Client onboarding
        # page instead (build 91).
        return redirect(url_for("ddb.index", tab="clients"))
    else:
        flash("Choose Forward or Reject.", "error")
    return redirect(_link(cid))


# ---------------------------------------------------------------- SAN report: one per SOF (build 105)
def _can_upload_sof_san(db, user, roles, c, s):
    """A SAN report can be uploaded for this SOF (build 105, build 110).
    In the normal flow the client was forwarded, this SOF has none yet,
    and the uploader is Transmission, Core or Technical support (or the
    portal admin). In the edited-SOF flow the client is finished and the
    SOF's change is waiting for its new SAN report, and the same three
    departments (or the portal admin) upload it."""
    san_role = bool(roles.intersection(SAN_ROLES)) or is_portal_admin(user)
    if c["status"] == "forwarded" and not s["san_file"] and san_role:
        return True
    if c["status"] == "completed" and san_role:
        edit = _open_sof_edit(db, s["id"])
        if edit is not None and edit["status"] == "san":
            return True
    return False


def _can_remove_sof_san(user, c, s):
    """The portal admin can remove one SOF's SAN report while the client
    is not completed (build 105)."""
    return bool(s["san_file"]) and c["status"] != "completed" and is_portal_admin(user)


@bp.route("/<int:cid>/sof/<int:sid>/san", methods=["POST"])
@login_required
def sof_san_upload(cid, sid):
    db, c, roles = _load(cid)
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if row is None:
        abort(404)
    if not _can_upload_sof_san(db, g.user, roles, c, row):
        flash("The SAN report cannot be uploaded: this SOF already has one, or you are not allowed to.", "error")
        return redirect(_link(cid))
    # Build 110: in the edited-SOF flow the upload is for the change that
    # is waiting for its new SAN report — the old report stays on the SOF.
    edit = _open_sof_edit(db, sid) if c["status"] == "completed" else None
    edit_upload = edit is not None and edit["status"] == "san"
    upload = request.files.get("san_file")
    if not upload or not upload.filename:
        flash("Choose the SAN report file.", "error")
        return redirect(_link(cid))
    own_dept = _dept_row(db, g.user["department_id"]) or _dept_row(db, _sales_dept_id(db))
    file_json, err = routes_deptdb._save_ddb_file(upload, own_dept)
    if err:
        flash(err, "error")
        return redirect(_link(cid))
    stored = _file_info(file_json)["stored"]
    try:
        if edit_upload:
            # The SOF already has a report — this one is the edited SOF's,
            # so it is added beside the old one, not instead of it.
            db.execute("UPDATE client_services SET san_file=?, san_by=?, san_at=datetime('now','localtime') "
                       "WHERE id=? AND client_id=?", (file_json, g.user["id"], sid, cid))
            db.execute("INSERT INTO client_sof_san_uploads(sof_id,edit_id,san_file,uploaded_by,uploaded_at) "
                       "VALUES (?,?,?,?,datetime('now','localtime'))",
                       (sid, edit["id"], file_json, g.user["id"]))
            db.execute("UPDATE client_sof_edits SET status='ra_dates' WHERE id=?", (edit["id"],))
            _history(db, cid, g.user, f"SAN report uploaded for the edited SOF {row['sof_number']}",
                     _file_info(file_json)["original"])
            log(db, "client_san", f"{client_no(c)} {c['client_name']} {row['sof_number']}")
            text = (f"The SAN report for the edited SOF {row['sof_number']} of '{c['client_name']}' "
                    f"was uploaded by {g.user['full_name']}. Revenue Assurance can now change the dates.")
            ids = set(_members(db, "revenue_assurance")) | set(_members(db, "sales")) | {c["owner_id"]} | _client_watchers(db, c)
            notify(db, ids, text, _link(cid), skip=g.user["id"])
            db.commit()
            flash(f"SAN report uploaded for the edited SOF {row['sof_number']}. Revenue Assurance and Sales received it.", "ok")
            return redirect(_link(cid))
        # The WHERE makes the upload atomic: of two people uploading at the same moment only one wins.
        done = db.execute("UPDATE client_services SET san_file=?, san_by=?, san_at=datetime('now','localtime') "
                          "WHERE id=? AND client_id=? AND san_file IS NULL",
                          (file_json, g.user["id"], sid, cid)).rowcount
        if not done:
            db.rollback()
            _remove_files([stored])
            flash("A SAN report was uploaded for this SOF already.", "error")
            return redirect(_link(cid))
        db.execute("INSERT INTO client_sof_san_uploads(sof_id,edit_id,san_file,uploaded_by,uploaded_at) "
                   "VALUES (?,?,?, ?,datetime('now','localtime'))", (sid, None, file_json, g.user["id"]))
        # The client counts as SAN-uploaded only once EVERY SOF has its own report.
        n = db.execute("SELECT COUNT(*) FROM client_services WHERE client_id=?", (cid,)).fetchone()[0]
        missing = db.execute("SELECT COUNT(*) FROM client_services WHERE client_id=? AND san_file IS NULL",
                             (cid,)).fetchone()[0]
        last = n > 0 and missing == 0
        if last and c["status"] == "forwarded":
            db.execute("UPDATE client_onboardings SET status='san_uploaded', "
                       "updated_at=datetime('now','localtime') WHERE id=?", (cid,))
        _history(db, cid, g.user, f"SAN report uploaded for SOF {row['sof_number']}",
                 _file_info(file_json)["original"])
        log(db, "client_san", f"{client_no(c)} {c['client_name']} {row['sof_number']}")
        text = (f"The SAN report for SOF {row['sof_number']} of '{c['client_name']}' "
                f"was uploaded by {g.user['full_name']}.")
        if last:
            text += " All SOFs now have their SAN report."
        ids = set(_members(db, "revenue_assurance")) | set(_members(db, "sales")) | {c["owner_id"]} | _client_watchers(db, c)
        notify(db, ids, text, _link(cid), skip=g.user["id"])
        db.commit()
    except Exception:
        db.rollback()
        _remove_files([stored])
        raise
    flash(f"SAN report uploaded for SOF {row['sof_number']}. Revenue Assurance and Sales received it.", "ok")
    return redirect(_link(cid))


@bp.route("/<int:cid>/sof/<int:sid>/san/remove", methods=["POST"])
@login_required
def sof_san_remove(cid, sid):
    """Portal admin only, to fix a wrong upload while the record is not completed.
    If the client was already SAN-uploaded it goes back to forwarded — it was
    approved and forwarded already, so it does not go back to approved.
    Build 110: the SOF keeps every upload, so removing the latest one
    brings the previous one back as the current report; if the removed
    report was the edited SOF's, its change waits for a new upload again."""
    db, c, roles = _load(cid)
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if row is None:
        abort(404)
    if not _can_remove_sof_san(g.user, c, row):
        abort(403)
    latest = db.execute("SELECT * FROM client_sof_san_uploads WHERE sof_id=? ORDER BY id DESC LIMIT 1",
                        (sid,)).fetchone()
    info = _file_info(row["san_file"])
    if latest is not None:
        info = _file_info(latest["san_file"])
        db.execute("DELETE FROM client_sof_san_uploads WHERE id=?", (latest["id"],))
        if latest["edit_id"]:
            db.execute("UPDATE client_sof_edits SET status='san' WHERE id=? AND status='ra_dates'",
                       (latest["edit_id"],))
    prev = db.execute("SELECT * FROM client_sof_san_uploads WHERE sof_id=? ORDER BY id DESC LIMIT 1",
                      (sid,)).fetchone()
    if prev is not None:
        db.execute("UPDATE client_services SET san_file=?, san_by=?, san_at=? WHERE id=? AND client_id=?",
                   (prev["san_file"], prev["uploaded_by"], prev["uploaded_at"], sid, cid))
    else:
        db.execute("UPDATE client_services SET san_file=NULL, san_by=NULL, san_at=NULL WHERE id=? AND client_id=?",
                   (sid, cid))
    if c["status"] == "san_uploaded":
        still_missing = db.execute("SELECT COUNT(*) FROM client_services WHERE client_id=? AND san_file IS NULL",
                                   (cid,)).fetchone()[0]
        if still_missing:
            db.execute("UPDATE client_onboardings SET status='forwarded', "
                       "updated_at=datetime('now','localtime') WHERE id=?", (cid,))
    _history(db, cid, g.user, f"SAN report removed for SOF {row['sof_number']}", (info or {}).get("original"))
    log(db, "client_san_remove", f"{client_no(c)} {c['client_name']} {row['sof_number']}")
    notify(db, _client_watchers(db, c),
           f"The SAN report for SOF {row['sof_number']} of '{c['client_name']}' was removed by {g.user['full_name']}.",
           _link(cid), skip=g.user["id"])
    db.commit()
    if info:
        _remove_files([info["stored"]])
    flash(f"The SAN report for SOF {row['sof_number']} was removed. A new one can be uploaded.", "ok")
    return redirect(_link(cid))


# ---------------------------------------------------------------- Revenue Assurance: one SOF's activation date
@bp.route("/<int:cid>/sof/<int:sid>/activation", methods=["POST"])
@login_required
def sof_activation(cid, sid):
    """Revenue Assurance edits the activation date of ONE SOF after the SAN
    report (build 93). The date the Sales user set is shown on the SOF row;
    changing it does NOT complete the record or send it to Finance — that
    takes the separate forward below. Build 110: this only runs before the
    record has reached Finance. A SOF with a change in flight is changed
    through that flow, never here, and once the record is completed the
    dates are locked except for the portal admin and an administrative
    permission user (see sof_dates below)."""
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["sof_activation"]:
        abort(403)
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if row is None:
        abort(404)
    if _open_sof_edit(db, sid) is not None:
        flash("This SOF has a change going through the approval flow — change its dates there.", "error")
        return redirect(_link(cid))
    raw = (request.form.get("activation_date") or "").strip()
    try:
        day = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        flash("Pick the activation date.", "error")
        return redirect(_link(cid))
    old = str(row["activation_date"])[:10] if row["activation_date"] else None
    if old == day.isoformat():
        flash("The activation date is already that day.", "ok")
        return redirect(_link(cid))
    db.execute("UPDATE client_services SET activation_date=? WHERE id=? AND client_id=?",
               (day.isoformat(), sid, cid))
    _history(db, cid, g.user,
             f"activation date set on {row['sof_number']}" if not old else f"activation date changed on {row['sof_number']}",
             f"{old} -> {day.isoformat()}" if old else day.isoformat())
    log(db, "client_activation", f"{client_no(c)} {c['client_name']} {row['sof_number']} {day.isoformat()}")
    # The date moved before the record reached Finance: nobody was told
    # before — the account manager and the Sales admin are told now.
    text = f"The activation date of SOF {row['sof_number']} of '{c['client_name']}' {'changed to' if old else 'was set to'} {day.isoformat()}."
    notify(db, _client_watchers(db, c), text, _link(cid), skip=g.user["id"])
    db.commit()
    flash("Activation date saved. Finance has not received the record yet — forward it below when ready.", "ok")
    return redirect(_link(cid))


# ---------------------------------------------------------------- the dates of one SOF after Finance has it (build 110)
@bp.route("/<int:cid>/sof/<int:sid>/dates", methods=["POST"])
@login_required
def sof_dates(cid, sid):
    """The portal admin or an administrative permission user changes the
    dates of ONE SOF after Revenue Assurance forwarded the record to
    Finance. The row stays where it is — it locks for everyone else — and
    Revenue Assurance, Finance and Sales are told what changed."""
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["dates_admin"]:
        abort(403)
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if row is None:
        abort(404)
    if _open_sof_edit(db, sid) is not None:
        flash("This SOF has a change going through the approval flow — change its dates there.", "error")
        return redirect(_link(cid))
    new = {}
    errors = []
    for key, label in (("activation_date", "Activation date"),
                       ("termination_date", "Termination date"),
                       ("commercial_impact_date", "Commercial impact date")):
        raw = (request.form.get(key) or "").strip()
        if raw:
            try:
                datetime.strptime(raw, "%Y-%m-%d")
                new[key] = raw
            except ValueError:
                errors.append(f"{label} does not look like a date.")
        else:
            new[key] = None
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(_link(cid))
    old = _sof_snapshot(row)
    changed = _sof_change_text(old, {**old, **new})
    if changed == "No fields changed.":
        flash("Nothing changed.", "ok")
        return redirect(_link(cid))
    # A termination takes effect at once for the portal admin (build 102);
    # clearing it puts a terminated SOF back to activated.
    status = "terminated" if new["termination_date"] else ("activated" if new["activation_date"] else row["status"])
    db.execute("UPDATE client_services SET activation_date=?, termination_date=?, commercial_impact_date=?, "
               "status=? WHERE id=? AND client_id=?",
               (new["activation_date"], new["termination_date"], new["commercial_impact_date"],
                status, sid, cid))
    _history(db, cid, g.user, f"SOF {row['sof_number']} dates changed by {g.user['full_name']}", changed)
    log(db, "client_sof_dates", f"{client_no(c)} {c['client_name']} {row['sof_number']} {changed}")
    text = (f"{g.user['full_name']} changed the dates of SOF {row['sof_number']} of '{c['client_name']}': "
            f"{changed}. The SOF is now {status}.")
    notify(db, set(_members(db, "revenue_assurance")) | set(_members(db, "finance"))
           | {c["account_manager_id"]} | set(_sales_admin_ids(db)) | _client_watchers(db, c),
           text, _link(cid), skip=g.user["id"])
    db.commit()
    flash("Dates saved. Revenue Assurance, Finance and Sales were told.", "ok")
    return redirect(_link(cid))


# ---------------------------------------------------------------- one SOF: edit, approve, reject (build 102)
@bp.route("/<int:cid>/sof/<int:sid>/edit", methods=["GET", "POST"])
@login_required
def sof_edit(cid, sid):
    """The account manager edits ONE activated or terminated SOF on a finished client —
    its fields, its activation date, and its termination date, commercial impact date and
    termination reason. Build 110: as soon as the account manager saves,
    the SOF goes to pending and the Sales admin is told the SOF number
    and what changed. The SOF itself keeps its old values until the
    change has run the whole flow. The portal admin's change applies at
    once. Build 112: every edit carries a new SOF file — the account
    manager must upload one, even for a date-only change; the old file
    stays downloadable, it is not replaced. Build 113: the activation
    date is editable here too — it lands when the Sales admin approves,
    and Revenue Assurance may change it again before forwarding the
    change to Finance. Build 121: the contacts change here too — every
    contact except the account manager, which cannot change after
    approval. The contact change is staged with the SOF and lands when
    the Sales admin approves it (or at once for the portal admin)."""
    db, c, roles = _load(cid)
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if row is None:
        abort(404)
    am = c.get("account_manager_id") == g.user["id"]
    portal_admin = is_portal_admin(g.user)
    if c["status"] != "completed" or not (portal_admin or (am and row["status"] in ("activated", "terminated"))):
        abort(403)
    if request.method == "GET":
        _departments, _contact_depts, _users_info = _contacts_form_data(db)
        _cur = _contacts_from_db(db, cid)
        _contacts = {side: [r for r in _cur[side] if r["ctype"] != "account_manager"]
                     for side, _l in CONTACT_SIDES}
        return render_template("sof_edit.html", c=c, s=row, f=_file_info(row["sof_file"]), back=_link(cid),
                               portal_admin=portal_admin, contacts=_contacts,
                               contact_partial={side: [] for side, _l in CONTACT_SIDES},
                               departments=_departments, contact_depts=_contact_depts, users_info=_users_info,
                               contact_sides=CONTACT_SIDES, contact_kinds=CONTACT_KINDS,
                               contact_kind_label=CONTACT_KIND_LABEL,
                               dept_names={d["id"]: d["name"] for d in _departments})
    new = {"sof_number": _clean(request.form.get("sof_number"), 255),
           "service": _clean(request.form.get("service"), 255),
           # Build 109: no Service type box — the short name is the Service itself.
           "service_type": _clean(request.form.get("service"), 255),
           "service_description": (request.form.get("service_description") or "").strip()[:2000],
           "details": (request.form.get("details") or "").strip()[:2000],
           # Build 113: the activation date is set here when it changes —
           # it lands when the Sales admin approves, and Revenue Assurance
           # may change it again before forwarding the change to Finance.
           # A finished SOF always has one, so it cannot be cleared here.
           "activation_date": (request.form.get("activation_date") or "").strip(),
           "status": row.get("status") or "",
           "termination_date": (request.form.get("termination_date") or "").strip(),
           "commercial_impact_date": (request.form.get("commercial_impact_date") or "").strip(),
           "termination_reason": (request.form.get("termination_reason") or "").strip()[:2000]}
    errors = []
    for key, label in (("sof_number", "SOF number"), ("service", "Service"),
                       ("service_description", "Service description"),
                       ("activation_date", "Activation date")):
        if not new[key]:
            errors.append(f"{label} is required.")
    for key, label in (("activation_date", "Activation date"),
                       ("termination_date", "Termination date"),
                       ("commercial_impact_date", "Commercial impact date")):
        if new[key]:
            try:
                datetime.strptime(new[key], "%Y-%m-%d")
            except ValueError:
                errors.append(f"{label} does not look like a date.")
    if new["sof_number"] and new["sof_number"].lower() != (row["sof_number"] or "").lower():
        clash = db.execute("SELECT id FROM client_services WHERE LOWER(sof_number)=? AND id<>?",
                           (new["sof_number"].lower(), sid)).fetchone()
        if clash:
            errors.append(f"SOF number {new['sof_number']} is already used on another client.")
    # Build 121: the contacts change here too — every contact except the
    # account manager. The technical and billing contacts must still be
    # there in each table; Others stays optional. When no contact table
    # is posted at all (an edit that only touches the SOF), the contacts
    # stand as they are.
    _cur = _contacts_from_db(db, cid)
    _old_contacts = {side: [r for r in _cur[side] if r["ctype"] != "account_manager"]
                     for side, _l in CONTACT_SIDES}
    if "c_client_type" in request.form or "c_hrc_type" in request.form:
        _contacts, _edit, _cerr = _read_contact_tables(
            db, request.form, "Contacts", ("technical", "billing"), allow_am=False)
        errors.extend(_cerr)
    else:
        _contacts, _edit = _old_contacts, {side: [] for side, _l in CONTACT_SIDES}
    # Build 112: the SOF file is uploaded here, and it is required for
    # the account manager — every edit carries a new SOF file, even a
    # date-only one. The portal admin may leave it off.
    upload = request.files.get("sof_file")
    has_upload = bool(upload and upload.filename)
    file_json = None
    file_name = ""
    if has_upload:
        _dept = db.execute("SELECT * FROM departments WHERE id=?", (c["department_id"],)).fetchone()
        file_json, _err = routes_deptdb._save_ddb_file(upload, _dept)
        if _err:
            errors.append(_err)
        else:
            file_name = (_file_info(file_json) or {}).get("original", "")
    elif not portal_admin:
        errors.append("Upload the SOF file for this change.")
    if errors:
        if file_json:
            _remove_files([(_file_info(file_json) or {}).get("stored")])
        for e in errors:
            flash(e, "error")
        _departments, _contact_depts, _users_info = _contacts_form_data(db)
        return render_template("sof_edit.html", c=c, s={**dict(row), **new}, f=_file_info(row["sof_file"]),
                               back=_link(cid), portal_admin=portal_admin, contacts=_contacts,
                               contact_partial=_edit, departments=_departments,
                               contact_depts=_contact_depts, users_info=_users_info,
                               contact_sides=CONTACT_SIDES, contact_kinds=CONTACT_KINDS,
                               contact_kind_label=CONTACT_KIND_LABEL,
                               dept_names={d["id"]: d["name"] for d in _departments})
    old = _sof_snapshot(row)
    old["contacts"] = _old_contacts
    new["contacts"] = _contacts
    diff = _sof_change_text(old, new)
    _cdiff = _contacts_change_text(old["contacts"], new["contacts"])
    if _cdiff:
        diff = (diff + "; " + _cdiff) if diff != "No fields changed." else _cdiff
    new["sof_file"] = file_json
    new["file_name"] = file_name
    if has_upload and file_json != (row["sof_file"] or None):
        diff = (diff + "; SOF file: replaced" if diff != "No fields changed."
                else "SOF file: replaced")
    if diff == "No fields changed.":
        flash("Nothing changed.", "ok")
        return redirect(_link(cid))
    if portal_admin:
        # The portal admin is the authority: the change applies at once,
        # and a termination takes effect at once. Build 113: the
        # activation date the admin set lands here too.
        status = "terminated" if new["termination_date"] else ("activated" if new["activation_date"] else "pending")
        db.execute("UPDATE client_services SET sof_number=?, service=?, service_type=?, service_description=?, "
                   "details=?, sof_file=?, activation_date=?, termination_date=?, commercial_impact_date=?, "
                   "termination_reason=?, status=? WHERE id=? AND client_id=?",
                   (new["sof_number"], new["service"], new["service_type"],
                    new["service_description"] or None, new["details"] or None,
                    new.get("sof_file") or row["sof_file"],
                    new["activation_date"] or None,
                    new["termination_date"] or None, new["commercial_impact_date"] or None,
                    new["termination_reason"] or None, status, sid, cid))
        # Build 112: a file the portal admin replaces joins the SOF's
        # file history — the old one stays downloadable.
        if has_upload and file_json != (row["sof_file"] or None):
            _record_sof_file(db, sid, file_json, None, g.user["id"])
        # Build 121: the staged contacts apply at once too — the
        # account manager rows stay as they are.
        _apply_contacts(db, cid, new["contacts"])
        _history(db, cid, g.user, f"SOF {row['sof_number']} changed by the portal admin", diff)
        notify(db, {c["account_manager_id"]} | set(_sales_admin_ids(db)),
               f"The portal admin changed SOF {row['sof_number']} of '{c['client_name']}': {diff}",
               _link(cid), skip=g.user["id"])
        db.commit()
        flash("Saved. The change applies at once.", "ok")
        return redirect(_link(cid))
    db.execute("INSERT INTO client_sof_edits(client_id,service_id,editor_id,old_values,new_values)"
               " VALUES (?,?,?,?,?)",
               (cid, sid, g.user["id"], json.dumps(old), json.dumps(new)))
    # Build 110: the SOF goes to pending as soon as the account manager
    # saves the change — the Sales admin decides on a pending SOF, and the
    # old values stay on it until the change has run the whole flow.
    db.execute("UPDATE client_services SET status='pending' WHERE id=? AND client_id=?", (sid, cid))
    _history(db, cid, g.user, f"SOF {row['sof_number']} change sent for approval", diff)
    notify(db, set(_sales_admin_ids(db)),
           f"{g.user['full_name']} changed SOF {row['sof_number']} of '{c['client_name']}': {diff} "
           "Approve or reject it from the client page.", _link(cid), skip=g.user["id"])
    db.commit()
    flash("Saved. The SOF is now pending and the Sales admin will approve or reject this change.", "ok")
    return redirect(_link(cid))


@bp.route("/<int:cid>/sof-edit/<int:eid>/approve", methods=["POST"])
@login_required
def sof_edit_approve(cid, eid):
    """The Sales admin approves one SOF change (build 102, build 110).
    Only that SOF is affected — never the whole client. The change is
    applied to the SOF, which stays pending, and Revenue Assurance is
    told the approval and what changed; Revenue Assurance then forwards
    it to Transmission, Core and Technical support for a new SAN report.
    A termination takes effect only when Revenue Assurance forwards the
    finished change to Finance. Build 112: a SOF file the change carries
    joins the SOF's file history — the old file is kept, never deleted."""
    db, c, roles = _load(cid)
    if not _is_sales_admin(db, g.user):
        abort(403)
    edit = db.execute("SELECT * FROM client_sof_edits WHERE id=? AND client_id=? AND status='awaiting'",
                      (eid, cid)).fetchone()
    if edit is None:
        flash("This SOF change was already decided.", "error")
        return redirect(_link(cid))
    new = json.loads(edit["new_values"])
    old = json.loads(edit["old_values"]) if edit["old_values"] else {}
    change = _sof_new_text(new) if not edit["service_id"] else _sof_change_text(old, new)
    # Build 121: a change may carry contact rows too — they land with
    # the SOF fields, the account manager rows untouched.
    _cdiff = _contacts_change_text((old or {}).get("contacts"), (new or {}).get("contacts"))
    if _cdiff:
        change = (change + "; " + _cdiff) if change != "No fields changed." else _cdiff
    if edit["service_id"]:
        row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?",
                         (edit["service_id"], cid)).fetchone()
        if row is None:
            abort(404)
        num = row["sof_number"]
        # The SOF goes to pending when the change is approved — unless it
        # was not activated to begin with, in which case it keeps its state.
        was = old.get("status") or row["status"]
        new_status = "pending" if was in ("activated", "pending") else was
        # Build 113: the activation date the change carries lands here
        # too — approving a change used to leave the old date on the
        # SOF, so an edited activation date never reached the list.
        db.execute("UPDATE client_services SET sof_number=?, service=?, service_type=?, service_description=?, "
                   "details=?, sof_file=?, activation_date=?, termination_date=?, commercial_impact_date=?, "
                   "billing_type=?, termination_reason=?, status=? WHERE id=?",
                   (new["sof_number"], new["service"], new["service_type"],
                    new["service_description"] or None, new["details"] or None,
                    new.get("sof_file") or row["sof_file"],
                    new.get("activation_date") or None,
                    new["termination_date"] or None, new["commercial_impact_date"] or None,
                    new.get("billing_type") or row.get("billing_type") or None,
                    new["termination_reason"] or None, new_status, edit["service_id"]))
        # Build 112: the new file joins the SOF's file history, and the
        # old one stays on disk and downloadable.
        if new.get("sof_file") and new["sof_file"] != (row["sof_file"] or None):
            _record_sof_file(db, edit["service_id"], new["sof_file"], eid, edit["editor_id"])
    else:
        num = new["sof_number"]
        pos = db.execute("SELECT COALESCE(MAX(position), -1)+1 FROM client_services WHERE client_id=?",
                         (cid,)).fetchone()[0]
        # Build 110: a SOF the account manager added carries the activation
        # date he set and the SOF file he uploaded — Revenue Assurance does
        # not set the date fresh, it may only change it later in the flow.
        # Build 124: its Dates block travels with it too.
        nid = db.execute("INSERT INTO client_services(client_id,position,sof_number,service,service_type,"
                         "billing_type,service_description,details,sof_file,activation_date,"
                         "termination_date,commercial_impact_date,public_code,status) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'pending')",
                         (cid, pos, new["sof_number"], new["service"], new["service_type"],
                          new.get("billing_type") or None,
                          new["service_description"] or None, new["details"] or None,
                          new.get("sof_file"), new.get("activation_date") or None,
                          new.get("termination_date") or None, new.get("commercial_impact_date") or None,
                          new_random_code_text(db))).lastrowid
        db.execute("UPDATE client_sof_edits SET service_id=? WHERE id=?", (nid, eid))
        # Build 112: the new SOF's file is the first row of its history.
        if new.get("sof_file"):
            _record_sof_file(db, nid, new["sof_file"], eid, edit["editor_id"])
        # Build 123: the new SOF's Internet format lands with it.
        _write_format(db, nid, new.get("format"))
    if new.get("contacts") is not None:
        _apply_contacts(db, cid, new["contacts"])
    db.execute("UPDATE client_sof_edits SET status='approved', decided_by=?, "
               "decided_at=datetime('now','localtime') WHERE id=?", (g.user["id"], eid))
    _history(db, cid, g.user, f"SOF {num} change approved",
             f"The SOF stays pending — Revenue Assurance forwards it to Transmission, Core and Technical "
             f"support for a new SAN report. {change}")
    log(db, "client_sof_approve", f"{client_no(c)} {c['client_name']} {num}")
    notify(db, {edit["editor_id"]} | set(_members(db, "revenue_assurance")),
           f"The SOF {num} change on '{c['client_name']}' was approved by {g.user['full_name']}: {change} "
           "Revenue Assurance forwards it for a new SAN report.", _link(cid), skip=g.user["id"])
    db.commit()
    flash(f"SOF {num} approved. Revenue Assurance forwards it to Transmission, Core and Technical support for a new SAN report.", "ok")
    return redirect(_link(cid))


@bp.route("/<int:cid>/sof-edit/<int:eid>/reject", methods=["POST"])
@login_required
def sof_edit_reject(cid, eid):
    """The Sales admin rejects one SOF change (build 102). The SOF keeps
    its old values and goes back to activated — it went to pending when
    the account manager saved the change (build 110) — and the account
    manager is told why. A SOF file the account manager uploaded for a
    rejected change is removed again."""
    db, c, roles = _load(cid)
    if not _is_sales_admin(db, g.user):
        abort(403)
    edit = db.execute("SELECT * FROM client_sof_edits WHERE id=? AND client_id=? AND status='awaiting'",
                      (eid, cid)).fetchone()
    if edit is None:
        flash("This SOF change was already decided.", "error")
        return redirect(_link(cid))
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("Give a reason for rejecting this SOF change.", "error")
        return redirect(_link(cid))
    new = json.loads(edit["new_values"])
    old = json.loads(edit["old_values"]) if edit["old_values"] else {}
    num = old.get("sof_number") or new.get("sof_number") or ""
    db.execute("UPDATE client_sof_edits SET status='rejected', reason=?, decided_by=?, "
               "decided_at=datetime('now','localtime') WHERE id=?", (reason, g.user["id"], eid))
    orphan = None
    if edit["service_id"]:
        # Back to the state the SOF had before the account manager saved
        # the change — usually activated.
        db.execute("UPDATE client_services SET status=? WHERE id=? AND client_id=?",
                   (old.get("status") or "activated", edit["service_id"], cid))
        row = db.execute("SELECT sof_file FROM client_services WHERE id=?", (edit["service_id"],)).fetchone()
        if new.get("sof_file") and (not row or new["sof_file"] != row["sof_file"]):
            orphan = (_file_info(new["sof_file"]) or {}).get("stored")
    elif new.get("sof_file"):
        orphan = (_file_info(new["sof_file"]) or {}).get("stored")
    _history(db, cid, g.user, f"SOF {num} change rejected", reason)
    log(db, "client_sof_reject", f"{client_no(c)} {c['client_name']} {num}")
    notify(db, {edit["editor_id"]},
           f"Your change to SOF {num} of '{c['client_name']}' was rejected by {g.user['full_name']}: {reason}",
           _link(cid), skip=g.user["id"])
    db.commit()
    if orphan:
        _remove_files([orphan])
    flash(f"SOF {num} change rejected. The account manager was told why.", "ok")
    return redirect(_link(cid))


# ---------------------------------------------------------------- the edited SOF's way to Finance (build 110)
@bp.route("/<int:cid>/sof-edit/<int:eid>/forward", methods=["POST"])
@login_required
def sof_edit_forward(cid, eid):
    """Revenue Assurance forwards an approved SOF change to Transmission,
    Core and Technical support, so one of them uploads a new SAN report
    for this SOF. Revenue Assurance cannot reject the change — it can
    only forward it."""
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["ra_sof_forward"]:
        abort(403)
    edit = db.execute("SELECT * FROM client_sof_edits WHERE id=? AND client_id=? AND status='approved'",
                      (eid, cid)).fetchone()
    if edit is None:
        flash("This SOF change is not waiting for Revenue Assurance.", "error")
        return redirect(_link(cid))
    new = json.loads(edit["new_values"])
    old = json.loads(edit["old_values"]) if edit["old_values"] else {}
    num = old.get("sof_number") or new.get("sof_number") or ""
    change = _sof_new_text(new) if not edit["service_id"] else _sof_change_text(old, new)
    db.execute("UPDATE client_sof_edits SET status='san' WHERE id=?", (eid,))
    _history(db, cid, g.user, f"SOF {num} change forwarded for a new SAN report",
             "Revenue Assurance sent it to Transmission, Core and Technical support.")
    log(db, "client_sof_forward", f"{client_no(c)} {c['client_name']} {num}")
    text = (f"Revenue Assurance forwarded the SOF {num} change on '{c['client_name']}' to you. "
            f"Upload a new SAN report for this SOF. {change}")
    notify(db, set(_members(db, "transmission")) | set(_members(db, "core"))
           | set(_members(db, "technical")), text, _link(cid), skip=g.user["id"])
    db.commit()
    flash(f"SOF {num} forwarded. Transmission, Core and Technical support were asked for a new SAN report.", "ok")
    return redirect(_link(cid))


@bp.route("/<int:cid>/sof-edit/<int:eid>/dates", methods=["POST"])
@login_required
def sof_edit_dates(cid, eid):
    """Revenue Assurance changes the dates of the edited SOF once its new
    SAN report is up — the activation date the account manager set, and
    the termination date and the commercial impact date when the account
    manager's change carries one of them. Build 112: for a new service
    the change carries no termination or commercial impact date, so
    Revenue Assurance sees only the activation date there. The dates are
    saved on the SOF; forwarding it to Finance is the next step."""
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["ra_sof_forward"]:
        abort(403)
    edit = db.execute("SELECT * FROM client_sof_edits WHERE id=? AND client_id=? AND status='ra_dates'",
                      (eid, cid)).fetchone()
    if edit is None:
        flash("This SOF change is not waiting for its dates.", "error")
        return redirect(_link(cid))
    if not edit["service_id"]:
        abort(404)
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?",
                     (edit["service_id"], cid)).fetchone()
    if row is None:
        abort(404)
    # Build 112: the termination and commercial impact boxes are only
    # there when the account manager's change carries one of those dates
    # — a value posted for a change that carries neither is ignored.
    _nv = json.loads(edit["new_values"])
    _has_term = bool((_nv.get("termination_date") or "") or (_nv.get("commercial_impact_date") or ""))
    new = {}
    errors = []
    for key, label in (("activation_date", "Activation date"),
                       ("termination_date", "Termination date"),
                       ("commercial_impact_date", "Commercial impact date")):
        raw = (request.form.get(key) or "").strip()
        if raw:
            try:
                datetime.strptime(raw, "%Y-%m-%d")
                new[key] = raw
            except ValueError:
                errors.append(f"{label} does not look like a date.")
        else:
            new[key] = None
    if not _has_term:
        new["termination_date"] = str(row["termination_date"])[:10] if row["termination_date"] else None
        new["commercial_impact_date"] = str(row["commercial_impact_date"])[:10] if row["commercial_impact_date"] else None
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(_link(cid))
    old = _sof_snapshot(row)
    changed = _sof_change_text(old, {**old, **new})
    if changed == "No fields changed.":
        flash("Nothing changed.", "ok")
        return redirect(_link(cid))
    db.execute("UPDATE client_services SET activation_date=?, termination_date=?, commercial_impact_date=? "
               "WHERE id=? AND client_id=?",
               (new["activation_date"], new["termination_date"], new["commercial_impact_date"],
                edit["service_id"], cid))
    _history(db, cid, g.user, f"dates changed on the edited SOF {row['sof_number']} by Revenue Assurance", changed)
    log(db, "client_sof_dates", f"{client_no(c)} {c['client_name']} {row['sof_number']} {changed}")
    db.commit()
    flash("Dates saved. Forward the SOF to Finance when ready.", "ok")
    return redirect(_link(cid))


@bp.route("/<int:cid>/sof-edit/<int:eid>/forward-finance", methods=["POST"])
@login_required
def sof_edit_forward_finance(cid, eid):
    """Revenue Assurance forwards the finished SOF change to Finance.
    The change is applied for good: the SOF becomes activated, or
    terminated when a termination date was set. Finance, the account
    manager and the Sales admin are told."""
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["ra_sof_forward"]:
        abort(403)
    edit = db.execute("SELECT * FROM client_sof_edits WHERE id=? AND client_id=? AND status='ra_dates'",
                      (eid, cid)).fetchone()
    if edit is None:
        flash("This SOF change is not ready to go to Finance.", "error")
        return redirect(_link(cid))
    if not edit["service_id"]:
        abort(404)
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?",
                     (edit["service_id"], cid)).fetchone()
    if row is None:
        abort(404)
    if not row["activation_date"]:
        flash("Set the activation date on this SOF first.", "error")
        return redirect(_link(cid))
    num = row["sof_number"]
    final = "terminated" if row["termination_date"] else "activated"
    db.execute("UPDATE client_services SET status=? WHERE id=?", (final, edit["service_id"]))
    db.execute("UPDATE client_sof_edits SET status='done' WHERE id=?", (eid,))
    _history(db, cid, g.user, f"SOF {num} change sent to Finance",
             f"The SOF is now {final}.")
    log(db, "client_sof_forward_finance", f"{client_no(c)} {c['client_name']} {num} {final}")
    notify(db, set(_members(db, "finance")) | {edit["editor_id"]} | set(_sales_admin_ids(db)),
           f"The SOF {num} change on '{c['client_name']}' is now final — the SOF is {final}.",
           _link(cid), skip=g.user["id"])
    db.commit()
    flash(f"SOF {num} is now {final}. Finance, the account manager and the Sales admin were told.", "ok")
    return redirect(_link(cid))


# ---------------------------------------------------------------- Revenue Assurance: forward to Finance
@bp.route("/<int:cid>/forward-finance", methods=["POST"])
@login_required
def forward_finance(cid):
    """Revenue Assurance sends the finished record to Finance. Only now does
    the record become Completed and visible to Finance (build 92). Every
    SOF must have its activation date first (build 93)."""
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["forward_finance_admin"]:
        abort(403)
    missing = db.execute("SELECT sof_number FROM client_services WHERE client_id=? AND activation_date IS NULL "
                         "ORDER BY position, id", (cid,)).fetchall()
    if missing:
        flash("Set the activation date on every SOF first (" +
              ", ".join(r["sof_number"] for r in missing) + " still has none).", "error")
        return redirect(_link(cid))
    days = ", ".join(f"{r['sof_number']} {str(r['activation_date'])[:10]}" for r in
                     db.execute("SELECT sof_number, activation_date FROM client_services WHERE client_id=? "
                                "ORDER BY position, id", (cid,)).fetchall())
    done = db.execute("UPDATE client_onboardings SET status='completed', decided_by=?, "
                      "decided_at=datetime('now','localtime'), updated_at=datetime('now','localtime') "
                      "WHERE id=? AND status='san_uploaded'", (g.user["id"], cid)).rowcount
    if not done:
        db.rollback()
        flash("This client cannot be sent to Finance now.", "error")
        return redirect(_link(cid))
    # Build 102: the SOFs that have their activation date are live now.
    db.execute("UPDATE client_services SET status='activated' WHERE client_id=? AND status='pending' "
               "AND activation_date IS NOT NULL", (cid,))
    _history(db, cid, g.user, "forwarded to finance", days)
    log(db, "client_forward_finance", f"{client_no(c)} {c['client_name']} {days}")
    text = f"The final record of '{c['client_name']}' is ready: activation dates {days}."
    notify(db, set(_members(db, "finance")) | {c["owner_id"]} | _client_watchers(db, c), text, _link(cid), skip=g.user["id"])
    db.commit()
    flash("Sent to Finance. Finance can now see the final record.", "ok")
    return redirect(_link(cid))


# ---------------------------------------------------------------- downloads
def _send_stored(info):
    path = routes_deptdb._ddb_file_path(info["stored"])
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=info.get("original") or info["stored"])


@bp.route("/<int:cid>/sof/<int:sid>")
@login_required
def sof_download(cid, sid):
    db, c, roles = _load(cid)
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if row is None:
        abort(404)
    # Build 112: ?up=<upload id> downloads one earlier file from the
    # history; without it, the SOF's current file.
    up = request.args.get("up", type=int)
    info = None
    if up:
        _u = db.execute("SELECT * FROM client_sof_file_uploads WHERE id=? AND sof_id=?", (up, sid)).fetchone()
        info = _file_info(_u["sof_file"]) if _u else None
    if info is None:
        info = _file_info(row["sof_file"])
    if info is None:
        abort(404)
    return _send_stored(info)


@bp.route("/<int:cid>/sof/<int:sid>/san/download")
@login_required
def sof_san_download(cid, sid):
    db, c, roles = _load(cid)
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if row is None:
        abort(404)
    # Build 110: ?up=<upload id> downloads one earlier report from the
    # history; without it, the SOF's current report.
    up = request.args.get("up", type=int)
    info = None
    if up:
        _u = db.execute("SELECT * FROM client_sof_san_uploads WHERE id=? AND sof_id=?", (up, sid)).fetchone()
        info = _file_info(_u["san_file"]) if _u else None
    if info is None:
        info = _file_info(row["san_file"])
    if info is None:
        abort(404)
    return _send_stored(info)


# ---------------------------------------------------------------- one SOF: its own page (build 105)
@bp.route("/<int:cid>/sof/<int:sid>/view")
@login_required
def sof_view(cid, sid):
    """One SOF on its own page: every field, the uploaded SOF file, every
    SAN report uploaded for it, and its change history. Anyone who may open
    the client may open it."""
    db, c, roles = _load(cid)
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if row is None:
        abort(404)
    _fields = {p: _form_fields(db, p) for p in (1, 2)}
    history = [h for h in db.execute(
        "SELECT * FROM client_history WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
        if row["sof_number"] in (h["action"] or "") or row["sof_number"] in (h["detail"] or "")]
    # Build 111: every SAN report for this SOF, oldest first — the same
    # list as the client page shows, not just the latest one.
    san_uploads = [
        {"id": u["id"], "file": _file_info(u["san_file"]),
         "by": (db.execute("SELECT full_name FROM users WHERE id=?", (u["uploaded_by"],)).fetchone() or {}).get("full_name") if u["uploaded_by"] else None,
         "at": u["uploaded_at"], "edit_id": u["edit_id"]}
        for u in db.execute("SELECT * FROM client_sof_san_uploads WHERE sof_id=? ORDER BY id", (sid,)).fetchall()]
    return render_template(
        "sof_view.html", c=c, s=row, f=_file_info(row["sof_file"]),
        sof_files=_sof_file_uploads(db, sid),
        san_uploads=san_uploads,
        history=history, sof_status_label=SOF_STATUS_LABEL,
        san_perm={"upload": _can_upload_sof_san(db, g.user, roles, c, row),
                  "remove": _can_remove_sof_san(g.user, c, row)},
        fields=_fields,
        fmap={fld["field_key"]: fld for p in (1, 2) for fld in _fields[p] if fld["field_key"]},
        custom=_load_custom(db, cid),
        back=_link(cid))


# ---------------------------------------------------------------- SOF PDF: one document per SOF (build 93)
def _build_sof_pdf(db, c, s):
    """The SOF's PDF (approved in sof-format-v2.jpg), built fresh on every download."""
    contacts = [dict(r) for r in db.execute(
        "SELECT * FROM client_contacts WHERE client_id=? ORDER BY position, id", (c["id"],)).fetchall()]
    custom = _load_custom(db, c["id"])
    custom_vals = [(f["name"], custom.get(("service", s["id"], f["id"]), ""))
                   for f in _form_fields(db, 2) if not f["is_default"]]
    custom_vals = [(n, v) for n, v in custom_vals if v]
    client = {"client_name": c["client_name"], "client_no": client_no(c),
              "business_type": c["business_type"] or "", "phone": c["phone"] or "",
              "email": c["email"] or "", "address": c["address"] or "", "notes": c["notes"] or "",
              "account_manager": c["am_full_name"] or c["am_name"] or ""}
    service = {"sof_number": s["sof_number"], "service": s["service"], "details": s["details"] or "",
               "activation_date": str(s["activation_date"])[:10] if s["activation_date"] else "",
               "created_at": str(c["created_at"])[:10] if c["created_at"] else ""}
    code = s["public_code"] or ""
    qr = external_url(db, "clients.sof_code_page", code=code) if code else ""
    return exports.sof_pdf(client, service, contacts, custom_vals, code,
                           setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME),
                           config.DEFAULT_COMPANY_ADDRESS, qr)


def _sof_with_code(db, cid, sid):
    """The SOF row, giving it a share code first when it has none yet
    (an older SOF made before the PDF existed)."""
    row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if row is None:
        return None
    if not row["public_code"]:
        db.execute("UPDATE client_services SET public_code=? WHERE id=?",
                   (new_random_code_text(db), sid))
        db.commit()
        row = db.execute("SELECT * FROM client_services WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    return row


@bp.route("/<int:cid>/sof/<int:sid>/pdf")
@login_required
def sof_pdf(cid, sid):
    """Download this SOF's PDF: one document per SOF, in the approved format."""
    db, c, roles = _load(cid)
    s = _sof_with_code(db, cid, sid)
    if s is None:
        abort(404)
    from flask import Response
    resp = Response(_build_sof_pdf(db, c, s), mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{s["sof_number"] or "sof"}.pdf"'
    return resp


@bp.route("/sof/code/<code>")
def sof_code_page(code):
    """Public code view: anyone who scans the SOF's QR (or types HRC-#####)
    sees the SOF and downloads its PDF. No login needed."""
    db = get_db()
    code = (code or "").strip().upper()
    row = db.execute("SELECT s.*, c.client_name, c.id AS client_id FROM client_services s "
                     "JOIN client_onboardings c ON c.id=s.client_id AND c.deleted_at IS NULL WHERE s.public_code=?", (code,)).fetchone()
    if row is None:
        return render_template("sof_code.html", code=code, status="missing", sof=None, client=None), 404
    if not row["public_enabled"]:
        return render_template("sof_code.html", code=code, status="off", sof=row,
                               client={"client_name": row["client_name"]}), 410
    db.execute("UPDATE client_services SET public_views=public_views+1 WHERE id=?", (row["id"],)); db.commit()
    return render_template("sof_code.html", code=code, status="ok", sof=row,
                           client={"client_name": row["client_name"]})


@bp.route("/sof/code/<code>/pdf")
def sof_code_pdf(code):
    """The SOF's PDF for the public code page (no login)."""
    db = get_db()
    code = (code or "").strip().upper()
    s = db.execute("SELECT * FROM client_services WHERE public_code=?", (code,)).fetchone()
    if s is None or not s["public_enabled"]:
        abort(404)
    c = db.execute("SELECT c.*, am.full_name AS am_name FROM client_onboardings c "
                   "LEFT JOIN users am ON am.id=c.account_manager_id WHERE c.id=? AND c.deleted_at IS NULL", (s["client_id"],)).fetchone()
    if c is None:
        abort(404)
    db.execute("UPDATE client_services SET public_views=public_views+1 WHERE id=?", (s["id"],)); db.commit()
    from flask import Response
    resp = Response(_build_sof_pdf(db, c, s), mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{s["sof_number"] or "sof"}.pdf"'
    return resp


# ---------------------------------------------------------------- form setup: the Sales admin sets the Add Client fields
@bp.route("/form-setup", methods=["GET", "POST"])
@login_required
def form_setup():
    """The Sales & Marketing admin sets the three Add Client pages' fields:
    each field's column name, input type, required or not. The fields the
    client was built with are the defaults; the admin adds his own on top.
    Every field except the structural ones can be deleted from the right
    of its row (build 95): deleting a field also deletes everything
    entered in it. Structural defaults (client name, contact name, SOF
    number, service, activation date) stay required, keep their type,
    and cannot be removed."""
    db = get_db()
    if not _is_sales_admin(db, g.user):
        abort(403)
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        page = request.form.get("page", type=int) or 1
        if page not in (1, 2):
            page = 1
        fields = _form_fields(db, page)
        if action == "add":
            name = _clean(request.form.get("new_name"), 255)
            ftype = (request.form.get("new_type") or "text").strip()
            if ftype not in [t for t, _l in FIELD_TYPES]:
                ftype = "text"
            options = (request.form.get("new_options") or "").strip()[:2000]
            req = 1 if request.form.get("new_required") else 0
            if not name:
                flash("Type the column name for the new field.", "error")
            elif any(fld["name"].lower() == name.lower() for fld in fields):
                flash("A field with that name is already on this page.", "error")
            else:
                pos = (db.execute("SELECT MAX(position) FROM client_form_fields WHERE page=?",
                                  (page,)).fetchone()[0] or 0) + 1
                db.execute("INSERT INTO client_form_fields(page,field_key,name,field_type,required,options,position,is_default)"
                           " VALUES (?,?,?, ?,?,?,?,0)",
                           (page, None, name, ftype, req, options or None, pos))
                db.commit()
                log(db, "client_form_field_add", f"page {page} {name} ({ftype})")
                flash("Field added.", "ok")
        elif action.startswith("move_"):
            try:
                fid = int(action.rsplit("_", 1)[1])
            except (ValueError, IndexError):
                fid = None
            if fid is not None:
                ids = [fld["id"] for fld in fields]
                if fid in ids:
                    i = ids.index(fid)
                    j = i - 1 if action.startswith("move_up_") else i + 1
                    if 0 <= j < len(ids):
                        ids[i], ids[j] = ids[j], ids[i]
                        for pos, _fid in enumerate(ids):
                            db.execute("UPDATE client_form_fields SET position=? WHERE id=?", (pos * 10, _fid))
                        db.commit()
                        flash("Moved.", "ok")
        elif action.startswith("remove_"):
            try:
                fid = int(action.split("_", 1)[1])
            except (ValueError, IndexError):
                fid = None
            row = next((fld for fld in fields if fld["id"] == fid), None) if fid else None
            if row and row["field_key"] not in STRUCTURAL_REQUIRED:
                db.execute("DELETE FROM client_field_values WHERE field_id=?", (fid,))
                _col = DEFAULT_FIELD_COLUMNS.get(row["field_key"])
                if _col:
                    db.execute("UPDATE %s SET %s=NULL" % (_col[0], _col[1]))
                db.execute("DELETE FROM client_form_fields WHERE id=?", (fid,))
                db.commit()
                log(db, "client_form_field_remove", f"page {page} {row['name']}")
                flash("Field removed.", "ok")
            elif row:
                flash("A structural field cannot be removed.", "error")
        elif action == "save":
            names = [fld["name"].lower() for fld in fields]
            for fld in fields:
                fid = fld["id"]
                name = _clean(request.form.get(f"name_{fid}"), 255) or fld["name"]
                if name.lower() != fld["name"].lower() and name.lower() in names:
                    flash(f"'{name}' is already a field on this page; that name was kept.", "error")
                    name = fld["name"]
                req = 1 if request.form.get(f"req_{fid}") else 0
                if fld["is_default"]:
                    if fld["field_key"] in STRUCTURAL_REQUIRED:
                        req = 1
                    db.execute("UPDATE client_form_fields SET name=?, required=? WHERE id=?", (name, req, fid))
                else:
                    ftype = (request.form.get(f"type_{fid}") or fld["field_type"]).strip()
                    if ftype not in [t for t, _l in FIELD_TYPES]:
                        ftype = fld["field_type"]
                    options = (request.form.get(f"opts_{fid}") or "").strip()[:2000]
                    db.execute("UPDATE client_form_fields SET name=?, field_type=?, required=?, options=? WHERE id=?",
                               (name, ftype, req, options or None, fid))
            db.commit()
            log(db, "client_form_fields_save", f"page {page}")
            flash("Saved.", "ok")
        return redirect(url_for("clients.form_setup"))
    return render_template("client_form_setup.html",
                           fields={p: _form_fields(db, p) for p in (1, 2)},
                           types=FIELD_TYPES, type_labels=dict(FIELD_TYPES), structural=STRUCTURAL_REQUIRED)


# ---------------------------------------------------------------- setup: which department plays which part
@bp.route("/setup", methods=["GET", "POST"])
@login_required
def setup():
    if not is_portal_admin(g.user):
        abort(403)
    db = get_db()
    depts = db.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
    ids = {d["id"] for d in depts}
    if request.method == "POST":
        for role in ROLE_KEYS:
            val = request.form.get("role_" + role, type=int)
            setting_set(db, "clientflow_" + role, str(val) if val in ids else "")
        log(db, "client_setup", "client onboarding departments saved")
        db.commit()
        g._client_flow = None
        flash("Saved.", "ok")
        return redirect(url_for("clients.setup"))
    return render_template("client_setup.html", depts=depts, flow=flow_depts(db), roles=FLOW_ROLES,
                           saved=any(setting_get(db, "clientflow_" + r) is not None for r in ROLE_KEYS))

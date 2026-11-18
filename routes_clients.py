"""
routes_clients.py - CLIENT ONBOARDING, a default tab of the Department Database (build 85).

The flow (from the customer workflow diagram):

  Sales user fills 3 pages ......... 1 client info, 2 contacts + account manager,
                                     3 services (one SOF per service, several allowed)
  Click Save ....................... the request goes to the Sales admin for approval
  Sales admin ...................... approves or rejects
      rejected ..................... goes back to the Sales user, who fixes it and saves again
      approved ..................... the client is saved and appears in the client dropdown
  Revenue Assurance ................ sees it first (view only)
  Transmission, Core, Technical .... see the full record
  SAN report ....................... ONE upload only, by any of Transmission / Core / Technical
  Revenue Assurance + Sales ........ receive the SAN report
  Revenue Assurance ................ the only department that edits the activation date
  Finance .......................... receives the final record

Which department plays which part is set once on the setup page (portal admin);
until it is saved, departments are matched by name (Sales, Revenue Assurance,
Transmission, Core, Technical support, Finance).

Status of a client: pending -> approved -> san_uploaded -> completed
                    pending -> rejected -> (Sales saves again) -> pending

Used by: app.py (registers it, tab link), routes_deptdb.py (list page = tab "clients").
Uses: core.py, models.py, routes_deptdb.py (file saving), utils.py
Templates: deptdb_clients, client_form, client_detail, client_setup.
"""
import json
import os
from datetime import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for

import config
import routes_deptdb
from auth import login_required
from core import ddb_is_tab_admin, ddb_shared_tabs, ddb_tabs, dept_member_ids, notify
from models import get_db, log, setting_get, setting_set
from utils import is_portal_admin, like_pattern, page_info

bp = Blueprint("clients", __name__, url_prefix="/clients")

# (key, label, what the department does in the flow)
FLOW_ROLES = [
    ("sales", "Sales", "Creates the client. Its department admin approves or rejects."),
    ("revenue_assurance", "Revenue Assurance", "Sees the approved client first (view only), gets the SAN report, sets the activation date."),
    ("transmission", "Transmission", "Views the full record and may upload the SAN report."),
    ("core", "Core", "Views the full record and may upload the SAN report."),
    ("technical", "Technical support", "Views the full record and may upload the SAN report."),
    ("finance", "Finance", "Receives the final record once the activation date is set."),
]
ROLE_KEYS = [k for k, _l, _d in FLOW_ROLES]
ROLE_LABEL = {k: label for k, label, _d in FLOW_ROLES}
SAN_ROLES = ("transmission", "core", "technical")           # may upload the one SAN report
REVIEW_ROLES = ("revenue_assurance",) + SAN_ROLES            # see a client once it is approved

STATUS_LABEL = {
    "pending": "Waiting for approval",
    "rejected": "Rejected",
    "approved": "Approved · waiting for SAN report",
    "san_uploaded": "SAN report uploaded · waiting for activation date",
    "completed": "Completed",
}
ALL_STATUSES = tuple(STATUS_LABEL)
APPROVED_STATES = ("approved", "san_uploaded", "completed")
MAX_ROWS = 30   # contacts and services per client


@bp.app_template_filter("client_no")
def client_no(cid):
    """CL-0007 for client #7."""
    return f"CL-{int(cid):04d}"


@bp.app_template_filter("client_status")
def client_status(value):
    return STATUS_LABEL.get(value, value)


# ---------------------------------------------------------------- which department plays which part
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


def _members(db, role):
    did = flow_depts(db).get(role)
    return dept_member_ids(db, did) if did else []


# ---------------------------------------------------------------- who may see / do what
def _can_view(user, roles, c):
    if is_portal_admin(user) or "sales" in roles or c["owner_id"] == user["id"]:
        return True
    if c["status"] in APPROVED_STATES and roles.intersection(REVIEW_ROLES):
        return True
    if c["status"] == "completed" and "finance" in roles:
        return True
    return False


def _visible_sql(user, roles, alias="c"):
    """(sql, params) limiting a query to the clients this viewer may see."""
    if is_portal_admin(user) or "sales" in roles:
        return "1=1", []
    parts, params = [f"{alias}.owner_id=?"], [user["id"]]
    if roles.intersection(REVIEW_ROLES):
        parts.append(f"{alias}.status IN ('approved','san_uploaded','completed')")
    if "finance" in roles:
        parts.append(f"{alias}.status='completed'")
    return "(" + " OR ".join(parts) + ")", params


def _perms(db, user, roles, c):
    """What this user may do with this client right now."""
    status = c["status"]
    sales_admin = _is_sales_admin(db, user)
    owner = c["owner_id"] == user["id"]
    return {
        "approve": status == "pending" and sales_admin,
        "edit": status == "rejected" and (owner or sales_admin),
        "upload_san": status == "approved" and not c["san_file"]
                      and (bool(roles.intersection(SAN_ROLES)) or is_portal_admin(user)),
        "remove_san": bool(c["san_file"]) and status == "san_uploaded" and is_portal_admin(user),
        "activation": status in ("san_uploaded", "completed") and "revenue_assurance" in roles,
    }


def _history(db, cid, user, action, detail=None):
    db.execute("INSERT INTO client_history(client_id,user_id,full_name,action,detail) VALUES (?,?,?,?,?)",
               (cid, user["id"] if user else None, user["full_name"] if user else None, action, detail))


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


def _dept_row(db, dept_id):
    return db.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone() if dept_id else None


# ---------------------------------------------------------------- list: the tab inside the Department Database
def client_tab_view(db, dept, is_admin, args):
    """The Client onboarding tab (tab=clients on the Department Database page)."""
    roles = user_roles(db, g.user)
    vis, vparams = _visible_sql(g.user, roles)
    sales_admin = _is_sales_admin(db, g.user)
    can_create = bool(_sales_dept_id(db)) and ("sales" in roles or is_portal_admin(g.user))

    view = args.get("view") or "all"
    if view not in ("all", "mine", "todo"):
        view = "all"
    status = args.get("status") or ""
    q = " ".join((args.get("q") or "").split())

    # "To do": what is waiting for this viewer
    todo_parts, todo_params = [], []
    if sales_admin:
        todo_parts.append("c.status='pending'")
    todo_parts.append("(c.status='rejected' AND c.owner_id=?)")
    todo_params.append(g.user["id"])
    if roles.intersection(SAN_ROLES) or is_portal_admin(g.user):
        todo_parts.append("(c.status='approved' AND c.san_file IS NULL)")
    if "revenue_assurance" in roles:
        todo_parts.append("c.status='san_uploaded'")
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
    if q:
        like = like_pattern(q)
        digits = q.upper().replace("CL-", "").strip()
        clause = ("(c.client_name LIKE ? ESCAPE '\\' OR u.full_name LIKE ? ESCAPE '\\' "
                  "OR am.full_name LIKE ? ESCAPE '\\'")
        params += [like] * 3
        if digits.isdigit():
            clause += " OR c.id=?"
            params.append(int(digits))
        where.append(clause + ")")
    sql_where = " WHERE " + " AND ".join(where)
    base = ("FROM client_onboardings c LEFT JOIN users u ON u.id=c.owner_id "
            "LEFT JOIN users am ON am.id=c.account_manager_id")
    total = db.execute("SELECT COUNT(*) " + base + sql_where, params).fetchone()[0]
    page, pages, offset = page_info(total, args.get("page", 1, type=int), config.PER_PAGE)
    rows = db.execute(
        "SELECT c.*, u.full_name AS owner_name, am.full_name AS am_name, "
        "(SELECT COUNT(*) FROM client_services s WHERE s.client_id=c.id) AS sof_count "
        + base + sql_where + " ORDER BY c.id DESC LIMIT ? OFFSET ?", params + [config.PER_PAGE, offset]).fetchall()

    # The dropdown of approved clients (everyone who can see them)
    approved = db.execute(
        "SELECT c.id, c.client_name FROM client_onboardings c WHERE " + vis +
        " AND c.status IN ('approved','san_uploaded','completed') ORDER BY c.client_name, c.id",
        vparams).fetchall()

    keep = {k: v for k, v in args.items() if k not in ("page",)}
    keep["tab"] = "clients"
    if is_portal_admin(g.user):
        keep["dept"] = dept["id"]
    return render_template(
        "deptdb_clients.html", dept=dept, is_admin=is_admin,
        tabs=routes_deptdb._tabs_row(ddb_tabs(db, dept["id"]), ddb_shared_tabs(db, g.user)),
        rows=rows, counts=counts, view=view, status=status, q=q, total=total, page=page, pages=pages,
        keep=keep, approved=approved, can_create=can_create, roles=roles,
        flow=flow_depts(db), role_label=ROLE_LABEL,
        can_setup=is_portal_admin(g.user), statuses=ALL_STATUSES, status_label=STATUS_LABEL)


# ---------------------------------------------------------------- one client
def _load(cid):
    """(db, client row, roles) for a client this user may see, else 404."""
    db = get_db()
    c = db.execute(
        "SELECT c.*, u.full_name AS owner_name, am.full_name AS am_name, am.designation AS am_designation, "
        "decider.full_name AS decided_name, sb.full_name AS san_name, ab.full_name AS activation_name, "
        "d.name AS dept_name FROM client_onboardings c "
        "LEFT JOIN users u ON u.id=c.owner_id LEFT JOIN users am ON am.id=c.account_manager_id "
        "LEFT JOIN users decider ON decider.id=c.decided_by LEFT JOIN users sb ON sb.id=c.san_by "
        "LEFT JOIN users ab ON ab.id=c.activation_by LEFT JOIN departments d ON d.id=c.department_id "
        "WHERE c.id=?", (cid,)).fetchone()
    if c is None:
        abort(404)
    roles = user_roles(db, g.user)
    if not _can_view(g.user, roles, c):
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
        (f"{names['transmission']}, {names['core']}, {names['technical']}", "View the full record",
         "done" if approved else "todo"),
        ("SAN report uploaded", "One upload only, by any of those three departments",
         "done" if st in ("san_uploaded", "completed") else "now" if st == "approved" else "todo"),
        (f"{names['revenue_assurance']} and {names['sales']} receive the SAN report", "",
         "done" if st in ("san_uploaded", "completed") else "todo"),
        ("Activation date set", f"Only {names['revenue_assurance']} edits it",
         "done" if st == "completed" else "now" if st == "san_uploaded" else "todo"),
        (f"{names['finance']} receives the final record", "", "done" if st == "completed" else "todo"),
    ]
    return steps


@bp.route("/<int:cid>")
@login_required
def detail(cid):
    db, c, roles = _load(cid)
    contacts = db.execute("SELECT * FROM client_contacts WHERE client_id=? ORDER BY position, id", (cid,)).fetchall()
    services = db.execute("SELECT * FROM client_services WHERE client_id=? ORDER BY position, id", (cid,)).fetchall()
    history = db.execute("SELECT * FROM client_history WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
    san = _file_info(c["san_file"])
    return render_template(
        "client_detail.html", c=c, contacts=contacts, services=services, history=history,
        sof=[(s, _file_info(s["sof_file"])) for s in services], san=san,
        perm=_perms(db, g.user, roles, c), timeline=_timeline(db, c),
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
        rows = db.execute("SELECT id, full_name, designation FROM users WHERE department_id=? AND is_active=1 "
                          "AND is_deleted=0 ORDER BY full_name", (sales,)).fetchall()
        if rows:
            return rows
    return db.execute("SELECT id, full_name, designation FROM users WHERE is_active=1 AND is_deleted=0 "
                      "ORDER BY full_name").fetchall()


def _blank_form():
    return {"client_name": "", "business_type": "", "address": "", "phone": "", "email": "", "notes": "",
            "account_manager_id": None,
            "contacts": [{"name": "", "designation": "", "phone": "", "email": ""}],
            "services": [{"id": "", "sof_number": "", "service": "", "details": "", "file_name": ""}]}


def _form_from_db(db, c):
    form = {k: c[k] or "" for k in ("client_name", "business_type", "address", "phone", "email", "notes")}
    form["account_manager_id"] = c["account_manager_id"]
    form["contacts"] = [dict(name=r["name"] or "", designation=r["designation"] or "", phone=r["phone"] or "",
                             email=r["email"] or "")
                        for r in db.execute("SELECT * FROM client_contacts WHERE client_id=? ORDER BY position, id",
                                            (c["id"],)).fetchall()] or _blank_form()["contacts"]
    form["services"] = [dict(id=r["id"], sof_number=r["sof_number"] or "", service=r["service"] or "",
                             details=r["details"] or "",
                             file_name=(_file_info(r["sof_file"]) or {}).get("original", ""))
                        for r in db.execute("SELECT * FROM client_services WHERE client_id=? ORDER BY position, id",
                                            (c["id"],)).fetchall()] or _blank_form()["services"]
    return form


def _pick(lst, i):
    return lst[i] if i < len(lst) else ""


def _read_form(db, existing):
    """Read and check the posted form.
    Returns (form for redisplay, errors, contacts, services, new files saved, old files to delete after commit).
    `existing` is {service id: row} of the client being edited (empty for a new client)."""
    f = request.form
    form = {k: _clean(f.get(k), 255) for k in ("client_name", "business_type", "phone", "email")}
    form["address"] = (f.get("address") or "").strip()[:2000]
    form["notes"] = (f.get("notes") or "").strip()[:4000]
    form["account_manager_id"] = f.get("account_manager_id", type=int)
    errors = []

    # ---- page 1
    if not form["client_name"]:
        errors.append("Page 1: type the client name.")
    if form["email"] and "@" not in form["email"]:
        errors.append("Page 1: the client email does not look right.")

    # ---- page 2
    contacts = []
    names = f.getlist("contact_name")
    for i in range(min(len(names), MAX_ROWS)):
        row = {"name": _clean(names[i]),
               "designation": _clean(_pick(f.getlist("contact_designation"), i)),
               "phone": _clean(_pick(f.getlist("contact_phone"), i)),
               "email": _clean(_pick(f.getlist("contact_email"), i))}
        if not any(row.values()):
            continue
        if not row["name"]:
            errors.append(f"Page 2: contact {len(contacts) + 1} needs a name.")
        if row["email"] and "@" not in row["email"]:
            errors.append(f"Page 2: the email of contact {len(contacts) + 1} does not look right.")
        contacts.append(row)
    if not contacts:
        errors.append("Page 2: add at least one contact person.")
    form["contacts"] = contacts or _blank_form()["contacts"]
    if form["account_manager_id"] is None or db.execute(
            "SELECT 1 FROM users WHERE id=? AND is_active=1 AND is_deleted=0",
            (form["account_manager_id"],)).fetchone() is None:
        errors.append("Page 2: pick the account manager.")

    # ---- page 3
    sales_dept = _dept_row(db, _sales_dept_id(db))
    removed = set(f.getlist("sof_remove"))
    numbers, files = f.getlist("sof_number"), request.files.getlist("sof_file")
    saved_new, delete_old, services = [], [], []
    used_old = set()
    for i in range(min(len(numbers), MAX_ROWS)):
        sid_raw = _pick(f.getlist("sof_existing"), i)
        sid = int(sid_raw) if str(sid_raw).isdigit() and int(sid_raw) in existing else None
        row = {"id": sid or "", "sof_number": _clean(numbers[i]),
               "service": _clean(_pick(f.getlist("sof_service"), i)),
               "details": (_pick(f.getlist("sof_details"), i) or "").strip()[:2000], "file_name": ""}
        upload = files[i] if i < len(files) else None
        has_upload = bool(upload and upload.filename)
        old_file = existing[sid]["sof_file"] if sid else None
        if not (row["sof_number"] or row["service"] or row["details"] or has_upload or sid):
            continue
        if sid:
            used_old.add(sid)
        if not row["sof_number"] or not row["service"]:
            errors.append(f"Page 3: service {len(services) + 1} needs the SOF number and the service.")
        file_json = None
        if has_upload:
            file_json, err = routes_deptdb._save_ddb_file(upload, sales_dept or db.execute(
                "SELECT * FROM departments ORDER BY id LIMIT 1").fetchone())
            if err:
                errors.append("Page 3: " + err)
            else:
                saved_new.append(_file_info(file_json)["stored"])
                if old_file:
                    delete_old.append((_file_info(old_file) or {}).get("stored"))
        elif sid and str(sid) not in removed:
            file_json = old_file
        elif sid and old_file:
            delete_old.append((_file_info(old_file) or {}).get("stored"))
        row["file_json"] = file_json
        row["file_name"] = (_file_info(file_json) or {}).get("original", "")
        services.append(row)
    for sid, old in existing.items():                    # a service row the user deleted from the form
        if sid not in used_old and old["sof_file"]:
            delete_old.append((_file_info(old["sof_file"]) or {}).get("stored"))
    if not services:
        errors.append("Page 3: add at least one service with its SOF number.")
    form["services"] = services or _blank_form()["services"]
    return form, errors, contacts, services, saved_new, delete_old


def _write_children(db, cid, contacts, services):
    db.execute("DELETE FROM client_contacts WHERE client_id=?", (cid,))
    db.execute("DELETE FROM client_services WHERE client_id=?", (cid,))
    for i, r in enumerate(contacts):
        db.execute("INSERT INTO client_contacts(client_id,position,name,designation,phone,email) VALUES (?,?,?,?,?,?)",
                   (cid, i, r["name"], r["designation"] or None, r["phone"] or None, r["email"] or None))
    for i, r in enumerate(services):
        db.execute("INSERT INTO client_services(client_id,position,sof_number,service,details,sof_file) "
                   "VALUES (?,?,?,?,?,?)",
                   (cid, i, r["sof_number"], r["service"], r["details"] or None, r.get("file_json")))


def _show_form(db, form, cid=None, c=None, errors=None):
    return render_template("client_form.html", form=form, cid=cid, c=c, errors=errors or [],
                           managers=_account_managers(db), max_rows=MAX_ROWS,
                           back=url_for("ddb.index", tab="clients"))


def _send_for_approval_notice(db, cid, name, resubmitted):
    verb = "sent the corrected client" if resubmitted else "sent a new client"
    notify(db, _sales_admin_ids(db), f"{g.user['full_name']} {verb} '{name}' for approval.",
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
        form["account_manager_id"] = g.user["id"] if any(m["id"] == g.user["id"] for m in _account_managers(db)) else None
        return _show_form(db, form)
    form, errors, contacts, services, saved_new, delete_old = _read_form(db, {})
    if errors:
        _remove_files(saved_new)
        return _show_form(db, form, errors=errors)
    try:
        cid = db.execute(
            "INSERT INTO client_onboardings(department_id,owner_id,client_name,business_type,address,phone,email,"
            "notes,account_manager_id,status) VALUES (?,?,?,?,?,?,?,?,?, 'pending')",
            (sales, g.user["id"], form["client_name"], form["business_type"] or None, form["address"] or None,
             form["phone"] or None, form["email"] or None, form["notes"] or None, form["account_manager_id"])).lastrowid
        _write_children(db, cid, contacts, services)
        _history(db, cid, g.user, "sent for approval", f"{len(contacts)} contact(s), {len(services)} service(s)")
        log(db, "client_new", f"{client_no(cid)} {form['client_name']}")
        _send_for_approval_notice(db, cid, form["client_name"], False)
        db.commit()
    except Exception:
        db.rollback()
        _remove_files(saved_new)
        raise
    flash("Saved and sent to the Sales admin for approval.", "ok")
    return redirect(_link(cid))


@bp.route("/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def edit(cid):
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["edit"]:
        flash("Only a rejected client can be changed, by the Sales user who made it or the Sales admin.", "error")
        return redirect(_link(cid))
    if request.method == "GET":
        return _show_form(db, _form_from_db(db, c), cid=cid, c=c)
    existing = {r["id"]: r for r in db.execute("SELECT * FROM client_services WHERE client_id=?", (cid,)).fetchall()}
    form, errors, contacts, services, saved_new, delete_old = _read_form(db, existing)
    if errors:
        _remove_files(saved_new)
        return _show_form(db, form, cid=cid, c=c, errors=errors)
    try:
        done = db.execute(
            "UPDATE client_onboardings SET client_name=?, business_type=?, address=?, phone=?, email=?, notes=?, "
            "account_manager_id=?, status='pending', reject_reason=NULL, decided_by=NULL, decided_at=NULL, "
            "updated_at=datetime('now','localtime') WHERE id=? AND status='rejected'",
            (form["client_name"], form["business_type"] or None, form["address"] or None, form["phone"] or None,
             form["email"] or None, form["notes"] or None, form["account_manager_id"], cid)).rowcount
        if done == 0:                                    # somebody else changed the status meanwhile
            db.rollback()
            _remove_files(saved_new)
            flash("This client is not rejected any more, so it cannot be changed.", "error")
            return redirect(_link(cid))
        _write_children(db, cid, contacts, services)
        _history(db, cid, g.user, "saved again and sent for approval")
        log(db, "client_edit", f"{client_no(cid)} {form['client_name']}")
        _send_for_approval_notice(db, cid, form["client_name"], True)
        db.commit()
    except Exception:
        db.rollback()
        _remove_files(saved_new)
        raise
    _remove_files(delete_old)
    flash("Saved and sent to the Sales admin for approval again.", "ok")
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
        log(db, "client_approve", f"{client_no(cid)} {c['client_name']}")
        text = f"The client '{c['client_name']}' was approved."
        notify(db, [c["owner_id"]], text, _link(cid), skip=g.user["id"])
        # Revenue Assurance sees it first (view only); the three technical departments see the full record.
        notify(db, _members(db, "revenue_assurance"), text + " You can view it (view only).", _link(cid), skip=g.user["id"])
        for role in SAN_ROLES:
            notify(db, _members(db, role), text + " View the record; one of you uploads the SAN report.",
                   _link(cid), skip=g.user["id"])
        db.commit()
        flash("Approved. The client is saved and Revenue Assurance, Transmission, Core and Technical support can see it.", "ok")
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
        log(db, "client_reject", f"{client_no(cid)} {c['client_name']}")
        notify(db, [c["owner_id"]], f"The client '{c['client_name']}' was rejected: {reason}", _link(cid), skip=g.user["id"])
        db.commit()
        flash("Rejected. It went back to the Sales user.", "ok")
    else:
        db.rollback()
        flash("This client was already decided.", "error")
    return redirect(_link(cid))


# ---------------------------------------------------------------- SAN report: one upload only
@bp.route("/<int:cid>/san", methods=["POST"])
@login_required
def san_upload(cid):
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["upload_san"]:
        flash("The SAN report cannot be uploaded: it was uploaded already, or you are not allowed to.", "error")
        return redirect(_link(cid))
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
        # The WHERE makes the upload atomic: of two people uploading at the same moment only one wins.
        done = db.execute("UPDATE client_onboardings SET san_file=?, san_by=?, san_at=datetime('now','localtime'), "
                          "status='san_uploaded', updated_at=datetime('now','localtime') "
                          "WHERE id=? AND status='approved' AND san_file IS NULL", (file_json, g.user["id"], cid)).rowcount
        if not done:
            db.rollback()
            _remove_files([stored])
            flash("A SAN report was uploaded already. Only one upload is allowed.", "error")
            return redirect(_link(cid))
        _history(db, cid, g.user, "SAN report uploaded", _file_info(file_json)["original"])
        log(db, "client_san", f"{client_no(cid)} {c['client_name']}")
        text = f"The SAN report of '{c['client_name']}' was uploaded by {g.user['full_name']}."
        ids = set(_members(db, "revenue_assurance")) | set(_members(db, "sales")) | {c["owner_id"]}
        notify(db, ids, text, _link(cid), skip=g.user["id"])
        db.commit()
    except Exception:
        db.rollback()
        _remove_files([stored])
        raise
    flash("SAN report uploaded. Revenue Assurance and Sales received it.", "ok")
    return redirect(_link(cid))


@bp.route("/<int:cid>/san/remove", methods=["POST"])
@login_required
def san_remove(cid):
    """Portal admin only, to fix a wrong upload while the activation date is not set."""
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["remove_san"]:
        abort(403)
    info = _file_info(c["san_file"])
    db.execute("UPDATE client_onboardings SET san_file=NULL, san_by=NULL, san_at=NULL, status='approved', "
               "updated_at=datetime('now','localtime') WHERE id=? AND status='san_uploaded'", (cid,))
    _history(db, cid, g.user, "SAN report removed", (info or {}).get("original"))
    log(db, "client_san_remove", f"{client_no(cid)} {c['client_name']}")
    db.commit()
    if info:
        _remove_files([info["stored"]])
    flash("The SAN report was removed. A new one can be uploaded.", "ok")
    return redirect(_link(cid))


# ---------------------------------------------------------------- Revenue Assurance: activation date
@bp.route("/<int:cid>/activation", methods=["POST"])
@login_required
def activation(cid):
    db, c, roles = _load(cid)
    if not _perms(db, g.user, roles, c)["activation"]:
        abort(403)
    raw = (request.form.get("activation_date") or "").strip()
    try:
        day = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        flash("Pick the activation date.", "error")
        return redirect(_link(cid))
    old = str(c["activation_date"])[:10] if c["activation_date"] else None
    if old == day.isoformat():
        flash("The activation date is already that day.", "ok")
        return redirect(_link(cid))
    done = db.execute("UPDATE client_onboardings SET activation_date=?, activation_by=?, "
                      "activation_at=datetime('now','localtime'), status='completed', "
                      "updated_at=datetime('now','localtime') WHERE id=? AND status IN ('san_uploaded','completed')",
                      (day.isoformat(), g.user["id"], cid)).rowcount
    if not done:
        db.rollback()
        flash("The activation date cannot be set now.", "error")
        return redirect(_link(cid))
    _history(db, cid, g.user, "activation date set" if not old else "activation date changed",
             f"{old} -> {day.isoformat()}" if old else day.isoformat())
    log(db, "client_activation", f"{client_no(cid)} {c['client_name']} {day.isoformat()}")
    if old:
        text = f"The activation date of '{c['client_name']}' changed to {day.isoformat()}."
    else:
        text = f"The final record of '{c['client_name']}' is ready: activation date {day.isoformat()}."
    notify(db, set(_members(db, "finance")) | {c["owner_id"]}, text, _link(cid), skip=g.user["id"])
    db.commit()
    flash("Activation date saved. Finance received the final record." if not old
          else "Activation date changed. Finance was told.", "ok")
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
    info = _file_info(row["sof_file"]) if row else None
    if info is None:
        abort(404)
    return _send_stored(info)


@bp.route("/<int:cid>/san/download")
@login_required
def san_download(cid):
    db, c, roles = _load(cid)
    info = _file_info(c["san_file"])
    if info is None:
        abort(404)
    return _send_stored(info)


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

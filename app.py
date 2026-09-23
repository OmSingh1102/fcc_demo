"""FinCrime KYC/KYB Operations Hub — demo.

One Flask module, thin routes, all logic in the fincrime/ package. Built the
way the ChargeShield demo is built: no factory, no blueprints, demo data
loaded at import so the reloader's two processes agree, a SQLite state store
that survives a restart, one stylesheet, no JS framework.

Sections, in order: Modular imports · App Setup · Sign-in, analysts and roles
· Tenant · Nav tables · State · Context processor · Auth routes · KYC case
management · Documents · Name screening · World-Check (simulated) · Queues,
Skopenow, KYB · Analytics · Demo affordances · Main.
"""
import hmac
import os
from functools import wraps

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for)

try:  # A deployed copy reads .env (see .env.example); a dev checkout has none.
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

# ─── Modular imports ───────────────────────────────────────────────────────────
from fincrime.adapters import idv_vendor
from fincrime.analytics.case_list import CaseListConsole
from fincrime.analytics.dashboard import AnalyticsConsole
from fincrime.analytics.queues import QueueConsole
from fincrime.data import vocab
from fincrime.data.loader import SEED_VERSION, index_by_id, load_seed
from fincrime.data.state_store import StateStore
from fincrime.documents import svg_cards
from fincrime.engines import recommendation, screening, segregation, sla, worldcheck, workflow
from fincrime.engines.errors import WorkflowError
from fincrime.engines.wc_report_pdf import render_wc_export
from fincrime.utils import dates
from fincrime.utils.text import initials

# ─── App Setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fincrime-dev-key")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

# The state store must never raise — its restore runs at import, so an
# unwritable or locked database would take the app down rather than merely
# losing a decision. It reports here instead.
StateStore.on_error = app.logger.warning

DEBUG = os.environ.get("DEBUG", "1") == "1"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8010"))

# Jinja *globals*, not context-processor values: a macro imported with
# {% from "_badges.html" import ... %} does not see the render context, but it
# does see globals, and the badge macros need the status colour map.
app.jinja_env.globals.update(status_tone=vocab.STATUS_TONE, vocab=vocab,
                             icon=app.jinja_env.get_template("_icon.html").module.icon)
app.jinja_env.filters.update(wc_date=dates.wc_date, wc_dt=dates.wc_datetime)

# ─── Sign-in, analysts and roles ───────────────────────────────────────────────
# Demo gate only: one shared password, a profile picker, the session cookie
# signed with the dev secret above. It decides which analyst the app records
# as the actor — it is not a security control.
DEMO_PASSWORD = os.environ.get("STRAIVE_DEMO_PASSWORD", "1234")
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"
# Only advertise the password on the card while it is the built-in one.
_SHOW_DEMO_HINT = "STRAIVE_DEMO_PASSWORD" not in os.environ

ROLE_LABEL = {"L1": "L1 Analyst", "L2": "L2 Analyst", "EDD": "EDD Analyst", "QC": "QC Lead"}
PUBLIC_ENDPOINTS = {"portal", "login", "logout", "static"}

ANALYSTS = []            # filled by _load_seed
ANALYST_BY_KEY = {}
ANALYST_BY_EMAIL = {}


def _analyst():
    return ANALYST_BY_KEY.get(session.get("user"))


def _actor() -> str:
    return session.get("email", "")


def _levels() -> set:
    return set(session.get("roles") or [])


def _check_password(password: str) -> bool:
    return hmac.compare_digest((password or "").encode("utf-8"), DEMO_PASSWORD.encode("utf-8"))


def _safe_next(target: str, fallback=None) -> str:
    """Only follow same-site paths. Rejects absolute and protocol-relative URLs."""
    if target and target.startswith("/") and target[1:2] not in ("/", "\\"):
        return target
    return fallback or url_for("kyc_list")


def role_required(*levels):
    """Restrict a view to analysts holding one of the given levels. A
    signed-in analyst without the level is sent home rather than shown an
    error — the nav never offered them the link."""
    allowed = set(levels)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("user"):
                return redirect(url_for("login", next=request.path))
            if allowed and not (_levels() & allowed):
                flash(f"That action needs {' or '.join(sorted(allowed))} access.", "error")
                return redirect(url_for("kyc_list"))
            return view(*args, **kwargs)
        return wrapper
    return decorator


@app.before_request
def _require_sign_in():
    """Everything outside PUBLIC_ENDPOINTS needs a session. One hook rather
    than a decorator on each route: easier to audit, impossible to forget."""
    if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not session.get("user") or session.get("user") not in ANALYST_BY_KEY:
        session.clear()
        return redirect(url_for("portal"))
    # A deep link may name the tenant, the way the real tool's URLs do.
    wanted = request.args.get("tenant")
    if wanted in vocab.TENANTS and wanted in (_analyst() or {}).get("tenants", []):
        session["tenant"] = wanted
    return None


# ─── Tenant ────────────────────────────────────────────────────────────────────
def _tenant() -> str:
    a = _analyst() or {}
    allowed = a.get("tenants") or ["ttlive"]
    t = session.get("tenant")
    return t if t in allowed else allowed[0]


# ─── Nav tables ────────────────────────────────────────────────────────────────
TOP_TABS = [
    {"label": "Case Management", "endpoint": "kyc_list"},
    {"label": "Utility Hub"}, {"label": "Risk & Customer Controls"}, {"label": "Platform Configuration"},
]

# Which side-nav entry a page belongs to, by endpoint prefix.
_NAV_OWNER = (("kyc_", "kyc_list"), ("document", "kyc_list"), ("ns_", "ns_queue"), ("wc_", "ns_queue"),
              ("queue_", "queue_l2"), ("analytics", "analytics"))


def _nav_owner(endpoint: str) -> str:
    for prefix, owner in _NAV_OWNER:
        if (endpoint or "").startswith(prefix):
            return owner
    return ""


def _side_nav():
    owner = _nav_owner(request.endpoint)
    levels = _levels()
    tenant = _tenant()
    open_l1 = sum(1 for c in KYC_CASES if c["tenant"] == tenant and c["status"] in ("DataConfirming", "DataScreening"))
    open_l2 = sum(1 for c in KYC_CASES if c["tenant"] == tenant and c["status"] == "DataEscalatingL2"
                  and not segregation.hidden_from(c, _actor(), "L2"))
    items = [
        {"label": "Transaction Monitoring", "icon": "activity", "disabled": True},
        {"label": "Sanctions Screening", "icon": "shield", "has_active": owner == "ns_queue", "children": [
            {"label": "Name Screening", "icon": "search", "endpoint": "ns_queue", "active": owner == "ns_queue"},
        ]},
        {"label": "Due Diligence (KYC/KYB)", "icon": "user-check", "endpoint": "kyc_list", "active": owner == "kyc_list", "count": open_l1},
    ]
    if levels & {"L2", "EDD", "QC"}:
        items.append({"label": "L2 / EDD Queue", "icon": "layers", "endpoint": "queue_l2", "active": owner == "queue_l2", "count": open_l2})
    items.append({"label": "Analytics", "icon": "bar-chart", "endpoint": "analytics", "active": owner == "analytics"})
    return items


# ─── State ─────────────────────────────────────────────────────────────────────
# Bumped on every write; polled by _live_refresh.html so a second screen
# notices a change made on the first.
STATE_VERSION = 0

KYC_CASES, ALERT_CASES, WC_CASES = [], [], []
KYC_BY_ID, ALERT_BY_ID, WC_BY_ID = {}, {}, {}


def _bump_state():
    global STATE_VERSION
    STATE_VERSION += 1


def _rebuild_indexes():
    KYC_BY_ID.clear(); KYC_BY_ID.update(index_by_id(KYC_CASES))
    ALERT_BY_ID.clear(); ALERT_BY_ID.update(index_by_id(ALERT_CASES))
    WC_BY_ID.clear(); WC_BY_ID.update(index_by_id(WC_CASES))
    ANALYST_BY_KEY.clear(); ANALYST_BY_KEY.update({a["key"]: a for a in ANALYSTS})
    ANALYST_BY_EMAIL.clear(); ANALYST_BY_EMAIL.update({a["email"]: a for a in ANALYSTS})


def _load_seed():
    """Rebuild the three case lists from the seed, then lay stored actions
    back on top. Rebinds the lists in place so every reference stays valid.

    A stored seed version that differs from the code's means the record shape
    may have moved; the store is cleared and the log says so. Done only in
    the reloader's child (or outside debug) so the parent process never
    wipes the database on its own boot."""
    analysts, kyc, alerts, wc = load_seed()
    ANALYSTS[:] = analysts
    KYC_CASES[:] = kyc
    ALERT_CASES[:] = alerts
    WC_CASES[:] = wc
    _rebuild_indexes()

    in_serving_process = (not DEBUG) or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    stored = StateStore.seed_version()
    if stored and stored != SEED_VERSION and in_serving_process:
        app.logger.warning("Seed version changed (%s -> %s); clearing stored demo state.", stored, SEED_VERSION)
        StateStore.clear()
        stored = ""
    if not stored and in_serving_process:
        StateStore.set_seed_version(SEED_VERSION)

    restored = (StateStore.restore("kyc", KYC_BY_ID) + StateStore.restore("alert", ALERT_BY_ID)
                + StateStore.restore("wc", WC_BY_ID))
    if restored:
        app.logger.info("Restored %d stored record(s) onto the seed.", restored)


def _save(kind: str, record: dict):
    """Persist one touched record and tell the live-refresh poll about it."""
    _bump_state()
    StateStore.save(kind, record)


def _kyc(case_id: str) -> dict:
    return KYC_BY_ID.get(case_id) or abort(404)


def _alert(alert_case_id: str) -> dict:
    return ALERT_BY_ID.get(alert_case_id) or abort(404)


def _wc(wc_case_id: str) -> dict:
    return WC_BY_ID.get(wc_case_id) or abort(404)


def _run_action(fn, *args, **kwargs):
    """Call an engine action; a WorkflowError becomes an error flash and the
    caller redirects. Returns (ok, result)."""
    try:
        return True, fn(*args, **kwargs)
    except WorkflowError as exc:
        flash(str(exc), "error")
        return False, None


# ─── Context processor ─────────────────────────────────────────────────────────
@app.context_processor
def _inject_nav():
    a = _analyst() or {}
    signed_in = bool(a)
    return {
        "tenants": vocab.TENANTS,
        "tenant": _tenant() if signed_in else "ttlive",
        "analyst_tenants": a.get("tenants") or ["ttlive"],
        "top_tabs": [dict(t, active=(t.get("endpoint") == "kyc_list")) for t in TOP_TABS],
        "side_nav": _side_nav() if signed_in else [],
        "role_label": " / ".join(a.get("roles", [])),
        "user_initials": initials(a.get("name", "")),
        "region": "US-TTP",
        "home_url": url_for("kyc_list") if signed_in else url_for("portal"),
        "demo_mode": DEMO_MODE,
        "switch_users": ANALYSTS if (DEMO_MODE and signed_in) else [],
        "all_analysts": ANALYSTS,
        "status_tone": vocab.STATUS_TONE,
        "state_version": STATE_VERSION,
        # The line-icon macro, delivered to every template including the
        # standalone auth pages. Fetched per render so editing _icon.html
        # shows up without a restart, like any other template.
        "icon": app.jinja_env.get_template("_icon.html").module.icon,
    }


# ─── Auth routes ───────────────────────────────────────────────────────────────
@app.route("/state/version")
def state_version():
    """Cheap staleness probe polled by every open console."""
    return jsonify({"v": STATE_VERSION})


@app.route("/")
def portal():
    if session.get("user") in ANALYST_BY_KEY:
        return redirect(url_for("kyc_list"))
    return render_template("portal.html")


def _login_page(error="", selected="", next_url="", status=200):
    return render_template("login.html", error=error, selected=selected or ANALYSTS[0]["key"], next=next_url,
                           analysts=ANALYSTS, demo_password=DEMO_PASSWORD if _SHOW_DEMO_HINT else ""), status


def _sign_in(analyst: dict):
    session.clear()
    session["user"] = analyst["key"]
    session["email"] = analyst["email"]
    session["name"] = analyst["name"]
    session["role"] = analyst["role"]
    session["roles"] = list(analyst["roles"])
    session["tenant"] = analyst["tenants"][0]


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.values.get("next", "")
    if request.method == "POST":
        key = request.form.get("analyst", "")
        analyst = ANALYST_BY_KEY.get(key)
        if not analyst:
            return _login_page(error="Choose an analyst profile to sign in as.", next_url=next_url, status=400)
        if not _check_password(request.form.get("password", "")):
            return _login_page(error="Incorrect password.", selected=key, next_url=next_url, status=401)
        _sign_in(analyst)
        return redirect(_safe_next(next_url))
    if session.get("user") in ANALYST_BY_KEY:
        return redirect(_safe_next(next_url))
    return _login_page(next_url=next_url)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("portal"))


@app.route("/tenant", methods=["POST"])
def set_tenant():
    wanted = request.form.get("tenant", "")
    if wanted in (_analyst() or {}).get("tenants", []):
        session["tenant"] = wanted
    return redirect(_safe_next(request.form.get("next", "")))


@app.route("/switch-user", methods=["POST"])
def switch_user():
    """Demo shortcut: jump between analyst profiles without the login page,
    so the presenter can go from L1 to L2 in one click. Off unless DEMO_MODE."""
    if not DEMO_MODE:
        abort(404)
    analyst = ANALYST_BY_KEY.get(request.form.get("analyst", ""))
    if analyst:
        keep_tenant = session.get("tenant")
        _sign_in(analyst)
        if keep_tenant in analyst["tenants"]:
            session["tenant"] = keep_tenant
        flash(f"Now working as {analyst['name']} ({' / '.join(analyst['roles'])}).", "success")
    return redirect(_safe_next(request.form.get("next", "")))


# ─── KYC case management ───────────────────────────────────────────────────────
@app.route("/kyc/list")
def kyc_list():
    vm = CaseListConsole.compute(KYC_CASES, _tenant(), _actor())
    preset = [s for s in request.args.getlist("status") if s in vocab.STATUSES]
    return render_template("kyc_list.html", rows=vm["rows"], total=vm["total"], filters=vm["filters"],
                           status_preset=preset)


def _linked(case):
    """(screening case, watchlist case) for a KYC case with a hit, else (None, None)."""
    alert = ALERT_BY_ID.get(case["screening"]["alert_case_id"]) if case["screening"]["hit"] else None
    wc = WC_BY_ID.get(alert["id"]) if alert else None
    return alert, wc


@app.route("/kyc/detail/<case_id>")
def kyc_detail(case_id):
    case = _kyc(case_id)
    alert, wc = _linked(case)
    levels, actor = _levels(), _actor()
    l2_level = "EDD" if case["pending_reason"] == "Pending EDD" else "L2"
    hit = case["screening"]["hit"]
    return render_template(
        "kyc_detail.html", case=case, alert=alert, wc=wc, levels=levels, actor=actor,
        points=workflow.verification_points(case), review=workflow.review_action(case, levels),
        is_mine=case["current_reviewer"] == actor, closed=case["status"] in vocab.CLOSED_STATUSES,
        sla=sla.chip(case), vendor=idv_vendor.details(case), confirm_fields=workflow.confirm_fields(case),
        pending_alerts=sum(1 for a in (alert or {}).get("alerts", []) if a["outcome"] == "Pending"),
        exports=(wc or {}).get("exports", []), l2_level=l2_level,
        segregated=segregation.hidden_from(case, actor, l2_level) if case["status"] == "DataEscalatingL2" else False,
        edd_decisions=(list(vocab.EDD_DECISIONS) if hit else ["No match - Approve"] + list(vocab.EDD_DECISIONS)),
        analysts=ANALYSTS)


@app.route("/kyc/detail/<case_id>/audit")
def kyc_audit(case_id):
    return render_template("kyc_audit.html", case=_kyc(case_id), view=request.args.get("view", "audit"))


def _case_action(case_id, fn, *args, success="", open_modal="", **kwargs):
    """Run one workflow action on a case as the signed-in analyst; persist on
    success; go back to the case, reopening the modal on a validation flash."""
    case = _kyc(case_id)
    ok, result = _run_action(fn, case, _actor(), *args, **kwargs)
    if ok:
        _save("kyc", case)
        if success:
            flash(success, "success")
    target = url_for("kyc_detail", case_id=case_id)
    if not ok and open_modal:
        target += f"?open={open_modal}"
    return redirect(target)


@app.route("/kyc/<case_id>/reserve", methods=["POST"])
@role_required("L1", "L2", "EDD")
def kyc_reserve(case_id):
    return _case_action(case_id, workflow.reserve, success="Case reserved. You are the current reviewer.")


@app.route("/kyc/<case_id>/release", methods=["POST"])
@role_required("L1", "L2", "EDD")
def kyc_release(case_id):
    return _case_action(case_id, workflow.release, success="Case released to the queue.")


@app.route("/kyc/<case_id>/assign", methods=["POST"])
@role_required("L1", "L2", "EDD", "QC")
def kyc_assign(case_id):
    return _case_action(case_id, workflow.assign, request.form.get("assignee", ""), success="Case assigned.")


@app.route("/kyc/<case_id>/tag", methods=["POST"])
def kyc_tag(case_id):
    return _case_action(case_id, workflow.add_tag, request.form.get("tag", ""))


@app.route("/kyc/<case_id>/modify", methods=["POST"])
@role_required("L1", "L2", "EDD", "QC")
def kyc_modify(case_id):
    return _case_action(case_id, workflow.modify_user_info, request.form, success="User info updated; see the Change Log.",
                        open_modal="modify-modal")


@app.route("/kyc/<case_id>/status", methods=["POST"])
@role_required("L2", "QC")
def kyc_status(case_id):
    return _case_action(case_id, workflow.change_status, request.form.get("status", ""), request.form.get("comment", ""),
                        success="Status changed.", open_modal="status-modal")


@app.route("/kyc/<case_id>/data_confirm", methods=["POST"])
@role_required("L1")
def kyc_data_confirm(case_id):
    return _case_action(case_id, workflow.data_confirm, request.form,
                        success="Data confirmed — the case moved to Data Screening and was re-screened.", open_modal="dc-modal")


@app.route("/kyc/<case_id>/resubmit", methods=["POST"])
@role_required("L1")
def kyc_resubmit(case_id):
    return _case_action(case_id, workflow.resubmit, request.form.getlist("decision"), request.form.get("id_reason", ""),
                        request.form.get("poa_reason", ""), request.form.get("note", ""),
                        success="Resubmission requested. The case leaves your queue until the user uploads again.",
                        open_modal="dc-modal")


@app.route("/kyc/<case_id>/escalate", methods=["POST"])
@role_required("L1")
def kyc_escalate(case_id):
    case = _kyc(case_id)
    back = "dc-modal" if case["status"] == "DataConfirming" else "edd-modal"
    return _case_action(case_id, workflow.escalate, request.form.get("reason", ""), request.form.get("comment", ""),
                        success="Escalated to L2. The 14-day EDD clock has started.", open_modal=back)


@app.route("/kyc/<case_id>/rfi", methods=["POST"])
@role_required("L1", "L2", "EDD")
def kyc_rfi(case_id):
    return _case_action(case_id, workflow.rfi, request.form.get("message", ""), success="RFI sent to the user.",
                        open_modal="rfi-modal")


@app.route("/kyc/<case_id>/edd_review", methods=["POST"])
@role_required("L1", "L2", "EDD")
def kyc_edd_review(case_id):
    case = _kyc(case_id)
    alert, _wc = _linked(case)
    attachment = request.form.get("attachment", "") or request.form.get("attachment_name", "")
    return _case_action(case_id, workflow.edd_review, request.form.get("decision", ""), request.form.get("summary", ""),
                        attachment, alert_case=alert, success="Review recorded.", open_modal="edd-modal")


@app.route("/kyc/<case_id>/l2_decision", methods=["POST"])
@role_required("L2", "EDD")
def kyc_l2_decision(case_id):
    case = _kyc(case_id)
    level = "EDD" if case["pending_reason"] == "Pending EDD" else "L2"
    return _case_action(case_id, workflow.l2_decision, level, request.form.get("decision", ""), request.form.get("comment", ""),
                        success=f"{level} decision recorded.", open_modal="l2-modal")


@app.route("/kyc/<case_id>/skopenow", methods=["GET", "POST"])
@role_required("L1", "L2", "EDD", "QC")
def kyc_skopenow(case_id):
    case = _kyc(case_id)
    if request.method == "POST":
        ok, _ = _run_action(workflow.skopenow_clear, case, _actor(), request.form.get("outcome", ""), request.form.get("notes", ""))
        if ok:
            _save("kyc", case)
            flash("Skopenow outcome recorded.", "success")
            return redirect(url_for("kyc_detail", case_id=case_id))
        return redirect(url_for("kyc_skopenow", case_id=case_id))
    return render_template("skopenow.html", case=case, is_mine=case["current_reviewer"] == _actor())


@app.route("/kyc/<case_id>/recalculate_risk", methods=["POST"])
@role_required("L1", "L2", "EDD")
def kyc_recalculate_risk(case_id):
    case = _kyc(case_id)
    ok, rating = _run_action(workflow.recalculate_risk, case, _actor())
    if ok:
        _save("kyc", case)
        flash(f"Risk rating recalculated: {rating}.", "success")
    return redirect(url_for("kyc_detail", case_id=case_id))


@app.route("/kyc/bulk_assign", methods=["POST"])
@role_required("L2", "QC")
def kyc_bulk_assign():
    assignee = request.form.get("assignee", "")
    done = 0
    for case_id in request.form.getlist("case_id"):
        case = KYC_BY_ID.get(case_id)
        if not case:
            continue
        ok, _ = _run_action(workflow.assign, case, _actor(), assignee)
        if ok:
            _save("kyc", case)
            done += 1
    flash(f"Assigned {done} case(s) to {assignee}.", "success" if done else "error")
    return redirect(url_for("kyc_list"))


# ─── Documents ─────────────────────────────────────────────────────────────────
@app.route("/documents/<case_id>/<doc_id>.svg")
def document_svg(case_id, doc_id):
    """A synthetic document drawn from the case data (see documents/svg_cards)."""
    case = _kyc(case_id)
    doc = next((d for d in case["documents"] if d["id"] == doc_id), None) or abort(404)
    return Response(svg_cards.render(case, doc), mimetype="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


# ─── Name screening ────────────────────────────────────────────────────────────
def _tenant_alerts():
    t = _tenant()
    return [a for a in ALERT_CASES if (KYC_BY_ID.get(a["kyc_case_id"]) or {}).get("tenant") == t]


@app.route("/name_screening/queue")
def ns_queue():
    level = request.args.get("level", "L1")
    mine = request.args.get("mine") == "1"
    # Row copies, not the records: "pending" is a view field and must not be
    # persisted into the store the next time the record is saved.
    alerts = [dict(a, pending=sum(1 for x in a["alerts"] if x["outcome"] == "Pending")) for a in _tenant_alerts()]
    queues = []
    for lv in ("L1", "L2"):
        rows = [a for a in alerts if a["case_level"] == lv]
        queues.append({"level": lv, "name": f"{vocab.TENANTS[_tenant()]['cms_queue']}_{lv}", "total": len(rows),
                       "pending": sum(1 for a in rows if a["status"] != "Closed"),
                       "completed": sum(1 for a in rows if a["status"] == "Closed")})
    rows = [a for a in alerts if a["case_level"] == level and (not mine or a["assigned_to"] == _actor())]
    rows.sort(key=lambda a: (a["status"] == "Closed", a["created_at"]), reverse=False)
    return render_template("ns_queue.html", level=level, mine_only=mine, queues=queues, rows=rows)


@app.route("/name_screening/search")
def ns_search():
    q = (request.args.get("q") or "").strip().lower()
    if q:
        for a in ALERT_CASES:
            k = KYC_BY_ID.get(a["kyc_case_id"]) or {}
            if q in (a["id"], a["merchant_uid"], a["kyc_case_id"]) or q in k.get("client", {}).get("legal_name", "").lower():
                return redirect(url_for("ns_case", alert_case_id=a["id"]))
        for wc in WC_CASES:
            if any(m["wc_id"] == q for m in wc["matches"]):
                mid = next(m["id"] for m in wc["matches"] if m["wc_id"] == q)
                return redirect(url_for("wc_match", wc_case_id=wc["id"], match_id=mid))
    flash(f"No screening case or record matches '{q}'." if q else "Enter a case ID, merchant UID, KYC case ID or name.", "error")
    return redirect(request.referrer or url_for("ns_queue"))


@app.route("/name_screening/case/<alert_case_id>")
def ns_case(alert_case_id):
    alert = _alert(alert_case_id)
    wc = WC_BY_ID.get(alert["id"])
    types = sorted({a["type"] for a in alert["alerts"] if a["type"]})
    return render_template("ns_case.html", alert=alert, wc=wc, actor=_actor(), types=types,
                           counts=screening.tab_counts(alert["alerts"]),
                           recommendation=recommendation.recommend_case_outcome(alert, wc))


def _alert_action(alert_case_id, fn, *args, success="", open_modal="", **kwargs):
    alert = _alert(alert_case_id)
    ok, _ = _run_action(fn, alert, _actor(), *args, **kwargs)
    if ok:
        _save("alert", alert)
        if success:
            flash(success, "success")
    target = url_for("ns_case", alert_case_id=alert_case_id)
    return redirect(target + (f"?open={open_modal}" if not ok and open_modal else ""))


@app.route("/name_screening/<alert_case_id>/handle", methods=["POST"])
@role_required("L1", "L2")
def ns_handle(alert_case_id):
    return _alert_action(alert_case_id, screening.handle, success="You are handling this screening case.")


@app.route("/name_screening/<alert_case_id>/alert_outcome", methods=["POST"])
@role_required("L1", "L2")
def ns_alert_outcome(alert_case_id):
    return _alert_action(alert_case_id, screening.alert_outcome, request.form, success="Alert outcome recorded.",
                         open_modal="alert-outcome")


@app.route("/name_screening/<alert_case_id>/case_outcome", methods=["POST"])
@role_required("L1", "L2")
def ns_case_outcome(alert_case_id):
    alert = _alert(alert_case_id)
    kyc = KYC_BY_ID.get(alert["kyc_case_id"])
    ok, _ = _run_action(screening.case_outcome, alert, _actor(), request.form, kyc=kyc)
    if ok:
        _save("alert", alert)
        if kyc:
            _save("kyc", kyc)
        flash(f"Case outcome recorded: {alert['case_outcome']['value']}. Back on the KYC case, run the EDD Review.", "success")
        return redirect(url_for("ns_case", alert_case_id=alert_case_id))
    return redirect(url_for("ns_case", alert_case_id=alert_case_id) + "?open=case-outcome")


# ─── World-Check (simulated) ───────────────────────────────────────────────────
def _wc_context(wc):
    alert = ALERT_BY_ID.get(wc["alert_case_id"])
    return {"wc": wc, "alert": alert, "back_url": url_for("ns_case", alert_case_id=wc["alert_case_id"]),
            "can_resolve": bool(alert) and alert["status"] == "Handling" and alert["assigned_to"] == _actor()}


@app.route("/wc/<wc_case_id>")
def wc_case(wc_case_id):
    wc = _wc(wc_case_id)
    status, mtype = request.args.get("status", ""), request.args.get("type", "")
    filtered = worldcheck.filter_matches(wc["matches"], status, mtype)
    page = worldcheck.paginate(filtered, int(request.args.get("page", "1") or 1))
    return render_template("wc_case.html", tab=request.args.get("tab", "worldcheck"), status=status, mtype=mtype,
                           facets=worldcheck.facets(wc["matches"]), page=page, **_wc_context(wc))


@app.route("/wc/<wc_case_id>/match/<match_id>")
def wc_match(wc_case_id, match_id):
    wc = _wc(wc_case_id)
    m = worldcheck.find_match(wc, match_id) or abort(404)
    status, mtype = request.args.get("status", ""), request.args.get("type", "")
    return render_template("wc_match.html", m=m, status=status, mtype=mtype,
                           nav=worldcheck.match_nav(wc, match_id, status, mtype),
                           comparison=worldcheck.comparison_rows(wc, m),
                           unresolved=worldcheck.facets(wc["matches"])["status"]["Unresolved"], **_wc_context(wc))


@app.route("/wc/<wc_case_id>/match/<match_id>/resolve", methods=["POST"])
@role_required("L1", "L2")
def wc_resolve(wc_case_id, match_id):
    wc = _wc(wc_case_id)
    ctx = _wc_context(wc)
    f = request.form
    if not ctx["can_resolve"]:
        flash("Handle the screening case first — only its handler can resolve matches.", "error")
    else:
        ok, _ = _run_action(worldcheck.resolve_match, wc, _actor(), match_id, f.get("status", ""), f.get("risk", ""),
                            f.get("reason", ""), f.get("comment", ""))
        if ok:
            _save("wc", wc)
            flash("Match resolved. Record the matching alert outcome on the screening case.", "success")
    return redirect(url_for("wc_match", wc_case_id=wc_case_id, match_id=match_id, status=f.get("status_filter", ""),
                            type=f.get("type_filter", "")))


@app.route("/wc/<wc_case_id>/export", methods=["POST"])
def wc_export(wc_case_id):
    wc = _wc(wc_case_id)
    export = worldcheck.record_export(wc, _actor())
    _save("wc", wc)
    flash(f"Exported {export['filename']} — it is now available to attach in the EDD Review.", "success")
    return redirect(url_for("wc_case", wc_case_id=wc_case_id, tab="summary"))


@app.route("/wc/<wc_case_id>/export.pdf")
def wc_export_pdf(wc_case_id):
    wc = _wc(wc_case_id)
    alert = ALERT_BY_ID.get(wc["alert_case_id"])
    pdf = render_wc_export(wc, alert, KYC_BY_ID.get(wc["kyc_case_id"]), _actor())
    name = (wc["exports"][-1]["filename"] if wc["exports"] else f"WorldCheck_{wc['id'][:8]}.pdf")
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


# ─── Queues ────────────────────────────────────────────────────────────────────
@app.route("/queue/l2")
@role_required("L2", "EDD", "QC")
def queue_l2():
    vm = QueueConsole.compute(KYC_CASES, _tenant(), _actor(), _levels())
    return render_template("queue_l2.html", vm=vm)


# ─── Analytics ─────────────────────────────────────────────────────────────────
@app.route("/analytics")
def analytics():
    vm = AnalyticsConsole.compute(KYC_CASES, ALERT_CASES, WC_CASES, _tenant())
    return render_template("analytics.html", vm=vm)


# ─── Demo affordances ──────────────────────────────────────────────────────────
@app.route("/reset", methods=["POST"])
def reset_demo():
    """Back to the seeded case book: drop every stored action and reload."""
    if not DEMO_MODE:
        abort(404)
    cleared = StateStore.clear()
    _load_seed()
    _bump_state()
    flash("Demo reset — the seeded case book is back." if cleared else "Could not clear the stored state.",
          "success" if cleared else "error")
    return redirect(_safe_next(request.form.get("next", "")) if request.form.get("next") else url_for("kyc_list"))


# ─── Main ──────────────────────────────────────────────────────────────────────
_load_seed()

if __name__ == "__main__":
    print(f" * FinCrime Operations Hub on http://{HOST}:{PORT}  (demo password: {DEMO_PASSWORD})")
    app.run(debug=DEBUG, host=HOST, port=PORT)

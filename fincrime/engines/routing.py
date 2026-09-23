"""Automated case routing — the hub's replacement for bot allocation plus
manual self-assignment (SOP 5.2: end-to-end routing, dynamic capacity and
case on-demand, immediate hand-offs between tiers).

A case has requirements (tenant, tier, document script, KYB); an analyst has
a skill book (tenants, roles, scripts, KYB) and a capacity. The router gives
a case to the least-loaded analyst who is eligible — same tenant, holds the
tier's role, has the skills, is not blocked by segregation at that tier, and
has free capacity. Every decision lands in the case's audit trail with the
reason, so a lead can always answer "why did this case go there?".

The module is bound to the live case book once at boot (configure()). It
never imports app.py or workflow.py: workflow imports it for hand-offs.
"""
from fincrime.data import vocab
from fincrime.engines import segregation, sla, worklog
from fincrime.engines.errors import WorkflowError
from fincrime.utils import dates
from fincrime.utils.text import display_name, script_of

ROUTER = "FCC Router"
BOOK = {"analysts": [], "cases": []}


def configure(analysts, cases):
    """Bind the live lists. app.py rebinds them in place on reset, so this
    is called once per boot and stays valid."""
    BOOK["analysts"] = analysts
    BOOK["cases"] = cases


def _cases(cases):
    return BOOK["cases"] if cases is None else cases


def _audit(case, action, detail=""):
    case.setdefault("audit", []).append({"at": dates.now_str(), "actor": ROUTER, "action": action, "detail": detail})


# ── requirements & eligibility ───────────────────────────────────────────────

def level_for(case):
    """The tier that should hold the case right now, or "" when it is not in
    any queue (intake, waiting on the user, closed)."""
    status, pending = case["status"], case.get("pending_reason", "")
    if status in ("DataConfirming", "DataScreening"):
        return "L2" if pending == "Pending Checker 2" else "L1"
    if status == "DataEscalatingL2":
        return "EDD" if pending == "Pending EDD" else "L2"
    return ""


def requirements(case):
    return {"tenant": case["tenant"], "level": level_for(case),
            "script": script_of((case.get("client") or {}).get("native_name", "")),
            "kyb": bool(case.get("agency"))}


def load(email, cases=None):
    """Open cases the analyst currently holds."""
    return sum(1 for c in _cases(cases)
               if c.get("current_reviewer") == email and c["status"] not in vocab.CLOSED_STATUSES)


def routed_today(email, cases=None, today=None):
    today = today or dates.now_str()[:10]
    return sum(1 for c in _cases(cases)
               if (c.get("routing") or {}).get("to") == email and (c.get("routing") or {}).get("at", "")[:10] == today)


def eligible(analyst, case, cases=None, exclude=()):
    """(ok, reason). The reason reads as a chip: what matched, or what blocked."""
    req = requirements(case)
    email = analyst["email"]
    skills = analyst.get("skills") or {}
    if not req["level"]:
        return False, "case is not in a queue"
    if req["tenant"] not in analyst.get("tenants", []):
        return False, f"no {vocab.TENANTS[req['tenant']]['label']} access"
    if req["level"] not in analyst.get("roles", []):
        return False, f"no {req['level']} role"
    if req["script"] not in (skills.get("scripts") or ["latin"]):
        return False, f"no {req['script']}-script document skill"
    if req["kyb"] and not skills.get("kyb"):
        return False, "no KYB skill"
    if email in exclude:
        return False, "handed the case off"
    if case.get("checker1") and case.get("pending_reason") == "Pending Checker 2" and email == case["checker1"]["by"]:
        return False, "was Checker 1"
    if segregation.hidden_from(case, email, req["level"]):
        return False, "worked the case at an earlier level"
    n, cap = load(email, cases), int(analyst.get("capacity") or 0)
    if n >= cap:
        return False, f"at capacity ({n}/{cap})"
    return True, f"{req['level']} · {req['script']} script{' · KYB' if req['kyb'] else ''} · load {n}/{cap}"


def candidates(case, cases=None, exclude=()):
    return [(a, *eligible(a, case, cases, exclude)) for a in BOOK["analysts"]]


def pick(case, cases=None, exclude=()):
    """(analyst | None, reason, considered). Least loaded wins; ties go to the
    alphabetically first key so the choice is reproducible."""
    considered = candidates(case, cases, exclude)
    ready = sorted(((load(a["email"], cases), a["key"], a, why) for a, ok, why in considered if ok),
                   key=lambda t: (t[0], t[1]))
    if ready:
        _, _, best, why = ready[0]
        return best, why, considered
    blocked = "; ".join(f"{display_name(a['email'])}: {why}" for a, ok, why in considered
                        if not ok and why != "case is not in a queue" and not why.startswith("no "))
    return None, "no eligible analyst with free capacity" + (f" ({blocked})" if blocked else ""), considered


# ── writing ──────────────────────────────────────────────────────────────────

def complete_handoff(case, email, at=None):
    """The newest hand-off still waiting for a taker gets its lag. Called by
    the router and by a manual Reserve / Assign, so a queued case picked up
    by hand measures its wait too."""
    now = at or dates.now_str()
    for h in reversed(case.get("handoffs") or []):
        if h.get("assigned_at"):
            return None
        h["assigned_to"], h["assigned_at"] = email, now
        start = dates.parse(h["at"])
        h["lag_seconds"] = int((dates.parse(now) - start).total_seconds()) if start else 0
        return h
    return None


def give(case, analyst, *, trigger, reason=""):
    """Hand the case to `analyst` now. The caller has already decided who."""
    now = dates.now_str()
    email = analyst["email"]
    case["current_reviewer"] = email
    case["routing"] = {"status": "routed", "to": email, "trigger": trigger, "reason": reason, "at": now}
    worklog.open_entry(case, email, level_for(case), now)
    complete_handoff(case, email, now)
    _audit(case, "Auto-routed", f"→ {display_name(email)} · {reason} · {vocab.ROUTING_TRIGGERS.get(trigger, trigger)}")
    return analyst


def route(case, *, trigger, cases=None, exclude=()):
    """Give the case to the best eligible analyst, or leave it queued (marked
    so, with the reason in the audit trail) when nobody can take it."""
    best, why, _ = pick(case, cases, exclude)
    if best is None:
        case["routing"] = {"status": "queued", "to": "", "trigger": trigger, "reason": why, "at": dates.now_str()}
        _audit(case, "Routing queued", f"{why}. Waiting for capacity ({vocab.ROUTING_TRIGGERS.get(trigger, trigger)}).")
        return None
    return give(case, best, trigger=trigger, reason=why)


def handoff(case, from_level, to_level, *, cases=None, exclude=()):
    """Record a tier hand-off and route the case at once (SOP 5.2.3: no bot
    lag). With no analyst book bound — unit use — the hand-off is recorded
    and nobody is routed."""
    case.setdefault("handoffs", []).append({"from": from_level, "to": to_level, "at": dates.now_str(),
                                            "assigned_to": "", "assigned_at": "", "lag_seconds": None, "via": "hub"})
    if not BOOK["analysts"]:
        return None
    return route(case, trigger="handoff", cases=cases, exclude=exclude)


def unassigned(tenant=None, cases=None):
    """Queue cases nobody holds, for the console and for on-demand pulls."""
    return [c for c in _cases(cases)
            if not c.get("current_reviewer") and level_for(c) and (tenant is None or c["tenant"] == tenant)]


def request_cases(analyst, n=1, *, tenant=None, cases=None, trigger="on_demand"):
    """Case on-demand (SOP 5.2.2): the analyst pulls up to `n` cases they are
    eligible for, most urgent first, within their remaining capacity."""
    email = analyst["email"]
    cap = int(analyst.get("capacity") or 0)
    if cap <= 0:
        raise WorkflowError("Your profile has no case capacity — the QC / team-lead role does not take cases.")
    headroom = cap - load(email, cases)
    if headroom <= 0:
        raise WorkflowError(f"You are at capacity ({cap}/{cap}). Complete or release a case before requesting more.")
    try:
        n = int(n or 1)
    except (TypeError, ValueError):
        n = 1
    n = max(1, min(n, headroom))
    pool = [c for c in unassigned(None, cases) if eligible(analyst, c, cases)[0]]
    if not pool:
        raise WorkflowError("No unassigned case matches your skill book right now.")
    pool.sort(key=lambda c: (0 if c["tenant"] == tenant else 1, sla.remaining_hours(c)))
    routed = []
    for c in pool[:n]:
        _, why = eligible(analyst, c, cases)
        give(c, analyst, trigger=trigger, reason=why)
        routed.append(c)
    return routed


def route_backlog(tenant, *, only_ids=None, cases=None, trigger="lead_run"):
    """Route the tenant's unassigned queue (or just `only_ids`), most urgent
    first. Returns [(case, analyst | None, reason)]."""
    out = []
    pool = unassigned(tenant, cases)
    if only_ids is not None:
        wanted = set(only_ids)
        pool = [c for c in pool if c["id"] in wanted]
    for c in sorted(pool, key=sla.remaining_hours):
        analyst = route(c, trigger=trigger, cases=cases)
        out.append((c, analyst, (c.get("routing") or {}).get("reason", "")))
    return out


def set_capacity(analyst, capacity):
    try:
        value = int(capacity)
    except (TypeError, ValueError):
        raise WorkflowError("Capacity must be a whole number.")
    if not 0 <= value <= vocab.CAPACITY_MAX:
        raise WorkflowError(f"Capacity must be between 0 and {vocab.CAPACITY_MAX}.")
    before = analyst.get("capacity")
    analyst["capacity"] = value
    return before, value

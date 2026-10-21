"""Scope schema, deterministic validation and normalization.

The agent proposes a scope; this module decides whether it is acceptable. It never trusts the agent for:
  * the denied-region list (derived: all regions - governed - extraAllowed)
  * whether a quoted 'explicit' requirement really appears in the SOW (quote must be found in the SOW text)
  * which SCPs / controls exist (closed catalogs)
"""
import copy
import re

from . import customscp
from .catalog import (CONTROL_CATALOG, MAX_CUSTOM_SCPS_PER_TARGET, SCP_CATALOG, SCP_MAX_CHARS, SECURITY_OU, STANDARD_OUS,
                      cid, scp_json)
from .regions import ALL_REGIONS

SCHEMA_VERSION = "1"
BASIS = ("explicit", "inferred", "default")
REQUIRED_EVIDENCE = ("regions.home", "regions.governed", "logging.retentionDays")
ACCOUNT_RE = re.compile(r"^\d{12}$")
OU_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$")
ACCOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")
ACCOUNT_KINDS = ("management", "log-archive", "audit", "workload", "other")
PROVISIONING = ("existing", "control-tower", "account-factory", "manual")
SHARED_KINDS = ("log-archive", "audit")
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"  # also used by the generated stacks
PAGE_CHARS = 30000


def norm_text(t):
    return re.sub(r"\s+", " ", str(t)).strip().lower()


def paginate(text, size=PAGE_CHARS):
    """Split on line boundaries into pages of <= size chars (a single longer line is hard-split)."""
    pages, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:
            if cur:
                pages.append(cur)
                cur = ""
            pages.append(line[:size])
            line = line[size:]
        if len(cur) + len(line) > size:
            pages.append(cur)
            cur = ""
        cur += line
    if cur:
        pages.append(cur)
    return pages or [""]


def _dict(d, key, errors, label=None):
    v = d.get(key)
    if v is None:
        d[key] = v = {}
    if not isinstance(v, dict):
        errors.append(f"{label or key} must be an object")
        d[key] = v = {}
    return v


def _list(d, key, errors, label):
    v = d.get(key, [])
    if v is None:
        v = []
    if not isinstance(v, list):
        errors.append(f"{label} must be a list")
        v = []
    d[key] = v
    return v


def validate(scope, sow_text=None):
    """Returns (normalized_scope, errors). errors == [] means acceptable."""
    errors = []
    if not isinstance(scope, dict):
        return {}, ["scope must be a JSON object"]
    s = copy.deepcopy(scope)
    sow = norm_text(sow_text) if sow_text is not None else None
    err = errors.append

    def evidence(label, basis, source):
        if basis not in BASIS:
            err(f"{label}: basis must be one of {list(BASIS)}")
        elif basis == "explicit":
            if not isinstance(source, str) or len(norm_text(source)) < 8:
                err(f"{label}: 'explicit' needs a verbatim SOW quote (>= 8 chars) in 'source'")
            elif sow is not None and norm_text(source) not in sow:
                err(f"{label}: quote not found in the SOW text: {source[:80]!r}")
        elif basis == "inferred" and not (isinstance(source, str) and source.strip()):
            err(f"{label}: 'inferred' needs 'source' explaining the inference")

    if s.get("schemaVersion") != SCHEMA_VERSION:
        err(f"schemaVersion must be {SCHEMA_VERSION!r}")

    # customer
    cust = _dict(s, "customer", errors)
    org = str(cust.get("orgName", "")).strip()
    if not org or len(org) > 50:
        err("customer.orgName is required (1-50 chars)")
    cust["orgName"] = org
    cust["orgSlug"] = re.sub(r"[^a-z0-9]+", "-", org.lower()).strip("-")[:40] or "customer"

    # regions
    r = _dict(s, "regions", errors)
    home = r.get("home")
    gov = _list(r, "governed", errors, "regions.governed")
    extra = _list(r, "extraAllowed", errors, "regions.extraAllowed")
    xdeny = _list(r, "explicitDeny", errors, "regions.explicitDeny")
    for label, vals in (("regions.governed", gov), ("regions.extraAllowed", extra), ("regions.explicitDeny", xdeny)):
        bad = [v for v in vals if v not in ALL_REGIONS]
        if bad:
            err(f"{label}: unknown regions {bad}")
    if home not in ALL_REGIONS:
        err("regions.home must be a valid region")
    if not gov:
        err("regions.governed must not be empty")
    elif home not in gov:
        err("regions.home must be included in regions.governed")
    conflict = set(xdeny) & (set(gov) | set(extra))
    if conflict:
        err(f"regions {sorted(conflict)} are both denied and governed/allowed; the SOW is contradictory, put it in openQuestions")
    enforce = r.get("enforceDeny", True)
    if not isinstance(enforce, bool):
        err("regions.enforceDeny must be true or false")
        enforce = True
    r["enforceDeny"] = enforce
    allowed = sorted(set(gov) | set(extra))
    r["governed"], r["extraAllowed"], r["explicitDeny"] = sorted(set(gov)), sorted(set(extra)), sorted(set(xdeny))
    r["allowed"] = allowed
    r["denied"] = sorted(set(ALL_REGIONS) - set(allowed))  # DERIVED, never taken from the agent

    # logging
    lg = _dict(s, "logging", errors)
    for key in ("retentionDays", "accessLogRetentionDays"):
        v = lg.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            err(f"logging.{key} must be an integer >= 1")
    for key in ("logArchiveAccountId", "auditAccountId"):
        v = str(lg.get(key, "") or "")
        if v and not ACCOUNT_RE.match(v):
            err(f"logging.{key} must be a 12-digit account id or empty")
        lg[key] = v
    lg["kmsKeyArn"] = str(lg.get("kmsKeyArn", "") or "")

    # evidence for key scalar decisions
    ev = _dict(s, "evidence", errors)
    for key in REQUIRED_EVIDENCE:
        e = ev.get(key)
        if not isinstance(e, dict):
            err(f"evidence.{key} is required: {{basis, source}}")
        else:
            evidence(f"evidence.{key}", e.get("basis"), e.get("source"))

    # OUs. Landing zone 4.0 no longer creates Security / Sandbox: the stacks do, so they are ordinary OUs here.
    ous = _list(s, "ous", errors, "ous")
    ou_names, seen_cid = [], set()
    for i, ou in enumerate(ous):
        if not isinstance(ou, dict):
            err(f"ous[{i}] must be an object")
            continue
        name = str(ou.get("name", "")).strip()
        ou["name"] = name
        if not OU_RE.match(name):
            err(f"ous[{i}].name invalid: {name!r}")
        elif name in ou_names:
            err(f"duplicate OU {name!r}")
        elif cid(name) in seen_cid:
            err(f"OU name {name!r} collides with another OU after normalization")
        else:
            ou_names.append(name)
            seen_cid.add(cid(name))
        evidence(f"ous[{i}] ({name})", ou.get("basis"), ou.get("source"))

    def _targets_of(items):
        return {t for it in items if isinstance(it, dict) and isinstance(it.get("targets"), list) for t in it["targets"]
                if isinstance(t, str)}

    referenced = (_targets_of(s.get("controls") or []) | _targets_of(s.get("scps") or []) | _targets_of(s.get("customScps") or [])
                  | {a["ou"] for a in (s.get("accounts") or []) if isinstance(a, dict) and isinstance(a.get("ou"), str)})
    for std in STANDARD_OUS:  # Security is always required; Sandbox when something refers to it
        if std not in ou_names and (std == SECURITY_OU or std in referenced):
            why = ("required: landing zone 4.0 service-integration accounts must sit in a Security OU directly under the root"
                   if std == SECURITY_OU else "referenced by a control, SCP or account in this scope")
            ous.append({"name": std, "basis": "default", "source": why})
            ou_names.append(std)
    # optional "parent": one level of nesting under a top-level OU; absent means directly under the root
    def _top(o):
        return isinstance(o, dict) and o.get("parent") in (None, "", "root")

    top_level = {o["name"] for o in ous if _top(o)}
    for i, ou in enumerate(ous):
        if not isinstance(ou, dict):
            continue
        parent = ou.get("parent")
        if parent in (None, "", "root"):
            ou.pop("parent", None)
            continue
        label = f"ous[{i}] ({ou['name']}).parent"
        if parent == ou["name"]:
            err(f"{label}: an OU cannot be its own parent")
        elif parent not in ou_names:
            err(f"{label}: unknown parent {parent!r}; it must be another OU listed under ous")
        elif parent not in top_level:
            err(f"{label}: {parent!r} is itself a child OU; only one level of nesting is supported, put the rest under 'unsupported'")
        elif parent == SECURITY_OU:
            err(f"{label}: the Security OU must hold only the shared accounts; use another parent")
    for o in ous:
        if o.get("name") == SECURITY_OU and o.get("parent"):
            err("the Security OU must be directly under the root (no parent)")
    ous.sort(key=lambda o: str(o.get("name", "")))
    ou_targets = set(ou_names)

    # accounts. Every account except the existing management account is created by the stacks from an email the customer
    # supplies as a variable / parameter (never taken from the SOW or the model). Log Archive and Audit are always present.
    accounts = _list(s, "accounts", errors, "accounts")
    acct_names = []
    for i, a in enumerate(accounts):
        if not isinstance(a, dict):
            err(f"accounts[{i}] must be an object")
            continue
        name = str(a.get("name", "")).strip()
        a["name"] = name
        if not ACCOUNT_NAME_RE.match(name):
            err(f"accounts[{i}].name invalid: {name!r}")
        elif name in acct_names:
            err(f"duplicate account {name!r}")
        else:
            acct_names.append(name)
        ou = a.get("ou")
        if not isinstance(ou, str) or (ou != "root" and ou not in ou_targets):
            err(f"accounts[{i}] ({name}).ou must be 'root' or an OU name from the scope, got {ou!r}")
        if a.get("kind") not in ACCOUNT_KINDS:
            err(f"accounts[{i}] ({name}).kind must be one of {list(ACCOUNT_KINDS)}")
        if a.get("provisioning") not in PROVISIONING:
            err(f"accounts[{i}] ({name}).provisioning must be one of {list(PROVISIONING)}")
        if a.get("kind") in SHARED_KINDS and ou != SECURITY_OU:
            err(f"accounts[{i}] ({name}): the {a.get('kind')} account must be in the {SECURITY_OU} OU")
        if a.get("kind") == "management" and (ou != "root" or a.get("provisioning") != "existing"):
            err(f"accounts[{i}] ({name}): the management account is existing and sits at the root")
        a["purpose"] = str(a.get("purpose", "") or "")[:200]
        evidence(f"accounts[{i}] ({name})", a.get("basis"), a.get("source"))
    for kind, label in (("log-archive", "log-archive"), ("audit", "audit")):
        found = [a for a in accounts if isinstance(a, dict) and a.get("kind") == kind]
        if len(found) > 1:
            err(f"only one {kind} account is allowed")
        elif not found:
            nm = f"{cust['orgSlug']}-{label}"
            accounts.append({"name": nm, "ou": SECURITY_OU, "kind": kind, "provisioning": "control-tower", "purpose": "",
                             "basis": "default", "source": "required by AWS Control Tower"})
            acct_names.append(nm)
    accounts.sort(key=lambda a: (str(a.get("ou")), str(a.get("name"))))

    # SCPs
    scps = _list(s, "scps", errors, "scps")
    ids = []
    for i, p in enumerate(scps):
        if not isinstance(p, dict):
            err(f"scps[{i}] must be an object")
            continue
        pid = p.get("id")
        if pid not in SCP_CATALOG:
            err(f"scps[{i}].id {pid!r} is not in the SCP catalog; put it under 'customScps'")
            continue
        if pid in ids:
            err(f"duplicate SCP {pid!r}")
        ids.append(pid)
        t = p.get("targets")
        if not isinstance(t, list) or not t:
            err(f"scps[{i}] ({pid}).targets must be a non-empty list")
            t = []
        for x in t:
            if x != "root" and x not in ou_targets:
                err(f"scps[{i}] ({pid}): unknown target {x!r} (use 'root' or an OU name)")
        p["targets"] = sorted(set(map(str, t)))
        evidence(f"scps[{i}] ({pid})", p.get("basis"), p.get("source"))
    if enforce and "deny-region" not in ids:
        scps.append({"id": "deny-region", "targets": ["root"], "basis": "default",
                     "source": "derived from regions.enforceDeny"})
    if not enforce and "deny-region" in ids:
        err("scps contains deny-region but regions.enforceDeny is false")
    scps.sort(key=lambda p: str(p.get("id", "")))
    per_target = {}
    for p in scps:
        for t in p.get("targets", []):
            per_target[t] = per_target.get(t, 0) + 1
    for t, n in per_target.items():
        if n > MAX_CUSTOM_SCPS_PER_TARGET:
            err(f"target {t!r} has {n} SCPs; the maximum is {MAX_CUSTOM_SCPS_PER_TARGET} (AWS limit of 5 includes FullAWSAccess and Control Tower's)")
    if not errors:
        for p in scps:
            if len(scp_json(p["id"], s)) > SCP_MAX_CHARS:
                err(f"SCP {p['id']} exceeds {SCP_MAX_CHARS} characters")

    # controls
    controls = _list(s, "controls", errors, "controls")
    cids = []
    for i, c in enumerate(controls):
        if not isinstance(c, dict):
            err(f"controls[{i}] must be an object")
            continue
        cc = c.get("id")
        if cc not in CONTROL_CATALOG:
            err(f"controls[{i}].id {cc!r} is not in the control catalog; put it under 'unsupported'")
            continue
        if cc in cids:
            err(f"duplicate control {cc!r}")
        cids.append(cc)
        t = c.get("targets")
        if not isinstance(t, list) or not t:
            err(f"controls[{i}] ({cc}).targets must be a non-empty list of OU names")
            t = []
        for x in t:
            if x not in ou_targets:
                err(f"controls[{i}] ({cc}): target {x!r} must be an OU name (not 'root')")
        c["targets"] = sorted(set(map(str, t)))
        evidence(f"controls[{i}] ({cc})", c.get("basis"), c.get("source"))
    controls.sort(key=lambda c: str(c.get("id", "")))

    # custom SCPs: agent-authored policy JSON, delivered for review in custom-scps/ and never applied by the stacks
    custom = _list(s, "customScps", errors, "customScps")
    seen_custom = []
    for i, e in enumerate(custom):
        norm, errs = customscp.validate_entry(e, f"customScps[{i}]", ou_targets, set(SCP_CATALOG), evidence)
        errors.extend(errs)
        if norm is not None:
            if norm["id"] in seen_custom:
                err(f"duplicate custom SCP {norm['id']!r}")
            seen_custom.append(norm["id"])
            custom[i] = norm
    if not errors:
        per_custom = {}
        for e in custom:
            for t in e["targets"]:
                per_custom[t] = per_custom.get(t, 0) + 1
        for e in custom:
            for t in e["targets"]:
                total = per_target.get(t, 0) + per_custom[t]
                if total > MAX_CUSTOM_SCPS_PER_TARGET:
                    e["warnings"].append(f"{t!r} would have {total} generated SCPs (catalog + custom); AWS allows 5 per target "
                                         "including FullAWSAccess and the ones Control Tower manages")
        custom.sort(key=lambda e: e["id"])

    # free-form reporting sections
    un = _list(s, "unsupported", errors, "unsupported")
    for i, u in enumerate(un):
        if not (isinstance(u, dict) and u.get("requirement") and u.get("reason")):
            err(f"unsupported[{i}] needs 'requirement' and 'reason'")
    for key in ("assumptions", "openQuestions"):
        v = _list(s, key, errors, key)
        if any(not isinstance(x, str) or not x.strip() for x in v):
            err(f"{key} must be a list of non-empty strings")

    missing = [f"email for account {a['name']}" for a in creatable_accounts(s)]
    s["status"] = "needs-input" if (missing or s["openQuestions"]) else "complete"
    s["missingRequired"] = missing
    s["summary"] = {"ous": len(ous), "accounts": len(accounts), "scps": len(scps), "controls": len(controls),
                    "customScps": len(custom), "controlAttachments": sum(len(c.get("targets", [])) for c in controls),
                    "governedRegions": len(r["governed"]), "deniedRegions": len(r["denied"]),
                    "unsupported": len(un), "openQuestions": len(s["openQuestions"])}
    return s, errors


_STOP = {"a", "an", "the", "for", "of", "to", "on", "in", "and", "or", "set", "detect", "whether", "disallow", "are", "is", "be",
         "with", "not", "no", "by", "from", "enabled", "access", "instances", "policy", "controls"}


def review_hints(scope):
    """Deterministic second look at a VALID scope. Returns hints for things the agent probably should have done differently.
    Hints never block saving; they are shown to the agent, which may fix the scope or keep it."""
    hints = []
    un = scope.get("unsupported", [])
    scp_like = [u for u in un if re.search(r"\bSCPs?\b|service control polic", f"{u['requirement']} {u['reason']}", re.I)]
    if scp_like:
        names = "; ".join(u["requirement"][:90] for u in scp_like[:8])
        hints.append(f"{len(scp_like)} item(s) under 'unsupported' look like SCP requirements ({names}). Anything the SOW wants as an SCP "
                     "that the SCP catalog cannot express belongs under 'customScps' (write the policy JSON and declare its inputs), not "
                     "'unsupported'. Move them, or keep one only if it is not an SCP and say why in its reason.")
    used = {c["id"] for c in scope.get("controls", [])}
    words = {}
    for cid_, (_, _, title) in CONTROL_CATALOG.items():
        for w in set(re.findall(r"[a-z0-9]+", title.lower())) - _STOP:
            words.setdefault(w, set()).add(cid_)
    text = " ".join(f"{u['requirement']} {u['reason']}" for u in un).lower()
    seen = set()
    for w, ids in sorted(words.items()):
        if len(w) >= 3 and len(ids) <= 2 and re.search(rf"\b{re.escape(w)}\b", text):
            for cid_ in sorted(ids - used - seen):
                seen.add(cid_)
                hints.append(f"'{w}' appears under 'unsupported' but the catalog has {cid_} ({CONTROL_CATALOG[cid_][2]}). "
                             "If it matches the SOW requirement, use it under 'controls' with the SOW quote.")
    return hints


def creatable_accounts(scope):
    """Accounts the generated stacks create from a customer-supplied email. The management account and anything marked
    existing are skipped; Log Archive / Audit are skipped when the customer supplies an existing account id."""
    given = {"log-archive": scope["logging"].get("logArchiveAccountId", ""), "audit": scope["logging"].get("auditAccountId", "")}
    return [a for a in scope.get("accounts", [])
            if a.get("kind") != "management" and a.get("provisioning") != "existing" and not given.get(a.get("kind"))]


def scope_markdown(s):
    r, lg = s["regions"], s["logging"]
    L = [f"# Scope: {s['customer']['orgName']}", "", f"Status: **{s['status']}**", ""]
    if s["missingRequired"]:
        L += [f"> Inputs needed before applying: {', '.join(s['missingRequired'])}. The stacks create these accounts from the emails.", ""]
    L += ["## Regions", f"- Home: `{r['home']}`", f"- Governed: {', '.join(r['governed'])}",
          f"- Allowed (governed + extra): {', '.join(r['allowed'])}",
          f"- Region deny SCP enforced: {r['enforceDeny']}", f"- Denied ({len(r['denied'])}): {', '.join(r['denied'])}", "",
          "## Logging", f"- Retention: {lg['retentionDays']} days (access logs {lg['accessLogRetentionDays']})",
          f"- Log archive account: {lg['logArchiveAccountId'] or 'created by the stacks from the email you provide'}",
          f"- Audit account: {lg['auditAccountId'] or 'created by the stacks from the email you provide'}",
          f"- KMS key: {lg['kmsKeyArn'] or 'Control Tower default'}", "", "## Organizational units (created by the stack)"]
    L += [f"- {o['name']}{' (under ' + o['parent'] + ')' if o.get('parent') else ''} [{o['basis']}]" for o in s["ous"]] or ["- none"]
    L += ["", "## Accounts (created by the stacks from an email you provide, except the management account)"]
    L += [f"- {a['name']}: {a['kind']}, in {a['ou']}{', existing' if a['provisioning'] == 'existing' else ''} [{a['basis']}]"
          for a in s.get("accounts", [])] or ["- none"]
    L += ["", "## Service control policies"]
    L += [f"- `{p['id']}` -> {', '.join(p['targets'])} [{p['basis']}]" for p in s["scps"]] or ["- none"]
    L += ["", "## Control Tower controls"]
    L += [f"- `{c['id']}` -> {', '.join(c['targets'])} [{c['basis']}]" for c in s["controls"]] or ["- none"]
    L += ["", "## Custom SCPs (AI-generated, review required; not applied by the stacks, see custom-scps/)"]
    L += [f"- `{e['id']}` -> {', '.join(e['targets'])}; inputs: {', '.join(i['name'] for i in e['inputs']) or 'none'} [{e['basis']}]"
          for e in s.get("customScps", [])] or ["- none"]
    L += ["", "## Not codified (requires other tooling or a decision)"]
    L += [f"- {u['requirement']}: {u['reason']}" for u in s["unsupported"]] or ["- none"]
    L += ["", "## Assumptions"] + ([f"- {a}" for a in s["assumptions"]] or ["- none"])
    L += ["", "## Open questions"] + ([f"- {q}" for q in s["openQuestions"]] or ["- none"])
    if s.get("reviewNotes"):
        L += ["", "## Review notes"] + [f"- {n}" for n in s["reviewNotes"]]
    return "\n".join(L) + "\n"

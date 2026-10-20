"""Scope schema, deterministic validation and normalization.

The agent proposes a scope; this module decides whether it is acceptable. It never trusts the agent for:
  * the denied-region list (derived: all regions - governed - extraAllowed)
  * whether a quoted 'explicit' requirement really appears in the SOW (quote must be found in the SOW text)
  * which catalog SCPs / controls exist (closed catalogs)
  * custom SCP documents: accepted only under customScps, size-limited, and never attached by the stacks
"""
import copy
import json
import re

from .catalog import CONTROL_CATALOG, CT_MANAGED_OUS, MAX_CUSTOM_SCPS_PER_TARGET, SCP_CATALOG, SCP_MAX_CHARS, cid, scp_json
from .regions import ALL_REGIONS

SCHEMA_VERSION = "1"
BASIS = ("explicit", "inferred", "default")
REQUIRED_EVIDENCE = ("regions.home", "regions.governed", "logging.retentionDays")
ACCOUNT_RE = re.compile(r"^\d{12}$")
OU_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$")
ACCOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")
CUSTOM_SCP_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
SCP_SID_RE = re.compile(r"^[A-Za-z0-9]+$")
_SCP_STMT_KEYS = {"Sid", "Effect", "Action", "NotAction", "Resource", "NotResource", "Condition"}
ACCOUNT_KINDS = ("management", "log-archive", "audit", "workload", "other")
PROVISIONING = ("existing", "control-tower", "account-factory", "manual")
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

    # OUs
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
        elif name in CT_MANAGED_OUS:
            err(f"OU {name!r} is created by Control Tower; do not list it under ous (it can still be a target)")
        elif name in ou_names:
            err(f"duplicate OU {name!r}")
        elif cid(name) in seen_cid:
            err(f"OU name {name!r} collides with another OU after normalization")
        else:
            ou_names.append(name)
            seen_cid.add(cid(name))
        evidence(f"ous[{i}] ({name})", ou.get("basis"), ou.get("source"))
    # optional "parent": one level of nesting under a top-level custom OU; absent means directly under the root
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
        elif parent in CT_MANAGED_OUS:
            err(f"{label}: {parent!r} is created by Control Tower and cannot be a parent")
        elif parent not in ou_names:
            err(f"{label}: unknown parent {parent!r}; it must be another OU listed under ous")
        elif parent not in top_level:
            err(f"{label}: {parent!r} is itself a child OU; only one level of nesting is supported, put the rest under 'unsupported'")
    ous.sort(key=lambda o: str(o.get("name", "")))
    ou_targets = set(ou_names) | set(CT_MANAGED_OUS)

    # accounts: documentation and diagram only. The stacks never create or move accounts.
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
            err(f"accounts[{i}] ({name}).ou must be 'root' or an OU name from the scope (or Security / Sandbox), got {ou!r}")
        if a.get("kind") not in ACCOUNT_KINDS:
            err(f"accounts[{i}] ({name}).kind must be one of {list(ACCOUNT_KINDS)}")
        if a.get("provisioning") not in PROVISIONING:
            err(f"accounts[{i}] ({name}).provisioning must be one of {list(PROVISIONING)}")
        a["purpose"] = str(a.get("purpose", "") or "")[:200]
        evidence(f"accounts[{i}] ({name})", a.get("basis"), a.get("source"))
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
            err(f"scps[{i}].id {pid!r} is not in the SCP catalog; author it under customScps, or put a non-SCP requirement under 'unsupported'")
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

    # Model-authored SCPs. Validated here, rendered only under custom-scps/, never attached by the stacks.
    custom = _list(s, "customScps", errors, "customScps")
    custom_ids = []
    for i, p in enumerate(custom):
        if not isinstance(p, dict):
            err(f"customScps[{i}] must be an object")
            continue
        pid = str(p.get("id", "")).strip()
        p["id"] = pid
        label = f"customScps[{i}] ({pid or '?'})"
        if not CUSTOM_SCP_ID_RE.match(pid):
            err(f"{label}.id must be a slug (lowercase, digits, hyphens, <= 41 chars)")
        elif pid in SCP_CATALOG:
            err(f"{label}.id is a catalog SCP; put catalog policies under scps")
        elif pid in custom_ids:
            err(f"duplicate custom SCP {pid!r}")
        else:
            custom_ids.append(pid)
        title = str(p.get("title", "")).strip()
        p["title"] = title
        if not title or len(title) > 80:
            err(f"{label}.title is required (1-80 chars)")
        t = p.get("targets")
        if not isinstance(t, list) or not t:
            err(f"{label}.targets must be a non-empty list")
            t = []
        for x in t:
            if x != "root" and x not in ou_targets:
                err(f"{label}: unknown target {x!r} (use 'root' or an OU name)")
        p["targets"] = sorted(set(map(str, t)))
        _scp_document(p.get("document"), label, errors)
        if isinstance(p.get("document"), dict) and isinstance(p["document"].get("Statement"), dict):
            p["document"]["Statement"] = [p["document"]["Statement"]]
        if isinstance(p.get("document"), dict):
            compact = json.dumps(p["document"], separators=(",", ":"))
            if len(compact) > SCP_MAX_CHARS:
                err(f"{label} document exceeds {SCP_MAX_CHARS} characters")
        evidence(label, p.get("basis"), p.get("source"))
    custom[:] = [p for p in custom if isinstance(p, dict)]
    custom.sort(key=lambda p: str(p.get("id", "")))

    # Catalog policies are attached by the stacks, so they alone must fit the Organizations quota.
    # Model-authored policies are not attached; crossing the quota with them is a warning, not a rejection.
    def _tally(policies):
        counts = {}
        for p in policies:
            if not isinstance(p, dict):
                continue
            for t in p.get("targets", []):
                counts[t] = counts.get(t, 0) + 1
        return counts

    catalog_counts, custom_counts = _tally(scps), _tally(custom)
    for t, n in catalog_counts.items():
        if n > MAX_CUSTOM_SCPS_PER_TARGET:
            err(f"target {t!r} has {n} catalog SCPs; the maximum is {MAX_CUSTOM_SCPS_PER_TARGET} (AWS limit of 5 includes FullAWSAccess and Control Tower's)")
    warnings = []
    for t, n in custom_counts.items():
        attached = catalog_counts.get(t, 0)
        if attached + n > MAX_CUSTOM_SCPS_PER_TARGET:
            warnings.append(
                f"target {t!r} has {n} model-authored SCP(s) and {attached} catalog SCP(s). "
                f"The stacks attach only the catalog policies. Attaching the model-authored files as well "
                f"would exceed {MAX_CUSTOM_SCPS_PER_TARGET} custom SCPs on that target.")
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

    # free-form reporting sections
    un = _list(s, "unsupported", errors, "unsupported")
    for i, u in enumerate(un):
        if not (isinstance(u, dict) and u.get("requirement") and u.get("reason")):
            err(f"unsupported[{i}] needs 'requirement' and 'reason'")
    for key in ("assumptions", "openQuestions"):
        v = _list(s, key, errors, key)
        if any(not isinstance(x, str) or not x.strip() for x in v):
            err(f"{key} must be a list of non-empty strings")

    missing = [k for k in ("logArchiveAccountId", "auditAccountId") if not lg.get(k)]
    s["status"] = "needs-input" if (missing or s["openQuestions"]) else "complete"
    s["missingRequired"] = missing
    s["warnings"] = warnings
    s["summary"] = {"ous": len(ous), "accounts": len(accounts), "scps": len(scps), "customScps": len(custom),
                    "controls": len(controls),
                    "controlAttachments": sum(len(c.get("targets", [])) for c in controls),
                    "governedRegions": len(r["governed"]), "deniedRegions": len(r["denied"]),
                    "unsupported": len(un), "openQuestions": len(s["openQuestions"]), "warnings": len(warnings)}
    return s, errors


def _str_or_strs(value):
    if isinstance(value, str):
        return bool(value)
    return isinstance(value, list) and len(value) > 0 and all(isinstance(x, str) and x for x in value)


def _scp_document(doc, label, errors):
    """A model-authored SCP must be an IAM policy document. Returns nothing; appends to errors."""
    if not isinstance(doc, dict):
        errors.append(f"{label}.document must be an IAM policy object")
        return
    if doc.get("Version") != "2012-10-17":
        errors.append(f"{label}.document.Version must be '2012-10-17'")
    extra = set(doc) - {"Version", "Id", "Statement"}
    if extra:
        errors.append(f"{label}.document has unsupported keys {sorted(extra)}")
    stmts = doc.get("Statement")
    if isinstance(stmts, dict):
        stmts = [stmts]
    if not isinstance(stmts, list) or not stmts:
        errors.append(f"{label}.document.Statement must be a non-empty list")
        return
    for i, st in enumerate(stmts):
        where = f"{label}.document.Statement[{i}]"
        if not isinstance(st, dict):
            errors.append(f"{where} must be an object")
            continue
        unknown = set(st) - _SCP_STMT_KEYS
        if "Principal" in st or "NotPrincipal" in st:
            errors.append(f"{where}: SCPs cannot set Principal")
            unknown -= {"Principal", "NotPrincipal"}
        if unknown:
            errors.append(f"{where} has unsupported keys {sorted(unknown)}")
        if st.get("Effect") not in ("Allow", "Deny"):
            errors.append(f"{where}.Effect must be Allow or Deny")
        if "Action" not in st and "NotAction" not in st:
            errors.append(f"{where} needs Action or NotAction")
        for key in ("Action", "NotAction", "Resource", "NotResource"):
            if key in st and not _str_or_strs(st[key]):
                errors.append(f"{where}.{key} must be a string or a list of strings")
        if "Resource" not in st and "NotResource" not in st:
            errors.append(f"{where} needs Resource or NotResource")
        if "Sid" in st and not (isinstance(st["Sid"], str) and SCP_SID_RE.match(st["Sid"])):
            errors.append(f"{where}.Sid must be alphanumeric")
        if "Condition" in st and not isinstance(st["Condition"], dict):
            errors.append(f"{where}.Condition must be an object")


def scope_markdown(s):
    r, lg = s["regions"], s["logging"]
    L = [f"# Scope: {s['customer']['orgName']}", "", f"Status: **{s['status']}**", ""]
    if s["missingRequired"]:
        L += [f"> Missing required input: {', '.join(s['missingRequired'])} (Control Tower API launch needs existing accounts).", ""]
    L += ["## Regions", f"- Home: `{r['home']}`", f"- Governed: {', '.join(r['governed'])}",
          f"- Allowed (governed + extra): {', '.join(r['allowed'])}",
          f"- Region deny SCP enforced: {r['enforceDeny']}", f"- Denied ({len(r['denied'])}): {', '.join(r['denied'])}", "",
          "## Logging", f"- Retention: {lg['retentionDays']} days (access logs {lg['accessLogRetentionDays']})",
          f"- Log archive account: {lg['logArchiveAccountId'] or 'NOT PROVIDED'}",
          f"- Audit account: {lg['auditAccountId'] or 'NOT PROVIDED'}",
          f"- KMS key: {lg['kmsKeyArn'] or 'Control Tower default'}", "", "## Organizational units (created by the stack)"]
    L += [f"- {o['name']}{' (under ' + o['parent'] + ')' if o.get('parent') else ''} [{o['basis']}]" for o in s["ous"]] or ["- none"]
    L += ["", "## Accounts (for context: the stacks do not create or move accounts)"]
    L += [f"- {a['name']}: {a['kind']}, {a['provisioning']}, in {a['ou']} [{a['basis']}]" for a in s.get("accounts", [])] or ["- none"]
    L += ["", "## Service control policies (applied by the stacks)"]
    L += [f"- `{p['id']}` -> {', '.join(p['targets'])} [{p['basis']}]" for p in s["scps"]] or ["- none"]
    L += ["", "## Custom SCPs (model-authored, delivered in custom-scps/, not applied by the stacks)"]
    L += [f"- `{p['id']}` {p.get('title', '')} -> {', '.join(p['targets'])} [{p['basis']}]" for p in s.get("customScps", [])] or ["- none"]
    L += ["", "## Control Tower controls"]
    L += [f"- `{c['id']}` -> {', '.join(c['targets'])} [{c['basis']}]" for c in s["controls"]] or ["- none"]
    L += ["", "## Not codified (requires other tooling or a decision)"]
    L += [f"- {u['requirement']}: {u['reason']}" for u in s["unsupported"]] or ["- none"]
    L += ["", "## Assumptions"] + ([f"- {a}" for a in s["assumptions"]] or ["- none"])
    L += ["", "## Open questions"] + ([f"- {q}" for q in s["openQuestions"]] or ["- none"])
    if s.get("warnings"):
        L += ["", "## Warnings"] + [f"- {w}" for w in s["warnings"]]
    return "\n".join(L) + "\n"

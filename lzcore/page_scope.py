"""Turn one SOW page at a time into a scope.

The model never holds more than the page it is reading. Each page is checked here, saved by the caller, and merged in
code. A summary of earlier pages is not a substitute: explicit quotes have to be a real slice of the page.
"""
import json
import re

from .catalog import CONTROL_CATALOG, SCP_CATALOG
from .customscp import ID_RE
from .regions import ALL_REGIONS
from .scope import (ACCOUNT_KINDS, ACCOUNT_NAME_RE, ACCOUNT_RE, OU_RE, PROVISIONING, norm_text, review_hints, validate)

_ALLOWED = {"scalars", "ous", "accounts", "scps", "controls", "customScpRequests", "unsupported", "assumptions", "openQuestions"}
_LISTS = ("ous", "accounts", "scps", "controls", "customScpRequests", "unsupported")
_SCALAR_KIND = {
    "customer.orgName": "str",
    "regions.home": "region",
    "regions.governed": "regions",
    "regions.extraAllowed": "regions",
    "regions.explicitDeny": "regions",
    "regions.enforceDeny": "bool",
    "logging.retentionDays": "int",
    "logging.accessLogRetentionDays": "int",
    "logging.logArchiveAccountId": "account",
    "logging.auditAccountId": "account",
    "logging.kmsKeyArn": "str",
}
_EVIDENCE_KEYS = ("regions.home", "regions.governed", "logging.retentionDays")


def parse_json_object(text):
    """Parse a JSON object from a model reply. Strips a ```json fence and ignores prose around the object."""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        raise ValueError("expected a JSON object")
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        value = json.loads(s)
    except ValueError:
        start, end = s.find("{"), s.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(s[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _email(obj):
    if isinstance(obj, str):
        return "@" in obj
    if isinstance(obj, dict):
        return any(_email(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_email(v) for v in obj)
    return False


def _dot_leader_quote(quote: str) -> bool:
    """PDF/TOC lines made of dots and spaces are not valid evidence."""
    compact = quote.strip()
    if len(compact) < 8:
        return False
    alnum = sum(1 for c in compact if c.isalnum())
    return alnum < 8


def _locate_quote(quote: str, page_text: str, hint_start: int | None) -> tuple[int, int] | None:
    """Return (start, end) when quote appears verbatim on the page."""
    if quote not in page_text:
        return None
    hits: list[int] = []
    pos = 0
    while True:
        i = page_text.find(quote, pos)
        if i < 0:
            break
        hits.append(i)
        pos = i + 1
    if not hits:
        return None
    if len(hits) == 1:
        s = hits[0]
        return s, s + len(quote)
    if isinstance(hint_start, int):
        s = min(hits, key=lambda h: abs(h - hint_start))
        return s, s + len(quote)
    return None


def _span(label, item, page_text):
    """Explicit quotes must equal page_text[start:end]. Inferred items need that span plus a reason."""
    basis = item.get("basis")
    if basis not in ("explicit", "inferred"):
        return None, f"{label}: basis must be 'explicit' or 'inferred'"
    if basis == "explicit":
        quote, reason = item.get("source"), None
    else:
        quote, reason = item.get("quote"), item.get("source")
        if not isinstance(reason, str) or not reason.strip():
            return None, f"{label}: inferred needs source explaining the inference"
    if not isinstance(quote, str):
        return None, f"{label}: needs a verbatim quote from this page"
    if _dot_leader_quote(quote):
        return None, (
            f"{label}: quote looks like table-of-contents filler (mostly dots/spaces); "
            "omit this field or cite real text from this page"
        )
    start, end = item.get("start"), item.get("end")
    hint = start if isinstance(start, int) else None
    if type(start) is not int or type(end) is not int or not (0 <= start < end <= len(page_text)):
        loc = _locate_quote(quote, page_text, hint)
        if loc is None:
            return None, f"{label}: start and end must be integer offsets into this page"
        start, end = loc
    elif page_text[start:end] != quote:
        loc = _locate_quote(quote, page_text, start)
        if loc is None:
            got = page_text[start:end]
            return None, (
                f"{label}: page[{start}:{end}] is {got[:80]!r}, not the quote; "
                "source must be a verbatim substring of this page"
            )
        start, end = loc
    if page_text[start:end] != quote:
        return None, f"{label}: source must match page[start:end] exactly (including newlines)"
    if len(norm_text(quote)) < 8:
        return None, f"{label}: quote must be at least 8 characters"
    source = quote if basis == "explicit" else f"{reason.strip()} (sow: {quote})"
    return {"basis": basis, "source": source}, None


def _value(label, kind, value):
    if kind == "str":
        if not isinstance(value, str) or not value.strip():
            return None, f"{label} must be a non-empty string"
        return value.strip(), None
    if kind == "region":
        if value not in ALL_REGIONS:
            return None, f"{label} must be a region code, got {value!r}"
        return value, None
    if kind == "regions":
        if not isinstance(value, list) or not value:
            return None, f"{label} must be a non-empty list of region codes"
        bad = [v for v in value if v not in ALL_REGIONS]
        if bad:
            return None, f"{label}: unknown regions {bad}"
        return sorted(set(value)), None
    if kind == "bool":
        if type(value) is not bool:
            return None, f"{label} must be true or false"
        return value, None
    if kind == "int":
        if type(value) is not int or value < 1:
            return None, f"{label} must be an integer >= 1"
        return value, None
    if kind == "account":
        if not isinstance(value, str) or not ACCOUNT_RE.match(value):
            return None, f"{label} must be a 12-digit account id"
        return value, None
    return None, f"{label}: unsupported kind"


def _as_list(raw, key, errors):
    value = raw.get(key) or []
    if not isinstance(value, list):
        errors.append(f"{key} must be a list")
        return []
    return value


def _targets(label, item, allow_root):
    t = item.get("targets")
    if not isinstance(t, list) or not t or not all(isinstance(x, str) and x.strip() for x in t):
        return None, f"{label}.targets must be a non-empty list of names"
    t = sorted(set(x.strip() for x in t))
    if not allow_root and "root" in t:
        return None, f"{label}: targets must be OU names, not 'root'"
    return t, None


def accept_page(raw, page_text):
    """Returns (finding, errors). errors == [] means every quote on this page is a real slice of page_text."""
    errors = []
    try:
        raw = parse_json_object(raw)
    except ValueError as e:
        return None, [f"invalid JSON: {e}"]
    extra = set(raw) - _ALLOWED
    if extra:
        errors.append(f"unknown keys {sorted(extra)}; this call records one page, not a finished scope")
    if _email(raw):
        errors.append("do not put an email address in the scope")

    finding = {key: [] for key in _LISTS}
    finding["scalars"] = {}
    finding["assumptions"] = []
    finding["openQuestions"] = []

    scalars = raw.get("scalars") or {}
    if not isinstance(scalars, dict):
        errors.append("scalars must be an object")
        scalars = {}
    for key, item in scalars.items():
        if key not in _SCALAR_KIND:
            errors.append(f"unknown scalar {key}")
            continue
        if not isinstance(item, dict) or "value" not in item:
            errors.append(f"scalars.{key} must be an object with value, basis, source, start, end")
            continue
        ev, err = _span(f"scalars.{key}", item, page_text)
        if err:
            errors.append(err)
            continue
        value, err = _value(f"scalars.{key}", _SCALAR_KIND[key], item.get("value"))
        if err:
            errors.append(err)
            continue
        finding["scalars"][key] = {"value": value, **ev}

    def add(key, row):
        finding[key].append(row)

    for i, item in enumerate(_as_list(raw, "ous", errors)):
        label = f"ous[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        ev, err = _span(label, item, page_text)
        if err:
            errors.append(err)
            continue
        name = str(item.get("name", "")).strip()
        if not OU_RE.match(name):
            errors.append(f"{label}.name invalid: {name!r}")
            continue
        row = {"name": name, **ev}
        parent = item.get("parent")
        if parent not in (None, "", "root"):
            if not isinstance(parent, str) or not OU_RE.match(parent.strip()):
                errors.append(f"{label}.parent invalid: {parent!r}")
                continue
            row["parent"] = parent.strip()
        add("ous", row)

    for i, item in enumerate(_as_list(raw, "accounts", errors)):
        label = f"accounts[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        ev, err = _span(label, item, page_text)
        if err:
            errors.append(err)
            continue
        name = str(item.get("name", "")).strip()
        if not ACCOUNT_NAME_RE.match(name):
            errors.append(f"{label}.name invalid: {name!r}")
            continue
        if item.get("kind") not in ACCOUNT_KINDS:
            errors.append(f"{label}.kind must be one of {list(ACCOUNT_KINDS)}")
            continue
        if item.get("provisioning") not in PROVISIONING:
            errors.append(f"{label}.provisioning must be one of {list(PROVISIONING)}")
            continue
        ou = item.get("ou")
        if not isinstance(ou, str) or (ou != "root" and not OU_RE.match(ou)):
            errors.append(f"{label}.ou invalid: {ou!r}")
            continue
        add("accounts", {"name": name, "ou": ou, "kind": item["kind"], "provisioning": item["provisioning"],
                         "purpose": str(item.get("purpose", "") or "")[:200], **ev})

    for i, item in enumerate(_as_list(raw, "scps", errors)):
        label = f"scps[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        ev, err = _span(label, item, page_text)
        if err:
            errors.append(err)
            continue
        if item.get("id") not in SCP_CATALOG:
            errors.append(f"{label}.id {item.get('id')!r} is not in the SCP catalog; use customScpRequests")
            continue
        targets, err = _targets(label, item, allow_root=True)
        if err:
            errors.append(err)
            continue
        add("scps", {"id": item["id"], "targets": targets, **ev})

    for i, item in enumerate(_as_list(raw, "controls", errors)):
        label = f"controls[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        ev, err = _span(label, item, page_text)
        if err:
            errors.append(err)
            continue
        if item.get("id") not in CONTROL_CATALOG:
            errors.append(f"{label}.id {item.get('id')!r} is not in the control catalog; use unsupported")
            continue
        targets, err = _targets(label, item, allow_root=False)
        if err:
            errors.append(err)
            continue
        add("controls", {"id": item["id"], "targets": targets, **ev})

    for i, item in enumerate(_as_list(raw, "customScpRequests", errors)):
        label = f"customScpRequests[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        if "policy" in item or "inputs" in item:
            errors.append(f"{label}: record the requirement only; the policy JSON is written after every page is merged")
            continue
        ev, err = _span(label, item, page_text)
        if err:
            errors.append(err)
            continue
        cid_ = item.get("id")
        if not isinstance(cid_, str) or not ID_RE.match(cid_):
            errors.append(f"{label}.id must be a lowercase hyphenated id")
            continue
        if cid_ in SCP_CATALOG:
            errors.append(f"{label}.id {cid_!r} is a catalog SCP; use scps")
            continue
        title = str(item.get("title", "") or "").strip()
        requirement = str(item.get("requirement", "") or "").strip()
        if not title or not requirement:
            errors.append(f"{label} needs title and requirement")
            continue
        targets, err = _targets(label, item, allow_root=True)
        if err:
            errors.append(err)
            continue
        add("customScpRequests", {"id": cid_, "title": title, "description": str(item.get("description", "") or "")[:600],
                                  "requirement": requirement, "targets": targets, **ev})

    for i, item in enumerate(_as_list(raw, "unsupported", errors)):
        label = f"unsupported[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        ev, err = _span(label, item, page_text)
        if err:
            errors.append(err)
            continue
        requirement = str(item.get("requirement", "") or "").strip()
        reason = str(item.get("reason", "") or "").strip()
        if not requirement or not reason:
            errors.append(f"{label} needs requirement and reason")
            continue
        add("unsupported", {"requirement": requirement, "reason": reason, **ev})

    for key in ("assumptions", "openQuestions"):
        vals = raw.get(key) or []
        if not isinstance(vals, list) or any(not isinstance(x, str) or not x.strip() for x in vals):
            errors.append(f"{key} must be a list of non-empty strings")
            continue
        finding[key] = [x.strip() for x in vals]

    for key, field in (("ous", "name"), ("accounts", "name"), ("scps", "id"), ("controls", "id"), ("customScpRequests", "id")):
        seen = []
        for row in finding[key]:
            if row[field] in seen:
                errors.append(f"duplicate {key} {row[field]!r} on this page")
            seen.append(row[field])

    if errors:
        return None, errors
    return finding, []


def _canon(value):
    if isinstance(value, list):
        return tuple(sorted(value))
    return value


def _prefer(old, new):
    if new.get("basis") == "explicit" and old.get("basis") != "explicit":
        return new
    return old


def scope_from_findings(findings):
    """Merge checked page findings. Conflicting values are errors. Nothing is filled in from a prompt example."""
    errors = []
    chosen = {}
    for finding in findings:
        page = finding.get("page")
        for key, item in (finding.get("scalars") or {}).items():
            if key not in chosen:
                chosen[key] = item
                continue
            if _canon(chosen[key]["value"]) != _canon(item["value"]):
                errors.append(f"{key} conflicts: page {chosen[key].get('page', page)} has {chosen[key]['value']!r}, "
                              f"page {page} has {item['value']!r}")
            else:
                chosen[key] = _prefer(chosen[key], item)
        for key, item in (finding.get("scalars") or {}).items():
            item.setdefault("page", page)

    if "customer.orgName" not in chosen:
        errors.append("customer.orgName was not stated on any page")
    if "regions.home" not in chosen:
        errors.append("regions.home was not stated on any page")
    if "logging.retentionDays" not in chosen:
        errors.append("logging.retentionDays was not stated on any page")
    if errors:
        return None, errors

    if "regions.governed" not in chosen:
        home = chosen["regions.home"]
        chosen["regions.governed"] = {"value": [home["value"]], "basis": home["basis"], "source": home["source"]}
    elif chosen["regions.home"]["value"] not in chosen["regions.governed"]["value"]:
        chosen["regions.governed"]["value"] = sorted(set(chosen["regions.governed"]["value"]) | {chosen["regions.home"]["value"]})

    assumptions, open_questions = [], []
    logging = {
        "retentionDays": chosen["logging.retentionDays"]["value"],
        "accessLogRetentionDays": chosen["logging.retentionDays"]["value"],
        "logArchiveAccountId": "", "auditAccountId": "", "kmsKeyArn": "",
    }
    if "logging.accessLogRetentionDays" in chosen:
        logging["accessLogRetentionDays"] = chosen["logging.accessLogRetentionDays"]["value"]
    else:
        assumptions.append("Access-log retention was not stated; it is set equal to the log retention quoted in the statement of work.")
    for key, field in (("logging.logArchiveAccountId", "logArchiveAccountId"), ("logging.auditAccountId", "auditAccountId"),
                       ("logging.kmsKeyArn", "kmsKeyArn")):
        if key in chosen:
            logging[field] = chosen[key]["value"]

    def rows(key):
        out = []
        for finding in findings:
            out.extend(finding.get(key) or [])
        return out

    def merge_named(key, field, conflict_on):
        merged = {}
        for row in rows(key):
            name = row[field]
            if name not in merged:
                merged[name] = dict(row)
                continue
            for part in conflict_on:
                if (merged[name].get(part) or None) != (row.get(part) or None):
                    errors.append(f"{key} {name!r} conflicts on {part}")
            if key in ("scps", "controls", "customScpRequests"):
                merged[name]["targets"] = sorted(set(merged[name]["targets"]) | set(row["targets"]))
            merged[name] = _prefer(merged[name], {**row, "targets": merged[name].get("targets", row.get("targets"))})
        return list(merged.values())

    ous = merge_named("ous", "name", ("parent",))
    accounts = merge_named("accounts", "name", ("ou", "kind", "provisioning"))
    scps = merge_named("scps", "id", ())
    controls = merge_named("controls", "id", ())
    custom = merge_named("customScpRequests", "id", ("requirement",))
    unsupported = []
    seen_un = set()
    for row in rows("unsupported"):
        k = norm_text(row["requirement"])
        if k in seen_un:
            continue
        seen_un.add(k)
        unsupported.append(row)
    for finding in findings:
        for text in finding.get("assumptions") or []:
            if text not in assumptions:
                assumptions.append(text)
        for text in finding.get("openQuestions") or []:
            if text not in open_questions:
                open_questions.append(text)
    if errors:
        return None, errors

    def emit(row, fields):
        out = {k: row[k] for k in fields if k in row and row[k] not in (None, "")}
        out["basis"] = row["basis"]
        out["source"] = row["source"]
        return out

    evidence = {key: {"basis": chosen[key]["basis"], "source": chosen[key]["source"]} for key in _EVIDENCE_KEYS}
    scope = {
        "schemaVersion": "1",
        "customer": {"orgName": chosen["customer.orgName"]["value"]},
        "regions": {
            "home": chosen["regions.home"]["value"],
            "governed": list(chosen["regions.governed"]["value"]),
            "extraAllowed": list(chosen.get("regions.extraAllowed", {}).get("value") or []),
            "explicitDeny": list(chosen.get("regions.explicitDeny", {}).get("value") or []),
            "enforceDeny": chosen["regions.enforceDeny"]["value"] if "regions.enforceDeny" in chosen else True,
        },
        "logging": logging,
        "evidence": evidence,
        "ous": [emit(o, ("name", "parent")) for o in ous],
        "accounts": [emit(a, ("name", "ou", "kind", "provisioning", "purpose")) for a in accounts],
        "scps": [emit(p, ("id", "targets")) for p in scps],
        "controls": [emit(c, ("id", "targets")) for c in controls],
        "customScpRequests": [emit(c, ("id", "title", "description", "requirement", "targets")) for c in custom],
        "unsupported": [emit(u, ("requirement", "reason")) for u in unsupported],
        "assumptions": assumptions,
        "openQuestions": open_questions,
    }
    return scope, []


def accept_custom_policies(raw, requests):
    """Keep the page's quote and targets. The model supplies only the policy JSON and its declared inputs."""
    try:
        raw = parse_json_object(raw)
    except ValueError as e:
        return None, [f"invalid JSON: {e}"]
    entries = raw.get("customScps") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return None, ["customScps must be a list"]
    by_id = {r["id"]: r for r in requests}
    seen, out, errors = [], [], []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"customScps[{i}] must be an object")
            continue
        cid_ = entry.get("id")
        req = by_id.get(cid_)
        if req is None:
            errors.append(f"customScps[{i}].id {cid_!r} was not requested by a page")
            continue
        if cid_ in seen:
            errors.append(f"duplicate custom SCP {cid_}")
            continue
        seen.append(cid_)
        out.append({"id": req["id"], "title": req["title"], "description": req.get("description") or req["requirement"],
                    "targets": list(req["targets"]), "policy": entry.get("policy"), "inputs": entry.get("inputs") or [],
                    "basis": req["basis"], "source": req["source"]})
    missing = [r["id"] for r in requests if r["id"] not in seen]
    if missing:
        errors.append(f"missing custom SCP policy for {missing}")
    if errors:
        return None, errors
    return out, []


def run_intake(pages, load_page, save_page, ask_page, sow_text, ask_custom=None, attempts=3):
    """Read each page with a fresh model call. A page that is already saved is not sent again.

    ask_page(page_number, page_text, errors) returns ("ok", finding) when the tool already checked the page,
    or ("raw", text) when the reply still has to be parsed. ask_custom(requests, errors) returns policy JSON.
    """
    findings = []
    for number, page_text in enumerate(pages, 1):
        saved = load_page(number)
        if not (isinstance(saved, dict) and "scalars" in saved):
            errors = []
            saved = None
            for _ in range(attempts):
                kind, payload = ask_page(number, page_text, errors)
                if kind == "ok":
                    saved, errors = payload, []
                else:
                    saved, errors = accept_page(payload, page_text)
                if not errors:
                    save_page(number, saved)
                    break
            if errors:
                return None, [f"page {number}: {e}" for e in errors]
        stamped = dict(saved)
        stamped["page"] = number
        findings.append(stamped)

    scope, errors = scope_from_findings(findings)
    if errors:
        return None, errors
    requests = scope.pop("customScpRequests")
    draft, errors = validate(scope, sow_text)
    if errors:
        return None, errors
    if requests:
        if ask_custom is None:
            return None, ["custom SCP requests need a policy writer"]
        c_errors = []
        for _ in range(attempts):
            policies, c_errors = accept_custom_policies(ask_custom(requests, c_errors), requests)
            if c_errors:
                continue
            draft, c_errors = validate({**draft, "customScps": policies}, sow_text)
            if not c_errors:
                break
        if c_errors:
            return None, c_errors
    notes = review_hints(draft)
    if notes:
        draft = {**draft, "reviewNotes": notes}
    return draft, []

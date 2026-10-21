"""Agent-authored custom SCPs, kept apart from the closed catalog.

The catalog (catalog.py) is code we wrote and tested. A custom SCP is JSON the LLM wrote from the SOW, so it is:
  * validated structurally here (shape, size, Deny-only, declared inputs),
  * delivered as REVIEW artifacts in custom-scps/ of both bundles, never applied by the generated stacks,
  * labelled AI-generated, with the inputs a human must fill in before use.
Nothing here proves a policy does what the SOW wants: a person must review it and test it on a non-production account.
"""
import hashlib
import json
import re

SCP_MAX_CHARS = 5120
ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,60}$")
INPUT_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
STATEMENT_KEYS = {"Sid", "Effect", "Action", "NotAction", "Resource", "NotResource", "Condition"}
SID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
ACCOUNT_ID_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
LITERAL_ROLE_RE = re.compile(r"role/([A-Za-z0-9+=,.@_-]+)")


def policy_text(policy):
    return json.dumps(policy, separators=(",", ":"), sort_keys=True)


def _strings(value):
    """A policy element that must be a non-empty string or a non-empty list of strings. Returns an error or None."""
    if isinstance(value, str) and value.strip():
        return None
    if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        return None
    return "must be a non-empty string or a list of strings"


def validate_policy(policy):
    """Returns (errors, warnings) for an SCP policy document (a dict)."""
    errors, warnings = [], []
    if not isinstance(policy, dict):
        return ["policy must be a JSON object"], warnings
    if policy.get("Version") != "2012-10-17":
        errors.append("policy.Version must be '2012-10-17'")
    extra = set(policy) - {"Version", "Statement", "Id"}
    if extra:
        errors.append(f"policy has unsupported top-level keys {sorted(extra)}")
    stmts = policy.get("Statement")
    if not isinstance(stmts, list) or not stmts:
        return errors + ["policy.Statement must be a non-empty list"], warnings
    for i, st in enumerate(stmts):
        where = f"Statement[{i}]"
        if not isinstance(st, dict):
            errors.append(f"{where} must be an object")
            continue
        bad = set(st) - STATEMENT_KEYS
        if bad:
            errors.append(f"{where}: unsupported keys {sorted(bad)} (SCPs have no Principal)")
        if st.get("Effect") != "Deny":
            errors.append(f"{where}: only Effect 'Deny' is accepted for generated SCPs")
        if ("Action" in st) == ("NotAction" in st):
            errors.append(f"{where}: give exactly one of Action or NotAction")
        else:
            key = "Action" if "Action" in st else "NotAction"
            bad = _strings(st[key])
            if bad:
                errors.append(f"{where}.{key} {bad}")
        if ("Resource" in st) == ("NotResource" in st):
            errors.append(f"{where}: give exactly one of Resource or NotResource")
        else:
            key = "Resource" if "Resource" in st else "NotResource"
            bad = _strings(st[key])
            if bad:
                errors.append(f"{where}.{key} {bad}")
        if "Sid" in st and (not isinstance(st["Sid"], str) or not SID_RE.match(st["Sid"])):
            errors.append(f"{where}.Sid must be alphanumeric")
        if "Condition" in st:
            cond = st["Condition"]
            if not isinstance(cond, dict) or not cond:
                errors.append(f"{where}.Condition must be a non-empty object")
            else:
                for op, body in cond.items():
                    if not isinstance(body, dict) or not body:
                        errors.append(f"{where}.Condition.{op} must be a non-empty object")
                        continue
                    for ck, cv in body.items():
                        bad = _strings(cv)
                        if bad:
                            errors.append(f"{where}.Condition.{op}.{ck} {bad}")
        if st.get("Action") in ("*", ["*"]) and not st.get("Condition"):
            warnings.append(f"{where}: denies every action with no Condition; it blocks all principals in the target")
        if "NotAction" in st and not st.get("Condition"):
            warnings.append(f"{where}: NotAction without a Condition is broad; check the exempted actions")
    text = policy_text(policy) if isinstance(policy, dict) else ""
    if text and ACCOUNT_ID_RE.search(text):
        errors.append("policy contains a 12-digit account id; write it as a {{NAME}} placeholder")
    if text and PLACEHOLDER_RE.search(text):
        warnings.append("policy still contains {{INPUT}} placeholders; attaching it before they are replaced makes an "
                        "exemption match nobody, so the Deny applies to every principal")
    for name in sorted(set(LITERAL_ROLE_RE.findall(text))):
        if "*" not in name:
            warnings.append(f"role name {name!r} is hardcoded; use a {{{{NAME}}}} placeholder")
    if len(text) > SCP_MAX_CHARS:
        errors.append(f"policy is {len(text)} characters when minified; the SCP limit is {SCP_MAX_CHARS}")
    return errors, warnings


def validate_entry(entry, label, ou_targets, catalog_ids, evidence):
    """Validates one customScps item. Returns (normalized, errors). `evidence` is the scope validator's checker."""
    errors = []
    if not isinstance(entry, dict):
        return None, [f"{label} must be an object"]
    cid_ = entry.get("id")
    if not isinstance(cid_, str) or not ID_RE.match(cid_):
        errors.append(f"{label}.id must be lowercase letters, digits and hyphens (3-61 chars)")
    elif cid_ in catalog_ids:
        errors.append(f"{label}.id {cid_!r} is a catalog SCP: use it under 'scps' instead of rewriting it")
    title = str(entry.get("title", "") or "").strip()
    if not title:
        errors.append(f"{label}.title is required")
    targets = entry.get("targets")
    if not isinstance(targets, list) or not targets:
        errors.append(f"{label}.targets must be a non-empty list")
        targets = []
    for t in targets:
        if t != "root" and t not in ou_targets:
            errors.append(f"{label}: unknown target {t!r} (use 'root' or an OU name)")
    policy = entry.get("policy")
    if isinstance(policy, str):
        try:
            policy = json.loads(policy)
        except ValueError as e:
            errors.append(f"{label}.policy is not valid JSON: {e}")
            policy = None
    perr, warnings = validate_policy(policy) if policy is not None else ([], [])
    errors += [f"{label}: {e}" for e in perr]

    inputs = entry.get("inputs", [])
    if not isinstance(inputs, list):
        errors.append(f"{label}.inputs must be a list")
        inputs = []
    declared = {}
    for j, inp in enumerate(inputs):
        ok = isinstance(inp, dict) and isinstance(inp.get("name"), str) and INPUT_RE.match(inp["name"]) and inp.get("description")
        if not ok:
            errors.append(f"{label}.inputs[{j}] needs a NAME like ADMIN_ROLE_NAME (A-Z, 0-9, _) and a description")
            continue
        declared[inp["name"]] = {"name": inp["name"], "description": str(inp["description"])[:300],
                                 "example": str(inp.get("example", ""))[:200]}
    used = set(PLACEHOLDER_RE.findall(policy_text(policy))) if policy is not None else set()
    for name in sorted(used - set(declared)):
        errors.append(f"{label}: placeholder {{{{{name}}}}} is used in the policy but not declared under inputs")
    for name in sorted(set(declared) - used):
        errors.append(f"{label}: input {name} is declared but never used in the policy")
    evidence(label, entry.get("basis"), entry.get("source"))  # the scope validator adds its own errors

    norm = {"id": cid_, "title": title, "description": str(entry.get("description", "") or "")[:600],
            "targets": sorted(set(map(str, targets))), "policy": policy,
            "inputs": [declared[k] for k in sorted(declared)], "warnings": warnings,
            "basis": entry.get("basis"), "source": entry.get("source")}
    if policy is not None:
        norm["sha256"] = hashlib.sha256(policy_text(policy).encode()).hexdigest()
    return norm, errors


def policy_file(entry):
    return json.dumps(entry["policy"], indent=2) + "\n"


def index_json(scope):
    items = [{k: e[k] for k in ("id", "title", "description", "targets", "basis", "source", "inputs", "warnings", "sha256")}
             for e in scope.get("customScps", [])]
    return json.dumps({"aiGenerated": True, "reviewRequired": True, "appliedByStacks": False, "policies": items}, indent=2) + "\n"


def readme(scope):
    org = scope["customer"]["orgName"]
    entries = scope.get("customScps", [])
    rows = "\n".join(f"| `{e['id']}` | {', '.join(e['targets'])} | {', '.join(i['name'] for i in e['inputs']) or 'none'} | "
                     f"{len(e['warnings'])} |" for e in entries) or "| none | | | |"
    return f"""# Custom service control policies for {org} (AI-generated, review required)

These policies were written by an AI model from the statement of work. They are **not** part of the tested catalog and the
Terraform / CloudFormation in this bundle does **not** apply them. A person must review each one, fill in its inputs,
and test it before it is attached to anything.

| Policy | Target | Inputs to fill in | Warnings |
|---|---|---|---|
{rows}

`index.json` lists every policy with the SOW quote it came from, its inputs, warnings and a SHA-256 of the policy text.

## Before you use a policy
1. Read it against the SOW quote in `index.json`. Nothing here proves the policy does what the SOW intends.
2. Replace each `{{{{INPUT_NAME}}}}` placeholder before use. An exemption that still contains one matches nobody, so the Deny applies to every principal.
3. Check the limits: an OU or account can have at most 5 SCPs including `FullAWSAccess` and the ones Control Tower manages,
   and each SCP is at most {SCP_MAX_CHARS} characters. Catalog SCPs already attached count toward this.
4. Test on a **non-production** account first (attach to its OU, watch CloudTrail for unexpected `AccessDenied`), then
   roll out to the next OU. An SCP with a broad Deny can lock everyone out of an account; the management account is not affected.
5. Create and attach (example):
```
aws organizations create-policy --name <name> --type SERVICE_CONTROL_POLICY --description "<why>" --content file://<policy>.json
aws organizations attach-policy --policy-id <p-...> --target-id <ou-... or r-...>
```
"""

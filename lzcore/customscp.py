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


def policy_text(policy):
    return json.dumps(policy, separators=(",", ":"), sort_keys=True)


VALUE_MAX = 200


def value_error(name, value):
    """Why a value for input `name` cannot be put into a policy, or None. Values become JSON string content."""
    if not isinstance(value, str):
        return f"the value for {name} must be text"
    if len(value) > VALUE_MAX:
        return f"the value for {name} is longer than {VALUE_MAX} characters"
    if "{{" in value or "}}" in value:
        return f"the value for {name} must not contain {{{{ or }}}}"
    if any(ord(c) < 32 for c in value):
        return f"the value for {name} must not contain control characters"
    return None


def fill(policy, values):
    """The policy with every {{NAME}} that has a value replaced. Works on the parsed JSON (keys and strings), so a
    value can never change the structure of the document. Names without a value stay as placeholders."""
    def sub(text):
        return PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text)
    def walk(node):
        if isinstance(node, dict):
            return {sub(k): walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return sub(node) if isinstance(node, str) else node
    return walk(policy)


def values_of(entry):
    return {i["name"]: i["value"] for i in entry.get("inputs", []) if i.get("value")}


def is_filled(entry):
    return all(i.get("value") for i in entry.get("inputs", []))


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
        if not ("Resource" in st or "NotResource" in st):
            errors.append(f"{where}: Resource (or NotResource) is required")
        if st.get("Action") in ("*", ["*"]) and not st.get("Condition"):
            warnings.append(f"{where}: denies every action with no Condition; it blocks all principals in the target")
        if "NotAction" in st and not st.get("Condition"):
            warnings.append(f"{where}: NotAction without a Condition is broad; check the exempted actions")
    if len(policy_text(policy)) > SCP_MAX_CHARS:
        errors.append(f"policy is {len(policy_text(policy))} characters when minified; the SCP limit is {SCP_MAX_CHARS}")
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
        value = inp.get("value")
        if value:  # an empty value means "not filled in yet"
            verr = value_error(inp["name"], value)
            if verr:
                errors.append(f"{label}: {verr}")
            else:
                declared[inp["name"]]["value"] = value
    used = set(PLACEHOLDER_RE.findall(policy_text(policy))) if policy is not None else set()
    for name in sorted(used - set(declared)):
        errors.append(f"{label}: placeholder {{{{{name}}}}} is used in the policy but not declared under inputs")
    for name in sorted(set(declared) - used):
        errors.append(f"{label}: input {name} is declared but never used in the policy")
    if policy is not None and not perr:
        values = {n: d["value"] for n, d in declared.items() if d.get("value")}
        filled_errors, _ = validate_policy(fill(policy, values))
        errors += [f"{label}: after filling in the inputs, {e}" for e in filled_errors if e not in perr]
    evidence(label, entry.get("basis"), entry.get("source"))  # the scope validator adds its own errors

    norm = {"id": cid_, "title": title, "description": str(entry.get("description", "") or "")[:600],
            "targets": sorted(set(map(str, targets))), "policy": policy,
            "inputs": [declared[k] for k in sorted(declared)], "warnings": warnings,
            "basis": entry.get("basis"), "source": entry.get("source")}
    if policy is not None:
        norm["sha256"] = hashlib.sha256(policy_text(policy).encode()).hexdigest()  # of the template, as written
        if declared and all(d.get("value") for d in declared.values()) or not declared:
            norm["filledSha256"] = hashlib.sha256(policy_text(fill(policy, values_of(norm))).encode()).hexdigest()
    return norm, errors


def apply_edits(scope, edits):
    """Applies the user's edits to a copy of the scope's customScps and returns (new_scope, errors).

    Each edit is {"id", "policy"?, "values"?}. `policy` replaces the policy template (a dict or JSON text); `values`
    maps an input name to the text to put in place of {{NAME}}. Only the policy and the values can change; the
    id, title, targets and the SOW evidence stay as the agent wrote them. Inputs follow the template: a {{NAME}} the
    editor added is declared, and an input the editor replaced with a literal is dropped. The caller re-runs the
    scope validator on the result, which applies every rule in validate_entry."""
    new = json.loads(json.dumps(scope))
    by_id = {e["id"]: e for e in new.get("customScps", [])}
    errors = []
    seen = set()
    for n, edit in enumerate(edits):
        label = f"edits[{n}]"
        if not isinstance(edit, dict) or edit.get("id") not in by_id:
            errors.append(f"{label}: unknown policy id {edit.get('id') if isinstance(edit, dict) else edit!r}")
            continue
        if edit["id"] in seen:
            errors.append(f"{label}: policy {edit['id']} appears twice")
            continue
        seen.add(edit["id"])
        entry = by_id[edit["id"]]
        policy = edit.get("policy", entry["policy"])
        if isinstance(policy, str):
            try:
                policy = json.loads(policy)
            except ValueError as e:
                errors.append(f"{label}: the policy is not valid JSON: {e}")
                continue
        values = edit.get("values")
        if values is None:
            values = {}
        if not isinstance(values, dict):
            errors.append(f"{label}.values must be an object of input name to text")
            continue
        used = sorted(set(PLACEHOLDER_RE.findall(policy_text(policy))))
        old = {i["name"]: i for i in entry.get("inputs", [])}
        inputs = []
        for name in used:
            item = dict(old.get(name) or {"name": name, "description": "Added in the editor", "example": ""})
            if name in values:
                item["value"] = values[name]
            inputs.append(item)
        for name in sorted(set(values) - set(used)):
            errors.append(f"{label}: {name} is not an input of the policy")
        entry["policy"], entry["inputs"] = policy, inputs
    return new, errors


def policy_file(entry):
    """The policy with the filled-in values in place. An input without a value keeps its {{PLACEHOLDER}}."""
    return json.dumps(fill(entry["policy"], values_of(entry)), indent=2) + "\n"


def index_json(scope):
    items = [{**{k: e[k] for k in ("id", "title", "description", "targets", "basis", "source", "inputs", "warnings", "sha256")},
              "filled": is_filled(e), **({"filledSha256": e["filledSha256"]} if "filledSha256" in e else {})}
             for e in scope.get("customScps", [])]
    return json.dumps({"aiGenerated": True, "reviewRequired": True, "appliedByStacks": False, "policies": items}, indent=2) + "\n"


def readme(scope):
    org = scope["customer"]["orgName"]
    entries = scope.get("customScps", [])
    def left(e):
        todo = [i["name"] for i in e["inputs"] if not i.get("value")]
        return ", ".join(todo) if todo else ("none" if not e["inputs"] else "none (all filled in)")
    rows = "\n".join(f"| `{e['id']}` | {', '.join(e['targets'])} | {left(e)} | "
                     f"{len(e['warnings'])} |" for e in entries) or "| none | | | |"
    return f"""# Custom service control policies for {org} (AI-generated, review required)

These policies were written by an AI model from the statement of work. They are **not** part of the tested catalog and the
Terraform / CloudFormation in this bundle does **not** apply them. A person must review each one, fill in its inputs,
and test it before it is attached to anything.

| Policy | Target | Inputs still to fill in | Warnings |
|---|---|---|---|
{rows}

`index.json` lists every policy with the SOW quote it came from, its inputs, warnings and a SHA-256 of the policy text.

## Before you use a policy
1. Read it against the SOW quote in `index.json`. Nothing here proves the policy does what the SOW intends.
2. Replace each `{{{{INPUT_NAME}}}}` still left in a policy file with a real value (role names, account ids, ...).
   Values entered in the web app are already in the policy file; `index.json` shows which policies are `filled`.
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

"""Deterministic Mermaid diagram of the AWS Organizations tree implied by a validated scope. No LLM involved.

It draws only what the scope says, and marks who creates each node so the picture matches what the stacks will do:
  stack     custom OUs the generated Terraform / CloudFormation create
  ct        Security and Sandbox OUs and accounts that Control Tower creates
  existing  accounts that must already exist (for example the management account)
  planned   accounts the SOW names but these stacks do NOT create (Account Factory or manual)
"""
import re

from .catalog import CT_MANAGED_OUS, cid

LEGEND = (
    ("stack", "Created by the generated stacks (custom OUs)"),
    ("ct", "Created by AWS Control Tower (Security, Sandbox, shared accounts)"),
    ("existing", "Must already exist (for example the management account)"),
    ("planned", "Named in the SOW but NOT created by these stacks (Account Factory or manual)"),
)
_ACCOUNT_CLASS = {"control-tower": "ct", "existing": "existing", "account-factory": "planned", "manual": "planned"}


def _t(text, limit=60):
    """Label text that is safe inside a quoted Mermaid label."""
    return re.sub(r'["<>`{}\[\]|\\#&;]', "", str(text)).replace("\n", " ").strip()[:limit]


def _ou_label(name, scope, extra="", parent=""):
    controls = sum(1 for c in scope["controls"] if name in c["targets"])
    scps = [p["id"] for p in scope["scps"] if name in p["targets"]]
    lines = [_t(name) + extra]
    if parent:
        lines.append(f"inherits from {_t(parent)}")
    if controls:
        lines.append(f"controls: {controls}")
    if scps:
        lines.append("SCPs: " + _t(", ".join(scps), 80))
    return "<br/>".join(lines)


def org_mermaid(scope):
    lg = scope["logging"]
    ids = {"log-archive": lg.get("logArchiveAccountId", ""), "audit": lg.get("auditAccountId", "")}
    scp_root = [p["id"] for p in scope["scps"] if "root" in p["targets"]]
    root_label = "Root" + ("<br/>SCPs: " + _t(", ".join(scp_root), 80) if scp_root else "")

    L = ["flowchart TD", f'  ROOT["{root_label}"]:::existing']
    node = {"root": "ROOT"}
    for name in sorted(CT_MANAGED_OUS):
        node[name] = cid("Ou", name)
        L.append(f'  {node[name]}["{_ou_label(name, scope, " OU")}"]:::ct')
    custom = sorted(scope["ous"], key=lambda o: (bool(o.get("parent")), o["name"]))  # top-level first, then children
    for o in custom:
        node[o["name"]] = cid("Ou", o["name"])
        L.append(f'  {node[o["name"]]}["{_ou_label(o["name"], scope, " OU", o.get("parent", ""))}"]:::stack')
    for name in sorted(CT_MANAGED_OUS):
        L.append(f"  ROOT --> {node[name]}")
    for o in custom:
        L.append(f'  {node[o.get("parent") or "root"]} --> {node[o["name"]]}')

    for a in scope.get("accounts", []):
        nid = cid("Acct", a["name"])
        detail = f'{a["kind"]} · {a["provisioning"]}'
        if a["kind"] in ids:
            detail += f' · id: {ids[a["kind"]] or "NOT PROVIDED"}'
        cls = _ACCOUNT_CLASS[a["provisioning"]]
        L.append(f'  {nid}("{_t(a["name"])}<br/>{_t(detail, 80)}"):::{cls}')
        L.append(f'  {node[a["ou"]]} {"-.->" if cls == "planned" else "-->"} {nid}')

    L += [
        "  classDef stack fill:#dbeafe,stroke:#1d4ed8,color:#0f172a",
        "  classDef ct fill:#ede9fe,stroke:#6d28d9,color:#0f172a",
        "  classDef existing fill:#e2e8f0,stroke:#334155,color:#0f172a",
        "  classDef planned fill:#ffffff,stroke:#64748b,stroke-dasharray:5 5,color:#0f172a",
    ]
    return "\n".join(L) + "\n"


def org_markdown(scope):
    """docs/ORG-STRUCTURE.md: renders as a diagram on GitHub and most Markdown viewers."""
    legend = "\n".join(f"- **{k}**: {v}" for k, v in LEGEND)
    note = ""
    if scope.get("missingRequired"):
        note = f"\n> Not ready to apply: missing {', '.join(scope['missingRequired'])}.\n"
    custom = scope.get("customScps") or []
    if custom:
        ids = ", ".join(p["id"] for p in custom)
        note += f"\nModel-authored SCPs are not attached by these stacks and are not drawn here. They are in `custom-scps/`: {ids}.\n"
    return (f"# Organization structure: {scope['customer']['orgName']}\n{note}\n"
            "Generated from the approved scope (`docs/scope.json`). The stacks create only the OUs marked `stack`; "
            "accounts are shown for context.\n\n"
            f"```mermaid\n{org_mermaid(scope)}```\n\n## Legend\n{legend}\n")

"""Deterministic Mermaid diagram of the AWS Organizations tree implied by a validated scope. No LLM involved.

It draws only what the scope says, and marks who creates each node so the picture matches what the stacks will do:
  stack     OUs and accounts the generated Terraform / CloudFormation create (accounts from the emails you provide)
  shared    the Security OU with the Log Archive and Audit accounts: created by the stacks, set up by Control Tower
  existing  what must already exist (the management account)
"""
import re

from .catalog import SECURITY_OU, cid
from .scope import creatable_accounts

LEGEND = (
    ("stack", "Created by the generated stacks (OUs, workload accounts)"),
    ("shared", "Security OU and shared accounts: created by the stacks, set up by Control Tower"),
    ("existing", "Already exists (the management account)"),
)


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
    created = {a["name"] for a in creatable_accounts(scope)}
    scp_root = [p["id"] for p in scope["scps"] if "root" in p["targets"]]
    root_label = "Root" + ("<br/>SCPs: " + _t(", ".join(scp_root), 80) if scp_root else "")

    L = ["flowchart TD", f'  ROOT["{root_label}"]:::existing']
    node = {"root": "ROOT"}
    ous = sorted(scope["ous"], key=lambda o: (bool(o.get("parent")), o["name"]))  # top-level first, then children
    for o in ous:
        node[o["name"]] = cid("Ou", o["name"])
        cls = "shared" if o["name"] == SECURITY_OU else "stack"
        L.append(f'  {node[o["name"]]}["{_ou_label(o["name"], scope, " OU", o.get("parent", ""))}"]:::{cls}')
    for o in ous:
        L.append(f'  {node[o.get("parent") or "root"]} --> {node[o["name"]]}')

    for a in scope.get("accounts", []):
        nid = cid("Acct", a["name"])
        if a["kind"] == "management":
            detail, cls = "management · already exists", "existing"
        else:
            detail = a["kind"] + (" · email required" if a["name"] in created else " · existing id")
            if a["kind"] in ids and ids[a["kind"]]:
                detail += f' · id: {ids[a["kind"]]}'
            cls = "shared" if a["kind"] in ids else "stack"
        L.append(f'  {nid}("{_t(a["name"])}<br/>{_t(detail, 80)}"):::{cls}')
        L.append(f'  {node[a["ou"]]} --> {nid}')

    L += [
        "  classDef stack fill:#0e1e33,stroke:#2b8ef0,color:#e6e9ef",
        "  classDef shared fill:#1f1b3d,stroke:#9b8cf7,color:#e6e9ef",
        "  classDef existing fill:#1a1f29,stroke:#8b94a3,color:#e6e9ef",
    ]
    return "\n".join(L) + "\n"


def org_markdown(scope):
    """docs/ORG-STRUCTURE.md: renders as a diagram on GitHub and most Markdown viewers."""
    legend = "\n".join(f"- **{k}**: {v}" for k, v in LEGEND)
    note = ""
    if scope.get("missingRequired"):
        note = f"\n> Not ready to apply: missing {', '.join(scope['missingRequired'])}.\n"
    return (f"# Organization structure: {scope['customer']['orgName']}\n{note}\n"
            "Generated from the scope (`docs/scope.json`). The stacks create every OU and account shown except "
            "the management account; accounts are created from the emails you provide.\n\n"
            f"```mermaid\n{org_mermaid(scope)}```\n\n## Legend\n{legend}\n")

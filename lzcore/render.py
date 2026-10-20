"""Deterministic stack rendering. Same scope in -> byte-identical files out. No LLM involved.

Fixed layouts (EXPECTED_*), so every customer gets the same folder and file structure:
  terraform/       static .tf files copied verbatim from templates/terraform + terraform.tfvars + policies/<scp>.json
  cloudformation/  00-prerequisites.yaml, 01-landing-zone.yaml (static) + 02-governance.yaml (generated) + parameters/
  custom-scps/     model-authored SCP JSON. Not referenced by the stacks.
  session/         agent session history
  scans/           added after validation (see with_scans); not part of the fixed render
"""
import io
import json
import os
import zipfile
from pathlib import Path

from .catalog import CT_MANAGED_OUS, cid, scp_json
from .diagram import org_markdown
from .scope import scope_markdown

TEMPLATES = Path(os.environ.get("TEMPLATES_DIR", Path(__file__).resolve().parent.parent / "templates"))
TF_STATIC = ("versions.tf", "providers.tf", "variables.tf", "prerequisites.tf", "landing_zone.tf",
             "organizations.tf", "scps.tf", "controls.tf", "outputs.tf")
CFN_STATIC = ("00-prerequisites.yaml", "01-landing-zone.yaml")
_EXTRAS = {"custom-scps/README.md", "session/history.json"}
TF_FIXED = set(TF_STATIC) | {"README.md", "terraform.tfvars", "docs/SCOPE.md", "docs/ORG-STRUCTURE.md", "docs/scope.json"} | _EXTRAS
CFN_FIXED = set(CFN_STATIC) | {"README.md", "02-governance.yaml", "parameters/01-landing-zone.json",
                               "parameters/02-governance.json", "docs/SCOPE.md", "docs/ORG-STRUCTURE.md", "docs/scope.json"} | _EXTRAS

CUSTOM_SCP_README = """# Custom SCPs (model-authored)

These policies were written by the model from the SOW and approved with the scope.
The Terraform and CloudFormation stacks do not create or attach them.
Catalog policies in `policies/` (Terraform) and in `02-governance.yaml` (CloudFormation) are the ones those stacks apply.

Review each JSON file in this folder before you attach it yourself with AWS Organizations.
"""

_NOT_RECORDED = {"status": "not-recorded"}


# ---------- helpers ----------
def _hcl_list(vals):
    return "[" + ", ".join(json.dumps(v) for v in vals) + "]"


def _aligned(pairs, indent=""):
    w = max((len(k) for k, _ in pairs), default=0)
    return "".join(f"{indent}{k.ljust(w)} = {v}\n" for k, v in pairs)


def _readme(name, scope):
    t = (TEMPLATES / name).read_text()
    return (t.replace("{{ORG}}", scope["customer"]["orgName"]).replace("{{HOME}}", scope["regions"]["home"])
            .replace("{{SLUG}}", scope["customer"]["orgSlug"]))


def _docs(scope):
    return {"docs/SCOPE.md": scope_markdown(scope), "docs/ORG-STRUCTURE.md": org_markdown(scope),
            "docs/scope.json": json.dumps(scope, indent=2, sort_keys=True) + "\n"}


def _extras(scope, session):
    """Files that ride along with both stacks: model SCPs (separate folder) and the agent session."""
    files = {"custom-scps/README.md": CUSTOM_SCP_README}
    for p in scope.get("customScps", []):
        files[f"custom-scps/{p['id']}.json"] = json.dumps(p["document"], indent=2) + "\n"
    body = session if isinstance(session, dict) else _NOT_RECORDED
    files["session/history.json"] = json.dumps(body, indent=2, sort_keys=True) + "\n"
    return files


def stable_names(files):
    """Names present for every customer. Catalog policy JSON, custom SCP JSON, and scan logs vary."""
    return {f for f in files if not f.startswith(("policies/", "scans/")) and not (f.startswith("custom-scps/") and f.endswith(".json"))}


def with_scans(files, scans):
    """Copy code-scan reports into the bundle under scans/. `scans` keys are file names, not a scans/ prefix."""
    out = dict(files)
    for name, content in scans.items():
        if not name or name.startswith(("/", "\\")) or ".." in name.split("/"):
            raise ValueError(f"invalid scan path {name!r}")
        out[f"scans/{name}"] = content if isinstance(content, str) else content.decode("utf-8", "replace")
    return out


# ---------- terraform ----------
def render_terraform(scope, session=None):
    r, lg = scope["regions"], scope["logging"]
    files = {f: (TEMPLATES / "terraform" / f).read_text() for f in TF_STATIC}
    files["README.md"] = _readme("README.terraform.md", scope)

    out = _aligned([
        ("org_name", json.dumps(scope["customer"]["orgName"])),
        ("home_region", json.dumps(r["home"])),
        ("governed_regions", _hcl_list(r["governed"])),
        ("allowed_regions", _hcl_list(r["allowed"])),
        ("log_archive_account_id", json.dumps(lg["logArchiveAccountId"])),
        ("audit_account_id", json.dumps(lg["auditAccountId"])),
        ("log_retention_days", str(lg["retentionDays"])),
        ("access_log_retention_days", str(lg["accessLogRetentionDays"])),
        ("kms_key_arn", json.dumps(lg["kmsKeyArn"])),
    ])
    out += "\nous = {" + ("}\n" if not scope["ous"] else "\n")
    if scope["ous"]:
        out += _aligned([(json.dumps(o["name"]), "{ parent = " + json.dumps(o["parent"]) + " }" if o.get("parent") else "{}")
                         for o in scope["ous"]], "  ") + "}\n"
    out += "\nscps = {" + ("}\n" if not scope["scps"] else "\n")
    if scope["scps"]:
        out += _aligned([(json.dumps(p["id"]), "{ targets = " + _hcl_list(p["targets"]) + " }") for p in scope["scps"]], "  ") + "}\n"
    out += "\ncontrols = {" + ("}\n" if not scope["controls"] else "\n")
    if scope["controls"]:
        out += _aligned([(json.dumps(c["id"]), "{ targets = " + _hcl_list(c["targets"]) + " }") for c in scope["controls"]], "  ") + "}\n"
    files["terraform.tfvars"] = out
    for p in scope["scps"]:
        files[f"policies/{p['id']}.json"] = scp_json(p["id"], scope, pretty=True)
    files.update(_docs(scope))
    files.update(_extras(scope, session))
    return files


# ---------- cloudformation ----------
def _param_file(pairs):
    return json.dumps([{"ParameterKey": k, "ParameterValue": str(v)} for k, v in pairs], indent=2) + "\n"


def render_cloudformation(scope, session=None):
    r, lg = scope["regions"], scope["logging"]
    files = {f: (TEMPLATES / "cloudformation" / f).read_text() for f in CFN_STATIC}
    files["README.md"] = _readme("README.cloudformation.md", scope)
    files["parameters/01-landing-zone.json"] = _param_file([
        ("GovernedRegions", ",".join(r["governed"])),
        ("LogArchiveAccountId", lg["logArchiveAccountId"]),
        ("AuditAccountId", lg["auditAccountId"]),
        ("LogRetentionDays", lg["retentionDays"]),
        ("AccessLogRetentionDays", lg["accessLogRetentionDays"]),
        ("KmsKeyArn", lg["kmsKeyArn"]),
    ])
    files["parameters/02-governance.json"] = _param_file([
        ("OrganizationRootId", ""), ("OrganizationId", ""), ("SecurityOuId", ""), ("SandboxOuId", ""),
    ])

    def target_ref(t):
        if t == "root":
            return "!Ref OrganizationRootId"
        if t in CT_MANAGED_OUS:
            return f"!Ref {t}OuId"
        return f"!GetAtt {cid('Ou', t)}.Id"

    L = [
        'AWSTemplateFormatVersion: "2010-09-09"',
        "Description: Custom OUs, service control policies and Control Tower controls. Deploy after 01-landing-zone completes.",
        "",
        "Metadata:  # parameters are fixed for every customer, so some may be unused",
        "  cfn-lint:",
        "    config:",
        "      ignore_checks: [W2001]",
        "",
        "Parameters:",
        "  OrganizationRootId:",
        "    Type: String",
        '    AllowedPattern: "r-[0-9a-z]{4,32}"',
        "  OrganizationId:",
        "    Type: String",
        '    AllowedPattern: "o-[0-9a-z]{10,32}"',
        "  SecurityOuId:",
        "    Type: String",
        '    AllowedPattern: "ou-[0-9a-z]{4,32}-[0-9a-z]{8,32}"',
        "  SandboxOuId:",
        "    Type: String",
        '    AllowedPattern: "ou-[0-9a-z]{4,32}-[0-9a-z]{8,32}"',
        "",
        "Resources:",
    ]
    emitted = False
    for o in scope["ous"]:
        L += [f"  {cid('Ou', o['name'])}:", "    Type: AWS::Organizations::OrganizationalUnit", "    Properties:",
              f"      Name: {json.dumps(o['name'])}",
              f"      ParentId: {'!GetAtt ' + cid('Ou', o['parent']) + '.Id' if o.get('parent') else '!Ref OrganizationRootId'}"]
        emitted = True
    for p in scope["scps"]:
        L += [f"  {cid('Scp', p['id'])}:", "    Type: AWS::Organizations::Policy", "    Properties:",
              f"      Name: {json.dumps(scope['customer']['orgSlug'] + '-' + p['id'])}",
              "      Type: SERVICE_CONTROL_POLICY",
              f"      Description: {json.dumps(p['id'])}",
              f"      Content: {scp_json(p['id'], scope)}",
              "      TargetIds:"]
        L += [f"        - {target_ref(t)}" for t in p["targets"]]
        emitted = True
    prev = None
    for c in scope["controls"]:
        for t in c["targets"]:
            sub_ou = f"{t}OuId" if t in CT_MANAGED_OUS else f"{cid('Ou', t)}.Id"  # usable inside !Sub ${...}
            L += [f"  {cid('Control', c['id'], t)}:", "    Type: AWS::ControlTower::EnabledControl"]
            if prev:
                L += [f"    DependsOn: {prev}"]
            L += ["    Properties:",
                  f'      ControlIdentifier: !Sub "arn:${{AWS::Partition}}:controltower:{r["home"]}::control/{c["id"]}"',
                  f'      TargetIdentifier: !Sub "arn:${{AWS::Partition}}:organizations::${{AWS::AccountId}}:ou/${{OrganizationId}}/${{{sub_ou}}}"']
            prev = cid("Control", c["id"], t)
            emitted = True
    if not emitted:  # a template needs at least one resource
        L += ["  NothingToDeploy:", "    Type: AWS::CloudFormation::WaitConditionHandle"]
    files["02-governance.yaml"] = "\n".join(L) + "\n"
    files.update(_docs(scope))
    files.update(_extras(scope, session))
    return files


# ---------- bundle ----------
def zip_bytes(files, root):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"{root}/{name}", date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[name].encode() if isinstance(files[name], str) else files[name])
    return buf.getvalue()


def render_all(scope, session=None):
    return {"terraform": render_terraform(scope, session), "cloudformation": render_cloudformation(scope, session)}

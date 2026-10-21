"""Deterministic stack rendering. Same scope in -> byte-identical files out. No LLM involved.

Fixed layouts (EXPECTED_*), so every customer gets the same folder and file structure:
  terraform/       static .tf files copied verbatim from templates/terraform + terraform.tfvars + policies/<scp>.json
  cloudformation/  00-prerequisites.yaml, 01-landing-zone.yaml (static) + 02-governance.yaml (generated) + parameters/
"""
import io
import json
import os
import zipfile
from pathlib import Path

from . import customscp
from .catalog import SECURITY_OU, cid, scp_json
from .diagram import org_markdown
from .scope import creatable_accounts, scope_markdown

TEMPLATES = Path(os.environ.get("TEMPLATES_DIR", Path(__file__).resolve().parent.parent / "templates"))
TF_STATIC = ("versions.tf", "providers.tf", "variables.tf", "prerequisites.tf", "accounts.tf", "landing_zone.tf",
             "organizations.tf", "scps.tf", "controls.tf", "outputs.tf")
CFN_STATIC = ("00-prerequisites.yaml", "01-landing-zone.yaml")
CUSTOM_SCP_FIXED = {"custom-scps/README.md", "custom-scps/index.json"}  # plus custom-scps/<id>.json per policy
TF_FIXED = set(TF_STATIC) | CUSTOM_SCP_FIXED | {"README.md", "terraform.tfvars", "docs/SCOPE.md", "docs/ORG-STRUCTURE.md", "docs/scope.json"}
CFN_FIXED = set(CFN_STATIC) | CUSTOM_SCP_FIXED | {"README.md", "02-governance.yaml", "parameters/00-prerequisites.json",
                                                  "parameters/01-landing-zone.json", "parameters/02-governance.json",
                                                  "docs/SCOPE.md", "docs/ORG-STRUCTURE.md", "docs/scope.json"}


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


def _custom_scps(scope):
    files = {"custom-scps/README.md": customscp.readme(scope), "custom-scps/index.json": customscp.index_json(scope)}
    files.update({f"custom-scps/{e['id']}.json": customscp.policy_file(e) for e in scope.get("customScps", [])})
    return files


def _docs(scope):
    return {"docs/SCOPE.md": scope_markdown(scope), "docs/ORG-STRUCTURE.md": org_markdown(scope),
            "docs/scope.json": json.dumps(scope, indent=2, sort_keys=True) + "\n"}


# ---------- terraform ----------
def render_terraform(scope):
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
    custom_ous = [o for o in scope["ous"] if o["name"] != SECURITY_OU]  # Security is a fixed resource in organizations.tf
    out += "\nous = {" + ("}\n" if not custom_ous else "\n")
    if custom_ous:
        out += _aligned([(json.dumps(o["name"]), "{ parent = " + json.dumps(o["parent"]) + " }" if o.get("parent") else "{}")
                         for o in custom_ous], "  ") + "}\n"
    accts = creatable_accounts(scope)
    out += ("\n# One root email per account. Each must be unique and must never have been used for another AWS account.\n"
            "# These are the only inputs you must fill in; `terraform plan` refuses an empty email.\n"
            "accounts = {" + ("}\n" if not accts else "\n"))
    for a in accts:
        out += (f"  {json.dumps(a['name'])} = {{\n    ou    = {json.dumps(a['ou'])}\n    kind  = {json.dumps(a['kind'])}\n"
                f"    email = \"\" # TODO: root email for {a['name']}\n  }}\n")
    if accts:
        out += "}\n"
    out += "\nscps = {" + ("}\n" if not scope["scps"] else "\n")
    if scope["scps"]:
        out += _aligned([(json.dumps(p["id"]), "{ targets = " + _hcl_list(p["targets"]) + " }") for p in scope["scps"]], "  ") + "}\n"
    out += "\ncontrols = {" + ("}\n" if not scope["controls"] else "\n")
    if scope["controls"]:
        out += _aligned([(json.dumps(c["id"]), "{ targets = " + _hcl_list(c["targets"]) + " }") for c in scope["controls"]], "  ") + "}\n"
    out += ("\n# Stage 2: set this after the first apply (see README), then apply again to register the OUs and enable the controls.\n"
            "# identity_center_enabled_baseline_arn = \"arn:aws:controltower:<region>:<management-account-id>:enabledbaseline/<id>\"\n")
    files["terraform.tfvars"] = out
    for p in scope["scps"]:
        files[f"policies/{p['id']}.json"] = scp_json(p["id"], scope, pretty=True)
    files.update(_custom_scps(scope))
    files.update(_docs(scope))
    return files


# ---------- cloudformation ----------
def _param_file(pairs):
    return json.dumps([{"ParameterKey": k, "ParameterValue": str(v)} for k, v in pairs], indent=2) + "\n"


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
ARN_PATTERN = r"^arn:aws[0-9a-zA-Z_\-:/]+$"
BASELINE_ID = "17BSJV3IGJ2QSGA2"  # AWSControlTowerBaseline, as printed in the AWS Control Tower examples


def render_cloudformation(scope):
    r, lg = scope["regions"], scope["logging"]
    files = {f: (TEMPLATES / "cloudformation" / f).read_text() for f in CFN_STATIC}
    files["README.md"] = _readme("README.cloudformation.md", scope)
    shared = {a["kind"]: a for a in scope["accounts"] if a["kind"] in ("log-archive", "audit")}
    files["parameters/00-prerequisites.json"] = _param_file([
        ("OrganizationRootId", ""),
        ("LogArchiveAccountName", shared["log-archive"]["name"]), ("LogArchiveAccountEmail", ""), ("LogArchiveAccountId", lg["logArchiveAccountId"]),
        ("AuditAccountName", shared["audit"]["name"]), ("AuditAccountEmail", ""), ("AuditAccountId", lg["auditAccountId"]),
    ])
    files["parameters/01-landing-zone.json"] = _param_file([
        ("GovernedRegions", ",".join(r["governed"])),
        ("LogArchiveAccountId", lg["logArchiveAccountId"]),  # empty: copy the output of the 00-prerequisites stack
        ("AuditAccountId", lg["auditAccountId"]),
        ("LogRetentionDays", lg["retentionDays"]),
        ("AccessLogRetentionDays", lg["accessLogRetentionDays"]),
        ("KmsKeyArn", lg["kmsKeyArn"]),
    ])
    members = [a for a in creatable_accounts(scope) if a["kind"] not in ("log-archive", "audit")]
    files["parameters/02-governance.json"] = _param_file([
        ("OrganizationRootId", ""), ("OrganizationId", ""), ("SecurityOuId", ""),
        ("ControlTowerBaselineArn", f"arn:aws:controltower:{r['home']}::baseline/{BASELINE_ID}"),
        ("ControlTowerBaselineVersion", "4.0"), ("IdentityCenterEnabledBaselineArn", ""),
    ] + [("Email" + cid(a["name"]), "") for a in members])

    def target_ref(t):
        if t == "root":
            return "!Ref OrganizationRootId"
        if t == SECURITY_OU:
            return "!Ref SecurityOuId"
        return f"!GetAtt {cid('Ou', t)}.Id"

    custom = sorted((o for o in scope["ous"] if o["name"] != SECURITY_OU), key=lambda o: (bool(o.get("parent")), o["name"]))
    L = [
        'AWSTemplateFormatVersion: "2010-09-09"',
        "Description: Custom OUs, Control Tower OU registration, accounts, service control policies and controls. Deploy after 01-landing-zone completes.",
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
        "    Description: The SecurityOuId output of the 00-prerequisites stack.",
        "  ControlTowerBaselineArn:",
        "    Type: String",
        f"    AllowedPattern: '{ARN_PATTERN}'",
        "    Description: \"aws controltower list-baselines --query 'baselines[?name==`AWSControlTowerBaseline`].arn'\"",
        "  ControlTowerBaselineVersion:",
        "    Type: String",
        "    AllowedPattern: '^\\d+(\\.\\d+){0,2}$'",
        "  IdentityCenterEnabledBaselineArn:",
        "    Type: String",
        f"    AllowedPattern: '{ARN_PATTERN}'",
        "    Description: The enabled IdentityCenterBaseline of the landing zone. See the README for the lookup command.",
    ]
    for a in members:
        L += [f"  Email{cid(a['name'])}:", "    Type: String", f"    AllowedPattern: '{EMAIL_PATTERN}'",
              f"    Description: {json.dumps('Root email for the new account ' + a['name'] + '. Must never have been used for another AWS account.')}"]
    L += ["", "Resources:"]
    for o in custom:
        L += [f"  {cid('Ou', o['name'])}:", "    Type: AWS::Organizations::OrganizationalUnit", "    Properties:",
              f"      Name: {json.dumps(o['name'])}",
              f"      ParentId: {'!GetAtt ' + cid('Ou', o['parent']) + '.Id' if o.get('parent') else '!Ref OrganizationRootId'}"]
    for p in scope["scps"]:
        L += [f"  {cid('Scp', p['id'])}:", "    Type: AWS::Organizations::Policy", "    Properties:",
              f"      Name: {json.dumps(scope['customer']['orgSlug'] + '-' + p['id'])}",
              "      Type: SERVICE_CONTROL_POLICY",
              f"      Description: {json.dumps(p['id'])}",
              f"      Content: {scp_json(p['id'], scope)}",
              "      TargetIds:"]
        L += [f"        - {target_ref(t)}" for t in p["targets"]]

    # One serial chain (baselines, then controls, then accounts): Control Tower runs one operation at a time.
    prev = None

    def chain():
        return [f"    DependsOn: {prev}"] if prev else []

    # An OU must be registered with Control Tower before controls can be enabled on it and before its accounts are governed.
    # The Security OU is the foundational OU and is set up by the landing zone itself.
    for o in custom:
        name = cid("Baseline", o["name"])
        L += [f"  {name}:", "    Type: AWS::ControlTower::EnabledBaseline"] + chain() + [
            "    Properties:",
            "      BaselineIdentifier: !Ref ControlTowerBaselineArn",
            "      BaselineVersion: !Ref ControlTowerBaselineVersion",
            f'      TargetIdentifier: !Sub "arn:${{AWS::Partition}}:organizations::${{AWS::AccountId}}:ou/${{OrganizationId}}/${{{cid("Ou", o["name"])}.Id}}"',
            "      Parameters:",
            "        - Key: IdentityCenterEnabledBaselineArn",
            "          Value: !Ref IdentityCenterEnabledBaselineArn"]
        prev = name
    for c in scope["controls"]:
        for t in c["targets"]:
            sub_ou = "SecurityOuId" if t == SECURITY_OU else f"{cid('Ou', t)}.Id"  # usable inside !Sub ${...}
            name = cid("Control", c["id"], t)
            L += [f"  {name}:", "    Type: AWS::ControlTower::EnabledControl"] + chain() + [
                "    Properties:",
                f'      ControlIdentifier: !Sub "arn:${{AWS::Partition}}:controltower:{r["home"]}::control/{c["id"]}"',
                f'      TargetIdentifier: !Sub "arn:${{AWS::Partition}}:organizations::${{AWS::AccountId}}:ou/${{OrganizationId}}/${{{sub_ou}}}"']
            prev = name
    # Accounts last, so enrollment events do not collide with the operations above. They are retained if the stack is deleted
    # because closing an AWS account takes up to 90 days.
    for a in members:
        L += [f"  {cid('Acct', a['name'])}:", "    Type: AWS::Organizations::Account", "    DeletionPolicy: Retain",
              "    UpdateReplacePolicy: Retain"] + chain() + [
            "    Properties:",
            f"      AccountName: {json.dumps(a['name'])}",
            f"      Email: !Ref Email{cid(a['name'])}",
            f"      ParentIds: [{target_ref(a['ou'])}]"]
    if len(L) and L[-1] == "Resources:":  # a template needs at least one resource
        L += ["  NothingToDeploy:", "    Type: AWS::CloudFormation::WaitConditionHandle"]
    files["02-governance.yaml"] = "\n".join(L) + "\n"
    files.update(_custom_scps(scope))
    files.update(_docs(scope))
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


def render_all(scope):
    return {"terraform": render_terraform(scope), "cloudformation": render_cloudformation(scope)}

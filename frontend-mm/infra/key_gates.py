"""Key gates: a Lambda per agent that the dashboard's CloudFront calls instead of the agent's API directly.

An agent's API wants a shared access key that the browser must not hold. The key lives in Secrets Manager in this account
(ingram-mm-dashboard/<agent>-access-key). The gate checks the caller's Cognito ID token and only then reads the key and
forwards the call. Nothing here prints the key. direct.py points the agent's origin at the gate's function URL once it exists.
All gates run the same code (key_gate/index.js); what differs is set by environment variables (see `Gate.environment`).
A gate is only built for an agent whose API origin is in the distribution (that is, one listed in infra/agents.txt).
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

ACCOUNT = "455162169375"
REGION = "us-east-1"
STAGE = "dev"
HERE = Path(__file__).resolve().parent / "key_gate" / "index.js"


class GateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Gate:
    agent: str  # the id in /agents/<id>/api/
    function_name: str
    role_name: str
    secret_id: str  # in this account; holds the agent API's access key
    origin: str  # the API's host in the CloudFront template; the gate replaces it
    label: str  # in messages: "TCO key gate"

    @property
    def environment(self) -> dict[str, str]:
        """What the shared code needs to know. The Cognito pool is the dashboard's and is in the code."""
        return {
            "PREFIX": f"/agents/{self.agent}/api",
            "STAGE": STAGE,
            "UPSTREAM": self.origin,
            "SECRET_ID": self.secret_id,
            "LABEL": self.agent,
        }


TCO = Gate(
    agent="tco",
    function_name="ingram-mm-dashboard-tco-key-gate",
    role_name="ingram-mm-dashboard-tco-key-gate",
    secret_id="ingram-mm-dashboard/tco-access-key",
    origin="sdcr1ipp07.execute-api.us-east-1.amazonaws.com",
    label="TCO",
)
ORCHESTRATOR = Gate(
    agent="orchestrator",
    function_name="ingram-mm-dashboard-orchestrator-key-gate",
    role_name="ingram-mm-dashboard-orchestrator-key-gate",
    secret_id="ingram-mm-dashboard/orchestrator-access-key",
    origin="aafoxbd4f1.execute-api.us-east-1.amazonaws.com",
    label="deck orchestrator",
)
# The agent team's own secret (same account, kept by its stack), so the key is never copied. Its API serves the gate's
# /dev/<path> through a dev stage.
ARCHITECTURE_DESIGN = Gate(
    agent="architecture-design",
    function_name="ingram-mm-dashboard-architecture-design-key-gate",
    role_name="ingram-mm-dashboard-architecture-design-key-gate",
    secret_id="a05-arch-dev/access-key",
    origin="xtyojvbhm9.execute-api.us-east-1.amazonaws.com",
    label="Architecture Design",
)
# The CVA agent's access-key API (stack cva-agent-key in the aivar-vision account, behind its own CloudFront). Its key is
# copied here by that repo's deploy/key/deploy.sh copy-key. The manifest's originPath /api/ already gives the full path.
CVA_OUTPUT = Gate(
    agent="cva-output",
    function_name="ingram-mm-dashboard-cva-output-key-gate",
    role_name="ingram-mm-dashboard-cva-output-key-gate",
    secret_id="ingram-mm-dashboard/cva-output-access-key",
    origin="d2f11is2hu6tzu.cloudfront.net",
    label="CVA Output",
)
GATES = (TCO, ORCHESTRATOR, ARCHITECTURE_DESIGN, CVA_OUTPUT)


def wanted(config: dict, gate: Gate) -> bool:
    """True when the distribution has this agent's API origin, so it needs the gate."""
    return any(origin.get("DomainName") == gate.origin for origin in config.get("Origins", []))


def point_at_gate(config: dict, gate: Gate, host: str) -> None:
    """Send the agent's origin to its gate. Other origins stay as the template wrote them."""
    for origin in config.get("Origins", []):
        if origin.get("DomainName") == gate.origin:
            origin["DomainName"] = host


def _aws(*args: str, ok_errors: tuple[str, ...] = ()) -> dict | None:
    result = subprocess.run(["aws", *args, "--region", REGION, "--output", "json"], capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        if any(code in message for code in ok_errors):
            return None
        raise GateError(message.splitlines()[-1] if message else f"aws {' '.join(args[:3])} failed")
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


def _zip_bytes() -> bytes:
    buffer = tempfile.SpooledTemporaryFile()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(HERE, "index.js")
    buffer.seek(0)
    return buffer.read()


def _role_arn(gate: Gate) -> str:
    found = _aws("iam", "get-role", "--role-name", gate.role_name, ok_errors=("NoSuchEntity",))
    if found:
        return found["Role"]["Arn"]
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }
    created = _aws("iam", "create-role", "--role-name", gate.role_name, "--assume-role-policy-document", json.dumps(trust),
                   "--description", f"Reads the {gate.label} access key for signed-in dashboard users")
    if not created:
        raise GateError(f"could not create role {gate.role_name}")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:*"},
            {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue",
             "Resource": f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{gate.secret_id}*"},
        ],
    }
    _aws("iam", "put-role-policy", "--role-name", gate.role_name, "--policy-name", f"{gate.agent}-key", "--policy-document", json.dumps(policy))
    return created["Role"]["Arn"]


def _host_of(config: dict | None) -> str | None:
    if not config or "FunctionUrl" not in config:
        return None
    return config["FunctionUrl"].split("//", 1)[1].strip("/")


def _read_url(name: str) -> str | None:
    return _host_of(_aws("lambda", "get-function-url-config", "--function-name", name, ok_errors=("ResourceNotFoundException",)))


def _function_url(name: str) -> str:
    found = _read_url(name)
    if found:
        return found
    created = _aws("lambda", "create-function-url-config", "--function-name", name, "--auth-type", "NONE")
    _aws("lambda", "add-permission", "--function-name", name, "--statement-id", "function-url-public",
         "--action", "lambda:InvokeFunctionUrl", "--principal", "*", "--function-url-auth-type", "NONE",
         ok_errors=("ResourceConflictException",))
    _aws("lambda", "add-permission", "--function-name", name, "--statement-id", "function-url-invoke",
         "--action", "lambda:InvokeFunction", "--principal", "*", "--invoked-via-function-url",
         ok_errors=("ResourceConflictException",))
    host = _host_of(created)
    if not host:
        raise GateError("a key gate has no function URL")
    return host


def find_gate_host(gate: Gate) -> str | None:
    """The function URL host if the gate already exists, else None. Reads only."""
    found = _aws("lambda", "get-function", "--function-name", gate.function_name, ok_errors=("ResourceNotFoundException",))
    if not found:
        return None
    return _read_url(gate.function_name)


def secret_exists(gate: Gate) -> bool:
    """Reads only. The secret's value is never read here."""
    return _aws("secretsmanager", "describe-secret", "--secret-id", gate.secret_id, ok_errors=("ResourceNotFoundException",)) is not None


def _settled(gate: Gate) -> None:
    for _ in range(30):
        state = _aws("lambda", "get-function-configuration", "--function-name", gate.function_name) or {}
        if state.get("State") == "Active" and state.get("LastUpdateStatus") == "Successful":
            return
        time.sleep(1)
    raise GateError(f"the {gate.label} key gate did not become ready")


def ensure_gate(gate: Gate) -> str:
    """Create or update the gate and return its function URL host. Does not print the access key."""
    if not secret_exists(gate):
        raise GateError(f"{gate.secret_id} is missing in this account (see infra/README.md: Key gates)")
    arn = _role_arn(gate)
    payload = _zip_bytes()
    digest = base64.b64encode(hashlib.sha256(payload).digest()).decode()
    environment = json.dumps({"Variables": gate.environment})
    current = _aws("lambda", "get-function", "--function-name", gate.function_name, ok_errors=("ResourceNotFoundException",))
    with tempfile.NamedTemporaryFile(suffix=".zip") as package:
        package.write(payload)
        package.flush()
        if current is None:
            for _ in range(8):
                made = subprocess.run(
                    ["aws", "lambda", "create-function", "--region", REGION, "--function-name", gate.function_name,
                     "--runtime", "nodejs20.x", "--role", arn, "--handler", "index.handler", "--timeout", "29",
                     "--memory-size", "256", "--environment", environment, "--zip-file", f"fileb://{package.name}",
                     "--output", "json"],
                    capture_output=True, text=True,
                )
                if made.returncode == 0:
                    break
                if "cannot be assumed" in made.stderr or "InvalidParameterValueException" in made.stderr:
                    time.sleep(3)
                    continue
                raise GateError((made.stderr or f"could not create the {gate.label} key gate").strip().splitlines()[-1])
            else:
                raise GateError(f"the {gate.label} key gate role could not be assumed yet")
        else:
            if current["Configuration"].get("CodeSha256") != digest:
                _aws("lambda", "update-function-code", "--function-name", gate.function_name, "--zip-file", f"fileb://{package.name}")
                _settled(gate)
            if (current["Configuration"].get("Environment") or {}).get("Variables") != gate.environment:
                _aws("lambda", "update-function-configuration", "--function-name", gate.function_name, "--environment", environment)
    _settled(gate)
    return _function_url(gate.function_name)

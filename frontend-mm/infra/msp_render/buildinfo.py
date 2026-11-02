"""Load and validate what the hosting is rendered from.

    agents/<id>/manifest.json   one per agent in infra/agents.txt: how its API is reached and which outside hosts its screens call
    out/.msp-build.json         the dashboard build's, written by scripts/export-hashes.mjs: the SHA-256 of every inline script

Everything in these files ends up inside a CloudFront Function, an HTTP header or the distribution, so every value
is checked against a strict allow-list here. A value that does not fit is an error, never silently dropped or
passed through.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SHA256_SOURCE = re.compile(r"^'sha256-[A-Za-z0-9+/]{43}='\Z")
AGENT_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
# A DNS name with at least two labels whose last label starts with a letter (this rejects IP addresses).
ORIGIN_DOMAIN = re.compile(rf"^(?:{_LABEL}\.)+[a-z](?:[a-z0-9-]{{0,61}}[a-z0-9])?\Z")
_SEGMENT = r"[A-Za-z0-9._~-]+"
URL_PATH = re.compile(rf"^/(?:{_SEGMENT}/)*(?:{_SEGMENT})?\Z")
# One CSP host source: https or wss, optional "*." wildcard, optional port, no path.
HOST_SOURCE = re.compile(r"^(?:https|wss)://(?:\*\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?::[0-9]{1,5})?\Z")

EXTERNAL_HOST_KEYS = ("font-src", "img-src", "connect-src", "style-src")
# Scheme sources allowed besides hosts (data: for fonts and images and blob: for images are common and low risk).
# style-src may also repeat the two keywords every policy already carries ('self' 'unsafe-inline'); they are merged.
SCHEME_SOURCES = {"font-src": ("data:",), "img-src": ("data:", "blob:"), "connect-src": (), "style-src": ("'self'", "'unsafe-inline'")}
REQUIRED_MANIFEST_KEYS = ("id", "apiProxy", "externalHosts")
KNOWN_MANIFEST_KEYS = REQUIRED_MANIFEST_KEYS + ("needsAws", "note", "rewrites")


class Report:
    """Collects every problem so the builder sees all of them in one run."""

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


@dataclass(frozen=True)
class ApiProxy:
    prefix: str
    origin_domain: str
    origin_path: str
    note: str = ""


def _no_hosts() -> Dict[str, List[str]]:
    return {key: [] for key in EXTERNAL_HOST_KEYS}


@dataclass
class Agent:
    """One validated agents/<id>/manifest.json."""

    agent_id: str
    api_proxy: List[ApiProxy] = field(default_factory=list)
    external_hosts: Dict[str, List[str]] = field(default_factory=_no_hosts)
    needs_aws: List[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Shell:
    """The validated out/.msp-build.json: the inline scripts of the dashboard's pages (which now hold every agent's screens)."""

    script_hashes: List[str] = field(default_factory=list)
    external_hosts: Dict[str, List[str]] = field(default_factory=_no_hosts)
    needs_aws: List[str] = field(default_factory=list)
    notes: str = ""


def _read_json(path: Path, report: Report, where: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        report.error(where, "file not found")
        return None
    except (OSError, ValueError) as exc:
        report.error(where, f"not readable JSON ({exc})")
        return None
    if not isinstance(data, dict):
        report.error(where, "the top level must be a JSON object")
        return None
    return data


def _string_list(value: Any, where: str, report: Report) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        report.error(where, "must be a list of strings")
        return []
    return list(value)


def _script_hashes(value: Any, where: str, report: Report) -> List[str]:
    hashes: List[str] = []
    for index, item in enumerate(_string_list(value, where, report)):
        if not SHA256_SOURCE.match(item):
            report.error(f"{where}[{index}]", f"not a CSP sha256 source like 'sha256-<44 base64 chars>' (got {item!r})")
        elif item not in hashes:
            hashes.append(item)
    return hashes


def _host_source_ok(item: str) -> bool:
    match = HOST_SOURCE.match(item)
    if not match:
        return False
    labels = match.group(1).split(".")
    # "https://*.com" or "https://com" would allow far too much; a wildcard needs a registrable name behind it.
    return len(labels) >= 2 and labels[-1].isalpha()


def _external_hosts(value: Any, where: str, report: Report) -> Dict[str, List[str]]:
    hosts = _no_hosts()
    if not isinstance(value, dict):
        report.error(where, "must be an object with font-src, img-src, connect-src and style-src lists")
        return hosts
    for key, raw in value.items():
        if key not in hosts:
            report.error(
                f"{where}.{key}",
                "unknown key; only font-src, img-src, connect-src, style-src are allowed "
                "(script sources are the dashboard build's inline-script hashes only: nothing else may run)",
            )
            continue
        for index, item in enumerate(_string_list(raw, f"{where}.{key}", report)):
            if item in SCHEME_SOURCES[key] or _host_source_ok(item):
                if item not in hosts[key]:
                    hosts[key].append(item)
            else:
                report.error(
                    f"{where}.{key}[{index}]",
                    f"{item!r} is not an https:// or wss:// host source (no path, no quotes, no spaces, no semicolon, "
                    f"no http://; extra sources allowed here: {', '.join(SCHEME_SOURCES[key]) or 'none'})",
                )
    return hosts


def _dot_segments(path: str) -> bool:
    return any(segment in (".", "..") for segment in path.split("/"))


def _path_ok(path: str) -> bool:
    return bool(URL_PATH.match(path)) and not _dot_segments(path)


def _api_proxy(value: Any, agent_id: str, where: str, report: Report) -> List[ApiProxy]:
    if not isinstance(value, list):
        report.error(where, "must be a list")
        return []
    api_root = f"/agents/{agent_id}/api/"
    # Only the API is proxied: everything else under /agents/<id>/ is a static file of the site, so a prefix outside api/ would hide files.
    prefix_ok = re.compile(rf"^{re.escape(api_root)}(?:{_SEGMENT}/)*\Z")
    result: List[ApiProxy] = []
    for index, item in enumerate(value):
        here = f"{where}[{index}]"
        if not isinstance(item, dict):
            report.error(here, "must be an object")
            continue
        prefix, domain, origin_path = item.get("prefix"), item.get("originDomain"), item.get("originPath")
        ok = True
        if not isinstance(prefix, str) or not prefix_ok.match(prefix) or _dot_segments(prefix):
            report.error(f"{here}.prefix", f"must be {api_root} or a folder below it, and end with / (got {prefix!r})")
            ok = False
        if not isinstance(domain, str) or not ORIGIN_DOMAIN.match(domain):
            report.error(f"{here}.originDomain", f"must be a bare lowercase host name, no scheme, port or path (got {domain!r})")
            ok = False
        if origin_path == "":
            origin_path = "/"  # the origin's root, e.g. an API Gateway $default stage
        if not isinstance(origin_path, str) or not _path_ok(origin_path):
            report.error(f"{here}.originPath", f"must be an absolute path of plain segments like /api/, or empty for the origin's root (got {origin_path!r})")
            ok = False
        if not ok:
            continue
        if any(p.prefix == prefix for p in result):
            report.error(f"{here}.prefix", f"{prefix} is listed twice")
            continue
        note = item.get("note", "")
        result.append(ApiProxy(prefix, domain, origin_path if origin_path.endswith("/") else origin_path + "/", note if isinstance(note, str) else ""))
    return result


def load_manifest(path: Path, agent_id: str, report: Report) -> Optional[Agent]:
    """Validate agents/<id>/manifest.json. Returns None if anything is wrong (the problems are in report)."""
    where = f"agents/{agent_id}/manifest.json"
    before = len(report.errors)
    data = _read_json(path, report, where)
    if data is None:
        return None
    for key in REQUIRED_MANIFEST_KEYS:
        if key not in data:
            report.error(where, f"required key {key!r} is missing")
    for key in data:
        if key == "scriptHashes":
            report.error(
                where,
                "scriptHashes does not belong in a manifest: the whole site has one script policy, built from the dashboard build's "
                "out/.msp-build.json (every agent's screens are part of that build)",
            )
        elif key not in KNOWN_MANIFEST_KEYS:
            report.warn(where, f"unknown key {key!r} is ignored")
    if data.get("rewrites") not in (None, []):
        report.error(
            f"{where}.rewrites",
            f"must be empty or absent: /agents/{agent_id}/ (apart from api/) is static files of the site, not an app, so no route is rewritten",
        )
    if len(report.errors) > before:
        return None

    if data["id"] != agent_id:
        report.error(f"{where}.id", f"is {data['id']!r} but the folder is {agent_id!r}")
    note = data.get("note", "")
    if not isinstance(note, str):
        report.error(f"{where}.note", "must be a string")
    agent = Agent(
        agent_id=agent_id,
        api_proxy=_api_proxy(data["apiProxy"], agent_id, f"{where}.apiProxy", report),
        external_hosts=_external_hosts(data["externalHosts"], f"{where}.externalHosts", report),
        needs_aws=_string_list(data.get("needsAws", []), f"{where}.needsAws", report),
        note=note if isinstance(note, str) else "",
    )
    return agent if len(report.errors) == before else None


def load_shell(path: Path, report: Report) -> Optional[Shell]:
    """Validate out/.msp-build.json: only scriptHashes is required; externalHosts, needsAws and notes are optional."""
    where = "shell/.msp-build.json"
    before = len(report.errors)
    data = _read_json(path, report, where)
    if data is None:
        return None
    if "scriptHashes" not in data:
        report.error(where, "required key 'scriptHashes' is missing")
    for key in ("apiProxy", "rewrites"):
        if key in data:
            report.error(where, f"the shell has no {key}; the API proxies are in agents/<id>/manifest.json")
    if data.get("id", "shell") != "shell":
        report.error(f"{where}.id", f"must be 'shell' if present (got {data['id']!r})")
    for key in data:
        if key not in ("id", "scriptHashes", "externalHosts", "needsAws", "notes", "apiProxy", "rewrites"):
            report.warn(where, f"unknown key {key!r} is ignored")
    if len(report.errors) > before:
        return None
    shell = Shell(
        script_hashes=_script_hashes(data["scriptHashes"], f"{where}.scriptHashes", report),
        external_hosts=_external_hosts(data.get("externalHosts", {}), f"{where}.externalHosts", report),
        needs_aws=_string_list(data.get("needsAws", []), f"{where}.needsAws", report),
        notes=data["notes"] if isinstance(data.get("notes"), str) else "",
    )
    return shell if len(report.errors) == before else None


def load_agents(manifests_dir: Path, ids: List[str], report: Report) -> List[Agent]:
    """Every id in the list must have a valid manifest, and no manifest may exist for an id that is not in the list."""
    agents: List[Agent] = []
    for agent_id in ids:
        agent = load_manifest(manifests_dir / agent_id / "manifest.json", agent_id, report)
        if agent:
            agents.append(agent)
    if manifests_dir.is_dir():
        for found in sorted(path.parent.name for path in manifests_dir.glob("*/manifest.json")):
            if found not in ids:
                report.error(f"agents/{found}/manifest.json", "this agent is not in infra/agents.txt: add the id there or remove the folder")
    return sorted(agents, key=lambda agent: agent.agent_id)


def read_agent_ids(path: Path) -> List[str]:
    ids: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if not AGENT_ID.match(line) or len(line) > 24:
            raise ValueError(f"{path}: {line!r} is not a valid agent id (lowercase letters, digits, single hyphens; at most 24)")
        if line in ids:
            raise ValueError(f"{path}: {line!r} is listed twice")
        ids.append(line)
    # An empty list is allowed: the dashboard then serves its own pages only, with no API proxy, until an agent is connected.
    return ids

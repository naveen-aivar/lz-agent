"""Checks of the assembled site (.build/site) against what was declared.

The most important one: every inline <script> in every HTML file must have its SHA-256 in the dashboard build's
scriptHashes (out/.msp-build.json), because the Content-Security-Policy allows no other inline script. A page that
fails this check would load blank in the browser, so the deploy stops here instead.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .buildinfo import Agent, Report, Shell

EXECUTABLE_SCRIPT_TYPES = {
    "", "module", "importmap", "text/javascript", "application/javascript", "application/x-javascript",
    "text/ecmascript", "application/ecmascript", "text/jscript", "text/livescript",
}
LEAKED_NAMES = {".msp-build.json", "NOTES.md", ".DS_Store"}
SECRET_PATTERN = re.compile(rb"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:aws_secret_access_key)")
EXTERNAL_SRC = re.compile(r"^(?:https?:)?//", re.I)


def script_source_hash(text: str) -> str:
    """The CSP source for an inline script's text, as a browser computes it (line endings normalised to LF)."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return "'sha256-" + base64.b64encode(hashlib.sha256(normalised.encode("utf-8")).digest()).decode("ascii") + "'"


class _PageScan(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.inline: List[str] = []  # text of every executable inline script
        self.external: List[str] = []  # script src values that point at another host
        self.handler_attributes: Set[str] = set()
        self._body: Optional[List[str]] = None
        self._executable = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = {name: (value or "") for name, value in attrs}
        self.handler_attributes.update(name for name in values if name.startswith("on") and len(name) > 2)
        if tag != "script":
            return
        if "src" in values:
            if EXTERNAL_SRC.match(values["src"]):
                self.external.append(values["src"])
            return
        self._executable = values.get("type", "").strip().lower() in EXECUTABLE_SCRIPT_TYPES
        self._body = []

    def handle_data(self, data: str) -> None:
        if self._body is not None:
            self._body.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._body is not None:
            text = "".join(self._body)
            if self._executable and text != "":
                self.inline.append(text)
            self._body = None


def scan_html(text: str) -> _PageScan:
    scan = _PageScan()
    scan.feed(text)
    scan.close()
    return scan


def _check_html(path: Path, relative: str, declared: Set[str], used: Set[str], report: Report) -> None:
    scan = scan_html(path.read_text(encoding="utf-8", errors="replace"))
    for text in scan.inline:
        digest = script_source_hash(text)
        if digest in declared:
            used.add(digest)
        else:
            snippet = " ".join(text.split())[:70]
            report.error(relative, f"inline script {digest} is not in scriptHashes, the page would be blocked by the CSP (starts: {snippet!r})")
    for source in scan.external:
        report.error(relative, f"loads a script from another host ({source}); script-src allows only this site and the declared hashes")
    if scan.handler_attributes:
        report.warn(relative, f"inline event handler attributes ({', '.join(sorted(scan.handler_attributes))}) are blocked by the CSP")


def check_site(site: Path, shell: Shell, agents: List[Agent], report: Report) -> Dict[str, int]:
    """Verify the site folder. Problems go to report; returns {'files': n, 'bytes': n}."""
    stats = {"files": 0, "bytes": 0}
    if not site.is_dir():
        report.error(str(site), "the assembled site folder does not exist (run scripts/assemble.sh)")
        return stats
    if not (site / "index.html").is_file():
        report.error("site", "index.html is missing at the root: the dashboard is not there")

    # What the proxy answers instead of S3: a static file under an API prefix could never be served.
    api_prefixes = [proxy.prefix.lstrip("/") for agent in agents for proxy in agent.api_proxy]
    agent_ids = {agent.agent_id for agent in agents}
    declared = set(shell.script_hashes)
    used: Set[str] = set()

    # agents/<id>/ holds only static files copied from public/agents/<id>/; an agent without any has no folder.
    present = {entry.name for entry in (site / "agents").iterdir()} if (site / "agents").is_dir() else set()
    for extra in sorted(present - agent_ids):
        report.error(f"site/agents/{extra}", "is not a known agent (see infra/agents.txt)")

    for directory, _, names in os.walk(site):
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(site).as_posix()
            stats["files"] += 1
            stats["bytes"] += path.stat().st_size
            if name in LEAKED_NAMES or name.endswith(".map"):
                report.error(f"site/{relative}", "must not be published (build metadata, notes, junk or a source map)")
            if SECRET_PATTERN.search(path.read_bytes()):
                report.error(f"site/{relative}", "looks like it contains a credential (AWS access key, private key or secret key name)")
            if any(relative.startswith(prefix) for prefix in api_prefixes):
                report.error(f"site/{relative}", "is under an API proxy prefix, so CloudFront would send the request to the agent's API and never serve this file")
            if name.endswith(".html"):
                _check_html(path, relative, declared, used, report)

    for stale in sorted(declared - used):
        report.warn("shell/.msp-build.json", f"scriptHashes lists {stale}, which no HTML file in the site uses (it widens the CSP for nothing)")
    return stats

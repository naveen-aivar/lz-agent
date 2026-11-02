#!/usr/bin/env python3
"""A stand-in for the real `npm run build`, for the script tests (infra/test_scripts.sh): writes a small static export of the
dashboard into a folder, the way Next leaves out/, with the inline scripts declared in shell/.msp-build.json and the static
files that public/agents/<id>/ would contribute (out/agents/<id>/...).

    fake_build.py <outDir>
"""
import json
import shutil
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent
# Static files per agent (public/agents/<id>/ in the repo). wafr and backupdr have none: an agent without static files must work too.
AGENT_STATIC = {
    "devops": {"images/logo.png": "png bytes", "samples/alarm.json": '{"alarm": 1}\n'},
    "secops": {"samples/findings.csv": "id,severity\n1,high\n"},
    "sre": {"img/topology.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>"},
    "onboarding": {"templates/checklist.docx": "docx bytes"},
}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def page(count: int, assets: str, title: str) -> str:
    scripts = "".join(f"<script>shell inline script {i}</script>" for i in range(count))
    return (
        f'<!doctype html><html><head><meta charSet="utf-8"/><title>{title}</title>'
        f'<link rel="stylesheet" href="{assets}.css"/></head><body><div id="root">{title}</div>{scripts}'
        f'<script src="{assets}.js" async></script></body></html>'
    )


def main() -> None:
    out = Path(sys.argv[1])
    info = json.loads((FIXTURES / "shell" / ".msp-build.json").read_text())
    assets = "/_next/static/chunks/app-0123456789abcdef"
    write(out / "index.html", page(len(info["scriptHashes"]), assets, "MSP dashboard"))
    write(out / "index.txt", "rsc payload")
    write(out / "404.html", "<!doctype html><title>404</title>")
    write(out / "favicon.ico", "ico")
    write(out / "_next/static/chunks/app-0123456789abcdef.js", "console.log('dashboard')")
    write(out / "_next/static/chunks/app-0123456789abcdef.css", "body{}")
    for agent_id, files in AGENT_STATIC.items():
        for relative, text in files.items():
            write(out / "agents" / agent_id / relative, text)
    shutil.copy(FIXTURES / "shell" / ".msp-build.json", out / ".msp-build.json")


main()

#!/usr/bin/env python3
"""Render the CloudFormation template and the two CloudFront Functions of the MSP dashboard.

Reads   agents/<id>/manifest.json    (one per agent in infra/agents.txt: its API proxy and the outside hosts its screens call)
        out/.msp-build.json          (the dashboard build's: the SHA-256 of every inline script, written by scripts/export-hashes.mjs)
Writes  .build/template.json   CloudFormation template (JSON)
        .build/router.js       viewer-request CloudFront Function (also inside the template)
        .build/headers.js      viewer-response CloudFront Function (also inside the template)
        .build/summary.txt     what was rendered, open items, warnings
        .build/smoke.txt       the pages scripts/deploy.sh checks after a deploy

Nothing is written when anything is wrong. Python 3 standard library only (Node runs the checks of the JavaScript).

  python3 infra/render.py                          render
  python3 infra/render.py --check-site .build/site render, then check the assembled site against the declarations
  python3 infra/render.py --check-manifests        only validate agents/<id>/manifest.json (fast; assemble.sh does this before the build)
Exit status: 0 ok, 1 the declarations or the site do not pass, 2 the tool itself cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from msp_render.buildinfo import Agent, Report, Shell, load_agents, load_shell, read_agent_ids  # noqa: E402
from msp_render.functions import check_size, render_headers, render_router, self_check  # noqa: E402
from msp_render.jsnode import NodeMissing  # noqa: E402
from msp_render.sitecheck import check_site  # noqa: E402
from msp_render.summary import build_summary, smoke_lines  # noqa: E402
from msp_render.template import build_template, check_limits  # noqa: E402

INFRA = Path(__file__).resolve().parent
ROOT = INFRA.parent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="frontend-msp folder (default: the parent of infra/)")
    parser.add_argument("--manifests-dir", type=Path, help="folder holding <id>/manifest.json (default: <root>/agents)")
    parser.add_argument("--shell-file", type=Path, help="the dashboard build's .msp-build.json (default: <root>/out/.msp-build.json)")
    parser.add_argument("--out-dir", type=Path, help="where to write the results (default: <root>/.build)")
    parser.add_argument("--agent-list", type=Path, help="the list of agent ids (default: infra/agents.txt)")
    parser.add_argument("--check-site", type=Path, metavar="DIR", help="also check the assembled site folder (default location: <root>/.build/site)")
    parser.add_argument("--check-manifests", action="store_true", help="only validate the agents' manifests, write nothing")
    parser.add_argument("--quiet", action="store_true", help="print only problems")
    return parser


def _load_agents(args: argparse.Namespace, report: Report) -> List[Agent]:
    """The valid manifests (problems of the others go to report)."""
    try:
        ids = read_agent_ids(args.agent_list or INFRA / "agents.txt")
    except (OSError, ValueError) as exc:
        report.error("agents list", str(exc))
        return []
    return load_agents(args.manifests_dir or args.root / "agents", ids, report)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    args.root = args.root.resolve()
    out_dir = (args.out_dir or args.root / ".build").resolve()
    report = Report()

    result = 1
    try:
        agents = _load_agents(args, report)
        shell = None if args.check_manifests else load_shell(args.shell_file or args.root / "out" / ".msp-build.json", report)
        if report.errors:
            pass  # every problem of the manifests and of the shell file is reported together below
        elif shell is None:
            result = 0
            if not args.quiet:
                print(f"manifests ok: {len(agents)} agents ({', '.join(agent.agent_id for agent in agents)})")
        else:
            result = _render(args, out_dir, shell, agents, report)
    except NodeMissing as exc:
        print(f"render: {exc}", file=sys.stderr)
        return 2
    except (ValueError, RuntimeError) as exc:
        report.error("render", str(exc))

    for text in report.warnings:
        print(f"warning: {text}", file=sys.stderr)
    for text in report.errors:
        print(f"error: {text}", file=sys.stderr)
    if report.errors:
        print(f"render: {len(report.errors)} problem(s); nothing was written", file=sys.stderr)
        return 1
    return result


def _render(args: argparse.Namespace, out_dir: Path, shell: Shell, agents: List[Agent], report: Report) -> int:
    router = render_router(agents)
    headers = render_headers(shell, agents)
    check_size("router.js", router, report.warnings)
    check_size("headers.js", headers, report.warnings)
    self_check(router, headers, agents)

    template = build_template(agents, router, headers)
    template_json = json.dumps(template, indent=2) + "\n"
    if len(template_json.encode("utf-8")) > 51_200:
        template_json = json.dumps(template, separators=(",", ":")) + "\n"
    for problem in check_limits(agents, template_json):
        report.error("template", problem)

    stats = {}
    if args.check_site:
        stats = check_site(args.check_site.resolve(), shell, agents, report)
    if report.errors:
        return 1

    sizes = {"template": len(template_json.encode()), "router": len(router.encode()), "headers": len(headers.encode())}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "template.json").write_text(template_json, encoding="utf-8")
    (out_dir / "router.js").write_text(router, encoding="utf-8")
    (out_dir / "headers.js").write_text(headers, encoding="utf-8")
    (out_dir / "smoke.txt").write_text(smoke_lines(shell, agents), encoding="utf-8")
    summary = build_summary(shell, agents, sizes, report.warnings, stats)
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")
    if not args.quiet:
        print(summary, end="")
        print(f"rendered into {out_dir}: template.json router.js headers.js summary.txt smoke.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The human summary (summary.txt) and the machine list the deploy smoke test reads (smoke.txt)."""

from __future__ import annotations

from typing import Dict, List

from .buildinfo import EXTERNAL_HOST_KEYS, Agent, Shell
from .functions import MAX_FUNCTION_BYTES, content_security_policy, union_external_hosts
from .template import MAX_BEHAVIORS, MAX_ORIGINS, MAX_TEMPLATE_BYTES, api_behaviors, api_origins


def smoke_lines(shell: Shell, agents: List[Agent]) -> str:
    """What scripts/deploy.sh checks after a deploy, one line each, '|' separated:

        shell||/|<first script hash>         the dashboard page
        agent|<id>|/agents/<id>/|            one static file of the agent (only if the site has some under that folder)
        api|<id>|<prefix>|                   an API proxy path (only probed, never failed on)

    The deploy script requires the CSP header of the dashboard page to contain its first script hash (empty field: none
    declared), which proves the right policy reached the page.
    """
    lines = ["shell||/|" + (shell.script_hashes[0] if shell.script_hashes else "")]
    lines.extend(f"agent|{agent.agent_id}|/agents/{agent.agent_id}/|" for agent in agents)
    for agent in agents:
        lines.extend(f"api|{agent.agent_id}|{proxy.prefix}|" for proxy in agent.api_proxy)
    return "\n".join(lines) + "\n"


def build_summary(
    shell: Shell,
    agents: List[Agent],
    sizes: Dict[str, int],
    warnings: List[str],
    site_stats: Dict[str, int],
) -> str:
    out: List[str] = []
    add = out.append
    add("Migration and Modernization dashboard: what was rendered")
    add("")
    add(f"template.json   {sizes['template']:>6} bytes (limit {MAX_TEMPLATE_BYTES})")
    add(f"router.js       {sizes['router']:>6} bytes (limit {MAX_FUNCTION_BYTES})")
    add(f"headers.js      {sizes['headers']:>6} bytes (limit {MAX_FUNCTION_BYTES})")
    add(f"distribution    {len(api_origins(agents)) + 1} origins (1 S3 + {len(api_origins(agents))} API, limit {MAX_ORIGINS}), "
        f"{len(api_behaviors(agents))} extra cache behaviors (limit {MAX_BEHAVIORS}) + the default one")
    if site_stats:
        add(f"site            {site_stats['files']} files, {site_stats['bytes'] / 1_048_576:.1f} MiB")
    add("")
    add(f"Content-Security-Policy (one for the whole site): {len(content_security_policy(shell, agents))} characters, "
        f"{len(shell.script_hashes)} inline-script hashes from the dashboard build")
    union = union_external_hosts(shell, agents)
    for host_key in EXTERNAL_HOST_KEYS:
        if union[host_key]:
            add(f"  {host_key}: {' '.join(union[host_key])}")
    add("")
    add("Agents (their screens are part of the dashboard; only the API is proxied, /agents/<id>/ otherwise is static files)")
    for agent in agents:
        add(f"  {agent.agent_id:<11} {len(agent.api_proxy)} API proxies")
        for proxy in agent.api_proxy:
            add(f"      api      {proxy.prefix}* -> https://{proxy.origin_domain}{proxy.origin_path}" + (f"   ({proxy.note})" if proxy.note else ""))
        for host_key in EXTERNAL_HOST_KEYS:
            if agent.external_hosts[host_key]:
                add(f"      {host_key}: {' '.join(agent.external_hosts[host_key])}")
    add("")
    add("API origins (one CloudFront origin per distinct domain)")
    for domain in api_origins(agents):
        users = sorted({agent.agent_id for agent in agents for proxy in agent.api_proxy if proxy.origin_domain == domain})
        add(f"  {domain}   used by {', '.join(users)}")

    open_items = [("shell", text) for text in shell.needs_aws] + [(agent.agent_id, text) for agent in agents for text in agent.needs_aws]
    add("")
    add("Open items from the builders (needsAws), for the integrator to review and apply; nothing here was applied")
    for who, text in open_items:
        add(f"  [{who}] {text}")
    if not open_items:
        add("  none")
    notes = ([("shell", shell.notes)] if shell.notes else []) + [(agent.agent_id, agent.note) for agent in agents if agent.note]
    if notes:
        add("")
        add("Notes from the builders")
        for who, text in notes:
            add(f"  [{who}] {text}")
    add("")
    add(f"Warnings ({len(warnings)})")
    for text in warnings:
        add(f"  {text}")
    if not warnings:
        add("  none")
    return "\n".join(out) + "\n"

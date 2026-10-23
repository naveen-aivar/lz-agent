"""Render / copy IaC bundles for a deploy run (shared by agent tools and orchestration Lambda)."""
from __future__ import annotations

import json
from typing import Any, Callable

from lzcore import render
from lzcore.deploy_workflow import should_deliver_design_bundles
from lzcore.iac_plan import build_manifest


def render_deploy_iac(
    *,
    run_id: str,
    scope: dict,
    plan: dict,
    design_artifacts: dict,
    base_prefix: str,
    put_json: Callable[[str, dict], None],
    put_bytes: Callable[[str, bytes], None],
    copy_object: Callable[[str, str], None],
    record_artifact: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Write iac-manifest.json and optional terraform/cloudformation zips on the deploy run."""
    base = f"{base_prefix.rstrip('/')}/deployment"
    manifest = build_manifest(scope, plan)
    manifest_key = f"{base}/iac-manifest.json"
    put_json(manifest_key, manifest)
    if record_artifact:
        record_artifact("iac-manifest", manifest_key)

    delivered: list[str] = []
    if should_deliver_design_bundles(plan):
        design_tf = (design_artifacts or {}).get("terraform")
        design_cfn = (design_artifacts or {}).get("cloudformation")
        if design_tf and design_cfn:
            for fmt, src in (("terraform", design_tf), ("cloudformation", design_cfn)):
                dest = f"{base_prefix.rstrip('/')}/{fmt}.zip"
                copy_object(src["key"], dest)
                if record_artifact:
                    record_artifact(fmt, dest)
                delivered.append(fmt)
        else:
            for fmt, files in render.render_all(scope).items():
                for name, content in files.items():
                    put_bytes(f"{base}/bundle-src/{fmt}/{name}", content.encode())
                zkey = f"{base_prefix.rstrip('/')}/{fmt}.zip"
                put_bytes(zkey, render.zip_bytes(files, fmt))
                if record_artifact:
                    record_artifact(fmt, zkey)
                delivered.append(fmt)

    return {"runId": run_id, "delivered": delivered, "manifestKey": manifest_key}

"""A small helper that runs the generated CloudFront Functions in Node, so they are judged by a real JavaScript engine
rather than by a Python look-alike."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Dict, List

# Loads a generated function the way CloudFront does (a plain script, strict mode, no module system) and calls it.
_RUN_FUNCTION = r"""
const vm = require('vm');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = input.cases.map((event) => {
  const sandbox = vm.createContext({});
  vm.runInContext('"use strict";\n' + input.code, sandbox, { timeout: 1000 });
  const handler = vm.runInContext('handler', sandbox);
  const result = handler(JSON.parse(JSON.stringify(event)));
  return JSON.parse(JSON.stringify(result));
});
process.stdout.write(JSON.stringify(out));
"""


class NodeMissing(RuntimeError):
    pass


def _node() -> str:
    path = shutil.which("node")
    if not path:
        raise NodeMissing("node is required (the generated functions are checked with it)")
    return path


def _run(script: str, payload: Dict[str, Any]) -> Any:
    result = subprocess.run(
        [_node(), "-e", script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"node failed: {result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout)


def run_function(code: str, events: List[Dict[str, Any]]) -> List[Any]:
    """Run handler(event) of a CloudFront Function's code for each event; returns what each call returned."""
    return _run(_RUN_FUNCTION, {"code": code, "cases": events})

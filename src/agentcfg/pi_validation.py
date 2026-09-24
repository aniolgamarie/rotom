"""离线验证调度：固定测试清单、临时 HOME 与独立结果。"""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile

from .deployment import json_bytes
from .storage import Tree


ROOT = Path(__file__).resolve().parents[2]
CASES = {
  "host-resources": ("test_pi_host.py", "test_pi_resource_discovery.py", "test_pi_validation_runtime.py"),
  "migration-conflicts": ("test_pi_migration_flow.py", "test_pi_capture.py", "test_pi_inventory.py"),
  "budget-permissions": ("test_pi_guarded_files.py", "test_pi_operations.py", "test_pi_commands.py", "test_pi_native_roots.py"),
  "termination-recovery": ("test_pi_supervisor.py", "test_pi_activity_linux.py", "test_pi_activity_macos.py", "test_pi_recovery.py", "test_pi_workspace_leases.py", "test_pi_validation_parent_loss.py", "test_pi_validation_recovery.py"),
  "codex-receipts": ("test_model_delegate_contract.py", "test_model_delegate_cli.py", "test_model_delegate_codex_worker.py"),
  "model-delegate-replacement": ("test_pi_delegate_retirement.py", "test_pi_delegate.py", "test_model_delegate_batch.py"),
  "dsh-compatibility": ("test_cli.py", "test_isolation.py", "test_config_schema.py"),
  "taskkeeper-lifecycle": ("test_pi_worker_protocol.py", "test_pi_checks.py", "test_pi_worker_files.py"),
  "cold-rebuild": ("test_pi_cold_rebuild.py",),
  "optional-services": ("test_pi_mcp_stdio.py", "test_pi_services.py", "test_pi_web.py", "test_pi_validation_live_services.py"),
}


def execute(args):
  if args.tier == "native":
    from .pi_validation_native import execute as execute_native
    return execute_native(args)
  if args.tier != "mock":
    from .pi_validation_live import execute as execute_live
    return execute_live(args)
  selected = list(CASES) if args.case == "all" else [args.case]
  files = sorted({file for name in selected for file in CASES[name]})
  missing = [file for file in files if not (ROOT / "tests" / file).is_file()]
  if missing:
    return {"schema_version": 1, "tier": "mock", "case": args.case, "status": "not-run", "reason": "scenario-tests-missing", "missing": missing, "results": []}
  python = ROOT / ".venv/bin/python"
  command = [str(python), "-m", "pytest", "-q", *(["tests"] if args.case == "all" else ["tests/" + file for file in files])]
  with tempfile.TemporaryDirectory(prefix="agentcfg-pi-verify-") as temp:
    root = Path(temp); home = root / "home"; home.mkdir(mode=0o700)
    env = {"PATH": os.defpath, "HOME": str(home), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
      **{key: str(home / key.lower()) for key in ("PI_CODING_AGENT_DIR", "CODEX_HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")}}
    for value in env.values():
      if value.startswith(str(home) + "/"): Path(value).mkdir(mode=0o700)
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    logs = args.output.absolute().parent / (args.output.name + ".artifacts")
    commands = [("pytest", command)]
    if args.case in ("all", "budget-permissions", "termination-recovery", "model-delegate-replacement", "taskkeeper-lifecycle", "optional-services"):
      node = shutil.which("node")
      if not node:
        return {"schema_version": 1, "tier": "mock", "case": args.case, "status": "not-run", "reason": "node-test-runtime-missing", "results": []}
      patterns = ["agents/pi/runtime/tests/*.test.ts", "agents/pi/packages/task-keeper/tests/agentcfg-*.test.ts",
        "agents/pi/packages/task-keeper/tests/request-ledger.test.ts", "agents/pi/packages/task-keeper/tests/one-shot-schedule.test.ts",
        "agents/pi/packages/model-delegate/tests/bridge.test.ts", "agents/pi/packages/openai-proxy/routing.test.mjs", "agents/pi/packages/openai-proxy/diagnostics.test.mjs"]
      node_files = sorted({str(path.relative_to(ROOT)) for pattern in patterns for path in ROOT.glob(pattern)})
      commands.append(("node", [node, "scripts/test-pi-mock.mjs", *node_files]))
    results = []
    for name, argv in commands:
      try:
        completed = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, timeout=1800)
        code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
      except subprocess.TimeoutExpired as error:
        code, stdout, stderr = None, error.stdout or b"", error.stderr or b""
      except OSError:
        code, stdout, stderr = None, b"", b"validation runner unavailable\n"
      with Tree(logs, create=True) as tree:
        tree.write_new(name + ".stdout", stdout)
        tree.write_new(name + ".stderr", stderr)
      results.append({"runner": name, "exit_code": code, "command": [".venv/bin/python" if name == "pytest" else "node", *argv[1:]],
        "artifact_refs": [logs.name + "/" + name + ".stdout", logs.name + "/" + name + ".stderr"]})
    finished = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"schema_version": 1, "tier": "mock", "case": args.case, "status": "passed" if all(row["exit_code"] == 0 for row in results) else "failed",
      "started_at": started, "finished_at": finished, "results": results,
      "limitations": ["mock-only; no native hosts or accounts"]}

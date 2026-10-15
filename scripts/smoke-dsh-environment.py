#!/usr/bin/env python3
"""Explicit native environment acceptance; isolated HOME, synthetic state, no accounts."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", required=True, type=Path)
  parser.add_argument("--evidence", required=True, type=Path)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("--allow-host is required; default tests never start hosts")
  os.umask(0o077)
  repository = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repository / "src"))
  from agentcfg import commands, dependencies, runtime, runtime_packages
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  lock = dependencies.read_lock(repository)
  package = args.runtime.absolute()
  if (runtime_packages.status(package, lock.identity) != "installed"
      or (package / "package.json").read_bytes() != lock.package
      or (package / "pnpm-lock.yaml").read_bytes() != lock.installer_resolution):
    parser.error("sealed runtime does not match the current lock")
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
  ensure_private(evidence)
  helper = importlib.util.spec_from_file_location("dsh_native_driver", repository / "scripts/smoke-dsh.py")
  driver = importlib.util.module_from_spec(helper)
  helper.loader.exec_module(driver)
  # 原生 bwrap 隔离 /tmp 和 /dev；哨兵需位于仍可见的只读文件系统中。
  with tempfile.TemporaryDirectory(prefix="rotom-dsh-environment-", dir="/var/tmp") as temporary:
    root = Path(temporary)
    env = {"PATH": os.environ.get("PATH", ""), "TERM": "xterm-256color", "LANG": "C.UTF-8",
      "CUSTOM_BUILD_VAR": "caller-build", "DELETED_BUILD_VAR": "caller-delete"}
    for name, suffix in {"HOME": "caller", "XDG_CONFIG_HOME": "caller-config", "TMPDIR": "tmp"}.items():
      env[name] = str(root / suffix)
      ensure_private(root / suffix)
    os.environ.clear()
    os.environ.update(env)
    project = root / "workspace"
    ensure_private(project)
    machine = root / "machine.toml"
    machine.write_text('schema_version=1\n[machine]\nid="environment-smoke"\n'
      '[machine.environment]\ninherit=["CUSTOM_BUILD_VAR"]\nunset=["DELETED_BUILD_VAR"]\n'
      '[overrides.providers.fixture]\nprotocol="openai-compatible"\nbase_url="http://127.0.0.1:9/v1"\n'
      'auth_kind="api-key"\ncredential_ref="secret:fixture"\n'
      '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-not-real"\ninput=["text"]\n'
      '[overrides.mcp.env-fixture]\ntransport="stdio"\n'
      f'command={json.dumps(shutil.which("node"))}\nargs=[{json.dumps(str(root / "environment-mcp-server.mjs"))}]\n'
      '[overrides.profiles.dsh-default]\nproviders=["fixture"]\nmodels=["fixture"]\nmcp=["env-fixture"]\n'
      '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n')
    machine.chmod(0o600)
    workspace = load_workspace(machine, "dsh-default", repository=repository)
    candidate = workspace.candidate(lock.identity)
    commands.apply_candidate(workspace, lock, candidate)
    with Tree(workspace.state_root) as state, instance_lock(state):
      workspace.adapter.prepare_runtime(workspace, package)
    contract = runtime.record(workspace, lock)
    spec = runtime.decode(contract, project, ())
    child_env, _ = runtime.prepare_environment(workspace, contract, spec)
    child_env["AGENTCFG_MCP_0123456789ABCDEF"] = "synthetic-internal-credential-never-forwarded"
    child_env.update(AGENTCFG_ENV_SMOKE_ROOT=str(root), AGENTCFG_ENV_SMOKE_RESULT=str(root / "result.json"),
      AGENTCFG_ENV_SMOKE_PATCH=str(workspace.instance / "dsh-home/agentcfg.patch.yml"))
    argv = ["node", str(repository / "scripts/smoke-dsh-environment.mjs"), str(package)]
    native = driver.run_native(argv, project, child_env, evidence / "transcript.log")
    result = json.loads((root / "result.json").read_text()) if (root / "result.json").exists() else {"status": "FAIL", "error": "NATIVE_RESULT_MISSING"}
    sources = sorted((repository / "src/agentcfg").glob("*.py")) + sorted((repository / "agents/dsh/packages/execution-environment").glob("*"))
    sources += [Path(__file__), repository / "scripts/smoke-dsh-environment.mjs", repository / "agents/dsh/templates/launch.mjs"]
    digests = {str(path.relative_to(repository)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    result.update(lock_identity=lock.identity, recipe=lock.metadata["recipe"], configuration=candidate.generation,
      source_files=digests, source_digest=hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest(),
      platform=sys.platform, native=native, real_accounts="NOT RUN", ptc="HOST_ENVIRONMENT_ONLY", subagents="NOT RUN")
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    success = result.get("status") == "PASS" and result.get("native_complete") and native["exit"] == 0 and not native["forced_termination"]
    print(json.dumps({"status": "PASS" if success else "FAIL", "checks": result.get("checks", {}), "evidence": str(evidence)}))
    return 0 if success else 1


if __name__ == "__main__":
  raise SystemExit(main())

#!/usr/bin/env python3
"""显式 Teams 原生验收：官方 bundle、真实会话与确定性无账号模型。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", required=True, type=Path)
  parser.add_argument("--evidence", required=True, type=Path)
  args = parser.parse_args(argv)
  if not args.allow_host:
    parser.error("需要 --allow-host；默认测试不启动第三方宿主")
  repo = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repo / "src"))
  from agentcfg import commands, dependencies, profile_runtime, runtime_packages
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  lock = dependencies.read_lock(repo)
  runtime = args.runtime.absolute()
  if (runtime_packages.status(runtime, lock.identity) != "installed"
      or (runtime / "package.json").read_bytes() != lock.package
      or (runtime / "pnpm-lock.yaml").read_bytes() != lock.installer_resolution):
    parser.error("runtime 收据与当前完整锁不匹配")
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  if any(evidence.iterdir()):
    parser.error("使用新的空证据目录")
  outer_path = os.environ.get("PATH", "")
  with tempfile.TemporaryDirectory(prefix="rotom-team-native-", dir="/dev/shm") as temporary:
    root = Path(temporary)
    env = {"PATH": outer_path, "LANG": "C.UTF-8", "TERM": "xterm-256color",
      "DSH_PERMISSION_MODE": "workspace-write", "DSH_TELEMETRY_DISABLED": "1"}
    for key, suffix in {"HOME": "home", "DSH_HOME": "dsh", "XDG_CONFIG_HOME": "config",
        "XDG_DATA_HOME": "data", "XDG_STATE_HOME": "state", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}.items():
      env[key] = str(root / suffix)
      ensure_private(root / suffix)
    os.environ.clear()
    os.environ.update(env)
    node = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True, check=True).stdout.strip()
    if node != lock.metadata["node"]:
      parser.error("需要完整锁要求的精确 Node 版本")
    project = root / "workspace"
    ensure_private(project)
    headless = root / "headless.patch.yml"
    headless.write_text("\n".join("- id: " + name + "\n  disabled: true" for name in (
      "dsh-tui", "dsh-tui-webserver", "deepseek-account", "llm-deepseek-account", "llm-deepseek-api-key",
      "web-search-deepseek", "web-fetch-http", "tool-web", "session-title-llm", "otel", "session-telemetry-otel")) + "\n")
    defaults = tomllib.loads((repo / "agents/dsh/agent.toml").read_text())["defaults"]["plugins"]
    machine = root / "machine.toml"
    state = root / "team-state.json"
    results = {}
    for phase in ("off", "on", "resume", "off-again"):
      plugins = [*defaults, *(["agent-teams"] if phase in ("on", "resume") else [])]
      machine.write_text('schema_version=1\n[machine]\nid="team-native-fixture"\n'
        '[overrides.providers.fixture]\nprotocol="openai-compatible"\nbase_url="http://127.0.0.1:9/v1"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
        '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture"\ninput=["text"]\n'
        '[overrides.profiles.dsh-default]\nproviders=["fixture"]\nmodels=["fixture"]\nplugins=' + json.dumps(plugins) + '\n'
        '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n'
        '[overrides.profiles.dsh-default.agent_options]\nauto_review=true\n'
        '[secrets]\nfixture="synthetic-never-used"\n')
      machine.chmod(0o600)
      workspace = load_workspace(machine, repository=repo)
      commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
      with Tree(workspace.state_root) as tree, instance_lock(tree):
        profile_runtime.prepare(workspace, runtime)
      result_path = root / (phase + ".json")
      child_env = {**env, "HOME": str(workspace.instance / "user-home"), "DSH_HOME": str(workspace.instance / "dsh-home"),
        "AGENTCFG_SMOKE_ROOT": str(root), "AGENTCFG_SMOKE_RESULT": str(result_path), "AGENTCFG_SMOKE_PHASE": phase,
        "AGENTCFG_SMOKE_STATE": str(state), "AGENTCFG_SMOKE_PATCH": str(workspace.instance / "dsh-home/agentcfg.patch.yml"),
        "AGENTCFG_SMOKE_HEADLESS": str(headless), "AGENTCFG_SMOKE_PRESET": str(runtime / "node_modules/@deepseek-ai/dsh-web-app/presets/standard.patch.yml")}
      child_env["AGENTCFG_DEVELOPMENT_ENV"] = json.dumps({"version": 1, "values": {
        key: child_env[key] for key in ("HOME", "PATH", "LANG", "TERM", "TMPDIR",
          "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")}, "unset": []})
      argv = ["node", str(repo / "scripts/smoke-dsh-agent-teams.mjs"), str(runtime)]
      with (evidence / (phase + ".log")).open("wb") as log:
        os.fchmod(log.fileno(), 0o600)
        try:
          process = subprocess.run(argv, cwd=project, env=child_env, stdout=log, stderr=subprocess.STDOUT, timeout=120)
          code = process.returncode
        except subprocess.TimeoutExpired:
          code = 124
      result = json.loads(result_path.read_bytes()) if result_path.exists() else {"functional": "FAIL", "error": "RESULT_MISSING"}
      result["exit"] = code
      if code:
        result["functional"] = "FAIL"
      results[phase] = result
      if result["functional"] != "PASS":
        break
    sources = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in (
      "scripts/smoke-dsh-agent-teams.py", "scripts/smoke-dsh-agent-teams.mjs", "src/agentcfg/dsh.py",
      "src/agentcfg/dsh_optional.py", "src/agentcfg/profile_runtime.py")}
    result = {"kind": "official-team-bundle-deterministic-no-account", "lock_identity": lock.identity,
      "functional": "PASS" if len(results) == 4 and all(r["functional"] == "PASS" for r in results.values()) else "FAIL",
      "results": results, "source_files": sources, "node": node, "real_accounts": "NOT RUN", "remote_model": "NOT RUN"}
    output = evidence / "result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    output.chmod(0o600)
    print(json.dumps({"functional": result["functional"], "phases": {k: v["functional"] for k, v in results.items()}}))
    return 0 if result["functional"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())

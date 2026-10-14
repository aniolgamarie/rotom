#!/usr/bin/env python3
"""显式原生验收：当前 sealed 锁、私人 HOME、公共 API 和真实系统沙箱。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time
import uuid


def run_native(argv, project, env, log):
  master, slave = pty.openpty()
  child = subprocess.Popen(argv, cwd=project, env=env, stdin=slave, stdout=slave, stderr=slave)
  os.close(slave)
  transcript = bytearray()
  started = time.monotonic()
  deadline = started + 90
  timed_out = False
  forced_termination = False
  try:
    while child.poll() is None and time.monotonic() < deadline:
      if select.select([master], [], [], 0.2)[0]:
        try:
          transcript.extend(os.read(master, 65536))
        except OSError:
          break
    if child.poll() is None:
      timed_out = time.monotonic() >= deadline
      forced_termination = True
      child.terminate()
      try:
        child.wait(timeout=5)
      except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
    else:
      child.wait()
    while select.select([master], [], [], 0)[0]:
      try:
        transcript.extend(os.read(master, 65536))
      except OSError:
        break
  finally:
    if child.poll() is None:
      child.kill()
      child.wait()
    os.close(master)
  log.write_bytes(transcript)
  return {"exit": child.returncode, "timed_out": timed_out, "forced_termination": forced_termination,
    "duration_seconds": round(time.monotonic() - started, 3)}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true", help="明确允许真实无账号宿主和系统沙箱检查")
  parser.add_argument("--runtime", required=True, type=Path)
  parser.add_argument("--evidence", required=True, type=Path)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要 --allow-host；普通 pytest 不启动第三方宿主")
  repository = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repository / "src"))
  from agentcfg import commands, dependencies, runtime, runtime_packages
  from agentcfg.process import launch_environment
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace

  lock = dependencies.read_lock(repository)
  package = args.runtime.absolute()
  if (runtime_packages.status(package, lock.identity) != "installed"
      or (package / "package.json").read_bytes() != lock.package
      or ((package / "package-lock.json").read_bytes() if (package / "package-lock.json").exists() else b"") != lock.resolution
      or (package / "pnpm-lock.yaml").read_bytes() != lock.installer_resolution):
    parser.error("runtime 的收据与当前完整 npm/pnpm 锁不匹配")
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  if (evidence / "result.json").exists():
    parser.error("证据目录已有结果；请为本次验收使用新目录")
  outer_path = os.environ.get("PATH", "")
  (repository / ".cache/dsh-upgrade").mkdir(mode=0o700, parents=True, exist_ok=True)
  with tempfile.TemporaryDirectory(prefix="rotom-dsh-smoke-", dir="/dev/shm") as private_dir, tempfile.TemporaryDirectory(prefix="native-workspace-", dir=repository / ".cache/dsh-upgrade") as data_dir:
    root, scratch = Path(private_dir), Path(data_dir)
    env = {"PATH": outer_path, "HOME": str(root / "home"), "DSH_HOME": str(root / "dsh"),
      "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
      "XDG_STATE_HOME": str(root / "state"), "XDG_CACHE_HOME": str(root / "cache"),
      "TMPDIR": str(root / "tmp"), "TERM": "xterm-256color", "LANG": "C.UTF-8"}
    for key, value in env.items():
      if key not in ("PATH", "TERM", "LANG"):
        ensure_private(Path(value))
    os.environ.clear()
    os.environ.update(env)
    version = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True, check=True).stdout.strip()
    if version != lock.metadata["node"]:
      parser.error("请准备当前锁要求的精确 Node 版本")
    machine = root / "machine.toml"
    machine.write_text('schema_version=1\n[machine]\nid="native-smoke"\n'
      '[overrides.providers.fixture]\nprotocol="openai-compatible"\nbase_url="http://127.0.0.1:9/v1"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
      '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-not-real"\ninput=["text"]\n'
      '[overrides.profiles.dsh-default]\nproviders=["codex","cursor","fixture"]\nmodels=["fixture"]\n'
      '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n')
    machine.chmod(0o600)
    workspace = load_workspace(machine, repository=repository)
    candidate = workspace.candidate(lock.identity)
    commands.apply_candidate(workspace, lock, candidate)
    with Tree(workspace.state_root) as state, instance_lock(state):
      workspace.adapter.prepare_runtime(workspace, package)
    project = scratch / "workspace"
    project.mkdir(mode=0o700)
    outside = scratch / "outside"
    outside.mkdir(mode=0o700)
    (project / ".env").write_text("AGENTCFG_DOTENV_SENTINEL=must-not-be-inherited\n")
    (workspace.instance / "dsh-home/.env").write_text("AGENTCFG_HOME_DOTENV_SENTINEL=must-not-be-inherited\n")
    spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=project, runtime_root=package,
      instance_root=workspace.instance, lock_identity=lock.identity)
    child_env = launch_environment(spec, workspace.resolved.data["machine"], workspace.secret_store)
    nonce = uuid.uuid4().hex
    native_result = root / "native-result.json"
    child_env.update(AGENTCFG_SMOKE_ROOT=str(root), AGENTCFG_SMOKE_RESULT=str(native_result),
      AGENTCFG_SMOKE_PATCH=str(workspace.instance / "dsh-home/agentcfg.patch.yml"),
      AGENTCFG_SMOKE_OUTSIDE=str(outside / "sentry.txt"), AGENTCFG_SMOKE_NONCE=nonce,
      AGENTCFG_SMOKE_LAUNCHER=str(workspace.instance / "launch.mjs"))
    argv = ["node", str(repository / "scripts/smoke-dsh.mjs"), str(package)]
    native = run_native(argv, project, child_env, evidence / "transcript.log")
    code = 124 if native["timed_out"] else 1 if native["forced_termination"] else native["exit"]
    result = json.loads(native_result.read_bytes()) if native_result.exists() else {"checks": {}, "error": "NATIVE_RESULT_MISSING"}
    result["native_exit"] = code
    result["native_process"] = native
    required = ("host", "manual_approval", "sandbox")
    complete = result.get("native_complete") is True and all(result.get("checks", {}).get(name) == "PASS" for name in required)
    if native["timed_out"]:
      result.update(error="NATIVE_TIMEOUT", error_location=result.get("stage", "driver.native"))
    elif not complete and "error" not in result:
      result.update(error="NATIVE_INCOMPLETE", error_location=result.get("stage", "driver.native"))
    if code == 0 and complete and "error" not in result and result.get("nonce") == nonce:
      child_env["AGENTCFG_SMOKE_SESSION"] = result["sessionId"]
      restart = run_native([*argv, "--read-audit"], project, child_env, evidence / "restart-transcript.log")
      result = json.loads(native_result.read_bytes())
      result.update(native_exit=code, native_process=native, restart_process=restart)
      code = 124 if restart["timed_out"] else 1 if restart["forced_termination"] else restart["exit"]
      result["restart_exit"] = code
      if restart["timed_out"]:
        result.update(error="RESTART_TIMEOUT", error_location=result.get("stage", "driver.restart"))
    else:
      result["restart_exit"] = "NOT RUN"
    paths = ("src/agentcfg/dsh.py", "src/agentcfg/commands.py", "src/agentcfg/deployment.py", "src/agentcfg/native.py",
      "src/agentcfg/profile_runtime.py", "agents/dsh/templates/launch.mjs", "agents/dsh/templates/tui.yaml",
      "agents/dsh/templates/check-runtime.mjs", "agents/dsh/packages/cursor-terminal/index.mjs", "scripts/smoke-dsh.py", "scripts/smoke-dsh.mjs")
    source = {name: hashlib.sha256((repository / name).read_bytes()).hexdigest() for name in paths}
    result.update(lock_identity=lock.identity, recipe=lock.metadata["recipe"], candidate_digest=candidate.generation,
      source_files=source, source_digest=hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
      platform=sys.platform, node=version, invocation=["scripts/smoke-dsh.py", "--allow-host", "--runtime", str(package), "--evidence", str(evidence)],
      model_calls="NOT RUN", mcp="NOT RUN", subagent="NOT RUN", ptc="NOT RUN", interactive_model_roundtrip="NOT RUN",
      ai_delegate_scope="BLOCKED: public delegated cwd and read-only limits not established",
      ai_review="BLOCKED: Perry reviewer not installed; deterministic public answerer verifies manual approval only")
    result["cwd_preserved"] = result.pop("cwd", None) == str(project)
    result["nonce_verified"] = result.pop("nonce", None) == nonce
    success = (code == 0 and result["nonce_verified"] and result["cwd_preserved"] and "error" not in result
      and result.get("native_complete") is True and result.get("audit_restart_complete") is True
      and all(result.get("checks", {}).get(name) == "PASS" for name in (*required, "audit_restart")))
    result["overall"] = "PASS" if success else "FAIL"
    (evidence / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"overall": result["overall"], "lock_identity": lock.identity, "evidence": str(evidence)}, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
  raise SystemExit(main())

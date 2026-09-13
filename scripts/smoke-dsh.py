#!/usr/bin/env python3
"""显式无账号 smoke：临时 HOME、临时 Git 项目、真实锁定宿主，结束后清理。"""

import argparse
import json
import os
from pathlib import Path
import pty
import select
import socket
import subprocess
import tempfile
import time
import uuid
import sys


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true", help="明确允许本次真实无账号宿主检查")
  parser.add_argument("--runtime", required=True, type=Path, help="已按当前锁安装的运行包目录")
  parser.add_argument("--with-openspec", action="store_true")
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要 --allow-host；普通 pytest 不启动第三方宿主")

  sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

  from agentcfg import deployment
  from agentcfg.dependencies import read_lock
  from agentcfg.profile_runtime import prepare
  from agentcfg.process import launch_environment
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace

  repository = Path(__file__).resolve().parents[1]
  lock = read_lock(repository)
  runtime = args.runtime.absolute()
  if (runtime / "package-lock.json").read_bytes() != lock.resolution:
    parser.error("runtime 不匹配仓库当前完整锁")
  outer_path = os.environ.get("PATH", "")
  with tempfile.TemporaryDirectory(prefix="agentcfg-native-smoke-") as directory:
    root = Path(directory).resolve()
    env = {"PATH": outer_path, "HOME": str(root / "home"), "DSH_HOME": str(root / "dsh"),
      "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
      "XDG_STATE_HOME": str(root / "state"), "XDG_CACHE_HOME": str(root / "cache"),
      "TMPDIR": str(root / "tmp"), "TERM": "xterm-256color", "LANG": "C.UTF-8"}
    for key, value in env.items():
      if key not in ("PATH", "TERM", "LANG"):
        Path(value).mkdir(mode=0o700)
    os.environ.clear()
    os.environ.update(env)
    version = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True, check=True).stdout.strip()
    if version != lock.metadata["node"]:
      parser.error("请准备当前锁要求的 Node 版本")
    with socket.socket() as listener:
      listener.bind(("127.0.0.1", 0))
      port = listener.getsockname()[1]
    machine = root / "machine.toml"
    machine.write_text('schema_version=1\n[machine]\nid="native-smoke"\n'
      f'[overrides.profiles.dsh-default.agent_options]\ncursor_port={port}\n')
    machine.chmod(0o600)
    workspace = load_workspace(machine, repository=repository)
    if workspace.resolved.data["mcp"] or any(p["auth_kind"] != "oauth" for p in workspace.resolved.data["providers"].values()):
      parser.error("无账号 smoke 只接受无 API/MCP 凭据的订阅配方")
    project = root / "project"
    project.mkdir(mode=0o700)
    subprocess.run(["git", "init", "--initial-branch=main", str(project)], env={**env,
      "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}, capture_output=True, check=True)
    if args.with_openspec:
      subprocess.run(["node", str(runtime / "node_modules/@fission-ai/openspec/bin/openspec.js"),
        "init", "--tools", "agents", "--profile", "core", "--no-animation"], cwd=project,
        env={**env, "OPENSPEC_TELEMETRY": "0", "DO_NOT_TRACK": "1", "OPENSPEC_NO_UPDATE_CHECK": "1"},
        capture_output=True, check=True)
    deployment.apply(workspace.instance, workspace.state_root, workspace.candidate(lock.identity), workspace.binding, {})
    with Tree(workspace.state_root) as state, instance_lock(state):
      workspace.adapter.prepare_runtime(workspace, runtime)
    spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=project, runtime_root=runtime,
      instance_root=workspace.instance, lock_identity=lock.identity)
    child_env = launch_environment(spec, workspace.resolved.data["machine"], workspace.secret_store)
    result = root / "result.json"
    nonce = uuid.uuid4().hex
    child_env.update(AGENTCFG_SMOKE_ROOT=str(root), AGENTCFG_SMOKE_RESULT=str(result),
      AGENTCFG_SMOKE_NONCE=nonce, AGENTCFG_SMOKE_PORT=str(port))
    master, slave = pty.openpty()
    child = subprocess.Popen(["node", "--import", str(workspace.instance / "env-guard.mjs"),
      str(repository / "scripts/smoke-dsh.mjs"), str(runtime)], cwd=project, env=child_env,
      stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    transcript = bytearray()
    deadline = time.monotonic() + 60
    try:
      while child.poll() is None and time.monotonic() < deadline:
        if select.select([master], [], [], 0.2)[0]:
          try:
            transcript.extend(os.read(master, 65536))
          except OSError:
            break
      if child.poll() is None:
        # 只关闭本脚本创建的测试宿主，绝不操作用户运行的实例。
        child.terminate()
        try:
          child.wait(timeout=8)
        except subprocess.TimeoutExpired:
          child.kill()
          child.wait()
      while select.select([master], [], [], 0)[0]:
        try:
          transcript.extend(os.read(master, 65536))
        except OSError:
          break
    finally:
      if child.poll() is None:
        child.terminate()
        try:
          child.wait(timeout=8)
        except subprocess.TimeoutExpired:
          child.kill()
          child.wait()
      os.close(master)
    if child.returncode != 0 or not result.exists() or b"EADDRINUSE" in transcript:
      print("无账号宿主 smoke 失败；未形成完整的原生加载证据")
      return 1
    evidence = json.loads(result.read_text())
    if evidence.pop("nonce", None) != nonce:
      raise RuntimeError("smoke result does not belong to this invocation")
    evidence["cwd_preserved"] = evidence.pop("cwd") == str(project)
    evidence["lock_identity"] = lock.identity
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
  raise SystemExit(main())

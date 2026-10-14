#!/usr/bin/env python3
"""显式 Core/Perry 原生无账号组件验收；假模型，不进入默认 pytest。"""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


def run(argv, cwd, env, log):
  started = time.monotonic()
  with log.open("wb") as output:
    child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
      code = child.wait(timeout=150)
      return {"exit": code, "timed_out": False, "seconds": round(time.monotonic() - started, 3)}
    except subprocess.TimeoutExpired:
      child.terminate()
      try:
        child.wait(timeout=5)
      except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
      return {"exit": 124, "timed_out": True, "seconds": round(time.monotonic() - started, 3)}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", required=True, type=Path)
  parser.add_argument("--formal-runtime", action="store_true", help="使用当前正式锁收据；不改变已接受的生命周期失败结论")
  parser.add_argument("--core-version", choices=("0.2.0-rc.2", "0.2.1-alpha.2"), default="0.2.0-rc.2")
  parser.add_argument("--evidence", required=True, type=Path)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要 --allow-host；默认测试不启动第三方宿主")
  repo = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repo / "src"))
  from agentcfg import commands, dependencies, profile_runtime, runtime_packages
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  package = args.runtime.absolute()
  lock_hash = hashlib.sha256((package / "pnpm-lock.yaml").read_bytes()).hexdigest()
  source_lock = dependencies.read_lock(repo)
  if args.formal_runtime:
    if (args.core_version != "0.2.0-rc.2" or runtime_packages.status(package, source_lock.identity) != "installed"
        or (package / "package.json").read_bytes() != source_lock.package
        or (package / "pnpm-lock.yaml").read_bytes() != source_lock.installer_resolution):
      parser.error("正式 runtime 收据与当前完整锁不匹配")
    # 上游源声明的 prerelease peer 警告仍保留；不把正式安装伪报成源声明通过。
    peer_gate = "FAIL"
  elif args.core_version == "0.2.0-rc.2":
    install = json.loads((package / "result.json").read_bytes())
    if (install.get("diagnostic-frozen-install_exit") != 0 or not install.get("lock_unchanged")
        or install["sha256"]["pnpm-lock.yaml"] != lock_hash or install.get("actual-module-graph_exit") != 0):
      parser.error("必须使用 frozen 安装完成、锁未漂移且主模块图通过的诊断 runtime")
    peer_gate = "PASS" if install.get("accepted_final_dependency_gate") else "FAIL"
  else:
    install = json.loads((package / "logs/frozen-install-retry-bounded.json").read_bytes())
    if install["exit"] != 0 or not install["lock_unchanged"] or install["lock_sha256"] != lock_hash:
      parser.error("必须使用实际 frozen 安装完成且锁未漂移的任务 runtime")
    peer_gate = "NOT ACCEPTED"
  for name, version in {"@deepseek-ai/dsh": args.core_version, "dsh-auto-review": "0.12.17",
      "@deepseek-ai/cordis": "4.0.5-alpha.1", "@deepseek-ai/schemastery": "3.18.5-alpha.1"}.items():
    if json.loads((package / "node_modules" / name / "package.json").read_bytes())["version"] != version:
      parser.error("组件版本不匹配")
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  if (evidence / "result.json").exists():
    parser.error("使用新的空证据目录")
  cache = repo / ".cache/dsh-upgrade"
  path = os.environ.get("PATH", "")
  with tempfile.TemporaryDirectory(prefix="rotom-review-", dir="/dev/shm") as home, tempfile.TemporaryDirectory(prefix="review-work-", dir=cache) as work:
    root, scratch = Path(home), Path(work)
    project = scratch / "workspace"
    project.mkdir(mode=0o700)
    outside = scratch / "outside"
    outside.mkdir(mode=0o700)
    env = {"PATH": path, "LANG": "C.UTF-8", "TERM": "xterm-256color", "DSH_PERMISSION_MODE": "workspace-write"}
    for name, suffix in {"HOME": "home", "DSH_HOME": "dsh", "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data",
        "XDG_STATE_HOME": "state", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}.items():
      env[name] = str(root / suffix)
      ensure_private(root / suffix)
    os.environ.clear()
    os.environ.update(env)
    version = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True, check=True).stdout.strip()
    if version != "v24.14.0":
      parser.error("需要 Node24.14.0")
    if args.formal_runtime:
      subprocess.run(["node", str(repo / "agents/dsh/templates/check-runtime.mjs"), str(package)],
        cwd=project, env=env, capture_output=True, check=True)
    machine = root / "machine.toml"
    machine.write_text('schema_version=1\n[machine]\nid="native-auto-review"\n'
      '[overrides.providers.fixture]\nprotocol="openai-compatible"\nbase_url="http://127.0.0.1:9/v1"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
      '[overrides.models.fixture]\nprovider="fixture"\nremote_id="allow"\ninput=["text"]\n'
      '[overrides.profiles.dsh-default]\nproviders=["fixture"]\nmodels=["fixture"]\n'
      '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n[secrets]\nfixture="synthetic-never-used"\n')
    machine.chmod(0o600)
    workspace = load_workspace(machine, repository=repo)
    identity = source_lock.identity if args.formal_runtime else hashlib.sha256((package / "package.json").read_bytes() + (package / "pnpm-lock.yaml").read_bytes()).hexdigest()
    candidate = workspace.candidate(identity)
    commands.apply_candidate(workspace, source_lock, candidate)
    with Tree(workspace.state_root) as tree, instance_lock(tree):
      profile = profile_runtime.prepare(workspace, package)
    # 仅临时组件验收去掉 TUI bundle；用户配方与受管模板均不修改。
    manifest = json.loads((profile / "package.json").read_bytes())
    manifest["dsh"]["profile"]["bundles"] = ["@deepseek-ai/dsh-base"]
    (profile / "package.json").write_text(json.dumps(manifest))
    (profile / "cordis.patch.yml").write_text("[]\n")
    patch = root / "component.patch.yml"
    patch.write_text("\n".join("- id: " + name + "\n  disabled: true" for name in (
      "deepseek-account", "llm-deepseek-account", "llm-deepseek-api-key", "web-search-deepseek",
      "web-fetch-http", "tool-web", "session-title-llm", "otel", "session-telemetry-otel")) + "\n")
    env.update(HOME=str(workspace.instance / "user-home"), DSH_HOME=str(workspace.instance / "dsh-home"))
    nonce = uuid.uuid4().hex
    result_path = root / "result.json"
    env.update(AGENTCFG_SMOKE_ROOT=str(root), AGENTCFG_SMOKE_RESULT=str(result_path), AGENTCFG_SMOKE_NONCE=nonce,
      AGENTCFG_SMOKE_PATCH=str(patch), AGENTCFG_SMOKE_OUTSIDE=str(outside / "sentry.txt"))
    argv = ["node", str(repo / "scripts/smoke-dsh-auto-review.mjs"), str(package)]
    process = run(argv, project, env, evidence / "transcript.log")
    result = json.loads(result_path.read_bytes()) if result_path.exists() else {"functional": "FAIL", "error": "RESULT_MISSING"}
    result["native_process"] = process
    if process["exit"] == 0 and result.get("native_complete") and result.get("nonce") == nonce:
      restart = run([*argv, "--read-audit"], project, env, evidence / "restart-transcript.log")
      result = json.loads(result_path.read_bytes())
      result.update(native_process=process, restart_process=restart)
    else:
      result["restart_process"] = "NOT RUN"
    result["nonce_verified"] = result.pop("nonce", None) == nonce
    sources = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in (
      "scripts/smoke-dsh-auto-review.py", "scripts/smoke-dsh-auto-review.mjs", "src/agentcfg/dsh.py", "src/agentcfg/profile_runtime.py")}
    result.update(kind="native-core-perry-simulated-sdk-model", source_files=sources,
      source_hash=hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(), node=version,
      stage_runtime_identity=identity, formal_runtime=args.formal_runtime,
      actual_lock_identity=source_lock.identity, actual_lock_recipe=source_lock.metadata["recipe"],
      pnpm_lock_sha256=lock_hash, candidate_digest=candidate.generation,
      platform=sys.platform, platform_detail=dict(system=platform.system(), release=platform.release(), machine=platform.machine()),
      core_version=args.core_version, dependency_peer_gate=peer_gate, real_accounts="NOT RUN", real_http_model="NOT RUN", full_tui_cursor="NOT RUN",
      invocation=["scripts/smoke-dsh-auto-review.py", "--allow-host", "--core-version", args.core_version, "--runtime", str(package), "--evidence", str(evidence)] + (["--formal-runtime"] if args.formal_runtime else []))
    if process["timed_out"] or process["exit"] != 0 or not result["nonce_verified"]:
      result.update(functional="FAIL", release_gate="FAIL", driver_error="NATIVE_INCOMPLETE_OR_TIMEOUT")
    result["release_gate"] = result.get("release_gate", "BLOCKED")
    if peer_gate != "PASS":
      result["release_gate"] = "FAIL"
    (evidence / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"functional": result.get("functional"), "release_gate": result["release_gate"], "evidence": str(evidence)}))
    return 0 if result.get("functional") == "PASS" and result["release_gate"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())

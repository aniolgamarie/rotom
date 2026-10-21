#!/usr/bin/env python3
"""显式正式配方功能 smoke：真实 Core/Perry/文件工具，确定性无账号模型。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


def run(argv, cwd, env, log):
  started = time.monotonic()
  with log.open("wb") as output:
    log.chmod(0o600)
    child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
      code = child.wait(timeout=180)
    except subprocess.TimeoutExpired:
      child.terminate()
      try:
        child.wait(timeout=5)
      except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
      code = 124
  return {"exit": code, "seconds": round(time.monotonic() - started, 3),
    "argv": [argv[0], "<repository>/scripts/" + Path(argv[1]).name, "<runtime>"]}


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", required=True, type=Path)
  parser.add_argument("--evidence", required=True, type=Path)
  parser.add_argument("--diagnostic-allow-only", action="store_true")
  args = parser.parse_args(argv)
  if not args.allow_host:
    parser.error("需要 --allow-host；默认测试不启动第三方宿主")
  repo = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repo / "src"))
  from agentcfg import commands, dependencies, profile_runtime, runtime_packages
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  lock = dependencies.read_lock(repo)
  package = args.runtime.absolute()
  if (runtime_packages.status(package, lock.identity) != "installed"
      or (package / "package.json").read_bytes() != lock.package
      or (package / "pnpm-lock.yaml").read_bytes() != lock.installer_resolution):
    parser.error("runtime 收据与当前完整锁不匹配")
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  if any(evidence.iterdir()):
    parser.error("使用新的空证据目录")
  filesystem = subprocess.run(["stat", "-f", "-c", "%T", str(evidence)],
    env={"PATH": os.defpath, "LANG": "C"}, capture_output=True, text=True, check=True).stdout.strip()
  if filesystem in ("tmpfs", "ramfs"):
    parser.error("sandbox 哨兵需要持久文件系统证据目录；临时内存文件系统不适用")
  sandbox_targets = evidence / "sandbox-targets"
  sandbox_targets.mkdir(mode=0o700)
  outer_path = os.environ.get("PATH", "")
  with tempfile.TemporaryDirectory(prefix="rotom-formal-review-", dir="/dev/shm") as temporary:
    root = Path(temporary)
    env = {"PATH": outer_path, "LANG": "C.UTF-8", "TERM": "xterm-256color",
      "DSH_PERMISSION_MODE": "workspace-write", "DSH_TELEMETRY_DISABLED": "1",
      "DSH_TUI_PRESET": "standard", "DSH_TUI_NO_LAUNCHPAD": "1", "DSH_TUI_DISABLE_TERMINAL_IMAGES": "1"}
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
    outside = root / "outside-sentinel.txt"
    outside.write_text("SYNTHETIC_FORMAL_REVIEW_OUTSIDE_SENTINEL")
    machine = root / "machine.toml"
    base = ('schema_version=1\n[machine]\nid="formal-review-smoke"\n'
      '[overrides.providers.fixture]\nprotocol="openai-compatible"\nbase_url="http://127.0.0.1:9/v1"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
      '[overrides.models.fixture]\nprovider="fixture"\nremote_id="allow"\ninput=["text"]\n'
      '[overrides.profiles.dsh-default]\nproviders=["fixture"]\nmodels=["fixture"]\n'
      '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n'
      '[secrets]\nfixture="synthetic-never-used"\n')
    headless = root / "headless.patch.yml"
    headless.write_text("\n".join("- id: " + name + "\n  disabled: true" for name in (
      "dsh-tui", "dsh-tui-webserver", "deepseek-account", "llm-deepseek-account", "llm-deepseek-api-key",
      "web-search-deepseek", "web-fetch-http", "tool-web", "session-title-llm", "otel", "session-telemetry-otel")) + "\n")
    # 官方文件是 patch 列表，交给公开 runProfile.patchFiles，不作为 include entries。
    preset_source = package / "node_modules/@deepseek-ai/dsh-web-app/presets/standard.patch.yml"
    results = {}
    modes = (("formal", True),) if args.diagnostic_allow_only else (("formal", True), ("manual", False), ("timeout", True))
    for mode, enabled in modes:
      options = '[overrides.profiles.dsh-default.agent_options]\nauto_review=' + str(enabled).lower() + "\n"
      if mode == "timeout":
        options += '[overrides.profiles.dsh-default.agent_options.auto_review_options]\nreviewer_timeout_ms=1000\n'
      machine.write_text(base + options)
      machine.chmod(0o600)
      workspace = load_workspace(machine, repository=repo)
      candidate = workspace.candidate(lock.identity)
      commands.apply_candidate(workspace, lock, candidate)
      with Tree(workspace.state_root) as tree, instance_lock(tree):
        profile = profile_runtime.prepare(workspace, package)
      expected = {a.target.selector.removeprefix("/auto-review/config/"): json.loads(a.content)
        for a in candidate.artifacts if a.target.selector and a.target.selector.startswith("/auto-review/config/")}
      expected_path = root / "expected.json"
      expected_path.write_text(json.dumps(expected, ensure_ascii=False))
      nonce = uuid.uuid4().hex
      result_path = root / (mode + ".json")
      child_env = {**env, "HOME": str(workspace.instance / "user-home"), "DSH_HOME": str(workspace.instance / "dsh-home"),
        "AGENTCFG_SMOKE_ROOT": str(root), "AGENTCFG_SMOKE_RESULT": str(result_path), "AGENTCFG_SMOKE_NONCE": nonce,
        "AGENTCFG_SMOKE_PATCH": str(workspace.instance / "dsh-home/agentcfg.patch.yml"), "AGENTCFG_SMOKE_HEADLESS": str(headless),
        "AGENTCFG_SMOKE_PRESET": str(preset_source), "AGENTCFG_SMOKE_EXPECTED": str(expected_path), "AGENTCFG_SMOKE_OUTSIDE": str(outside), "AGENTCFG_SMOKE_MODE": mode}
      child_env["AGENTCFG_SMOKE_DIAGNOSTIC_ALLOW_ONLY"] = "1" if args.diagnostic_allow_only else "0"
      child_env["AGENTCFG_SMOKE_SANDBOX_TARGET_ROOT"] = str(sandbox_targets)
      child_env["AGENTCFG_DEVELOPMENT_ENV"] = json.dumps({"version": 1, "values": {
        key: child_env[key] for key in ("HOME", "PATH", "LANG", "TERM", "TMPDIR",
          "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")}, "unset": []})
      process = run(["node", str(repo / "scripts/smoke-dsh-formal-review.mjs"), str(package)], project, child_env, evidence / (mode + ".log"))
      result = json.loads(result_path.read_bytes()) if result_path.exists() else {"functional": "FAIL", "error": "RESULT_MISSING"}
      result.update(process=process, candidate_digest=candidate.generation, profile_bundles=json.loads((profile / "package.json").read_bytes())["dsh"]["profile"]["bundles"])
      if result.pop("nonce", None) != nonce or process["exit"] != 0:
        result["functional"] = "FAIL"
      results[mode] = result
    sources = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in (
      "scripts/smoke-dsh-formal-review.py", "scripts/smoke-dsh-formal-review.mjs", "scripts/dsh-sandbox-review-cases.mjs", "src/agentcfg/dsh.py", "src/agentcfg/dsh_optional.py", "src/agentcfg/profile_runtime.py")}
    result = {"kind": "formal-config-native-file-tool-deterministic-no-account", "results": results,
      "diagnostic_allow_only": args.diagnostic_allow_only,
      "functional": "PASS" if len(results) == len(modes) and all(value["functional"] == "PASS" for value in results.values()) else "FAIL",
      "known_lifecycle_gate": "NOT REVALIDATED (historical 0.12.17 failures retained)", "lifecycle_fixes_claimed": False, "os_sandbox_proven": False,
      "lock_identity": lock.identity, "pnpm_lock_sha256": hashlib.sha256(lock.installer_resolution).hexdigest(),
      "source_files": sources, "node": node, "headless_preset_source": str(preset_source),
      "headless_preset_sha256": hashlib.sha256(preset_source.read_bytes()).hexdigest(), "real_accounts": "NOT RUN", "real_http_model": "NOT RUN"}
    result_file = evidence / "result.json"
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    result_file.chmod(0o600)
    print(json.dumps({"functional": result["functional"], "known_lifecycle_gate": result["known_lifecycle_gate"], "evidence": str(evidence)}))
    return 0 if result["functional"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())

#!/usr/bin/env python3
"""独立实验体验：AI 仅审批无副作用内存 probe；不属于正式 agentcfg run。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))
from agentcfg import commands, dependencies, deployment, native, profile_runtime, runtime as launch_runtime, runtime_packages
from agentcfg.adapter import Artifact, ManagedTarget, Ownership
from agentcfg.process import launch_environment
from agentcfg.render import RenderCandidate
from agentcfg.storage import Conflict, Tree, ensure_private, instance_lock
from agentcfg.workspace import load_workspace

FIXTURE = "tests/fixtures/dsh-auto-review-probe"
PACKAGE = "rotom-dsh-auto-review-probe"
OWNER = "experience-owner.json"
NOTICE = ("EXPERIMENT: AI may approve only the memory counter probe. Other approval requests delegate to human; native allow rules remain. "
  "/auto-review off is memory-only; an in-flight approval may still execute. "
  "Reviewer audit is not durable. Dependency strict-peer gate remains FAIL; this is not a release.")


def digest(raw):
  return hashlib.sha256(raw).hexdigest()


def encoded(data):
  return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def sources():
  names = ["scripts/experience-dsh-auto-review.py", "scripts/experience-dsh-auto-review.mjs",
    *(FIXTURE + "/" + name for name in ("package.json", "index.mjs", "cordis.patch.yml"))]
  return {name: digest((REPOSITORY / name).read_bytes()) for name in names}


def runtime_info(runtime):
  runtime = runtime.absolute()
  result = json.loads((runtime / "result.json").read_bytes())
  graph = json.loads((runtime / "actual-module-graph.json").read_bytes())
  if (not result.get("runtime_installed") or result.get("diagnostic-frozen-install_exit") != 0
      or not result.get("lock_unchanged") or any(graph.get(key) != "PASS" for key in
      ("sdkRootMainStatus", "perryTuiMainStatus", "publicMainImport", "alpha1EvalNotLoaded"))):
    raise Conflict("需要已完成安装和主路径检查的 RC2 诊断 runtime")
  expected = {"@deepseek-ai/dsh": "0.2.0-rc.2", "dsh-auto-review": "0.12.17",
    "@deepseek-harness-tui/dsh-tui": "0.15.0", "@deepseek-ai/cordis": "4.0.5-alpha.1",
    "@deepseek-ai/schemastery": "3.18.5-alpha.1"}
  for name, version in expected.items():
    if json.loads((runtime / "node_modules" / name / "package.json").read_bytes())["version"] != version:
      raise Conflict("体验 runtime 版本不匹配")
  inputs = {name: digest((runtime / name).read_bytes()) for name in ("package.json", "pnpm-lock.yaml")}
  if any(result.get("sha256", {}).get(name) != value for name, value in inputs.items()):
    raise Conflict("runtime manifest 或完整锁与 frozen 安装记录不一致")
  manifest = json.loads((runtime / "package.json").read_bytes())
  for name, version in manifest.get("dependencies", {}).items():
    if name.startswith("@deepseek-ai/dsh") and version == "0.2.0-rc.2":
      actual = json.loads((runtime / "node_modules" / name / "package.json").read_bytes())
      if actual.get("name") != name or actual.get("version") != version:
        raise Conflict("runtime Core SDK 版本漂移")
  inputs["node_modules_topology"] = runtime_packages.topology_digest(runtime)
  files = set(graph.get("loadedFiles", []))
  files.update(item["entry"] for values in graph.get("contexts", {}).values() for item in values.values() if "entry" in item)
  for value in sorted(files):
    path = Path(value)
    relative = path.relative_to(runtime)
    if relative.parts[0] != "node_modules" or not path.resolve().is_relative_to(runtime.resolve()):
      raise Conflict("诊断模块来源不在 runtime 内")
    inputs[str(relative)] = digest(path.read_bytes())
  return {"directory": str(runtime), "identity": digest(encoded(inputs)), "inputs": inputs,
    "strict_peer_gate": "FAIL retained; diagnostic only", "cursor_schema": "distinct instance, not proven compatible"}


def context(local, directory):
  return load_workspace(local, profile="dsh-default", repository=REPOSITORY,
    proposal={"machine": {"paths": {name: str(directory / suffix) for name, suffix in (
      ("instances_root", "instances"), ("state_root", "state"), ("cache_root", "cache"))}}})


def candidate_for(workspace, lock):
  base = workspace.candidate(lock.identity)
  extra = Artifact(ManagedTarget(workspace.adapter.shared_files[0], Ownership.FIELDS, "cordis-yaml",
    "/dsh-tui/config/recapOnOpen"), b"false")
  return RenderCandidate(digest((base.generation + ":experience-recap-disabled").encode()), base.artifacts + (extra,))


def wanted_files(workspace, runtime):
  root = "dsh-home/profiles/agentcfg/"
  manifest = {"name": "rotom-auto-review-experience-profile", "version": "0.0.0-experimental", "private": True,
    "dependencies": {PACKAGE: "file:" + str(REPOSITORY / FIXTURE)},
    "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "dsh-auto-review", PACKAGE, "@deepseek-harness-tui/dsh-tui"]}}}
  patch = native.load((workspace.instance / "dsh-home/agentcfg.patch.yml").read_bytes())
  policy = native.load((REPOSITORY / FIXTURE / "cordis.patch.yml").read_bytes())[0]
  patch.append(policy)
  patch.extend({"id": name, "disabled": True} for name in ("session-title-llm", "otel", "session-telemetry-otel"))
  return {root + "package.json": encoded(manifest), "dsh-home/experience.patch.yml": native.dump(patch)}


def check_owner(record, workspace, runtime, source, candidate):
  if record is None or record.get("kind") != "rotom-auto-review-experience-v1":
    raise Conflict("目录不是本实验拥有的体验目录")
  allowed = {"kind", "phase", "instance", "binding", "runtime", "sources", "candidate", "owned_files", "projections", "limits"}
  if set(record) - allowed or record.get("phase") not in ("preparing", "ready"):
    raise Conflict("体验所有权记录格式异常")
  if (record.get("instance") != str(workspace.instance) or record.get("binding") != workspace.binding or record.get("runtime") != runtime
      or record.get("sources") != source or record.get("candidate") != candidate.generation):
    raise Conflict("体验来源、绑定或 runtime 已变化；请使用新的隔离目录")
  with Tree(workspace.instance) as tree:
    for name, expected in record["owned_files"].items():
      raw = tree.read(name)
      if raw is None and record["phase"] == "preparing":
        continue
      if raw is None or raw[1] != 0o600 or digest(raw[0]) != expected:
        raise Conflict("体验受管正文漂移，拒绝覆盖或启动")


def check_plan(workspace, lock, candidate):
  plan = commands.current_plan(workspace, lock, candidate)
  if plan.conflicts or plan.drift:
    raise Conflict("正式配置存在受管字段漂移，拒绝体验操作")
  return plan


def _prepare_locked(local, directory, runtime):
  directory = directory.absolute()
  info, source = runtime_info(runtime), sources()
  if directory.is_symlink():
    raise Conflict("体验目录不能是链接")
  if directory.exists() and not (directory / OWNER).exists() and any(path.name != "instance.lock" for path in directory.iterdir()):
    raise Conflict("体验需要全新的空目录，不能接管已有数据")
  ensure_private(directory)
  workspace = context(local, directory)
  lock = dependencies.read_lock(REPOSITORY)
  candidate = candidate_for(workspace, lock)
  with Tree(directory) as tree:
    raw = tree.read(OWNER)
    record = json.loads(raw[0]) if raw else None
  with Tree(workspace.state_root, create=True) as state, instance_lock(state):
    if record:
      check_owner(record, workspace, info, source, candidate)
      check_plan(workspace, lock, candidate)
    else:
      # 准备标记只允许相同输入恢复；run 在 ready 前拒绝启动。
      record = {"kind": "rotom-auto-review-experience-v1", "phase": "preparing", "instance": str(workspace.instance), "binding": workspace.binding,
        "runtime": info, "sources": source, "candidate": candidate.generation, "owned_files": {}, "projections": {}}
      with Tree(directory) as tree:
        tree.write_state(OWNER, encoded(record))
  # 此独立夹具由下方 phase/owned_files 日志准备专属 profile，不调用正式 profile 准备。
  with workspace.adapter.lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding,
      launch_runtime.record(workspace, lock))
  with Tree(workspace.state_root) as state, instance_lock(state):
    files = wanted_files(workspace, runtime)
    if record["owned_files"]:
      check_owner(record, workspace, info, source, candidate)
    else:
      record["owned_files"] = {name: digest(data) for name, data in files.items()}
      with Tree(directory) as tree:
        tree.write_state(OWNER, encoded(record))
    with Tree(workspace.instance) as tree:
      for name, data in files.items():
        before = tree.read(name)
        if before and before[0] != data:
          raise Conflict("体验文件已存在且正文不匹配")
        if not before:
          tree.replace(name, data, mode=0o600, expected=None)
    profile = workspace.instance / "dsh-home/profiles/agentcfg"
    ensure_private(profile / "node_modules")
    projections = {name: str(runtime / "node_modules" / name) for name in (
      "@deepseek-ai/dsh-base", "dsh-auto-review", "@deepseek-harness-tui/dsh-tui", "rotom-dsh-cursor-terminal")}
    projections[PACKAGE] = str(REPOSITORY / FIXTURE)
    profile_runtime.project_runtime_modules(profile, runtime,
      {"projections": record["projections"], "pending_projections": projections}, projections)
    ensure_private(directory / "workspace")
    for suffix in ("config", "data", "state", "cache", "tmp"):
      ensure_private(directory / "environment" / suffix)
    record.update(phase="ready", projections=projections, limits=NOTICE)
    with Tree(directory) as tree:
      tree.write_state(OWNER, encoded(record))
  return workspace


def signal_own_group(child, value):
  try:
    if os.getpgid(child.pid) != child.pid:
      raise Conflict("体验子进程组身份异常，拒绝信号操作")
    os.killpg(child.pid, value)
  except ProcessLookupError:
    pass


def _run_locked(local, directory, runtime, *, allow_host=False):
  if not allow_host:
    raise Conflict("--run 需要 --allow-host；会调用显式授权的模型来源")
  directory = directory.absolute()
  workspace = context(local, directory)
  lock = dependencies.read_lock(REPOSITORY)
  candidate = candidate_for(workspace, lock)
  with Tree(workspace.state_root) as state, instance_lock(state):
    with Tree(directory) as tree:
      record = json.loads(tree.read(OWNER)[0])
    if record.get("phase") != "ready":
      raise Conflict("体验准备未完成")
    check_owner(record, workspace, runtime_info(runtime), sources(), candidate)
    if check_plan(workspace, lock, candidate).changes:
      raise Conflict("体验配置需要重新准备")
    profile = workspace.instance / "dsh-home/profiles/agentcfg"
    for name, target in record["projections"].items():
      link = profile / "node_modules" / name
      if not link.is_symlink() or os.readlink(link) != target:
        raise Conflict("体验模块投影漂移")
    spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=directory / "workspace", runtime_root=runtime,
      instance_root=workspace.instance, lock_identity=record["runtime"]["identity"])
    env = launch_environment(spec, workspace.resolved.data["machine"], workspace.secret_store)
    for name, suffix in {"XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data", "XDG_STATE_HOME": "state",
        "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}.items():
      env[name] = str(directory / "environment" / suffix)
    argv = [spec.argv[0], str(REPOSITORY / "scripts/experience-dsh-auto-review.mjs"), spec.argv[2],
      str(workspace.instance / "dsh-home/experience.patch.yml")]
    print(NOTICE, flush=True)
    child = subprocess.Popen(argv, cwd=spec.cwd, env=env, start_new_session=True)
    previous_resize = None
    if hasattr(signal, "SIGWINCH"):
      def forward_resize(_signum, _frame):
        try:
          child.send_signal(signal.SIGWINCH)
        except ProcessLookupError:
          pass
      previous_resize = signal.signal(signal.SIGWINCH, forward_resize)
    try:
      try:
        code = child.wait()
      except KeyboardInterrupt:
        previous_interrupt = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
          child.send_signal(signal.SIGINT)
          try:
            code = child.wait(timeout=5)
          except subprocess.TimeoutExpired:
            signal_own_group(child, signal.SIGTERM)
            try:
              code = child.wait(timeout=5)
            except subprocess.TimeoutExpired:
              signal_own_group(child, signal.SIGKILL)
              code = child.wait(timeout=5)
        finally:
          signal.signal(signal.SIGINT, previous_interrupt)
    finally:
      if previous_resize is not None:
        signal.signal(signal.SIGWINCH, previous_resize)
      if child.poll() is None:
        signal_own_group(child, signal.SIGTERM)
        try:
          child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          signal_own_group(child, signal.SIGKILL)
          child.wait(timeout=5)
    return code if code >= 0 else 128 - code


def prepare(local, directory, runtime):
  directory = directory.absolute()
  ensure_private(directory)
  with Tree(directory) as operation, instance_lock(operation):
    return _prepare_locked(local, directory, runtime)


def run_experience(local, directory, runtime, *, allow_host=False):
  if not allow_host:
    raise Conflict("--run 需要 --allow-host；会调用显式授权的模型来源")
  directory = directory.absolute()
  with Tree(directory) as operation, instance_lock(operation):
    return _run_locked(local, directory, runtime, allow_host=allow_host)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  mode = parser.add_mutually_exclusive_group(required=True)
  mode.add_argument("--prepare", action="store_true")
  mode.add_argument("--run", action="store_true")
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", type=Path, required=True)
  parser.add_argument("--directory", type=Path, required=True, help="新的私有实验根；固定使用其 workspace 子目录，不暴露当前真实仓库")
  parser.add_argument("--local", type=Path, required=True)
  args = parser.parse_args()
  try:
    if args.prepare:
      prepare(args.local, args.directory, args.runtime.absolute())
      print("Prepared isolated experimental dsh-default. " + NOTICE)
      return 0
    return run_experience(args.local, args.directory, args.runtime.absolute(), allow_host=args.allow_host)
  except Conflict as error:
    print(str(error), file=sys.stderr)
    return 4
  except Exception:
    print("体验准备或启动失败；没有访问旧账号，也不会自动安装依赖", file=sys.stderr)
    return 6


if __name__ == "__main__":
  raise SystemExit(main())

#!/usr/bin/env python3
"""显式隔离 DSH 启动/单次停止验收；不属于默认 pytest，不开放生产控制。"""

import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import uuid


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))


def save(path, value):
  # 仅本次全新私人验收目录；不接受或重放日常控制文件。
  raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
  temporary = path.with_name(".pending-" + uuid.uuid4().hex)
  fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
  with os.fdopen(fd, "wb") as stream:
    stream.write(raw)
    stream.flush()
    os.fsync(stream.fileno())
  os.link(temporary, path)
  temporary.unlink()
  directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
  try:
    os.fsync(directory)
  finally:
    os.close(directory)


def candidate_launcher(original, workspace, registry, factory_for, previous_runs):
  # 仅本验收包装仓库自有启动函数；不替换候选查询/协调器/原生 writer。
  from agentcfg import run_owners

  def launch(spec, env, pass_fds, **kwargs):
    run_id = kwargs.get("run_id")
    run_owners._run_id(run_id)
    actual = kwargs.get("owner_registry")
    if (kwargs.get("resume") is not True or run_id in previous_runs
        or type(actual) is not run_owners.Registry or actual.root != registry.root
        or actual.binding_digest != registry.binding_digest
        or (kwargs.get("control_factory") is not None and not callable(kwargs["control_factory"]))
        or kwargs.get("attempt") is None
        or not callable(kwargs.get("before_dispatch")) or not callable(kwargs.get("after_dispatch"))
        or type(pass_fds) is not tuple or len(pass_fds) < 2
        or any(type(fd) is not int or fd < 0 for fd in pass_fds)
        or len(set(pass_fds)) != len(pass_fds)):
      raise RuntimeError("CANDIDATE_LAUNCH_BOUNDARY")
    for fd in pass_fds:
      os.fstat(fd)
    for fd, path in zip(pass_fds, (workspace.instance, workspace.state_root / "instance.lock")):
      opened, named = os.fstat(fd), path.stat(follow_symlinks=False)
      if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
        raise RuntimeError("CANDIDATE_LEASE_BOUNDARY")
    owner = registry.snapshot().get(run_id)
    if (owner is None or run_owners._encode(owner) != run_owners._encode(actual.snapshot().get(run_id))
        or owner["lifecycle_state"] != "active"
        or run_owners._encode(kwargs.get("manager_identity")) != run_owners._encode(owner["manager_identity"])):
      raise RuntimeError("CANDIDATE_OWNER_BOUNDARY")
    # 此模式独立验收恢复交接，显式换成测试自有停止通道；正常工厂另由 acceptance 验收。
    kwargs.pop("control_factory", None)
    return original(spec, env, pass_fds, **kwargs,
      control_factory=factory_for(pass_fds[0], pass_fds[1]))

  return launch


def worker(root, label, resume, candidate_resume=False):
  from agentcfg import dsh_process, run_owners, runtime
  from agentcfg.stop_dispatches import StopDispatches
  from agentcfg.stop_inbox import StopInbox
  from agentcfg.stop_service import StopService
  from agentcfg.workspace import load_workspace

  workspace = load_workspace(root / "machine.toml", profile="dsh-default", repository=REPOSITORY)
  preparation = json.loads((root / "preparation.json").read_text())
  if (not workspace.instance.is_relative_to(root) or not workspace.state_root.is_relative_to(root)
      or preparation["binding"] != workspace.binding
      or preparation["instance"] != str(workspace.instance)
      or preparation["state_root"] != str(workspace.state_root)):
    raise RuntimeError("WORKER_ISOLATION_BOUNDARY")
  registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
  folder = root / label

  def factory_for(lifecycle_fd, lease):
    def factory(*, run_id, host):
      bound = host.snapshot()
      saved_owner = registry.snapshot()[run_id]
      inbox = StopInbox(folder / "inbox", workspace.binding)
      journal = StopDispatches(folder / "dispatches", workspace.binding)
      request = {
        "schema_version": 1, "kind": "stop-request", "action": "graceful-stop",
        "request_id": uuid.uuid4().hex, "batch_id": uuid.uuid4().hex,
        "plan_id": hashlib.sha256(json.dumps({"test": "isolated-native-stop",
          "binding": workspace.binding, "run": run_id, "host": bound}, sort_keys=True).encode()).hexdigest(),
        "run_id": run_id, "manager_identity": bound["manager_identity"],
        "host_identity": bound["identity"], "deadline_ns": time.monotonic_ns() + 180_000_000_000,
      }

      def verify(current):
        # 明确授权的测试只选择刚启动的这一项；不伪装生产审阅/资源完整覆盖。
        return (current == request and host.snapshot() == bound
          and registry.snapshot().get(run_id) == saved_owner
          and saved_owner["lifecycle_state"] == "active")

      service = StopService(run_id, host, inbox=inbox, journal=journal, verify=verify)
      save(folder / "control.json", {"request": request, "endpoint": inbox.describe(),
        "binding": workspace.binding, "owner": saved_owner,
        "lease_identities": [[os.fstat(fd).st_dev, os.fstat(fd).st_ino] for fd in (lifecycle_fd, lease)]})
      return service

    return factory

  def operation(workspace, spec, env, lease, contract, *, run_id, lifecycle_fd, package_fd):
    manager = registry.snapshot()[run_id]["manager_identity"]
    return dsh_process.launch(spec, env,
      tuple(fd for fd in (lifecycle_fd, lease, package_fd) if isinstance(fd, int)),
      run_id=run_id, owner_registry=registry, manager_identity=manager, control_factory=factory_for(lifecycle_fd, lease))

  if candidate_resume:
    if label != "resume" or not resume:
      raise RuntimeError("CANDIDATE_RESUME_TARGET_REQUIRED")
    from rotom import cli
    from rotom.resume import dsh_candidate
    previous_runs = frozenset(registry.snapshot())
    original = dsh_process.launch
    dsh_process.launch = candidate_launcher(original, workspace, registry, factory_for, previous_runs)
    try:
      code = cli.main(["--no-input", "resume", "dsh", "--local", str(root / "machine.toml"),
        "--profile", "dsh-default", "--session", resume, "--here"], resume_candidate=dsh_candidate())
    finally:
      dsh_process.launch = original
  else:
    code = runtime.run(workspace, cwd=root / "project",
      arguments=("--resume", resume) if resume else (), resume_operation=operation)
  result = {"exit_code": code, "owners": registry.snapshot()}
  if candidate_resume:
    from agentcfg.resume_attempts import ResumeAttempts
    control_path = folder / "control.json"
    result["candidate_resume"] = None
    if control_path.exists():
      control = json.loads(control_path.read_text())
      run_id = control["request"]["run_id"]
      owner = result["owners"].get(run_id)
      attempts = ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding)
      record = attempts.read(run_id)
      if record is not None and owner is not None:
        projection = attempts.for_owner(owner)
        requested = record["requested"]
        result["candidate_resume"] = {"record": record, "projection": projection,
          "request_matches": requested["session"]["native_ref"] == resume
            and record["manager_identity"] == owner["manager_identity"],
          "dispatch_launched": record["dispatch"]["state"] == "launched",
          "exit_matches": record["exit_code"] == code,
          "load_unknown": record["load_confirmation"] == "unknown",
          "continue_not_sent": record["continue_status"] == "not_sent",
          "new_run": run_id not in previous_runs,
          "original_cwd": requested["cwd"] == str(root / "project") == owner["start_cwd"]["path"]}
  save(folder / "worker-result.json", result)
  return code


def session_id(marker):
  if not marker.exists():
    return None
  value = marker.read_text().strip()
  if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
    raise RuntimeError("INVALID_SYNTHETIC_SESSION_MARKER")
  return value


def visible(output):
  text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", output.decode(errors="replace"))
  return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def artifact_ids(workspace):
  # 只列本次合成目录中的官方 JSONL 文件名，不读取会话正文。
  sessions = workspace.instance / "dsh-home/sessions"
  identifiers = {}
  for path in sessions.glob("*/*/session*.jsonl*"):
    if (not re.fullmatch(r"session(?:\.v[1-9][0-9]*)?\.jsonl(?:\.zstd)?", path.name)
        or path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink()
        or not path.is_file()):
      raise RuntimeError("INVALID_SYNTHETIC_SESSION_ARTIFACT")
    identifier = path.parent.name
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier):
      raise RuntimeError("INVALID_SYNTHETIC_SESSION_ARTIFACT")
    if identifier in identifiers and identifiers[identifier] != path.parent:
      raise RuntimeError("CONFLICTING_SYNTHETIC_SESSION_ARTIFACT")
    identifiers[identifier] = path.parent
  return sorted(identifiers)


def history_target(identifiers, marker):
  # marker 缺失可使用唯一真实 artifact；冲突或多目标绝不猜测。
  if len(identifiers) != 1 or (marker is not None and marker != identifiers[0]):
    return None
  return identifiers[0]


def fixture_observation(state):
  with state["gate"]:
    result = {"requests": state["requests"], "responses": sorted(state["responses"]), "error": state["error"]}
    if "request_observations" in state:
      result["request_observations"] = sorted(copy.deepcopy(state["request_observations"]),
        key=lambda item: item["sequence"])
    return result


def fixture_control_ready(folder, binding):
  from agentcfg.stop_inbox import StopInbox
  from agentcfg.stop_requests import decode_stop_request

  # 只有原子发布且身份一致的停止通道就绪，才允许唯一一次合成输入。
  try:
    control = json.loads((folder / "control.json").read_text())
    if control["binding"] != binding:
      return False
    endpoint = StopInbox(folder / "inbox", binding).describe()
    if endpoint is None or endpoint != control["endpoint"]:
      return False
    request = decode_stop_request(json.dumps(control["request"]).encode("utf-8"))
    return all(request[name] == endpoint[name]
      for name in ("run_id", "manager_identity", "host_identity"))
  except Exception:
    # 尚未就绪或元数据不符时仅等待；不能借此发送输入或重建通道。
    return False


def leases_released(workspace, identities):
  descriptors = []
  try:
    if not isinstance(identities, list) or len(identities) != 2:
      return False
    for path, expected in zip((workspace.instance, workspace.state_root / "instance.lock"), identities):
      fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
      descriptors.append(fd)
      current = os.fstat(fd)
      if [current.st_dev, current.st_ino] != expected:
        return False
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      named = path.stat(follow_symlinks=False)
      if [named.st_dev, named.st_ino] != expected:
        return False
    return True
  except OSError:
    return False
  finally:
    for fd in reversed(descriptors):
      os.close(fd)


def phase(root, env, workspace, label, resume=None, fixture=None, candidate_resume=False):
  from agentcfg.stop_dispatches import StopDispatches
  from agentcfg.stop_inbox import StopInbox

  folder = root / label
  folder.mkdir(mode=0o700)
  master, slave = pty.openpty()
  before = termios.tcgetattr(slave)
  fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
  argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--allow-host", "--root", str(root),
    "--worker", label]
  if resume:
    argv.extend(["--resume", resume])
  if candidate_resume:
    argv.extend(["--fixture-history", "--candidate-resume"])
  fixture_before = fixture_observation(fixture) if fixture is not None else None
  child = subprocess.Popen(argv, cwd=root / "project", env=env,
    stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
  output = bytearray()
  marker = workspace.instance / "user-home/.dsh-tui/resume.txt"
  started = time.monotonic()
  input_bytes = 0
  pasted = False
  submitted = False
  stable_since = None
  stable_requests = None
  fixture_completed = False
  resized_for_history = False

  def pump():
    if select.select([master], [], [], 0.1)[0]:
      try:
        output.extend(os.read(master, 65536))
      except OSError:
        pass

  control = None
  observed = None
  try:
    # session marker 仅是人工验收线索，不作为加载完成/输入就绪回执。
    while child.poll() is None and time.monotonic() - started < 30:
      pump()
      if fixture is not None:
        text = re.sub(r"\s+", "", visible(output))
        observation = fixture_observation(fixture)
        if (not resized_for_history and "ONE" in observation["responses"]
            and "DONE_ONE" not in text and time.monotonic() - started >= 3):
          # 原生增量帧会把正文拆成单字；改变测试窗宽取得完整重绘，不借标题证明历史。
          resized_for_history = True
          fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 34, 140, 0, 0))
          os.killpg(child.pid, signal.SIGWINCH)
        if label == "start":
          if (not pasted and not termios.tcgetattr(slave)[3] & termios.ICANON
              and "fixture-not-real" in text and fixture_control_ready(folder, workspace.binding)):
            # 唯一一次合成输入；即使部分写入或观察失败也不重发。
            pasted = True
            input_bytes += os.write(master, b"\x1b[200~CONCURRENCY_ONE\x1b[201~")
          if pasted and not submitted and "CONCURRENCY_ONE" in text:
            submitted = True
            input_bytes += os.write(master, b"\r")
          if (submitted and "ONE" in observation["responses"] and "DONE_ONE" in text
              and observation["error"] is None):
            if stable_since is None or stable_requests != observation["requests"]:
              stable_since = time.monotonic()
              stable_requests = observation["requests"]
            if time.monotonic() - stable_since >= 1:
              fixture_completed = True
              break
          else:
            stable_since = None
        elif "DONE_ONE" in text and time.monotonic() - started >= 8:
          break
      elif (folder / "control.json").exists() and session_id(marker) and time.monotonic() - started >= 8:
        break
    observed = session_id(marker)
    if child.poll() is None and (folder / "control.json").exists():
      control = json.loads((folder / "control.json").read_text())
      inbox = StopInbox(folder / "inbox", workspace.binding)
      inbox.submit(control["request"], expected=control["endpoint"])
    until = time.monotonic() + 30
    while child.poll() is None and time.monotonic() < until:
      pump()
    if child.poll() is None:
      save(folder / "unconfirmed.json", {"status": "waiting-for-original-child", "stop_submitted": bool(control)})
      print("Native child still active; original PTY and leases retained, no retry or escalation.", flush=True)
      # 保留现场，供人工明确处理；绝不因测试超时隐式 kill、关闭 PTY 或重发。
      while child.poll() is None:
        pump()
  except BaseException:
    print("Native observation failed; retain original child and PTY until exit, no retry.", flush=True)
    # 包含读文件/投递异常；不能通过解释器退出间接关闭仍活动宿主的 PTY。
    while child.poll() is None:
      try:
        pump()
      except (OSError, ValueError):
        time.sleep(0.1)
    raise
  code = child.wait()
  while select.select([master], [], [], 0)[0]:
    try:
      chunk = os.read(master, 65536)
    except OSError:
      break
    if not chunk:
      break
    output.extend(chunk)
  restored = before == termios.tcgetattr(slave)
  os.close(master)
  os.close(slave)
  fd = os.open(folder / "transcript.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
  with os.fdopen(fd, "wb") as stream:
    stream.write(output)
  journal = StopDispatches(folder / "dispatches", workspace.binding)
  dispatch = journal.read(control["request"]["run_id"]) if control else None
  worker_result = json.loads((folder / "worker-result.json").read_text()) if (folder / "worker-result.json").exists() else None
  owner = worker_result["owners"].get(control["request"]["run_id"]) if worker_result and control else None
  result = {"exit_code": code, "requested_session": resume, "marker_before_stop": observed,
    "marker_after_exit": session_id(marker), "termios_restored": restored,
    "stop_submitted": control is not None, "dispatch": dispatch,
    "dispatch_matches_request": bool(dispatch and control and dispatch["request"] == control["request"]),
    "transcript_bytes": len(output), "input_bytes_sent": input_bytes,
    "owner_release": owner["lifecycle_state"] if owner else None,
    "physical_leases_released": leases_released(workspace, control["lease_identities"] if control else None),
    "session_files": sorted(str(path.relative_to(workspace.instance / "dsh-home"))
      for path in (workspace.instance / "dsh-home/sessions").glob("*/*/session*.jsonl*"))}
  if candidate_resume:
    result["candidate_resume"] = worker_result.get("candidate_resume") if worker_result else None
  if fixture is not None:
    after = fixture_observation(fixture)
    ids = artifact_ids(workspace)
    text = re.sub(r"\s+", "", visible(output))
    target = history_target(ids, result["marker_after_exit"])
    if observed is not None and observed != target:
      target = None
    result["fixture"] = {"before": fixture_before, "after": after,
      "paste_attempted": pasted, "submit_attempted": submitted,
      "resized_for_history": resized_for_history,
      "history_visible": "DONE_ONE" in text, "artifact_ids": ids,
      "history_target": target,
      "completed_before_stop": fixture_completed,
      "new_model_requests": after["requests"] - fixture_before["requests"]}
  save(folder / "result.json", result)
  return result


def channel_confirmed(result):
  # 143 只证明信号终止，不称作优雅保存；0/143 都须有持久派发和独立后代退出观察。
  return (result["exit_code"] in (0, 143) and result["stop_submitted"]
    and result["dispatch"] is not None and result["dispatch"]["dispatch"] == "signal_sent"
    and result["dispatch_matches_request"]
    and result["owner_release"] == "idle_confirmed" and result["physical_leases_released"])


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true", help="确认本次已获真实隔离宿主与单次 SIGTERM 验收授权")
  parser.add_argument("--root", required=True, type=Path, help="本次全新私人测试根；主入口拒绝已有目录")
  parser.add_argument("--runtime", type=Path, help="已核验的当前锁运行包副本；只读并复制至测试根")
  parser.add_argument("--node", type=Path, help="当前锁要求的精确 Node 可执行文件")
  parser.add_argument("--fixture-history", action="store_true",
    help="显式本地假模型：一次合成输入创建历史，再零输入公开 resume；不访问真实模型")
  parser.add_argument("--candidate-resume", action="store_true",
    help="仅本原生验收通过可信 Python 候选 CLI 恢复；要求 --fixture-history，不开放日常入口")
  parser.add_argument("--worker", help=argparse.SUPPRESS)
  parser.add_argument("--resume", help=argparse.SUPPRESS)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要 --allow-host；只允许显式授权的隔离原生验收")
  if args.candidate_resume and not args.fixture_history:
    parser.error("--candidate-resume 需要 --fixture-history")
  os.umask(0o077)
  root = args.root.absolute()
  if args.worker:
    if args.worker not in ("start", "resume"):
      parser.error("invalid worker label")
    return worker(root, args.worker, args.resume, args.candidate_resume)
  if args.runtime is None or args.node is None or root.exists():
    parser.error("需要已核验 runtime、精确 node 和不存在的私人 root")
  from agentcfg import commands, dependencies, runtime_packages
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace

  lock = dependencies.read_lock(REPOSITORY)
  source = args.runtime.absolute()
  if (runtime_packages.status(source, lock.identity) != "installed"
      or (source / "package.json").read_bytes() != lock.package
      or (source / "pnpm-lock.yaml").read_bytes() != lock.installer_resolution):
    raise RuntimeError("CURRENT_LOCK_RUNTIME_REQUIRED")
  root.mkdir(mode=0o700)
  env = {"PATH": str(args.node.absolute().parent) + ":/usr/bin:/bin", "TERM": "xterm-256color",
    "COLORTERM": "truecolor", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
  for name, suffix in {"HOME": "home", "DSH_HOME": "dsh", "XDG_CONFIG_HOME": "config",
      "XDG_DATA_HOME": "data", "XDG_STATE_HOME": "state", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}.items():
    env[name] = str(root / suffix)
    ensure_private(root / suffix)
  os.environ.clear()
  os.environ.update(env)
  node = subprocess.run([str(args.node), "--version"], env=env, capture_output=True, text=True, check=True).stdout.strip()
  if node != lock.metadata["node"]:
    raise RuntimeError("EXACT_NODE_REQUIRED")
  ensure_private(root / "project")
  server = None
  server_thread = None
  fixture = None
  if args.fixture_history:
    spec = importlib.util.spec_from_file_location("native_concurrency_fixture",
      REPOSITORY / "scripts/smoke-dsh-concurrency.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = {"gate": threading.Lock(), "requests": 0, "responses": set(), "error": None,
      "request_observations": []}
    server = module.FixtureServer(("127.0.0.1", 0), module.handler(fixture, "not-a-real-key"))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
  try:
    machine = root / "machine.toml"
    machine.write_text('schema_version=1\n[machine]\nid="native-stop-fixture"\n'
      '[overrides.providers.fixture]\nprotocol="openai-compatible"\nauth_kind="api-key"\n'
      f'credential_ref="secret:fixture"\nbase_url="http://127.0.0.1:{server.server_port if server else 9}/v1"\n'
      '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-not-real"\ninput=["text"]\n'
      '[overrides.profiles.dsh-default]\nproviders=["fixture"]\nmodels=["fixture"]\n'
      '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n'
      '[overrides.profiles.dsh-default.agent_options]\nshow_welcome=false\n'
      '[secrets]\nfixture="not-a-real-key"\n')
    machine.chmod(0o600)
    workspace = load_workspace(machine, profile="dsh-default", repository=REPOSITORY)
    destination = workspace.backend.root(workspace, lock.identity)
    if not destination.is_relative_to(root):
      raise RuntimeError("ISOLATION_BOUNDARY")
    ensure_private(destination.parent)
    shutil.copytree(source, destination, symlinks=True)
    if runtime_packages.status(destination, lock.identity) != "installed":
      raise RuntimeError("COPIED_RUNTIME_INVALID")
    candidate = workspace.candidate(lock.identity)
    commands.apply_candidate(workspace, lock, candidate)
    with Tree(workspace.state_root) as state, instance_lock(state):
      workspace.adapter.prepare_runtime(workspace, destination)
    save(root / "preparation.json", {"lock_identity": lock.identity, "generation": candidate.generation,
      "node": node, "binding": workspace.binding, "instance": str(workspace.instance),
      "state_root": str(workspace.state_root), "runtime": str(destination), "source": str(source)})
    start = phase(root, env, workspace, "start", fixture=fixture)
    results = {"start": start}
    target = (start["fixture"]["history_target"] if fixture is not None else start["marker_after_exit"])
    history_ready = (fixture is None or (start["fixture"]["completed_before_stop"]
      and "ONE" in start["fixture"]["after"]["responses"]
      and start["fixture"]["after"]["error"] is None))
    if channel_confirmed(start) and history_ready and target:
      results["resume"] = phase(root, env, workspace, "resume", target, fixture=fixture,
        candidate_resume=args.candidate_resume)
    save(root / "result.json", results)
    print(json.dumps({name: {key: item[key] for key in
      ("exit_code", "stop_submitted", "termios_restored", "input_bytes_sent", "transcript_bytes")}
      for name, item in results.items()}, sort_keys=True))
    passed = all(channel_confirmed(item) and item["termios_restored"] for item in results.values())
    if fixture is not None:
      resumed = results.get("resume")
      # Rotom 恢复须零自动输入；宿主辅助模型调用保留观测，须独立审阅来源。
      # 本脚本退出 0 不能替代调用来源审查或完整 T053 能力准入判断。
      passed = bool(passed and history_ready and target and resumed
        and resumed["input_bytes_sent"] == 0
        and resumed["fixture"]["after"]["error"] is None
        and resumed["fixture"]["artifact_ids"] == [target]
        and resumed["fixture"]["history_target"] == target and resumed["fixture"]["history_visible"])
    if args.candidate_resume:
      evidence = results.get("resume", {}).get("candidate_resume")
      passed = bool(passed and evidence is not None and all(evidence[name] is True for name in
        ("request_matches", "dispatch_launched", "exit_matches", "load_unknown", "continue_not_sent",
          "new_run", "original_cwd")))
    return 0 if passed else 1
  finally:
    # 仅关闭本进程自己的本地服务；不触碰 child/PTY/宿主。
    if server is not None:
      server.shutdown()
      server.server_close()
      server_thread.join()


if __name__ == "__main__":
  raise SystemExit(main())

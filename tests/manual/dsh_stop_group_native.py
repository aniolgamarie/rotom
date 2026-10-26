#!/usr/bin/env python3
"""显式隔离 DSH 三选二停止验收；零输入、独立第三项清理，不验证会话恢复。"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import termios
import time


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("native_group_acceptance", HERE / "dsh_stop_acceptance_native.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
acceptance.DEFAULT_LAUNCH = True
base = acceptance.base
_WORKERS = ("start-0", "start-1", "start-2")
_CLIENTS = ("selected-two", "third-cleanup")


def pump(workers):
  """只读取全部原 PTY；不发送任何输入，也不因一个 child 退出关闭其它终端。"""
  masters = [item["master"] for item in workers]
  if not masters:
    return
  readable = select.select(masters, [], [], 0.1)[0]
  for item in workers:
    if item["master"] in readable:
      try:
        item["output"].extend(os.read(item["master"], 65536))
      except OSError:
        pass


def active(workers, clients):
  return any(item["child"].poll() is None for item in workers) or any(child.poll() is None for child in clients)


def preserve(workers, clients, folder, reason):
  """诊断写失败或再次中断也不退出活动 PTY；返回期间遇到的首个控制异常。"""
  interrupted = None
  try:
    path = folder / "unconfirmed.json"
    if not path.exists():
      base.save(path, {"status": "unconfirmed", "reason": reason})
    print("Native group unconfirmed; retaining original PTYs without retry or additional signal.", flush=True)
  except BaseException as error:
    if not isinstance(error, Exception):
      interrupted = error
  while True:
    try:
      if not active(workers, clients):
        return interrupted
      pump(workers)
    except BaseException as error:
      if not isinstance(error, Exception) and interrupted is None:
        interrupted = error
      # 观察失败不证明原进程退出；保留原 PTY，不改用关闭或信号清理。
      try:
        time.sleep(0.1)
      except BaseException as error:
        if not isinstance(error, Exception) and interrupted is None:
          interrupted = error


def lease_probe(workspace, identities):
  results = []
  for path, expected in zip((workspace.instance, workspace.state_root / "instance.lock"), identities):
    fd = None
    value = {"identity_matches": False, "busy": False, "exclusive_available": False}
    try:
      fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
      info = os.fstat(fd)
      named = path.stat(follow_symlinks=False)
      value["identity_matches"] = ([info.st_dev, info.st_ino] == expected
        and [named.st_dev, named.st_ino] == expected)
      if value["identity_matches"]:
        try:
          fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
          value["exclusive_available"] = True
        except BlockingIOError:
          value["busy"] = True
    except OSError:
      pass
    finally:
      if fd is not None:
        os.close(fd)
    results.append(value)
  return results


def read_rows(registry):
  with registry._locked(nonblocking=True) as owner:
    if owner is None:
      raise RuntimeError("GROUP_OWNER_REQUIRED")
    records, _ = registry._records(owner)
    registry._verify_root(owner)
    return records


def group_phase(root, env, workspace, label, resume=None, fixture=None, candidate_resume=False):
  from agentcfg import dsh_stop_client, dsh_stop_completion, run_owners, run_stop_fence
  from agentcfg.stop_dispatches import StopDispatches
  from agentcfg.stop_inbox import StopInbox
  if label != "start" or resume is not None or fixture is not None or candidate_resume:
    raise RuntimeError("GROUP_NO_INPUT_NO_RESUME_ONLY")
  folder = root / label
  folder.mkdir(mode=0o700)
  workers, clients = [], []
  registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
  journal = StopDispatches(workspace.state_root / "stop-dispatches", workspace.binding)
  identities = [[path.stat().st_dev, path.stat().st_ino] for path in
    (workspace.instance, workspace.state_root / "instance.lock")]
  baselines, batches = {}, []

  def start_client(client_label, runs):
    target = root / client_label
    target.mkdir(mode=0o700)
    base.save(target / "control.json", {"run_id": runs[0], "run_ids": runs})
    argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--group-client", str(root), client_label]
    base.save(target / "process-argv.json", {"argv": argv})
    with (target / "client.json").open("xb") as stdout, (target / "client.stderr").open("xb") as stderr:
      child = subprocess.Popen(argv, cwd=root / "project", env=env, stdin=subprocess.DEVNULL,
        stdout=stdout, stderr=stderr)
    clients.append(child)
    return child, target

  def wait_selected(client, selected):
    until = time.monotonic() + 40
    while (client.poll() is None or any(item["child"].poll() is None for item in selected)) and time.monotonic() < until:
      pump(workers)
    if client.poll() is None or any(item["child"].poll() is None for item in selected):
      interrupted = preserve(workers, clients, folder, "selected-stop-not-confirmed")
      if interrupted is not None:
        raise interrupted
      raise RuntimeError("GROUP_SELECTED_STOP_UNCONFIRMED")
    pump(workers)

  def batch_result(client, target, selected):
    result = json.loads((target / "client.json").read_text())
    batch = result["batch_id"]
    saved = run_stop_fence.read_snapshot(registry, batch)
    close = dsh_stop_completion.read_close(registry, batch)
    status = dsh_stop_client.status_stop(workspace, batch_id=batch)
    expected = sorted(selected)
    checks = {"client_exit_zero": client.returncode == 0, "status_stopped": status["status"] == "stopped",
      "fence_closed": run_stop_fence.read(registry) is None and status["protected"] is False,
      "snapshot_selection": saved is not None and saved["selected_runs"] == expected,
      "close_matches": bool(close and close["reason"] == "stopped" and close["batch_id"] == batch
        and close["plan_id"] == result["plan_id"] == saved["plan_id"]
        and sorted(close["records"]) == expected)}
    value = {"client_exit_code": client.returncode, "result": result, "snapshot": saved,
      "close": close, "status": status, "checks": checks}
    base.save(target / "verified-result.json", value)
    batches.append(value)
    if not all(checks.values()):
      raise RuntimeError("GROUP_BATCH_NOT_CONFIRMED")
    return value

  try:
    for worker_label in _WORKERS:
      target = root / worker_label
      target.mkdir(mode=0o700)
      master, slave = pty.openpty()
      before = termios.tcgetattr(slave)
      fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
      argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--group-worker", str(root), worker_label]
      base.save(target / "worker-argv.json", {"argv": argv})
      child = subprocess.Popen(argv, cwd=root / "project", env=env, stdin=slave, stdout=slave, stderr=slave,
        start_new_session=True)
      workers.append({"label": worker_label, "child": child, "master": master, "slave": slave,
        "before": before, "output": bytearray()})
      # 本次验证同时活动后的停止，不把 optional host 登记的并发启动竞争纳入目标。
      # 每项已由默认入口完成登记后，才启动下一项；期间持续读取所有原 PTY。
      ready = None
      registration_until = time.monotonic() + 25
      while time.monotonic() < registration_until:
        pump(workers)
        if any(item["child"].poll() is not None for item in workers):
          raise RuntimeError("GROUP_EARLY_MANAGER_EXIT")
        try:
          matches = [row for row in read_rows(registry).values()
            if row["manager_identity"]["pid"] == child.pid and row["lifecycle_state"] == "active"
            and row["protocol"]["control"] is not None]
          if len(matches) == 1:
            row = matches[0]
            endpoint = StopInbox(workspace.state_root / "stop-inboxes" / row["run_id"], workspace.binding).describe()
            if run_owners._encode(endpoint) == run_owners._encode(row["protocol"]["control"]["endpoint"]):
              ready = row
              break
        except Exception:
          # 只读短锁竞争仍在原窗口内观察；不补登记、不重启、不发请求或输入。
          continue
      if ready is None:
        raise RuntimeError("GROUP_SEQUENTIAL_REGISTRATION_UNCONFIRMED")
      base.save(target / "registered.json", {"owner": ready, "manager_pid": child.pid})
    started = time.monotonic()
    until = started + 25
    while time.monotonic() < until:
      pump(workers)
      if any(item["child"].poll() is not None for item in workers):
        raise RuntimeError("GROUP_EARLY_MANAGER_EXIT")
      try:
        rows = read_rows(registry)
        found = {}
        for item in workers:
          matches = [row for row in rows.values() if row["manager_identity"]["pid"] == item["child"].pid
            and row["lifecycle_state"] == "active" and row["protocol"]["control"] is not None]
          if len(matches) != 1:
            break
          row = matches[0]
          endpoint = StopInbox(workspace.state_root / "stop-inboxes" / row["run_id"], workspace.binding).describe()
          if run_owners._encode(endpoint) != run_owners._encode(row["protocol"]["control"]["endpoint"]):
            break
          found[item["label"]] = row
        if len(found) == 3 and time.monotonic() - started >= 8:
          baselines = found
          break
      except Exception:
        # 只读登记竞争可以再次观察；绝不补登记、重发输入或请求。
        continue
    if len(baselines) != 3 or len({row["run_id"] for row in baselines.values()}) != 3:
      raise RuntimeError("GROUP_CONTROL_NOT_READY")
    if not all(item["identity_matches"] and item["busy"] for item in lease_probe(workspace, identities)):
      raise RuntimeError("GROUP_ORIGINAL_LEASES_NOT_HELD")
    base.save(folder / "active-owners.json", {"owners": baselines, "lease_identities": identities})
    selected = [baselines[name]["run_id"] for name in _WORKERS[:2]]
    first, first_folder = start_client(_CLIENTS[0], selected)
    wait_selected(first, workers[:2])
    first_batch = batch_result(first, first_folder, selected)
    third = baselines[_WORKERS[2]]
    current = read_rows(registry).get(third["run_id"])
    channel = StopInbox(workspace.state_root / "stop-inboxes" / third["run_id"], workspace.binding)
    with channel._registry._locked(nonblocking=True) as tree:
      endpoint, requests = channel._load(tree)
      channel._expected(third["protocol"]["control"]["endpoint"], endpoint)
    probe = lease_probe(workspace, identities)
    third_checks = {"owner_unchanged_active": run_owners._encode(current) == run_owners._encode(third)
        and current["lifecycle_state"] == "active",
      "manager_still_live": workers[2]["child"].poll() is None
        and run_owners.observed_process_identity(third["manager_identity"]["pid"]) == third["manager_identity"],
      "host_birth_unchanged": run_owners.observed_process_identity(third["host_identity"]["identity"]["pid"])
        == third["host_identity"]["identity"], "requests_empty": not requests,
      "journal_absent": journal.read(third["run_id"]) is None,
      "shared_ex_blocked": all(item["identity_matches"] and item["busy"] for item in probe),
      "first_fence_closed": first_batch["checks"]["fence_closed"]}
    base.save(folder / "third-remains-active.json", {"checks": third_checks, "owner": current, "leases": probe})
    if not all(third_checks.values()):
      raise RuntimeError("GROUP_THIRD_NOT_INDEPENDENT")
    # 独立计划仅清理原第三项；从不重试前两项，也不扩大所选集合。
    last, last_folder = start_client(_CLIENTS[1], [third["run_id"]])
    wait_selected(last, workers[2:])
    batch_result(last, last_folder, [third["run_id"]])
    if batches[0]["result"]["batch_id"] == batches[1]["result"]["batch_id"]:
      raise RuntimeError("GROUP_CLEANUP_MUST_BE_DISTINCT_BATCH")
  except BaseException:
    # 包括 Ctrl-C：保留全部原进程和 PTY，直到它们自然结束才透传异常。
    preserve(workers, clients, folder, "group-check-unconfirmed")
    raise

  owners = read_rows(registry)
  worker_results = []
  for item in workers:
    code = item["child"].wait()
    restored = item["before"] == termios.tcgetattr(item["slave"])
    target = root / item["label"]
    (target / "transcript.bin").write_bytes(item["output"])
    run = baselines[item["label"]]["run_id"]
    dispatch = journal.read(run)
    matching = [entry for entry in batches if run in entry["snapshot"]["selected_runs"]]
    inbox = StopInbox(workspace.state_root / "stop-inboxes" / run, workspace.binding)
    with inbox._registry._locked(nonblocking=True) as tree:
      endpoint, requests = inbox._load(tree)
      inbox._expected(baselines[item["label"]]["protocol"]["control"]["endpoint"], endpoint)
    matches = bool(dispatch and len(requests) == 1 and list(requests.values())[0] == dispatch["request"]
      and len(matching) == 1 and dispatch["request"]["run_id"] == run
      and dispatch["request"]["batch_id"] == matching[0]["result"]["batch_id"]
      and dispatch["request"]["plan_id"] == matching[0]["snapshot"]["plan_id"])
    value = {"exit_code": code, "owner_release": owners[run]["lifecycle_state"],
      "dispatch": dispatch, "request_count": len(requests), "dispatch_matches_request": matches, "termios_restored": restored,
      "input_bytes_sent": 0, "transcript_bytes": len(item["output"])}
    base.save(target / "result.json", value)
    worker_results.append(value)
    # 所有原 manager 与客户端均已结束，才关闭本进程拥有的 PTY。
    os.close(item["master"]); os.close(item["slave"])
  released = base.leases_released(workspace, identities)
  marker = base.session_id(workspace.instance / "user-home/.dsh-tui/resume.txt")
  result = {"kind": "three-select-two-stop", "exit_code": 0 if all(item["exit_code"] == 0 for item in worker_results) else 1,
    "stop_submitted": len(clients) == 2, "termios_restored": all(item["termios_restored"] for item in worker_results),
    "input_bytes_sent": 0, "transcript_bytes": sum(item["transcript_bytes"] for item in worker_results),
    "marker_after_exit": marker, "physical_leases_released": released, "workers": worker_results,
    "batches": batches, "third_checks": third_checks, "no_resume_validation": True}
  base.save(folder / "result.json", result)
  return result


def group_confirmed(result):
  return bool(result.get("kind") == "three-select-two-stop" and result["exit_code"] == 0
    and result["stop_submitted"] and result["physical_leases_released"] and result["input_bytes_sent"] == 0
    and result["marker_after_exit"] is None and all(result["third_checks"].values())
    and len(result["workers"]) == 3 and len(result["batches"]) == 2
    and all(item["exit_code"] == 0 and item["termios_restored"] and item["owner_release"] == "idle_confirmed"
      and item["dispatch_matches_request"] and item["dispatch"] is not None
      and item["dispatch"]["dispatch"] == "signal_sent" for item in result["workers"])
    and all(all(entry["checks"].values()) for entry in result["batches"]))


base.phase, base.channel_confirmed = group_phase, group_confirmed
base.__doc__ = __doc__


if __name__ == "__main__":
  os.umask(0o077)
  if len(sys.argv) == 4 and sys.argv[1] in ("--group-worker", "--group-client"):
    root, label = Path(sys.argv[2]), sys.argv[3]
    if not root.is_absolute() or ".." in root.parts:
      raise SystemExit("PRIVATE_ABSOLUTE_GROUP_ROOT_REQUIRED")
    if sys.argv[1] == "--group-worker" and label in _WORKERS:
      raise SystemExit(acceptance.worker(root, label, None))
    if sys.argv[1] == "--group-client" and label in _CLIENTS:
      raise SystemExit(acceptance.client(root, label))
    raise SystemExit("FIXED_GROUP_LABEL_REQUIRED")
  if any(option in sys.argv for option in ("--fixture-history", "--candidate-resume", "--worker", "--resume")):
    raise SystemExit("GROUP_NO_INPUT_NO_RESUME_ONLY")
  raise SystemExit(base.main())

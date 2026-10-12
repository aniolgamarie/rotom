"""显式纯Pi合成基线采集；默认只准备/核验，不在import或测试时启动宿主。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import select
import stat
import subprocess
import sys
import time

from .pi_budgets import IDENTITIES
from .schema import ConfigError


ROOT = Path(__file__).resolve().parents[2]
SDK_VERSION = "1.0.1"
METHOD_REVISION = 1
WARMUPS = 3
COLD_RUNS = 10
SAME_SESSION_PROMPTS = 30
MAX_TOTAL_CALLS = 43
SAMPLE_INTERVAL_NS = 100_000_000
MAX_EVENT_LINE = 16 * 1024
MAX_EVENT_BYTES = 2 * 1024 * 1024
MAX_OUTER_STDERR_BYTES = 256 * 1024
MAX_SAMPLE_ROWS = 1202
MAX_PROCESSES_PER_SAMPLE = 32
MAX_SAMPLE_TIMEOUT_SECONDS = 120
MAX_SDK_TREE_BYTES = 256 * 1024 * 1024
MAX_SDK_TREE_ENTRIES = 50000
PHASES = ("warmup", "cold", "same-session")
METRIC_UNITS = {
  "cli_ready_ms": "ms", "first_response_ms": "ms", "same_session_response_ms": "ms",
  "idle_rss_peak_bytes": "bytes", "idle_cpu_ticks": "ticks", "idle_fd_peak": "count",
  "idle_descendant_peak": "count", "post_task_live_descendants_30s": "count",
  "post_task_rss_peak_bytes": "bytes", "post_task_cpu_ticks": "ticks"}
PLATFORM_KEYS = {"schema_version", "profile", "method_revision", "authorization", "platform", "runtime", "input", "schedule"}
PLATFORM_ID_KEYS = ("platform_identity", "runtime_identity", "method_identity", "checker_identity", "input_identity")
AUTH_KEYS = {"reference", "max_model_calls", "external_model_calls", "paid_cost", "paid_currency"}
SCHEDULE_KEYS = {"warmups", "cold_runs", "same_session_interactions", "idle_seconds_per_run", "post_task_seconds_per_run", "sample_interval_ms", "per_sample_timeout_seconds"}


def _fail():
  raise ConfigError("pi-benchmark-input")


def _sha(raw):
  return hashlib.sha256(raw).hexdigest()


def _regular_digest(path):
  path = Path(path)
  info = path.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 256 * 1024 * 1024: _fail()
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  try:
    opened = os.fstat(fd)
    if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns): _fail()
    hasher = hashlib.sha256()
    size = 0
    while True:
      chunk = os.read(fd, min(1024 * 1024, info.st_size - size + 1))
      if not chunk: break
      size += len(chunk)
      if size > info.st_size: _fail()
      hasher.update(chunk)
    after = os.fstat(fd)
    if (size, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
        info.st_size, info.st_size, info.st_mtime_ns, info.st_ctime_ns): _fail()
    return hasher.hexdigest()
  finally:
    os.close(fd)


def _json(data):
  try:
    value = json.loads(data, object_pairs_hook=_unique_pairs, parse_constant=lambda _: _fail())
  except (ValueError, UnicodeError, TypeError):
    _fail()
  return value


def _unique_pairs(pairs):
  value = {}
  for key, item in pairs:
    if key in value: _fail()
    value[key] = item
  return value


def _bytes(value):
  return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def _write_new(path, raw, mode=0o600):
  fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
  try:
    os.fchmod(fd, mode)
    with os.fdopen(fd, "wb", closefd=False) as stream:
      stream.write(raw); stream.flush(); os.fsync(fd)
  finally:
    os.close(fd)


def _sync_existing(path):
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  try:
    os.fsync(fd)
  finally:
    os.close(fd)


def _open_new_private(path):
  fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
  os.fchmod(fd, 0o600)
  return os.fdopen(fd, "wb")


def _hex(value):
  return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _tree_digest(paths):
  rows = []
  for name, path in sorted(paths.items()):
    rows.append({"name": name, "sha256": _regular_digest(path)})
  return _sha(_bytes(rows))


def _canonical_path(value, *, directory=None):
  if not isinstance(value, str) or not value or "\x00" in value: _fail()
  path = Path(value)
  if not path.is_absolute() or ".." in path.parts: _fail()
  try: resolved = path.resolve(strict=True)
  except OSError: _fail()
  if resolved != path: _fail()
  info = path.lstat()
  if directory is True and not stat.S_ISDIR(info.st_mode): _fail()
  if directory is False and not stat.S_ISREG(info.st_mode): _fail()
  return path


RUNTIME_DOCUMENT_KEYS = {
  "schema_version", "sdk_version", "sdk_tree_root", "sdk_root", "sdk_inventory_path", "sdk_inventory_sha256",
  "cli_path", "cli_sha256", "package_path", "package_sha256", "node_path", "node_sha256", "bwrap_path", "bwrap_sha256",
}


def _read_runtime_document(path):
  path = Path(path)
  info = path.lstat()
  if not path.is_absolute() or ".." in path.parts or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 64 * 1024: _fail()
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  try:
    opened = os.fstat(fd)
    if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size): _fail()
    raw = os.read(fd, 64 * 1024 + 1)
    if len(raw) != info.st_size or len(raw) > 64 * 1024: _fail()
  finally:
    os.close(fd)
  document = _json(raw)
  if not isinstance(document, dict) or set(document) != RUNTIME_DOCUMENT_KEYS or type(document.get("schema_version")) is not int or document["schema_version"] != 1: _fail()
  if document.get("sdk_version") != SDK_VERSION: _fail()
  directories = {"sdk_tree_root", "sdk_root"}
  paths = {key: _canonical_path(document.get(key), directory=(key in directories) if key in directories or key in {
    "sdk_inventory_path", "cli_path", "package_path", "node_path", "bwrap_path"} else None) for key in (
    "sdk_tree_root", "sdk_root", "sdk_inventory_path", "cli_path", "package_path", "node_path", "bwrap_path")}
  try:
    paths["sdk_root"].relative_to(paths["sdk_tree_root"])
    paths["cli_path"].relative_to(paths["sdk_root"])
    paths["package_path"].relative_to(paths["sdk_root"])
  except ValueError: _fail()
  if paths["cli_path"] != paths["sdk_root"] / "dist/cli.js" or paths["package_path"] != paths["sdk_root"] / "package.json": _fail()
  if not all(_hex(document.get(key)) for key in ("sdk_inventory_sha256", "cli_sha256", "package_sha256", "node_sha256", "bwrap_sha256")): _fail()
  if paths["package_path"].stat().st_size > 64 * 1024: _fail()
  if paths["sdk_inventory_path"].stat().st_size > 8 * 1024 * 1024: _fail()
  if paths["node_path"].stat().st_mode & 0o111 == 0 or paths["bwrap_path"].stat().st_mode & 0o111 == 0: _fail()
  package_raw = paths["package_path"].read_bytes()
  package = _json(package_raw)
  if not isinstance(package, dict) or package.get("name") != "@earendil-works/pi-coding-agent" or package.get("version") != SDK_VERSION: _fail()
  for path_key, hash_key in (("cli_path", "cli_sha256"), ("package_path", "package_sha256"), ("node_path", "node_sha256"), ("bwrap_path", "bwrap_sha256"), ("sdk_inventory_path", "sdk_inventory_sha256")):
    if _regular_digest(paths[path_key]) != document[hash_key]: _fail()
  return document, raw, paths


def platform_snapshot(runtime):
  if not sys.platform.startswith("linux") or os.uname().machine not in ("x86_64", "aarch64"): _fail()
  release = Path("/proc/sys/kernel/osrelease").read_text(encoding="ascii").strip()
  os_release = Path("/etc/os-release").read_bytes()
  try:
    clock_ticks = os.sysconf("SC_CLK_TCK")
    page_size_bytes = os.sysconf("SC_PAGE_SIZE")
  except (OSError, ValueError):
    _fail()
  if type(clock_ticks) is not int or clock_ticks <= 0 or type(page_size_bytes) is not int or page_size_bytes <= 0: _fail()
  bwrap_sha = runtime["bwrap_sha256"]
  node_path_sha = runtime["node_sha256"]
  return {"platform": "linux-x86_64" if os.uname().machine == "x86_64" else "linux-arm64",
    "kernel_release": release, "os_release_sha256": _sha(os_release), "bwrap_sha256": bwrap_sha,
    "node_sha256": node_path_sha, "clock_ticks": clock_ticks, "page_size_bytes": page_size_bytes,
    "platform_identity": _sha(_bytes({"machine": os.uname().machine,
      "release": release, "os_release_sha256": _sha(os_release), "bwrap_sha256": bwrap_sha,
      "clock_ticks": clock_ticks, "page_size_bytes": page_size_bytes}))}


def fixed_runtime(runtime_document_path):
  document, raw, paths = _read_runtime_document(runtime_document_path)
  tree_relative = paths["sdk_root"].relative_to(paths["sdk_tree_root"])
  cli_relative = paths["cli_path"].relative_to(paths["sdk_tree_root"])
  if not cli_relative.parts or cli_relative.parts[0] != tree_relative.parts[0]: _fail()
  guest_cli = "/opt/sdk-tree/" + cli_relative.as_posix()
  return {"runtime_document_path": str(Path(runtime_document_path)), "runtime_document_sha256": _sha(raw),
    "sdk_version": document["sdk_version"], "sdk_root": str(paths["sdk_root"]), "sdk_tree_root": str(paths["sdk_tree_root"]),
    "sdk_tree_id": tree_relative.parts[0], "sdk_inventory_path": str(paths["sdk_inventory_path"]),
    "sdk_inventory_sha256": document["sdk_inventory_sha256"], "cli_path": str(paths["cli_path"]),
    "cli_guest_path": guest_cli, "cli_sha256": document["cli_sha256"], "package_path": str(paths["package_path"]),
    "package_sha256": document["package_sha256"], "node_path": str(paths["node_path"]), "node_guest_path": "/opt/node",
    "node_sha256": document["node_sha256"], "bwrap_path": str(paths["bwrap_path"]), "bwrap_sha256": document["bwrap_sha256"]}


def fixed_input():
  prompt = "Return exactly the fixed synthetic response sentinel."
  reply = "PURE_PI_SYNTHETIC_RESPONSE_OK"
  project = {"kind": "empty-directory", "relative_entries": []}
  return {"provider_id": "synthetic-local", "model_id": "synthetic-main", "api": "openai-completions",
    "base_url_template": "http://127.0.0.1:<ephemeral-port>/v1", "prompt": prompt, "prompt_sha256": _sha(prompt.encode()),
    "response": reply, "response_sha256": _sha(reply.encode()), "project": project,
    "project_identity": _sha(_bytes(project)), "credential": "private-synthetic-only-no-account",
    "external_model_calls": 0, "paid_cost": "0"}


def make_plan(authorization_ref, *, per_sample_timeout_seconds, runtime_document_path):
  if not isinstance(authorization_ref, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", authorization_ref) is None: _fail()
  if type(per_sample_timeout_seconds) is not int or not 100 <= per_sample_timeout_seconds <= MAX_SAMPLE_TIMEOUT_SECONDS: _fail()
  runtime = fixed_runtime(runtime_document_path); platform = platform_snapshot(runtime); input_value = fixed_input()
  method_path = ROOT / "specs/005-pi-two-profiles/acceptance.md"
  method_identity = _regular_digest(method_path)
  checker_identity = _tree_digest({"module": ROOT / "src/agentcfg/pi_benchmark.py", "script": ROOT / "scripts/benchmark-pi-profiles.py"})
  runtime_identity = _sha(_bytes(runtime)); input_identity = _sha(_bytes(input_value))
  return {"schema_version": 1, "profile": "pure-pi", "method_revision": METHOD_REVISION,
    "authorization": {"reference": authorization_ref, "max_model_calls": MAX_TOTAL_CALLS,
      "external_model_calls": 0, "paid_cost": "0", "paid_currency": "USD"},
    "platform": {**platform, "platform_identity": platform["platform_identity"]},
    "runtime": {**runtime, "runtime_identity": runtime_identity},
    "input": {**input_value, "input_identity": input_identity},
    "schedule": {"warmups": WARMUPS, "cold_runs": COLD_RUNS, "same_session_interactions": SAME_SESSION_PROMPTS,
      "idle_seconds_per_run": 60, "post_task_seconds_per_run": 30, "sample_interval_ms": 100,
      "per_sample_timeout_seconds": per_sample_timeout_seconds},
    "method_identity": method_identity, "checker_identity": checker_identity}


def validate_plan(plan):
  if not isinstance(plan, dict) or set(plan) != PLATFORM_KEYS | {"method_identity", "checker_identity"}: _fail()
  if type(plan["schema_version"]) is not int or plan["schema_version"] != 1 or plan["profile"] != "pure-pi" or type(plan["method_revision"]) is not int or plan["method_revision"] != METHOD_REVISION: _fail()
  auth = plan["authorization"]
  if not isinstance(auth, dict) or set(auth) != AUTH_KEYS or not isinstance(auth["reference"], str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", auth["reference"]) is None: _fail()
  if type(auth["max_model_calls"]) is not int or auth["max_model_calls"] != MAX_TOTAL_CALLS or type(auth["external_model_calls"]) is not int or auth["external_model_calls"] != 0 or auth["paid_cost"] != "0" or auth["paid_currency"] != "USD": _fail()
  platform, runtime, input_value, schedule = (plan[name] for name in ("platform", "runtime", "input", "schedule"))
  if not isinstance(platform, dict) or not isinstance(runtime, dict) or not isinstance(input_value, dict) or not isinstance(schedule, dict): _fail()
  if set(platform) != {"platform", "kernel_release", "os_release_sha256", "bwrap_sha256", "node_sha256", "clock_ticks", "page_size_bytes", "platform_identity"}: _fail()
  if platform.get("platform") not in ("linux-x86_64", "linux-arm64") or not isinstance(platform.get("kernel_release"), str) or not platform["kernel_release"]: _fail()
  if type(platform.get("clock_ticks")) is not int or platform["clock_ticks"] <= 0 or type(platform.get("page_size_bytes")) is not int or platform["page_size_bytes"] <= 0: _fail()
  if not all(_hex(platform.get(name)) for name in ("os_release_sha256", "bwrap_sha256", "node_sha256", "platform_identity")): _fail()
  expected_platform = _sha(_bytes({"machine": "x86_64" if platform["platform"] == "linux-x86_64" else "aarch64",
    "release": platform["kernel_release"], "os_release_sha256": platform["os_release_sha256"], "bwrap_sha256": platform["bwrap_sha256"],
    "clock_ticks": platform["clock_ticks"], "page_size_bytes": platform["page_size_bytes"]}))
  if expected_platform != platform["platform_identity"]: _fail()
  if set(runtime) != {"runtime_document_path", "runtime_document_sha256", "sdk_version", "sdk_root", "sdk_tree_root", "sdk_tree_id", "sdk_inventory_path", "sdk_inventory_sha256", "cli_path", "cli_guest_path", "cli_sha256", "package_path", "package_sha256", "node_path", "node_guest_path", "node_sha256", "bwrap_path", "bwrap_sha256", "runtime_identity"}: _fail()
  if runtime.get("sdk_version") != SDK_VERSION or runtime.get("node_guest_path") != "/opt/node": _fail()
  if not all(_hex(runtime.get(name)) for name in ("runtime_document_sha256", "sdk_inventory_sha256", "cli_sha256", "package_sha256", "node_sha256", "bwrap_sha256", "runtime_identity")): _fail()
  for name in ("runtime_document_path", "sdk_root", "sdk_tree_root", "sdk_inventory_path", "cli_path", "node_path", "bwrap_path"):
    if not isinstance(runtime.get(name), str) or not Path(runtime[name]).is_absolute() or ".." in Path(runtime[name]).parts: _fail()
  try:
    Path(runtime["sdk_root"]).relative_to(Path(runtime["sdk_tree_root"]))
    Path(runtime["cli_path"]).relative_to(Path(runtime["sdk_root"]))
  except ValueError: _fail()
  if runtime.get("cli_guest_path") != "/opt/sdk-tree/" + Path(runtime["cli_path"]).relative_to(Path(runtime["sdk_tree_root"])).as_posix(): _fail()
  runtime_core = {key: value for key, value in runtime.items() if key != "runtime_identity"}
  if _sha(_bytes(runtime_core)) != runtime["runtime_identity"]: _fail()
  if set(input_value) != {"provider_id", "model_id", "api", "base_url_template", "prompt", "prompt_sha256", "response", "response_sha256", "project", "project_identity", "credential", "external_model_calls", "paid_cost", "input_identity"}: _fail()
  if input_value.get("provider_id") != "synthetic-local" or input_value.get("model_id") != "synthetic-main" or input_value.get("api") != "openai-completions" or input_value.get("base_url_template") != "http://127.0.0.1:<ephemeral-port>/v1": _fail()
  if input_value.get("prompt") != fixed_input()["prompt"] or input_value.get("response") != fixed_input()["response"]: _fail()
  if input_value.get("prompt_sha256") != _sha(input_value["prompt"].encode()) or input_value.get("response_sha256") != _sha(input_value["response"].encode()): _fail()
  if input_value.get("external_model_calls") != 0 or input_value.get("paid_cost") != "0" or input_value.get("credential") != "private-synthetic-only-no-account": _fail()
  if input_value.get("project") != {"kind": "empty-directory", "relative_entries": []} or input_value.get("project_identity") != _sha(_bytes(input_value["project"])): _fail()
  input_core = {key: value for key, value in input_value.items() if key != "input_identity"}
  if input_value.get("input_identity") != _sha(_bytes(input_core)): _fail()
  if not _hex(plan.get("method_identity")) or not _hex(plan.get("checker_identity")): _fail()
  if plan["method_identity"] != _regular_digest(ROOT / "specs/005-pi-two-profiles/acceptance.md"): _fail()
  if plan["checker_identity"] != _tree_digest({"module": ROOT / "src/agentcfg/pi_benchmark.py", "script": ROOT / "scripts/benchmark-pi-profiles.py"}): _fail()
  if set(schedule) != SCHEDULE_KEYS or schedule["warmups"] != WARMUPS or schedule["cold_runs"] != COLD_RUNS or schedule["same_session_interactions"] != SAME_SESSION_PROMPTS: _fail()
  if type(schedule["idle_seconds_per_run"]) is not int or schedule["idle_seconds_per_run"] != 60 or type(schedule["post_task_seconds_per_run"]) is not int or schedule["post_task_seconds_per_run"] != 30 or type(schedule["sample_interval_ms"]) is not int or schedule["sample_interval_ms"] != 100: _fail()
  if type(schedule["per_sample_timeout_seconds"]) is not int or not 100 <= schedule["per_sample_timeout_seconds"] <= MAX_SAMPLE_TIMEOUT_SECONDS: _fail()
  return plan


def parse_proc_stat(raw):
  """按最后一个右括号解析Linux stat，避免comm含空格/括号时错位。"""
  if not isinstance(raw, str): _fail()
  left = raw.find("("); right = raw.rfind(")")
  if left <= 0 or right <= left or not raw[:left].strip().isdigit(): _fail()
  pid = int(raw[:left].strip()); comm = raw[left + 1:right]; fields = raw[right + 1:].split()
  if len(fields) < 22: _fail()
  try:
    return {"pid": pid, "comm": comm, "state": fields[0], "ppid": int(fields[1]), "pgrp": int(fields[2]),
      "utime": int(fields[11]), "stime": int(fields[12]), "starttime": int(fields[19]), "rss_pages": int(fields[21])}
  except (ValueError, IndexError):
    _fail()


def birth_tuple(record):
  return {"pid": record["pid"], "starttime": record["starttime"], "pidns_inode": record["pidns_inode"]}


class ProcObserver:
  """只用stat扫描PPID关系；仅对已锚定后代读取cmdline/exe/fd元数据。"""
  def __init__(self, proc_root="/proc", *, node_path, node_guest_path, bwrap_path, cli_guest_path):
    self.proc_root = Path(proc_root); self.node_path = Path(node_path); self.node_guest_path = node_guest_path
    self.bwrap_path = Path(bwrap_path); self.cli_guest_path = cli_guest_path
    info = self.node_path.stat(); self.node_identity = (info.st_dev, info.st_ino)
    bwrap_info = self.bwrap_path.stat(); self.bwrap_identity = (bwrap_info.st_dev, bwrap_info.st_ino)
    self.known = {}
    self.outer_identity = None
    self.target_identity = None
    self.target_pidfd = None
    self.pidfd_identity = None

  def close(self):
    fd, self.target_pidfd = self.target_pidfd, None
    self.pidfd_identity = None
    if fd is not None: os.close(fd)

  def _pin_target(self, target):
    # 假proc默认测试不触碰真实系统PID；原CLI固定使用真实/proc。
    if self.proc_root != Path("/proc") or self.target_pidfd is not None or not hasattr(os, "pidfd_open"):
      return
    if target["uid"] != os.geteuid(): return
    fd = None
    try:
      before = self._details(target["pid"], target)
      if before is None or birth_tuple(before) != birth_tuple(target): return
      fd = os.pidfd_open(target["pid"], 0)
      os.set_inheritable(fd, False)
      after = self._details(target["pid"], target)
      if (after is None or birth_tuple(after) != birth_tuple(target)
          or after["uid"] != target["uid"] or (after["exe_device"], after["exe_inode"]) != self.node_identity):
        return
      self.target_pidfd = fd; self.pidfd_identity = birth_tuple(target); fd = None
    except OSError:
      pass
    finally:
      if fd is not None: os.close(fd)

  def _target_exit_seen(self, timeout_ms=0):
    if type(timeout_ms) is not int or not 0 <= timeout_ms <= 100: return False
    if self.target_pidfd is None or self.pidfd_identity != self.target_identity: return False
    try:
      polling = select.poll(); polling.register(self.target_pidfd, select.POLLIN)
      events = polling.poll(timeout_ms)
    except OSError:
      return False
    return (not any(flags & (select.POLLERR | select.POLLNVAL) for _, flags in events)
      and any(flags & (select.POLLIN | select.POLLHUP) for _, flags in events))

  def _all_stat(self):
    records = {}
    try: entries = os.listdir(self.proc_root)
    except OSError: return None
    for name in entries:
      if not name.isdigit(): continue
      try: record = parse_proc_stat((self.proc_root / name / "stat").read_text())
      except (OSError, ConfigError): continue
      if str(record["pid"]) == name: records[name] = record
    return records

  def _chain(self, outer_pid, records):
    root = records.get(str(outer_pid))
    if root is None: return None, None
    descendants = {str(outer_pid): root}; changed = True
    while changed:
      changed = False
      for pid, row in records.items():
        if pid not in descendants and str(row["ppid"]) in descendants:
          descendants[pid] = row; changed = True
    return root, descendants

  def _details(self, pid, row):
    base = self.proc_root / str(pid)
    try:
      before = parse_proc_stat((base / "stat").read_text())
      if before["starttime"] != row["starttime"] or before["ppid"] != row["ppid"]: return None
      status = (base / "status").read_text()
      uid_line = next(line for line in status.splitlines() if line.startswith("Uid:"))
      uid = int(uid_line.split()[1]); nspid_line = next((line for line in status.splitlines() if line.startswith("NSpid:")), "NSpid:")
      nspid = [int(value) for value in nspid_line.split()[1:]]
      ns_info = (base / "ns/pid").stat()
      exe_info = (base / "exe").stat()
      cmdline_raw = (base / "cmdline").read_bytes()
      argv = [part.decode("utf-8", "strict") for part in cmdline_raw.rstrip(b"\0").split(b"\0")] if cmdline_raw else []
      fd_count = len(os.listdir(base / "fd"))
      rss_line = next(line for line in status.splitlines() if line.startswith("VmRSS:"))
      rss_bytes = int(rss_line.split()[1]) * 1024
      ns_inode = ns_info.st_ino
      after = parse_proc_stat((base / "stat").read_text())
      ns_after = (base / "ns/pid").stat().st_ino
    except (OSError, StopIteration, ValueError, UnicodeError):
      return None
    if (after["starttime"], after["ppid"], ns_after) != (before["starttime"], before["ppid"], ns_inode): return None
    identity = {**row, "uid": uid, "nspid": nspid, "pidns_inode": ns_inode,
      "exe_device": exe_info.st_dev, "exe_inode": exe_info.st_ino, "argv": argv,
      "rss_bytes": rss_bytes, "fd_count": fd_count}
    key = (row["pid"], row["starttime"], ns_inode)
    return identity

  def identify(self, outer_pid):
    records = self._all_stat()
    if records is None: return {"status": "unknown", "reason": "proc_unavailable"}
    outer, descendants = self._chain(outer_pid, records)
    if outer is None: return {"status": "unknown", "reason": "outer_missing"}
    outer_detail = self._details(int(outer_pid), outer)
    if outer_detail is None: return {"status": "unknown", "reason": "outer_unreadable"}
    if (outer_detail["exe_device"], outer_detail["exe_inode"]) != self.bwrap_identity:
      return {"status": "missing", "reason": "outer_executable_mismatch"}
    if not outer_detail["argv"] or outer_detail["argv"][0] != str(self.bwrap_path):
      return {"status": "missing", "reason": "outer_argv_mismatch"}
    current_outer = birth_tuple(outer_detail)
    if self.outer_identity is not None and current_outer != self.outer_identity:
      return {"status": "missing", "reason": "outer_birth_changed"}
    self.outer_identity = current_outer
    self.known.pop((outer_detail["pid"], outer_detail["starttime"], outer_detail["pidns_inode"]), None)
    node_matches = []; driver_matches = []
    for pid, row in descendants.items():
      if pid == str(outer_pid): continue
      detail = self._details(int(pid), row)
      if detail is None: continue
      if (detail["exe_device"], detail["exe_inode"]) != self.node_identity: continue
      argv = detail["argv"]
      if len(argv) >= 2 and argv[1] == self.cli_guest_path: node_matches.append(detail)
    if len(node_matches) > 1:
      return {"status": "unknown", "reason": "inner_node_ambiguous", "outer": current_outer}
    if len(node_matches) == 0:
      if self.target_identity is not None:
        alive = self.known_alive()
        if all(item.get("status") in ("verified", "missing") for item in alive):
          live = [item["process"] for item in alive if item.get("process") is not None]
          target_tuple = (self.target_identity["pid"], self.target_identity["starttime"], self.target_identity["pidns_inode"])
          return {"status": "verified", "outer": self.outer_identity, "target": self.target_identity,
            "processes": live,
            "descendant_count": sum(1 for item in live if (item["pid"], item["starttime"], item["pidns_inode"]) != target_tuple),
            "rss_bytes": sum(item["rss_bytes"] for item in live),
            "cpu_ticks": sum(item["utime"] + item["stime"] for item in live),
            "fd_count": sum(item["fd_count"] for item in live),
            "target_exit_fact": "original-pidfd-readable" if self._target_exit_seen() else None,
            "target_exited": not any(item.get("identity") == target_tuple and item.get("status") == "verified" for item in alive)}
        return {"status": "unknown", "reason": "inner_node_exit_unverified", "outer": current_outer,
          "target": self.target_identity}
      return {"status": "missing", "reason": "inner_node_unidentified", "outer": current_outer, "descendant_count": len(descendants) - 1}
    target = node_matches[0]
    if not target["argv"] or target["argv"][0] != self.node_guest_path:
      return {"status": "missing", "reason": "inner_node_argv_mismatch", "outer": outer}
    current_target = birth_tuple(target)
    if self.target_identity is not None and current_target != self.target_identity:
      return {"status": "missing", "reason": "inner_node_birth_changed", "outer": current_outer}
    target_descendants = {}
    changed = True
    while changed:
      changed = False
      for pid, row in records.items():
        if pid == str(target["pid"]) or pid in target_descendants: continue
        parent_known = str(row["ppid"]) == str(target["pid"]) or str(row["ppid"]) in target_descendants
        if parent_known:
          detail = self._details(int(pid), row)
          if detail is None: return {"status": "unknown", "reason": "descendant_unreadable", "outer": current_outer, "target": self.target_identity}
          target_descendants[pid] = detail; changed = True
    processes = [target, *target_descendants.values()]
    self.target_identity = current_target
    self._pin_target(target)
    self.known.update({(item["pid"], item["starttime"], item["pidns_inode"]): item for item in processes})
    return {"status": "verified", "outer": current_outer,
      "target": birth_tuple(target), "processes": processes, "descendant_count": len(target_descendants),
      "rss_bytes": sum(item["rss_bytes"] for item in processes),
      "cpu_ticks": sum(item["utime"] + item["stime"] for item in processes),
      "fd_count": sum(item["fd_count"] for item in processes)}

  def known_alive(self):
    alive = []
    for identity, old in list(self.known.items()):
      is_target = self.target_identity is not None and identity == (
        self.target_identity["pid"], self.target_identity["starttime"], self.target_identity["pidns_inode"])
      if is_target and self._target_exit_seen():
        alive.append({"status": "missing", "identity": identity, "exit_fact": "original-pidfd-readable"})
        continue
      pid = str(identity[0])
      try:
        now = parse_proc_stat((self.proc_root / pid / "stat").read_text())
      except FileNotFoundError:
        alive.append({"status": "missing", "identity": identity})
        continue
      except (OSError, ConfigError):
        alive.append({"status": "unknown", "identity": identity})
        continue
      if now["starttime"] != old["starttime"]:
        alive.append({"status": "missing", "identity": identity})
        continue
      try:
        ns = (self.proc_root / pid / "ns/pid").stat().st_ino
      except FileNotFoundError:
        alive.append({"status": "missing", "identity": identity})
        continue
      except OSError:
        alive.append({"status": "unknown", "identity": identity})
        continue
      if ns == old["pidns_inode"]:
        is_target = self.target_identity is not None and identity == (
          self.target_identity["pid"], self.target_identity["starttime"], self.target_identity["pidns_inode"])
        if is_target and now["state"] == "Z":
          state = self._target_zombie_state(pid, old)
          alive.append({"status": state, "identity": identity})
          continue
        try:
          detail = self._details(int(pid), now)
        except Exception:
          detail = None
        if detail is not None:
          alive.append({"status": "verified", "identity": identity, "process": detail})
        elif is_target:
          # 详情读取期间CLI可能刚退出；只对已锚定目标复核原birth的Z/消失状态。
          alive.append({"status": self._target_zombie_state(pid, old), "identity": identity})
        else:
          alive.append({"status": "unknown", "identity": identity})
      else:
        alive.append({"status": "missing", "identity": identity})
    # proc读取本身跨多个系统调用；目标可能在第一次poll后才退出。
    # 发布本tick前重验原pidfd，只能补同birth目标，不能补未知后代。
    target_key = None if self.target_identity is None else (
      self.target_identity["pid"], self.target_identity["starttime"], self.target_identity["pidns_inode"])
    if (any(item.get("identity") == target_key and item.get("status") == "unknown" for item in alive)
        and self._target_exit_seen(100)):
      alive = [{"status": "missing", "identity": item["identity"], "exit_fact": "original-pidfd-readable"}
        if item.get("identity") == target_key and item.get("status") == "unknown" else item for item in alive]
    return alive

  def _target_zombie_state(self, pid, old):
    """仅在原CLI birth仍为同owner Z态时证明它不可执行；其余情况保留unknown。"""
    base = self.proc_root / pid
    try:
      before = parse_proc_stat((base / "stat").read_text())
    except FileNotFoundError:
      return "missing"
    except (OSError, ConfigError):
      return "unknown"
    if before["starttime"] != old["starttime"]:
      return "missing"
    if before["state"] != "Z":
      return "unknown"
    try:
      status = (base / "status").read_text()
      uid_line = next(line for line in status.splitlines() if line.startswith("Uid:"))
      uid = int(uid_line.split()[1])
      namespace = (base / "ns/pid").stat().st_ino
    except (OSError, StopIteration, ValueError, IndexError):
      try:
        current = parse_proc_stat((base / "stat").read_text())
      except FileNotFoundError:
        return "missing"
      except (OSError, ConfigError):
        return "unknown"
      return "missing" if current["starttime"] != old["starttime"] else "unknown"
    try:
      after = parse_proc_stat((base / "stat").read_text())
    except FileNotFoundError:
      return "missing"
    except (OSError, ConfigError):
      return "unknown"
    try:
      namespace_after = (base / "ns/pid").stat().st_ino
    except FileNotFoundError:
      try:
        current = parse_proc_stat((base / "stat").read_text())
      except FileNotFoundError:
        return "missing"
      except (OSError, ConfigError):
        return "unknown"
      return "missing" if current["starttime"] != old["starttime"] else "unknown"
    except OSError:
      return "unknown"
    if (after["starttime"], after["state"], namespace_after) != (before["starttime"], "Z", namespace):
      return "missing" if after["starttime"] != old["starttime"] or namespace_after != old["pidns_inode"] else "unknown"
    if namespace != old["pidns_inode"]:
      return "missing"
    if uid != old["uid"] or uid != os.geteuid():
      return "unknown"
    return "missing"


def build_invocation(plan, work, phase, index, driver_path):
  validate_plan(plan)
  work = Path(work)
  if not work.is_absolute() or ".." in work.parts or phase not in PHASES or type(index) is not int or index < 0: _fail()
  argv = [plan["runtime"]["bwrap_path"], "--die-with-parent", "--unshare-all", "--new-session", "--cap-drop", "ALL",
    "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
    "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--ro-bind", str(plan["runtime"]["sdk_tree_root"]), "/opt/sdk-tree",
    "--ro-bind", plan["runtime"]["node_path"], "/opt/node", "--dir", "/probe", "--ro-bind", str(driver_path), "/probe/driver.mjs",
    "--bind", str(work), "/work", "--setenv", "HOME", "/work/home", "--setenv", "PI_CODING_AGENT_DIR", "/work/home/.pi",
    "--setenv", "PI_OFFLINE", "1", "--setenv", "XDG_CONFIG_HOME", "/work/home/.config", "--setenv", "XDG_DATA_HOME", "/work/home/.local/share",
    "--setenv", "XDG_CACHE_HOME", "/work/home/.cache", "--setenv", "XDG_STATE_HOME", "/work/home/.local/state",
    "--setenv", "TMPDIR", "/tmp", "--setenv", "PATH", "/opt:/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8",
    "--chdir", "/work/project", "/opt/node", "/probe/driver.mjs", "--phase", phase, "--index", str(index),
    "--cli", plan["runtime"]["cli_guest_path"], "--work", "/work"]
  return argv


def _proc_sample(observer, outer_pid, timestamp_ns, phase, *, owned_process=None):
  sample = observer.identify(outer_pid)
  # 仅采集器持有的原 Popen.wait 事实补齐已锚定直接子进程的退出过渡。
  # wait 不证明后代终止；此前观测到的每个 birth 仍须逐个复核。
  if (sample.get("reason") in ("outer_unreadable", "outer_missing")
      and owned_process is not None and owned_process.pid == outer_pid
      and observer.outer_identity is not None and observer.outer_identity["pid"] == outer_pid
      and observer.target_identity is not None):
    exit_code = owned_process.poll()
    if type(exit_code) is int:
      alive = observer.known_alive()
      if alive and all(item.get("status") in ("verified", "missing") for item in alive):
        live = [item["process"] for item in alive if item.get("process") is not None]
        target = observer.target_identity
        target_key = (target["pid"], target["starttime"], target["pidns_inode"])
        sample = {"status": "verified", "reason": "owned_outer_wait_observed", "outer": observer.outer_identity,
          "target": target, "outer_wait_exit_code": exit_code, "processes": live,
          "target_exit_fact": "original-pidfd-readable" if observer._target_exit_seen() else None,
          "descendant_count": sum((item["pid"], item["starttime"], item["pidns_inode"]) != target_key for item in live),
          "rss_bytes": sum(item["rss_bytes"] for item in live),
          "cpu_ticks": sum(item["utime"] + item["stime"] for item in live),
          "fd_count": sum(item["fd_count"] for item in live)}
  process_rows = sample.get("processes", [])
  if len(process_rows) > MAX_PROCESSES_PER_SAMPLE:
    sample = {"status": "unknown", "reason": "process_sample_limit"}
    process_rows = []
  processes = [{key: row[key] for key in ("pid", "starttime", "ppid", "nspid", "pidns_inode", "uid", "rss_bytes", "fd_count", "utime", "stime", "exe_device", "exe_inode")}
    for row in process_rows]
  return {"host_monotonic_ns": timestamp_ns, "phase": phase, "identity_status": sample["status"],
    "identity_reason": sample.get("reason"), "outer": sample.get("outer"), "target": sample.get("target"),
    "outer_wait_exit_code": sample.get("outer_wait_exit_code"),
    "target_exit_fact": sample.get("target_exit_fact"),
    "processes": processes, "rss_bytes": sample.get("rss_bytes"),
    "cpu_ticks": sample.get("cpu_ticks"), "fd_count": sample.get("fd_count"),
    "descendant_count": sample.get("descendant_count")}


def summarize_samples(plan, records):
  validate_plan(plan)
  expected = {(phase, index) for phase, count in (("warmup", WARMUPS), ("cold", COLD_RUNS)) for index in range(count)}
  expected.add(("same-session", 0))
  if not isinstance(records, list) or len(records) != len(expected) or {(row.get("phase"), row.get("index")) for row in records if isinstance(row, dict)} != expected: _fail()
  rows = {(row["phase"], row["index"]): row for row in records}
  if any(row.get("status") not in ("observed", "failed", "timeout") or not isinstance(row.get("metrics"), dict) for row in rows.values()): _fail()
  def sample(row, key, *, source="metrics"):
    if row.get("status") in ("failed", "timeout"):
      return {"status": row["status"]}
    value = row.get(source, {}).get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
      return {"status": "observed", "value": str(value)}
    if value is not None: _fail()
    if row.get("status") == "timeout": return {"status": "timeout"}
    if row.get("status") == "failed": return {"status": "failed"}
    return {"status": "missing"}
  metrics = {}
  cold = [rows[("cold", index)] for index in range(COLD_RUNS)]
  warmup = [rows[("warmup", index)] for index in range(WARMUPS)]
  for key in ("cli_ready_ms", "first_response_ms", "idle_rss_peak_bytes", "idle_cpu_ticks", "idle_fd_peak", "idle_descendant_peak",
    "post_task_live_descendants_30s", "post_task_rss_peak_bytes", "post_task_cpu_ticks"):
    metrics[key] = {"unit": METRIC_UNITS[key], "samples": [sample(row, key) for row in cold],
      "warmup_samples": [sample(row, key) for row in warmup]}
  same = rows[("same-session", 0)]
  values = same.get("metrics", {}).get("same_session_response_ms")
  if not isinstance(values, list) or len(values) > SAME_SESSION_PROMPTS or any(type(value) not in (int, float) or value <= 0 for value in values): _fail()
  same_samples = ([{"status": "observed", "value": str(value)} for value in values]
    + [{"status": "missing"} for _ in range(SAME_SESSION_PROMPTS - len(values))]) if same["status"] == "observed" else [
      {"status": same["status"]} for _ in range(SAME_SESSION_PROMPTS)]
  metrics["same_session_response_ms"] = {"unit": "ms",
    "samples": same_samples,
    "warmup_samples": []}
  baseline = {"schema_version": 1, "profile": "pure-pi", "platform": plan["platform"]["platform"],
    "platform_identity": plan["platform"]["platform_identity"], "runtime_identity": plan["runtime"]["runtime_identity"],
    "method_identity": plan["method_identity"], "checker_identity": plan["checker_identity"],
    "input_identity": plan["input"]["input_identity"], "metrics": metrics}
  return baseline


def _read_plan(path):
  path = Path(path)
  info = path.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 1024 * 1024: _fail()
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  try:
    opened = os.fstat(fd)
    if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size): _fail()
    raw = os.read(fd, 1024 * 1024 + 1)
    if len(raw) != info.st_size: _fail()
  finally:
    os.close(fd)
  return validate_plan(_json(raw))


def _private_dir(path, *, create):
  path = Path(path)
  if not path.is_absolute() or ".." in path.parts: _fail()
  for parent in reversed(path.parents[:-1]):
    try: parent_info = parent.lstat()
    except FileNotFoundError: _fail()
    if not stat.S_ISDIR(parent_info.st_mode): _fail()
  if create:
    if path.exists() or path.is_symlink(): _fail()
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o022: _fail()
    path.mkdir(mode=0o700)
  info = path.lstat()
  if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700: _fail()
  return path


def prepare(output, authorization_ref, per_sample_timeout_seconds, runtime_document_path):
  plan = validate_plan(make_plan(authorization_ref, per_sample_timeout_seconds=per_sample_timeout_seconds,
    runtime_document_path=runtime_document_path))
  _verify_fixed_inputs(plan)
  path = _private_dir(output, create=True)
  _write_new(path / "plan.json", _bytes(plan))
  (path / "runs").mkdir(mode=0o700)
  return {"status": "prepared", "native_started": False, "product_gate": False, "profile": "pure-pi"}


def _verify_fixed_inputs(plan):
  runtime = fixed_runtime(plan["runtime"]["runtime_document_path"])
  if _sha(_bytes(runtime)) != _sha(_bytes({key: value for key, value in plan["runtime"].items() if key != "runtime_identity"})): _fail()
  _verify_sdk_tree(runtime)
  platform = platform_snapshot(runtime)
  if platform["platform_identity"] != plan["platform"]["platform_identity"]: _fail()


def _verify_sdk_tree(runtime):
  inventory_path = Path(runtime["sdk_inventory_path"]); tree_root = Path(runtime["sdk_tree_root"])
  inventory_info = inventory_path.lstat()
  if not stat.S_ISREG(inventory_info.st_mode) or inventory_info.st_nlink != 1 or inventory_info.st_size > 8 * 1024 * 1024: _fail()
  fd = os.open(inventory_path, os.O_RDONLY | os.O_NOFOLLOW)
  try:
    opened = os.fstat(fd)
    if (opened.st_dev, opened.st_ino, opened.st_size) != (inventory_info.st_dev, inventory_info.st_ino, inventory_info.st_size): _fail()
    chunks = []; hasher = hashlib.sha256(); size = 0
    while True:
      chunk = os.read(fd, 1024 * 1024)
      if not chunk: break
      size += len(chunk)
      if size > inventory_info.st_size: _fail()
      chunks.append(chunk); hasher.update(chunk)
    if size != inventory_info.st_size or hasher.hexdigest() != runtime["sdk_inventory_sha256"]: _fail()
  finally:
    os.close(fd)
  rows = _json(b"".join(chunks))
  if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SDK_TREE_ENTRIES: _fail()
  expected = set()
  total_bytes = 0
  root_resolved = tree_root.resolve(strict=True)
  for row in rows:
    if not isinstance(row, dict) or not isinstance(row.get("path"), str): _fail()
    rel = Path(row["path"])
    if rel.is_absolute() or not rel.parts or ".." in rel.parts or row["path"] in expected: _fail()
    expected.add(row["path"])
    target = tree_root / rel
    info = target.lstat()
    kind = row.get("kind")
    if kind == "file":
      if type(row.get("bytes")) is not int or row["bytes"] < 0: _fail()
      total_bytes += row["bytes"]
      if total_bytes > MAX_SDK_TREE_BYTES or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != row["bytes"] or row.get("sha256") != _regular_digest(target): _fail()
    elif kind == "directory":
      if not stat.S_ISDIR(info.st_mode): _fail()
    elif kind == "symlink":
      if not stat.S_ISLNK(info.st_mode) or os.readlink(target) != row.get("target"): _fail()
      resolved = target.resolve(strict=True)
      try: relative = resolved.relative_to(root_resolved)
      except ValueError: _fail()
      if row.get("resolved_relative") != relative.as_posix(): _fail()
    else: _fail()
  actual = set()
  for base, directories, files in os.walk(tree_root, followlinks=False):
    base_path = Path(base)
    for name in directories + files:
      actual.add((base_path / name).relative_to(tree_root).as_posix())
      if len(actual) > MAX_SDK_TREE_ENTRIES: _fail()
  if actual != expected: _fail()


def _driver_source():
  return r'''import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { mkdir, writeFile, open } from "node:fs/promises";
import { createInterface } from "node:readline";
const args=process.argv.slice(2), get=(k)=>args[args.indexOf(k)+1], phase=get("--phase"), index=Number(get("--index")), cli=get("--cli"), work=get("--work");
const home=work+"/home", pi=home+"/.pi", captures=work+"/captures", provider="synthetic-local", model="synthetic-main", key="synthetic-only-no-account";
 const reply="PURE_PI_SYNTHETIC_RESPONSE_OK", prompt="Return exactly the fixed synthetic response sentinel.", calls=[]; let child, events=[], lines=[], stdoutBytes=0, stderrBytes=0, exitCode=null, exitSignal=null, sentinelTurns=0;
function emit(name, fields={}) { const driverNs=process.hrtime.bigint(); process.stdout.write(JSON.stringify({kind:"event",name,phase,index,...fields,driver_monotonic_ns:driverNs.toString()})+"\n"); return driverNs; }
function waitUntil(deadline) { return new Promise(resolve=>{function check(){const remaining=deadline-process.hrtime.bigint();if(remaining<=0n){resolve();return};setTimeout(check,Math.max(1,Math.ceil(Number(remaining)/1e6)))}check()}); }
function waitFor(predicate, start, ms=60000) { for(let i=start;i<events.length;i++)if(predicate(events[i]))return Promise.resolve({row:events[i],index:i}); return new Promise((resolve,reject)=>{let timer=setTimeout(()=>{process.off("rpc-line",scan);reject(new Error("protocol-timeout"));},ms);function scan(row){if(predicate(row)){clearTimeout(timer);process.off("rpc-line",scan);resolve({row,index:events.length-1})}}process.on("rpc-line",scan)}); }
function chunks(){ const rows=[{id:"synthetic",object:"chat.completion.chunk",created:1,model,choices:[{index:0,delta:{role:"assistant"},finish_reason:null}]},{id:"synthetic",object:"chat.completion.chunk",created:1,model,choices:[{index:0,delta:{content:reply},finish_reason:null}]},{id:"synthetic",object:"chat.completion.chunk",created:1,model,choices:[{index:0,delta:{},finish_reason:"stop"}],usage:{prompt_tokens:7,completion_tokens:1,total_tokens:8}}]; return rows.map(x=>`data: ${JSON.stringify(x)}\n\n`).join("")+"data: [DONE]\n\n"; }
async function main(){
 await mkdir(pi,{recursive:true,mode:0o700}); await mkdir(captures,{recursive:true,mode:0o700});
 const server=createServer(async(req,res)=>{let body="";for await(const chunk of req)body+=chunk.toString("utf8");let parsed={};try{parsed=JSON.parse(body)}catch{};calls.push({method:req.method,path:req.url,model:parsed.model??null,stream:parsed.stream===true,message_count:Array.isArray(parsed.messages)?parsed.messages.length:0,synthetic_auth_present:typeof req.headers.authorization==="string"});emit("synthetic_request",{call_index:calls.length,model:parsed.model??null});res.writeHead(200,{"content-type":"text/event-stream","cache-control":"no-cache"});const text=chunks();emit("synthetic_response_first",{call_index:calls.length});res.end(text,()=>emit("synthetic_response_last",{call_index:calls.length}));});
 await new Promise((resolve,reject)=>{server.once("error",reject);server.listen(0,"127.0.0.1",resolve)});const address=server.address();
 const cfg={providers:{[provider]:{name:"Synthetic local provider",api:"openai-completions",baseUrl:`http://127.0.0.1:${address.port}/v1`,apiKey:key,models:[{id:model,name:"Synthetic baseline model",reasoning:false,input:["text"],contextWindow:4096,maxTokens:64,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}]}}};
 await writeFile(pi+"/models.json",JSON.stringify(cfg),{mode:0o600});
 child=spawn(process.execPath,[cli,"--mode","rpc","--offline","--no-extensions","--no-skills","--no-prompt-templates","--no-themes","--no-session","--provider",provider,"--model",model],{cwd:work+"/project",env:{PATH:"/opt:/usr/bin:/bin",HOME:home,PI_CODING_AGENT_DIR:pi,PI_OFFLINE:"1",XDG_CONFIG_HOME:home+"/.config",XDG_DATA_HOME:home+"/.local/share",XDG_CACHE_HOME:home+"/.cache",XDG_STATE_HOME:home+"/.local/state",TMPDIR:"/tmp",LANG:"C.UTF-8"},stdio:["pipe","pipe","pipe"]});
 const rl=createInterface({input:child.stdout}); const out=await open(captures+"/sdk.stdout","wx",0o600), err=await open(captures+"/sdk.stderr","wx",0o600);
 rl.on("line",async line=>{const raw=Buffer.from(line+"\n");stdoutBytes+=raw.length;if(stdoutBytes>2*1024*1024){child.kill("SIGKILL");return};await out.write(raw);let row;try{row=JSON.parse(line)}catch{return};events.push(row);process.emit("rpc-line",row)});
 child.stderr.on("data",async data=>{stderrBytes+=data.length;if(stderrBytes>256*1024){child.kill("SIGKILL");return};await err.write(data)});
 child.once("exit",(code,sig)=>{exitCode=code;exitSignal=sig;emit("cli_exit",{exit_code:code,signal:sig})});
 let at=0; child.stdin.write(JSON.stringify({type:"get_state",id:"ready"})+"\n"); const ready=await waitFor(x=>x.type==="response"&&x.id==="ready",at); at=ready.index+1;
 if(ready.row.success!==true||ready.row.data?.model?.provider!==provider||ready.row.data?.model?.id!==model)throw new Error("model-not-ready"); emit("cli_ready");
 if(phase!=="same-session"){const idleStart=emit("idle_start");await waitUntil(idleStart+60000000000n);emit("idle_end");}
 const count=phase==="same-session"?30:1, latencies=[];
 for(let i=0;i<count;i++){const id=`prompt-${i}`, begin=process.hrtime.bigint(), before=events.length;emit("prompt_write",{prompt_index:i});child.stdin.write(JSON.stringify({type:"prompt",id,message:prompt})+"\n");const accepted=await waitFor(x=>x.type==="response"&&x.id===id,at);at=accepted.index+1;if(accepted.row.success!==true||accepted.row.data?.disposition!=="started")throw new Error("prompt-not-accepted");const ended=await waitFor(x=>x.type==="agent_end",at);at=ended.index+1;if(events.slice(before).some(x=>JSON.stringify(x).includes(reply)))sentinelTurns++;else throw new Error("synthetic-response-missing");latencies.push(Number(process.hrtime.bigint()-begin)/1e6);emit("agent_end",{prompt_index:i});}
 child.stdin.end();emit("rpc_eof");await new Promise((resolve,reject)=>{if(exitCode!==null)return resolve();const timer=setTimeout(()=>reject(new Error("cli-exit-timeout")),30000);child.once("exit",()=>{clearTimeout(timer);resolve()})});
 const postStart=emit("task_end");await waitUntil(postStart+30000000000n);
 await out.sync();await err.sync();await out.close();await err.close();await new Promise(resolve=>server.close(resolve));
 const result={phase,index,cli_exit_code:exitCode,cli_signal:exitSignal,stdout_bytes:stdoutBytes,stderr_bytes:stderrBytes,synthetic_request_count:calls.length,synthetic_requests:calls,assistant_sentinel_count:sentinelTurns,rpc_tool_event_count:events.filter(x=>x.type==="tool_execution_start"||x.type==="tool_execution_end").length,prompt_latency_ms:latencies};
 await writeFile(work+"/driver-result.json",JSON.stringify(result),{mode:0o600});emit("driver_done",{exit_code:exitCode,requests:calls.length});
}
main().catch(async()=>{if(child&&exitCode===null){try{child.kill("SIGKILL")}catch{}};try{await writeFile(work+"/driver-result.json",JSON.stringify({phase,index,failed:true,synthetic_request_count:calls.length}),{mode:0o600})}catch{};emit("driver_failed");process.exitCode=1});
'''


def _create_work(run_dir):
  (run_dir / "work").mkdir(mode=0o700)
  work = run_dir / "work"
  for name in ("home", "tmp", "project", "captures"):
    (work / name).mkdir(mode=0o700)
  for name in (".config", ".cache", ".local", ".local/share", ".local/state"):
    path = work / "home" / name
    if not path.exists(): path.mkdir(mode=0o700)


def _safe_run_name(phase, index):
  if phase not in PHASES or type(index) is not int: _fail()
  maximum = WARMUPS if phase == "warmup" else COLD_RUNS if phase == "cold" else 1
  if index < 0 or index >= maximum: _fail()
  return f"{phase}-{index:02d}"


def _phase_expected_calls(phase):
  return SAME_SESSION_PROMPTS if phase == "same-session" else 1


def _existing_records(root):
  rows = []
  runs = root / "runs"
  runs_info = runs.lstat()
  if not stat.S_ISDIR(runs_info.st_mode) or runs_info.st_uid != os.geteuid() or stat.S_IMODE(runs_info.st_mode) != 0o700: _fail()
  for run_dir in sorted(runs.iterdir()):
    run_info = run_dir.lstat()
    if not stat.S_ISDIR(run_info.st_mode) or run_info.st_uid != os.geteuid() or stat.S_IMODE(run_info.st_mode) != 0o700 or run_dir.name not in {
      *[f"warmup-{index:02d}" for index in range(WARMUPS)], *[f"cold-{index:02d}" for index in range(COLD_RUNS)], "same-session-00"}:
      _fail()
    path = run_dir / "record.json"
    try: info = path.lstat()
    except FileNotFoundError: _fail()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 8 * 1024 * 1024: _fail()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
      opened = os.fstat(fd)
      if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size): _fail()
      raw = os.read(fd, 8 * 1024 * 1024 + 1)
      if len(raw) != info.st_size: _fail()
    finally:
      os.close(fd)
    row = _json(raw)
    if not isinstance(row, dict): _fail()
    if type(row.get("index")) is not int or row.get("status") not in ("observed", "failed", "timeout"): _fail()
    phase = row.get("phase")
    if _safe_run_name(phase, row["index"]) != run_dir.name: _fail()
    count = row.get("synthetic_request_count")
    if type(count) is not int or not 0 <= count <= _phase_expected_calls(phase): _fail()
    if row.get("status") == "timeout" and row.get("failure") != "per_sample_timeout": _fail()
    rows.append(row)
  return rows


def _event_name(value):
  if not isinstance(value, dict) or value.get("kind") != "event" or value.get("name") not in {
    "synthetic_request", "synthetic_response_first", "synthetic_response_last", "cli_ready", "idle_start",
    "idle_end", "prompt_write", "agent_end", "cli_exit", "rpc_eof", "task_end", "driver_done", "driver_failed",
  }: _fail()
  name = value["name"]
  fields = {
    "synthetic_request": {"call_index", "model"},
    "synthetic_response_first": {"call_index"},
    "synthetic_response_last": {"call_index"},
    "prompt_write": {"prompt_index"},
    "agent_end": {"prompt_index"},
    "cli_exit": {"exit_code", "signal"},
    "driver_done": {"exit_code", "requests"},
  }.get(name, set())
  if set(value) != {"kind", "name", "phase", "index", "driver_monotonic_ns", *fields}: _fail()
  if value.get("phase") not in PHASES or type(value.get("index")) is not int: _fail()
  if type(value.get("driver_monotonic_ns")) is not str or re.fullmatch(r"[0-9]{1,24}", value["driver_monotonic_ns"]) is None: _fail()
  for field in ("prompt_index", "call_index", "exit_code", "requests"):
    if field in value and type(value[field]) is not int: _fail()
  if "signal" in value and value["signal"] is not None and not isinstance(value["signal"], str): _fail()
  if "model" in value and value["model"] != "synthetic-main": _fail()
  return value


def run_sample(directory, phase, index):
  root = _private_dir(directory, create=False); plan = _read_plan(root / "plan.json")
  _verify_fixed_inputs(plan)
  name = _safe_run_name(phase, index); run_dir = root / "runs" / name
  expected_calls = _phase_expected_calls(phase)
  previous = _existing_records(root)
  if any(row.get("synthetic_request_count") is None or type(row.get("synthetic_request_count")) is not int for row in previous): _fail()
  observed_calls = sum(row["synthetic_request_count"] for row in previous)
  if observed_calls + expected_calls > plan["authorization"]["max_model_calls"]: _fail()
  run_dir.mkdir(mode=0o700)
  _create_work(run_dir)
  driver = run_dir / "driver.mjs"; _write_new(driver, _driver_source().encode(), 0o600)
  work = run_dir / "work"
  argv = build_invocation(plan, work, phase, index, driver)
  _write_new(run_dir / "invocation.json", _bytes({"argv": argv, "environment": "empty outer; fixed guest allowlist", "driver_sha256": _regular_digest(driver)}))
  process = None; outer_stderr = None; events = []; samples = []; stdout_bytes = 0; phase_by_event = "startup"; started_ns = time.monotonic_ns()
  observer = ProcObserver(node_path=plan["runtime"]["node_path"], bwrap_path=plan["runtime"]["bwrap_path"],
    node_guest_path=plan["runtime"]["node_guest_path"], cli_guest_path=plan["runtime"]["cli_guest_path"])
  deadline = time.monotonic() + plan["schedule"]["per_sample_timeout_seconds"]
  status = "failed"; failure = "not-completed"; driver_result = None
  try:
    _append_host_event(events, "spawn_requested", started_ns)
    outer_stderr = _open_new_private(run_dir / "outer.stderr")
    process = subprocess.Popen(argv, cwd=run_dir, env={}, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
      stderr=subprocess.PIPE, close_fds=True, shell=False, start_new_session=True)
    _append_host_event(events, "spawn_returned", time.monotonic_ns())
    with _open_new_private(run_dir / "events.jsonl") as event_stream:
      selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ, "stdout")
      selector.register(process.stderr, selectors.EVENT_READ, "stderr")
      buffer = b""; next_sample = time.monotonic_ns()
      while True:
        now = time.monotonic_ns()
        if now >= next_sample:
          if len(samples) >= MAX_SAMPLE_ROWS:
            failure = "process_sample_limit"; process.terminate(); break
          samples.append(_proc_sample(observer, process.pid, now - started_ns, phase_by_event, owned_process=process)); next_sample = now + SAMPLE_INTERVAL_NS
        if time.monotonic() >= deadline:
          failure = "per_sample_timeout"; process.terminate(); break
        for key, _ in selector.select(timeout=0.02):
          chunk = os.read(key.fileobj.fileno(), 65536)
          if not chunk:
            selector.unregister(key.fileobj); break
          if key.data == "stderr":
            outer_stderr_bytes = outer_stderr.tell() + len(chunk)
            if outer_stderr_bytes > MAX_OUTER_STDERR_BYTES:
              failure = "outer_stderr_limit"; process.terminate(); break
            outer_stderr.write(chunk); outer_stderr.flush()
            continue
          stdout_bytes += len(chunk)
          if stdout_bytes > MAX_EVENT_BYTES: failure = "event_output_limit"; process.terminate(); break
          buffer += chunk
          if len(buffer) > MAX_EVENT_LINE and b"\n" not in buffer: failure = "event_line_limit"; process.terminate(); break
          while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if not line or len(line) > MAX_EVENT_LINE: failure = "invalid_event_line"; process.terminate(); break
            event = _event_name(_json(line))
            if event.get("phase") != phase or event.get("index") != index: failure = "invalid_event_shape"; process.terminate(); break
            # Only fixed field names and numeric indexes are retained; prompt, headers and env values are not event fields.
            clean = {key: event.get(key) for key in ("kind", "name", "phase", "index", "prompt_index", "call_index", "model", "exit_code", "signal", "requests", "driver_monotonic_ns")}
            clean["host_monotonic_ns"] = time.monotonic_ns(); event_stream.write(_bytes(clean)); event_stream.flush()
            events.append(clean)
            if clean["name"] == "idle_start": phase_by_event = "idle"
            elif clean["name"] == "prompt_write": phase_by_event = "active"
            elif clean["name"] == "task_end": phase_by_event = "post-task"
            if clean["name"] == "driver_done": break
        if process.poll() is not None and not selector.get_map(): break
        if failure != "not-completed": break
        if events and events[-1]["name"] == "driver_done": break
      selector.close()
      if process.poll() is None:
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired:
          process.kill(); process.wait(timeout=2)
      outer_stderr.flush(); os.fsync(outer_stderr.fileno())
      if buffer: failure = "partial_event_line"
      event_stream.flush(); os.fsync(event_stream.fileno())
    outer_code = process.returncode
    try:
      raw_result = (work / "driver-result.json").read_bytes()
      if len(raw_result) > 256 * 1024: _fail()
      driver_result = _json(raw_result)
    except OSError:
      driver_result = None
    identity_ok = _identity_samples_complete(samples)
    driver_ok = _valid_driver_result(driver_result, phase, index, expected_calls)
    events_ok = _valid_event_sequence(events, phase, expected_calls, plan["schedule"])
    post_sample_ok = _post_window_sample_valid(events, samples, started_ns, plan["schedule"])
    if outer_code == 0 and driver_ok and identity_ok and events_ok and post_sample_ok and failure == "not-completed":
      status = "observed"; failure = None
    else:
      failure = failure if failure != "not-completed" else "process_identity_missing" if not identity_ok else "driver_result_invalid" if not driver_ok else "event_sequence_invalid" if not events_ok else "post_window_sample_missing"
    if driver_result is None: driver_result = {"phase": phase, "index": index, "failed": True, "synthetic_request_count": None}
    if type(driver_result.get("synthetic_request_count")) is not int or not 0 <= driver_result["synthetic_request_count"] <= expected_calls: observed_count = None
    else: observed_count = driver_result["synthetic_request_count"]
    metric_values = _derive_metrics(phase, events, samples, driver_result, status)
    record = {"phase": phase, "index": index, "status": status, "failure": failure,
      "outer_exit_code": outer_code, "outer_signal": -outer_code if isinstance(outer_code, int) and outer_code < 0 else None,
      "synthetic_request_count": observed_count, "paid_external_requests": 0, "paid_cost": "0",
      "identity_verified": identity_ok, "driver_result": driver_result, "events_sha256": _regular_digest(run_dir / "events.jsonl"),
      "metrics": metric_values, "process_sample_count": len(samples), "process_samples": samples}
    record_bytes = _bytes(record)
    if len(record_bytes) > 8 * 1024 * 1024: _fail()
    _write_new(run_dir / "record.json", record_bytes)
    return record
  except Exception:
    if process is not None and process.poll() is None:
      try: process.terminate(); process.wait(timeout=2)
      except Exception:
        try: process.kill(); process.wait(timeout=2)
        except Exception: pass
    if not (run_dir / "record.json").exists():
      record = {"phase": phase, "index": index, "status": "failed", "failure": "collector_failure",
        "synthetic_request_count": None, "paid_external_requests": 0, "paid_cost": "0", "identity_verified": False,
        "metrics": {}, "process_sample_count": len(samples), "process_samples": samples}
      try: _write_new(run_dir / "record.json", _bytes(record))
      except Exception: pass
    raise
  finally:
    if outer_stderr is not None:
      try:
        outer_stderr.flush(); os.fsync(outer_stderr.fileno())
      except OSError:
        pass
      outer_stderr.close()
    if hasattr(observer, "close"): observer.close()
    if process and process.stdout: process.stdout.close()
    if process and process.stderr: process.stderr.close()


def _append_host_event(events, name, timestamp_ns):
  events.append({"name": name, "host_monotonic_ns": timestamp_ns})


def _identity_samples_complete(samples):
  first = next((index for index, row in enumerate(samples) if row["identity_status"] == "verified" and row.get("target")), None)
  if first is None: return False
  # Before the inner SDK process is born, a short missing window is expected.
  # Once anchored, every later sample must preserve the same checked birth tuple.
  target = samples[first]["target"]
  return all(row["identity_status"] == "verified" and row.get("target") == target for row in samples[first:])


def _post_window_sample_valid(events, samples, started_ns, schedule):
  task_end = next((event["host_monotonic_ns"] for event in events if event["name"] == "task_end"), None)
  if task_end is None: return False
  window_end = task_end - started_ns + schedule["post_task_seconds_per_run"] * 1_000_000_000
  rows = [row for row in samples if row["phase"] == "post-task"]
  if not rows: return False
  last = rows[-1]
  return last["identity_status"] == "verified" and abs(last["host_monotonic_ns"] - window_end) <= 2 * SAMPLE_INTERVAL_NS


def _valid_driver_result(result, phase, index, expected_calls):
  expected_fields = {"phase", "index", "cli_exit_code", "cli_signal", "stdout_bytes", "stderr_bytes",
    "synthetic_request_count", "synthetic_requests", "assistant_sentinel_count", "rpc_tool_event_count", "prompt_latency_ms"}
  if not isinstance(result, dict) or set(result) != expected_fields: return False
  if result.get("phase") != phase or result.get("index") != index or result.get("cli_exit_code") != 0 or result.get("cli_signal") is not None: return False
  if type(result.get("stdout_bytes")) is not int or not 0 <= result["stdout_bytes"] <= MAX_EVENT_BYTES: return False
  if type(result.get("stderr_bytes")) is not int or not 0 <= result["stderr_bytes"] <= 256 * 1024: return False
  if type(result.get("synthetic_request_count")) is not int or result["synthetic_request_count"] != expected_calls: return False
  requests = result.get("synthetic_requests")
  if not isinstance(requests, list) or len(requests) != expected_calls: return False
  for row in requests:
    if not isinstance(row, dict) or set(row) != {"method", "path", "model", "stream", "message_count", "synthetic_auth_present"}: return False
    if row["method"] != "POST" or row["path"] != "/v1/chat/completions" or row["model"] != "synthetic-main" or row["stream"] is not True: return False
    if type(row["message_count"]) is not int or row["message_count"] < 1 or row["synthetic_auth_present"] is not True: return False
  if type(result.get("assistant_sentinel_count")) is not int or result["assistant_sentinel_count"] != expected_calls or type(result.get("rpc_tool_event_count")) is not int or result["rpc_tool_event_count"] != 0: return False
  latencies = result.get("prompt_latency_ms")
  return isinstance(latencies, list) and len(latencies) == expected_calls and all(type(value) in (int, float) and value > 0 for value in latencies)


def _valid_event_sequence(events, phase, expected_calls, schedule):
  by_name = {}
  driver_by_name = {}
  driver_times = []
  for event in events:
    name = event.get("name")
    if name in ("spawn_requested", "spawn_returned"):
      by_name.setdefault(name, []).append(event["host_monotonic_ns"])
      continue
    if not isinstance(name, str) or type(event.get("host_monotonic_ns")) is not int: return False
    if type(event.get("driver_monotonic_ns")) is not str or re.fullmatch(r"[0-9]{1,24}", event["driver_monotonic_ns"]) is None: return False
    driver_times.append(int(event["driver_monotonic_ns"]))
    by_name.setdefault(name, []).append(event["host_monotonic_ns"])
    driver_by_name.setdefault(name, []).append(int(event["driver_monotonic_ns"]))
  if not driver_times or any(right < left for left, right in zip(driver_times, driver_times[1:])): return False
  def one(name):
    rows = by_name.get(name, [])
    return rows[0] if len(rows) == 1 else None
  started = one("spawn_requested"); returned = one("spawn_returned"); ready = one("cli_ready")
  eof = one("rpc_eof"); task_end = one("task_end"); done = one("driver_done"); exit_time = one("cli_exit")
  if None in (started, returned, ready, eof, task_end, done, exit_time) or not started <= returned <= ready <= eof <= exit_time <= task_end <= done: return False
  driver_task_end = driver_by_name.get("task_end", [])
  driver_done = driver_by_name.get("driver_done", [])
  if (len(driver_task_end) != 1 or len(driver_done) != 1
      or driver_done[0] - driver_task_end[0] < schedule["post_task_seconds_per_run"] * 1_000_000_000): return False
  if len(by_name.get("driver_failed", [])) or len(by_name.get("driver_done", [])) != 1: return False
  if len(by_name.get("prompt_write", [])) != expected_calls or len(by_name.get("agent_end", [])) != expected_calls: return False
  prompt_indices = [event.get("prompt_index") for event in events if event.get("name") == "prompt_write"]
  end_indices = [event.get("prompt_index") for event in events if event.get("name") == "agent_end"]
  if prompt_indices != list(range(expected_calls)) or end_indices != list(range(expected_calls)): return False
  request_indices = [event.get("call_index") for event in events if event.get("name") == "synthetic_request"]
  first_indices = [event.get("call_index") for event in events if event.get("name") == "synthetic_response_first"]
  last_indices = [event.get("call_index") for event in events if event.get("name") == "synthetic_response_last"]
  if request_indices != list(range(1, expected_calls + 1)) or first_indices != request_indices or last_indices != request_indices: return False
  request_times = by_name["synthetic_request"]; first_times = by_name["synthetic_response_first"]; last_times = by_name["synthetic_response_last"]
  for prompt_time, request_time, first_time, last_time, end_time in zip(
      by_name["prompt_write"], request_times, first_times, last_times, by_name["agent_end"]):
    if not prompt_time <= request_time <= first_time <= last_time <= end_time: return False
  if len(by_name.get("synthetic_request", [])) != expected_calls or len(by_name.get("synthetic_response_first", [])) != expected_calls or len(by_name.get("synthetic_response_last", [])) != expected_calls: return False
  if any(not (ready <= start <= finish <= eof) for start, finish in zip(by_name["prompt_write"], by_name["agent_end"])): return False
  if phase == "same-session":
    if by_name.get("idle_start") or by_name.get("idle_end"): return False
  else:
    idle_start = one("idle_start"); idle_end = one("idle_end")
    if idle_start is None or idle_end is None or not ready <= idle_start: return False
    if not idle_start <= idle_end <= by_name["prompt_write"][0]: return False
    driver_idle_start = int(next(event["driver_monotonic_ns"] for event in events if event["name"] == "idle_start"))
    driver_idle_end = int(next(event["driver_monotonic_ns"] for event in events if event["name"] == "idle_end"))
    if driver_idle_end - driver_idle_start < schedule["idle_seconds_per_run"] * 1_000_000_000: return False
  cli_exit_events = [event for event in events if event.get("name") == "cli_exit"]
  done_events = [event for event in events if event.get("name") == "driver_done"]
  return len(cli_exit_events) == 1 and cli_exit_events[0].get("exit_code") == 0 and cli_exit_events[0].get("signal") is None \
    and len(done_events) == 1 and done_events[0].get("exit_code") == 0 and done_events[0].get("requests") == expected_calls


def _derive_metrics(phase, events, samples, result, status):
  timestamps = {name: [event["host_monotonic_ns"] for event in events if event["name"] == name] for name in
    ("spawn_requested", "cli_ready", "prompt_write", "synthetic_request", "synthetic_response_first", "synthetic_response_last", "agent_end", "task_end")}
  def delta(a, b):
    return (timestamps[b][0] - timestamps[a][0]) / 1e6 if timestamps.get(a) and timestamps.get(b) and timestamps[b][0] >= timestamps[a][0] else None
  verified = [item for item in samples if item["identity_status"] == "verified"]
  idle = [item for item in verified if item["phase"] == "idle"]
  post = [item for item in verified if item["phase"] == "post-task"]
  first = delta("prompt_write", "agent_end") if phase != "same-session" else None
  def cpu_delta(window):
    if len(window) < 2 or any(row["identity_status"] != "verified" for row in window): return None
    total = 0
    for before, after in zip(window, window[1:]):
      old = {(item["pid"], item["starttime"], item["pidns_inode"]): item for item in before["processes"]}
      new = {(item["pid"], item["starttime"], item["pidns_inode"]): item for item in after["processes"]}
      for identity in old.keys() & new.keys():
        prior = old[identity]["utime"] + old[identity]["stime"]
        current = new[identity]["utime"] + new[identity]["stime"]
        if current < prior: return None
        total += current - prior
    return total
  idle_window = [row for row in samples if row["phase"] == "idle"]
  post_window = [row for row in samples if row["phase"] == "post-task"]
  values = {"cli_ready_ms": delta("spawn_requested", "cli_ready"), "first_response_ms": first,
    "idle_rss_peak_bytes": max((item["rss_bytes"] for item in idle if item["rss_bytes"] is not None), default=None),
    "idle_cpu_ticks": cpu_delta(idle_window),
    "idle_fd_peak": max((item["fd_count"] for item in idle if item["fd_count"] is not None), default=None),
    "idle_descendant_peak": max((item["descendant_count"] for item in idle if item["descendant_count"] is not None), default=None),
    "post_task_live_descendants_30s": post[-1]["descendant_count"] if post else None,
    "post_task_rss_peak_bytes": max((item["rss_bytes"] for item in post if item["rss_bytes"] is not None), default=None),
    "post_task_cpu_ticks": cpu_delta(post_window)}
  if phase == "same-session":
    prompt_times = timestamps["prompt_write"]; end_times = timestamps["agent_end"]
    values["same_session_response_ms"] = [(end - start) / 1e6 for start, end in zip(prompt_times, end_times) if end >= start]
  return values


def build_baseline(directory):
  root = _private_dir(directory, create=False); plan = _read_plan(root / "plan.json")
  rows = _existing_records(root)
  baseline = summarize_samples(plan, rows)
  _write_new(root / "baseline.json", _bytes(baseline))
  return baseline


def main(argv=None):
  parser = argparse.ArgumentParser(prog="benchmark-pi-profiles", allow_abbrev=False)
  commands = parser.add_subparsers(dest="command", required=True)
  prep = commands.add_parser("prepare", allow_abbrev=False); prep.add_argument("--output-dir", required=True); prep.add_argument("--authorization-ref", required=True); prep.add_argument("--per-sample-timeout-seconds", type=int, required=True); prep.add_argument("--runtime-document", required=True)
  preflight = commands.add_parser("preflight", allow_abbrev=False); preflight.add_argument("--directory", required=True)
  run = commands.add_parser("run", allow_abbrev=False); run.add_argument("--directory", required=True); run.add_argument("--phase", choices=PHASES, required=True); run.add_argument("--index", type=int, required=True); run.add_argument("--authorized", action="store_true")
  summarize = commands.add_parser("summarize", allow_abbrev=False); summarize.add_argument("--directory", required=True)
  try:
    args = parser.parse_args(argv)
    if args.command == "prepare": result = prepare(args.output_dir, args.authorization_ref, args.per_sample_timeout_seconds, args.runtime_document)
    elif args.command == "preflight":
      root = _private_dir(args.directory, create=False); plan = _read_plan(root / "plan.json"); _verify_fixed_inputs(plan); result = {"status": "ready", "profile": plan["profile"], "native_started": False}
    elif args.command == "run":
      if not args.authorized: _fail()
      result = run_sample(args.directory, args.phase, args.index)
    else: result = build_baseline(args.directory)
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)); return 0
  except (ConfigError, OSError, ValueError, subprocess.SubprocessError):
    print("pi-benchmark: invalid plan or sample failed", file=sys.stderr); return 6


if __name__ == "__main__":
  raise SystemExit(main())

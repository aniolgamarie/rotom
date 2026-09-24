"""macOS 原生 helper 适配；没有 /proc 回退，停止只通过仍持有 child 的 helper。"""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .deployment import json_bytes
from .pi_catalog import validate
from .process import DependencyError, checked, environment
from .process_tracking import TrackedProcesses
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private


class MacProcesses(TrackedProcesses):
  def __init__(self, helper, record_root, *, helper_digest, runner=None, stop_client=None, platform=None, clock=None, pause=None):
    if (platform or sys.platform) != "darwin":
      raise DependencyError("macOS监督需要本机libproc helper；不模拟Linux进程接口")
    super().__init__(record_root)
    self.helper, self.helper_digest = Path(helper), helper_digest
    self.runner, self.stop_client = runner or checked, stop_client or self._stop_client
    self.clock, self.pause = clock or time.monotonic, pause or time.sleep
    ensure_private(self.record_root)
    self._verify_helper()

  def _verify_helper(self):
    try:
      if self.helper.is_symlink() or not self.helper.is_file() or hashlib.sha256(self.helper.read_bytes()).hexdigest() != self.helper_digest:
        raise ValueError()
    except (OSError, ValueError):
      raise DependencyError("macOS helper 缺失或身份不匹配运行包") from None

  def _query(self, *arguments):
    self._verify_helper()
    home = self.record_root / "helper-home"
    ensure_private(home)
    raw = self.runner([str(self.helper), *arguments], cwd=self.record_root, env=environment(home=home))
    try:
      return json.loads(raw)
    except (ValueError, TypeError):
      raise Conflict("macOS helper 返回不可验证的数据") from None

  def identity(self, pid):
    value = self._query("inspect", str(pid))
    if value == {"status": "absent"}:
      raise ProcessLookupError()
    try:
      validate("process-identity", value)
      if value["platform"] != "darwin" or value["namespace"] is not None or value["pid"] != pid:
        raise ValueError()
    except (ConfigError, ValueError, KeyError):
      raise Conflict("macOS进程身份未知") from None
    return value

  def observe(self, expected):
    try:
      actual = self.identity(expected["pid"])
      return "alive" if all(actual[key] == expected[key] for key in expected if key != "ppid") else "unknown"
    except ProcessLookupError:
      return "dead"
    except (Conflict, DependencyError, OSError):
      return "unknown"

  def _scan(self):
    values = self._query("list")
    if not isinstance(values, list):
      raise Conflict("macOS进程清点结果未知")
    result = {}
    for value in values:
      validate("process-identity", value)
      if value["platform"] != "darwin" or str(value["pid"]) in result:
        raise Conflict("macOS进程清点身份冲突")
      result[str(value["pid"])] = value
    return result

  def bind_control(self, expected, *, helper_identity, control_path, nonce):
    validate("process-identity", helper_identity)
    path = Path(control_path)
    if (not path.is_absolute() or not path.is_relative_to(self.record_root) or ".." in path.parts
        or not re.fullmatch(r"[0-9a-f]{64}", nonce) or self.observe(helper_identity) != "alive"
        or helper_identity["pid"] == expected["pid"] or expected["ppid"] != helper_identity["pid"]
        or helper_identity["platform"] != "darwin" or helper_identity["uid"] != expected["uid"]):
      raise Conflict("macOS控制通道未绑定可信helper身份")
    value = {"schema_version": 1, "worker": expected, "helper": helper_identity, "control_path": str(path), "nonce": nonce}
    with Tree(self.record_root) as tree:
      name = "control-" + self._path(expected)
      before = tree.read(name)
      if before is not None and before[0] != json_bytes(value):
        raise Conflict("macOS控制身份不能被覆盖")
      tree.write_state(name, json_bytes(value))

  def _control(self, expected):
    with Tree(self.record_root) as tree:
      raw = tree.read("control-" + self._path(expected))
    if raw is None or raw[1] != 0o600:
      raise Conflict("macOS缺少原始helper控制证明")
    try:
      value = json.loads(raw[0])
      if (set(value) != {"schema_version", "worker", "helper", "control_path", "nonce"} or value["schema_version"] != 1
          or value["worker"] != expected or not re.fullmatch(r"[0-9a-f]{64}", value["nonce"])
          or not Path(value["control_path"]).is_relative_to(self.record_root) or ".." in Path(value["control_path"]).parts
          or value["helper"]["pid"] != expected["ppid"] or value["helper"]["uid"] != expected["uid"]):
        raise ValueError()
      validate("process-identity", value["helper"])
    except (ValueError, TypeError, KeyError, ConfigError):
      raise Conflict("macOS helper 控制记录损坏") from None
    return value

  def _receipt(self, expected):
    control = self._control(expected)
    relative = Path(control["control_path"]).relative_to(self.record_root).as_posix() + ".receipt.json"
    with Tree(self.record_root) as tree:
      raw = tree.read(relative)
    if raw is None or raw[1] != 0o600:
      return None
    try:
      value = json.loads(raw[0])
      if (set(value) != {"schema_version", "nonce", "state", "exit_code", "grant_generation", "worker"}
          or value["schema_version"] != 1 or value["nonce"] != control["nonce"] or value["worker"] != expected
          or value["state"] not in ("running", "terminated", "unknown") or type(value["exit_code"]) is not int
          or type(value["grant_generation"]) is not int or value["grant_generation"] < 1):
        raise ValueError()
    except (ValueError, KeyError, TypeError):
      raise Conflict("macOS终止记录不匹配本次nonce及进程") from None
    return value

  def termination_status(self, expected):
    try:
      self._record(expected)
      receipt = self._receipt(expected)
      # helper 的 nonce/出生身份清点证明涵盖完整后代；不把后来复用的 PID 当旧执行。
      if receipt is not None and receipt["state"] == "terminated":
        return "terminated"
      tracked = super().termination_status(expected)
      if receipt is not None and receipt["state"] == "unknown":
        return "unknown"
      return "unknown" if tracked in ("unknown", "terminated") else "active"
    except (Conflict, DependencyError, OSError):
      return "unknown"

  def _stop_client(self, control, generation, *, force=False):
    self._verify_helper()
    read_fd, write_fd = os.pipe()
    try:
      os.write(write_fd, (control["nonce"] + "\n").encode())
      os.close(write_fd)
      write_fd = None
      result = subprocess.run([str(self.helper), "kill-control" if force else "stop-control", control["control_path"], str(read_fd), str(generation)],
        cwd=self.record_root, env=environment(home=self.record_root / "helper-home"), pass_fds=(read_fd,), capture_output=True, text=True)
      if result.returncode or result.stdout.strip() != "accepted":
        raise Conflict("macOS helper 未接受本次停止授权")
    finally:
      os.close(read_fd)
      if write_fd is not None:
        os.close(write_fd)

  def send_signal(self, expected, number):
    # macOS契约：不对裸PID发信号；停止只经仍持有child的helper stop/kill-control并留下收据。
    raise Conflict("macOS停止必须通过helper控制通道")

  def stop(self, expected, *, grant_generation, grace_seconds=5, force=False):
    if type(force) is not bool: raise Conflict("停止模式无效")
    if type(grant_generation) is not int or grant_generation < 2:
      raise Conflict("macOS停止缺少已撤销的新generation")
    record = self._refresh(expected)
    control = self._control(expected)
    receipt = self._receipt(expected)
    if self.observe(control["helper"]) != "alive":
      raise Conflict("macOS helper 或执行包含关系未知；不对裸PID发信号")
    self.stop_client(control, grant_generation, **({"force": True} if force else {}))
    deadline = self.clock() + grace_seconds
    while self.clock() < deadline:
      if self.termination_status(expected) == "terminated":
        return
      self.pause(min(0.05, max(0, deadline - self.clock())))
    raise Conflict("macOS停止尚无完整终止证明")

  def external_status(self, identifier):
    return "unknown"

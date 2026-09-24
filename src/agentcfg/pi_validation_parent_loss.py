"""Linux 原生负向探测：只通过已核验 pidfd 中断本夹具的父宿主。"""
import json
from pathlib import Path
import signal
import sys

from .pi_host import HostSupervisor
from .deployment import json_bytes
from .storage import Conflict, Tree


class OrdinaryCancelSupervisor(HostSupervisor):
  """仅在夹具模型实际收到请求后通知 SDK 驱动执行取消。"""
  def __init__(self, config, *, lease_fd, readiness, nonce, model_started):
    super().__init__(config, lease_fd=lease_fd)
    self.readiness = Path(readiness)
    self.native_nonce = nonce
    self.model_started = model_started
    self.notified = False

  def poll(self):
    super().poll()
    if self.notified or not self.model_started(): return
    with Tree(self.readiness.parent) as tree:
      tree.write_new(self.readiness.name, json_bytes({"nonce": self.native_nonce, "runtime_identity": self.runtime_root.name}))
    self.notified = True


class ParentLossSupervisor(HostSupervisor):
  def __init__(self, config, *, lease_fd, readiness, nonce, model_started, kill_platform=None):
    super().__init__(config, lease_fd=lease_fd)
    self.readiness = Path(readiness)
    self.native_nonce = nonce
    self.model_started = model_started
    self.parent_loss_workers = []
    self.parent_loss_facts = None
    # darwin经helper kill-control中断宿主；linux保持pidfd身份信号。仅测试可注入。
    self.kill_platform = kill_platform or sys.platform

  def terminate_parent_host(self, lease_id):
    """模拟父宿主突然死亡：darwin撤权后经持有的helper控制通道强停；linux用pidfd身份信号。"""
    if self.kill_platform == "darwin":
      lease = self.store.request_cancel(lease_id, self.store.owner)
      self.processes.stop(lease["process_identity"], grant_generation=lease["grant_generation"], force=True)
      return
    host = self.store.read(lease_id)
    self.processes.send_signal(host["process_identity"], signal.SIGKILL)

  def poll(self):
    super().poll()
    if self.parent_loss_workers or self.host_exit is not None: return
    with Tree(self.readiness.parent) as tree: raw = tree.read(self.readiness.name, max_bytes=1024 * 1024)
    if raw is None: return
    ready = json.loads(raw[0])
    if (raw[1] != 0o600 or not isinstance(ready, dict) or set(ready) != {"nonce", "runtime_identity", "facts"}
        or ready["nonce"] != self.native_nonce or ready["runtime_identity"] != self.runtime_root.name
        or not isinstance(ready["facts"], dict) or ready["facts"].get("sdk_session") is not True):
      raise Conflict("PI_NATIVE_PARENT_LOSS_READINESS")
    kind = ready["facts"].get("child_execution_kind", "worker")
    if kind not in ("worker", "external"): raise Conflict("PI_NATIVE_PARENT_LOSS_CHILD_KIND")
    workers = [row for row in self.store.records() if row["kind"] == kind and row["state"] == "running"
      and row["process_identity"] is not None and self.processes.observe(row["process_identity"]) == "alive"]
    if not workers: return
    if not self.model_started(): return
    host = self.store.read(self.host_lease_id)
    child = self.children.get(self.host_lease_id)
    if not child or host["state"] != "running" or child["identity"] != host["process_identity"]: return
    # 使用现有 Linux pidfd 身份复核；不向任意 PID/PGID 发信号，也不直接停止 worker。
    self.terminate_parent_host(self.host_lease_id)
    self.parent_loss_workers = [row["lease_id"] for row in workers]
    self.parent_loss_facts = ready["facts"]

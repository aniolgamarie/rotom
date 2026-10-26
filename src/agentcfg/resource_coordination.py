"""新运行包的协调域原型；持久引用不是进程退出、完整历史覆盖或维护许可。"""

from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import re
import stat
import uuid

from . import storage
from .paths import PathError, _absolute_directory, safe_id
from .resource_keys import resource_key
from .resource_protocol import TERMINAL_INTENT_PHASES, decode, encode
from .storage import Conflict, Tree, advisory_lock, identity


_STATE = "coordination.json"
_LIMIT = 2 * 1024 * 1024
_ERROR = "共享资源协调状态不能确认；保留阻塞并重新核验"
_CLAIMS = "runtime-claims"


@contextmanager
def _boundary():
  try:
    yield
  except (OSError, PathError, ValueError, TypeError, KeyError, Conflict):
    raise Conflict(_ERROR) from None


def _physical(fd):
  info = os.fstat(fd)
  return {"device": info.st_dev, "inode": info.st_ino}


def _absent(tree, relative, *, create=False):
  # 首次采用只看存在性；绝不为判定存在而读取已有租约或原生内容。
  try:
    with tree.parent(relative, create=create) as (parent, name):
      os.stat(name, dir_fd=parent, follow_symlinks=False)
  except FileNotFoundError:
    return
  raise Conflict(_ERROR)


def runtime_claim_exists(cache, runtime_identity):
  """只查声明存在性；损坏声明也阻止旧格式降级，不读取其正文或创建路径。"""
  with _boundary():
    safe_id(runtime_identity)
    with Tree(Path(cache)) as cache_tree:
      if cache_tree.fd is None:
        return False
      with Tree(cache_tree.root / _CLAIMS) as claims:
        if claims.fd is None:
          with cache_tree.parent(_CLAIMS):
            pass
          return False
        with claims.parent(runtime_identity + ".json") as (parent, name):
          try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
          except FileNotFoundError:
            exists = False
          else:
            exists = True
        with cache_tree.parent(_CLAIMS) as (parent, name):
          current = os.stat(name, dir_fd=parent, follow_symlinks=False)
          if (current.st_dev, current.st_ino) != (os.fstat(claims.fd).st_dev, os.fstat(claims.fd).st_ino):
            raise Conflict(_ERROR)
        return exists


def _read_runtime_claim(cache, runtime_identity):
  with Tree(Path(cache) / _CLAIMS) as claims:
    value = claims.read(runtime_identity + ".json", max_bytes=_LIMIT)
    if value is None or value[1] != 0o600:
      raise Conflict(_ERROR)
    return decode(value[0], kind="runtime-anchor")


def _publish_runtime_claim(cache_tree, runtime_identity, anchor):
  # 先持久化独立声明，再暴露 final 租约。声明失败或响应丢失均不自动清理。
  with Tree(cache_tree.root / _CLAIMS, create=True) as claims:
    claims.write_new(runtime_identity + ".json", encode(anchor))
    with cache_tree.parent(_CLAIMS) as (parent, name):
      current = os.stat(name, dir_fd=parent, follow_symlinks=False)
      if (current.st_dev, current.st_ino) != (os.fstat(claims.fd).st_dev, os.fstat(claims.fd).st_ino):
        raise Conflict(_ERROR)
    os.fsync(cache_tree.fd)
    # cache 本身也可能本次才创建；逐级同步目录项，不假定 ensure_private 已持久化父目录。
    ancestor = cache_tree.root.parent
    while True:
      with _absolute_directory(ancestor) as parent:
        os.fsync(parent)
      if ancestor == ancestor.parent:
        break
      ancestor = ancestor.parent
    # 同步期间目录或声明可能被替换；固定的 Tree 会重核命名目录，再核对当前声明。
    current = claims.read(runtime_identity + ".json", max_bytes=_LIMIT)
    if current is None or current[1] != 0o600 or decode(current[0], kind="runtime-anchor") != anchor:
      raise Conflict(_ERROR)
    with cache_tree.parent(_CLAIMS):
      pass


def read_runtime_anchor(fd):
  """只读调用方已锁定的租约 fd；空旧格式不提供任何协调覆盖证明。"""
  with _boundary():
    before = os.fstat(fd)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
        or before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size > _LIMIT):
      raise Conflict(_ERROR)
    raw = os.pread(fd, _LIMIT + 1, 0)
    if identity(before) != identity(os.fstat(fd)) or len(raw) != before.st_size:
      raise Conflict(_ERROR)
    return decode(raw, kind="runtime-anchor") if raw else None


class Domain:
  """根路径由可信配置提供；不采用锚点里的路径，不自动初始化或修复。"""

  def __init__(self, root):
    self.root = Path(root)

  @contextmanager
  def _transaction(self, *, write=False):
    # 短锁中只读写本域元数据；绝不等待物理锁、宿主、网络或用户输入。
    with _boundary(), Tree(self.root) as tree:
      if tree.fd is None:
        raise Conflict(_ERROR)
      with advisory_lock(tree.fd, shared=not write):
        before = tree.read(_STATE, max_bytes=_LIMIT)
        if before is None or before[1] != 0o600:
          raise Conflict(_ERROR)
        state = decode(before[0], kind="domain")
        if state["physical"] != _physical(tree.fd):
          raise Conflict(_ERROR)
        yield state
        if write:
          state["revision"] += 1
          encoded = encode(state)
          tree.replace(_STATE, encoded, expected=before[2])
          # 也覆盖重新打开初始化响应不明的域；旧路径存在不证明祖先项已落盘。
          storage.sync_directory_ancestors(self.root.parent)
          saved = tree.read(_STATE, max_bytes=_LIMIT)
          if saved is None or saved[1] != 0o600 or saved[0] != encoded:
            raise Conflict(_ERROR)
        else:
          # parent() 再核验命名根，不能只信首次固定的旧目录 fd。
          with tree.parent(_STATE):
            pass

  def snapshot(self):
    with self._transaction() as state:
      return state

  def _runtime(self, state, cache, runtime_identity, fd):
    path = Path(cache) / "leases" / (runtime_identity + ".lock")
    key = resource_key("runtime", path, lease_fd=fd).as_dict()
    anchor = read_runtime_anchor(fd)
    if (anchor is None or anchor["resource_key"] != key
        or anchor["domain_id"] != state["domain_id"]
        or anchor["domain_physical"] != state["physical"]):
      raise Conflict(_ERROR)
    record = state["resources"].get(anchor["resource_id"])
    if (record is None or record["status"] != "ready" or record["key"] != key
        or record["cache"] != str(cache) or record["runtime_identity"] != runtime_identity):
      raise Conflict(_ERROR)
    if _read_runtime_claim(cache, runtime_identity) != anchor:
      raise Conflict(_ERROR)
    if resource_key("runtime", path, lease_fd=fd).as_dict() != key:
      raise Conflict(_ERROR)
    return record["resource_id"]

  def check_runtime(self, cache, runtime_identity, *, lease_fd, idle=False):
    """调用方须持续持有物理租约；此检查不创建维护许可，也不授予启动权限。"""
    with self._transaction() as state:
      rid = self._runtime(state, cache, runtime_identity, lease_fd)
      if idle:
        self._idle(state, {rid})
      return rid

  @staticmethod
  def _idle(state, resources):
    for table in ("reservations", "intents"):
      terminal = ("cancelled", "released") if table == "reservations" else TERMINAL_INTENT_PHASES
      if any(resources.intersection(entry["resources"]) and entry["phase"] not in terminal
          for entry in state[table].values()):
        raise Conflict(_ERROR)

  @staticmethod
  def _resources(state, resources):
    if (type(resources) is not list or not resources
        or any(type(rid) is not str for rid in resources)
        or len(set(resources)) != len(resources)
        or any(rid not in state["resources"] or state["resources"][rid]["status"] != "ready"
          for rid in resources)):
      raise Conflict(_ERROR)
    return set(resources)

  @staticmethod
  def _unfenced(state, resources):
    if any(entry["phase"] not in TERMINAL_INTENT_PHASES and resources.intersection(entry["resources"])
        for entry in state["intents"].values()):
      raise Conflict(_ERROR)

  def reserve(self, *, run_id, op_id, owner_ref, resources, expected_revision=None):
    with self._transaction(write=True) as state:
      if expected_revision is not None and (type(expected_revision) is not int or expected_revision != state["revision"]):
        raise Conflict(_ERROR)
      selected = self._resources(state, resources)
      self._unfenced(state, selected)
      if run_id in state["reservations"] or any(entry["op_id"] == op_id
          for entry in state["reservations"].values()):
        raise Conflict(_ERROR)
      state["reservations"][run_id] = {"run_id": run_id, "op_id": op_id,
        "owner_ref": deepcopy(owner_ref), "resources": sorted(resources), "phase": "reserved",
        "generation": state["revision"] + 1}
      receipt = deepcopy(state["reservations"][run_id])
    # 只有原子写入及 fsync 返回后才交回；响应丢失不得凭空重发同一运行。
    return receipt

  def dispatch(self, run_id, *, lease_fds):
    """调用方先取得全部物理 SH；先持久化可能派发，再由未来合作启动器执行。"""
    with self._transaction(write=True) as state:
      entry = state["reservations"][run_id]
      selected = self._resources(state, entry["resources"])
      if entry["phase"] != "reserved" or set(lease_fds) != selected:
        raise Conflict(_ERROR)
      self._unfenced(state, selected)
      for rid, fd in lease_fds.items():
        resource = state["resources"][rid]
        if self._runtime(state, resource["cache"], resource["runtime_identity"], fd) != rid:
          raise Conflict(_ERROR)
      entry["phase"] = "dispatched"

  def cancel_reserved(self, run_id):
    self._transition("reservations", run_id, {"reserved"}, "cancelled")

  def mark_unknown(self, run_id):
    self._transition("reservations", run_id,
      {"reserved", "owner_pending", "owner_attached", "dispatched", "release_pending", "unknown"}, "unknown")

  def _transition(self, table, key, allowed, phase):
    with self._transaction(write=True) as state:
      entry = state[table][key]
      if entry["phase"] not in allowed:
        raise Conflict(_ERROR)
      if table == "intents" and "progress" in entry:
        from . import maintenance
        from .maintenance_store import _read
        with Tree(self.root) as tree:
          if tree.fd is None or _physical(tree.fd) != state["physical"]:
            raise Conflict(_ERROR)
          _read(state, tree, key)
        progress = entry["progress"]
        if phase == "cancelled" and progress != maintenance._initial_batch(key, progress["plan"]):
          raise Conflict(_ERROR)
        if phase == "unknown":
          progress.update(revision=progress["revision"] + 1, phase="unknown", review_required=True)
      entry["phase"] = phase

  @staticmethod
  def _intent_selection(state, resources, selected_runs, operation):
    active = {run: entry for run, entry in state["reservations"].items()
      if entry["phase"] not in ("cancelled", "released") and resources.intersection(entry["resources"])}
    selected = set(selected_runs)
    # 仅停止可保留已知的未选运行；共享包维护仍须覆盖全部引用。未知覆盖两者均拒绝。
    if (operation not in ("setup", "stop_only")
        or any(entry["phase"] != "dispatched" for entry in active.values())
        or (operation == "setup" and selected != set(active))
        or (operation == "stop_only" and (not selected.issubset(active) or (active and not selected)))):
      raise Conflict(_ERROR)
    # 已选运行须覆盖其完整资源闭包；不得遗漏 HOME/包，也不额外冻结未选实例。
    if selected and resources != set().union(*(set(active[run]["resources"]) for run in selected)):
      raise Conflict(_ERROR)

  def accept_intent(self, *, batch_id, generation, operation, expected_revision,
      resources, selected_runs):
    with self._transaction(write=True) as state:
      selected = self._resources(state, resources)
      self._unfenced(state, selected)
      if (type(expected_revision) is not int or state["revision"] != expected_revision
          or batch_id in state["intents"] or type(selected_runs) is not list
          or any(type(run) is not str for run in selected_runs)
          or len(set(selected_runs)) != len(selected_runs)):
        raise Conflict(_ERROR)
      self._intent_selection(state, selected, selected_runs, operation)
      state["intents"][batch_id] = {"batch_id": batch_id, "generation": generation,
        "operation": operation, "resources": sorted(resources), "selected_runs": sorted(selected_runs), "phase": "active"}

  def dispatch_intent(self, batch_id):
    """记录控制动作可能派发；不执行停止，也不授予后续 setup 副作用许可。"""
    with self._transaction(write=True) as state:
      intent = state["intents"][batch_id]
      selected = self._resources(state, intent["resources"])
      if intent["phase"] != "active":
        raise Conflict(_ERROR)
      from .maintenance_store import check_stop_snapshot_for_dispatch
      check_stop_snapshot_for_dispatch(self, state, intent)
      self._intent_selection(state, selected, intent["selected_runs"], intent["operation"])
      intent["phase"] = "dispatched"

  def mark_intent_unknown(self, batch_id):
    self._transition("intents", batch_id, {"active", "dispatched", "unknown"}, "unknown")

  def cancel_intent(self, batch_id):
    self._transition("intents", batch_id, {"active"}, "cancelled")


def initialize_domain(root):
  """显式内部操作；普通 sync 不调用。已有域只核验，非空未知目录绝不采用。"""
  root = Path(root)
  with _boundary(), Tree(root, create=True) as tree, advisory_lock(tree.fd):
    existing = tree.read(_STATE, max_bytes=_LIMIT)
    if existing is not None:
      state = decode(existing[0], kind="domain")
      if existing[1] != 0o600 or state["physical"] != _physical(tree.fd):
        raise Conflict(_ERROR)
      os.fsync(tree.fd)
    else:
      if os.listdir(tree.fd):
        raise Conflict(_ERROR)
      state = {"schema_version": 1, "kind": "domain", "domain_id": uuid.uuid4().hex,
        "physical": _physical(tree.fd), "revision": 0,
        "resources": {}, "reservations": {}, "intents": {}}
      tree.write_new(_STATE, encode(state))
    # 首次发布和已有域重核都确认祖先目录项；同步失败不返回可用域，也不删旧事实。
    storage.sync_directory_ancestors(root.parent)
    saved = tree.read(_STATE, max_bytes=_LIMIT)
    expected = existing[0] if existing is not None else encode(state)
    if saved is None or saved[1] != 0o600 or saved[0] != expected:
      raise Conflict(_ERROR)
  return Domain(root)


def enroll_runtime(domain, cache, runtime_identity):
  """仅新资源：先保存独立声明，再发布非空锚点与登记；已有资源不自动采用。"""
  cache = Path(cache)
  with _boundary():
    safe_id(runtime_identity)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,191}", runtime_identity) is None:
      raise Conflict(_ERROR)
    state = domain.snapshot()
    with Tree(cache, create=True) as cache_tree:
      if runtime_claim_exists(cache, runtime_identity):
        raise Conflict(_ERROR)
      _absent(cache_tree, "leases/" + runtime_identity + ".lock")
      _absent(cache_tree, "runtimes/" + runtime_identity, create=True)
      with Tree(cache / "leases", create=True) as tree:
        temporary = ".rotom-enroll-" + uuid.uuid4().hex
        target = runtime_identity + ".lock"
        with tree.parent(target) as (parent, name):
          fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=parent)
          try:
            with advisory_lock(fd, unlock=False):
              key = resource_key("runtime", tree.root / temporary, lease_fd=fd).as_dict()
              rid = uuid.uuid4().hex
              anchor = {"schema_version": 1, "kind": "runtime-anchor", "protocol": "rotom-resource-v1",
                "domain_id": state["domain_id"], "domain_physical": state["physical"],
                "resource_id": rid, "resource_key": key}
              raw = memoryview(encode(anchor))
              while raw:
                written = os.write(fd, raw)
                if written <= 0:
                  raise Conflict(_ERROR)
                raw = raw[written:]
              os.fsync(fd)
              _publish_runtime_claim(cache_tree, runtime_identity, anchor)
              # 不替换锁 inode；no-overwrite 发布仲裁两域并发，永不暴露空的 final 文件。
              with tree.parent(target):
                os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
              os.unlink(temporary, dir_fd=parent)
              temporary = None
              os.fsync(parent)
              if resource_key("runtime", tree.root / target, lease_fd=fd).as_dict() != key:
                raise Conflict(_ERROR)
              with domain._transaction(write=True) as latest:
                if latest["domain_id"] != state["domain_id"] or latest["physical"] != state["physical"]:
                  raise Conflict(_ERROR)
                if rid in latest["resources"] or any(entry["key"] == key or (entry.get("cache") == str(cache)
                    and entry.get("runtime_identity") == runtime_identity) for entry in latest["resources"].values()):
                  raise Conflict(_ERROR)
                _absent(cache_tree, "runtimes/" + runtime_identity)
                if resource_key("runtime", tree.root / target, lease_fd=fd).as_dict() != key:
                  raise Conflict(_ERROR)
                if _read_runtime_claim(cache, runtime_identity) != anchor:
                  raise Conflict(_ERROR)
                latest["resources"][rid] = {"resource_id": rid, "key": key, "cache": str(cache),
                  "runtime_identity": runtime_identity, "status": "ready"}
              return anchor
          finally:
            os.close(fd)
            # 已发布的 final 永不清理。进程崩溃留下双链接时也不自动恢复。
            if temporary is not None:
              os.unlink(temporary, dir_fd=parent)
              os.fsync(parent)

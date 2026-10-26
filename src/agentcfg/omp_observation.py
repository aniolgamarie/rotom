"""OMP 只读 scope/owner 元数据观察；不证明当前运行包可用或授予控制权限。"""
from contextlib import contextmanager, ExitStack
import os

from .lifecycle import _omp_launch_context, _omp_path
from .omp_lifecycle import _same_file
from .paths import safe_id
from .resource_coordination import Domain
from .resource_scopes import _verify
from .run_owners import Registry, record_state
from .storage import Conflict, Tree, advisory_lock


_ERROR = "OMP实例观察归属或协调记录不能确认；保留未知状态"


def _domain(workspace):
  if hasattr(workspace, "resolved"):
    root, _, _ = _omp_launch_context(workspace)
  else:
    # 根由轻量工作区从同一次严格配置读取传入；不从声明/owner 推导路径。
    root = _omp_path(workspace.global_state_root) / "lifecycle"
    profile = safe_id(workspace.profile)
    if (workspace.agent != "omp" or profile != workspace.binding["profile"]
        or _omp_path(workspace.state_root) != root.parent / "omp" / profile):
      raise Conflict(_ERROR)
    _omp_path(workspace.instance)
    _omp_path(workspace.cache)
  return Domain(root)


@contextmanager
def guard(workspace, *, shared=True):
  """只打开现存实例锁；EX 仅用于观察可取得性，不核实退出或清除 unknown。"""
  with ExitStack() as stack:
    try:
      domain = _domain(workspace)
      tree = stack.enter_context(Tree(workspace.instance))
      if tree.fd is None:
        raise ValueError()
      name = ".agentcfg-omp.lock"
      with tree.parent(name) as (parent, leaf):
        fd = os.open(leaf, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
      stack.callback(os.close, fd)
      _same_file(tree, name, fd)
      stack.enter_context(advisory_lock(fd, shared=shared, unlock=False))
      home = stack.enter_context(Tree(workspace.instance / "user-home"))
      if home.fd is None:
        raise ValueError()
      with domain._transaction() as state:
        _verify(state, workspace, instance_fd=fd, native_home_fd=home.fd)
    except Exception:
      raise Conflict(_ERROR) from None
    yield fd


def _record_link(state, entry, workspace, registry, tree, record, scope, instance_fd, home_fd):
  from . import resource_owners as owners
  resources = set(entry["resources"])
  runtimes = resources - scope
  if (len(runtimes) != 1 or resources != scope | runtimes
      or entry["owner_ref"] != {"state_root": str(workspace.state_root), "binding": workspace.binding}):
    raise Conflict(_ERROR)
  resource = state["resources"].get(next(iter(runtimes)))
  if (resource is None or resource["status"] != "ready" or resource["key"]["kind"] != "runtime"
      or resource["cache"] != str(workspace.cache)):
    raise Conflict(_ERROR)
  evidence = owners._evidence(workspace, tree, instance_fd=instance_fd, native_home_fd=home_fd)
  link = entry.get("owner_link")
  if (link is None or evidence != {key: value for key, value in link.items() if key != "record_digest"}
      or record["agent"] != "omp" or record["backend"] != "managed"
      or record["native_home_ref"]["path"] != evidence["native_home"]["path"]
      or record["deployed_identity"]["runtime"] != owners._runtime_digest(state, entry)
      or record["coordination_domain"] != owners._coordination(state, entry, evidence)):
    raise Conflict(_ERROR)
  digest = link["record_digest"]
  if record_state(record) == "idle_confirmed" and entry["phase"] in ("release_pending", "released"):
    digest = entry["release_receipt"]["owner_record_digest"]
  if owners._digest(record) != digest:
    raise Conflict(_ERROR)
  registry._verify_root(tree)


def snapshot(workspace, *, instance_fd):
  """在物理租约内读双向元数据；不取包锁，不把历史字段当作包的现场核验。"""
  try:
    domain = _domain(workspace)
    with Tree(workspace.instance / "user-home") as home, domain._transaction() as state:
      if home.fd is None:
        raise ValueError()
      scope = _verify(state, workspace, instance_fd=instance_fd, native_home_fd=home.fd)
      selected = {run: entry for run, entry in state["reservations"].items()
        if scope.intersection(entry["resources"])}
      registry = Registry(workspace.state_root / "run-owners", workspace.binding)
      with registry._locked(nonblocking=True) as tree:
        records, _ = registry._records(tree)
        pending = False
        for run, record in records.items():
          if record.get("coordination_domain") is None:
            # 保留未关联的旧记录用于历史展示，但不能将其当作完整合作覆盖。
            pending = True
            continue
          entry = selected.get(run)
          if entry is None:
            raise ValueError()
          _record_link(state, entry, workspace, registry, tree, record, scope, instance_fd, home.fd)
        expected = {"dispatched": "active", "unknown": "unknown", "released": "idle_confirmed"}
        for run, entry in selected.items():
          if entry["phase"] == "cancelled" and run not in records:
            continue
          record = records.get(run)
          if (record is None or record.get("coordination_domain") is None
              or expected.get(entry["phase"]) != record_state(record)):
            pending = True
        if any(entry["phase"] != "cancelled" and scope.intersection(entry["resources"])
            for entry in state["intents"].values()):
          pending = True
        return records, pending
  except Exception:
    raise Conflict(_ERROR) from None

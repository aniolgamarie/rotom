"""OMP 生命周期适配接缝；不采用旧资源，不从记录路径寻找协调域。"""
from contextlib import contextmanager, ExitStack
import sys

from . import omp_identity, omp_lifecycle, omp_setup, resource_coordination as coordination, resource_scopes as scopes, runtime
from .deployment import read_state
from .lifecycle import _omp_launch_context, omp_scope_write_guard
from .paths import safe_id
from .storage import Conflict, Tree


_ERROR = "OMP生命周期归属或已部署运行身份不能确认；保留保护并核验部署"


@contextmanager
def _admit(select):
  with ExitStack() as stack:
    try:
      admitted = stack.enter_context(select())
    except Conflict:
      raise
    except Exception:
      raise Conflict(_ERROR) from None
    # 仅脱敏准入异常；不把前台主体的异常或控制中断改写为 Conflict。
    yield admitted


def preflight(workspace):
  try:
    if scopes.scope_claim_exists(workspace.instance):
      with omp_scope_write_guard(workspace):
        pass
    else:
      omp_identity.preflight_setup(workspace)
  except Conflict:
    raise
  except Exception:
    raise Conflict(_ERROR) from None


def _require_legacy(workspace, identity):
  if (scopes.scope_claim_exists(workspace.instance)
      or coordination.runtime_claim_exists(workspace.cache, identity)):
    raise Conflict(_ERROR)


def prepare(workspace, lock):
  try:
    identity = runtime.runtime_identity(workspace, lock)
    if sys.platform == "linux":
      omp_setup.prepare_setup(workspace, identity)
    else:
      # 非 Linux 不登记；已有合作证据不能降级为旧入口。
      _require_legacy(workspace, identity)
  except Conflict:
    raise
  except Exception:
    raise Conflict(_ERROR) from None


def write_guard(workspace, *, create=False):
  return _admit(lambda: omp_scope_write_guard(workspace)
    if scopes.scope_claim_exists(workspace.instance)
    else omp_identity.lifecycle_guard(workspace, create=create))


def apply_for(workspace, lock):
  def select():
    identity = runtime.runtime_identity(workspace, lock)
    if sys.platform == "linux":
      return omp_setup.apply_guard(workspace, identity)
    _require_legacy(workspace, identity)
    return omp_identity.lifecycle_guard(workspace, create=True)
  return _admit(select)


def run_guard(workspace):
  def select():
    if not scopes.scope_claim_exists(workspace.instance):
      return omp_identity.lifecycle_guard(workspace, shared=True)
    if sys.platform != "linux":
      raise Conflict(_ERROR)
    _omp_launch_context(workspace)
    # 不创建状态目录；这次读取仅选择候选，原 runtime 的 state SH/绑定/包重核仍必要。
    with Tree(workspace.state_root) as state:
      if state.read("pending.json") is not None:
        raise Conflict(_ERROR)
      current = read_state(state)["current"]
      if current is None or current["binding"] != workspace.binding:
        raise Conflict(_ERROR)
      launch = current["launch"]
      identity = launch["runtime_identity"] if "runtime_identity" in launch else launch["lock_identity"]
      if type(identity) is not str:
        raise Conflict(_ERROR)
      safe_id(identity)
    return omp_lifecycle.cooperative_run(workspace, identity)
  return _admit(select)

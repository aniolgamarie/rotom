"""仅可信 Python 内部 fresh-only setup/apply 接缝；不注册默认入口。"""
from contextlib import contextmanager, ExitStack
import os
import re
import stat

from . import omp_identity, resource_coordination as coordination, resource_scopes as scopes
from .lifecycle import _omp_launch_context, omp_scope_write_guard
from .omp_lifecycle import _shared_file
from .paths import safe_id
from .storage import Conflict, Tree


_ERROR = "OMP准备或写入归属不能确认；保留保护，未自动采用旧资源"


def _context(workspace, runtime_identity):
  root, _, _ = _omp_launch_context(workspace)
  if (type(runtime_identity) is not str or safe_id(runtime_identity) != runtime_identity
      or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,191}", runtime_identity) is None):
    raise Conflict(_ERROR)
  return coordination.Domain(root)


def _exists(path, *, directory=False):
  # 只探测存在性；缺失祖先也逐层核验，不创建路径，不跟随链接。
  with Tree(path.parent) as tree:
    if tree.fd is None:
      _exists(path.parent, directory=True)
      return False
    try:
      with tree.parent(path.name) as (parent, name):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
      return False
    if stat.S_ISLNK(info.st_mode):
      raise Conflict(_ERROR)
    if directory:
      if not stat.S_ISDIR(info.st_mode):
        raise Conflict(_ERROR)
      with Tree(path):
        pass
    return True


def _check_runtime(domain, workspace, runtime_identity):
  # 只证明现存包的完整同域声明；结束即释放，不能把包 SH 带到 instance EX 前。
  with _shared_file(workspace.cache, "leases/" + runtime_identity + ".lock") as fd:
    domain.check_runtime(workspace.cache, runtime_identity, lease_fd=fd, idle=False)


def prepare_setup(workspace, runtime_identity, *, maintenance=None):
  """fresh 才能登记新包；不创建实例、profile state 或 owner，也不清理失败保护。

  跨资源首次登记不是全有或全无；并发留下的部分或混合现场必须保留并失败关闭。
  """
  try:
    if maintenance is not None:
      from .maintenance_execution import require_execution
      require_execution(maintenance).check_runtime(workspace, runtime_identity, stage="prepare")
    domain = _context(workspace, runtime_identity)
    cooperative = scopes.scope_claim_exists(workspace.instance)
    claimed_runtime = coordination.runtime_claim_exists(workspace.cache, runtime_identity)
    if maintenance is not None and not (cooperative and claimed_runtime):
      raise Conflict(_ERROR)
    if cooperative:
      options = {"maintenance": maintenance, "stage": "prepare"} if maintenance is not None else {}
      with omp_scope_write_guard(workspace, **options):
        pass
    elif _exists(workspace.instance, directory=True):
      omp_identity.preflight_setup(workspace)
      if claimed_runtime:
        raise Conflict(_ERROR)
      return
    if claimed_runtime:
      _check_runtime(domain, workspace, runtime_identity)
      return
    lease_exists = _exists(workspace.cache / "leases" / (runtime_identity + ".lock"))
    runtime_exists = _exists(workspace.cache / "runtimes" / runtime_identity, directory=True)
    if lease_exists or runtime_exists:
      if cooperative:
        raise Conflict(_ERROR)
      return
    # 已合作 scope 的域必须已经完整；不能用初始化来修补其缺失状态。
    if cooperative:
      domain.snapshot()
    else:
      domain = coordination.initialize_domain(domain.root)
    coordination.enroll_runtime(domain, workspace.cache, runtime_identity)
  except Exception:
    raise Conflict(_ERROR) from None


@contextmanager
def apply_guard(workspace, runtime_identity, *, maintenance=None):
  """现存合作资源核验后才登记 fresh scope；返回原 instance EX fd。"""
  with ExitStack() as stack:
    try:
      if maintenance is not None:
        from .maintenance_execution import require_execution
        require_execution(maintenance).check_runtime(workspace, runtime_identity, stage="apply")
      domain = _context(workspace, runtime_identity)
      legacy = False
      if maintenance is not None and not (scopes.scope_claim_exists(workspace.instance)
          and coordination.runtime_claim_exists(workspace.cache, runtime_identity)):
        raise Conflict(_ERROR)
      if scopes.scope_claim_exists(workspace.instance):
        options = {"maintenance": maintenance, "stage": "apply"} if maintenance is not None else {}
        guard = omp_scope_write_guard(workspace, **options)
      else:
        claimed_runtime = coordination.runtime_claim_exists(workspace.cache, runtime_identity)
        if _exists(workspace.instance, directory=True):
          if claimed_runtime:
            raise Conflict(_ERROR)
          legacy = True
          guard = omp_identity.lifecycle_guard(workspace, create=True)
        elif claimed_runtime:
          _check_runtime(domain, workspace, runtime_identity)
          scopes.enroll_scope(domain, workspace)
          guard = omp_scope_write_guard(workspace)
        else:
          legacy = True
          guard = omp_identity.lifecycle_guard(workspace, create=True)
      fd = stack.enter_context(guard)
      # 只捕获取得原物理 EX 时已经可见的并发 claim，不消除之后的跨资源窗口。
      # 运行入口仍须复核包 claim/anchor；混合现场不清理、不重试或自动登记 scope。
      if legacy and coordination.runtime_claim_exists(workspace.cache, runtime_identity):
        raise Conflict(_ERROR)
    except Exception:
      raise Conflict(_ERROR) from None
    yield fd

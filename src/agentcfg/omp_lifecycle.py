"""仅可信 Python 候选的 OMP 合作上下文；不注册日常适配器或首次采用。"""
from contextlib import contextmanager, ExitStack
import os
import stat
import sys
import time

from . import resource_owners as owners, run_owners
from .descendants import DescendantScope
from .lifecycle import CooperativeRunLease, cancel_omp_launch, check_omp_launch, reserve_omp_launch
from .resource_coordination import Domain
from .resource_keys import resource_key
from .storage import Conflict, Tree, advisory_lock


_ERROR = "OMP 合作运行上下文不能确认；保留已有保护"
_WARNING = "OMP 运行保护记账或收尾未能确认；保留事实，请人工核验"


def _warn():
  try:
    print(_WARNING, file=sys.stderr)
  except BaseException:
    pass


def _same_file(tree, name, fd):
  if type(fd) is not int or fd < 0 or tree.fd is None:
    raise Conflict(_ERROR)
  with tree.parent(name) as (parent, leaf):
    named = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
    opened = os.fstat(fd)
    for info in (named, opened):
      if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
          or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        raise Conflict(_ERROR)
    if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
      raise Conflict(_ERROR)


def _close(stack):
  try:
    stack.close()
  except BaseException:
    _warn()


@contextmanager
def _shared_file(root, name):
  stack = ExitStack()
  fd = None
  try:
    try:
      tree = stack.enter_context(Tree(root))
      if tree.fd is None:
        raise Conflict(_ERROR)
      with tree.parent(name) as (parent, leaf):
        fd = os.open(leaf, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
      _same_file(tree, name, fd)
      stack.enter_context(advisory_lock(fd, shared=True, unlock=False))
      _same_file(tree, name, fd)
    except Exception:
      raise Conflict(_ERROR) from None
    yield fd
  finally:
    if fd is not None:
      try:
        os.close(fd)
      except BaseException:
        _warn()
    _close(stack)


@contextmanager
def cooperative_run(workspace, runtime_identity):
  """先预留再取 physical SH；state SH 由 runtime 在 package 前取得。

  HOME 只固定目录身份。token/三 fd/owner 的实际覆盖须由既有原语核验，
  本上下文不提供额外的控制许可，也不使任何默认 OMP 入口可用。
  """
  instance, state_root, cache = workspace.instance, workspace.state_root, workspace.cache
  token = reserve_omp_launch(workspace, runtime_identity)
  domain = Domain(token.domain_root)
  active = True
  package_used = False
  package_active = False
  current_package_fd = None
  owner_used = False
  owner_attempted = False
  owner_active = False
  current_state_fd = None
  physical_fd = None
  home_fd = None
  outer = ExitStack()

  def unchanged(selected):
    if (not active or selected is not workspace or workspace.instance != instance
        or workspace.state_root != state_root or workspace.cache != cache):
      raise Conflict(_ERROR)

  def observing(run_id):
    unchanged(workspace)
    if run_id != token.run_id or not owner_active or not package_active:
      raise Conflict(_ERROR)
    try:
      for fd in (physical_fd, home_fd, current_package_fd, current_state_fd):
        os.fstat(fd)
      with Tree(state_root) as state:
        _same_file(state, "instance.lock", current_state_fd)
    except Exception:
      raise Conflict(_ERROR) from None

  class RunObserver:
    def snapshot(self):
      observing(token.run_id)
      return run_owners.Registry(state_root / "run-owners", workspace.binding).snapshot()

    def bind_current_host(self, run_id, host):
      observing(run_id)
      from .omp_run_observation import bind_current_host
      return bind_current_host(domain, run_id, workspace=workspace, instance_fd=physical_fd,
        native_home_fd=home_fd, runtime_fds={token.runtime_resource_id: current_package_fd}, host=host)

  def observer_factory(run_id):
    observing(run_id)
    return RunObserver()

  @contextmanager
  def package_guard(selected, identity):
    nonlocal package_used, package_active, current_package_fd
    stack = ExitStack()
    try:
      try:
        unchanged(selected)
        if package_used or identity != token.runtime_identity:
          raise Conflict(_ERROR)
        package_used = True
        fd = stack.enter_context(_shared_file(cache, "leases/" + identity + ".lock"))
        key = resource_key("runtime", cache / "leases" / (identity + ".lock"), lease_fd=fd).as_dict()
        with domain._transaction(deadline_ns=time.monotonic_ns() + 2_000_000_000) as state:
          if state["resources"][token.runtime_resource_id]["key"] != key:
            raise Conflict(_ERROR)
        current_package_fd, package_active = fd, True
      except Exception:
        raise Conflict(_ERROR) from None
      yield fd
    finally:
      package_active, current_package_fd = False, None
      _close(stack)

  @contextmanager
  def owner_guard(selected, *, metadata, lifecycle_fd, state_fd, package_fd):
    nonlocal owner_used, owner_attempted, owner_active, current_state_fd
    observer = None
    entered = False
    try:
      unchanged(selected)
      if owner_used or not package_active:
        raise Conflict(_ERROR)
      owner_used = True
      if (type(lifecycle_fd) is not int or lifecycle_fd != physical_fd
          or type(package_fd) is not int or package_fd != current_package_fd):
        raise Conflict(_ERROR)
      with Tree(state_root) as state:
        _same_file(state, "instance.lock", state_fd)
      check_omp_launch(token, workspace, instance_fd=physical_fd,
        native_home_fd=home_fd, package_fd=package_fd)
      manager = run_owners.current_process_identity()
      observer = DescendantScope(manager)
      # 固定 DescendantScope 可收尾部分进入，控制异常也必须释放全局观察锁。
      entered = True
      observer.__enter__()
      arguments = {"workspace": workspace, "instance_fd": physical_fd,
        "native_home_fd": home_fd, "runtime_fds": {token.runtime_resource_id: package_fd}}
      # 标记必须早于第一次可能已写入 owner 的调用；响应丢失不取消或重试。
      owner_attempted = True
      owners.attach_owner(domain, token.run_id, manager_identity=manager,
        metadata=metadata, expected_reservation=token, **arguments)
      owners.dispatch_owner(domain, token.run_id, expected_reservation=token, **arguments)
    except BaseException as error:
      if entered:
        try:
          observer.__exit__(*sys.exc_info())
        except BaseException:
          _warn()
      if isinstance(error, Exception):
        raise Conflict(_ERROR) from None
      raise
    try:
      current_state_fd, owner_active = state_fd, True
      yield token.run_id
    finally:
      owner_active, current_state_fd = False, None
      # 三 SH 与 HOME fd 仍由外层持有；记账失败不覆盖原生退出或异常。
      try:
        observation = observer.observe(token.run_id)
        if observation is None:
          owners.mark_owner_unknown(domain, token.run_id, manager_identity=manager, **arguments)
        elif (type(observation) is run_owners.ReleaseObservation
            and observation.complete is True and observation.all_related_exited is True):
          owners.finish_owner(domain, token.run_id, observation=observation, **arguments)
        else:
          raise Conflict(_ERROR)
      except BaseException:
        _warn()
      finally:
        try:
          observer.__exit__(*sys.exc_info())
        except BaseException:
          _warn()

  try:
    try:
      unchanged(workspace)
      physical_fd = outer.enter_context(_shared_file(instance, ".agentcfg-omp.lock"))
      home = outer.enter_context(Tree(instance / "user-home"))
      if home.fd is None:
        raise Conflict(_ERROR)
      home_fd = home.fd
    except Exception:
      raise Conflict(_ERROR) from None
    yield CooperativeRunLease(physical_fd, package_guard, owner_guard, observer_factory)
  finally:
    active = False
    if not owner_attempted:
      try:
        cancel_omp_launch(token, workspace)
      except BaseException:
        _warn()
    _close(outer)

"""停止元数据短锁；不控制宿主、不延长调用方截止时间。"""
from contextlib import contextmanager
import fcntl
import time

from .storage import Conflict, Tree


_ERROR = "停止元数据锁或原截止时间不能确认；保留事实且不重试派发"


@contextmanager
def locked(registry, deadline_ns, *, create=False, allow_expired_once=False, check_after=False):
  """只等待短锁竞争；复用原单调截止点，锁内不获取物理锁。"""
  try:
    if (type(deadline_ns) is not int or not 0 < deadline_ns <= 2**63 - 1
        or any(type(value) is not bool for value in (create, allow_expired_once, check_after))):
      raise ValueError()
    last = None
    def remaining():
      nonlocal last
      now = time.monotonic_ns()
      if (type(now) is not int or not 0 <= now <= 2**63 - 1
          or last is not None and now < last or deadline_ns - now > 300000000000):
        raise ValueError()
      last = now
      return deadline_ns - now
    left = remaining()
    if left <= 0 and not allow_expired_once:
      raise ValueError()
    with Tree(registry.root, create=create) as tree:
      if tree.fd is None:
        raise ValueError()
      contended = False
      while True:
        try:
          fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
          break
        except BlockingIOError:
          contended = True
          left = remaining()
          if left <= 0:
            raise ValueError()
          time.sleep(min(0.01, left / 1000000000))
          if remaining() <= 0:
            raise ValueError()
      try:
        registry._verify_root(tree)
        if remaining() <= 0 and (not allow_expired_once or contended):
          raise ValueError()
        yield tree
        registry._verify_root(tree)
        if check_after and remaining() <= 0:
          raise ValueError()
      finally:
        fcntl.flock(tree.fd, fcntl.LOCK_UN)
  except Exception:
    raise Conflict(_ERROR) from None


@contextmanager
def try_locked(registry):
  """只将真实 EAGAIN 作为本次未观察；缺根、坏路径和元数据仍失败。"""
  try:
    with Tree(registry.root) as tree:
      if tree.fd is None:
        raise ValueError()
      try:
        fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      except BlockingIOError:
        yield None
        return
      try:
        registry._verify_root(tree)
        yield tree
        registry._verify_root(tree)
      finally:
        fcntl.flock(tree.fd, fcntl.LOCK_UN)
  except Exception:
    raise Conflict(_ERROR) from None

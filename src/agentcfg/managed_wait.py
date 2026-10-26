"""manager 单线程服务等待；由 dsh_process 的可信工厂安装停止服务。

仅调度可信内存回调，不提供 IPC、身份、批准或释放证明，不设置 TUI 总期限。
调用方保持现场句柄和租约，各请求的截止预算由 service 独立负责。
"""
import math
import subprocess

from .storage import Conflict


_ERROR = "manager 服务等待参数无效"


def wait_with_service(child, *, service, interval=0.1, unavailable=None) -> int:
  try:
    if (not callable(service) or unavailable is not None and not callable(unavailable)
        or type(interval) not in (int, float) or not math.isfinite(interval) or not 0 < interval <= 1):
      raise ValueError()
  except Exception:
    raise Conflict(_ERROR) from None
  while True:
    try:
      return child.wait(timeout=interval)
    except subprocess.TimeoutExpired:
      pass
    try:
      service()
    except Exception:
      # 服务一旦未知便永久关闭；只等待同一 child，不重试回调或派发控制。
      if unavailable is not None:
        try:
          unavailable()
        except Exception:
          pass
      return child.wait()

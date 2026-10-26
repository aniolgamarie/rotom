"""DSH 共享启动生命周期；由受管入口为已准入组合提供可信停止服务工厂。"""
import subprocess
import sys

from .storage import Conflict


class WaitUnconfirmed(Exception):
  """等待观察失败不等于宿主未启动，避免被 OSError 路径误分类。"""


def _warn(message):
  try:
    print(message, file=sys.stderr)
  except Exception:
    pass


def _close_control(service, exc):
  if service is None:
    return
  try:
    service.close()
  except BaseException as error:
    # 服务只撤销内存资格；收尾不能覆盖已有等待或控制异常。
    if exc[0] is not None:
      return
    if not isinstance(error, Exception):
      raise
    _warn("停止服务收尾未能确认；保留记录与原宿主结果。")


def launch(spec, env, pass_fds, *, run_id, owner_registry=None, manager_identity=None,
    before_dispatch=None, after_dispatch=None, attempt=None, resume=False, control_factory=None) -> int:
  # 工厂仅由可信受管入口提供；缺省不创建控制服务，也不限制 TUI 总时长。
  if control_factory is not None and not callable(control_factory):
    raise Conflict("停止服务工厂无效；尚未启动宿主")
  if before_dispatch is not None:
    before_dispatch(run_id)
  child = subprocess.Popen(list(spec.argv), cwd=spec.cwd, env=env, pass_fds=pass_fds)
  host, service = None, None
  host_bound, startup_observed = False, True
  try:
    if owner_registry is not None:
      from .spawned_host import capture_spawned_host
      try:
        # 必须先于 wait/poll 和其它启动后回调；只借用当次 Popen 对象。
        host = capture_spawned_host(child, manager_identity)
        if host is None:
          _warn("恢复进程身份未确认；继续等待原宿主，自动控制保持关闭。" if resume
            else "启动进程身份未确认；继续等待原宿主，自动控制保持关闭。")
        else:
          owner_registry.bind_current_host(run_id, host)
          host_bound = True
      except Exception:
        _warn("恢复进程身份未能登记；继续等待原宿主，自动控制保持关闭。" if resume
          else "启动进程身份未能登记；继续等待原宿主，自动控制保持关闭。")
    if attempt is not None:
      try:
        attempt.launched()
      except Exception:
        startup_observed = False
        _warn("恢复启动记账未完成；保留未知记录，未发送继续。" if resume
          else "启动记账未完成；保留未知记录。")
    if after_dispatch is not None:
      try:
        after_dispatch(run_id)
      except Exception:
        startup_observed = False
        _warn("恢复派发通知未完成；继续等待原宿主，未发送继续。" if resume
          else "启动派发通知未完成；继续等待原宿主。")
    if control_factory is not None:
      try:
        if not host_bound or not startup_observed:
          raise ValueError()
        from .stop_service import StopService
        candidate = control_factory(run_id=run_id, host=host)
        if type(candidate) is not StopService or candidate.belongs_to(run_id, host) is not True:
          raise ValueError()
        service = candidate
      except Exception:
        # 子进程已启动：控制服务失效只撤销服务，不放弃等待、不再 spawn。
        _warn("停止服务未能建立；继续等待原宿主，保留已有记录。")
    try:
      if service is None:
        code = child.wait()
      else:
        from .managed_wait import wait_with_service
        code = wait_with_service(child, service=service, unavailable=lambda:
          _warn("停止请求处理未能确认；保留事实并继续等待原宿主。"))
    except Exception:
      # 不重复 wait 或 spawn；继承的租约和既有 unknown owner 保留保护。
      raise WaitUnconfirmed("dsh_resume_wait_unconfirmed" if resume else "dsh_run_wait_unconfirmed") from None
    code = code if code >= 0 else 128 - code
    if attempt is not None:
      try:
        attempt.exited(code)
      except Exception:
        _warn("恢复退出记账未完成；保留原生退出结果，请检查恢复记录。" if resume
          else "启动退出记账未完成；保留原生退出结果，请检查运行记录。")
    return code
  finally:
    try:
      _close_control(service, sys.exc_info())
    finally:
      if host is not None:
        # 只清理自有 pidfd；由句柄保护原等待/控制异常，新的关闭中断仍透传。
        host.__exit__(*sys.exc_info())

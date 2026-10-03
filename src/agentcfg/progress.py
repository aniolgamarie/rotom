"""输出固定阶段、后端脱敏进度和等待时间，不展示安装器原始输出。"""

from contextlib import contextmanager
import sys
import threading
import time

from .presentation import command_line


class Progress:
  def __init__(self, command, args, *, interval=15):
    self.command = command
    self.args = args
    self.interval = interval
    self.stage_name = "选择机器和配方"
    self.started = time.monotonic()

  def stage(self, name, *, hint=None):
    repeated = name == self.stage_name and hasattr(self.args, "progress_stage")
    self.stage_name = name
    self.args.progress_stage = name
    self.args.progress_hint = hint
    if repeated:
      return
    self.started = time.monotonic()
    print(f"{self.command}: {name}…", file=sys.stderr, flush=True)

  def sync_stage(self, name):
    self.stage(f"同步依赖 / {name}", hint="doctor")

  @contextmanager
  def heartbeat(self):
    stopped = threading.Event()

    def report():
      while not stopped.wait(self.interval):
        elapsed = round(time.monotonic() - self.started)
        print(f"{self.command}: {self.stage_name}仍在进行（距上次进度更新已等待 {elapsed} 秒）", file=sys.stderr, flush=True)

    worker = threading.Thread(target=report, name="agentcfg-progress", daemon=True)
    worker.start()
    try:
      yield
    finally:
      stopped.set()
      worker.join()


def failure_context(args, code, *, interrupted=False, reason=None, hint=None):
  if (reason is None and not interrupted and args.command not in ("setup", "sync")
      and not hasattr(args, "progress_stage")):
    return
  stage = getattr(args, "progress_stage", "")
  verb = "已中断" if interrupted else "失败"
  print(f"{args.command}: {stage}{verb}（退出码 {code}）", file=sys.stderr)
  if reason:
    print("原因: " + reason, file=sys.stderr)
  hint = hint or getattr(args, "progress_hint", None)
  if hint:
    print("下一步:\n  " + command_line(args, *hint.split()), file=sys.stderr)

"""只输出固定阶段名和等待时间，不展示安装器原始输出。"""

from contextlib import contextmanager
import sys
import threading
import time


class Progress:
  def __init__(self, command, args, *, interval=15):
    self.command = command
    self.args = args
    self.interval = interval
    self.stage_name = "选择机器和配方"
    self.started = time.monotonic()

  def stage(self, name, *, hint=None):
    self.stage_name = name
    self.started = time.monotonic()
    self.args.progress_stage = name
    self.args.progress_hint = hint
    print(f"{self.command}: {name}…", file=sys.stderr, flush=True)

  def sync_stage(self, name):
    self.stage(f"同步依赖 / {name}", hint="doctor")

  @contextmanager
  def heartbeat(self):
    stopped = threading.Event()

    def report():
      while not stopped.wait(self.interval):
        elapsed = round(time.monotonic() - self.started)
        print(f"{self.command}: {self.stage_name}仍在进行（已等待 {elapsed} 秒）", file=sys.stderr, flush=True)

    worker = threading.Thread(target=report, name="agentcfg-progress", daemon=True)
    worker.start()
    try:
      yield
    finally:
      stopped.set()
      worker.join()


def failure_context(args, code, *, interrupted=False):
  if args.command not in ("setup", "sync") and not hasattr(args, "progress_stage"):
    return
  stage = getattr(args, "progress_stage", "选择机器和配方")
  verb = "已中断" if interrupted else "失败"
  print(f"{args.command}: {stage}{verb}（退出码 {code}）", file=sys.stderr)
  hint = getattr(args, "progress_hint", None)
  if hint:
    suffix = " 查看依赖与工具链状态" if hint == "doctor" else " 查看脱敏诊断"
    print(f"排查: 使用相同选择器运行 ./agentcfg {hint}{suffix}，处理原因后重试", file=sys.stderr)

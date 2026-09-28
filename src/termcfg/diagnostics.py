"""不输出私人正文的阶段进度与统一结果。"""

import json
import sys
import threading
import time
from contextlib import contextmanager


_CURRENT = threading.local()


def reset_progress() -> None:
  _CURRENT.stage = None
  _CURRENT.component = None


def current_progress() -> dict:
  return {key: value for key, value in (("stage", getattr(_CURRENT, "stage", None)),
          ("component", getattr(_CURRENT, "component", None))) if value}


class Progress:
  def __init__(self, command: str):
    self.command = command
    self.start = time.monotonic()
    self.last = 0.0

  def stage(self, name: str, *, component: str = "", item: str = "", force: bool = True):
    _CURRENT.stage = name
    if component:
      _CURRENT.component = component
    now = time.monotonic()
    if force or now - self.last >= 1.5:
      bits = [self.command, name]
      if component:
        bits.append(component)
      if item:
        bits.append(item)
      bits.append(f"{now - self.start:.1f}s")
      print(" | ".join(bits), file=sys.stderr, flush=True)
      self.last = now


@contextmanager
def heartbeat(progress: Progress, stage: str, *, component: str = ""):
  stop = threading.Event()
  thread = threading.Thread(target=lambda: _heartbeat_loop(stop, progress, stage, component), daemon=True)
  thread.start()
  try:
    yield
  finally:
    stop.set()
    thread.join(timeout=2)


def _heartbeat_loop(stop: threading.Event, progress: Progress, stage: str, component: str):
  while not stop.wait(1.5):
    progress.stage(stage, component=component, force=False)


def emit(payload: dict, *, json_mode: bool = False) -> None:
  if json_mode:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
  else:
    for name, value in payload.items():
      if name == "components" and isinstance(value, dict):
        for component, result in value.items():
          print(f"{component}: {result}")
      else:
        print(f"{name}: {value}")

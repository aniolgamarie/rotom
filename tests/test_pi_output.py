"""模拟管道输出，不启动进程；验证有界捕获及最后发布完成标记。"""

from io import BytesIO
import json
from types import SimpleNamespace

from agentcfg.pi_output import OutputCapture


def test_capture_drains_but_limits_private_outputs(tmp_path):
  capture = OutputCapture(tmp_path / "output", limit=16)
  capture.attach(SimpleNamespace(stdout=BytesIO(b"x" * 100000), stderr=BytesIO(b"warning")))
  for thread in capture.threads:
    thread.join(2)
  assert capture.complete()
  assert (capture.root / "stdout").read_bytes() == b"x" * 16
  assert (capture.root / "stderr").read_bytes() == b"warning"
  record = json.loads((capture.root / "capture.json").read_text())
  assert record["complete"] is True and record["truncated"] is True
  assert record["streams"]["stdout"]["bytes"] == 16


def test_live_output_is_available_before_eof_with_explicit_cursor(tmp_path):
  from io import BytesIO
  from types import SimpleNamespace
  import threading
  import base64
  from agentcfg.pi_output import OutputCapture
  ready, finish = threading.Event(), threading.Event()
  class Live:
    sent = False
    def read1(self, limit):
      if not self.sent:
        self.sent = True; return b"ready\n"
      ready.set(); assert finish.wait(5); return b""
    def read(self, limit): raise AssertionError("live capture must use read1, not wait for a full buffer")
    def close(self): pass
  capture = OutputCapture(tmp_path / "capture")
  capture.attach(SimpleNamespace(stdout=Live(), stderr=BytesIO()))
  try:
    assert ready.wait(2)
    snapshot = capture.since(0)
    assert snapshot["complete"] is False and snapshot["dropped"] is False
    assert base64.b64decode(snapshot["events"][0]["data_b64"]) == b"ready\n"
    assert capture.since(snapshot["next_cursor"])["events"] == []
  finally:
    finish.set()
    for thread in capture.threads: thread.join(5)
  assert capture.complete()

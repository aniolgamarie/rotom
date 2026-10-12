"""临时目录和假流验证输出保留故障；不启动宿主、不清理恢复引用。"""
import base64
import errno
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

from agentcfg.pi_output import OutputCapture
from agentcfg.storage import Tree


def finish(capture):
  for thread in capture.threads:
    thread.join(5)
    assert not thread.is_alive()
  assert capture.complete()


@pytest.mark.parametrize("number", [errno.ENOSPC, errno.EROFS])
@pytest.mark.parametrize("name", ["stdout", "capture.json"])
def test_failed_retention_never_publishes_successful_capture(tmp_path, monkeypatch, number, name):
  write = Tree.write_immutable
  calls = []
  def failing_write(tree, path, content):
    calls.append(path)
    if path == name:
      raise OSError(number, "synthetic retention failure")
    return write(tree, path, content)
  monkeypatch.setattr(Tree, "write_immutable", failing_write)
  capture = OutputCapture(tmp_path / "capture", limit=32)
  streams = [BytesIO(b"x" * 100000), BytesIO(b"warning")]
  capture.attach(SimpleNamespace(stdout=streams[0], stderr=streams[1]))
  finish(capture)
  assert all(stream.closed for stream in streams)
  assert name in calls
  metadata = capture.root / "capture.json"
  if name == "capture.json":
    assert not metadata.exists()
  elif metadata.exists():
    assert json.loads(metadata.read_text())["complete"] is False
  assert any(row["failed"] for row in capture.results.values())
  assert not any("synthetic retention failure" in str(row) for row in capture.results.values())


@pytest.mark.parametrize("number", [errno.ENOSPC, errno.EROFS])
def test_failed_stream_before_other_eof_cannot_publish_success(tmp_path, monkeypatch, number):
  write = Tree.write_immutable
  def failing_write(tree, path, content):
    if path == "stdout":
      raise OSError(number, "synthetic retention failure")
    return write(tree, path, content)
  monkeypatch.setattr(Tree, "write_immutable", failing_write)
  capture = OutputCapture(tmp_path / "capture")
  # 固定真实读取器完成顺序，覆盖失败先登记、另一个流随后到EOF的分支。
  capture._read("stdout", BytesIO(b"output"))
  assert capture.results["stdout"]["failed"] is True
  assert not (capture.root / "capture.json").exists()
  capture._read("stderr", BytesIO(b"warning"))
  assert capture.results["stdout"]["failed"] is True
  metadata = capture.root / "capture.json"
  if metadata.exists():
    record = json.loads(metadata.read_text())
    assert record["complete"] is False
    assert record["streams"]["stdout"]["failed"] is True


def test_read_failure_persists_incomplete_evidence_and_closes_stream(tmp_path):
  class Broken:
    closed = False
    reads = 0
    def read(self, limit):
      self.reads += 1
      if self.reads == 1:
        return b"retained-prefix"
      raise OSError(errno.EIO, "PRIVATE_STREAM_ERROR")
    def close(self):
      self.closed = True
  stream = Broken()
  capture = OutputCapture(tmp_path / "capture")
  capture.attach(SimpleNamespace(stdout=stream, stderr=BytesIO()))
  finish(capture)
  assert stream.closed
  record = json.loads((capture.root / "capture.json").read_text())
  assert record["complete"] is False
  assert record["streams"]["stdout"]["failed"] is True
  assert (capture.root / "stdout").read_bytes() == b"retained-prefix"
  assert "PRIVATE_STREAM_ERROR" not in json.dumps(record)


def test_output_flood_has_bounded_file_ring_and_explicit_observer_gap(tmp_path):
  class Flood:
    closed = False
    remaining = 2048
    def read(self, limit):
      assert limit == 65536
      if not self.remaining:
        return b""
      self.remaining -= 1
      return b"x" * limit
    def close(self):
      self.closed = True
  stream = Flood()
  capture = OutputCapture(tmp_path / "capture", limit=16)
  capture.attach(SimpleNamespace(stdout=stream, stderr=BytesIO()))
  finish(capture)
  assert stream.closed and stream.remaining == 0
  assert (capture.root / "stdout").read_bytes() == b"x" * 16
  assert len(capture.events) <= 1024
  assert sum(len(row[2]) for row in capture.events) <= 4 * 1024 * 1024
  value = capture.since(0)
  assert value["dropped"] is True and value["has_more"] is True
  assert len(value["events"]) <= 4 and value["complete"] is True
  assert all(len(base64.b64decode(row["data_b64"])) <= 65536 for row in value["events"])
  record = json.loads((capture.root / "capture.json").read_text())
  assert record["complete"] is True and record["truncated"] is True

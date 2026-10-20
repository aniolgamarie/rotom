import importlib.util
from pathlib import Path
import json
import os
import pytest


@pytest.fixture
def producer():
  path = Path(__file__).parent / "fixtures/herdr-bench/v1/producer.py"
  spec = importlib.util.spec_from_file_location("client_proof_producer", path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def reader(producer, tmp_path, monkeypatch, chunks):
  monkeypatch.setattr(producer.os, "set_blocking", lambda *args: None)
  class Poll:
    def register(self, *args):
      pass
    def poll(self, timeout):
      return [(0, 1)] if chunks else []
  monkeypatch.setattr(producer.select, "poll", Poll)
  monkeypatch.setattr(producer.os, "read", lambda fd, count: chunks.pop(0))
  monkeypatch.setattr(producer.os, "get_terminal_size", lambda fd: os.terminal_size((80, 21)))
  writes = []
  monkeypatch.setattr(producer.os, "write", lambda fd, data: writes.append(bytes(data)) or len(data))
  item = producer.RecordReader(tmp_path, "a" * 32, "w1:p1")
  item.marker_writes = writes
  return item


def test_fragmented_and_multiple_receipts(producer, tmp_path, monkeypatch):
  line = lambda nonce: ("RB:" + "a" * 32 + ":" + nonce * 32 + "\n").encode()
  chunks = [line("b")[:12]]
  item = reader(producer, tmp_path, monkeypatch, chunks)
  item.pump("waiting")
  assert not list(tmp_path.glob("*.json"))
  chunks.append(line("b")[12:] + line("c"))
  item.pump("measure")
  rows = [json.loads(path.read_text()) for path in tmp_path.glob("*.json")]
  assert len(rows) == 2
  assert all(row["size"] == {"cols": 80, "rows": 21} and row["phase"] == "measure" for row in rows)
  assert all(path.stat().st_mode & 0o777 == 0o600 for path in tmp_path.glob("*.json"))


@pytest.mark.parametrize("payload", [b"x" * 70, b"bad\n", b"RB:" + b"d" * 32 + b":" + b"b" * 32 + b"\n"])
def test_rejects_invalid_input(producer, tmp_path, monkeypatch, payload):
  item = reader(producer, tmp_path, monkeypatch, [payload])
  with pytest.raises(ValueError):
    item.pump("warmup")
  assert not list(tmp_path.glob("*.json"))
  assert item.marker_writes == [b"RBREADY:" + b"a" * 32 + b"\n"]


def test_duplicate_nonce_rejected(producer, tmp_path, monkeypatch):
  line = b"RB:" + b"a" * 32 + b":" + b"b" * 32 + b"\n"
  item = reader(producer, tmp_path, monkeypatch, [line + line])
  with pytest.raises(ValueError):
    item.pump("record")
  assert len(list(tmp_path.glob("*.json"))) == 1


def test_wait_and_measure_pump(producer, tmp_path, monkeypatch):
  barrier = tmp_path / "measure.json"
  phases = []
  def pump(phase):
    phases.append(phase)
    if not barrier.exists():
      producer.write_new(barrier, {"run_id": "a" * 32, "phase": "measure", "start_ns": 1})
  monkeypatch.setattr(producer.time, "sleep", lambda _: None)
  assert producer.barrier(tmp_path, "a" * 32, "measure", pump=pump) == 1
  now = [1]
  def sleep(seconds):
    now[0] += round(seconds * 1e9)
  result = producer.window("record", 0, "measure", 1, clock=lambda: now[0], sleep=sleep, pump=pump)
  assert "waiting" in phases and "measure" in phases
  assert result["lines"] == result["bytes"] == 0
  assert now[0] == 300_000_000_001


def test_output_counts_unchanged_without_reader(producer):
  now = [1]
  def sleep(seconds):
    now[0] += round(seconds * 1e9)
  result = producer.window("output", 0, "warmup", 1, clock=lambda: now[0], sleep=sleep, write=lambda fd, data: len(data))
  assert result["lines"] == 60 * 512
  assert result["bytes"] == 60 * 512 * 128


@pytest.mark.parametrize("mode", ["idle", "output"])
def test_nonrecord_main_never_reads_stdin(producer, tmp_path, monkeypatch, mode):
  monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
  value = {"run_id": "a" * 32, "mode": mode, "seed": 0, "config_digest": "b" * 64}
  monkeypatch.setattr(producer, "config", lambda *args: (value, tmp_path))
  monkeypatch.setattr(producer, "RecordReader", lambda *args: pytest.fail("nonrecord reader"))
  monkeypatch.setattr(producer.os, "read", lambda *args: pytest.fail("nonrecord stdin"))
  monkeypatch.setattr(producer.os, "write", lambda *args: pytest.fail("nonrecord readiness marker"))
  monkeypatch.setattr(producer, "wait_file", lambda *args, **kwargs: {"run_id": "a" * 32, "panes": ["w1:p1"]})
  monkeypatch.setattr(producer, "write_new", lambda *args: None)
  monkeypatch.setattr(producer, "barrier", lambda *args, **kwargs: 1)
  def window(*args, **kwargs):
    assert kwargs.get("pump") is None
    raise RuntimeError("reached window")
  monkeypatch.setattr(producer, "window", window)
  with pytest.raises(RuntimeError, match="reached window"):
    producer.main()


def test_reader_bounded_and_eof(producer, tmp_path, monkeypatch):
  item = reader(producer, tmp_path, monkeypatch, [b""])
  with pytest.raises(ValueError, match="closed"):
    item.pump("record")
  item = reader(producer, tmp_path, monkeypatch, [])
  with pytest.raises(ValueError, match="phase"):
    item.pump("unknown")


def test_record_marker_only_initial_and_after_valid_receipt(producer, tmp_path, monkeypatch):
  line = lambda nonce: b"RB:" + b"a" * 32 + b":" + nonce * 32 + b"\n"
  chunks = []
  item = reader(producer, tmp_path, monkeypatch, chunks)
  marker = b"RBREADY:" + b"a" * 32 + b"\n"
  assert item.marker_writes == [marker]
  original_write = producer.write_new
  def write_receipt(path, value):
    assert len(item.marker_writes) == 1
    original_write(path, value)
  monkeypatch.setattr(producer, "write_new", write_receipt)
  chunks.append(line(b"b"))
  item.pump("waiting")
  assert len(list(tmp_path.glob("*.json"))) == 1
  assert item.marker_writes == [marker, marker]
  chunks.append(line(b"b"))
  with pytest.raises(ValueError):
    item.pump("waiting")
  assert item.marker_writes == [marker, marker]


@pytest.mark.parametrize("invalid", [0, -1, None, True, 42])
def test_record_marker_partial_output_is_bounded_and_closed_rejected(producer, tmp_path, monkeypatch, invalid):
  item = reader(producer, tmp_path, monkeypatch, [])
  output = bytearray()
  def write(fd, data):
    assert fd == 1
    output.extend(data[:1])
    return 1
  monkeypatch.setattr(producer.os, "write", write)
  item.marker()
  assert output == b"RBREADY:" + b"a" * 32 + b"\n"
  monkeypatch.setattr(producer.os, "write", lambda fd, data: invalid)
  with pytest.raises(ValueError, match="output closed"):
    item.marker()

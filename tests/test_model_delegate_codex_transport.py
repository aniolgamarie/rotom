"""公开stdio生命周期契约：全假pipe/selector，不运行CLI，不把turn当model计量。"""
import io
import json
import time
from types import SimpleNamespace
import pytest
from agentcfg.model_delegate_codex_transport import CodexAppServerTransport
from agentcfg.storage import Conflict


def fixture(monkeypatch, *, wrong=False, eof=False):
  channel = io.BytesIO(); source = SimpleNamespace(fileno=lambda: 777)
  process = SimpleNamespace(stdin=channel, stdout=source)
  stopped = []; reads = []
  selector = SimpleNamespace(register=lambda *a: None, select=lambda timeout: [True], close=lambda: stopped.append("selector-close"))
  def read(fd, count):
    assert fd == 777 and count <= 65536
    reads.append(count)
    if eof: return b""
    request = json.loads(channel.getvalue().splitlines()[-1])
    result = {"userAgent": "synthetic"} if request["method"] == "initialize" else {"thread": {"id": "thread-one"}}
    return json.dumps({"id": "foreign" if wrong else request["id"], "result": result}).encode()+b"\n"
  monkeypatch.setattr("agentcfg.model_delegate_codex_transport.os.read", read)
  transport = CodexAppServerTransport(process, check=lambda: True, stop=lambda: stopped.append("original-stop"),
    deadline=time.monotonic()+10, selector=selector)
  return transport, channel, stopped, reads


def test_original_receiver_once_initialization_and_thread_binding(monkeypatch):
  transport, channel, stopped, _ = fixture(monkeypatch)
  transport.initialize()
  assert [json.loads(line)["method"] for line in channel.getvalue().splitlines()] == ["initialize", "initialized"]
  frame = {"action": "thread_start", "request_id": "thread-request", "binding": {"model": "selected", "model_provider": "managed", "cwd": "/owned"}}
  assert transport.action(frame)["thread"]["id"] == "thread-one"
  with pytest.raises(Conflict, match="REQUEST_REPLAY"): transport.action(frame)
  assert len(channel.getvalue().splitlines()) == 3
  transport.close(); transport.close()
  assert stopped == ["original-stop", "selector-close"]


def test_turn_requires_qualified_meter_and_never_calls_write_or_read(monkeypatch):
  transport, channel, _, reads = fixture(monkeypatch)
  transport.thread_id = "thread-one"
  with pytest.raises(Conflict, match="METER_UNAVAILABLE"):
    transport.action({"action": "turn_start", "request_id": "turn-request", "binding": {"model": "selected", "model_provider": "managed", "cwd": "/owned"}, "thread_id": "thread-one", "text": "private task"})
  assert channel.getvalue() == b"" and reads == []


@pytest.mark.parametrize("wrong,eof", [(True,False),(False,True)])
def test_bad_reply_or_eof_is_unknown_not_termination_or_retry(monkeypatch, wrong, eof):
  transport, channel, stopped, _ = fixture(monkeypatch, wrong=wrong, eof=eof)
  with pytest.raises(Conflict): transport.initialize()
  assert len(channel.getvalue().splitlines()) == 1
  assert stopped == []
  transport.close()
  assert stopped == ["original-stop", "selector-close"]


@pytest.mark.parametrize("timestamp,extra,accepted", [(1234, {}, True), (True, {}, False),
  (2 ** 63, {}, False), (1234, {"authority": "untrusted"}, False)])
def test_public_notification_timestamp_is_observation_only(monkeypatch, timestamp, extra, accepted):
  transport, channel, _, _ = fixture(monkeypatch)
  frames = [{"method": "remoteControl/status/changed", "params": {}, "emittedAtMs": timestamp, **extra}]
  def read(fd, count):
    if frames: return json.dumps(frames.pop(0)).encode()+b"\n"
    request = json.loads(channel.getvalue().splitlines()[-1])
    return json.dumps({"id": request["id"], "result": {"userAgent": "synthetic"}}).encode()+b"\n"
  monkeypatch.setattr("agentcfg.model_delegate_codex_transport.os.read", read)
  if accepted:
    assert transport.initialize() == {"userAgent": "synthetic"}
    assert transport.events[0]["emittedAtMs"] == timestamp
    assert transport.thread_id is None and transport.turn_id is None
  else:
    with pytest.raises(Conflict, match="EVENT_INVALID"): transport.initialize()

"""中继只使用替身 socket；默认测试不会建立监听或执行 CLI。"""
from collections import deque
import selectors
import socket
from types import SimpleNamespace

import pytest

from agentcfg.pi_web_relay import LoopbackRelay, RelayError


class Socket:
  def __init__(self):
    self.reads = deque()
    self.sent = bytearray()
    self.closed = False
    self.write_closed = False
    self.send_limit = 65536

  def bind(self, address): self.bound = address
  def listen(self, count): self.backlog = count
  def setblocking(self, value): pass
  def settimeout(self, value): pass
  def connect(self, path): self.path = path
  def close(self): self.closed = True
  def shutdown(self, direction):
    assert direction == socket.SHUT_WR
    self.write_closed = True
  def recv(self, size):
    if not self.reads: raise BlockingIOError()
    data = self.reads.popleft()
    if len(data) > size: self.reads.appendleft(data[size:])
    return data[:size]
  def send(self, data):
    count = min(self.send_limit, len(data))
    self.sent.extend(data[:count])
    return count
  def accept(self): return self.client, ("127.0.0.1", 12345)


class Selector:
  def __init__(self): self.rows = {}; self.events = []
  def register(self, sock, events, data): self.rows[sock] = (events, data)
  def modify(self, sock, events, data): self.rows[sock] = (events, data)
  def unregister(self, sock): self.rows.pop(sock)
  def close(self): assert not self.rows
  def select(self, timeout):
    pending, self.events = self.events, []
    return [(SimpleNamespace(fileobj=sock, data=self.rows[sock][1]), events) for sock, events in pending]


def fixture():
  calls = []; selector = Selector(); now = [1]
  def factory(family, kind):
    sock = Socket(); calls.append((family, kind, sock)); return sock
  relay = LoopbackRelay("/private/proxy.sock", 41234, socket_factory=factory, selector_factory=lambda: selector, now=lambda: now[0])
  relay.start()
  client = Socket(); relay.listener.client = client
  selector.events = [(relay.listener, selectors.EVENT_READ)]; relay.poll()
  return relay, client, calls[-1][2], selector, calls, now


def test_relay_binds_only_loopback_and_connects_only_declared_unix_socket():
  relay, client, upstream, selector, calls, _ = fixture()
  assert relay.listener.bound == ("127.0.0.1", 41234)
  assert [row[0] for row in calls] == [socket.AF_INET, socket.AF_UNIX]
  assert upstream.path == "/private/proxy.sock"
  request = b"CONNECT example.invalid:443 HTTP/1.1\r\n\r\n"
  client.reads.append(request)
  selector.events = [(client, selectors.EVENT_READ)]; relay.poll()
  assert not upstream.sent
  upstream.send_limit = 5
  while relay.peers[upstream]["bytes"]:
    selector.events = [(upstream, selectors.EVENT_WRITE)]; relay.poll()
  assert upstream.sent == request
  relay.close(); relay.close()
  assert client.closed and upstream.closed and not relay.peers


def test_relay_applies_backpressure_and_drains_before_half_close():
  relay, client, upstream, selector, _, _ = fixture()
  client.reads.append(b"x" * 100000)
  for _ in range(4):
    selector.events = [(client, selectors.EVENT_READ)]; relay.poll()
  assert relay.peers[upstream]["bytes"] == 65536
  assert client not in selector.rows
  selector.events = [(upstream, selectors.EVENT_WRITE)]; relay.poll()
  assert client in selector.rows and relay.peers[upstream]["bytes"] < 65536
  client.reads.clear(); client.reads.append(b"")
  selector.events = [(client, selectors.EVENT_READ)]; relay.poll()
  assert not upstream.write_closed
  while relay.peers[upstream]["bytes"]:
    selector.events = [(upstream, selectors.EVENT_WRITE)]; relay.poll()
  assert upstream.write_closed and not client.closed
  upstream.reads.append(b"")
  selector.events = [(upstream, selectors.EVENT_READ)]; relay.poll()
  assert client.closed and upstream.closed
  relay.close()


def test_idle_connection_and_bind_failure_release_resources():
  relay, client, upstream, _, _, now = fixture()
  now[0] += 61; relay.poll()
  assert client.closed and upstream.closed
  relay.close()
  listener = Socket()
  def reject_bind(_address): raise OSError("occupied")
  listener.bind = reject_bind
  relay = LoopbackRelay("/private/proxy.sock", 41234, socket_factory=lambda *_: listener, selector_factory=Selector)
  with pytest.raises(OSError): relay.start()
  assert relay.closed and listener.closed


@pytest.mark.parametrize("path,port", [("relative", 1234), ("/socket\n", 1234), ("/" + "a" * 101, 1234), ("/socket", True), ("/socket", 0)])
def test_relay_binding_is_closed(path, port):
  with pytest.raises(RelayError): LoopbackRelay(path, port)

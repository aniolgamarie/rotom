"""沙箱内的回环中继；只连接冻结的 Unix 代理，不解析或直接连接目标主机。"""

from collections import deque
import selectors
import socket
import time

class RelayError(ValueError):
  """第一方中继只依赖标准库，沙箱无需导入配置或凭据模块。"""


class LoopbackRelay:
  def __init__(self, socket_path, port, *, socket_factory=socket.socket, selector_factory=selectors.DefaultSelector, now=time.monotonic):
    if (not isinstance(socket_path, str) or not socket_path.startswith("/") or len(socket_path.encode()) > 100
        or any(ord(char) < 32 or ord(char) == 127 for char in socket_path)
        or type(port) is not int or not 1024 <= port <= 65535):
      raise RelayError("pi-web-relay-binding")
    self.path = socket_path
    self.port = port
    self.factory = socket_factory
    self.selector = selector_factory()
    self.now = now
    self.listener = None
    self.peers = {}
    self.closed = False

  def start(self):
    if self.listener is not None or self.closed: raise RelayError("pi-web-relay-state")
    listener = self.factory(socket.AF_INET, socket.SOCK_STREAM)
    try:
      # 不使用 SO_REUSEPORT；已有占用明确失败，不能把 CLI 指向其他监听者。
      listener.bind(("127.0.0.1", self.port))
      listener.listen(32)
      listener.setblocking(False)
      self.selector.register(listener, selectors.EVENT_READ, None)
      self.listener = listener
    except BaseException:
      listener.close()
      self.close()
      raise

  def _accept(self):
    client, address = self.listener.accept()
    if address[0] != "127.0.0.1" or len(self.peers) >= 128:
      client.close()
      return
    upstream = self.factory(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
      upstream.settimeout(1)
      upstream.connect(self.path)
      for current, other in ((client, upstream), (upstream, client)):
        current.setblocking(False)
        row = {"socket": current, "other": other, "queue": deque(), "bytes": 0,
          "eof": False, "write_closed": False, "touched": self.now(), "registered": True}
        self.peers[current] = row
        self.selector.register(current, selectors.EVENT_READ, row)
    except OSError:
      self._drop(client)
      client.close()
      upstream.close()

  def _drop(self, current):
    row = self.peers.get(current)
    for item in (current, row["other"] if row else None):
      if item is None: continue
      record = self.peers.pop(item, None)
      if record and record["registered"]: self.selector.unregister(item)
      item.close()

  def _refresh(self, row):
    other = self.peers.get(row["other"])
    if not other: return
    events = (selectors.EVENT_READ if not row["eof"] and other["bytes"] < 65536 else 0)
    if row["bytes"]: events |= selectors.EVENT_WRITE
    if not row["bytes"] and other["eof"] and not row["write_closed"]:
      row["socket"].shutdown(socket.SHUT_WR)
      row["write_closed"] = True
    if row["eof"] and other["eof"] and not row["bytes"] and not other["bytes"]:
      self._drop(row["socket"])
      return
    if events and row["registered"]: self.selector.modify(row["socket"], events, row)
    elif events:
      self.selector.register(row["socket"], events, row); row["registered"] = True
    elif row["registered"]:
      self.selector.unregister(row["socket"]); row["registered"] = False

  def _transfer(self, row, events):
    other = self.peers.get(row["other"])
    if not other: return
    if events & selectors.EVENT_READ and not row["eof"] and other["bytes"] < 65536:
      try: data = row["socket"].recv(min(16384, 65536 - other["bytes"]))
      except BlockingIOError: data = None
      if data:
        other["queue"].append(data); other["bytes"] += len(data)
        row["touched"] = other["touched"] = self.now()
      elif data == b"": row["eof"] = True
    if events & selectors.EVENT_WRITE and row["queue"]:
      data = row["queue"][0]
      try: count = row["socket"].send(data)
      except BlockingIOError: count = 0
      if count:
        row["bytes"] -= count
        if count == len(data): row["queue"].popleft()
        else: row["queue"][0] = data[count:]
        row["touched"] = other["touched"] = self.now()
    self._refresh(row)
    if other["socket"] in self.peers: self._refresh(other)

  def poll(self, timeout=0.1):
    if self.closed or self.listener is None: raise RelayError("pi-web-relay-state")
    for key, events in self.selector.select(timeout):
      if key.data is None:
        try: self._accept()
        except BlockingIOError: pass
      elif key.fileobj in self.peers:
        try: self._transfer(key.data, events)
        except OSError: self._drop(key.fileobj)
    for current, row in list(self.peers.items()):
      if current in self.peers and self.now() - row["touched"] > 60: self._drop(current)

  def close(self):
    if self.closed: return
    self.closed = True
    for current in list(self.peers):
      if current in self.peers: self._drop(current)
    if self.listener is not None:
      self.selector.unregister(self.listener)
      self.listener.close()
      self.listener = None
    self.selector.close()

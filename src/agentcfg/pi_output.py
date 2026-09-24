"""持续排空输出但只保留有界私人文件；完成标记必须晚于两个管道的 EOF。"""

import hashlib
from pathlib import Path
import threading

from .deployment import json_bytes
from .storage import Tree, ensure_private


class OutputCapture:
  def __init__(self, root, limit=1024 * 1024):
    self.root, self.limit = Path(root), limit
    ensure_private(self.root)
    self.threads, self.results = [], {}
    self.lock = threading.Lock()
    self.events, self.sequence = [], 0

  def attach(self, process):
    for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
      thread = threading.Thread(target=self._read, args=(name, stream), daemon=True)
      self.threads.append(thread)
      thread.start()

  def _read(self, name, stream):
    content = bytearray()
    truncated, failed = False, False
    try:
      read = getattr(stream, "read1", stream.read)
      while chunk := read(65536):
        with self.lock:
          self.sequence += 1
          self.events.append((self.sequence, name, bytes(chunk)))
          self.events = self.events[-1024:]
          while sum(len(item[2]) for item in self.events) > 4 * 1024 * 1024:
            self.events.pop(0)
        room = self.limit - len(content)
        content.extend(chunk[:max(0, room)])
        truncated |= len(chunk) > room
    except Exception:
      failed = True
    finally:
      stream.close()
    try:
      with Tree(self.root) as tree:
        tree.write_immutable(name, bytes(content))
      result = {"path": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "truncated": truncated, "failed": failed}
      with self.lock:
        self.results[name] = result
        if len(self.results) == 2:
          with Tree(self.root) as tree:
            tree.write_immutable("capture.json", json_bytes({"schema_version": 1, "complete": not any(row["failed"] for row in self.results.values()),
              "truncated": any(row["truncated"] for row in self.results.values()), "streams": self.results}))
    except Exception:
      with self.lock:
        self.results[name] = {"failed": True}

  def complete(self):
    return all(not thread.is_alive() for thread in self.threads)

  def since(self, cursor):
    import base64
    with self.lock:
      start = self.events[0][0] if self.events else self.sequence + 1
      events = [(seq, name, data) for seq, name, data in self.events if seq > cursor][:4]
      return {"events": [{"seq": seq, "stream": name, "data_b64": base64.b64encode(data).decode()} for seq, name, data in events],
        "next_cursor": events[-1][0] if events else max(cursor, self.sequence), "dropped": cursor + 1 < start,
        "has_more": bool(events and events[-1][0] < self.sequence), "complete": self.complete()}

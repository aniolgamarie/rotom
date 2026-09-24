"""平台无关的持久进程包含关系；身份观察由各平台实现。"""

import json
import os
from pathlib import Path

from .activity import digest
from .deployment import json_bytes
from .pi_catalog import validate
from .schema import ConfigError
from .storage import Conflict, Tree


class TrackedProcesses:
  def __init__(self, record_root):
    self.record_root = Path(record_root)

  def _path(self, expected):
    return digest({key: value for key, value in expected.items() if key != "ppid"}) + ".json"

  def register(self, expected, *, foreground=True, child_groups=False):
    if type(child_groups) is not bool or child_groups and expected["platform"] != "linux":
      raise Conflict("平台不支持独立子进程组登记")
    if not foreground or expected["pid"] != expected["pgid"] or expected["uid"] != os.geteuid() or self.observe(expected) != "alive":
      raise Conflict("平台执行必须为身份已确认的独立前台进程组")
    record = {"schema_version": 1, "leader": expected, "members": {str(expected["pid"]): expected}, "escaped": False}
    if child_groups: record.update(schema_version=2, child_groups=True)
    with Tree(self.record_root, create=True) as tree:
      old = tree.read(self._path(expected))
      if old is not None:
        previous = self._record(expected)
        if previous["leader"] != expected or previous.get("child_groups", False) != child_groups:
          raise Conflict("平台监督身份冲突")
        return
      tree.write_state(self._path(expected), json_bytes(record))
    self._refresh(expected)

  def _record(self, expected):
    with Tree(self.record_root) as tree:
      raw = tree.read(self._path(expected))
    if raw is None or raw[1] != 0o600:
      raise Conflict("平台执行缺少持久包含关系证明")
    try:
      record = json.loads(raw[0])
      fields = {"schema_version", "leader", "members", "escaped"}
      if record.get("schema_version") == 2:
        fields.add("child_groups")
        if record.get("child_groups") is not True or expected["platform"] != "linux": raise ValueError()
      if set(record) != fields or type(record["schema_version"]) is not int or record["schema_version"] not in (1, 2) or record["leader"] != expected or type(record["escaped"]) is not bool:
        raise ValueError()
      if not isinstance(record["members"], dict) or record["members"].get(str(expected["pid"])) != expected: raise ValueError()
      for pid, member in record["members"].items():
        validate("process-identity", member)
        if str(member["pid"]) != pid or member["uid"] != expected["uid"]:
          raise ValueError()
    except Exception:
      raise Conflict("平台执行包含关系记录损坏") from None
    return record

  def _refresh(self, expected):
    record, current = self._record(expected), self._scan()
    before = json_bytes(record)
    changed = True
    while changed:
      changed = False
      for pid, child in current.items():
        if pid in record["members"]:
          continue
        parent = record["members"].get(str(child["ppid"]))
        if parent is not None and self.observe(parent) == "alive":
          if child["uid"] != expected["uid"]:
            record["escaped"] = True
          else:
            try: validate("process-identity", child)
            except ConfigError: record["escaped"] = True
            else:
              record["members"][pid] = child
              changed = True
    groups = {expected["pgid"]}
    if record.get("child_groups"):
      groups.update(member["pgid"] for member in record["members"].values() if member["pid"] == member["pgid"])
    for pid, child in current.items():
      if child["pgid"] in groups and pid not in record["members"]:
        record["escaped"] = True
    for pid, child in record["members"].items():
      observed = current.get(pid)
      if observed and (observed["pgid"] not in groups or any(observed.get(key) != child[key] for key in child if key != "ppid")):
        record["escaped"] = True
    if before != json_bytes(record):
      with Tree(self.record_root) as tree:
        tree.write_state(self._path(expected), json_bytes(record))
    return record

  def termination_status(self, expected):
    try:
      record = self._refresh(expected)
      if record["escaped"]:
        return "unknown"
      statuses = [self.observe(member) for member in record["members"].values()]
      if "unknown" in statuses:
        return "unknown"
      return "terminated" if all(status == "dead" for status in statuses) else "active"
    except (OSError, ValueError, Conflict, ConfigError):
      return "unknown"

"""Pi 公开扩展辅助观察的只读投影；历史选择不代表当前加载完成。"""
import re

from . import run_owners
from .dsh_sessions import scope_key
from .pi_session_guard import _read, _PROTOCOL, _guard_record
from .sessions import KnownSession, SessionRef, SessionError
from .storage import Tree


def from_records(workspace, records):
  if workspace.agent != "pi":
    return ()
  result = []
  try:
    if workspace.profile != workspace.binding["profile"]:
      raise ValueError()
    for identifier, record in records.items():
      if record.get("schema_version") != 2 or record["agent"] != "pi":
        continue
      run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)._validate_record(
        identifier + ".json", record)
      with Tree(workspace.state_root / "pi-session-observations") as tree:
        observed = _read(tree, identifier + ".json")
      if observed is None:
        continue
      value = observed[0]
      with Tree(workspace.state_root / "pi-session-guards") as tree:
        marker = _read(tree, identifier + ".json")
      if (type(value) is not dict or set(value) != {"schema_version", "protocol", "run_id",
          "manager_identity", "host_identity", "session_id", "cwd", "file", "observed_at_ns"}
          or type(value["schema_version"]) is not int or value["schema_version"] != 1
          or value["protocol"] != _PROTOCOL or value["run_id"] != identifier
          or run_owners._encode(value["manager_identity"]) != run_owners._encode(record["manager_identity"])
          or record["host_identity"] is None
          or run_owners._encode(value["host_identity"]) != run_owners._encode(record["host_identity"])
          or type(value["session_id"]) is not str
          or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value["session_id"]) is None
          or type(value["observed_at_ns"]) is not int or value["observed_at_ns"] <= 0
          or marker is None or type(marker[0]) is not dict
          or type(marker[0].get("source_identity")) is not str
          or re.fullmatch(r"[0-9a-f]{64}", marker[0]["source_identity"]) is None
          or run_owners._encode(marker[0]) != run_owners._encode(_guard_record(record, marker[0]["source_identity"]))):
        raise ValueError()
      home = workspace.instance / "pi-home"
      if record["native_home_ref"]["kind"] != "pi-home" or record["native_home_ref"]["path"] != str(home):
        raise ValueError()
      if value["file"] is not None:
        file = run_owners._absolute(value["file"])
        if file.parent != home / "sessions" or file.suffix != ".jsonl":
          raise ValueError()
      run_owners._absolute(value["cwd"])
      result.append(KnownSession(
        ref=SessionRef("pi", "managed", run_owners.native_home_key(record["native_home_ref"]), value["session_id"]),
        scope=scope_key(workspace.binding), profile=workspace.profile, cwd=value["cwd"],
        cwd_status="historical", confirmation="historical", observed_at_ns=value["observed_at_ns"], run_id=identifier))
  except Exception:
    raise SessionError(4, "pi_session_observation_unconfirmed") from None
  return tuple(result)

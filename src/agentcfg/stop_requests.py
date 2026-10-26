"""停止请求纯 codec；JSON 不是批准、句柄或派发许可。

仅保存明确身份和同 boot 单调期限数据，不核实来源、时效或任何现场状态。
"""
import json
import re

from . import run_owners
from .storage import Conflict


_ERROR = "停止请求数据格式或长度无效"
_MAX_BYTES = 16 * 1024
_FIELDS = {"schema_version", "kind", "action", "request_id", "batch_id", "run_id", "plan_id",
  "manager_identity", "host_identity", "deadline_ns"}


def _normalize(value):
  if type(value) is not dict or set(value) != _FIELDS:
    raise ValueError()
  run_owners._no_float(value)
  if (type(value["schema_version"]) is not int or value["schema_version"] != 1
      or type(value["kind"]) is not str or value["kind"] != "stop-request"
      or type(value["action"]) is not str or value["action"] != "graceful-stop"
      or type(value["plan_id"]) is not str or re.fullmatch(r"[0-9a-f]{64}", value["plan_id"]) is None
      or type(value["deadline_ns"]) is not int or not 1 <= value["deadline_ns"] <= 2**63 - 1):
    raise ValueError()
  for name in ("request_id", "batch_id", "run_id"):
    run_owners._run_id(value[name])
  normalized = dict(value)
  for name in ("manager_identity", "host_identity"):
    identity = value[name]
    if type(identity) is not dict or set(identity) != {"pid", "birth_id"}:
      raise ValueError()
    normalized[name] = run_owners._manager(identity)
  if normalized["manager_identity"]["pid"] == normalized["host_identity"]["pid"]:
    raise ValueError()
  return normalized


def encode_stop_request(value) -> bytes:
  try:
    encoded = run_owners._encode(_normalize(value))
    if len(encoded) > _MAX_BYTES:
      raise ValueError()
    return encoded
  except Exception:
    raise Conflict(_ERROR) from None


def decode_stop_request(raw) -> dict:
  try:
    if type(raw) is not bytes or len(raw) > _MAX_BYTES:
      raise ValueError()
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=run_owners._pairs,
      parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant)
    normalized = _normalize(value)
    if len(run_owners._encode(normalized)) > _MAX_BYTES:
      raise ValueError()
    return normalized
  except Exception:
    raise Conflict(_ERROR) from None

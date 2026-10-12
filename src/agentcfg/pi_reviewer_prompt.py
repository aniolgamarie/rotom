"""私有可信编译器接缝；只投影封闭能力事实，不读取正文或评估用户意图。"""

import json
import re

from .schema import ConfigError


SYSTEM_PROMPT = ("Rotom capability review protocol v1. Facts describe the complete classified capability boundary only; "
  "private content and user intent have not been evaluated. Never infer authorization from aliases. "
  "Return exactly schema_version, request_id, operation_digest, context_digest, reviewer_identity, decision, reason_code. "
  "Echo schema_version 1 and all binding aliases. Decision allow uses authorized-in-scope; ask uses ambiguous-intent, "
  "unverifiable-input or needs-human; deny uses outside-user-scope, destructive-change or untrusted-authorization. "
  "Insufficient facts require ask, never allow.")
MAX_PROMPT_BYTES = 32768
FACT_KEYS = ("operation_kind", "action", "target_class", "access_effect", "network_class", "content_evaluated")
EFFECTS = {"read": "read", "ls": "read", "find": "read", "grep": "read",
  "write": "write", "edit": "read-and-write", "rename": "read-and-write"}


def _invalid():
  raise ConfigError("PI_RISK_REVIEW_PROJECTION_INVALID")


def _closed(value, keys):
  # 不执行外来映射、代理或值对象的方法。
  if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != set(keys): _invalid()


def facts_from_projection(value, prepared):
  _closed(value, ("schema_version", "operation_id", "operation_digest", "facts", "eligible", "source_binding"))
  if type(value["schema_version"]) is not int or value["schema_version"] != 1: _invalid()
  for key in ("operation_id", "operation_digest"):
    if type(value[key]) is not str or value[key] != prepared[key]: _invalid()
  if type(value["eligible"]) is not bool: _invalid()
  source = value["source_binding"]
  _closed(source, ("kind", "identity"))
  if (type(source["kind"]) is not str or source["kind"] != "selected-inputs-v1" or
      type(source["identity"]) is not str or re.fullmatch(r"[0-9a-f]{64}", source["identity"]) is None): _invalid()
  facts = value["facts"]
  _closed(facts, FACT_KEYS)
  for key in FACT_KEYS[:-1]:
    if type(facts[key]) is not str: _invalid()
  if facts["content_evaluated"] is not False: _invalid()
  resolved = prepared["resolution"]
  action = facts["action"]
  if (facts["operation_kind"] != "file" or resolved["kind"] != "file" or
      action not in EFFECTS or action != resolved["tool_name"] or
      facts["access_effect"] != EFFECTS[action] or facts["network_class"] != "none" or
      resolved["network"] != "deny" or facts["target_class"] != "selected-workspace-object" or
      EFFECTS[action] in ("read", "read-and-write") and not resolved["read_roots"] or
      EFFECTS[action] in ("write", "read-and-write") and not resolved["write_roots"]):
    return None
  # 来源身份只在原ticket内比较，绝不作为模型请求字段。
  return {"facts": dict.copy(facts), "source_binding": dict.copy(source)} if value["eligible"] else None


def prompt_payload(binding, facts):
  user = json.dumps({"schema_version": 1, "binding": binding, "facts": facts},
    separators=(",", ":"), ensure_ascii=True, allow_nan=False)
  if len(SYSTEM_PROMPT.encode("utf8")) + len(user.encode("utf8")) > MAX_PROMPT_BYTES: _invalid()
  return {"system_prompt": SYSTEM_PROMPT, "user_prompt": user, "binding": dict.copy(binding)}

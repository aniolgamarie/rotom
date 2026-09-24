"""原生凭据叶子只允许声明的环境引用；校验先于差异与备份。"""

import re

from .storage import Conflict


def reference_guard(tokens):
  if not isinstance(tokens, (tuple, list)):
    raise Conflict("原生引用保护声明无效")
  from .omp_env import is_generated_name
  kinds = ({"environment-reference"} if all(isinstance(token, str) and re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", token) for token in tokens)
           else {"omp-env-name"} if all(is_generated_name(token) for token in tokens) else set())
  if (not tokens or not kinds
      or len(set(tokens)) != len(tokens)):
    raise Conflict("原生引用保护声明无效")
  return {"kind": next(iter(kinds)), "tokens": list(tokens)}


def validate_guard(guard):
  if guard is None:
    return None
  if not isinstance(guard, dict) or set(guard) != {"kind", "tokens"} or guard["kind"] not in ("environment-reference", "omp-env-name"):
    raise Conflict("原生引用保护声明无效")
  checked = reference_guard(guard["tokens"])
  if checked["kind"] != guard["kind"]:
    raise Conflict("原生引用保护声明无效")
  return checked


def validate_projection(value, guard):
  checked = validate_guard(guard)
  if checked is None:
    return
  if (not isinstance(value, dict) or type(value.get("present")) is not bool
      or set(value) != ({"present", "value"} if value["present"] else {"present"})):
    raise Conflict("受管引用投影格式无效")
  if value["present"] and (not isinstance(value["value"], str) or value["value"] not in checked["tokens"]):
    raise Conflict("受管认证字段不是已声明引用，不能生成差异或备份")


def transition_guard(before, after):
  first, second = validate_guard(before), validate_guard(after)
  if first and second and first["kind"] != second["kind"]:
    raise Conflict("原生引用保护类型不能转换")
  tokens = list(dict.fromkeys((first or {}).get("tokens", []) + (second or {}).get("tokens", [])))
  return reference_guard(tokens) if tokens else None


def validate_saved_state(state):
  for current in (state.get("current"), (state.get("previous") or {}).get("current")):
    if current:
      for item in current["items"].values():
        validate_item_guard(item, item["baseline"])
        validate_projection(item["baseline"], item.get("guard"))
  for change in (state.get("previous") or {}).get("changes", []):
    validate_change(change)


def validate_change(change):
  validate_item_guard(change["item"], change["after"])
  if (is_pi_credential(change["item"]) or is_omp_credential(change["item"])) and change["before"].get("present") and not change.get("before_guard"):
    raise Conflict("历史认证引用缺少保护声明")
  validate_projection(change["before"], change.get("before_guard"))
  validate_projection(change["after"], change["item"].get("guard"))


def is_pi_credential(item):
  selector = item.get("selector")
  return item.get("path") == "pi-home/models.json" and isinstance(selector, str) and selector.startswith("/providers/") and selector.endswith("/apiKey")


def is_omp_credential(item):
  selector = item.get("selector")
  path = item.get("path")
  return isinstance(selector, str) and ((isinstance(path, str) and path.endswith("/models.yml") and selector.endswith("/apiKey"))
    or (isinstance(path, str) and path.endswith("/mcp.json") and
        (re.fullmatch(r"/mcpServers/[^/]+/env/[^/]+", selector) is not None or selector.endswith("/headers/Authorization"))))


def validate_item_guard(item, value):
  guard = item.get("guard")
  checked = validate_guard(guard) if guard is not None else None
  if checked is not None and checked["kind"] == "omp-env-name" and not (is_omp_credential(item) or is_pi_credential(item)):
    raise Conflict("OMP环境引用只能保护登记的认证叶子")
  if is_omp_credential(item) and checked is not None and checked["kind"] != "omp-env-name":
    raise Conflict("OMP认证叶子必须使用omp-env-name保护")
  if is_pi_credential(item) and checked is not None and checked["kind"] != "environment-reference":
    raise Conflict("Pi认证叶子必须使用environment-reference保护")
  # 无保护的旧记录不得通过回滚重新引入原生明文凭据。
  if (is_pi_credential(item) or is_omp_credential(item)) and value.get("present") and item.get("guard") is None:
    raise Conflict("历史认证引用缺少保护声明")


def reverse_change(change):
  item = {k: v for k, v in change["item"].items() if k != "guard"}
  if change.get("before_guard") is not None:
    item["guard"] = change["before_guard"]
  result = {**change, "item": item, "before": change["after"], "after": change["before"]}
  if change["item"].get("guard") is not None:
    result["before_guard"] = change["item"]["guard"]
  else:
    result.pop("before_guard", None)
  return result

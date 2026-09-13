"""DSH 已审核标量 JS 的惰性 YAML 编解码；从不执行表达式。"""

from dataclasses import dataclass
import re

import yaml

from .storage import Conflict


@dataclass(frozen=True)
class JS:
  expression: str


_EXPRESSIONS = frozenset({
  "process.env.DSH_TUI_PRESET ?? undefined",
  "process.env.DSH_TUI_WORKSPACE_TARGET ?? undefined",
  "process.env.DSH_TUI_RESUME_SESSION ?? undefined",
})


def check_expression(expression):
  return expression in _EXPRESSIONS or re.fullmatch(r"process\.env\.AGENTCFG_MCP_[A-F0-9]{16}", expression) is not None


class NativeLoader(yaml.SafeLoader):
  pass


class NativeDumper(yaml.SafeDumper):
  pass


def _js(loader, node):
  if not isinstance(node, yaml.ScalarNode):
    raise Conflict("不支持非标量可执行 YAML")
  expression = loader.construct_scalar(node)
  if not check_expression(expression):
    raise Conflict("原生表达式不在适配器白名单")
  return JS(expression)


NativeLoader.add_constructor("tag:yaml.org,2002:js", _js)
NativeDumper.add_representer(JS, lambda dumper, value: dumper.represent_scalar("tag:yaml.org,2002:js", value.expression))


def _walk(value, path=()):
  if isinstance(value, JS):
    # 只有明确字段可使用表达式；同一表达式放在别的节点也拒绝。
    field = path[-1] if path else None
    known = {"preset": "process.env.DSH_TUI_PRESET ?? undefined",
             "workspace": "process.env.DSH_TUI_WORKSPACE_TARGET ?? undefined",
             "sessionId": "process.env.DSH_TUI_RESUME_SESSION ?? undefined"}
    if field in known and value.expression == known[field]:
      return
    if "headers" in path or "env" in path:
      if re.fullmatch(r"process\.env\.AGENTCFG_MCP_[A-F0-9]{16}", value.expression):
        return
    raise Conflict("原生 JS 位于非白名单字段")
  if isinstance(value, dict):
    if "__jsExpr" in value:
      raise Conflict("禁止未标记的原生可执行载体")
    for key, child in value.items():
      _walk(child, path + (key,))
  elif isinstance(value, list):
    for i, child in enumerate(value):
      _walk(child, path + (i,))


def load(data):
  try:
    value = yaml.load(data, Loader=NativeLoader)
    _walk(value)
    return value
  except Exception:
    raise Conflict("原生 YAML 无效或包含未允许的表达式") from None


def dump(value):
  _walk(value)
  return yaml.dump(value, Dumper=NativeDumper, allow_unicode=True, sort_keys=False).encode()


def replace_config(rows, row_id, changes):
  """完整 config 合成；这不是声明 Cordis 能任意深合并。"""
  from copy import deepcopy
  matches = [row for row in rows if row.get("id") == row_id]
  if len(matches) != 1 or not isinstance(matches[0].get("config"), dict):
    raise Conflict("待覆盖原生行缺失、重复或不是数据对象")
  row = deepcopy(matches[0])
  row["config"].update(deepcopy(changes))
  _walk(row)
  return row

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
  "ctx.ssh.ptcLaunch",
})
_MCP_ARGS_PREFIX = "JSON.parse(process.env.AGENTCFG_MCP_ENV_ARGS).concat("


def mcp_arguments_expression(expression):
  import json
  if not expression.startswith(_MCP_ARGS_PREFIX) or not expression.endswith(")"):
    return False
  try:
    arguments = json.loads(expression[len(_MCP_ARGS_PREFIX):-1])
    return (isinstance(arguments, list) and bool(arguments) and all(isinstance(item, str) and "\0" not in item for item in arguments)
      and bool(arguments[0]) and "=" not in arguments[0])
  except (ValueError, TypeError):
    return False


def check_expression(expression):
  return (expression in _EXPRESSIONS or mcp_arguments_expression(expression)
    or re.fullmatch(r"process\.env\.AGENTCFG_MCP_[A-F0-9]{16}", expression) is not None)


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
    if field == "launch" and value.expression == "ctx.ssh.ptcLaunch":
      return
    if field == "args" and mcp_arguments_expression(value.expression):
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


class CordisLoader(yaml.SafeLoader):
  """原生用户层只解析数据；未知标量 JS 原样保存，从不执行。"""


def _cordis_mapping(loader, node):
  result = {}
  for key_node, value_node in node.value:
    key = loader.construct_object(key_node, deep=True)
    if not isinstance(key, str) or not key or key in result:
      raise Conflict("Cordis 字段名无效或重复")
    result[key] = loader.construct_object(value_node, deep=True)
  return result


def _cordis_js(loader, node):
  if not isinstance(node, yaml.ScalarNode):
    raise Conflict("Cordis JS 必须为未执行的标量")
  return JS(loader.construct_scalar(node))


CordisLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _cordis_mapping)
CordisLoader.add_constructor("tag:yaml.org,2002:js", _cordis_js)


class CordisDocument(dict):
  """按 id 暴露字段，另外保留非字段行和原生顺序。"""

  def __init__(self):
    super().__init__()
    self.rows = []


def load_cordis(data):
  rows = yaml.load(data, Loader=CordisLoader)
  if rows is None:
    rows = []
  if not isinstance(rows, list):
    raise Conflict("Cordis patch 必须为行列表")
  document = CordisDocument()
  for row in rows:
    if not isinstance(row, dict):
      raise Conflict("Cordis patch 行必须为对象")
    if "id" in row:
      identity = row["id"]
      if not isinstance(identity, str) or not identity or identity in document or "insert" in row:
        raise Conflict("Cordis patch id 无效或重复")
      document[identity] = {key: value for key, value in row.items() if key != "id"}
      document.rows.append(identity)
    elif set(row) == {"insert"} and isinstance(row["insert"], list) and all(isinstance(item, dict) for item in row["insert"]):
      document.rows.append(row)
    else:
      raise Conflict("Cordis patch 行没有合法 id 或 insert")
  return document


def dump_cordis(document):
  rows = []
  emitted = set()
  for row in getattr(document, "rows", []):
    if isinstance(row, str):
      if row not in document:
        continue
      rows.append(_cordis_row(row, document[row]))
      emitted.add(row)
    else:
      rows.append(row)
  for identity, row in document.items():
    if identity not in emitted:
      rows.append(_cordis_row(identity, row))
  content = yaml.dump(rows, Dumper=NativeDumper, allow_unicode=True, sort_keys=False).encode()
  # 编码后的行也通过同一结构准入，拒绝伪造或损坏的映射。
  load_cordis(content)
  return content


def _cordis_row(identity, row):
  if not isinstance(identity, str) or not identity or not isinstance(row, dict) or row.get("id", identity) != identity:
    raise Conflict("Cordis 字段映射 id 无效")
  return {"id": identity, **row}

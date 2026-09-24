"""校验隔离计算产物；只有父侧权限与提交检查通过，结果和 anchors 才能进入会话。"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat

from jsonschema import Draft202012Validator

from .paths import _absolute_directory, relative_path
from .pi_readseek_mutations import commit_changes
from .pi_readseek_snapshot import verify_snapshot_source
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree


TOOLS = {"readSeek_" + name for name in ("edit", "grep", "search", "refs", "rename", "def", "digest", "view", "write")}


def validate_request(contracts, tool, params):
  """使用随受信运行包密封的原工具 schema，不接受模型提供 schema。"""
  if tool not in TOOLS or not isinstance(params, dict): raise ConfigError("readseek-tool-request")
  closed(contracts, ("schema_version", "tools"))
  definitions = contracts["tools"]
  if (contracts["schema_version"] != 1 or not isinstance(definitions, list) or len(definitions) != len(TOOLS)
      or {row.get("name") for row in definitions if isinstance(row, dict)} != TOOLS):
    raise ConfigError("readseek-tool-contracts")
  schema = next(row["parameters"] for row in definitions if row["name"] == tool)
  if schema.get("additionalProperties") is not False: raise ConfigError("readseek-tool-contracts")
  if any(Draft202012Validator(schema).iter_errors(params)): raise ConfigError("readseek-tool-arguments")
  try: encoded = json.dumps(params, ensure_ascii=False, allow_nan=False).encode()
  except (ValueError, TypeError, UnicodeError): raise ConfigError("readseek-tool-arguments") from None
  if len(encoded) > 1024 * 1024: raise ConfigError("readseek-tool-arguments-limit")
  return deepcopy(params)


def project_path(root, raw):
  if (not isinstance(raw, str) or not raw or raw.startswith("~") or "\\" in raw
      or any(ord(char) < 32 or ord(char) == 127 for char in raw)):
    raise ConfigError("readseek-path")
  root = Path(root)
  value = Path(raw)
  if ".." in value.parts: raise Conflict("READSEEK_PATH_SCOPE")
  value = value if value.is_absolute() else root / value
  if not value.is_relative_to(root) or ".git" in value.relative_to(root).parts:
    raise Conflict("READSEEK_PATH_SCOPE")
  return value


def worker_parameters(snapshot, params):
  result = deepcopy(params)
  if "path" in result:
    path = project_path(snapshot["source_root"], result["path"])
    result["path"] = str(Path(snapshot["snapshot_root"]) / path.relative_to(snapshot["source_root"]))
  return result


def ensure_mapping_unambiguous(snapshot, params):
  """只替换不可出现在源正文/用户输入中的完整随机副本前缀，避免改写程序文字。"""
  prefix = snapshot["snapshot_root"].encode()
  if prefix in json.dumps(params, ensure_ascii=False).encode(): raise Conflict("READSEEK_PATH_MAPPING_COLLISION")
  with Tree(Path(snapshot["snapshot_root"])) as tree:
    for row in snapshot["entries"]:
      raw = tree.read(row["path"], max_bytes=max(row["size"], 1))
      if raw is None or len(raw[0]) != row["size"] or hashlib.sha256(raw[0]).hexdigest() != row["sha256"]:
        raise Conflict("READSEEK_SNAPSHOT_CHANGED")
      if prefix in raw[0]: raise Conflict("READSEEK_PATH_MAPPING_COLLISION")


def _map_result(value, snapshot, depth=0):
  if depth > 64: raise Conflict("READSEEK_RESULT_LIMIT")
  if isinstance(value, str): return value.replace(snapshot["snapshot_root"], snapshot["source_root"])
  if isinstance(value, list): return [_map_result(item, snapshot, depth + 1) for item in value]
  if isinstance(value, dict):
    return {key: _map_result(item, snapshot, depth + 1) for key, item in value.items()}
  if value is None or type(value) in (int, float, bool): return value
  raise Conflict("READSEEK_RESULT_INVALID")


def _computed_files(snapshot, max_files=10000, max_bytes=128 * 1024 * 1024):
  """调用方须先暂停/终止 worker，或将输出复制到其不可再写的私人目录。"""
  paths, visited = [], 0
  def visit(fd, prefix):
    nonlocal visited
    visited += 1
    if visited > max_files * 4 + 1000: raise Conflict("READSEEK_RESULT_LIMIT")
    for name in sorted(os.listdir(fd)):
      path = name if not prefix else prefix + "/" + name
      relative_path(path)
      if name in (".git", ".readseek"): raise Conflict("READSEEK_UNEXPECTED_FILE")
      info = os.stat(name, dir_fd=fd, follow_symlinks=False)
      if stat.S_ISDIR(info.st_mode):
        child = os.open(name, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try: visit(child, path)
        finally: os.close(child)
      elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        paths.append(path)
        if len(paths) > max_files: raise Conflict("READSEEK_RESULT_LIMIT")
      else: raise Conflict("READSEEK_UNEXPECTED_FILE")
  with _absolute_directory(Path(snapshot["snapshot_root"])) as fd: visit(fd, "")
  result, total = {}, 0
  with Tree(Path(snapshot["snapshot_root"])) as tree:
    for path in paths:
      raw = tree.read(path, max_bytes=16 * 1024 * 1024)
      if raw is None: raise Conflict("READSEEK_SNAPSHOT_CHANGED")
      total += len(raw[0])
      if total > max_bytes: raise Conflict("READSEEK_RESULT_LIMIT")
      result[path] = raw[0]
  return result


def accept_result(files, permission_tool, snapshot, tool, params, output, *, journal_root, operation_id, anchors, read_operation="read"):
  """租约仍由调用方持有；本函数没有释放租约或报告物理终止的权限。"""
  if tool not in TOOLS: raise ConfigError("readseek-tool-request")
  closed(output, ("schema_version", "operation_id", "tool", "snapshot_digest", "result", "anchor_events", "computed_entries"))
  if (output["schema_version"] != 1 or output["operation_id"] != operation_id or output["tool"] != tool
      or output["snapshot_digest"] != snapshot["snapshot_digest"]): raise Conflict("READSEEK_RESULT_IDENTITY")
  try: encoded = json.dumps(output, allow_nan=False).encode()
  except (TypeError, ValueError, UnicodeError): raise Conflict("READSEEK_RESULT_INVALID") from None
  if len(encoded) > 32 * 1024 * 1024: raise Conflict("READSEEK_RESULT_LIMIT")
  result = output["result"]
  if (not isinstance(result, dict) or not isinstance(result.get("content"), list)
      or "isError" in result and type(result["isError"]) is not bool): raise Conflict("READSEEK_RESULT_INVALID")
  verify_snapshot_source(files, permission_tool, snapshot, operation=read_operation)
  computed = _computed_files(snapshot)
  expected_entries = [{"path": path, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    for path, body in sorted(computed.items())]
  if output["computed_entries"] != expected_entries: raise Conflict("READSEEK_COMPUTED_IDENTITY")
  original = {row["path"]: row for row in snapshot["entries"]}
  if original.keys() - computed.keys(): raise Conflict("READSEEK_UNEXPECTED_DELETION")
  changes = []
  write = tool in ("readSeek_edit", "readSeek_write") or tool == "readSeek_rename" and params.get("apply", True)
  workspace = tool == "readSeek_rename" and params.get("workspace", False)
  if workspace and write and not snapshot["scope_complete"]: raise Conflict("READSEEK_INCOMPLETE_WORKSPACE")
  requested = project_path(snapshot["source_root"], params["path"]) if write else None
  for name, body in computed.items():
    row = original.get(name)
    if row and hashlib.sha256(body).hexdigest() == row["sha256"]: continue
    path = str(Path(snapshot["source_root"]) / name)
    if (not write or result.get("isError") or not workspace and Path(path) != requested
        or tool != "readSeek_write" and row is None): raise Conflict("READSEEK_UNEXPECTED_MUTATION")
    before = files.read(permission_tool, path, operation=read_operation) if row else None
    if row and hashlib.sha256(before).hexdigest() != row["sha256"]: raise Conflict("READSEEK_SOURCE_CHANGED")
    changes.append({"path": path, "before": before, "after": body})
  events = output["anchor_events"]
  if not isinstance(events, list) or len(events) > 20000: raise Conflict("READSEEK_ANCHOR_EVENT")
  next_anchors = dict(anchors)
  for change in changes: next_anchors.pop(change["path"], None)
  for event in events:
    closed(event, ("action", "path"))
    if event["action"] == "clear" and event["path"] is None:
      next_anchors.clear(); continue
    if event["action"] not in ("mark", "forget"): raise Conflict("READSEEK_ANCHOR_EVENT")
    path = project_path(snapshot["snapshot_root"], event["path"])
    name = path.relative_to(snapshot["snapshot_root"]).as_posix()
    public = str(Path(snapshot["source_root"]) / name)
    if event["action"] == "forget": next_anchors.pop(public, None)
    elif name not in computed: raise Conflict("READSEEK_ANCHOR_EVENT")
    else: next_anchors[public] = hashlib.sha256(computed[name]).hexdigest()
  mapped = _map_result(result, snapshot)
  if not snapshot["scope_complete"]:
    mapped["content"].append({"type": "text", "text": "[agentcfg: search/read scope is incomplete; permission-excluded files were not inspected.]"})
    details = mapped.get("details")
    mapped["details"] = {**(details if isinstance(details, dict) else {}),
      "agentcfgReadseek": {"scopeComplete": False, "skipped": snapshot["skipped"]}}
  # 所有结果/锚点检查必须早于第一份业务写入。
  receipt = commit_changes(files, permission_tool, changes, journal_root, operation_id) if changes else None
  files.policy.current()
  return {"result": mapped, "anchors": next_anchors, "mutation": receipt,
    "scope_complete": snapshot["scope_complete"], "snapshot_digest": snapshot["snapshot_digest"]}


def fresh_anchors(snapshot, anchors):
  """仅延续仍匹配当前副本的 anchors；源发生变化时自然失效。"""
  return [str(Path(snapshot["snapshot_root"]) / row["path"]) for row in snapshot["entries"]
    if anchors.get(str(Path(snapshot["source_root"]) / row["path"])) == row["sha256"]]

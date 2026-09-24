"""显式OMP agent目录只读盘点；候选资源始终需要人工审阅。"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

import yaml

from .deployment import json_bytes
from .schema import AdapterSchemas, ConfigError, validate_document
from .storage import Conflict, Tree, ensure_private
from .paths import relative_path


SENSITIVE_KEY = re.compile(r"api.?key|secret|password|token|authorization|credential|cookie|auth|trust", re.I)
SENSITIVE_TEXT = re.compile(rb"SECRET[_ -]|-----BEGIN .*PRIVATE KEY|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{8,}|(?:password|api[_-]?key|token|authorization)\s*[:=]\s*[^\s]", re.I)
RESOURCE_KINDS = {"skills", "prompts", "themes", "rules"}
RUNTIME_NAMES = {"auth.db", "auth.json", "auth.db-wal", "auth.db-shm", "sessions", "session", "logs", "cache", "trust", "backups", ".env", ".git"}


def _runtime_name(name):
  return (name in RUNTIME_NAMES or name.startswith(".env") or name.endswith(".bak")
    or bool(re.search(r"\.(?:db|sqlite3?)(?:-wal|-shm|-journal)?$", name, re.I)))


def _sha(raw):
  return hashlib.sha256(raw).hexdigest()


def _document(tree, name):
  raw = tree.read(name)
  if raw is None:
    return {}
  try:
    if len(raw[0]) > 4 * 1024 * 1024:
      raise ValueError()
    result = json.loads(raw[0]) if name.endswith(".json") else yaml.safe_load(raw[0])
    if result is None:
      return {}
    if not isinstance(result, dict):
      raise ValueError()
    return result
  except Exception:
    raise ConfigError("omp-inventory-source-format") from None


def _secrets(value, found, sensitive=False):
  if isinstance(value, dict):
    for key, child in value.items():
      _secrets(child, found, sensitive or bool(SENSITIVE_KEY.search(str(key))))
  elif isinstance(value, list):
    for child in value:
      _secrets(child, found, sensitive)
  elif sensitive and isinstance(value, str) and value:
    found.add(value.encode())


def _sensitive(raw, known):
  return bool(SENSITIVE_TEXT.search(raw)) or any(value in raw for value in known)


def _children(tree, directory=""):
  if not directory:
    return sorted(os.listdir(tree.fd))
  with tree.parent(directory + "/_") as (fd, _):
    return sorted(os.listdir(fd))


def _candidate(tree, path):
  """完整读取一个明确资源包，拒绝任何链接/特殊文件；不执行。"""
  result = []
  def visit(name):
    relative_path(name)
    if any(_runtime_name(part) for part in Path(name).parts):
      raise Conflict("OMP候选包不能包含运行数据或秘密文件")
    with tree.parent(name) as (parent, leaf):
      info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
    if stat.S_ISDIR(info.st_mode):
      for child in _children(tree, name):
        visit(name + "/" + child)
    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
      raw = tree.read(name)
      if len(raw[0]) > 4 * 1024 * 1024:
        raise Conflict("OMP候选资源过大，需单独审阅")
      result.append({"path": name, "content": raw[0], "executable": bool(raw[1] & 0o111)})
    else:
      raise Conflict("OMP候选资源不得包含链接或特殊文件")
  visit(path)
  return result


def build_inventory(source, *, adapter, data):
  source = Path(source)
  if not source.is_absolute():
    raise ConfigError("omp-inventory-source-not-absolute")
  if source.is_symlink():
    raise Conflict("OMP盘点来源不得为链接")
  items, resources, captured, known = [], [], {}, set()
  def item(kind, path, disposition, reason, target="", review=False, digest=None, executable=False):
    # 来自混合文档的未知字段名也不能携带已知秘密。
    public_path = "redacted-source-location" if _sensitive(path.encode(), known) else path
    items.append({"kind": kind, "path": public_path, "disposition": disposition, "reason": reason,
      "target": target, "review_required": review, "sha256": digest, "executable": executable})
  with Tree(source, private=False) as tree:
    if tree.fd is None:
      raise ConfigError("omp-inventory-source-missing")
    documents = {name: _document(tree, name) for name in ("config.yml", "models.yml", "keybindings.yml", "mcp.json", ".mcp.json")}
    for value in documents.values():
      _secrets(value, known)
    # 只尝试已经选中且可唯一反查的主题/角色/动作，其他内容逐项处置而不复制原值。
    for filename, document in documents.items():
      for key, value in document.items():
        if filename == "config.yml" and key in {"theme", "modelRoles"} and isinstance(value, dict):
          for child, selected in value.items():
            path = filename + "/" + str(key) + "/" + str(child)
            try:
              if not isinstance(selected, str) or _sensitive(selected.encode(), known):
                raise ConfigError("omp-inventory-sensitive-preference")
              proposal = adapter.capture_configuration({key: {child: selected}}, data)
              if not proposal:
                raise ConfigError("omp-inventory-unmapped-preference")
              _merge(captured, proposal)
              item("setting", path, "纳入", "declared-nonsecret-preference", "local-overrides.toml", True)
            except ConfigError:
              item("setting", path, "替代", "explicit-public-declaration-required", review=True)
        elif filename == "keybindings.yml":
          try:
            if _sensitive(json_bytes(value), known):
              raise ConfigError("omp-inventory-sensitive-preference")
            proposal = adapter.capture_configuration({"keybindings": {key: value}}, data)
            if not proposal:
              raise ConfigError("omp-inventory-unmapped-preference")
            _merge(captured, proposal)
            item("setting", filename + "/" + str(key), "纳入", "declared-nonsecret-preference", "local-overrides.toml", True)
          except ConfigError:
            item("setting", filename + "/" + str(key), "排除", "undeclared-or-sensitive-preference")
        else:
          sensitive = bool(SENSITIVE_KEY.search(str(key)))
          item("setting", filename + "/" + str(key), "排除" if sensitive else "替代",
            "authentication-not-imported" if sensitive else "manual-public-mapping-required", review=not sensitive)
    for name in _children(tree):
      if name in documents:
        continue
      if _runtime_name(name):
        item("runtime", name, "原生保留", "runtime-data-not-read-or-copied")
        continue
      if name in {"extensions", "packages"}:
        item("extension", name, "替代", "omp-compatibility-and-dependency-review-required", review=True)
        continue
      if name in RESOURCE_KINDS:
        try:
          names = [name + "/" + child for child in _children(tree, name)]
        except (OSError, Conflict):
          item("resource", name, "排除", "unsafe-resource-not-copied")
          continue
      elif name == "RULES.md":
        names = [name]
      else:
        item("unknown", name, "原生保留", "unknown-source-not-read")
        continue
      for path in names:
        try:
          candidate = _candidate(tree, path)
          if name == "skills" and not any(entry["path"] == path + "/SKILL.md" for entry in candidate):
            raise Conflict("OMP候选技能缺少SKILL.md")
        except (OSError, Conflict):
          item("resource", path, "排除", "unsafe-resource-not-copied")
          continue
        if any(_sensitive(entry["content"], known) or _sensitive(entry["path"].encode(), known) for entry in candidate):
          item("resource", path, "排除", "sensitive-resource-not-copied")
          continue
        for entry in candidate:
          resources.append(entry)
          item("resource", entry["path"], "纳入", "candidate-requires-human-review", "resources/" + entry["path"], True,
            _sha(entry["content"]), entry["executable"])
  proposal = {"schema_version": 1, "overrides": {"profiles": {data["profile"]["id"]: captured}}}
  schemas = AdapterSchemas(adapter.schemas().bundles, {data["profile"]["id"]: "omp"})
  validate_document("local", {**proposal, "machine": {"id": data["machine"]["id"]}}, adapter_schemas=schemas)
  report = {"schema_version": 1, "source_root": str(source), "source_identity": {"kind": "explicit-native-agent-directory"},
    "items": items, "proposed_overrides": proposal["overrides"], "ready_to_deploy": False}
  report["projection_sha256"] = _sha(json_bytes(report))
  return report, proposal, resources


def _merge(target, incoming):
  for key, value in incoming.items():
    if isinstance(value, dict):
      _merge(target.setdefault(key, {}), value)
    else:
      target[key] = value


def _toml(document):
  """提案只含已校验的TOML基础类型，键和值分别编码。"""
  lines = []
  def visit(value, path):
    if path:
      lines.append("[" + ".".join(json.dumps(part, ensure_ascii=False) for part in path) + "]")
    for key, child in value.items():
      if not isinstance(child, dict):
        lines.append(json.dumps(key, ensure_ascii=False) + " = " + json.dumps(child, ensure_ascii=False))
    lines.append("")
    for key, child in value.items():
      if isinstance(child, dict):
        visit(child, (*path, key))
  visit(document, ())
  return ("\n".join(lines) + "\n").encode()


def write_inventory(workspace, source):
  if workspace.resolved.data["profile"]["agent"] != "omp":
    raise ConfigError("omp-inventory-requires-omp-profile")
  report, proposal, resources = build_inventory(source, adapter=workspace.adapter, data=workspace.resolved.data)
  destination = workspace.cache / "inventory" / uuid.uuid4().hex
  with Tree(destination, create=True) as tree:
    tree.write_new("disposition.json", json_bytes(report))
    tree.write_new("local-overrides.toml", _toml(proposal))
    ensure_private(destination / "resources")
    for entry in resources:
      tree.replace("resources/" + entry["path"], entry["content"], 0o600, expected=None)
  return {"proposal": str(destination), "items": len(report["items"]), "ready_to_deploy": False}

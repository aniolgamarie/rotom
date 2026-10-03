"""共享凭据文件；秘密只进入 SecretStore 或专用写入流程。"""

import json
from copy import deepcopy
import os
from pathlib import Path
import re

from .paths import PathError, configured_path, read_private_file, safe_id
from .secrets import CredentialError, SecretStore
from .storage import Conflict, Tree, instance_lock


_DEFAULT_SHARED_NAMES = {"deepseek_key", "kimi_key", "glm_key"}
_BARE_TOML_KEY = re.compile(r"[A-Za-z0-9_-]+")


def _group_maps(document):
  """返回所有凭据表及其实际 TOML section；调用前必须完成结构校验。"""
  groups = []
  if "secrets" in document:
    groups.append((("secrets",), document["secrets"]))
  if "shared" in document:
    groups.append((("shared",), document["shared"]))
  for provider_id, values in document.get("providers", {}).items():
    groups.append((("providers", provider_id), values))
  return groups


def _flatten_credentials(document):
  """将分类表展平为全局 secret 引用；跨组同名一律拒绝。"""
  from .schema import ConfigError
  flattened = {}
  for _, values in _group_maps(document):
    for name, value in values.items():
      if name in flattened:
        raise ConfigError("duplicate-credential-reference", ("secrets_file",))
      flattened[name] = value
  return flattened


def _expected_section(name, provider_id=None):
  if name in _DEFAULT_SHARED_NAMES or provider_id is None:
    return ("shared",)
  return ("providers", provider_id)


def _toml_key(value):
  return value if _BARE_TOML_KEY.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def section_label(section):
  """返回用户可识别的精确 TOML 分组标签。"""
  if section == ("inline",):
    return "旧机器文件 [secrets]"
  if section == ("secrets",):
    return "[secrets]（旧格式）"
  if section == ("shared",):
    return "[shared]"
  if (isinstance(section, tuple) and len(section) == 2
      and section[0] == "providers" and isinstance(section[1], str)):
    return f"[providers.{_toml_key(section[1])}]"
  raise ValueError("未知凭据分组")


def secrets_path(document, local_path):
  from .schema import ConfigError
  value = document.get("secrets_file")
  try:
    if value is not None:
      path = configured_path(value)
    else:
      root = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
      path = configured_path(root) / "agentcfg" / "secrets.toml"
    repository = Path(__file__).resolve().parents[2]
    if path == local_path.absolute() or path.is_relative_to(repository):
      raise PathError("秘密文件不能指向机器配置")
    return path
  except (PathError, TypeError, ValueError):
    pass
  raise ConfigError("secrets-file-path", ("local", "secrets_file"))


def read_secrets_document(path):
  from .config import _parse_toml
  from .schema import ConfigError
  error = None
  try:
    # 旧机器可能只有 0700 的 machines 子目录；缺失的共享文件不新增权限要求。
    # lstat 只检查存在性，链接自身存在时仍交给严格的 no-follow 读取拒绝。
    path.lstat()
    content = read_private_file(path)
  except FileNotFoundError:
    return {"schema_version": 1, "shared": {}}
  except (OSError, PathError):
    error = "共享密钥文件读取不安全；需当前用户所有、普通单链接文件 0600、父目录 0700，路径不得含符号链接"
  if error:
    raise Conflict(error)
  document = _parse_toml(content, ("secrets_file",))
  valid = (set(document) <= {"schema_version", "secrets", "shared", "providers"}
    and type(document.get("schema_version")) is int and document["schema_version"] == 1
    and isinstance(document.get("secrets", {}), dict)
    and isinstance(document.get("shared", {}), dict)
    and isinstance(document.get("providers", {}), dict))
  if valid:
    try:
      for section, values in _group_maps(document):
        if len(section) == 2:
          safe_id(section[1])
        SecretStore(values)
    except (PathError, CredentialError):
      valid = False
  if not valid:
    raise ConfigError("schema", ("secrets_file",))
  _flatten_credentials(document)
  return document


def load_secrets(document, local_path):
  """空旧占位符不遮蔽共享值；两个非空来源一律拒绝，避免悄悄选错账号。"""
  from .schema import separate_local, ConfigError
  separate_local(document)
  shared = _flatten_credentials(read_secrets_document(secrets_path(document, local_path)))
  inline = document.get("secrets", {})
  if any(value and shared.get(name) for name, value in inline.items()):
    raise ConfigError("duplicate-credential-source", ("local", "secrets", "<key>"))
  return SecretStore({**shared, **{name: value for name, value in inline.items() if value}})


def key_location(document, local_path, name):
  return local_path if document.get("secrets", {}).get(name) else secrets_path(document, local_path)


def credential_section(document, local_path, name, *, provider_id=None):
  """返回凭据当前 section；缺失时返回按命名和 provider 推导的目标 section。"""
  from .schema import ConfigError
  try:
    safe_id(name)
    if provider_id is not None:
      safe_id(provider_id)
  except PathError:
    raise ConfigError("model-key-invalid") from None
  if document.get("secrets", {}).get(name):
    return ("inline",)
  shared = read_secrets_document(secrets_path(document, local_path))
  for section, values in _group_maps(shared):
    if name in values:
      return section
  return _expected_section(name, provider_id)


def _key_tree(parent):
  tree = None
  try:
    tree = Tree(parent, create=True)
    # instance_lock 的 O_CREAT 受调用方 umask 影响；先以原子 0600 文件固定权限。
    if tree.read("instance.lock") is None:
      # 已被其他操作创建的锁绝不替换，否则会让两个进程分别锁住不同 inode。
      tree.write_new("instance.lock", b"")
    return tree
  except PathError:
    if tree is not None:
      tree.close()
  except BaseException:
    if tree is not None:
      tree.close()
    raise
  raise Conflict("共享密钥目录不安全；请将其父目录设为当前用户所有的 0700 目录，且路径不得含符号链接")


def validate_shared_placeholders(document, local_path, placeholders):
  """只读形成共享候选，供跨文件更新在创建目录或锁文件前失败。"""
  from .schema import ConfigError
  valid = isinstance(placeholders, dict)
  if valid:
    try:
      for name, provider_id in placeholders.items():
        safe_id(name)
        if provider_id is not None:
          safe_id(provider_id)
    except PathError:
      valid = False
  if not valid:
    raise ConfigError("model-key-invalid")
  path = secrets_path(document, local_path)
  shared = _flatten_credentials(read_secrets_document(path))
  inline = document.get("secrets", {})
  if any(value and shared.get(name) for name, value in inline.items()):
    raise ConfigError("duplicate-credential-source", ("local", "secrets", "<key>"))
  # 构造分类目标以验证所有新增项，而不读取或返回任何秘密值。
  present = set(inline) | set(shared)
  for name, provider_id in placeholders.items():
    if name not in present:
      _expected_section(name, provider_id)
  return path


def save_shared_key(document, local_path, name, value, *, provider_id=None, after_write=None):
  """锁住共享存储并原子更新；关联配置写入失败时只回滚本次凭据版本。"""
  from .model_wizard import render_edit
  from .schema import ConfigError
  try:
    safe_id(name)
    if provider_id is not None:
      safe_id(provider_id)
    SecretStore({name: value})
    valid = bool(value) and "\0" not in value
  except (PathError, CredentialError):
    valid = False
  if not valid:
    raise ConfigError("model-key-invalid")
  path = secrets_path(document, local_path)
  if document.get("secrets", {}).get(name):
    raise ConfigError("model-key-inline-source")
  with _key_tree(path.parent) as tree, instance_lock(tree):
    old = read_secrets_document(path)
    before = tree.read(path.name)
    # 读取正文与写入快照必须指向相同内容。
    from .config import _parse_toml
    if before and (before[1] != 0o600 or _parse_toml(before[0], ("secrets_file",)) != old):
      raise Conflict("共享密钥文件在读取期间发生变化")
    section = next((candidate for candidate, values in _group_maps(old) if name in values),
      _expected_section(name, provider_id))
    new = {**old}
    target = new
    for part in section:
      target[part] = {**target.get(part, {})}
      target = target[part]
    target[name] = value
    content = before[0] if before else (
      "schema_version = 1\n\n"
      "# shared 保存默认公共凭据；providers 按 provider 分类；密钥名在全文件内必须唯一。\n"
      "[shared]\n"
    ).encode("utf-8")
    rendered = render_edit(content, [(section, {name: value})], new)
    if before is None:
      tree.write_new(path.name, rendered)
    else:
      tree.replace(path.name, rendered, 0o600, expected=before[2])
    written = tree.read(path.name)
    try:
      if after_write is not None:
        after_write()
    except BaseException:
      try:
        tree.replace(path.name, before[0] if before else None, 0o600, expected=written[2])
      except Exception:
        raise Conflict("配置写入失败，共享凭据回滚发生冲突；请运行 model status 检查，勿覆盖并发修改") from None
      raise
  return path


def ensure_shared_placeholders(document, local_path, placeholders, *, after_write):
  """批量补齐空凭据占位；回调失败时仅 CAS 回滚本次共享版本。"""
  from .config import _parse_toml
  from .model_wizard import render_edit
  from .schema import ConfigError
  valid = isinstance(placeholders, dict) and callable(after_write)
  if valid:
    try:
      for name, provider_id in placeholders.items():
        safe_id(name)
        if provider_id is not None:
          safe_id(provider_id)
    except PathError:
      valid = False
  if not valid:
    raise ConfigError("model-key-invalid")

  path = secrets_path(document, local_path)
  inline = document.get("secrets", {})
  with _key_tree(path.parent) as tree, instance_lock(tree):
    old = read_secrets_document(path)
    before = tree.read(path.name)
    if before and (before[1] != 0o600 or _parse_toml(before[0], ("secrets_file",)) != old):
      raise Conflict("共享密钥文件在读取期间发生变化")
    shared_values = _flatten_credentials(old)
    if any(value and shared_values.get(name) for name, value in inline.items()):
      raise ConfigError("duplicate-credential-source", ("local", "secrets", "<key>"))
    present = set(inline) | set(_flatten_credentials(old))
    additions = {name: provider_id for name, provider_id in placeholders.items()
                 if name not in present}
    if not additions and before is not None:
      after_write()
      return path, (), "unchanged"

    new = deepcopy(old)
    grouped = {}
    for name, provider_id in additions.items():
      section = _expected_section(name, provider_id)
      target = new
      for part in section:
        target[part] = {**target.get(part, {})}
        target = target[part]
      target[name] = ""
      grouped.setdefault(section, {})[name] = ""
    content = before[0] if before else (
      "schema_version = 1\n\n"
      "# shared 保存默认公共凭据；providers 按 provider 分类；密钥名在全文件内必须唯一。\n"
      "[shared]\n"
    ).encode("utf-8")
    rendered = render_edit(content, list(grouped.items()), new)
    if before is None:
      tree.write_new(path.name, rendered)
    else:
      tree.replace(path.name, rendered, 0o600, expected=before[2])
    written = tree.read(path.name)
    try:
      after_write()
    except BaseException:
      try:
        tree.replace(path.name, before[0] if before else None, 0o600, expected=written[2])
      except Exception:
        raise Conflict("配置写入失败，共享占位回滚发生冲突；请运行 model status 检查，勿覆盖并发修改") from None
      raise
  return path, tuple(additions), "created" if before is None else "supplemented"

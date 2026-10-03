"""创建或幂等补齐本地机器配置及其空私人占位。"""

from copy import deepcopy
from dataclasses import dataclass
import json
import errno
import os
import tomllib
from pathlib import Path

from .config import LocalConfig, _parse_toml, resolve_config
from .paths import (InitializationError, PathError, configured_path, prepare_initial_local,
                    read_private_file, safe_id)
from .schema import ConfigError, separate_local, validate_document
from .secret_files import ensure_shared_placeholders, validate_shared_placeholders
from .storage import Conflict, Tree
from .workspace import load_public_catalog


@dataclass(frozen=True)
class InitializationResult:
  machine_path: Path
  secrets_path: Path
  profile: str
  machine_action: str
  secrets_action: str
  local_fields: tuple[str, ...] = ()
  secret_fields: tuple[str, ...] = ()


def available_profiles() -> list[tuple[str, str]]:
  """只读取仓库登记的公开 profile 元数据。"""
  repository = Path(__file__).resolve().parents[2]
  profiles = []
  for path in sorted((repository / "profiles").glob("*.toml")):
    try:
      document = tomllib.loads(path.read_text(encoding="utf-8"))
      profile_id, agent = document["id"], document["agent"]
      safe_id(profile_id)
      if not isinstance(agent, str) or profile_id != path.stem or agent not in ("dsh", "pi", "omp"):
        raise ValueError
      profiles.append((profile_id, agent))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, ValueError, PathError):
      raise InitializationError(2) from None
  if not profiles:
    raise InitializationError(2)
  return profiles


def _new_document(machine_id, profile_id):
  return {"schema_version": 1, "machine": {"id": machine_id, "default_profile": profile_id}}


def _new_content(document):
  machine = document["machine"]
  content = (f"schema_version = 1\n\n[machine]\nid = {json.dumps(machine['id'], ensure_ascii=False)}\n"
             f"default_profile = {json.dumps(machine['default_profile'], ensure_ascii=False)}\n")
  values = document.get("local_values", {})
  if values:
    content += "\n# 私人服务地址占位；使用 model url 填写。\n[local_values]\n"
    content += "".join(f"{json.dumps(name, ensure_ascii=False)} = \"\"\n" for name in sorted(values))
  content += "\n# 密钥保存在共享 agentcfg/secrets.toml；运行 model status 查看缺项。\n"
  return content.encode("utf-8")


def _resolved(catalog, document, profile_id):
  ordinary, _ = separate_local(document)
  validate_document("local", ordinary, adapter_schemas=catalog.adapter_schemas)
  return resolve_config(catalog, LocalConfig(ordinary), profile_id=profile_id,
    adapter_schemas=catalog.adapter_schemas, allow_missing_local_values=True)


def initialize_local(machine_id: str, *, config_home: str | Path,
                     profile_id: str | None = None) -> InitializationResult:
  """创建或补齐目标 profile 的空占位；已有私人值与非目标字段保持不变。"""
  try:
    machine_id = safe_id(machine_id)
    machine_id.encode("utf-8")
    if profile_id is not None:
      profile_id = safe_id(profile_id)
      profile_id.encode("utf-8")
    root = configured_path(os.fspath(config_home))
    root = Path("/", *root.parts[1:])
    os.fsencode(root)
  except (PathError, TypeError, ValueError, UnicodeError):
    raise InitializationError(2) from None

  repository = Path(__file__).resolve().parents[2]
  machine_path = root / "agentcfg" / "machines" / f"{machine_id}.toml"
  if machine_path.is_relative_to(repository):
    raise InitializationError(4)

  try:
    catalog, _ = load_public_catalog(repository=repository)
    try:
      original = read_private_file(machine_path)
    except FileNotFoundError:
      original = None

    if original is None:
      target_profile = profile_id or "dsh-default"
      document = _new_document(machine_id, target_profile)
    else:
      document = _parse_toml(original, ("local",))
      ordinary, _ = separate_local(document)
      validate_document("local", ordinary, adapter_schemas=catalog.adapter_schemas)
      machine = document.get("machine", {})
      if machine.get("id") != machine_id:
        raise ConfigError("machine-id", ("local", "machine", "id"))
      target_profile = profile_id or machine.get("default_profile", "dsh-default")

    # 保留精确公开配方存在性检查；在创建任何私人目录前失败。
    if (target_profile not in catalog.profiles
        or not (repository / "profiles" / f"{target_profile}.toml").is_file()):
      raise ConfigError("reference", ("profile",))
    resolved = _resolved(catalog, document, target_profile)
    local_names = tuple(dict.fromkeys(name for _, name in resolved.local_value_refs))
    local_additions = tuple(name for name in local_names
                            if name not in document.get("local_values", {}))
    candidate = deepcopy(document)
    if local_additions:
      candidate["local_values"] = {**candidate.get("local_values", {}),
                                   **{name: "" for name in local_additions}}
    # 在任何文件写入前完整解析机器候选；空值被允许且仍算字段已具备。
    final_resolved = _resolved(catalog, candidate, target_profile)

    credentials = {}
    for provider_id, provider in final_resolved.data["providers"].items():
      reference = provider.get("credential_ref")
      if isinstance(reference, str) and reference.startswith("secret:"):
        credentials.setdefault(reference.removeprefix("secret:"), provider_id)

    if original is None:
      rendered = _new_content(candidate)
      machine_action = "created"
    elif local_additions:
      from .model_wizard import render_edit
      rendered = render_edit(original, [(("local_values",),
        {name: "" for name in local_additions})], candidate)
      machine_action = "supplemented"
    else:
      rendered = original
      machine_action = "unchanged"

    # 两份候选均已解析后才创建缺失目录；锁内会重读共享文件防止并发漂移。
    validate_shared_placeholders(document, machine_path, credentials)
    prepare_initial_local(root)
    with Tree(machine_path.parent) as machine_tree:
      before = machine_tree.read(machine_path.name)
    if before is not None and before[1] != 0o600:
      raise Conflict("本地机器文件必须为当前用户所有的普通单链接 0600 文件")
    if ((before is None) != (original is None)
        or before is not None and before[0] != original):
      raise Conflict("本地机器文件在规划期间发生变化，请重试")

    def commit_machine():
      with Tree(machine_path.parent) as tree:
        current = tree.read(machine_path.name)
        expected = before[2] if before else None
        if (current[2] if current else None) != expected:
          raise Conflict("本地机器文件在提交前发生变化，请重试")
        if before is None:
          tree.write_new(machine_path.name, rendered)
        elif rendered != before[0]:
          tree.replace(machine_path.name, rendered, 0o600, expected=expected)

    shared_path, secret_additions, secrets_action = ensure_shared_placeholders(
      document, machine_path, credentials, after_write=commit_machine)
    return InitializationResult(machine_path, shared_path, target_profile, machine_action,
      secrets_action, local_additions, secret_additions)
  except InitializationError:
    raise
  except PathError:
    raise InitializationError(4) from None
  except OSError as error:
    code = 4 if error.errno in (errno.EEXIST, errno.ELOOP, errno.ENOTDIR) else 6
    raise InitializationError(code) from None

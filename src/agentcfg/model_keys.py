"""只通过隐藏输入更新模型凭据，不接收命令行明文 key。"""

import getpass
import sys
import warnings
from copy import deepcopy

from .config import read_local_document
from .schema import ConfigError
from .secret_files import credential_section, key_location, save_shared_key, section_label
from .storage import Conflict, Tree
from .presentation import command_line
from .workspace import load_workspace


def set_model_key(args):
  if not sys.stdin.isatty() or not sys.stdout.isatty():
    raise ConfigError("model-wizard-requires-terminal")
  workspace = load_workspace(args.local, args.profile, allow_missing_local_values=True)
  provider = workspace.resolved.data["providers"].get(args.provider)
  if args.provider in ("deepseek", "kimi", "glm"):
    name = args.provider + "_key"
  elif provider and provider.get("auth_kind") == "api-key":
    name = provider["credential_ref"].removeprefix("secret:")
  else:
    raise ConfigError("model-key-provider-not-selected")
  document = read_local_document(args.local)
  path = key_location(document, args.local, name)
  section = credential_section(document, args.local, name, provider_id=args.provider)
  print(f"凭据：{name}\n保存位置：{path}\n文件分组：{section_label(section)}")
  if path == args.local:
    print("此 key 已保存在旧机器文件中，本次更新原位置；其他 key 默认写入共享文件。")
  else:
    print("所有引用此凭据的工具和 profile 共用；输入不会回显。")
  try:
    with warnings.catch_warnings():
      warnings.simplefilter("error", getpass.GetPassWarning)
      value = getpass.getpass("API key（隐藏输入，留空取消）: ")
  except (EOFError, OSError, getpass.GetPassWarning):
    raise ConfigError("model-wizard-secret-input-unavailable") from None
  if not value:
    print("已取消；密钥未修改。")
    return 0
  if "\0" in value:
    raise ConfigError("model-key-invalid")
  # 不允许隐藏输入期间机器配置的秘密来源发生变化。
  if read_local_document(args.local) != document:
    raise Conflict("机器配置在输入期间发生变化；请重试")
  if path == args.local:
    from .model_wizard import render_edit
    proposed = deepcopy(document)
    proposed["secrets"][name] = value
    with Tree(path.parent) as tree:
      before = tree.read(path.name)
      from .config import _parse_toml
      if before is None or before[1] != 0o600 or _parse_toml(before[0], ("local",)) != document:
        raise Conflict("机器配置在输入期间发生变化；请重试")
      tree.replace(path.name, render_edit(before[0], [(("secrets",), {name: value})], proposed),
        0o600, expected=before[2])
  else:
    save_shared_key(document, args.local, name, value, provider_id=args.provider)
  print("key 已保存（未联网验证）；仅更新 key 无需重新部署。退出工具后重新启动：\n  " + command_line(args, "run"))
  return 0

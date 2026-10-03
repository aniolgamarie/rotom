"""隐藏输入私人服务地址；公开配置只保留引用，实际地址不回显。"""

from copy import deepcopy
import getpass
import sys
import warnings

from .config import _parse_toml, read_local_document
from .model_wizard import render_edit
from .local_values import validate_local_url
from .schema import ConfigError, validate_document
from .storage import Conflict, Tree
from .presentation import command_line
from .workspace import load_workspace


def set_model_url(args):
  if not sys.stdin.isatty() or not sys.stdout.isatty():
    raise ConfigError("model-wizard-requires-terminal")
  original = read_local_document(args.local)
  with Tree(args.local.parent) as tree:
    before = tree.read(args.local.name)
  if before is None or before[1] != 0o600 or _parse_toml(before[0], ("local",)) != original:
    raise Conflict("机器配置在读取期间发生变化；请重试")
  workspace = load_workspace(args.local, args.profile, allow_missing_local_values=True)
  provider = workspace.resolved.data["providers"].get(args.provider)
  if not provider or provider.get("auth_kind") != "api-key":
    raise ConfigError("model-url-provider-not-selected")
  references = dict(workspace.resolved.local_value_refs)
  name = references.get(args.provider)
  section = ("local_values",) if name else ("overrides", "providers", args.provider)
  field = name or "base_url"
  print(f"Provider：{args.provider}\n保存到私人机器文件：{args.local}")
  print("配置位置：" + ".".join((*section, field)))
  print("填写与该 provider 协议匹配的完整服务地址；不要在 URL 中包含 key 或密码。")
  try:
    with warnings.catch_warnings():
      warnings.simplefilter("error", getpass.GetPassWarning)
      value = getpass.getpass("服务 URL（隐藏输入，留空取消）: ").strip()
  except (EOFError, OSError, getpass.GetPassWarning):
    raise ConfigError("model-url-input-unavailable") from None
  if not value:
    print("已取消；机器配置未修改。")
    return 0
  validate_local_url(value)
  proposed = deepcopy(original)
  target = proposed
  for part in section:
    target = target.setdefault(part, {})
  target[field] = value
  validate_document("local", proposed, adapter_schemas=workspace.schemas)
  proposal = {key: proposed[key] for key in ("local_values", "overrides") if key in proposed}
  # 允许逐个填写缺失地址；普通部署与启动入口仍要求所有已选地址完整。
  load_workspace(args.local, workspace.profile, proposal=proposal, allow_missing_local_values=True)
  rendered = render_edit(before[0], [(section, {field: value})], proposed)
  with Tree(args.local.parent) as tree:
    tree.replace(args.local.name, rendered, 0o600, expected=before[2])
  print("私人 URL 已保存（未联网验证）；退出工具后更新部署：\n  " + command_line(args, "setup"))
  return 0

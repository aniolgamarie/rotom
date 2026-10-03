"""为现有私人机器文件安全添加一个静态 API-key 模型。"""

from copy import deepcopy
import getpass
import json
from pathlib import Path
import re
import sys
import tomllib
import warnings

from .adapter import SecretRef
from .config import read_local_document
from .paths import PathError, safe_id
from .presentation import command_line, table
from .progress import Progress
from .schema import ConfigError, validate_document
from .storage import Conflict, Tree
from .secret_files import save_shared_key
from .workspace import load_workspace


_HEADER = re.compile(r"^\s*\[.*\]\s*(?:#.*)?$")
_KEY = re.compile(r"^\s*([A-Za-z0-9_-]+|\"(?:[^\"\\]|\\.)*\"|'[^']*')\s*=")
_MARKER = "__agentcfg_table_marker__"
_PRESETS = {
  "deepseek": "deepseek_flash",
  "kimi": "kimi_k3",
  "glm": "glm_53",
}


def _literal(value):
  return json.dumps(value, ensure_ascii=False)


def _key_literal(value):
  return value if re.fullmatch(r"[A-Za-z0-9_-]+", value) else _literal(value)


def _assignment_key(line):
  match = _KEY.match(line)
  if not match:
    return None
  try:
    return next(iter(tomllib.loads(match.group(1) + " = 1")))
  except tomllib.TOMLDecodeError:
    return None


def _header_path(line):
  if not _HEADER.fullmatch(line.rstrip("\r\n")):
    return None
  try:
    node = tomllib.loads(line + f"{_MARKER} = true\n")
  except tomllib.TOMLDecodeError:
    raise Conflict("本地 TOML 使用了向导无法安全编辑的表语法；请手动修改") from None
  path = []
  while isinstance(node, dict) and _MARKER not in node:
    if len(node) != 1:
      raise Conflict("本地 TOML 表结构无法安全定位；请手动修改")
    key, node = next(iter(node.items()))
    path.append(key)
  if not isinstance(node, dict) or node.get(_MARKER) is not True:
    raise Conflict("本地 TOML 表结构无法安全定位；请手动修改")
  return tuple(path)


def _edit_field(source, section, key, value):
  if "\r" in source or "'''" in source or '"""' in source:
    raise Conflict("本地 TOML 含复杂多行格式；向导拒绝自动改写，请手动修改")
  lines = source.splitlines(keepends=True)
  headings = [(index, _header_path(line)) for index, line in enumerate(lines)
              if _HEADER.fullmatch(line.rstrip("\r\n"))]
  matches = [index for index, path in headings if path == section]
  if len(matches) > 1:
    raise Conflict("本地 TOML 目标表重复；向导拒绝改写")
  literal = _literal(value)
  if not matches:
    heading = ".".join(_literal(part) for part in section)
    suffix = "" if not source or source.endswith("\n") else "\n"
    return source + suffix + f"\n[{heading}]\n{_literal(key)} = {literal}\n"
  start = matches[0]
  end = next((index for index, _ in headings if index > start), len(lines))
  existing = [index for index in range(start + 1, end) if _assignment_key(lines[index]) == key]
  if len(existing) > 1:
    raise Conflict("本地 TOML 目标字段重复；向导拒绝改写")
  assignment = f"{_key_literal(key)} = {literal}\n"
  if existing:
    index = existing[0]
    try:
      tomllib.loads(lines[index])
    except tomllib.TOMLDecodeError:
      raise Conflict("本地 TOML 目标字段跨多行；向导拒绝自动改写") from None
    lines[index] = assignment
  else:
    lines.insert(end, assignment)
  return "".join(lines)


def render_edit(original, updates, expected):
  """只改目标字段；再以完整 TOML 语义比较验证没有触碰其他内容。"""
  source = original.decode("utf-8")
  for section, fields in updates:
    for key, value in fields.items():
      source = _edit_field(source, section, key, value)
  try:
    actual = tomllib.loads(source)
  except tomllib.TOMLDecodeError:
    raise Conflict("本地 TOML 无法安全局部改写；原文件保持不变") from None
  if actual != expected:
    raise Conflict("本地 TOML 改写结果与已校验提案不一致；原文件保持不变")
  return source.encode("utf-8")


def _ask(label, *, default=None):
  suffix = f" [{default}]" if default is not None else ""
  try:
    value = input(f"{label}{suffix}: ").strip()
  except EOFError:
    raise ConfigError("model-wizard-input-ended") from None
  return value or default or ""


def _id(value):
  try:
    return safe_id(value)
  except PathError:
    raise ConfigError("model-wizard-invalid-id") from None


def _positive(value):
  if not value:
    return None
  try:
    number = int(value)
  except ValueError:
    number = 0
  if number < 1:
    raise ConfigError("model-wizard-invalid-capacity")
  return number


def _answers(workspace):
  provider_id = _id(_ask("新 provider ID"))
  model_id = _id(_ask("新 model ID"))
  protocols = ("openai-compatible", "openai-responses", "anthropic-messages") if workspace.agent == "omp" else (
    "openai-compatible", "openai-responses")
  protocol = _ask("协议 " + " / ".join(protocols), default="openai-compatible")
  if protocol not in protocols:
    raise ConfigError("model-wizard-invalid-protocol")
  base_url = _ask("服务 base URL（不要包含密钥）")
  remote_id = _ask("服务端模型 ID")
  inputs = [part.strip() for part in _ask("输入能力，逗号分隔", default="text").split(",")]
  if not inputs or set(inputs) - {"text", "image"} or len(set(inputs)) != len(inputs):
    raise ConfigError("model-wizard-invalid-input")
  if workspace.agent == "omp":
    from .omp import ROLE_MAP
    roles = tuple(ROLE_MAP)
    role = _id(_ask("绑定角色 " + " / ".join(roles), default="main"))
    if role not in roles:
      raise ConfigError("model-wizard-invalid-role")
  else:
    role = _id(_ask("绑定角色", default="main"))
  model = {"provider": provider_id, "remote_id": remote_id, "input": inputs}
  if workspace.agent == "omp":
    model["context_window"] = _positive(_ask("上下文容量（已核实的正整数）"))
    model["max_output_tokens"] = _positive(_ask("最大输出 token（已核实的正整数）"))
    if not model["context_window"] or not model["max_output_tokens"]:
      raise ConfigError("omp-model-capacity-required")
  source = _ask("模型规格来源（可留空）")
  if source:
    model["source"] = source
  secret_name = _id(provider_id + "_key")
  try:
    with warnings.catch_warnings():
      warnings.simplefilter("error", getpass.GetPassWarning)
      secret = getpass.getpass("API key（隐藏输入，启用时必填）: ")
  except (EOFError, OSError, getpass.GetPassWarning):
    raise ConfigError("model-wizard-secret-input-unavailable") from None
  if not secret:
    raise ConfigError("model-wizard-key-required-for-selection")
  return provider_id, model_id, role, secret_name, secret, {
    "protocol": protocol, "auth_kind": "api-key", "base_url": base_url,
    "credential_ref": "secret:" + secret_name}, model


def _public_ids(repository):
  found = {"providers": set(), "models": set()}
  sources = [*sorted((repository / "shared").glob("*.toml")),
    *sorted((repository / "agents").glob("*/content.toml"))]
  for path in sources:
    try:
      data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
      raise ConfigError("model-wizard-public-catalog") from None
    for kind in found:
      found[kind].update(data.get(kind, {}))
  return found


def _preset_catalog(repository):
  from .schema import validate_document
  try:
    providers = tomllib.loads((repository / "shared/providers.toml").read_text(encoding="utf-8"))
    models = tomllib.loads((repository / "shared/models.toml").read_text(encoding="utf-8"))
  except (OSError, UnicodeError, tomllib.TOMLDecodeError):
    raise ConfigError("model-preset-catalog-invalid") from None
  validate_document("registry", providers)
  validate_document("registry", models)
  for stem in _PRESETS.values():
    for protocol in ("openai", "anthropic"):
      item = models.get("models", {}).get(stem + "_" + protocol)
      provider = providers.get("providers", {}).get(item.get("provider")) if isinstance(item, dict) else None
      if (not isinstance(provider, dict) or provider.get("protocol") != {
            "openai": "openai-compatible", "anthropic": "anthropic-messages"}[protocol]
          or provider.get("auth_kind") != "api-key" or "base_url" not in provider or "credential_ref" not in provider
          or not isinstance(item.get("pricing"), dict) or "context_window" not in item
          or "max_output_tokens" not in item or "source" not in item):
        raise ConfigError("model-preset-catalog-invalid")
  return providers["providers"], models["models"]


def _check_native_candidate(workspace):
  """锁材料缺失时仍可编辑 Pi 私人配置；部署前必须补齐完整锁。"""
  try:
    lock = workspace.backend.read_lock(workspace.repository)
  except ConfigError as error:
    if workspace.agent != "pi" or error.code != "pi-lock-missing-or-stale":
      raise
    workspace.candidate("unlocked-pi-config-check")
    print("警告：Pi 依赖锁不可用或不完整；模型原生产物已离线校验，完整锁仍待核验。" +
      "补齐 Pi 锁材料后运行 validate、plan、setup。", file=sys.stderr)
    return False
  workspace.candidate(lock.identity)
  return True


def list_presets(args):
  repository = Path(__file__).resolve().parents[2]
  providers, models = _preset_catalog(repository)
  print("官方模型预设（仓库声明）\n")
  if not getattr(args, "verbose", False):
    rows = []
    for vendor, stem in _PRESETS.items():
      model = models[stem + "_openai"]
      rows.append((vendor, model["remote_id"], f"{model['context_window']:,}",
        f"{model['max_output_tokens']:,}", ", ".join(model["input"])))
    table(("服务商", "模型", "上下文 token", "最大输出 token", "输入"), rows)
    print("\n默认加入所有工具和 profile；填写共享 key 后即可使用对应模型。")
    print("完整地址、计价与来源：./agentcfg model presets --verbose")
    return 0
  for vendor, stem in _PRESETS.items():
    model = models[stem + "_openai"]
    openai = providers[model["provider"]]["base_url"]
    anthropic = providers[models[stem + "_anthropic"]["provider"]]["base_url"]
    pricing = model["pricing"]
    rates = pricing["standard"]
    amount = f"{pricing['currency']}/{pricing['per_tokens']} tokens"
    print(f"{vendor}: {model['remote_id']} | context={model['context_window']} | output={model['max_output_tokens']} | input={','.join(model['input'])}")
    print("  reasoning=" + (",".join(model.get("reasoning_efforts", [])) if model.get("reasoning") else "off") +
      (f" | provider max output={model['max_output_supported']}" if "max_output_supported" in model else ""))
    print(f"  OpenAI: {openai} | Anthropic: {anthropic}")
    print(f"  {'peak ' if 'off_peak' in pricing else ''}{amount}: input={rates['input']} output={rates['output']}" +
      (f" cache-read={rates['cache_read']}" if "cache_read" in rates else ""))
    if "cache_write" in rates:
      print(f"  cache-write={rates['cache_write']} {amount}")
    if "off_peak" in pricing:
      low = pricing["off_peak"]
      print(f"  off-peak: input={low['input']} output={low['output']}" +
        (f" cache-read={low['cache_read']}" if "cache_read" in low else "") + f"; {pricing['schedule']}")
    print(f"  source: {model['source']} | price: {pricing['source']} (checked {pricing['checked_on']})")
  print("\nDeepSeek、Kimi、GLM 默认加入所有工具和 profile；通过 model status 查看 key 填写位置。")
  return 0


def model_status(args):
  from .model_status import show_model_status
  return show_model_status(args)


def enable_preset(args):
  if not sys.stdin.isatty() or not sys.stdout.isatty():
    raise ConfigError("model-wizard-requires-terminal")
  progress = Progress("model enable", args)
  progress.stage("读取私人配置与公共模型预设", hint="validate")
  old = read_local_document(args.local)
  with Tree(args.local.parent) as tree:
    snapshot = tree.read(args.local.name)
  if snapshot is None or snapshot[1] != 0o600:
    raise Conflict("本地配置在读取后发生变化或权限无效")
  try:
    same_document = tomllib.loads(snapshot[0].decode("utf-8")) == old
  except (UnicodeError, tomllib.TOMLDecodeError):
    same_document = False
  if not same_document:
    raise Conflict("本地配置在读取后发生变化；请重试")
  workspace = load_workspace(args.local, args.profile)
  with Tree(args.local.parent) as tree:
    checked_snapshot = tree.read(args.local.name)
  if checked_snapshot is None or checked_snapshot[2] != snapshot[2]:
    raise Conflict("本地配置在解析期间发生变化；请重试")
  protocol = args.protocol or ("anthropic" if workspace.agent == "omp" else "openai")
  if protocol == "anthropic" and workspace.agent != "omp":
    raise ConfigError("model-preset-protocol-unsupported")
  providers, models = _preset_catalog(workspace.repository)
  model_id = _PRESETS[args.preset] + "_" + protocol
  model = models[model_id]
  provider_id = model["provider"]
  provider = providers[provider_id]
  secret_name = provider["credential_ref"].removeprefix("secret:")
  secret = workspace.secret_store.resolve(SecretRef(provider["credential_ref"]), required=False)
  needs_key = not secret
  if not secret:
    progress.stage("读取所需 API key（隐藏输入）", hint="validate")
    try:
      with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        secret = getpass.getpass(f"{args.preset} API key（隐藏输入）: ")
    except (EOFError, OSError, getpass.GetPassWarning):
      raise ConfigError("model-wizard-secret-input-unavailable") from None
    if not secret:
      raise ConfigError("model-preset-key-required")
  proposed = deepcopy(old)
  profile = proposed.setdefault("overrides", {}).setdefault("profiles", {}).setdefault(workspace.profile, {})
  selected = workspace.resolved.data["profile"]
  providers_selected = list(selected["providers"])
  models_selected = list(selected["models"])
  if provider_id not in providers_selected:
    providers_selected.append(provider_id)
  if model_id not in models_selected:
    models_selected.append(model_id)
  profile["providers"] = providers_selected
  profile["models"] = models_selected
  role_updates = {}
  if "main" not in selected["roles"]:
    role_updates["main"] = model_id
    if workspace.agent == "pi":
      declarations = workspace.resolved.data["adapter_documents"]["agent"]["resources"]
      for resource_id in selected["agent_options"].get("resources", {}).get("roles", []):
        role = declarations[resource_id]["model_role"]
        if role not in selected["roles"]:
          role_updates[role] = model_id
  if role_updates:
    profile.setdefault("roles", {}).update(role_updates)
  if proposed == old and not needs_key:
    print(f"{workspace.agent}/{workspace.profile}: {model_id} 已启用，密钥已配置")
    return 0
  progress.stage("校验候选配置和原生产物", hint="validate")
  validate_document("local", proposed, adapter_schemas=workspace.schemas)
  checked = load_workspace(args.local, workspace.profile, proposal={"overrides": proposed["overrides"]})
  native_checked = _check_native_candidate(checked)
  updates = [(("overrides", "profiles", workspace.profile),
    {"providers": providers_selected, "models": models_selected})]
  if role_updates:
    updates.append((("overrides", "profiles", workspace.profile, "roles"), role_updates))
  with Tree(args.local.parent) as tree:
    before = tree.read(args.local.name)
    if before is None or before[1] != 0o600 or before[2] != snapshot[2]:
      raise Conflict("本地配置在读取后发生变化或权限无效")
    original = before[0]
    if tomllib.loads(original.decode("utf-8")) != old:
      raise Conflict("本地配置在向导期间发生变化；请重试")
    rendered = render_edit(original, updates, proposed)
    progress.stage("等待确认并写入私人文件", hint="validate")
    print(f"提案：为 {workspace.agent}/{workspace.profile} 启用 {model['name']}（{protocol}），新密钥保存到共享文件；" +
      ("绑定角色 " + ", ".join(role_updates) + "。" if role_updates else "保留现有角色绑定。"))
    if _ask("写入私人机器文件？输入 yes 确认") != "yes":
      print("已取消；机器文件未修改")
      return 0
    def write_config():
      tree.replace(args.local.name, rendered, 0o600, expected=before[2])
    if needs_key:
      save_shared_key(old, args.local, secret_name, secret, provider_id=provider_id, after_write=write_config)
    else:
      write_config()
  print("模型已启用。" if native_checked else "模型配置已保存；Pi 依赖锁材料待补齐。")
  print("下一步：\n  " + command_line(args, "setup" if native_checked else "doctor"))
  return 0


def add_model(args):
  if not sys.stdin.isatty() or not sys.stdout.isatty():
    raise ConfigError("model-wizard-requires-terminal")
  if args.model_command != "add":
    raise ConfigError("model-wizard-command")
  progress = Progress("model add", args)
  progress.stage("读取并校验所选配置", hint="validate")
  old = read_local_document(args.local)
  with Tree(args.local.parent) as tree:
    snapshot = tree.read(args.local.name)
  if snapshot is None or snapshot[1] != 0o600:
    raise Conflict("本地配置在读取后发生变化或权限无效")
  try:
    same_document = tomllib.loads(snapshot[0].decode("utf-8")) == old
  except (UnicodeError, tomllib.TOMLDecodeError):
    same_document = False
  if not same_document:
    raise Conflict("本地配置在读取后发生变化；请重试")
  workspace = load_workspace(args.local, args.profile)
  with Tree(args.local.parent) as tree:
    checked_snapshot = tree.read(args.local.name)
  if checked_snapshot is None or checked_snapshot[2] != snapshot[2]:
    raise Conflict("本地配置在解析期间发生变化；请重试")
  progress.stage("收集模型参数", hint="validate")
  provider_id, model_id, role, secret_name, secret, provider, model = _answers(workspace)
  public = _public_ids(workspace.repository)
  if provider_id in public["providers"] or model_id in public["models"]:
    raise ConfigError("model-wizard-public-id-exists")
  if provider_id in workspace.resolved.data["providers"] or model_id in workspace.resolved.data["models"]:
    raise ConfigError("model-wizard-id-already-selected")
  proposed = deepcopy(old)
  overrides = proposed.setdefault("overrides", {})
  providers = overrides.setdefault("providers", {})
  models = overrides.setdefault("models", {})
  if (provider_id in providers or model_id in models or secret_name in proposed.get("secrets", {})
      or workspace.secret_store.resolve(SecretRef("secret:" + secret_name), required=False)):
    raise ConfigError("model-wizard-id-exists")
  providers[provider_id] = provider
  models[model_id] = model
  profile = overrides.setdefault("profiles", {}).setdefault(workspace.profile, {})
  profile["providers"] = [*workspace.resolved.data["profile"]["providers"], provider_id]
  profile["models"] = [*workspace.resolved.data["profile"]["models"], model_id]
  role_updates = {role: model_id}
  if workspace.agent == "pi" and role == "main":
    selected = workspace.resolved.data["profile"]
    declarations = workspace.resolved.data["adapter_documents"]["agent"]["resources"]
    for resource_id in selected["agent_options"].get("resources", {}).get("roles", []):
      required_role = declarations[resource_id]["model_role"]
      if required_role not in selected["roles"]:
        role_updates[required_role] = model_id
  profile.setdefault("roles", {}).update(role_updates)
  progress.stage("校验候选配置和原生产物", hint="validate")
  validate_document("local", proposed, adapter_schemas=workspace.schemas)
  # 使用现有合并/适配器验证链检查整份候选，不读取原生账号、不联网。
  checked = load_workspace(args.local, workspace.profile, proposal={"overrides": overrides})
  _check_native_candidate(checked)
  updates = [
    (("overrides", "providers", provider_id), provider),
    (("overrides", "models", model_id), model),
    (("overrides", "profiles", workspace.profile), {"providers": profile["providers"], "models": profile["models"]}),
    (("overrides", "profiles", workspace.profile, "roles"), role_updates),
  ]
  with Tree(args.local.parent) as tree:
    before = tree.read(args.local.name)
    if before is None or before[1] != 0o600 or before[2] != snapshot[2]:
      raise Conflict("本地配置在读取后发生变化或权限无效")
    original = before[0]
    if tomllib.loads(original.decode("utf-8")) != old:
      raise Conflict("本地配置在向导期间发生变化；请重试")
    rendered = render_edit(original, updates, proposed)
    progress.stage("等待确认并写入私人文件", hint="validate")
    print(f"提案：为 {workspace.agent}/{workspace.profile} 新增 provider {provider_id}、model {model_id}，绑定角色 {role}；密钥保存到共享文件。")
    if _ask("写入私人机器文件？输入 yes 确认") != "yes":
      print("已取消；机器文件未修改")
      return 0
    save_shared_key(old, args.local, secret_name, secret, provider_id=provider_id, after_write=lambda:
      tree.replace(args.local.name, rendered, 0o600, expected=before[2]))
  print("配置已写入。下一步：\n  " + command_line(args, "setup"))
  return 0

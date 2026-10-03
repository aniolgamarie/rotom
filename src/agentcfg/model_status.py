"""模型就绪摘要与编辑位置；详细目录按需展开，始终不显示私人值。"""

from .adapter import SecretRef
from .config import read_local_document
from .presentation import command_line, table
from .secret_files import credential_section, key_location, secrets_path, section_label
from .workspace import load_workspace


def show_model_status(args):
  workspace = load_workspace(args.local, args.profile, allow_missing_local_values=True)
  data = workspace.resolved.data
  document = read_local_document(args.local)
  verbose = getattr(args, "verbose", False)
  missing_urls = dict(workspace.resolved.missing_local_values)
  default_providers = set(workspace.default_providers)
  rows, missing_keys, locations, readiness = [], {}, {}, {}
  for provider_id, provider in data["providers"].items():
    models = [model for model in data["models"].values() if model["provider"] == provider_id]
    origin = "全局默认" if provider_id in default_providers else "profile 扩展"
    if provider["auth_kind"] == "api-key":
      reference = provider["credential_ref"]
      ready = workspace.secret_store.resolve(SecretRef(reference), required=False) is not None
      key_state = "已填写" if ready else "未填写"
      name = reference.removeprefix("secret:")
      path = key_location(document, args.local, name)
      section = credential_section(document, args.local, name, provider_id=provider_id)
      location = (path, section_label(section))
      fields = locations.setdefault(location, {})
      fields.setdefault(name, []).append(provider_id)
      if not ready:
        missing_keys.setdefault(name, provider_id)
    else:
      ready = True
      key_state = "原生登录"
    readiness[provider_id] = ready
    address = "未填写" if provider_id in missing_urls else (
      "已配置" if provider.get("base_url") else "原生管理")
    rows.append((provider_id, origin, address, key_state, len(models)))

  print(f"模型配置  {workspace.agent} / {workspace.profile}")
  pending = []
  if missing_urls:
    pending.append(f"{len(set(missing_urls.values()))} 个地址待填写（阻止部署）")
  if missing_keys:
    pending.append(f"{len(missing_keys)} 个 key 未填写（对应模型不可调用）")
  print("  " + ("；".join(pending) if pending else "未发现 URL / key 缺项"))
  print("  配置视图；未检查部署同步、账号登录或服务连通性。\n")
  table(("Provider", "来源", "地址", "认证", "模型数"), rows)

  role_rows = []
  for role, model_id in data["profile"]["roles"].items():
    model = data["models"][model_id]
    pending = []
    if model["provider"] in missing_urls:
      pending.append("缺 URL")
    if not readiness[model["provider"]]:
      pending.append("缺 key")
    role_rows.append((role, model["provider"], model["remote_id"], "、".join(pending) or "—"))
  if role_rows:
    print("\n角色绑定")
    table(("角色", "Provider", "模型", "待处理"), role_rows)

  print("\n填写位置（可直接用编辑器修改）")
  print(f"  机器配置：{args.local}")
  names = list(dict.fromkeys(name for _, name in workspace.resolved.local_value_refs))
  if names:
    print("    [local_values] " + ", ".join(names))
  printed = None
  for (path, label), fields in locations.items():
    if path != printed:
      print(f"  {'旧机器密钥' if path == args.local else '密钥文件'}：{path}")
      printed = path
    print(f"    {label}")
    for name, providers in fields.items():
      print(f"      {name} ← " + ", ".join(providers))
  if not locations:
    print(f"  密钥文件：{secrets_path(document, args.local)}（当前无静态 key 引用）")

  if verbose:
    print("\n完整模型目录")
    for provider_id in data["providers"]:
      models = [model["remote_id"] for model in data["models"].values() if model["provider"] == provider_id]
      print(f"  {provider_id}")
      for model in models or ["原生动态目录"]:
        print("    " + model)
    if missing_urls or missing_keys:
      print("\n逐项填写命令（隐藏输入）")
      for provider_id in missing_urls:
        print("  " + command_line(args, "model", "url", provider_id, profile=workspace.profile))
      for name, provider_id in missing_keys.items():
        alias = name.removesuffix("_key") if name in {"deepseek_key", "kimi_key", "glm_key"} else provider_id
        print("  " + command_line(args, "model", "key", alias, profile=workspace.profile))
    print("\n密钥名在文件中唯一；同一引用可供多个工具和 profile 共用，分组用于辨识。")
  else:
    print("\n完整目录与逐项填写命令：")
    print("  " + command_line(args, "model", "status", "--verbose", profile=workspace.profile))
  print("仅修改 key：重新 run；修改 URL、模型或其他配置：退出工具后 setup，再 run。")
  return 0

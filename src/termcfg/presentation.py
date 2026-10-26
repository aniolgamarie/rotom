"""终端结果的允许字段投影；只消费本次已有事实，不读取文件或终端。"""

import re
import unicodedata


_COMMANDS = frozenset(("components", "init-local", "status", "doctor", "plan", "apply",
                       "sync", "lock", "recover", "rollback", "rollback-plan", "migrate"))
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_ENVIRONMENT_REASONS = {
  "invalid_home": "环境 HOME 无效；须设置非空的字面绝对路径，不查询账户目录或自动修正。",
  **{"invalid_" + name.lower(): f"环境 {name} 无效；非空时必须是字面绝对路径，不展开 ~/ 或变量。"
     for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")},
}
_REASONS = {
  **_ENVIRONMENT_REASONS,
  "invalid_arguments": "参数无效；请使用下面的局部帮助，不会自动修正或执行。",
  "invalid_machine_id": "机器名称无效；仅使用合法 ID，不接受路径。",
  "machine_missing": "所选机器尚未初始化。",
  "machine_exists": "机器已经存在；修改选择需显式 --edit。",
  "selection_required": "非交互调用必须显式提供 --component 或 --none。",
  "empty_selection": "当前没有选择组件；先明确选择，不自动扩展部署范围。",
  "duplicate_component": "组件重复；每个组件只选择一次。",
  "component_and_none_conflict": "--none 与 --component 不能同时使用。",
  "invalid_timeout": "下载超时必须在 10–3600 秒之间。",
  "plugin_required": "该组件需显式 --plugin；用 lock --help 查看维护参数。",
  "plugin_add_requires_repo_entry": "新增插件还需 --repo 与 --entry；来源须在允许前缀内。",
  "invalid_plugin_version": "插件提交 ID 必须是完整的 40 位十六进制值。",
  "confirmation_declined": "已取消确认；是否存在此前影响请看下方事务/影响信息。",
  "plan_id_required": "非 TTY 执行需当前 --plan-id；请先审阅对应计划。",
  "plan_id_mismatch": "计划 ID 与当前目标不匹配；必须重新预览，不能复用其他 HOME 的计划。",
  "plan_only_conflict": "--plan-only 与执行用 --plan-id 不能同时提供。",
  "adoption_required": "目标尚未授权接管；审阅计划后显式指定 --adopt-target。",
  "zshenv_confirmation_required": "自定义 .zshenv 替换还需额外确认 --confirm-zshenv。",
  "unmanaged_target": "已有非受管目标；需显式接管，不代表同意覆盖。",
  "target_drift": "目标偏离已记录状态；先审阅漂移，不能直接覆盖。",
  "recovery_target_drift": "恢复目标已变化；保留现场，不强行恢复。",
  "rollback_target_drift": "回滚目标已变化；重新检查，不强行覆盖。",
  "recovery_pending": "存在待恢复事务；先处理恢复，再进行同步、部署或迁移。",
  "legacy_migration_required": "存在旧所有权元数据；先检查待恢复事务，再显式迁移。",
  "migration_pending": "元数据迁移尚未完成；先检查状态，再显式继续。",
  "migration_metadata_drift": "迁移元数据出现漂移；保留现场并检查，不自动覆盖。",
  "no_recovery_pending": "没有待恢复事务；本次未恢复目标。",
  "already_committed": "事务已经提交；仅清理了事务记录。",
  "already_migrated": "已经使用当前所有权元数据；无需再次迁移。",
  "no_previous_version": "没有可用的上一版备份，不能执行回滚。",
  "required_program_missing": "缺少必需程序；请自行准备对应 zsh/tmux 工具链，本工具不会自动安装。",
  "required_environment_missing": "必需环境尚有阻塞；先处理下面列出的环境/目标问题。",
  "unsupported_platform": "当前平台尚未得到支持证据；不要把离线检查视为原生验收。",
  "optional_fzf_missing": "可选 fzf 未找到；只影响对应功能，不是必需阻塞。",
  "optional_plugins_not_synced": "可选插件未准备；需要时再显式 sync（可能联网）。",
  "private_hook_conflict": "私人 hook 位置冲突；由用户明确保留位置，不自动读取或迁移正文。",
  "private_hook_invalid_config_home": "私人 hook 的 XDG 配置位置无效；请检查环境设置。",
  "private_hook_metadata_unverified": "私人 hook 元数据未验证，未读取或执行正文。",
  "possible_private_content": "目标可能含私人值；先审阅并迁到 0600 私人文件，再重新 plan。",
  "unclassified_existing_content": "旧目标内容未能安全分类；先审阅并迁走私人值，再重新 plan。",
  "invalid_asset_lock": "依赖锁无效；先检查/恢复仓库锁，重新 lock 是维护操作而非自动修复。",
  "invalid_plugin_lock": "插件锁无效；先检查/恢复仓库锁，不自动重新解析版本。",
  "source_digest_mismatch": "公开来源校验不匹配；核对仓库文件与清单，不绕过校验。",
  "lock_snapshot_changed": "依赖锁在操作期间改变；重新检查来源与已发生影响。",
  "filesystem_failure": "文件系统操作失败；请检查已发生的影响和恢复状态，不盲目重试。",
  "internal_failure": "操作未能完成；请保留现场并检查状态。",
  "interrupted": "操作被中断；请先核对部分影响和待恢复事务。",
  "operation_busy": "同一范围已有操作；不要删除租约或强制覆盖。",
}
_EFFECTS = {
  "recovery_pending": "可能已有部分目标写入；存在待恢复事务，其他变更须等待。先核对目标，不盲目重试。",
  "home_unchanged": "本次失败路径未报告 HOME 写入；不代表环境已通过检查。",
  "check_home_and_transaction_state": "可能已有目标/状态写入或恢复；先检查 HOME 和事务状态。",
  "private_package_or_selection_may_have_changed": "私人包或激活选择可能已改变；HOME 配置未由 sync 部署。",
  "package_selection_unchanged": "包选择未激活；可能已有下载或临时准备，不代表没有任何写入。",
  "check_repository_lock": "仓库锁可能已写入；先检查锁文件，不直接重复锁定。",
  "repository_lock_unchanged": "仓库锁未激活更新；可能已有下载/准备。",
}
_STATES = {"ready": "未发现必需阻塞", "blocked": "存在必需阻塞", "degraded": "降级（未发现必需阻塞）",
           "unverified": "部分事实未验证（未发现必需阻塞）"}
_ACTIONS = {"create": "新建", "replace": "替换", "unchanged": "不变", "adopt-required": "需要显式接管",
            "blocked": "阻塞", "conflict": "冲突"}


def _text(value):
  if not isinstance(value, (str, int, bool)):
    return "未知"
  text = str(value)
  result = []
  for char in text:
    if char in "\n\r\t":
      result.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[char])
    elif unicodedata.category(char) in {"Cc", "Cf", "Cs"}:
      result.append(f"\\u{ord(char):04x}")
    else:
      result.append(char)
  return "".join(result)


def _suggestion(lines, label, value, command):
  lines.append(label)
  if _text(value) != value:
    # 不解析建议字符串，也不把可见转义冒充原始 argv；仅退回已登记命令的帮助。
    lines.append("  建议含控制字符，不能原样复制；仅提供局部帮助，不改写参数。")
    help_command = "rollback" if command == "rollback-plan" else command
    value = f"./termcfg {help_command} --help" if help_command in _COMMANDS else "./termcfg --help"
  lines.append("  " + value)


def _id(value):
  return value if isinstance(value, str) and _ID.fullmatch(value) else "未知"


def _code(value):
  return value if isinstance(value, str) and _CODE.fullmatch(value) else "unknown_reason"


def _reason(value):
  code = _code(value)
  return _REASONS.get(code, f"{code}：未提供进一步解释；请保留此原因码并检查对应范围。")


def _items(value):
  return value if isinstance(value, (tuple, list)) else ()


def _ids(value):
  return "、".join(_id(item) for item in _items(value)) or "无"


def _overview(payload, command):
  if command in {"doctor", "status"}:
    if payload.get("ready") is True:
      return "检查已完成：未发现必需阻塞（仍需查看降级和未验证项）"
    if payload.get("ready") is False:
      return "需要处理；不等于所有检查均已完成"
    return "状态未知/未验证"
  if command in {"plan", "rollback-plan"} and isinstance(payload.get("targets"), list):
    return "预览已生成：先审阅目标和确认条件，不代表授权写入"
  if payload.get("ready") is not True:
    return "本次未完成或结果未验证；请先核对原因与影响"
  if command == "init-local":
    return "选择已保存；尚未部署或验证环境"
  if command == "sync":
    return "锁定的可选插件已准备；尚未部署 HOME 配置"
  if command == "lock":
    return "仓库插件锁已保存；尚未同步到机器"
  if command == "apply":
    return "无需写入；目标未改变" if payload.get("changed") == [] else "配置已写入；不代表当前会话已重新加载"
  if command == "rollback":
    return "上一版配置已恢复；不代表当前会话已重新加载"
  if command == "recover":
    return "恢复操作已完成；环境未重新检查" if payload.get("recovered") is True else _reason(payload.get("reason"))
  if command == "migrate":
    return "旧所有权元数据已迁移" if payload.get("migrated") is True else "当前元数据无需再次迁移"
  if command == "components":
    return "公开组件目录；未检查私人机器或运行环境"
  return "结果未验证"


def _scope(lines, payload, context, command):
  if command == "components":
    return
  machine = context.get("machine") or payload.get("machine_id")
  lines.append("目标机器：" + (_id(machine) if machine is not None else "未确认；不猜测默认目标"))
  components = context.get("components") or payload.get("components")
  if isinstance(components, dict):
    components = [name for name in ("zsh", "tmux") if name in components]
  component = payload.get("component")
  if not components and isinstance(component, str) and component in {"zsh", "tmux"}:
    components = (component,)
  names = [name for name in _items(components) if isinstance(name, str) and name in {"zsh", "tmux"}]
  if names:
    lines.append("组件：" + "、".join(names))
  elif command == "init-local" and payload.get("components") == []:
    lines.append("组件：已保存空选择")
  if context.get("diagnostic_home") is True:
    lines.append("范围：--home 诊断视图，不授权写入；写入前须对机器保存的目标重新 plan。")


def _recovery_and_effects(lines, payload):
  if payload.get("entry_activation") in {"activated", "possibly_activated"}:
    lines.append("入口绑定：已激活或可能已激活；收尾未完成，先 recover，不要再次 apply。")
  if payload.get("entry_transition") in {"possibly_removed", "possibly_restored", "removed", "restored"}:
    lines.append("入口绑定：恢复或移除可能已生效；收尾未完成，先 recover，再核对当前绑定。")
  if payload.get("recovery_pending") is True or payload.get("side_effect") == "recovery_pending":
    lines.append("恢复：存在待恢复事务；优先处理，其他变更须等待。")
  elif payload.get("recovery_pending") is False:
    lines.append("恢复：本次未发现待恢复事务。")
  effect = payload.get("side_effect")
  if isinstance(effect, str):
    lines.append("影响：" + _EFFECTS.get(effect, "影响未验证；请检查事务状态。"))
  if payload.get("cleanup_pending") is True:
    lines.append("注意：主要操作已完成，但备份/临时材料清理仍待处理。")
  if payload.get("stage") == "commit" and payload.get("ready") is False:
    lines.append("提交阶段：目标可能已写入或恢复；清理与最终状态未验证。")
  transaction = payload.get("transaction")
  transaction = transaction if isinstance(transaction, dict) else {}
  transaction_id = payload.get("transaction_id", transaction.get("transaction_id"))
  if transaction_id is not None:
    lines.append("事务 ID：" + _id(transaction_id))
  phase = payload.get("transaction_phase", transaction.get("phase"))
  if phase is not None:
    lines.append("事务阶段：" + _code(phase))
  for key, label in (("component", "受影响组件"), ("target_id", "受影响目标"), ("stage", "执行阶段")):
    if key in payload:
      lines.append(label + "：" + _id(payload[key]))
  for item in _items(transaction.get("items")):
    if isinstance(item, dict):
      lines.append(f"  事务目标 {_id(item.get('component'))}/{_id(item.get('target_id'))}：{_code(item.get('stage'))}")


def _environment(lines, values):
  for component in ("zsh", "tmux"):
    entry = values.get(component)
    if not isinstance(entry, dict):
      continue
    state = entry.get("status")
    lines.append(f"{component}：{_STATES.get(state, '状态未验证') if isinstance(state, str) else '状态未验证'}")
    for field, label in (("required_blockers", "必需阻塞"), ("optional_degradations", "可选降级"), ("unverified", "未验证")):
      for reason in _items(entry.get(field)):
        lines.append(f"  {label}：{_reason(reason)}")
    hooks = entry.get("private_hooks")
    if isinstance(hooks, dict) and isinstance(hooks.get("selection"), dict):
      selection = hooks["selection"]
      lines.append("  私人 hook：仅本次环境的元数据视图，未读取或执行正文。")
      for key in ("zshenv", "zshrc"):
        if key in selection:
          lines.append(f"    {key}: {_code(selection[key])}")
    files = entry.get("files")
    if isinstance(files, dict):
      for target, state in files.items():
        lines.append(f"  目标 {_id(target)}：{_code(state)}")
    issues = entry.get("target_issues")
    if isinstance(issues, dict):
      for target, reason in issues.items():
        lines.append(f"  目标问题 {_id(target)}：{_reason(reason)}")
    if "previous_backup" in entry:
      value = entry["previous_backup"]
      lines.append("  上一版备份：" + ("有记录" if value is True else "无记录" if value is False else "未知"))


def _environment_prerequisite(lines, payload, values):
  # 仅识别已采集的固定原因码；不读取环境、不改写建议或机器可读结果。
  reasons = [payload.get("reason"), payload.get("source_diagnostic")]
  for name in ("zsh", "tmux"):
    entry = values.get(name)
    if isinstance(entry, dict):
      reasons.extend(_items(entry.get("required_blockers")))
  if any(isinstance(reason, str) and reason in _ENVIRONMENT_REASONS for reason in reasons):
    lines.append("前置：先修正上述 HOME/XDG 环境路径，再运行下方建议；--home 仅改变诊断目标，不能修复环境发现。")


def _targets(lines, payload):
  if "plan_id" in payload:
    lines.append("计划 ID：" + _id(payload["plan_id"]))
  for target in _items(payload.get("targets")):
    if not isinstance(target, dict):
      continue
    name = _id(target.get("target_id"))
    if payload.get("command") == "rollback-plan":
      lines.append(f"  {name}：恢复为 {_code(target.get('restore_kind'))}")
      continue
    action = target.get("action")
    title = _ACTIONS.get(action, "动作未验证") if isinstance(action, str) else "动作未验证"
    backup = "需要备份" if target.get("backup") is True else "无旧目标备份" if target.get("backup") is False else "备份情况未知"
    lines.append(f"  {_id(target.get('component'))}/{name}：{title}；{backup}")
    if target.get("reason"):
      lines.append("    " + _reason(target["reason"]))
    binding = target.get("entry_binding")
    if isinstance(binding, dict):
      lines.append("    入口来源：" + _text(binding.get("repository")))
      previous = binding.get("previous_repository")
      lines.append("    之前来源：" + (_text(previous) if isinstance(previous, str) else "首次绑定"))
    if action == "adopt-required":
      lines.append(f"    同意接管时需显式 --adopt-target {name}；不会自动填入。")
    if name == "zshenv" and action != "unchanged":
      lines.append("    若为自定义 .zshenv，整文件替换还需额外 --confirm-zshenv 当前计划ID。")
  if payload.get("command") in {"plan", "rollback-plan"}:
    lines.append("执行边界：TTY 需审阅确认；非 TTY 需当前计划 ID；计划本身不代表同意。")


def render_result(payload, *, context=None):
  context = context if isinstance(context, dict) else {}
  command = payload.get("command")
  command = command if isinstance(command, str) and command in _COMMANDS else "结果"
  lines = [f"termcfg {command}", "结论：" + _overview(payload, command)]
  _scope(lines, payload, context, command)
  if payload.get("reason"):
    lines.append("原因：" + _reason(payload["reason"]))
  if payload.get("source_diagnostic"):
    lines.append("来源诊断：" + _reason(payload["source_diagnostic"]))
  _recovery_and_effects(lines, payload)
  values = payload.get("environment", payload.get("components", {}))
  values = values if isinstance(values, dict) else {}
  if command in {"status", "doctor", "plan"}:
    _environment(lines, values)
    lines.append("证据：本次离线检查；未启动或验证正在运行的 shell/tmux 会话。")
  if command == "components":
    for name in ("zsh", "tmux"):
      if name in values:
        lines.append(f"  {name}：{_ids(values[name])}")
  _targets(lines, payload)
  for key, label in (("changed", "已改变目标"), ("unchanged", "未改变目标"),
                     ("restored", "已恢复目标"), ("prepared", "已准备插件")):
    if key in payload:
      lines.append(label + "：" + _ids(payload[key]))
  if command == "lock":
    for key, label in (("plugin", "插件"), ("commit", "提交 ID")):
      if key in payload:
        lines.append(label + "：" + _id(payload[key]))
  if command in {"apply", "rollback", "recover"}:
    lines.append("生效：未重启或重载 shell/tmux；成功改动请在新会话中验证。")
  if command == "migrate":
    lines.append("范围：仅旧所有权元数据；未管理代理文件或服务。")
  _environment_prerequisite(lines, payload, values)
  next_command = payload.get("next_command")
  printed = set()
  if isinstance(next_command, str):
    prefix = "下一步（按上述前置条件；不是自动执行）："
    if context.get("diagnostic_home") and command == "plan":
      prefix = "下一步（先核对诊断/保存目标范围，不转用本次计划 ID）："
    _suggestion(lines, prefix, next_command, command)
    printed.add(next_command)
  for name in ("zsh", "tmux"):
    entry = values.get(name)
    if not isinstance(entry, dict):
      continue
    suggestion = entry.get("next_command")
    if not isinstance(suggestion, str) or suggestion in printed:
      continue
    optional = (not entry.get("required_blockers") and
                "optional_plugins_not_synced" in _items(entry.get("optional_degradations")))
    label = "可选准备（可能联网，不是必需步骤）" if optional else "组件建议（先满足上述前置条件）"
    if optional and context.get("diagnostic_home"):
      label = "可选插件后续检查（先对机器保存目标重新预览）"
    _suggestion(lines, f"{name} {label}：", suggestion, command)
    printed.add(suggestion)
  return "\n".join(lines)

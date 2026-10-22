"""结构化命令的稳定终端展示；JSON 模式保持脚本兼容。"""

from __future__ import annotations

import json
from pathlib import PurePath
import re
import shlex
import shutil
import sys
import unicodedata


def command_line(args, *words, profile=None):
  """重建保留调用方选择器的可复制命令。"""
  tokens = ["./agentcfg"]
  machine = getattr(args, "machine", None) if args is not None else None
  local = getattr(args, "local", None) if args is not None else None
  selected_profile = profile if profile is not None else getattr(args, "profile", None)
  if machine is not None:
    tokens.extend(("--machine", str(machine)))
  elif local is not None:
    tokens.extend(("--local", str(local)))
  if selected_profile is not None:
    tokens.extend(("--profile", str(selected_profile)))
  tokens.extend(str(word) for word in words)
  return shlex.join(tokens)


def _text(value):
  if value is None:
    return "—"
  if value is True:
    return "是"
  if value is False:
    return "否"
  value = str(value)
  result = []
  for character in value:
    if character == "\n":
      result.append("\\n")
    elif character == "\r":
      result.append("\\r")
    elif character == "\t":
      result.append("\\t")
    elif unicodedata.category(character) == "Cc":
      result.append("?")
    else:
      result.append(character)
  return "".join(result)


def _display_width(value):
  width = 0
  for character in value:
    if unicodedata.combining(character):
      continue
    width += 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1
  return width


def _pad(value, width):
  return value + " " * max(0, width - _display_width(value))


def table(headings, rows, *, stream=None, width=None):
  """输出无样式表格；空间不足时逐条纵向展示且不截断内容。"""
  stream = sys.stdout if stream is None else stream
  headings = tuple(_text(item) for item in headings)
  records = [tuple(_text(item) for item in row) for row in rows]
  if any(len(row) != len(headings) for row in records):
    raise ValueError("table-column-count")
  if not headings:
    return ""
  available = width
  if available is None:
    available = shutil.get_terminal_size(fallback=(100, 24)).columns
  widths = [max([_display_width(heading), *(_display_width(row[index]) for row in records)])
            for index, heading in enumerate(headings)]
  required = sum(widths) + 3 * (len(headings) - 1)
  lines = []
  if required <= max(1, available):
    lines.append(" | ".join(_pad(heading, widths[index]) for index, heading in enumerate(headings)))
    lines.append("-+-".join("-" * column_width for column_width in widths))
    lines.extend(" | ".join(_pad(value, widths[index]) for index, value in enumerate(row))
                 for row in records)
  elif not records:
    lines.append("无条目")
  else:
    for item_index, row in enumerate(records, start=1):
      if item_index > 1:
        lines.append("")
      lines.append(f"条目 {item_index}")
      lines.extend(f"{heading}: {value}" for heading, value in zip(headings, row))
  rendered = "\n".join(lines)
  if rendered:
    print(rendered, file=stream)
  return rendered


def _scalar(value):
  return value if isinstance(value, (str, int, float, bool)) or value is None else None


def _dependency(value):
  if value is None:
    return None
  if _scalar(value) is not None:
    return _text(value)
  if isinstance(value, dict):
    for key in ("status", "installed", "ready"):
      if key in value and _scalar(value[key]) is not None:
        return _text(value[key])
  return "见 JSON 详情"


def _public_list(value):
  if isinstance(value, list) and all(isinstance(item, str) for item in value):
    return "、".join(_text(item) for item in value) if value else "无"
  return value


def _target(payload):
  parts = [_text(payload[key]) for key in ("agent", "profile") if payload.get(key) is not None]
  return " / ".join(parts) if parts else "未指定"


def _write_fields(fields, stream):
  # 调用方必须显式提炼结构值；通用字段表不展开未知容器。
  rows = [(label, value) for label, value in fields
          if value is not None and isinstance(value, (str, int, float, bool))]
  if rows:
    labels = [str(label) for label, _ in rows]
    width = max(_display_width(label) for label in labels)
    for label, (_, value) in zip(labels, rows):
      print(f"{_pad(label, width)}  {_text(value)}", file=stream)


def _location_rows(payload, limit=8):
  rows = []
  for group, label in (("conflict_targets", "冲突"), ("drift_targets", "漂移"), ("diff", "变更")):
    entries = payload.get(group)
    if not isinstance(entries, list):
      continue
    for entry in entries:
      if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
        continue
      rows.append((label, entry["id"], entry.get("target"), entry.get("field"), entry.get("action")))
      if len(rows) == limit:
        return rows
  return rows


_BLOCKER_LABELS = {
  "recovery-pending": "存在待恢复的部署操作",
  "dependencies-sync-required": "当前依赖需要同步",
  "dependencies-missing": "当前依赖缺失",
  "dependencies-unknown": "当前依赖状态未知",
  "not-deployed": "尚未部署配置",
  "deployed-dependencies-unavailable": "已部署版本所需依赖不可用",
  "deployed-binding-mismatch": "当前运行选择与已部署契约不匹配",
  "deployment-conflict-or-drift": "部署目标存在冲突或漂移",
  "changes-pending": "配置有待部署变更",
  "lock-missing-or-invalid": "依赖锁缺失或无效",
}


def _blocker_labels(blockers):
  if not isinstance(blockers, list):
    return []
  labels = []
  for blocker in blockers:
    code = blocker.get("code") if isinstance(blocker, dict) else blocker
    if not isinstance(code, str):
      continue
    label = _BLOCKER_LABELS.get(code)
    if label is None:
      label = "存在其他阻塞项（详情见 JSON）"
    if label not in labels:
      labels.append(label)
  return labels


def _service_summary(service_checks):
  """提炼 live 检查的公开位置和固定状态，不输出 URL、路线或异常。"""
  if not isinstance(service_checks, list):
    return [], {"total": 0, "reachable": 0, "unverified": 0}
  reasons = {"endpoint-unavailable": "无可检查端点",
    "proxy-authentication-not-inspected": "代理认证未检查",
    "proxy-probe-transport-unavailable": "代理探测传输不支持",
    "endpoint-unreachable": "端点不可达或未验证",
    "explicit-route-required": "需要显式网络路线",
    "native-service-not-inspected": "原生服务未检查",
    "public-target-not-selected": "未选择公开探测目标"}
  rows = []
  counts = {"total": len(service_checks), "reachable": 0, "unverified": 0}
  for check in service_checks:
    if isinstance(check, str):
      status = check if check in ("reachable", "unverified") else "unverified"
      counts[status] += 1
      continue
    if not isinstance(check, dict):
      counts["unverified"] += 1
      continue
    status = check.get("status") if check.get("status") in ("reachable", "unverified") else "unverified"
    counts[status] += 1
    location = check.get("location_id")
    if not isinstance(location, str) or not re.fullmatch(r"(?:provider|route|service):[0-9a-f]{20}", location):
      location = "公开位置不可用"
    http_status = check.get("http_status")
    if type(http_status) is not int or not 100 <= http_status <= 599:
      http_status = None
    rows.append((location, "HTTP 可达" if status == "reachable" else "未验证",
      http_status, reasons.get(check.get("reason"), "—" if status == "reachable" else "其他原因见 JSON")))
  return rows, counts


def _command_suggestions(payload, args, readiness=None, *, commands=None):
  readiness = payload.get("readiness") if readiness is None else readiness
  if not isinstance(readiness, dict):
    return []
  result = []
  for action in readiness.get("next_commands", []):
    if not isinstance(action, str):
      continue
    choices = ("apply", "rollback") if action == "apply-or-rollback" else (action,)
    for choice in choices:
      try:
        words = shlex.split(choice)
      except ValueError:
        continue
      supported = (len(words) == 1 and words[0] in ("setup", "sync", "plan", "apply", "rollback")
        or len(words) == 3 and words[:2] == ["lock", "--agent"] and words[2] in ("dsh", "pi", "omp"))
      if supported and (commands is None or words[0] in commands):
        result.append(command_line(args, *words, profile=payload.get("profile")))
  return result


def _render_plan(payload, stream):
  if payload.get("mode") == "migration-preview" or payload.get("ready_to_deploy") is False:
    print("plan：迁移提案已生成（尚未部署）", file=stream)
    _write_fields((("目标", _target(payload)), ("盘点条目", payload.get("items")),
      ("阻塞项", payload.get("blockers")), ("提案文件", payload.get("proposal"))), stream)
    return
  conflicts = payload.get("conflicts", 0)
  drift = payload.get("drift", 0)
  title = "存在冲突" if conflicts else "发现漂移" if drift else "计划已就绪"
  print(f"plan：{title}", file=stream)
  _write_fields((("目标", _target(payload)), ("待变更", payload.get("changes")),
    ("漂移", drift), ("冲突", conflicts), ("依赖", _dependency(payload.get("dependencies"))),
    ("诊断定位文件", payload.get("diagnostics"))), stream)
  rows = _location_rows(payload)
  if rows:
    print("定位条目（最多 8 项）:", file=stream)
    table(("类型", "位置 ID", "目标", "字段", "动作"), rows, stream=stream)


def _identity_summary(identity):
  """仅投影已采集的固定身份状态；不读取路径或推断已部署环境。"""
  if not isinstance(identity, dict):
    return [], False
  fields = []
  blocked = identity.get("layout_conflict") == "xdg-or-identity-layout-conflict"
  if blocked:
    fields.append(("身份布局", "XDG 或身份布局冲突"))
  execution = identity.get("planned_execution_environment")
  if isinstance(execution, dict) and execution.get("scope") == "planned-not-deployed":
    fields.append(("计划环境范围", "仅计划，非已部署环境验证"))
    if execution.get("status") == "ready":
      fields.append(("计划环境状态", "计划路径检查通过"))
    elif execution.get("status") == "path-conflict":
      fields.append(("计划环境状态", "计划路径冲突"))
      blocked = True
  return fields, blocked


def _doctor_conditions(payload, readiness):
  """只按已收集事实排列提示，不重新计算 readiness 或探测状态。"""
  blockers = readiness.get("blockers")
  codes = set()
  for item in blockers if isinstance(blockers, list) else []:
    code = item.get("code") if isinstance(item, dict) else item
    if isinstance(code, str):
      codes.add(code)
  pending = payload.get("recovery_pending") is True or "recovery-pending" in codes
  lock_bad = payload.get("lock") == "missing-or-invalid" or "lock-missing-or-invalid" in codes
  return pending, lock_bad


def _doctor_actions(payload, args, readiness, stream, *, pending, lock_bad, identity_blocked):
  """恢复选项是备选，依赖重建是维护；均不得伪装成无条件操作序列。"""
  if pending:
    choices = _command_suggestions(payload, args, readiness, commands={"apply", "rollback"})
    if choices:
      print("先处理部署恢复（备选，不是依次执行；请先核对恢复意图）:", file=stream)
      for suggestion in choices:
        print(f"- {suggestion}", file=stream)
    else:
      print("本次报告未提供可执行的恢复选择；先核对所选配置、依赖锁与部署恢复记录。", file=stream)
  ordinary = _command_suggestions(payload, args, readiness,
    commands={"setup", "sync", "plan"} if pending else {"setup", "sync", "plan", "apply", "rollback"})
  if ordinary:
    label = ("恢复完成后重新诊断，再评估（不是当前执行顺序）:" if pending else
      "依赖锁恢复并重新诊断后再评估:" if lock_bad else
      "身份或计划环境冲突处理并重新诊断后再评估:" if identity_blocked else "下一步:")
    print(label, file=stream)
    for suggestion in ordinary:
      print(f"- {suggestion}", file=stream)
  maintenance = _command_suggestions(payload, args, readiness, commands={"lock"})
  if maintenance:
    prefix = "恢复完成后，" if pending else ""
    print(prefix + "仅在有意重新解析依赖时考虑（不是普通修复）:", file=stream)
    for suggestion in maintenance:
      print(f"- {suggestion}", file=stream)


def _render_doctor(payload, args, stream):
  readiness = payload.get("readiness")
  input_diagnostics = payload.get("input_diagnostics")
  if not isinstance(readiness, dict) and isinstance(input_diagnostics, dict):
    readiness = input_diagnostics.get("readiness")
  readiness = readiness if isinstance(readiness, dict) else {}
  status = readiness.get("status", "unknown")
  pending, lock_bad = _doctor_conditions(payload, readiness)
  identity_fields, identity_blocked = _identity_summary(payload.get("identity"))
  live = payload.get("live") is True
  service_rows, service_counts = _service_summary(payload.get("service_checks")) if live else ([], {})
  if live:
    if status != "offline-ready" or pending or lock_bad or identity_blocked:
      title = "在线检查完成，仍需处理"
    elif service_counts.get("unverified"):
      title = "在线检查完成，部分未验证"
    else:
      title = "在线检查完成"
  elif status != "offline-ready" or pending or lock_bad or identity_blocked:
    title = "需要处理"
  else:
    title = "离线就绪"
  print(f"doctor：{title}", file=stream)
  machine = getattr(args, "machine", None)
  local = getattr(args, "local", None)
  _write_fields((("机器", machine),
    ("本地配置", str(local) if machine is None and isinstance(local, (str, PurePath)) else None),
    ("目标", _target(payload)),
    ("检查范围", "本次显式在线检查；不等同账号或模型验证" if live else "本次离线诊断；不代表在线可用")), stream)
  if pending:
    print("恢复前置：存在待恢复的部署；暂缓普通同步、更新与启动，先核对恢复选择。", file=stream)
  if lock_bad:
    print("锁前置：核对或恢复所选仓库的依赖锁；不要将重建锁当成普通修复。", file=stream)
  if identity_blocked:
    print("身份前置：存在身份布局或计划执行环境路径冲突；暂缓启动与普通部署，先核对所选身份和环境布局，处理后重新诊断。", file=stream)
  _write_fields(identity_fields, stream)
  readiness_labels = ({"offline-ready": "基础部署检查通过", "action-required": "基础部署需要处理"}
    if live else {"offline-ready": "基础部署离线就绪", "action-required": "基础部署需要处理"})
  readiness_label = readiness_labels.get(status, "状态未知")
  if identity_blocked:
    readiness_label += "；身份或计划环境仍有冲突"
  _write_fields((("就绪状态", readiness_label),
    ("已部署", payload.get("deployed")), ("前版备份", payload.get("previous_backup")),
    ("依赖", _dependency(payload.get("dependencies"))),
    ("已部署依赖", _dependency(payload.get("deployed_dependencies"))),
    ("部署契约匹配", payload.get("deployed_binding_matches_current")),
    ("漂移", payload.get("drift")), ("冲突", payload.get("conflicts")),
    ("待变更", payload.get("changes_pending")), ("待恢复", payload.get("recovery_pending")),
    ("依赖锁", payload.get("lock")), ("诊断定位文件", payload.get("diagnostics"))), stream)
  verification = payload.get("verification")
  if isinstance(verification, dict):
    labels = {"passed": "已验证", "failed": "验证失败", "blocked": "受阻",
      "not_run": "未执行", "not_inspected": "未检查"}
    _write_fields(((label, labels.get(verification.get(stage), "未知")) for stage, label in (
      ("configuration", "配置声明"), ("dependencies", "依赖准备"), ("deployment", "配置部署"),
      ("loading", "资源加载"), ("account", "账号验证"), ("runtime", "运行验证"))), stream)
  features = payload.get("feature_readiness")
  if isinstance(features, dict):
    print("功能声明（不代表已加载）:", file=stream)
    rows = []
    for key, label in (("status_bar", "状态栏信息对齐"), ("collaboration", "Pro调查协作"), ("optional_modules", "按需模块")):
      value = features.get(key)
      value = value if isinstance(value, dict) else {}
      status = {"not_ready": "未就绪", "not_selected": "未选择"}.get(value.get("status"), "未知")
      decision = {"held": "暂停准入", "candidate": "候选"}.get(value.get("decision"), "未知")
      rows.append((label, status + "；" + decision))
    _write_fields(rows, stream)
  approvals = payload.get("approval_review")
  if isinstance(approvals, dict) and approvals.get("scope") == "configuration-preview":
    print("审批配置预览（不代表当前会话状态）:", file=stream)
    def approval_number(name):
      value = approvals.get(name)
      return value if type(value) is int and value >= 0 else "未知"
    enabled = approvals.get("enabled") is True
    escalation = approvals.get("sandbox_escalation") is True
    _write_fields((("Perry 配置", "启用" if enabled else "停用"),
      ("待批沙箱提权", "AI 审查" if enabled and escalation else "人工处理"),
      ("审查超时（毫秒）", approval_number("reviewer_timeout_ms")),
      ("每回合审查预算", approval_number("max_reviews_per_turn")),
      ("每回合失败预算", approval_number("max_failures_per_turn")),
      ("审查失败", "转人工" if approvals.get("fallback_policy") == "delegate" else "未知"),
      ("完整 AI 判决持久审计", "不支持" if approvals.get("persistent_verdict_audit") == "unsupported" else "未验证"),
      ("当前会话的实际分流与回退原因", "未检查")), stream)
  if live:
    _write_fields((("在线服务检查", service_counts.get("total")),
      ("HTTP 可达", service_counts.get("reachable")), ("未验证", service_counts.get("unverified")),
      ("账号登录与模型调用", "未验证；在线检查只验证显式路线的 HTTP 可达性")), stream)
  else:
    _write_fields((("账号登录与模型服务", "未验证；请使用原生状态检查"),), stream)
  environment = payload.get("environment")
  if isinstance(environment, dict):
    _write_fields((("环境诊断", {"host-preview": "宿主启动预览，不包含变量值",
      "not-deployed": "尚未部署"}.get(environment.get("status"), "未知")),
      ("环境策略", {"caller": "调用者开发环境", "isolated": "独立宿主，开发工具使用单独边界",
        "legacy": "旧版契约，需 plan/apply 迁移"}.get(environment.get("policy"))),
      ("环境声明待部署", environment.get("declarations_pending")),
      ("受保护输入数量", environment.get("sensitive_excluded"))), stream)
    from .config import _credential_name
    reasons = {"caller": "调用者", "machine-inherit": "机器继承", "machine-value": "机器固定值",
      "machine-editor": "机器编辑器", "machine-unset": "机器删除", "one-shot-inherit": "本次继承",
      "one-shot-unset": "本次删除", "adapter-policy": "适配器策略", "not-inherited": "未声明继承"}
    rows = []
    for item in environment.get("variables", []):
      if not isinstance(item, dict):
        continue
      name = item.get("name")
      if (not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
          or _credential_name(name) or name.startswith(("AGENTCFG_", "DSH_"))):
        continue
      rows.append((name, {"removed": "删除", "overridden": "覆盖"}.get(item.get("status"), "未知"),
        reasons.get(item.get("source"), "未知")))
    if rows:
      table(("变量名称", "处理", "原因"), rows, stream=stream)
    print("环境诊断不读取凭据；下游工具行为以对应原生验收范围为准。", file=stream)
  blockers = _blocker_labels(readiness.get("blockers"))
  if blockers:
    print("需要处理的原因:", file=stream)
    for blocker in blockers:
      print(f"- {blocker}", file=stream)
  _doctor_actions(payload, args, readiness, stream, pending=pending, lock_bad=lock_bad,
    identity_blocked=identity_blocked)
  if live and service_rows:
    print("在线服务检查:", file=stream)
    table(("位置 ID", "状态", "HTTP", "说明"), service_rows, stream=stream)
  if isinstance(input_diagnostics, dict):
    terminal = input_diagnostics.get("diagnostic_terminal")
    if isinstance(terminal, dict):
      _write_fields((("诊断 stdin 为终端", terminal.get("stdin_tty")),
        ("规范输入", terminal.get("canonical")), ("输入回显", terminal.get("echo")),
        ("终端信号", terminal.get("signals"))), stream)
    host = input_diagnostics.get("host_events")
    if isinstance(host, dict):
      status_labels = {"not-available": "当前后端不提供受管输入事件",
        "not-checked": "尚未检查宿主输入事件"}
      _write_fields((("宿主输入诊断", status_labels.get(host.get("status"))),
        ("OMP 日志存在", host.get("logs_present")), ("已检查日志", host.get("logs_checked")),
        ("日志读取状态", {"some-logs-unavailable": "部分日志不可用",
          "unavailable-or-unsafe": "日志不可用或不安全"}.get(host.get("logs_status"))),
        ("循环阻塞事件", len(host["loop_blocks"]) if isinstance(host.get("loop_blocks"), list) else None)), stream)
      events = []
      for event in host.get("loop_blocks", [])[-5:] if isinstance(host.get("loop_blocks"), list) else []:
        if not isinstance(event, dict):
          continue
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?[+-]\d{2}:\d{2}", timestamp):
          timestamp = "未知"
        phase = event.get("phase") if event.get("phase") in (
          "layout", "paint", "render", "ui.select-filter", "unknown") else "unknown"
        numbers = [event.get(key) for key in ("pid", "blocked_ms", "cpu_ms")]
        if not all(type(value) is int and 0 <= value <= 1_000_000_000 for value in numbers):
          continue
        events.append((timestamp, {"layout": "布局", "paint": "绘制", "render": "渲染",
          "ui.select-filter": "选择筛选", "unknown": "未知"}[phase], *numbers))
      if events:
        print("最近循环阻塞事件（最多 5 项）:", file=stream)
        table(("时间", "阶段", "PID", "阻塞 ms", "CPU ms"), events, stream=stream)
      if "note" in input_diagnostics:
        print("诊断说明: 当前终端标志不记录按键，也不能证明原生宿主已收到输入。", file=stream)
      if "note" in host:
        print("OMP 建议: 结合状态栏检查 Vim 输入状态；诊断不记录按键。", file=stream)


def _render_human(payload, args, stream):
  command = payload.get("command")
  if command == "plan":
    _render_plan(payload, stream)
  elif command == "doctor":
    _render_doctor(payload, args, stream)
  else:
    titles = {
      "validate": "配置有效" if payload.get("valid") is True else "配置未通过校验",
      "render": "原生产物已生成",
      "apply": "部署结果",
      "sync": "依赖同步完成",
      "rollback": "上一版已恢复" if payload.get("restored") is not None else "没有确认恢复结果",
      "lock": "依赖锁已生成" if payload.get("locked") is True else "依赖锁未生成",
      "capture": "捕获提案已生成（尚未部署）",
      "inventory": "盘点提案已生成（尚未部署）",
    }
    print(f"{_text(command or '结果')}：{titles.get(command, '命令已返回结果')}", file=stream)
    fields = {
      "validate": (("目标", _target(payload)), ("产物", payload.get("artifacts")),
        ("已检查 profile", _public_list(payload.get("profiles_checked"))),
        ("凭据", {"not-checked-offline": "未检查（离线）"}.get(
          payload.get("credentials"), payload.get("credentials")))),
      "render": (("目标", _target(payload)), ("产物", payload.get("artifacts")), ("缓存目录", payload.get("cache"))),
      "apply": (("目标", _target(payload)), ("变更", payload.get("changes")),
        ("漂移", payload.get("drift")), ("冲突", payload.get("conflicts"))),
      "sync": (("目标", _target(payload)), ("本次安装", payload.get("installed")),
        ("状态", payload.get("status")), ("发生变化", payload.get("changed")), ("运行包 ID", payload.get("identity"))),
      "rollback": (("目标", _target(payload)), ("已恢复项", payload.get("restored"))),
      "lock": (("目标", _target(payload)), ("锁定完成", payload.get("locked"))),
      "capture": (("目标", _target(payload)), ("捕获字段", payload.get("captured_fields")), ("提案文件", payload.get("proposal"))),
      "inventory": (("目标", _target(payload)), ("盘点条目", payload.get("items")),
        ("可直接部署", payload.get("ready_to_deploy")), ("提案目录", payload.get("proposal"))),

    }
    _write_fields(fields.get(command, (("目标", _target(payload)),)), stream)
  if command in ("plan", "doctor"):
    print("完整字段请使用 --format json。", file=stream)


def emit_result(payload, *, args=None):
  """按显式格式或 stdout 终端状态输出一个结果，不修改 payload。"""
  mode = (getattr(args, "format", None) if args is not None else None) or "auto"
  if mode not in ("auto", "human", "json"):
    raise ValueError("result-format")
  stream = sys.stdout
  human = mode == "human" or mode == "auto" and stream.isatty()
  if not human:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stream)
    return
  _render_human(payload, args, stream)

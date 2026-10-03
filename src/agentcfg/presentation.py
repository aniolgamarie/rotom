"""结构化命令的稳定终端展示；JSON 模式保持脚本兼容。"""

from __future__ import annotations

import json
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
  "deployment-conflict-or-drift": "部署目标存在冲突或漂移",
  "changes-pending": "配置有待部署变更",
  "lock-missing-or-invalid": "依赖锁缺失或无效",
}

_CAPABILITY_BLOCKERS = {
  "PI_MODEL_UNBOUND": "主模型尚未绑定",
  "PI_DEPLOYMENT_MISSING": "能力尚未部署",
  "PI_DEPENDENCIES_MISSING": "能力依赖缺失",
  "PI_LOAD_FAILED": "原生加载验证失败",
  "PI_AUTHENTICATION_FAILED": "认证验证失败",
  "PI_EXECUTION_FAILED": "原生执行验证失败",
  "PI_AUTHENTICATION_PENDING": "等待原生登录",
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


def _capability_summary(capabilities):
  """提炼 Pi 公共能力诊断；不展开 admission、时间或未知嵌套值。"""
  if not isinstance(capabilities, list):
    return [], False
  rows = []
  has_blockers = False
  states = {"installed": "已安装", "sync-required": "需同步", "missing": "缺失",
    "not-selected": "未选择", "not-run": "未运行", "verified": "已验证", "stale": "已过期",
    "not-inspected": "未检查", "not-required": "无需检查", "observed-ready": "已观察就绪",
    "pending-login": "等待登录"}
  for row in capabilities:
    if not isinstance(row, dict) or row.get("selected") is not True:
      continue
    identifier = row.get("id")
    location = row.get("location_id")
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9:._-]{0,79}", identifier):
      identifier = "已选择能力"
    if not isinstance(location, str) or not re.fullmatch(r"capability:[0-9a-f]{20}", location):
      location = "—"
    raw_blockers = row.get("blockers")
    blocker_labels = []
    if isinstance(raw_blockers, list):
      for blocker in raw_blockers:
        label = _CAPABILITY_BLOCKERS.get(blocker) if isinstance(blocker, str) else None
        if label is None:
          label = "存在其他能力阻塞（详情见 JSON）"
        if label not in blocker_labels:
          blocker_labels.append(label)
    dependency_blocking = row.get("dependencies") != "installed"
    if dependency_blocking and "能力依赖缺失" not in blocker_labels:
      blocker_labels.append("能力依赖未安装")
    has_blockers = has_blockers or bool(blocker_labels) or dependency_blocking
    def state(key):
      value = row.get(key)
      return states.get(value, "未知")
    rows.append((identifier, _text(row.get("configured")) if type(row.get("configured")) is bool else "未知",
      _text(row.get("deployed")) if type(row.get("deployed")) is bool else "未知",
      state("dependencies"), state("load_evidence"), state("execution_evidence"),
      state("authentication"), "、".join(blocker_labels) if blocker_labels else "无", location))
  return rows, has_blockers


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


def _count_summary(value):
  """只输出数量和固定状态汇总，不展开身份、路径或未知结构。"""
  if type(value) is int and value >= 0:
    return value
  if isinstance(value, (list, tuple, set)):
    return len(value)
  if not isinstance(value, dict):
    return None
  total = value.get("count", value.get("total"))
  if type(total) is not int or total < 0:
    total = None
  statuses = {"active": "活动", "pending": "待处理", "terminated": "已终止",
    "released": "已释放", "protected": "受保护", "unknown": "未知"}
  status_values = [child for child in value.values() if isinstance(child, str)]
  if total is None and status_values and len(status_values) == len(value) and all(
      child in statuses for child in status_values):
    total = len(value)
  if total is None:
    for key in ("items", "ids", "processes", "leases", "work"):
      if isinstance(value.get(key), list):
        total = len(value[key])
        break
  parts = [str(total)] if total is not None else []
  for key, label in (("active", "活动"), ("pending", "待处理"), ("protected", "受保护")):
    child = value.get(key)
    if type(child) is int and child >= 0:
      parts.append(f"{label} {child}")
    elif key == "protected" and type(child) is bool:
      parts.append(f"{label} {_text(child)}")
  counts = {}
  for child in value.values():
    if isinstance(child, str) and child in statuses:
      counts[child] = counts.get(child, 0) + 1
  parts.extend(f"{statuses[key]} {counts[key]}" for key in statuses if counts.get(key))
  return "；".join(parts) if parts else "结构化保护信息见 JSON"


def _command_suggestions(payload, args, readiness=None):
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
      if supported:
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


def _render_doctor(payload, args, stream):
  readiness = payload.get("readiness")
  input_diagnostics = payload.get("input_diagnostics")
  if not isinstance(readiness, dict) and isinstance(input_diagnostics, dict):
    readiness = input_diagnostics.get("readiness")
  readiness = readiness if isinstance(readiness, dict) else {}
  status = readiness.get("status", "unknown")
  capability_rows, capability_blocked = _capability_summary(payload.get("capabilities"))
  live = payload.get("live") is True
  service_rows, service_counts = _service_summary(payload.get("service_checks")) if live else ([], {})
  if live:
    if status != "offline-ready" or capability_blocked:
      title = "在线检查完成，仍需处理"
    elif service_counts.get("unverified"):
      title = "在线检查完成，部分未验证"
    else:
      title = "在线检查完成"
  elif status != "offline-ready" or capability_blocked:
    title = "需要处理"
  else:
    title = "离线就绪"
  print(f"doctor：{title}", file=stream)
  readiness_labels = ({"offline-ready": "基础部署检查通过", "action-required": "基础部署需要处理"}
    if live else {"offline-ready": "基础部署离线就绪", "action-required": "基础部署需要处理"})
  readiness_label = readiness_labels.get(status, "状态未知")
  if capability_blocked:
    readiness_label += "；能力项仍有阻塞"
  _write_fields((("目标", _target(payload)), ("就绪状态", readiness_label),
    ("已部署", payload.get("deployed")), ("依赖", _dependency(payload.get("dependencies"))),
    ("已部署依赖", _dependency(payload.get("deployed_dependencies"))),
    ("漂移", payload.get("drift")), ("冲突", payload.get("conflicts")),
    ("待变更", payload.get("changes_pending")), ("待恢复", payload.get("recovery_pending")),
    ("依赖锁", payload.get("lock")), ("诊断定位文件", payload.get("diagnostics"))), stream)
  if live:
    _write_fields((("在线服务检查", service_counts.get("total")),
      ("HTTP 可达", service_counts.get("reachable")), ("未验证", service_counts.get("unverified")),
      ("账号登录与模型调用", "未验证；在线检查只验证显式路线的 HTTP 可达性")), stream)
  elif status == "offline-ready" and not capability_blocked:
    _write_fields((("账号登录与模型服务", "未验证；请使用原生状态检查"),), stream)
  blockers = _blocker_labels(readiness.get("blockers"))
  if blockers:
    print("需要处理的原因:", file=stream)
    for blocker in blockers:
      print(f"- {blocker}", file=stream)
  suggestions = _command_suggestions(payload, args, readiness)
  if suggestions:
    print("下一步:", file=stream)
    for suggestion in suggestions:
      print(f"- {suggestion}", file=stream)
  if capability_rows:
    blocked_rows = [(row[0], row[-2], row[-1]) for row in capability_rows if row[-2] != "无"]
    print(f"已选择能力: {len(capability_rows)} 项；阻塞 {len(blocked_rows)} 项（加载与执行证据见 JSON）。", file=stream)
    if blocked_rows:
      print("能力阻塞（最多 8 项）:", file=stream)
      table(("能力", "原因", "位置 ID"), blocked_rows[:8], stream=stream)
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


def _render_recover(payload, stream):
  blockers = payload.get("blockers")
  if isinstance(blockers, list) and blockers:
    title = "恢复受阻"
  elif "plan_digest" in payload:
    title = "停止恢复计划已生成（尚未执行）"
  else:
    title = f"恢复结果：{_text(payload.get('state', '已处理'))}"
  print(f"recover：{title}", file=stream)
  _write_fields((("目标", _target(payload)), ("执行记录", payload.get("lease_id")),
    ("计划类型", payload.get("plan_kind")), ("计划摘要", payload.get("plan_digest")),
    ("有效期", payload.get("expires_at")), ("目标进程", _count_summary(payload.get("target_processes"))),
    ("外部工作", _count_summary(payload.get("external_work"))),
    ("工作区租约", _count_summary(payload.get("workspace_leases"))),
    ("状态", payload.get("state")), ("保护保持", payload.get("protected"))), stream)
  blocker_labels = _blocker_labels(blockers)
  if blocker_labels:
    print("阻塞原因:", file=stream)
    for blocker in blocker_labels:
      print(f"- {blocker}", file=stream)


def _render_human(payload, args, stream):
  command = payload.get("command")
  if command == "plan":
    _render_plan(payload, stream)
  elif command == "doctor":
    _render_doctor(payload, args, stream)
  elif command == "recover":
    _render_recover(payload, stream)
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
      "project": "项目集成已处理",
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
      "project": (("目标", _target(payload)), ("集成", payload.get("integration")),
        ("变更文件", payload.get("changed")),
        ("产物数量", len(payload["artifacts"]) if isinstance(payload.get("artifacts"), list) else None)),
    }
    _write_fields(fields.get(command, (("目标", _target(payload)),)), stream)
  if command in ("plan", "doctor", "recover"):
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

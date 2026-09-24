"""从已确认的规格和选择建立初始范围；不把没有机器或账号改为未选。"""
from copy import deepcopy
from datetime import datetime, timezone
from .activity import digest
from .pi_acceptance import validate_scope


PLATFORMS = (("linux", "x86_64"), ("linux", "arm64"), ("darwin", "arm64"), ("darwin", "x86_64"))
PROFILES = {"pi-default": "node", "pi-managed": "node", "pi-codex": "node", "pi-cursor": "bun"}
OPTIONAL = {"codex": "pi-codex", "cursor": "pi-cursor", "mcp": "pi-default", "web": "pi-default", "proxy": "pi-default", "terminal": "pi-default"}


def initial_scope(*, optional_selected, created_at=None):
  if set(optional_selected) != set(OPTIONAL) or any(type(value) is not bool for value in optional_selected.values()):
    from .schema import ConfigError
    raise ConfigError("pi-scope-selection-required")
  items = []
  def add(capability, case, profile, system, architecture, levels, applicability="required", reason="规格要求的软件与原生验证"):
    items.append({"capability_id": capability, "scenario_id": profile + "." + case, "identity": None,
      "platform": {"os": system, "architecture": architecture, "engine": PROFILES[profile]}, "applicability": applicability,
      "levels": levels, "evidence_paths": [], "selection_reason": reason})
  for system, architecture in PLATFORMS:
    for profile in PROFILES:
      for case in ("V01-inventory", "V03-dependencies", "V04-launch", "V05-resources", "V08-recovery", "V09-supervision", "V10-manager", "V13-permissions", "V17-optional-software", "V20-cold-rebuild"):
        add("pi-host", case, profile, system, architecture, ["mock", "native"])
      for case in ("V02-schema", "V06-credentials", "V07-migration", "V18-diagnostics", "V19-dsh-compatibility", "V21-upgrade"):
        add("agentcfg-pi", case, profile, system, architecture, ["mock"])
      if profile == "pi-managed":
        for case in ("V10-manager", "V11-workflow", "V12-budget", "V14-cancel", "V15-schedule"):
          add("task-keeper", case, profile, system, architecture, ["mock", "native"])
        for route in ("direct", "proxy"):
          for case in ("inspect-fix-review", "second-view"):
            add("task-keeper", "live-" + route + "." + case, profile, system, architecture, ["live"], reason="必需 Task Keeper 真实模型与双路线场景")
      else:
        for case in ("V16-delegate", "V22-control", "V23-batch-progress", "V24-retirement"):
          add("model-delegate", case, profile, system, architecture, ["mock", "native"])
    for name, profile in OPTIONAL.items():
      add(name, "live-" + name, profile, system, architecture, ["live"],
        "selected_optional" if optional_selected[name] else "not_selected",
        "用户明确选择该真实账号／服务验收" if optional_selected[name] else "用户明确不选择该真实账号／服务验收")
  value = {"schema_version": 1, "scope_id": "001-unify-pi-capabilities", "revision": 1,
    "created_at": created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "items": items}
  value["scope_digest"] = digest(value)
  return validate_scope(value)


def support_markdown(value):
  lines = ["# Pi 支持与验收状态", "", "报告生成与交付批准分开；未冻结候选身份不会得到通过。", "",
    "- Scope：`" + value["scope_id"] + "`，revision " + str(value["scope_revision"]),
    "- 当前批准：" + ("通过" if value["release_approved"] else "未通过"),
    "- 候选身份：" + ("已冻结" if value["candidate_frozen"] else "尚未冻结"), "",
    "| 平台 | 引擎 | passed | failed | not-run | stale | not-selected |", "|---|---|---:|---:|---:|---:|---:|"]
  groups = {}
  for row in value["items"]:
    key = (row["platform"]["os"] + "-" + row["platform"]["architecture"], row["platform"]["engine"])
    counts = groups.setdefault(key, {name: 0 for name in value["counts"]}); counts[row["status"]] += 1
  for (platform, engine), counts in sorted(groups.items()):
    lines.append("| " + " | ".join([platform, engine, *[str(counts[name]) for name in value["counts"]]]) + " |")
  lines += ["", "四个平台范围保留；当前只有 Linux x86_64 机器，其余三个平台尚无测试入口。", "",
    "Codex、Cursor、MCP、web、代理和终端全部为已选 live 项。未登录、缺授权或缺机器不转成 not-selected。", "",
    "Codex 保留官方 CLI；系统／受管配置和组织或未知账号无法核验时拒绝执行。稳定受信机器和账号是运行前提，预检不提供原子配置保证；这些兼容性缺口不删除验收范围。", "",
    "当前矩阵只反映固定 scope 中已登记的匹配证据。已有开发期测试记录不会自动提升为最终候选通过。", ""]
  return "\n".join(lines)

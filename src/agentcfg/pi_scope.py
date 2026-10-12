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


# 新任务使用独立版本，不能把历史 001 的证据提升为双 profile 验收。
TWO_PROFILES_SCOPE = "005-pi-two-profiles"
REQUIREMENT_CHECKS = {
  "R01": "S01", "R02": "S03 B01 B02 B03 B04", "R03": "S02 S03 B06",
  "R04": "S04 S05 S13", "R05": "S06 S07", "R06": "S07 S09 B05",
  "R07": "S10 S11 B05", "R08": "S03 S14", "R09": "S12 S13 B03",
  "R10": "S12 B01 B03 P01", "R11": "S08 B04 P02", "R12": "S08 S11 P03 P04 P05",
  "R13": "P04", "R14": "P05", "R15": "S05 S08 P03 P04", "R16": "S09 P06 P07",
  "R17": "S12 P08", "R18": "P09", "R19": "P10", "R20": "F01 F02 F04 F06 F08",
  "R21": "F02 F03 F04", "R22": "F05 F08", "R23": "F06 F09", "R24": "F06 F07 X03 X04",
  "R25": "F11 F12 X05", "R26": "F10 F13 F15 X06", "R27": "F04 F12 F13 F14 F18 W04 X01 X02",
  "R28": "F01 F11 F14 F15 F16", "R29": "F05 F08 F10 X07", "R30": "S14 F09 F10",
  "R31": "S01 S02 B02 F18 M01", "R32": "S02 F15 M02", "R33": "B06 F17 M03",
  "R34": "S05 S14 M04", "R35": "S04 W02 W03 W06 W07 W08 M05",
  "R36": "W01 W02 W03 W04 W05 W06 W08 M06", "R37": "S01 S02 S03 M01 M02 M07",
}
CHECK_REQUIREMENTS = {f"{prefix}{number:02}": [requirement for requirement, checks in REQUIREMENT_CHECKS.items()
  if f"{prefix}{number:02}" in checks.split()] for prefix, count in (("S", 14), ("B", 6), ("F", 18), ("W", 8), ("P", 10), ("M", 7))
  for number in range(1, count + 1)}
INVARIANTS = {"X01": ["F12", "F14", "P06"], "X02": ["F06", "F08", "F13"],
  "X03": ["F06", "F07"], "X04": ["F07"], "X05": ["F11", "F15"],
  "X06": ["F13", "F15", "M02"], "X07": ["F05", "F08", "F10"], "X08": ["S05", "P08", "M04"]}
CHECK_LEVELS = {
  "S01": "U V", "S02": "U P V", "S03": "U P", "S04": "L V", "S05": "U P V", "S06": "P L V",
  "S07": "P L", "S08": "U O P V", "S09": "U P V", "S10": "U P", "S11": "U P V", "S12": "U P V",
  "S13": "L", "S14": "U P L", "B01": "U P V", "B02": "U P", "B03": "U P V", "B04": "U P",
  "B05": "P", "B06": "P L V", "F01": "U P", "F02": "P L V", "F03": "P L", "F04": "U P V",
  "F05": "U P V", "F06": "U P L V", "F07": "U V", "F08": "U O P V", "F09": "P L",
  "F10": "U P V", "F11": "U P V", "F12": "U P V", "F13": "U O V", "F14": "U O P V",
  "F15": "U O P V", "F16": "U P", "F17": "P L V", "F18": "O P V",
  "P01": "U P", "P02": "U P", "P03": "O V", "P04": "O V", "P05": "O P V",
  "P06": "U P", "P07": "U O", "P08": "U P V", "P09": "U P", "P10": "U L V",
  "M01": "U O P", "M02": "U O", "M03": "O P L", "M04": "U P L", "M05": "V", "M06": "V", "M07": "U P V",
  **{f"W{number:02}": "V" for number in range(1, 9)}, **{key: "U V" for key in INVARIANTS},
}


def two_profiles_items(*, stop_hook_selected=False, whole_process_isolation_decision="undecided"):
  items = []
  for check in (*CHECK_REQUIREMENTS, *INVARIANTS):
    profiles = ("pi-base",) if check.startswith("B") else ("pi-full",) if check.startswith(("F", "X")) or check in ("P08", "P09", "P10") else ("pi-base", "pi-full")
    for profile in profiles:
      subitems = ["default"]
      if check == "P05":
        subitems = ["coverage", "feasibility"]
        if whole_process_isolation_decision == "supported": subitems.append("malicious-extension")
      elif check == "M03": subitems = ["pure-pi-base" if profile == "pi-base" else "four-states"]
      elif check.startswith("M"): subitems = ["base-and-common" if profile == "pi-base" else "full-and-common"]
      elif check == "P01" and profile == "pi-full": subitems = ["reviewer-disabled", "reviewer-enabled"]
      elif check in ("P08", "P09", "P10"): subitems = ["reviewer-enabled"]
      for subitem in subitems:
        items.append({"check_id": check, "profile": profile, "subitem_id": subitem,
          "requirements": CHECK_REQUIREMENTS.get(check, sorted({requirement for related in INVARIANTS.get(check, []) for requirement in CHECK_REQUIREMENTS[related]})),
          "invariant_checks": INVARIANTS.get(check, []), "levels": CHECK_LEVELS[check].split(),
          "applicability": "not_selected" if check == "W05" and not stop_hook_selected else "required",
          "identity": None, "checker": None, "platform": {"os": "linux", "architecture": "x86_64", "engine": "node"}, "evidence_paths": []})
  return items


def two_profiles_scope(*, created_at=None, stop_hook_selected=False, whole_process_isolation_decision="undecided"):
  if type(stop_hook_selected) is not bool:
    from .schema import ConfigError
    raise ConfigError("pi-scope-selection-required")
  value = {"schema_version": 2, "scope_id": TWO_PROFILES_SCOPE, "revision": 1,
    "created_at": created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "stop_hook_selected": stop_hook_selected, "serious_review_findings": None,
    "whole_process_isolation_decision": whole_process_isolation_decision,
    "items": two_profiles_items(stop_hook_selected=stop_hook_selected, whole_process_isolation_decision=whole_process_isolation_decision)}
  value["scope_digest"] = digest(value)
  return validate_scope(value)

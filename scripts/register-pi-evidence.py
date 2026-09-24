#!/usr/bin/env python3
"""可信的证据登记器：核验输入、提取身份、生成 EvidenceRecord。

关键原则：
1. 不信任文件名或顶层标签；语义核验复用生产 validate_run_report / scenarios / native_cases。
2. 身份信任锚点是当前仓库的真实锁（recipe_digest 已核验源码），不是首个报告自报的摘要。
3. 证据键区分 capability/scenario/platform/level/suffix/candidate。
4. 已有文件内容完全相同才可幂等复用；不同内容必须拒绝。
5. 只登记报告中实际存在的命令与时间；不构造 `--case a+b`、占位 runtime 或 mtime 冒充。
6. cold 报告必须递归核验每个被引用的 native 报告，并核对精确的目标、步骤与 case 集合。
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.pi_acceptance import read_scope, validate_revision, validate_scope
from agentcfg.pi_cold_rebuild import native_cases, collect_source, snapshot_digest
from agentcfg.pi_dependencies import PiBackend
from agentcfg.pi_validation_report import validate_run_report
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree, create_new_private_file

EXPECTED_MOCK_RUNNERS = {"pytest", "node"}
EXPECTED_COLD_TARGETS = ("first", "第二组 空格路径")
EXPECTED_COLD_STEPS = ("python-environment", "sync", "apply")

# 逐V项native覆盖映射：capability→V项→构成case（每个case都必须属于该profile生产 native_cases）
NATIVE_MAP = {
  "pi-host": {
    "V01-inventory": ["host-resources"], "V03-dependencies": ["host-resources"],
    "V04-launch": ["host-resources"], "V05-resources": ["host-resources", "readseek-tools"],
    "V08-recovery": ["termination-recovery"], "V09-supervision": ["termination-recovery"],
    "V10-manager": ["host-resources"], "V13-permissions": ["budget-permissions", "readseek-tools"],
    "V17-optional-software": ["host-resources"],
  },
  "model-delegate": {name: ["model-delegate-replacement"] for name in ("V16-delegate", "V22-control", "V23-batch-progress", "V24-retirement")},
  "task-keeper": {name: ["taskkeeper-lifecycle"] for name in ("V10-manager", "V11-workflow", "V12-budget", "V14-cancel", "V15-schedule")},
}


def _load(path, label):
  if not path.exists(): raise ValueError(f"{label} 缺失: {path}")
  try:
    return json.loads(path.read_text())
  except (ValueError, UnicodeError) as error:
    raise ValueError(f"{label} 无法解析为 JSON: {path.name} ({type(error).__name__})") from None


def _strings(value, label):
  if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
    raise ValueError(f"{label} 必须是非空字符串数组")


def verify_mock_report(mock_path):
  """mock 报告：生产 schema+状态一致性，双 runner、真实命令、产物引用齐备。"""
  value = _load(mock_path, "mock 报告")
  try:
    validate_run_report(value, tier="mock", case="all")
  except ConfigError as error:
    raise ValueError(f"mock 报告未通过生产校验: {error}") from None
  if value["status"] != "passed": raise ValueError(f"mock 报告 status 不是 passed: {value['status']}")
  if not value.get("started_at") or not value.get("finished_at"): raise ValueError("mock 报告缺少真实起止时间")
  runners = {row.get("runner") for row in value["results"]}
  if runners != EXPECTED_MOCK_RUNNERS: raise ValueError(f"mock runner 集合不是预期双 runner: {sorted(runners)}")
  for row in value["results"]:
    if row.get("exit_code") != 0: raise ValueError(f"mock runner {row.get('runner')} 退出码非零: {row.get('exit_code')}")
    _strings(row.get("command"), f"mock runner {row.get('runner')} command")
    refs = row.get("artifact_refs")
    if not isinstance(refs, list) or not refs: raise ValueError(f"mock runner {row.get('runner')} artifact_refs 为空")
    for ref in refs:
      if not (mock_path.parent / ref).exists(): raise ValueError(f"mock 产物引用不存在: {ref}")
  return value


def verify_native_report(native_path, expected_lock, expected_runtime, expected_source, expected_profile, expected_platform, case=None):
  """native 报告：生产校验（scenario 集合精确匹配、执行完整性）+ 调用方身份 + 真实来源。"""
  value = _load(native_path, "native 报告")
  report_case = value.get("case")
  if not isinstance(report_case, str) or not report_case: raise ValueError("native 报告缺少 case")
  if case is not None and report_case != case: raise ValueError(f"native 报告 case 不匹配: {report_case} != {case}")
  runtime = value.get("runtime")
  if not isinstance(runtime, dict): raise ValueError("native 报告缺少 runtime 身份")
  if runtime.get("profile") != expected_profile: raise ValueError(f"native runtime.profile 不匹配: {runtime.get('profile')}")
  if runtime.get("platform") != expected_platform: raise ValueError(f"native runtime.platform 不匹配: {runtime.get('platform')}")
  if runtime.get("lock_identity") != expected_lock: raise ValueError("native runtime.lock_identity 不匹配")
  if runtime.get("runtime_identity") != expected_runtime: raise ValueError("native runtime.runtime_identity 不匹配")
  if value.get("source_digest") != expected_source: raise ValueError("native source_digest 不匹配")
  try:
    validate_run_report(value, tier="native", case=report_case)
  except ConfigError as error:
    raise ValueError(f"native 报告未通过生产校验: {error}") from None
  if value["status"] != "passed": raise ValueError(f"native 报告 status 不是 passed: {value['status']}")
  if not value.get("started_at") or not value.get("finished_at"): raise ValueError("native 报告缺少真实起止时间")
  _strings(value.get("command"), "native command")
  if not value.get("results"): raise ValueError("native 报告 results 为空")
  for row in value["results"]:
    if row.get("status") != "passed": raise ValueError(f"native scenario {row.get('scenario_id')} 未通过: {row.get('status')}")
    if (row.get("facts") or {}).get("real_account_used") is not False:
      raise ValueError(f"native scenario {row.get('scenario_id')} 未声明 real_account_used=false")
  return value


def verify_cold_rebuild_report(report_path, expected_lock, expected_source, run_root, profile, expected_platform):
  """冷重建报告：固定双目标/步骤/生产 case 集合，并递归核验每个被引用 native 报告。"""
  value = _load(report_path, "冷重建报告")
  if value.get("schema_version") != 1 or value.get("case") != "cold-rebuild": raise ValueError("冷重建报告 schema/case 不符")
  if value.get("lock_identity") != expected_lock: raise ValueError(f"冷重建 lock_identity 不匹配: {value.get('lock_identity')}")
  if value.get("profile") != profile: raise ValueError(f"冷重建 profile 不匹配: {value.get('profile')}")
  if value.get("platform") != expected_platform: raise ValueError(f"冷重建 platform 不匹配: {value.get('platform')}")
  if value.get("status") != "passed": raise ValueError(f"冷重建 status 不是 passed: {value.get('status')}")
  if not value.get("started_at") or not value.get("finished_at"): raise ValueError("冷重建报告缺少真实起止时间")
  _strings(value.get("command"), "冷重建 command")
  targets = value.get("targets")
  if not isinstance(targets, list) or [row.get("target") for row in targets if isinstance(row, dict)] != list(EXPECTED_COLD_TARGETS):
    raise ValueError(f"冷重建目标必须按序为 {list(EXPECTED_COLD_TARGETS)}")
  expected_cases = list(native_cases(profile))
  for target in targets:
    name = target["target"]
    if target.get("lock_identity") != expected_lock: raise ValueError(f"冷重建目标 {name} lock_identity 不匹配")
    if target.get("source_digest") != expected_source: raise ValueError(f"冷重建目标 {name} source_digest 不匹配")
    if target.get("installation") != "verified": raise ValueError(f"冷重建目标 {name} installation 不是 verified")
    if target.get("native_execution") != "passed": raise ValueError(f"冷重建目标 {name} native_execution 不是 passed")
    steps = target.get("steps")
    if (not isinstance(steps, list) or [row.get("step") for row in steps if isinstance(row, dict)] != list(EXPECTED_COLD_STEPS)
        or any(row.get("exit_code") != 0 for row in steps)):
      raise ValueError(f"冷重建目标 {name} steps 不是全零的 {list(EXPECTED_COLD_STEPS)}")
    rows = target.get("native_cases")
    if not isinstance(rows, list) or [row.get("case") for row in rows if isinstance(row, dict)] != expected_cases:
      raise ValueError(f"冷重建目标 {name} native_cases 与生产预期 {expected_cases} 不符")
    for row in rows:
      case = row.get("case")
      if row.get("status") != "passed" or row.get("exit_code") != 0:
        raise ValueError(f"冷重建目标 {name} case {case} 未通过: {row.get('status')}/{row.get('exit_code')}")
      if row.get("report") != "native/" + case + ".json":
        raise ValueError(f"冷重建目标 {name} case {case} 报告路径异常: {row.get('report')}")
      native_path = run_root / profile / name / "native" / (case + ".json")
      try:
        verify_native_report(native_path, expected_lock, target.get("runtime_identity"), expected_source, profile, expected_platform, case=case)
      except ValueError as error:
        raise ValueError(f"冷重建目标 {name} case {case} 引用的 native 报告核验失败: {error}") from None
  return value


def extract_identity_from_cold_report(run_root, profile, lock, expected_platform, identity=None):
  """核验冷重建与 checkout 源码快照摘要后提取候选身份；返回 (identity, runtime, source_digest)。"""
  report_path = run_root / (profile + "-cold.json")
  value = _load(report_path, "冷重建报告")
  targets = value.get("targets")
  source_digest = targets[0]["source_digest"] if isinstance(targets, list) and targets else None
  if not isinstance(source_digest, str): raise ValueError("冷重建报告缺少可用 source_digest")
  verify_cold_rebuild_report(report_path, lock, source_digest, run_root, profile, expected_platform)
  first = run_root / profile / "first"
  checkout = first / "checkout"
  if not checkout.is_dir(): raise ValueError(f"冷重建 checkout 源码快照缺失: {checkout}")
  if snapshot_digest(collect_source(checkout)) != source_digest:
    raise ValueError("checkout 源码快照摘要与冷重建报告不符（不能仅信报告自报）")
  if identity is None:
    local = first / "home/native-fixture/local.toml"
    if not local.exists(): raise ValueError(f"部署工作区缺失: {local}")
    from agentcfg.workspace import load_workspace
    from agentcfg.pi_diagnostics import diagnostic_identity
    workspace = load_workspace(local, profile, repository=checkout)
    identity = diagnostic_identity({"data": workspace.resolved.data, "repository": checkout,
      "lock_identity": lock, "runtime_identity": targets[0]["runtime_identity"]})
  return identity, targets[0]["runtime_identity"], source_digest


def write_record(evidence_root, rel, record, *, report=False):
  """写入证据记录：幂等要求逐字节相同；拒绝符号链接与不同内容。report=True 返回 created/identical。"""
  path = Path(evidence_root) / rel
  if path.is_symlink(): raise ValueError(f"证据路径是符号链接，拒绝: {rel}")
  if path.exists():
    if path.read_bytes() == json_bytes(record):
      print("skip identical:", rel)
      return "identical" if report else rel
    raise ValueError(f"证据文件内容不同，不能复用: {rel}")
  path.parent.mkdir(parents=True, exist_ok=True)
  os.chmod(path.parent, 0o700)
  fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
  with os.fdopen(fd, "wb") as output:
    output.write(json_bytes(record)); output.flush(); os.fsync(output.fileno())
  return rel


def compute_live_identity(local, profile, repository=ROOT):
  """真实部署 generation 身份：与 live 执行器同一部署门槛（installed+current+generation+无活动）。"""
  from agentcfg.deployment import read_state
  from agentcfg.pi_diagnostics import diagnostic_identity
  from agentcfg.pi_lifecycle import assert_inactive
  from agentcfg.runtime import record
  from agentcfg.workspace import load_workspace
  workspace = load_workspace(local, profile, repository=repository)
  lock = workspace.backend.read_lock(repository)
  if workspace.agent != "pi": raise ConfigError("pi-live-profile-agent")
  identity = workspace.backend.runtime_identity(workspace, lock)
  if workspace.backend.status(workspace, identity) != "installed": raise Conflict("PI_LIVE_RUNTIME_NOT_INSTALLED")
  with Tree(workspace.state_root) as tree:
    if tree.read("pending.json") is not None: raise Conflict("PI_LIVE_DEPLOYMENT_PENDING")
    current = read_state(tree)["current"]
  if (not current or current["binding"] != workspace.binding or current["launch"].get("runtime_identity") != identity
      or current["launch"]["lock_identity"] != lock.identity): raise Conflict("PI_LIVE_DEPLOYMENT_MISMATCH")
  candidate = workspace.candidate(lock.identity)
  if current["generation"] != candidate.generation or current["launch"] != record(workspace, lock):
    raise Conflict("PI_LIVE_CONFIGURATION_NOT_DEPLOYED")
  assert_inactive(workspace.state_root)
  return diagnostic_identity({"data": workspace.resolved.data, "repository": workspace.repository,
    "lock_identity": lock.identity, "runtime_identity": identity}), lock.identity


def freeze_live(args, *, identity_fn=None, lock_anchor=None):
  """把真实部署身份冻结进 scope 新 revision（只动本 profile 的 linux-x86_64 live 项）。"""
  anchor = lock_anchor
  if anchor is None:
    from agentcfg.pi_dependencies import PiBackend
    anchor = PiBackend().read_lock(ROOT).identity
  from agentcfg.pi_scope import PROFILES
  if anchor != args.lock:
    print(f"ERROR: 候选锁与当前仓库源码不符: {args.lock} != {anchor}")
    return 2
  if args.profile not in PROFILES:
    print("ERROR: --profile 必须是四个 Pi 配方之一")
    return 2
  scope = read_scope(args.scope)
  before = json.loads(Path(args.scope).read_text())
  identity, _lock = (identity_fn or compute_live_identity)(args.local, args.profile)
  engine = PROFILES[args.profile]
  requested = list(args.live_items or [])
  if not requested:
    print("ERROR: --freeze-live 需要至少一个 --live-item（direct/proxy 等按项冻结，避免波及他路线）")
    return 2
  frozen_ids = set()
  items = []
  for row in scope["items"]:
    row = dict(row)
    platform = row["platform"]
    live_linux = (row["levels"] == ["live"] and platform["os"] == "linux" and platform["architecture"] == "x86_64"
      and platform["engine"] == engine and row["scenario_id"].startswith(args.profile + "."))
    if live_linux and row["applicability"] != "not_selected" and row["scenario_id"] in requested:
      row["identity"] = identity
      frozen_ids.add(row["scenario_id"])
    items.append(row)
  missing = [name for name in requested if name not in frozen_ids]
  if missing:
    print(f"ERROR: 以下 --live-item 不是本 profile 可选中的 linux-x86_64 live 项: {missing}")
    return 2
  after = dict(before)
  after["revision"] = before["revision"] + 1
  after["items"] = items
  after["scope_digest"] = digest({key: value for key, value in after.items() if key != "scope_digest"})
  try:
    validate_revision(before, after)
    validate_scope(after)
  except (ConfigError, ValueError) as error:
    print(f"ERROR: scope validation failed: {error}")
    return 1
  out = args.scope.with_name(args.scope.stem + "-r" + str(after["revision"]) + ".json")
  if out.exists() or out.is_symlink():
    try: existing = json.loads(out.read_text()).get("scope_digest")
    except (ValueError, UnicodeError): existing = None
    if existing != after["scope_digest"]:
      print(f"ERROR: scope 快照已存在且内容不同，保留历史: {out}")
      return 1
    print(f"scope 快照已存在（digest 相同，不重写）: {out}")
    return 0
  create_new_private_file(out, json_bytes(after))
  print(f"live identity frozen: {sorted(frozen_ids)} | profile={args.profile} | new scope: {out}")
  return 0


def register_live(args, *, lock_anchor=None):
  """登记一次真实 live 执行：结构、身份、scenario 精确绑定后如实保存 passed/failed 状态。

  不可信/结构非法/身份或 scenario 不匹配 → 拒绝；合法但执行失败 → 登记 failed；
  每次执行以报告摘要作 attempt 标识独立留档，重试历史不覆盖；相同材料幂等。
  """
  from agentcfg.pi_validation_live import CASE_CAPABILITIES
  anchor = lock_anchor or PiBackend().read_lock(ROOT).identity
  if anchor != args.lock:
    print(f"ERROR: 候选锁与当前仓库源码不符: {args.lock} != {anchor}")
    return 2
  if not args.live_items or len(args.live_items) != 1:
    print("ERROR: --live-register 每次必须且只能指定一个 --live-item")
    return 2
  item_id = args.live_items[0]
  missing = [flag for flag, value in (("--live-report", args.live_report),
    ("--native-report", args.native_report), ("--command-sidecar", args.command_sidecar),
    ("--evidence-root", args.evidence_root)) if not value]
  if missing:
    print(f"ERROR: live 登记缺少参数: {missing}")
    return 2
  scope = read_scope(args.scope)
  before = json.loads(Path(args.scope).read_text())
  rows = [row for row in scope["items"] if row["scenario_id"] == item_id and row["levels"] == ["live"]
    and row["platform"]["os"] == "linux" and row["platform"]["architecture"] == "x86_64"]
  if len(rows) != 1:
    print("ERROR: --live-item 必须唯一匹配 linux-x86_64 的 live scope 项")
    return 2
  item = rows[0]
  if item["identity"] is None:
    print("ERROR: 该 live 项身份尚未冻结（先 --freeze-live），不登记")
    return 1
  report = _load(args.live_report, "live 报告")
  capability = item["capability_id"]
  cases = [case for case, capabilities in CASE_CAPABILITIES.items() if capability in capabilities]
  if report.get("case") not in cases:
    print(f"ERROR: live 报告 case {report.get('case')!r} 不属于 {capability} 的既定前提 case {cases}")
    return 1
  try:
    validate_run_report(report, tier="live", case=report["case"])
  except ConfigError as error:
    print(f"ERROR: live 报告未通过生产校验: {error}")
    return 1
  if report["status"] not in ("passed", "failed"):
    print(f"ERROR: live 报告 status={report['status']!r}；未执行不登记，失败或通过才构成一次执行证据")
    return 1
  # 精确绑定：报告内实际 scenario、runtime profile 与目标 scope 项必须逐项一致。
  rows_live = report["results"]
  if len(rows_live) != 1 or rows_live[0].get("scenario_id") != item_id:
    print("ERROR: live 报告的 scenario_id 与目标 scope 项不匹配（禁止跨 scenario 登记）")
    return 1
  if report["runtime"]["profile"] != item_id.split(".", 1)[0]:
    print("ERROR: live 报告 runtime.profile 与目标项不一致")
    return 1
  if report["identity"] != item["identity"]:
    print("ERROR: live 报告身份与 scope 冻结的部署身份不一致（stale）")
    return 1
  native = _load(args.native_report, "native 前提报告")
  native_case = "optional-services" if capability in ("mcp", "web", "terminal") else report["case"]
  try:
    validate_run_report(native, tier="native", case=native_case)
  except ConfigError as error:
    print(f"ERROR: native 前提报告未通过生产校验: {error}")
    return 1
  if digest(native) != report["native_report_digest"]:
    print("ERROR: live 报告的 native_report_digest 与实际 native 文件不一致")
    return 1
  if native["runtime"] != report["runtime"]:
    print("ERROR: native 前提与 live 的 runtime 身份不一致")
    return 1
  if native["status"] != "passed":
    print("ERROR: native 前提未通过，不能登记 live")
    return 1
  sidecar = _load(args.command_sidecar, "命令 sidecar")
  _strings(sidecar.get("command"), "sidecar command")
  attempt = digest(report)[:12]
  evidence_dir = Path(args.evidence_root).resolve()

  def archive_copy(directory, name, document):
    rel = f"{directory}/{name}"
    path = evidence_dir / rel
    if path.is_symlink(): raise ValueError(f"归档路径是符号链接: {rel}")
    payload = json_bytes(document)
    if path.exists():
      if path.read_bytes() == payload: return rel
      raise ValueError(f"归档材料冲突（同名不同内容）: {rel}")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
      stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    return rel

  safe_item = item_id.replace(".", "-")
  refs = [archive_copy("live-reports", f"{safe_item}.{attempt}.json", report),
    archive_copy("native-prereqs", f"{safe_item}.{attempt}.json", native),
    archive_copy("live-provenance", f"{safe_item}.{attempt}.command.json", {"schema_version": 1,
      "command": list(sidecar["command"]), "source_report": "live-reports/" + safe_item + "." + attempt + ".json"})]
  item_engine = item["platform"]["engine"]
  suffix = item_id.split(".", 1)[1].replace(".", "-")
  rel = f"evidence/{capability}.{item_id}.{item['platform']['os']}-{item['platform']['architecture']}-{item_engine}.live.{suffix}.{attempt}.{args.lock[:8]}.json"
  record = {"schema_version": 1, "capability_id": capability, "test_case_id": item_id, "level": "live",
    "identity": item["identity"], "platform": dict(item["platform"]), "started_at": report["started_at"],
    "finished_at": report["finished_at"], "status": report["status"], "command": list(sidecar["command"]),
    "artifact_refs": sorted(refs),
    "limitations": ["live evidence covers this selected scope item only",
      "真实账号调用的执行记录；状态如实取自经过生产校验的报告"], "reason": ""}
  from agentcfg.pi_catalog import validate
  validate("evidence", record)
  try:
    created = write_record(args.evidence_root, rel, record, report=True)
  except ValueError as error:
    print(f"ERROR: 证据写入被拒绝: {error}")
    return 1
  already = rel in item["evidence_paths"]
  if created == "identical" and already:
    print(f"duplicate registration: {item_id} attempt {attempt} 已登记，无变更")
    return 0
  items = []
  for row in scope["items"]:
    row = dict(row)
    if row["scenario_id"] == item["scenario_id"] and row["platform"] == item["platform"]:
      row["evidence_paths"] = sorted(set(row["evidence_paths"]) | {rel})
    items.append(row)
  after = dict(before)
  after["revision"] = before["revision"] + 1
  after["items"] = items
  after["scope_digest"] = digest({key: value for key, value in after.items() if key != "scope_digest"})
  try:
    validate_revision(before, after)
    validate_scope(after)
  except (ConfigError, ValueError) as error:
    print(f"ERROR: scope validation failed: {error}")
    return 1
  out = args.scope.with_name(args.scope.stem + "-r" + str(after["revision"]) + ".json")
  if out.exists() or out.is_symlink():
    try: existing = json.loads(out.read_text()).get("scope_digest")
    except (ValueError, UnicodeError): existing = None
    if existing != after["scope_digest"]:
      print(f"ERROR: scope 快照已存在且内容不同，保留历史: {out}")
      return 1
    print(f"scope 快照已存在（digest 相同，不重写）: {out}")
    return 0
  create_new_private_file(out, json_bytes(after))
  print(f"live registered: {item_id} attempt {attempt} status {record['status']} | record: {rel} | new scope: {out}")
  return 0


def main(argv=None, *, lock_anchor=None, identity_override=None, live_identity_fn=None):
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--scope", type=Path, required=True)
  parser.add_argument("--evidence-root", type=Path)
  parser.add_argument("--run-root", type=Path)
  parser.add_argument("--mock-report", type=Path)
  parser.add_argument("--lock", required=True)
  parser.add_argument("--freeze-live", action="store_true")
  parser.add_argument("--live-item", action="append", dest="live_items")
  parser.add_argument("--local", type=Path)
  parser.add_argument("--profile")
  parser.add_argument("--live-report", type=Path)
  parser.add_argument("--native-report", type=Path)
  parser.add_argument("--command-sidecar", type=Path)
  parser.add_argument("--live-register", action="store_true")
  args = parser.parse_args(argv)
  if args.freeze_live:
    if not args.local or not args.profile:
      print("ERROR: --freeze-live 需要 --local 与 --profile")
      return 2
    return freeze_live(args, identity_fn=live_identity_fn, lock_anchor=lock_anchor)
  if args.live_register:
    return register_live(args, lock_anchor=lock_anchor)
  if not args.evidence_root or not args.run_root or not args.mock_report:
    print("ERROR: 登记模式需要 --evidence-root/--run-root/--mock-report")
    return 2

  # 信任锚点：声明候选必须与当前仓库源码计算出的真实锁一致。
  anchor = lock_anchor or PiBackend().read_lock(ROOT).identity
  if anchor != args.lock:
    print(f"ERROR: 候选锁与当前仓库源码不符: {args.lock} != {anchor}")
    return 2

  scope = read_scope(args.scope)
  before = json.loads(Path(args.scope).read_text())
  try:
    mock = verify_mock_report(args.mock_report)
  except ValueError as error:
    print(f"ERROR: mock 报告核验失败: {error}")
    return 1

  profiles = ("pi-default", "pi-cursor", "pi-codex", "pi-managed")
  expected_platform = "linux-x86_64"
  identities, runtimes, source_digests = {}, {}, {}
  expected_source_digest = None
  for profile in profiles:
    try:
      identity, runtime, source_digest = extract_identity_from_cold_report(args.run_root, profile, args.lock, expected_platform,
        identity=(identity_override or {}).get(profile) if identity_override else None)
    except (ValueError, ConfigError) as error:
      print(f"WARNING: {profile}: {error}，跳过该 profile")
      continue
    if expected_source_digest is None: expected_source_digest = source_digest
    if source_digest != expected_source_digest:
      print(f"WARNING: {profile} source_digest 与其他 profile 不一致，跳过（不允许混候选登记）")
      continue
    identities[profile], runtimes[profile], source_digests[profile] = identity, runtime, source_digest
  if not identities:
    print("ERROR: 没有有效的 profile identity")
    return 1
  print(f"有效 profiles: {sorted(identities)}")
  print(f"source_digest: {expected_source_digest}")

  evidence_dir = Path(args.evidence_root).resolve()

  def ref_in(path):
    absolute = Path(path).resolve()
    try: return absolute.relative_to(evidence_dir).as_posix()
    except ValueError: return str(absolute)

  records_written = []
  def emit(item, level, suffix, status, command, started, finished, refs, limitations):
    profile = item["scenario_id"].split(".")[0]
    platform = f"{item['platform']['os']}-{item['platform']['architecture']}-{item['platform']['engine']}"
    rel = f"evidence/{item['capability_id']}.{item['scenario_id']}.{platform}.{level}.{suffix}.{args.lock[:8]}.json"
    value = {"schema_version": 1, "capability_id": item["capability_id"], "test_case_id": item["scenario_id"],
      "level": level, "identity": identities[profile], "platform": dict(item["platform"]),
      "started_at": started, "finished_at": finished, "status": status,
      "command": list(command), "artifact_refs": sorted(set(refs)), "limitations": list(limitations), "reason": ""}
    from agentcfg.pi_catalog import validate
    validate("evidence", value)
    records_written.append(write_record(args.evidence_root, rel, value))
    return rel

  def register_item(item):
    profile = item["scenario_id"].split(".")[0]
    scenario = item["scenario_id"].split(".", 1)[1]
    if profile not in identities: return
    paths = []
    if "mock" in item["levels"]:
      pytest_row = next(row for row in mock["results"] if row["runner"] == "pytest")
      node_row = next(row for row in mock["results"] if row["runner"] == "node")
      refs = [ref_in(args.mock_report)] + [ref_in(Path(args.mock_report).parent / ref) for ref in pytest_row["artifact_refs"] + node_row["artifact_refs"]]
      paths.append(emit(item, "mock", "suite", "passed", pytest_row["command"], mock["started_at"], mock["finished_at"], refs,
        ["双 runner 汇总登记；node 实际命令: " + " ".join(node_row["command"])]))
    if "native" in item["levels"]:
      if scenario == "V20-cold-rebuild":
        report_path = args.run_root / (profile + "-cold.json")
        try:
          cold = verify_cold_rebuild_report(report_path, args.lock, source_digests[profile], args.run_root, profile, expected_platform)
        except ValueError as error:
          print(f"WARNING: {profile} V20-cold-rebuild 核验失败: {error}")
          cold = None
        if cold is not None:
          refs = [ref_in(report_path)] + [ref_in(args.run_root / profile / name / "native" / (row["case"] + ".json"))
            for target in cold["targets"] for name, row in ((target["target"], row) for row in target["native_cases"])]
          paths.append(emit(item, "native", "cold", cold["status"], cold["command"], cold["started_at"], cold["finished_at"], refs,
            ["两目标完整冷安装与被引用 native 报告已递归核验"]))
      else:
        mapped = NATIVE_MAP.get(item["capability_id"], {}).get(scenario, [])
        cases = [case for case in mapped if case in native_cases(profile)]
        not_applicable = [case for case in mapped if case not in cases]
        if mapped and not cases:
          print(f"WARNING: {profile} {scenario} 映射 case {not_applicable} 全部不属于该 profile 生产 native_cases，不登记")
        elif cases:
          reports = []
          for case in cases:
            try:
              reports.append(verify_native_report(args.run_root / profile / "first" / "native" / (case + ".json"),
                args.lock, runtimes[profile], source_digests[profile], profile, expected_platform, case=case))
            except ValueError as error:
              print(f"WARNING: {profile} {scenario} case {case} 核验失败: {error}")
              reports = None; break
          if reports:
            last = max(reports, key=lambda row: row["finished_at"])
            refs = [ref_in(args.run_root / profile / "first" / "native" / (case + ".json")) for case in cases]
            limitations = ["构成 case 的实际命令逐份保存在被引用报告中: " + " | ".join(" ".join(row["command"]) for row in reports)]
            if not_applicable:
              limitations.append(f"映射中 {not_applicable} 不属于 {profile} 的配方能力矩阵（validation-matrix V05/V13 的该项语义由配方适用 case 覆盖）")
            paths.append(emit(item, "native", "cases", "passed", last["command"], min(row["started_at"] for row in reports), last["finished_at"], refs, limitations))
    if paths:
      item["identity"] = identities[profile]
      item["evidence_paths"] = sorted(set(item.get("evidence_paths", [])) | set(paths))

  items = []
  try:
    for item in scope["items"]:
      item = dict(item)
      if item["platform"]["os"] == "linux" and item["platform"]["architecture"] == "x86_64":
        register_item(item)
      items.append(item)
  except ValueError as error:
    print(f"ERROR: 证据写入被拒绝（不覆盖既有历史）: {error}")
    return 1

  after = dict(before)
  after["revision"] = before["revision"] + 1
  after["items"] = items
  after["scope_digest"] = digest({key: value for key, value in after.items() if key != "scope_digest"})
  try:
    validate_revision(before, after)
    validate_scope(after)
  except (ConfigError, ValueError) as error:
    print(f"ERROR: scope validation failed: {error}")
    return 1
  out = args.scope.with_name(args.scope.stem + "-r" + str(after["revision"]) + ".json")
  if out.exists() or out.is_symlink():
    try: existing = json.loads(out.read_text()).get("scope_digest")
    except (ValueError, UnicodeError): existing = None
    if existing != after["scope_digest"]:
      print(f"ERROR: scope 快照已存在且内容不同，保留历史: {out}")
      return 1
    print(f"records: {len(records_written)} | scope 快照已存在（digest 相同，不重写）: {out}")
    return 0
  create_new_private_file(out, json_bytes(after))
  print(f"records: {len(records_written)} | new scope: {out}")
  return 0


if __name__ == "__main__":
  sys.exit(main())

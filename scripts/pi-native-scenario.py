#!/usr/bin/env python3
"""隔离环境内的单场景驱动；真实 SDK/进程监督搭配合成本地模型。"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.activity import digest, protected
from agentcfg.deployment import json_bytes
from agentcfg.pi_host import HostSupervisor
from agentcfg.pi_lifecycle import guard
from agentcfg.pi_supervisor import closed
from agentcfg.pi_validation_fixture import MODELS, prepare_fixture, prepare_deployed_fixture
from agentcfg.pi_validation_provider import ProviderServer, ScriptedProvider
from agentcfg.pi_validation_parent_loss import ParentLossSupervisor, OrdinaryCancelSupervisor
from agentcfg.pi_validation_recovery import run_recovery_case
from agentcfg.pi_validation_delegate import run_delegate_control
from agentcfg.pi_validation_codex import run_codex_case
from agentcfg.pi_validation_codex_provider import CodexProvider
from agentcfg.pi_validation_service_provider import ServiceProvider
from agentcfg.pi_validation_live_services import service_facts_valid
from agentcfg.pi_validation_migration import prepare_migration_probe, finish_migration_probe, MigrationConflictSupervisor
from agentcfg.pi_validation_runtime import inspect_runtime, worker_failure_observed
from agentcfg.process import checked
from agentcfg.storage import Tree, ensure_private, instance_lock


SCENARIOS = {"taskkeeper-proxy-fix", "taskkeeper-proxy-second-view", "delegate-proxy-control", "mcp-service", "web-service", "terminal-service", "codex-native-readonly", "codex-native-write", "codex-native-control", "host-resources", "migration-runtime-conflicts", "permission-denials", "ordinary-cancel", "parent-loss", "recovery-grants", "delegate-presets", "delegate-batch", "delegate-control", "readseek-tools", "taskkeeper-inspect", "taskkeeper-fix", "taskkeeper-second-view", "taskkeeper-budget",
  "taskkeeper-quota", "taskkeeper-missing-result", "taskkeeper-pause-resume", "taskkeeper-stop", "taskkeeper-schedule"}


def run_case(path):
  if os.environ.get("AGENTCFG_NATIVE_VALIDATION") != "1": raise ValueError("native authorization marker missing")
  path = Path(path).absolute()
  with Tree(path.parent) as tree: raw = tree.read(path.name, max_bytes=1024 * 1024)
  value = json.loads(raw[0])
  closed(value, ("schema_version", "nonce", "scenario", "runtime_root", "source_root", "fixture_root", "programs", "provider_port"))
  if (type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["scenario"] not in SCENARIOS
      or not re.fullmatch(r"[a-f0-9]{64}", value["nonce"]) or Path(value["fixture_root"]) != path.parent / "fixture"
      or Path(value["source_root"]) != path.parents[2] / "source"):
    raise ValueError("native input contract")
  runtime = inspect_runtime(value["runtime_root"])
  scenario = value["scenario"]
  service = scenario.removesuffix("-service") if scenario in ("mcp-service", "web-service", "terminal-service") else None
  if scenario in ("delegate-control", "delegate-proxy-control", "migration-runtime-conflicts", "codex-native-readonly", "codex-native-write", "codex-native-control"):
    runtime = inspect_runtime(Path(value["fixture_root"]) / "instances_root/pi" / runtime.profile / "runtimes" / runtime.identity)
  templates = {}
  if scenario == "delegate-presets":
    with Tree(runtime.root) as tree:
      for name in ("general", "context", "challenge", "plan", "research", "review", "scout"):
        templates[name] = tree.read("supervisor/shared/skills/model-delegate/presets/" + name + ".md")[0].decode()
  provider = ScriptedProvider(MODELS.values(), scenario={"taskkeeper-quota": "quota", "taskkeeper-missing-result": "missing-final",
    "permission-denials": "deny-path", "ordinary-cancel": "slow", "migration-runtime-conflicts": "slow", "readseek-tools": "readseek", "delegate-presets": "delegate-presets", "delegate-batch": "slow", "delegate-control": "slow", "parent-loss": "slow", "taskkeeper-pause-resume": "slow", "taskkeeper-stop": "slow"}.get(scenario, "normal"), delay_seconds=10 if scenario == "ordinary-cancel" else 2,
    denied_path=str(Path(value["fixture_root"]) / "local.toml"), delegate_root=str(Path(value["fixture_root"]) / "project"), delegate_templates=templates)
  if scenario.startswith("codex-native-"):
    provider = CodexProvider(write=scenario == "codex-native-write", denied_paths=(str(Path(value["fixture_root"]) / "local.toml"),
      str(Path(value["fixture_root"]) / "instances_root/pi/pi-codex/codex-home/auth.json")), maximum_requests=24 if scenario == "codex-native-control" else 8)
  if service: provider = ServiceProvider(MODELS.values())
  if scenario == "delegate-proxy-control": provider.require_proxy = True; provider.scenario = "slow"; provider.delay = 2
  if scenario.startswith("taskkeeper-proxy-"): provider.require_proxy = True
  with ProviderServer(provider, port=value["provider_port"]) as server:
    if scenario.startswith("codex-native-"):
      fixture = prepare_deployed_fixture(value["fixture_root"], value["source_root"], runtime, server.base_url, value["programs"], run=checked,
        codex_mode="write" if scenario == "codex-native-write" else "readonly")
      if scenario == "codex-native-control": return run_delegate_control(fixture, runtime, value, path, provider)
      return run_codex_case(fixture, runtime, value, path, provider)
    if scenario in ("delegate-control", "delegate-proxy-control"):
      fixture = prepare_deployed_fixture(value["fixture_root"], value["source_root"], runtime, server.base_url, value["programs"], run=checked, proxy=scenario == "delegate-proxy-control")
      return run_delegate_control(fixture, runtime, value, path, provider)
    if scenario == "migration-runtime-conflicts":
      fixture = prepare_deployed_fixture(value["fixture_root"], value["source_root"], runtime, server.base_url, value["programs"], run=checked)
      migration_probe = prepare_migration_probe(fixture, runtime)
    else:
      fixture = prepare_fixture(value["fixture_root"], value["source_root"], runtime, server.base_url, value["programs"], run=checked,
        second_view=scenario in ("taskkeeper-second-view", "taskkeeper-proxy-second-view"), request_limit=2 if scenario == "taskkeeper-budget" else 100, fixing=scenario in ("taskkeeper-fix", "taskkeeper-proxy-fix"), service=service, proxy=scenario.startswith("taskkeeper-proxy-"), readseek=scenario == "readseek-tools")
    if scenario == "recovery-grants": return run_recovery_case(fixture, runtime, value, path)
    workspace = fixture["workspace"]
    ensure_private(workspace.state_root)
    node_input = path.parent / "node-input.json"
    with Tree(path.parent) as tree:
      node = {"schema_version": 1, "nonce": value["nonce"], "scenario": scenario,
        "instance_root": str(workspace.instance), "project": str(fixture["project"]), "runtime_identity": runtime.identity, "provider_port": value["provider_port"],
        "output": str(path.parent / "scenario-result.json")}
      if service:
        node.pop("scenario"); node.pop("provider_port"); node.update(capability=service, output=str(path.parent / "service-result.json"))
      tree.write_new(node_input.name, json_bytes(node))
    argv = list(fixture["spec"].argv)
    at = argv.index(str(runtime.root / "runtime/launch.mjs"))
    argv = [value["programs"]["engine"], *argv[1:at], str(runtime.root / ("runtime/service-validation.mjs" if service else "runtime/native-validation.mjs")), "--input", str(node_input)]
    with Tree(workspace.instance) as tree: manifest = json.loads(tree.read("pi-home/agentcfg-manifest.json")[0])
    config = {"state_root": str(workspace.state_root), "instance_root": str(workspace.instance), "repository": str(runtime.root / "supervisor"),
      "runtime_root": str(runtime.root), "instance_id": digest({"instance": str(workspace.instance), "binding": workspace.binding}),
      "lock_identity": runtime.lock_identity, "slice_identity": runtime.slice_identity, "policy_digest": digest(manifest["permission_policy"]),
      "manifest_digest": digest(manifest), "cwd": str(fixture["project"]), "engine": runtime.engine, "argv": argv,
      # 结果尚未生成；它们位于授权项目根之外，不把不存在的路径当成已核验保护根。
      "protected_roots": [str(workspace.local_path), str(workspace.instance), str(workspace.state_root), str(path), str(node_input)]}
    # 本进程已在验收沙箱内；彻底替换启动环境，不引入外层账号或父监督能力。
    os.environ.clear(); os.environ.update(fixture["environment"]); os.environ["AGENTCFG_NATIVE_VALIDATION"] = "1"
    if service: os.environ["AGENTCFG_SERVICE_VALIDATION"] = "1"
    with guard(workspace), Tree(workspace.state_root, create=True) as state, instance_lock(state) as lease_fd:
      supervisor = (ParentLossSupervisor(config, lease_fd=lease_fd, readiness=path.parent / "parent-loss-ready.json", nonce=value["nonce"],
          model_started=lambda: provider.snapshot()["requests"] > 0)
        if scenario == "parent-loss" else OrdinaryCancelSupervisor(config, lease_fd=lease_fd,
          readiness=path.parent / "model-request-started.json", nonce=value["nonce"], model_started=lambda: provider.snapshot()["requests"] > 0)
        if scenario == "ordinary-cancel" else MigrationConflictSupervisor(config, lease_fd=lease_fd, fixture=fixture,
          model_started=lambda: provider.snapshot()["requests"] > 0)
        if scenario == "migration-runtime-conflicts" else HostSupervisor(config, lease_fd=lease_fd))
      code = supervisor.run()
      records = supervisor.store.records()
      ended = bool(records) and not any(protected(row) for row in records)
    with Tree(path.parent) as tree:
      raw = tree.read("scenario-result.json", max_bytes=1024 * 1024)
      result = json.loads(raw[0]) if raw else None
      if service:
        raw = tree.read("service-result.json", max_bytes=1024 * 1024)
        service_result = json.loads(raw[0]) if raw else None
        if (isinstance(service_result, dict) and set(service_result) == {"schema_version", "nonce", "capability", "runtime_identity", "status", "failure_code", "facts"}
            and type(service_result["schema_version"]) is int and service_result["schema_version"] == 1 and service_result["capability"] == service
            and service_result.get("nonce") == value["nonce"] and service_result.get("runtime_identity") == runtime.identity
            and service_result.get("status") == "passed" and service_result["failure_code"] is None and service_facts_valid(service_result.get("facts"), service, 1)):
          observed = provider.snapshot()
          if service == "mcp": measured = observed["mcp_calls"].get("initialize", 0) >= 1 and observed["mcp_calls"].get("tools/list", 0) >= 1
          elif service == "web": measured = observed["web_calls"] >= 1
          else:
            with Tree(workspace.instance) as instance: states_raw = instance.read("pi-home/service-state/agent-report/native-terminal-states.jsonl")
            states = [json.loads(line) for line in states_raw[0].splitlines()] if states_raw else []
            measured = any(states[index:index + 3] == ["working", "blocked", "idle"] for index in range(max(0, len(states) - 2)))
          result = {"nonce": value["nonce"], "scenario": scenario, "runtime_identity": runtime.identity, "status": "passed" if measured else "failed",
            "facts": {**service_result["facts"], "real_account_used": False, "service_request_observed": measured,
              "source_preserved": (fixture["project"] / "code.txt").read_text() == "original\n"}}
      expected_exit = 137 if scenario == "parent-loss" else 0
      if scenario == "parent-loss":
        stopped = {row["lease_id"]: row for row in records}
        revoked = bool(supervisor.parent_loss_workers) and all(stopped[key]["state"] == "reclaimed"
          and stopped[key]["stop_requested_at"] is not None and stopped[key]["grant_generation"] > 1 for key in supervisor.parent_loss_workers)
        result = {"nonce": value["nonce"], "scenario": scenario, "runtime_identity": runtime.identity, "status": "passed",
          "facts": {**(supervisor.parent_loss_facts or {}), "parent_exit_observed": code == expected_exit,
            "worker_revocation_observed": revoked, "activity_drained": ended,
            "source_preserved": (fixture["project"] / "code.txt").read_text() == "original\n"}}
        if not revoked or not ended or code != expected_exit or not result["facts"]["source_preserved"]: result["status"] = "failed"
      valid = (isinstance(result, dict) and result.get("nonce") == value["nonce"] and result.get("scenario") == scenario
        and result.get("runtime_identity") == runtime.identity and result.get("status") == "passed" and isinstance(result.get("facts"), dict))
      if valid and scenario.startswith("taskkeeper-proxy-"):
        measured = provider.snapshot()
        valid = measured["requests"] > 0 and measured["proxy_requests"] == measured["requests"]
        result["facts"].update(transport="proxy", proxy_authentication_verified=valid)
      if valid and scenario == "permission-denials":
        # 被拒绝的真实文件存在，但不能产生普通文件 IO 的准入记录。
        admitted = workspace.state_root / "activity/ordinary-operations"
        result["facts"]["no_file_admission"] = not admitted.exists() or not any(admitted.iterdir())
        valid = result["facts"]["no_file_admission"]
      if valid and scenario == "migration-runtime-conflicts":
        result["facts"].update(finish_migration_probe(fixture, migration_probe, supervisor))
      if valid and scenario == "taskkeeper-missing-result":
        result["facts"]["missing_final_rejected"] = worker_failure_observed(workspace.state_root, records, {"EVIDENCE_EMPTY", "EVIDENCE_MISSING"})
        valid = result["facts"]["missing_final_rejected"]
      if valid and scenario == "delegate-presets": valid = provider.snapshot()["delivered_presets"] == sorted(templates)
      if valid and scenario == "delegate-batch": valid = provider.snapshot()["max_inflight"] == 2
      tree.write_new("controller-result.json", json_bytes({"schema_version": 1, "nonce": value["nonce"], "scenario": scenario,
        "runtime_identity": runtime.identity, "status": "passed" if code == expected_exit and valid and ended else "failed", "host_exit_code": code,
        "termination_confirmed": ended, "executions": len(records), "worker_executions": sum(row["kind"] == "worker" and row["process_identity"] is not None for row in records),
        "provider": provider.snapshot(), "facts": result.get("facts") if valid else None}))
    return 0 if code == expected_exit and valid and ended else 5


if __name__ == "__main__":
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--input", type=Path, required=True)
  try: sys.exit(run_case(parser.parse_args().input))
  except Exception as error:
    # 只报告类型和源码位置；异常正文可能含配置值或凭据，不能输出。
    frames = [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
      for frame in traceback.extract_tb(error.__traceback__)]
    sys.stderr.write(json.dumps({"error_type": type(error).__name__, "frames": frames}, separators=(",", ":")) + "\n")
    sys.stderr.write("原生场景未完成；临时活动记录保留，不能据此登记通过。\n")
    sys.exit(5)

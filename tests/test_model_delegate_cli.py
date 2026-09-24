"""CLI 历史状态在 supervisor 退出后仍独立核对证据，未知执行不触发重发。"""

from pathlib import Path
import json

import pytest

from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.model_delegate_cli import saved_status
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict, Tree
from test_pi_delegate import fixture


@pytest.mark.parametrize("feedback_required", [False, True])
def test_offline_status_verifies_saved_physical_evidence_current_candidate_and_final(tmp_path, feedback_required):
  controller, host, args, calls = fixture(tmp_path)
  instance = Path(host.config["instance_root"])
  binding = {"machine": "fixture", "local": str(tmp_path / "local.toml"), "profile": "pi-fixture"}
  host.store.owner["instance_id"] = digest({"instance": str(instance), "binding": binding})
  with Tree(instance, create=True) as tree:
    tree.write_state(".agentcfg-instance.json", json_bytes({"schema_version": 1, "binding": binding, "state_root": str(host.root)}))
  if feedback_required:
    from agentcfg.model_delegate_context import import_context
    from agentcfg.pi_worker_files import snapshot
    from test_model_delegate_context import context
    value = context()
    value["workspace"] = {"cwd": args["cwd"], "candidate_digest": snapshot(args["cwd"])}
    value["hypotheses"] = []
    host.manifest()["options"]["model_delegate"]["context_budget_tokens"] = 2000
    args.update(context_artifact=import_context(controller.root, value), feedback_required=True)
  request = controller.prepare(Principal("delegate"), args)
  controller.start(Principal("delegate"), request["run_id"])
  lease = host.store.read(request["lease_id"])
  with Tree(controller.root) as tree:
    directory = "reports/" + request["run_id"] + "/"
    tree.write_state(directory + "final.md", json_bytes({"facts": [], "conflicts": [], "summary": "fixture result"}) if feedback_required else b"fixture result")
    tree.write_state(directory + "event-000000000001.json", json_bytes({"schema_version": 2, "run_id": request["run_id"], "seq": 1,
      "timestamp": "2026-09-17T00:00:00Z", "kind": "completed", "phase": "turn-completed", "artifact_id": None}))
    tree.write_state(directory + "result.json", json_bytes({"schema_version": 2, "run_id": request["run_id"], "attempt_id": request["attempt_id"],
      "request_digest": request["request_digest"], "process_identity": lease["process_identity"], "host_completed": True, "observed_model": None,
      "resume_token": "fixture-session", "usage": {"input_tokens": None, "output_tokens": None, "cost": None}, "feedback_dispositions": []}))
  with Tree(host.root) as tree:
    tree.write_state("activity/exits/" + lease["lease_id"] + ".json", json_bytes({"schema_version": 1, "lease_id": lease["lease_id"], "process_identity": lease["process_identity"], "exit_code": 0}))
  host.store.processes.current.pop(201)
  host.store.finish(lease["lease_id"], host.store.owner)
  assert controller.refresh(request["run_id"])["state"] == "completed"
  assert saved_status(instance, request["run_id"])["verification"] == "verified-execution"
  assert len(calls) == 1
  if feedback_required:
    controller.handle(Principal("manager"), "delegate_result", {"run_id": request["run_id"]})
    with Tree(controller.root) as tree:
      path = directory + "feedback.json"
      original = tree.read(path)[0]
      feedback = json.loads(original); feedback["summary"] = "tampered"
      tree.write_state(path, json_bytes(feedback))
    with pytest.raises(Conflict, match="DELEGATE_FEEDBACK_STALE"):
      saved_status(instance, request["run_id"])
    with pytest.raises(Conflict, match="DELEGATE_FEEDBACK_STALE"):
      controller.handle(Principal("manager"), "delegate_result", {"run_id": request["run_id"]})
    with Tree(controller.root) as tree: tree.write_state(path, original)
  (Path(args["cwd"]) / "code.txt").write_text("later source change")
  with pytest.raises(Conflict):
    saved_status(instance, request["run_id"])
  assert len(calls) == 1


@pytest.mark.parametrize("action, extra", [
  ("status", ["--backend", "codex"]), ("cancel", ["--allow-workspace-write"]),
  ("start", ["--run-id", "old"]), ("resume", ["--after", "old:1"]),
  ("result", ["--observe"]), ("probe", ["--prompt-file", "private"]),
  ("wait", ["--offset", "10"]), ("poll", ["--timeout-seconds", "1"]),
])
def test_cli_rejects_ignored_action_options_before_reading_instance(action, extra, monkeypatch):
  import agentcfg.model_delegate_cli as module
  from agentcfg.schema import ConfigError
  monkeypatch.setattr(module, "instance_binding", lambda *_: pytest.fail("invalid options must fail before instance IO"))
  with pytest.raises(ConfigError, match="delegate-action-option"):
    module.main([action, "--instance", "/not-read", *extra])


def test_bootstrap_uses_only_explicit_sealed_instance_and_rejects_unlisted_python(tmp_path, monkeypatch):
  import hashlib
  import runpy
  import sys
  root = Path(__file__).resolve().parents[1]
  main = runpy.run_path(str(root / "shared/skills/model-delegate/scripts/run-model.py"))["main"]
  instance, state, repository = tmp_path / "instance", tmp_path / "state", tmp_path / "repository"
  identity = "a" * 64
  entry = "supervisor/scripts/model-delegate.py"
  content = b"# fake frozen client, never executed\n"
  binding = {"machine": "fixture", "profile": "pi-fixture", "local": str(tmp_path / "local.toml")}
  with Tree(instance, create=True) as tree:
    tree.write_state(".agentcfg-instance.json", json_bytes({"schema_version": 1, "binding": binding, "state_root": str(state)}))
    tree.write_state("runtimes/" + identity + "/" + entry, content)
    tree.write_state("runtimes/" + identity + "/.agentcfg-receipt.json", json_bytes({"schema_version": 1, "identity": identity, "status": "installed",
      "files": {entry: {"kind": "file", "sha256": hashlib.sha256(content).hexdigest()}}}))
  with Tree(state, create=True) as tree:
    tree.write_state("deployment.json", json_bytes({"version": 1, "current": {"binding": binding, "launch": {"lock_identity": identity,
      "environment": [{"name": "AGENTCFG_REPOSITORY", "literal": str(repository)}]}}}))
  with Tree(repository, create=True) as tree: tree.write_state(".venv/bin/python", b"fake interpreter, never executed")
  calls = []
  def execv(program, args):
    calls.append((program, args)); raise RuntimeError("captured execution")
  monkeypatch.setattr(main.__globals__["os"], "execv", execv)
  monkeypatch.setattr(sys, "argv", ["run-model.py", "status", "--instance", str(instance), "--run-id", "run"])
  with pytest.raises(RuntimeError, match="captured execution"): main()
  assert calls[0][0] == str(repository / ".venv/bin/python")
  assert calls[0][1][1:3] == ["-B", "-I"]
  with Tree(instance) as tree: tree.write_state("runtimes/" + identity + "/supervisor/src/unlisted.py", b"must never import")
  with pytest.raises(ValueError): main()
  assert len(calls) == 1


def test_start_uses_profile_timeout_and_reports_execution_failure_as_nonzero(tmp_path, monkeypatch, capsys):
  from types import SimpleNamespace
  import agentcfg.model_delegate_cli as module
  import agentcfg.workspace
  instance = tmp_path / "instance"; state = tmp_path / "state"; state.mkdir(mode=0o700)
  binding = {"machine": "fixture", "profile": "pi-fixture", "local": str(tmp_path / "local.toml")}
  with Tree(instance, create=True) as tree:
    tree.write_state(".agentcfg-instance.json", json_bytes({"schema_version": 1, "binding": binding, "state_root": str(state)}))
    tree.write_state("pi-home/agentcfg-manifest.json", json_bytes({"options": {"model_delegate": {"max_run_seconds": 20}}}))
  monkeypatch.setattr(module, "read_state", lambda _: {"current": {"binding": binding, "launch": {"lock_identity": "a" * 64,
    "environment": [{"name": "AGENTCFG_REPOSITORY", "literal": str(tmp_path / "repository")}]}}})
  monkeypatch.setattr(agentcfg.workspace, "load_workspace", lambda *args, **kwargs: SimpleNamespace(agent="pi", instance=instance))
  calls = []
  def launch(_workspace, request): calls.append(request); return {"schema_version": 2, "run_id": "fake", "state": "failed", "verification": "unverified"}
  monkeypatch.setattr(module, "launch_single", launch)
  prompt = tmp_path / "prompt"; prompt.write_text("fixture bounded task")
  code = module.main(["start", "--instance", str(instance), "--backend", "pi", "--mode", "review", "--provider", "fixture", "--model", "selected", "--cwd", str(tmp_path), "--prompt-file", str(prompt)])
  assert code == 5 and calls[0]["timeout_seconds"] == 20
  assert json.loads(capsys.readouterr().out)["state"] == "failed"

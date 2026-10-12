"""实例委托准入调用真实租约事务，进程启动与宿主全部为替身。"""

from types import SimpleNamespace
from pathlib import Path
import json
import os

import pytest

from agentcfg.pi_delegate import DelegateController
from agentcfg.pi_supervisor import Principal, SpawnCommand, SupervisorService
from agentcfg.workspace_leases import WorkspaceLeases
from agentcfg.storage import Conflict, Tree
from agentcfg.deployment import json_bytes
from test_pi_activity import make_store, identity
from test_pi_workspace_leases import worktree


def fixture(tmp_path):
  source = worktree(tmp_path)
  (source / "code.txt").write_text("source")
  store, processes = make_store(tmp_path / "controller")
  store.workspaces = WorkspaceLeases("fixture-boot")
  manifest = {"options": {"model_delegate": {"enabled": True, "backends": ["pi"], "allowed_modes": ["review", "investigate"],
    "presets": ["general", "review"], "max_run_seconds": 60, "pi": {"model_roles": ["reviewer"], "network_route": "direct"}},
    "network": {"routes": {"direct": {"mode": "direct", "provider_ids": ["fictional"]}}},
    "paths": {"roots": {"project": {"path": str(source), "purpose": "project"}}}},
    "model_bindings": {"reviewer": {"provider": "agentcfg-fictional", "model": "model"}},
    "allowed_models": [{"provider": "agentcfg-fictional", "model": "model"}], "permission_policy": {"schema_version": 1, "default": "deny", "rules": []}}
  calls = []
  host = SimpleNamespace(store=store, root=store.root, runtime_root=tmp_path / ("c" * 64), manifest=lambda: manifest,
    config={"instance_root": str(tmp_path / "instance"), "lock_identity": "a" * 64, "slice_identity": "b" * 64},
    service=SimpleNamespace(active_children=2))
  def spawn(command, lease):
    calls.append(lease["lease_id"])
    processes.current[201] = identity(201)
    return identity(201)
  host.spawn = spawn
  host.resolve_command = lambda lease, program, payload: SpawnCommand(("fake-host",), source, {})
  host.activate = lambda lease: None
  host.service = SupervisorService(store, lambda *args: host.resolve_command(*args), lambda *args: host.spawn(*args))
  with Tree(host.runtime_root, create=True) as tree:
    tree.write_state("runtime/commands.json", json_bytes({"schema_version": 1, "programs": {"delegate-pi": {"entrypoint": "runtime/delegate-pi-main.mjs", "kind": "external", "engine": "node"}}}))
    tree.write_state("runtime/delegate-pi-main.mjs", b"fixture, never execute")
    for name in ("general", "review"):
      tree.write_state("supervisor/shared/skills/model-delegate/presets/" + name + ".md", b"Use readonly tools and report evidence.")
  controller = DelegateController(host)
  args = {"idempotency_key": "once", "backend": "pi", "mode": "review", "preset": "review", "task": "Review fixture",
    "cwd": str(source), "model": {"provider_id": "agentcfg-fictional", "model_id": "model"}, "timeout_seconds": 30}
  return controller, host, args, calls


def test_delegate_prepares_immutable_identity_then_requires_ready_without_resend(tmp_path):
  controller, host, args, calls = fixture(tmp_path)
  principal = Principal("manager")
  request = controller.prepare(principal, args)
  assert host.store.read(request["lease_id"])["state"] == "allocating"
  assert request["workspace_write_lease_ids"] == []
  assert controller.prepare(principal, args) == request
  assert calls == []
  assert controller.start(principal, request["run_id"])["state"] == "start_unknown"
  assert controller.start(principal, request["run_id"])["state"] == "start_unknown"
  assert len(calls) == 1
  with Tree(controller.root) as tree:
    tree.write_state("reports/" + request["run_id"] + "/ready.json", json_bytes({"ready": True,
      **{key: request[key] for key in ("run_id", "lease_id", "request_digest")}}))
  assert controller.ready(request["run_id"]) is True
  assert controller.runs.status(request["run_id"])["state"] == "running"
  assert controller.cancel(principal, request["run_id"])["termination_confirmed"] is False
  assert host.store.read(request["lease_id"])["state"] == "cancel_requested"


def test_worker_managed_channel_and_changed_idempotency_content_cannot_allocate(tmp_path):
  controller, host, args, calls = fixture(tmp_path)
  with pytest.raises(Conflict, match="UNMETERED_EXTERNAL_DELEGATE"):
    controller.prepare(Principal("worker"), args)
  assert host.store.records() == []
  controller.prepare(Principal("manager"), args)
  with pytest.raises(Conflict, match="DELEGATE_DISPATCH_CONFLICT"):
    controller.prepare(Principal("manager"), {**args, "task": "different task"})
  assert len(host.store.records()) == 1 and not calls


def test_pi_delegate_file_tools_are_readonly_even_with_writer_policy(tmp_path):
  import base64
  controller, host, args, calls = fixture(tmp_path)
  manifest = host.manifest()
  manifest["permission_policy"]["rules"] = [{"id": "project", "kind": "file", "effect": "allow", "tool_ids": ["tk_read", "tk_write"],
    "operations": ["read", "write"], "root_ref": "project", "relative_path": ".", "match": "subtree"}]
  request = controller.prepare(Principal("manager"), args)
  controller.start(Principal("manager"), request["run_id"])
  worker = Principal("worker", request["lease_id"], request["grant_generation"])
  action = {"run_id": request["run_id"], "lease_id": request["lease_id"], "grant_generation": request["grant_generation"], "operation_id": "read",
    "action": {"tool_id": "tk_read", "operation": "read", "path": "code.txt", "offset": 0, "limit": 65536}}
  assert base64.b64decode(controller.handle(worker, "delegate_file_action", action)["data_b64"]) == b"source"
  with pytest.raises(Conflict):
    controller.handle(worker, "delegate_file_action", {**action, "action": {"tool_id": "tk_write", "operation": "write", "path": "code.txt"}})
  controller.cancel(Principal("manager"), request["run_id"])
  with pytest.raises(Conflict):
    controller.handle(worker, "delegate_file_action", action)


@pytest.mark.parametrize("api", ["openai-completions", "openai-responses"])
def test_fixed_pi_spawn_projects_one_model_and_minimal_credentials_before_exec(tmp_path, monkeypatch, api):
  from agentcfg.pi_delegate_spawn import resolve_delegate
  controller, host, args, _ = fixture(tmp_path)
  host.delegates = controller
  host.config["engine"] = "node"
  executable = tmp_path / "explicit-node"; executable.write_text("synthetic interpreter, never run"); executable.chmod(0o700)
  host.engine_executable = str(executable)
  host.repository = tmp_path / "frozen-supervisor"
  host.server = SimpleNamespace(endpoint=tmp_path / "control/control.json")
  host.service.issue_capability = lambda *args: "private-worker-token"
  key = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA"
  monkeypatch.setenv(key, "synthetic-selected")
  monkeypatch.setenv("UNRELATED_PRIVATE_KEY", "synthetic-unselected")
  with Tree(Path(host.config["instance_root"]), create=True) as tree:
    tree.write_state("pi-home/models.json", json_bytes({"providers": {"agentcfg-fictional": {"api": api, "baseUrl": "https://fixture.invalid/v1",
      "apiKey": "$" + key, "models": [{"id": "model", "input": ["text"]}, {"id": "other", "input": ["text"]}]}}}))
  with Tree(host.runtime_root, create=True) as tree:
    tree.write_state("runtime/commands.json", json_bytes({"schema_version": 1, "programs": {"delegate-pi": {"entrypoint": "runtime/delegate-pi-main.mjs", "kind": "external", "engine": "node"}}}))
    tree.write_state("runtime/delegate-pi-main.mjs", b"fixture, never execute")
    for name in ("general", "review"):
      tree.write_state("supervisor/shared/skills/model-delegate/presets/" + name + ".md", b"Use readonly tools and report evidence.")
  request = controller.prepare(Principal("manager"), args)
  lease = host.store.read(request["lease_id"])
  command = resolve_delegate(host, lease, "delegate-pi", {"run_id": request["run_id"]})
  assert command.environment[key] == "synthetic-selected"
  assert "UNRELATED_PRIVATE_KEY" not in command.environment
  assert "synthetic-selected" not in repr(command)
  models = json.loads((Path(command.environment["PI_CODING_AGENT_DIR"]) / "models.json").read_text())
  assert [row["id"] for row in models["providers"]["agentcfg-fictional"]["models"]] == ["model"]
  assert "synthetic-selected" not in json.dumps(models)
  assert command.argv[0] == str(executable) and command.cwd == Path(args["cwd"])
  assert str(executable.parent) not in command.environment["PATH"].split(os.pathsep)
  assert host.store.read(lease["lease_id"])["state"] == "allocating"


def test_only_explicit_standalone_readonly_runs_inherit_configured_request_retries(tmp_path):
  controller, host, args, _ = fixture(tmp_path)
  host.manifest()["options"]["model_delegate"]["readonly_retries"] = 2
  managed_by_parent = controller.prepare(Principal("manager"), args)
  standalone = controller.prepare(Principal("delegate"), {**args, "idempotency_key": "standalone"})
  assert controller.input(managed_by_parent["run_id"])["retry_limit"] == 0
  assert controller.input(standalone["run_id"])["retry_limit"] == 2
  from agentcfg.schema import ConfigError
  with pytest.raises(ConfigError):
    controller.prepare(Principal("manager"), {**args, "idempotency_key": "forged-retry", "retry_limit": 3})


def test_pi_oauth_delegate_projects_only_selected_unexpired_access_without_refresh_or_global_auth(tmp_path):
  from datetime import datetime, timezone
  from agentcfg.pi_delegate_spawn import resolve_delegate
  from agentcfg.secrets import CredentialError
  controller, host, args, _ = fixture(tmp_path)
  host.delegates = controller; host.config["engine"] = "node"; host.repository = tmp_path / "frozen"
  executable = tmp_path / "explicit-node"; executable.write_text("synthetic interpreter, never run"); executable.chmod(0o700)
  host.engine_executable = str(executable)
  host.server = SimpleNamespace(endpoint=tmp_path / "control")
  host.service.issue_capability = lambda *args: "private-worker-capability"
  manifest = host.manifest()
  manifest["provider_bindings"] = {"openai-codex": {"logical_id": "codex", "auth_kind": "oauth", "owner": "pi-native"}}
  manifest["model_bindings"]["reviewer"] = {"provider": "openai-codex", "model": "fixture-model"}
  manifest["allowed_models"] = [manifest["model_bindings"]["reviewer"]]
  manifest["options"]["network"]["routes"]["direct"]["provider_ids"] = ["codex"]
  args["model"] = {"provider_id": "openai-codex", "model_id": "fixture-model"}
  auth = {"openai-codex": {"type": "oauth", "access": "synthetic-selected-access", "refresh": "synthetic-refresh-never-copied", "expires": datetime.now(timezone.utc).timestamp() * 1000 + 60000},
    "other": {"type": "oauth", "access": "synthetic-other-account", "refresh": "synthetic-other-refresh", "expires": 1}}
  with Tree(Path(host.config["instance_root"]), create=True) as tree: tree.write_state("pi-home/auth.json", json_bytes(auth))
  request = controller.prepare(Principal("delegate"), args)
  lease = host.store.read(request["lease_id"])
  command = resolve_delegate(host, lease, "delegate-pi", {"run_id": request["run_id"]})
  assert "synthetic-selected-access" in command.environment.values()
  assert "synthetic-refresh-never-copied" not in command.environment.values()
  assert "synthetic-other-account" not in command.environment.values()
  serialized = "\n".join(path.read_text() for path in host.root.rglob("*.json"))
  assert "synthetic-selected-access" not in serialized and "synthetic-refresh-never-copied" not in serialized
  auth["openai-codex"]["expires"] = 0
  with Tree(Path(host.config["instance_root"])) as tree: tree.write_state("pi-home/auth.json", json_bytes(auth))
  with pytest.raises(CredentialError): resolve_delegate(host, lease, "delegate-pi", {"run_id": request["run_id"]})


def test_pi_delegate_cannot_read_a_machine_denied_subroot_through_project_allow(tmp_path):
  controller, host, args, _ = fixture(tmp_path)
  secret = Path(args["cwd"]) / "private"; secret.mkdir(); (secret / "key").write_text("synthetic-private")
  manifest = host.manifest()
  manifest["options"]["paths"]["roots"]["private"] = {"path": str(secret), "purpose": "read"}
  manifest["options"]["permissions"] = {"denied_roots": ["private"]}
  manifest["permission_policy"]["rules"] = [{"id": "read", "kind": "file", "effect": "allow", "tool_ids": ["tk_read"], "operations": ["read"], "root_ref": "project", "relative_path": ".", "match": "subtree"}]
  request = controller.prepare(Principal("manager"), args)
  controller.start(Principal("manager"), request["run_id"])
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    controller.file_action(Principal("worker", request["lease_id"], request["grant_generation"]), {"run_id": request["run_id"], "lease_id": request["lease_id"],
      "grant_generation": request["grant_generation"], "operation_id": "read", "action": {"tool_id": "tk_read", "operation": "read", "path": "private/key", "offset": 0, "limit": 100}})


def test_cursor_delegate_uses_only_selected_instance_access_and_bun_flags(tmp_path, monkeypatch):
  from agentcfg.pi_delegate_spawn import resolve_delegate
  from datetime import datetime, timezone
  controller, host, args, _ = fixture(tmp_path)
  host.delegates = controller; host.repository = tmp_path / "frozen-supervisor"; host.config["engine"] = "bun"
  executable = tmp_path / "explicit-bun"; executable.write_text("synthetic interpreter, never run"); executable.chmod(0o700)
  host.engine_executable = str(executable)
  host.server = SimpleNamespace(endpoint=tmp_path / "control/control.json"); host.service.issue_capability = lambda *_: "worker-token"
  manifest = host.manifest(); manifest["provider_bindings"] = {"cursor": {"logical_id": "cursor", "auth_kind": "oauth", "owner": "pi-cursor"}}
  manifest["model_bindings"]["reviewer"] = {"provider": "cursor", "model": "fixture-cursor"}
  manifest["allowed_models"] = [{"provider": "cursor", "model": "fixture-cursor"}]
  manifest["options"]["network"]["routes"]["direct"]["provider_ids"] = ["cursor"]
  manifest["options"]["cursor"] = {"endpoint": "https://agentn.us.api5.cursor.sh", "network_route": "direct"}
  args["model"] = {"provider_id": "cursor", "model_id": "fixture-cursor"}
  with Tree(host.runtime_root) as tree:
    tree.write_state("runtime/commands.json", json_bytes({"schema_version": 1, "programs": {"delegate-pi": {"entrypoint": "runtime/delegate-pi-main.mjs", "kind": "external", "engine": "bun"}}}))
  with Tree(Path(host.config["instance_root"]), create=True) as tree:
    tree.write_state("pi-home/auth.json", json_bytes({"cursor": {"type": "oauth", "access": "synthetic-selected-cursor", "refresh": "must-not-copy-refresh", "expires": datetime.now(timezone.utc).timestamp() * 1000 + 600000}}))
    tree.write_state("pi-home/cursor-cache/model-catalog.json", json_bytes({"version": 1, "savedAt": 1, "tokenHash": "must-not-copy-token-hash", "rawModels": [{"id": "fixture-cursor"}], "parameterizedModels": []}))
  monkeypatch.setenv("CURSOR_ACCESS_TOKEN", "unselected-global-token")
  request = controller.prepare(Principal("manager"), args)
  command = resolve_delegate(host, host.store.read(request["lease_id"]), "delegate-pi", {"run_id": request["run_id"]})
  assert command.argv[0] == str(executable) and "--no-install" in command.argv and "--no-env-file" in command.argv
  assert command.environment["CURSOR_ACCESS_TOKEN"] == "synthetic-selected-cursor"
  assert command.environment["PI_CURSOR_SYSTEM_CREDENTIALS"] == "deny"
  worker_path = host.root / "activity/delegate-worker-inputs" / (request["lease_id"] + ".json")
  assert "synthetic-selected-cursor" not in worker_path.read_text() and "must-not-copy-refresh" not in worker_path.read_text()
  copied = Path(command.environment["PI_CURSOR_CACHE_DIR"]) / "model-catalog.json"
  assert "tokenHash" not in copied.read_text()
  assert command.environment["CURSOR_CONFIG_DIR"].startswith(str(host.root))


def test_configuration_rejection_before_spawn_releases_only_unstarted_admission(tmp_path):
  from agentcfg.pi_codex_admission import CodexAdmissionError
  controller, host, args, calls = fixture(tmp_path)
  principal = Principal("manager")
  request = controller.prepare(principal, args)
  def reject_config(*_args): raise CodexAdmissionError("CODEX_SYSTEM_CONFIG_PRESENT")
  host.resolve_command = reject_config
  with pytest.raises(CodexAdmissionError, match="CODEX_SYSTEM_CONFIG_PRESENT"):
    controller.start(principal, request["run_id"])
  lease = host.store.read(request["lease_id"])
  assert calls == [] and not lease["spawn_committed"]
  assert host.store.reconcile(lease["lease_id"])["protected"] is False


def capacity_fixture(tmp_path, monkeypatch):
  controller, host, args, calls = fixture(tmp_path)
  # 占满容量的工作和本次分配独立；只使用进程身份替身，不创建任何子进程。
  occupied_identity = identity(302)
  host.store.processes.current[302] = occupied_identity
  occupied = host.store.begin(kind="worker", execution_id="capacity-worker", task_id="capacity-task", attempt_id="capacity-attempt",
    lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
    planned_workspaces=[], spawn=lambda _lease: occupied_identity)
  host.service.active_children = 1
  assert len(host.service.execution_children()) == 1
  monkeypatch.setattr(host, "resolve_command", lambda *_: pytest.fail("capacity busy must precede command resolution"))
  monkeypatch.setattr(host, "activate", lambda *_: pytest.fail("unstarted allocation must never activate"))
  principal = Principal("manager")
  request = controller.prepare(principal, args)
  return controller, host, args, calls, principal, request, occupied


def test_capacity_busy_retires_only_unstarted_allocation_with_valid_failed_receipt_and_no_replay(tmp_path, monkeypatch):
  from agentcfg.model_delegate import validate_record
  controller, host, args, calls, principal, request, occupied = capacity_fixture(tmp_path, monkeypatch)
  with pytest.raises(Conflict, match="^DELEGATE_CAPACITY_BUSY$"):
    controller.start(principal, request["run_id"])
  lease = host.store.read(request["lease_id"])
  assert lease["state"] == "failed" and lease["spawn_committed"] is False and lease["process_identity"] is None
  proof = host.store.reconcile(lease["lease_id"])
  assert proof["protected"] is False
  assert proof["termination_evidence"]["kind"] == "never-started" and proof["termination_evidence"]["verified"] is True
  row = controller.runs.read(request["run_id"])
  assert row["state"] == "failed" and row["receipt"]["terminal_status"] == "failed"
  validate_record("receipt-v2", row["receipt"], schemas=controller.runs.schemas)
  assert row["receipt"]["resources_reclaimed"] is True and row["receipt"]["process_terminated"] is True
  assert row["receipt"]["observed_model"] is None and row["receipt"]["backend_resume_token"] is None
  assert calls == [] and host.store.processes.signals == []
  assert host.store.read(occupied["lease_id"]) == occupied
  assert host.store.reconcile(occupied["lease_id"])["protected"] is True
  assert controller.prepare(principal, args) == request
  assert controller.start(principal, request["run_id"])["state"] == "failed"
  assert controller.runs.read(request["run_id"])["receipt"] == row["receipt"]
  assert calls == []


def test_capacity_busy_abort_failure_keeps_unknown_protected_allocation_without_false_receipt(tmp_path, monkeypatch):
  controller, host, args, calls, principal, request, occupied = capacity_fixture(tmp_path, monkeypatch)
  aborts = []
  def abort_failure(lease_id, owner):
    aborts.append((lease_id, owner))
    raise Conflict("synthetic abort remains unknown")
  monkeypatch.setattr(host.store, "abort_allocation", abort_failure)
  assert controller.start(principal, request["run_id"])["state"] == "start_unknown"
  assert aborts == [(request["lease_id"], host.store.owner)]
  lease = host.store.read(request["lease_id"])
  proof = host.store.reconcile(lease["lease_id"])
  assert lease["state"] == "allocating" and lease["spawn_committed"] is False and lease["process_identity"] is None
  assert proof["protected"] is True and proof["termination_evidence"] is None
  row = controller.runs.read(request["run_id"])
  assert row["receipt"] is None and row["verification"] == "unverified"
  assert host.store.read(occupied["lease_id"]) == occupied
  assert controller.prepare(principal, args) == request
  assert controller.start(principal, request["run_id"])["state"] == "start_unknown"
  assert len(aborts) == 1 and calls == [] and host.store.processes.signals == []


def test_modern_start_acceptance_does_not_claim_native_ready(tmp_path):
  controller, host, args, calls = fixture(tmp_path)
  host.processes = host.store.processes
  request = controller.prepare(Principal("manager"), args)
  reply = controller.start(Principal("manager"), request["run_id"])
  assert reply["state"] == "start_unknown"
  assert controller._modern_start_accepted(request) is True
  assert controller.ready(request["run_id"]) is False
  assert controller.runs.read(request["run_id"])["state"] == "start_unknown"
  with Tree(controller.root) as tree:
    tree.write_state("reports/" + request["run_id"] + "/ready.json", json_bytes({"ready": True,
      **{key: request[key] for key in ("run_id", "lease_id", "request_digest")}}))
  assert controller.ready(request["run_id"]) is True
  assert controller.runs.read(request["run_id"])["state"] == "running"
  assert calls == [request["lease_id"]]


@pytest.mark.parametrize("changed", ["birth", "generation"])
def test_modern_start_acceptance_rejects_changed_physical_identity(tmp_path, changed):
  controller, host, args, _ = fixture(tmp_path)
  host.processes = host.store.processes
  request = controller.prepare(Principal("manager"), args)
  controller.start(Principal("manager"), request["run_id"])
  if changed == "birth":
    host.processes.current[201] = identity(201, "different-birth")
  else:
    request = {**request, "grant_generation": request["grant_generation"] + 1}
  assert controller._modern_start_accepted(request) is False


def test_modern_lost_start_ack_preserves_unknown_and_does_not_resend(tmp_path, monkeypatch):
  # 来源替身仅测试已授权控制器故障窗口，不证明实际source注册资格。
  from test_model_delegate_v3_intents import ORIGIN, BINDING, submit
  from test_model_delegate_v3_execution import BUDGET
  controller, host, args, calls = fixture(tmp_path)
  host.processes = host.store.processes
  host._delegate_input_oracle = lambda request: 0
  source = {"origin": ORIGIN, "source_kind": "model-tool"}
  controller.sources = SimpleNamespace(resolve=lambda *a, **k: source,
    authorize=lambda *a: None, binding=lambda *a: (BINDING, BUDGET))
  action = submit(task=args["task"], cwd=args["cwd"], model=args["model"])
  original = controller.start
  def lost(*a):
    original(*a)
    raise OSError("synthetic lost ACK")
  monkeypatch.setattr(controller, "start", lost)
  with pytest.raises(OSError): controller.modern_action(Principal("manager"), "fixture-ref", action)
  run_id = next(iter(controller.modern_attempts.values()))["logical_run_id"]
  record = controller.logical.private(run_id)
  assert record["actions"][0]["state"] == "unknown"
  assert record["budget"]["reservations"]["cost_microunits"] == BUDGET["max_cost_microunits"]
  controller.modern_action(Principal("manager"), "fixture-ref", action)
  assert len(calls) == 1


def test_modern_worker_authority_uses_physical_birth_and_persisted_cancel(tmp_path):
  from test_model_delegate_v3_intents import ORIGIN, BINDING, submit
  from test_model_delegate_v3_execution import BUDGET
  controller, host, args, _ = fixture(tmp_path)
  host.processes = host.store.processes
  request = controller.prepare(Principal("manager"), args)
  started = controller.logical.begin(ORIGIN, submit(), BINDING, BUDGET)
  controller.logical.update(started["run_id"], started["action_key"], state="sending", physical=request)
  controller.modern_attempts[request["run_id"]] = {"logical_run_id": started["run_id"], "action_key": started["action_key"]}
  controller.start(Principal("manager"), request["run_id"])
  worker = Principal("worker", request["lease_id"], request["grant_generation"])
  assert controller.handle(worker, "delegate_authorize_v3", {"run_id": request["run_id"]})["valid"] is True
  host.processes.current[201] = identity(201, "reused-pid")
  with pytest.raises(Conflict, match="DELEGATE_CONTROL_DENIED"):
    controller.handle(worker, "delegate_authorize_v3", {"run_id": request["run_id"]})
  host.processes.current[201] = identity(201)
  controller.logical.revoke(started["run_id"])
  with pytest.raises(Conflict, match="DELEGATE_GRANT_REVOKED"):
    controller.handle(worker, "delegate_meter_v3", {"run_id": request["run_id"], "metric": "calls", "sequence": 1})
  assert controller.logical.private(started["run_id"])["budget"]["totals"]["calls"] == 0


def test_modern_resume_mapping_preserves_private_original_and_rejects_changed_history(tmp_path, monkeypatch):
  # 测原owner的私有路径/内容绑定；fake终止proof不作为实际终止资格。
  controller, host, args, _ = fixture(tmp_path)
  request = controller.prepare(Principal("manager"), args)
  directory = controller.root / "reports" / request["run_id"]
  with Tree(directory, create=True) as tree:
    tree.write_state("sessions/original.jsonl", b'{"type":"session","id":"native-original"}\n')
    tree.write_state("session-v3.json", json_bytes({"schema_version": 3, "physical_run_id": request["run_id"],
      "attempt_id": request["attempt_id"], "session_id": "native-original",
      "session_path": str(directory / "sessions/original.jsonl"), "cwd": request["cwd"]}))
  token = controller._modern_resume_ref(request, directory)
  assert len(token) == 32 and token != str(directory / "sessions/original.jsonl")
  monkeypatch.setattr(controller.runs, "read", lambda _: {"verification": "verified-execution", "request": request,
    "receipt": {"backend_resume_token": token}})
  monkeypatch.setattr("agentcfg.pi_delegate.saved_termination", lambda *a: {"termination_verified": True, "resources_reclaimed": True})
  following = {**request, "continuation_of": request["run_id"]}
  assert controller.modern_resume_path(following) == str(directory / "sessions/original.jsonl")
  with Tree(directory) as tree: tree.write_state("sessions/original.jsonl", b"changed-private-history\n")
  with pytest.raises(Conflict, match="DELEGATE_RESUME_INVALID"): controller.modern_resume_path(following)


@pytest.mark.parametrize("changed", [None, "request-id", "birth", "generation", "cancel"])
def test_modern_private_live_ack_is_exact_and_never_resends_or_revives_cancel(tmp_path, changed):
  import io
  from test_model_delegate_v3_intents import ORIGIN, BINDING, submit, follow
  from test_model_delegate_v3_execution import BUDGET
  controller, host, args, _ = fixture(tmp_path)
  host.processes = host.store.processes
  request = controller.prepare(Principal("manager"), args)
  started = controller.logical.begin(ORIGIN, submit(), BINDING, BUDGET)
  controller.logical.update(started["run_id"], started["action_key"], state="sending", physical=request)
  controller.logical.meter_claim(started["run_id"], started["action_key"], "calls", 1, synthetic_cost=0)
  controller.start(Principal("manager"), request["run_id"])
  action = follow("message", started["run_id"], "live-message", text="literal")
  sent = controller.logical.begin(ORIGIN, action, BINDING, BUDGET)
  controller.logical.update(sent["run_id"], sent["action_key"], state="sending", physical=request)
  channel = io.BytesIO()
  host.children = {request["lease_id"]: {"process": SimpleNamespace(poll=lambda: None, stdin=channel)}}
  controller.modern_live_action(sent["run_id"], sent["action_key"], request, action)
  frame = json.loads(channel.getvalue())
  with Tree(controller.root) as tree:
    saved = json.loads(tree.read("live-frames-v3/" + sent["action_key"] + ".json")[0])
  assert saved["frame"] == frame
  lease = host.store.read(request["lease_id"])
  ack = {"schema_version": 3, "accepted": True, "sent": True, "request_id": frame["request_id"], "action_key": sent["action_key"],
    "expected_physical_run_id": request["run_id"], "native_action_id": None, "process_identity": lease["process_identity"],
    "grant_generation": request["grant_generation"], "runtime_identity": request["runtime_identity"]}
  if changed == "request-id": ack["request_id"] = "wrong"
  elif changed == "birth": ack["process_identity"] = identity(201, "wrong-birth")
  elif changed == "generation": ack["grant_generation"] += 1
  elif changed == "cancel": controller.logical.revoke(sent["run_id"])
  with Tree(controller.root / "reports" / request["run_id"], create=True) as tree:
    tree.write_state("live-ack-" + sent["action_key"] + ".json", json_bytes(ack))
  before = channel.getvalue()
  if changed in {"request-id", "birth", "generation"}:
    with pytest.raises(Conflict, match="DELEGATE_LIVE_ACK_INVALID"):
      controller._modern_live_ack(sent["run_id"], sent["action_key"])
  else:
    assert controller._modern_live_ack(sent["run_id"], sent["action_key"]) is (changed is None)
    assert controller._modern_live_ack(sent["run_id"], sent["action_key"]) is (changed is None)
  assert channel.getvalue() == before
  stored = controller.logical.private(sent["run_id"])["actions"][-1]
  assert stored["state"] == ("acknowledged" if changed is None else "unknown")
  assert stored["native_action_id"] is None


def test_modern_spawn_uses_default_initializer_projection_and_never_copies_native_auth(tmp_path, monkeypatch):
  import hashlib
  from agentcfg.pi_delegate_spawn import resolve_delegate
  from test_model_delegate_v3_intents import ORIGIN, BINDING, submit
  from test_model_delegate_v3_execution import BUDGET
  controller, host, args, _ = fixture(tmp_path)
  host.delegates = controller; host.config["engine"] = "node"
  host.repository = tmp_path / "supervisor"; host.server = SimpleNamespace(endpoint=tmp_path / "control.json")
  host.service.issue_capability = lambda *a: "private-worker-capability"
  executable = tmp_path / "node"; executable.write_bytes(b"never execute"); executable.chmod(0o700); host.engine_executable = str(executable)
  provider_id, model_id = args["model"]["provider_id"], args["model"]["model_id"]
  config = {"api": "openai-completions", "baseUrl": "https://synthetic.invalid/v1", "models": [{"id": model_id, "input": ["text"]}]}
  binding = {"logical_id": "fictional", "auth_kind": "api-key", "owner": "pi-environment"}
  host.manifest().update(provider_bindings={provider_id: binding}, model_configuration={"schema_version": 1,
    "providers": {provider_id: {**binding, "credential_ref": "selected-ref", "config": config}}})
  variable = "AGENTCFG_PI_CREDENTIAL_" + hashlib.sha256(b"fictional").hexdigest()[:16].upper()
  monkeypatch.setenv(variable, "synthetic-private")
  with Tree(Path(host.config["instance_root"]), create=True) as tree:
    tree.write_state("pi-home/models.json", json_bytes({"providers": {provider_id: {**config, "apiKey": "$" + variable}}}))
    tree.write_state("pi-home/auth.json", b"synthetic unrelated native account sentinel\n")
  with Tree(host.runtime_root) as tree:
    tree.write_state("runtime/commands.json", json_bytes({"schema_version": 1, "programs": {"delegate-pi": {
      "entrypoint": "runtime/official-delegate-worker-main.mjs", "kind": "external", "engine": "node"}}}))
    tree.write_state("runtime/official-delegate-worker-main.mjs", b"own modern entry, never execute")
  request = controller.prepare(Principal("manager"), args)
  logical = controller.logical.begin(ORIGIN, submit(), BINDING, BUDGET)
  controller.logical.update(logical["run_id"], logical["action_key"], state="sending", physical=request)
  controller.modern_attempts[request["run_id"]] = {"logical_run_id": logical["run_id"], "action_key": logical["action_key"]}
  original_read = Tree.read
  def no_native_auth(self, name, **kwargs):
    assert str(name) != "pi-home/auth.json", "modern worker must not read/copy native credentials"
    return original_read(self, name, **kwargs)
  monkeypatch.setattr(Tree, "read", no_native_auth)
  command = resolve_delegate(host, host.store.read(request["lease_id"]), "delegate-pi", {"run_id": request["run_id"]})
  assert command.stdin_pipe is True and "--experimental-import-meta-resolve" in command.argv
  assert command.environment[variable] == "synthetic-private"
  worker = json.loads(Path(command.argv[-1]).read_bytes())
  assert worker["schema_version"] == 3
  assert worker["scoped_manifest"]["allowed_models"] == [{"provider": provider_id, "model": model_id}]
  assert "synthetic-private" not in json.dumps(worker)
  assert not (Path(worker["scoped_instance_root"]) / "pi-home/auth.json").exists()

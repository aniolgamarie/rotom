"""Shell启动描述与实际租约取消；worker和进程均不执行。"""

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import sys

import pytest

from agentcfg.activity import protected
from agentcfg.deployment import json_bytes
from agentcfg.storage import Conflict, Tree
from agentcfg.schema import ConfigError
from test_pi_admitted_shell import fixture, prepare, consume, external, running_worker, issue


ENTRY = "supervisor/scripts/pi-shell.py"


def configured(tmp_path):
  f = fixture(tmp_path)
  host = f[2]
  host.server = SimpleNamespace(endpoint=host.root / "private.sock")
  with Tree(host.runtime_root) as tree:
    tree.write_state("runtime/commands.json", json_bytes({"schema_version": 1, "programs": {
      "ordinary-shell": {"entrypoint": ENTRY, "kind": "external", "engine": "python"}}}))
    tree.write_state(ENTRY, b"synthetic worker, never execute")
    tree.write_state(".agentcfg-receipt.json", json_bytes({"schema_version": 2, "identity": host.runtime_root.name,
      "files": {ENTRY: {"kind": "file", "mode": 0o600, "sha256": hashlib.sha256(b"synthetic worker, never execute").hexdigest()},
        "runtime/commands.json": {"kind": "file", "mode": 0o600, "sha256": hashlib.sha256(tree.read("runtime/commands.json")[0]).hexdigest()}}}))
  return f


def launched(f):
  prepared = prepare(f)
  ticket = consume(f, prepared)
  lease = f[2].store.read(ticket["lease_id"])
  command = f[0].command(lease, {"operation_id": prepared["operation_id"]})
  return prepared, ticket, lease, command


def test_fixed_private_worker_description_and_once_input(tmp_path, monkeypatch):
  f = configured(tmp_path)
  monkeypatch.setenv("SECRET_ACCOUNT", "must-not-inherit")
  prepared, ticket, lease, command = launched(f)
  assert command.argv == (str(f[2].runtime_root / ENTRY),)
  assert set(command.environment) == {"HOME", "TMPDIR", "PATH", "LANG", "LC_ALL"}
  assert command.environment["HOME"] == "/.rotom-shell-bootstrap/home"
  assert not (f[2].root / "activity/ordinary-shell-homes").exists()
  assert not command.launch.active and not command.launch.attempted
  assert f[2].service.capabilities == {}
  assert command.capture_root == f[2].root / "activity/outputs" / lease["lease_id"]
  assert not command.stdin_pipe and command.terminal_size is None and command.process_scope == "linux-shell"
  assert "private-script-sentinel" not in repr(command.argv) + repr(command.environment) + repr(command)
  worker = running_worker(f, ticket)
  data = f[0].take_input(worker, prepared["operation_id"])
  assert data["process_identity"] == f[2].store.read(worker.lease_id)["process_identity"]
  assert "private-script-sentinel" in data["command"]
  with pytest.raises(Conflict): f[0].take_input(worker, prepared["operation_id"])
  with pytest.raises(Conflict): f[0].command(lease, {"operation_id": prepared["operation_id"]})


@pytest.mark.parametrize("fault", ["unconsumed", "lease", "generation", "owner", "allocation", "revoked", "cancel", "parent", "context"])
def test_invalid_launch_never_issues_capability(tmp_path, monkeypatch, fault):
  f = configured(tmp_path); prepared = prepare(f)
  if fault == "unconsumed": lease = f[2].store.read(f[3].lease_id)
  else:
    ticket = consume(f, prepared); lease = f[2].store.read(ticket["lease_id"])
  if fault == "lease": lease["lease_id"] = f[3].lease_id
  if fault == "generation": lease["grant_generation"] += 1
  if fault == "owner": lease["owner_nonce"] = "foreign"
  if fault == "allocation": lease["execution_id"] = "foreign"
  if fault == "revoked": f[0].revoke(f[3], prepared["operation_id"])
  if fault == "cancel":
    running_worker(f, ticket); lease = f[2].store.request_cancel(ticket["lease_id"], f[2].store.owner)
  if fault == "parent": f[2].store.processes.current.pop(202)
  if fault == "context": f[2].manifest()["options"]["external_tools"]["shell"]["timeout_seconds"] = 29
  calls = []
  monkeypatch.setattr(f[2].service, "issue_capability", lambda *args: calls.append(args) or "synthetic-capability")
  with pytest.raises(Conflict): f[0].command(lease, {"operation_id": prepared["operation_id"]})
  assert calls == []


@pytest.mark.parametrize("fault", ["missing", "definition", "entry", "mode", "hash", "receipt", "identity"])
def test_runtime_drift_cannot_launch(tmp_path, monkeypatch, fault):
  f = configured(tmp_path); prepared = prepare(f); ticket = consume(f, prepared)
  root = f[2].runtime_root
  if fault == "missing": (root / "runtime/commands.json").unlink()
  if fault == "definition": (root / "runtime/commands.json").write_text('{"programs":{"ordinary-command":{}}}')
  if fault == "entry": (root / ENTRY).unlink()
  if fault == "mode": (root / ENTRY).chmod(0o700)
  if fault == "hash": (root / ENTRY).write_bytes(b"drift")
  if fault in ("receipt", "identity"):
    path = root / ".agentcfg-receipt.json"; value = json.loads(path.read_bytes())
    value["schema_version" if fault == "receipt" else "identity"] = 1 if fault == "receipt" else "wrong"
    path.write_bytes(json_bytes(value))
  calls = []; monkeypatch.setattr(f[2].service, "issue_capability", lambda *args: calls.append(args) or "synthetic-capability")
  with pytest.raises((Conflict, ConfigError)): f[0].command(f[2].store.read(ticket["lease_id"]), {"operation_id": prepared["operation_id"]})
  assert calls == []


def test_retry_does_not_extend_timeout_and_tick_retains_writer(tmp_path, monkeypatch):
  f = configured(tmp_path); now = [f[0]._now_ms()]
  monkeypatch.setattr(f[0], "_now_ms", lambda: now[0])
  prepared, ticket, lease, _ = launched(f)
  deadline = f[0].records[prepared["operation_id"]]["run_deadline_ms"]
  now[0] += 1000
  f[0].command(lease, {"operation_id": prepared["operation_id"]})
  assert f[0].records[prepared["operation_id"]]["run_deadline_ms"] == deadline
  worker = running_worker(f, ticket); now[0] = deadline
  with pytest.raises(Conflict): f[0].take_input(worker, prepared["operation_id"])
  f[0].tick(); current = f[2].store.read(ticket["lease_id"])
  assert current["state"] == "cancel_requested" and protected(current)
  assert f[2].store.workspaces.read(current["planned_workspaces"][0])["state"] != "released"
  f[0].tick(); assert f[2].store.read(ticket["lease_id"]) == current
  assert f[0].records[prepared["operation_id"]]["private"] is None


@pytest.mark.parametrize("spawned", [False, True])
def test_revoke_tick_requests_stop_only_with_process_identity(tmp_path, spawned):
  f = configured(tmp_path); prepared, ticket, lease, _ = launched(f)
  if spawned: running_worker(f, ticket)
  f[0].revoke(f[3], prepared["operation_id"]); f[0].tick()
  current = f[2].store.read(ticket["lease_id"])
  assert current["state"] == ("cancel_requested" if spawned else "allocating")
  assert protected(current) and len(external(f)) == 1
  f[0].tick(); assert f[2].store.read(ticket["lease_id"]) == current


def test_unknown_allocation_tick_never_retries_or_releases(tmp_path, monkeypatch):
  f = configured(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  original = f[2].store.allocate; calls = []
  def lost(**args): calls.append(args); original(**args); raise OSError("lost")
  monkeypatch.setattr(f[2].store, "allocate", lost)
  with pytest.raises(OSError): f[0].consume(f[3], permit)
  f[0].revoke(f[3], prepared["operation_id"]); f[0].tick(); f[0].tick()
  lease, = external(f)
  assert len(calls) == 1 and lease["state"] == "allocating" and protected(lease)


def test_payload_closed_and_consumed_context_is_not_requested_again(tmp_path, monkeypatch):
  f = configured(tmp_path); prepared = prepare(f); ticket = consume(f, prepared)
  lease = f[2].store.read(ticket["lease_id"])
  monkeypatch.setattr(f[0], "_current", lambda _: pytest.fail("consumed request context lookup"))
  with pytest.raises(ConfigError): f[0].command(lease, {"operation_id": prepared["operation_id"], "command": "private"})
  f[0].command(lease, {"operation_id": prepared["operation_id"]})


@pytest.mark.parametrize("input_taken", [False, True])
def test_deadline_keeps_unspawned_or_stops_started_after_input_handoff(tmp_path, monkeypatch, input_taken):
  f = configured(tmp_path); now = [f[0]._now_ms()]
  monkeypatch.setattr(f[0], "_now_ms", lambda: now[0])
  prepared, ticket, lease, _ = launched(f)
  if input_taken:
    worker = running_worker(f, ticket)
    f[0].take_input(worker, prepared["operation_id"])
  now[0] = f[0].records[prepared["operation_id"]]["run_deadline_ms"]
  with pytest.raises(Conflict): f[0].command(lease, {"operation_id": prepared["operation_id"]})
  f[0].tick()
  row = f[2].store.read(ticket["lease_id"])
  assert row["state"] == ("cancel_requested" if input_taken else "allocating")
  assert protected(row) and f[0].records[prepared["operation_id"]]["input_revoked"]
  assert f[0].records[prepared["operation_id"]]["private"] is None


def test_unknown_process_observation_with_identity_still_requests_cancel(tmp_path):
  f = configured(tmp_path); prepared, ticket, lease, _ = launched(f)
  running_worker(f, ticket)
  f[2].store.processes.current.pop(203)
  f[0].revoke(f[3], prepared["operation_id"]); f[0].tick()
  row = f[2].store.read(ticket["lease_id"])
  assert row["state"] == "cancel_requested" and protected(row)


@pytest.mark.parametrize("fault", ["extra-root", "schema-bool", "schema-version", "schema-missing", "programs-type", "definition-extra", "commands-hash", "commands-mode", "duplicate-commands", "duplicate-receipt"])
def test_command_document_is_closed_and_receipted(tmp_path, monkeypatch, fault):
  f = configured(tmp_path); prepared = prepare(f); ticket = consume(f, prepared)
  root = f[2].runtime_root
  path = root / "runtime/commands.json"
  receipt_path = root / ".agentcfg-receipt.json"
  doc = json.loads(path.read_bytes()); receipt = json.loads(receipt_path.read_bytes())
  if fault == "extra-root": doc["extra"] = "invalid"
  elif fault == "schema-bool": doc["schema_version"] = True
  elif fault == "schema-version": doc["schema_version"] = 2
  elif fault == "schema-missing": del doc["schema_version"]
  elif fault == "programs-type": doc["programs"] = []
  elif fault == "definition-extra": doc["programs"]["ordinary-shell"]["extra"] = True
  elif fault == "commands-hash": doc["programs"]["extra-program"] = {}
  elif fault == "commands-mode": path.chmod(0o700)
  if fault == "duplicate-commands":
    data = json_bytes(doc).replace(b'"schema_version":1', b'"schema_version":99,"schema_version":1')
    assert data != json_bytes(doc)
  else: data = json_bytes(doc)
  path.write_bytes(data)
  # 格式负例的收据与字节相符，独立证明闭合/重复键验证。
  if fault != "commands-hash": receipt["files"]["runtime/commands.json"]["sha256"] = hashlib.sha256(data).hexdigest()
  receipt_data = json_bytes(receipt)
  if fault == "duplicate-receipt":
    receipt_data = receipt_data.replace(b'"schema_version":2', b'"schema_version":1,"schema_version":2')
    assert receipt_data != json_bytes(receipt)
  receipt_path.write_bytes(receipt_data)
  calls = []; monkeypatch.setattr(f[2].service, "issue_capability", lambda *args: calls.append(args) or "synthetic-capability")
  with pytest.raises(Conflict, match="SHELL_RUNTIME_UNAVAILABLE"):
    f[0].command(f[2].store.read(ticket["lease_id"]), {"operation_id": prepared["operation_id"]})
  assert calls == []

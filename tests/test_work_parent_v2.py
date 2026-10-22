"""父侧写前意图、一次创建与已证明结果记账；原生端点均为替身。"""
from copy import deepcopy
import os
from pathlib import Path

import pytest

from termcfg import work, work_config, herdr
from termcfg.errors import TermcfgError
from termcfg.work_state import WorkState, context_owner, SOURCE, LAUNCH_SOURCE
from work_helpers import FakeHerdr


def setup_parent(tmp_path, monkeypatch):
  directory = tmp_path / "project"
  directory.mkdir()
  shell = tmp_path / "synthetic-shell"
  shell.write_text("synthetic executable; never run")
  shell.chmod(0o700)
  monkeypatch.setenv("SHELL", str(shell))
  definition = {"label": "Problem", "launcher": "shell"}
  settings = work_config.WorkSettings(tmp_path / "private.toml", "/bin/synthetic-herdr", "trial",
    model="structured-v1", structured={"templates": {"trial": {
      "order": ["problem"], "initial": "problem", "tab_types": {"problem": definition}}}})
  client = FakeHerdr(str(tmp_path / "native" / "api.sock"), version="v2")
  state = WorkState(client.socket_path, client.identity, create=True)
  owner = context_owner(client.socket_path, "project", str(directory))
  binding = {"version": 2, "owner": owner, "endpoint": str(Path(client.socket_path).resolve()),
    "generation": list(client.identity), "epoch": "a" * 32,
    "context": {"kind": "project", "key": str(directory)}, "workspace_start": str(directory),
    "captured_home": os.environ["HOME"], "workspace_id": None, "template": "trial", "origin": "explicit",
    "types": {"problem": work_config.prepare_launch(settings, definition, directory)}}
  monkeypatch.setattr(herdr, "require_startup_evidence", lambda *a: {})
  return client, settings, state, binding


def launch(client, settings, state, binding, **kwargs):
  return work.create_instance_v2(client, settings, state, binding, "problem", label="Trial", binary=settings.herdr_binary, **kwargs)


def test_initial_parent_persists_intent_and_commit_before_each_mutation(tmp_path, monkeypatch):
  client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
  def dispatched(fake, params):
    import json
    value = json.loads(params["env"][work_config.PAYLOAD_ENV_V2])
    assert state.read_intent(value["op"])["payload_digest"]
    assert state.read("receipts", value["op"])["phase"] == "dispatched"
  def committed(fake, params):
    op = params["tokens"].get("rw2_commit")
    if op:
      assert state.read("receipts", op)["phase"] == "commit-issued"
  client.barriers[("workspace.create", "before", 1)] = dispatched
  client.barriers[("pane.report_metadata", "before", 1)] = committed
  try:
    pane = launch(client, settings, state, binding)
    saved = state.load_binding(binding["owner"])
    assert saved["workspace_id"] == pane["workspace_id"]
    assert saved["types"]["problem"]["default"]
    assert len(saved["types"]["problem"]["instances"]) == 1
    assert state.pending(binding["owner"]) == []
    assert client.call_counts["workspace.create"] == 1
    assert client.call_counts["tab.create"] == 0
    assert client.call_counts["tab.rename"] == 1
    assert client.tabs[pane["tab_id"]]["label"] == "Problem"
    assert not any(method.startswith("worktree.") or "send" in method for method, _ in client.requests)
  finally:
    state.close()


def test_initial_lost_reply_queries_but_never_adopts_or_recreates(tmp_path, monkeypatch):
  client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
  client.fail("workspace.create", when="after", error=TermcfgError(4, "synthetic response lost"))
  try:
    with pytest.raises(TermcfgError) as error:
      launch(client, settings, state, binding)
    assert error.value.code == 4
    assert state.pending(binding["owner"]) and state.load_binding(binding["owner"]) is None
    assert client.call_counts["pane.list"] >= 1
    assert client.call_counts["workspace.report_metadata"] == 0
    assert client.call_counts["pane.report_metadata"] == 0
    with pytest.raises(TermcfgError):
      launch(client, settings, state, binding)
    assert client.call_counts["workspace.create"] == 1
  finally:
    state.close()


def test_stale_type_draft_is_refused_before_creating_or_committing_another_default(tmp_path, monkeypatch):
  client, settings, state, draft = setup_parent(tmp_path, monkeypatch)
  try:
    launch(client, settings, state, draft)
    saved = state.load_binding(draft["owner"])
    draft["workspace_id"] = saved["workspace_id"]
    before = list(client.mutation_calls)
    with pytest.raises(TermcfgError) as error:
      launch(client, settings, state, draft)
    assert error.value.code == 4
    assert client.mutation_calls == before
    assert state.intents() == []
    assert state.load_binding(draft["owner"]) == saved
  finally:
    state.close()


@pytest.mark.parametrize("change", ["duplicate", "moved", "reused-terminal"])
def test_initial_ready_correlation_refuses_wrong_native_identity(tmp_path, monkeypatch, change):
  client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
  def drift(fake, params):
    pane = next(iter(fake.panes.values()))
    if change == "duplicate":
      duplicate = deepcopy(pane)
      duplicate.update(pane_id="duplicate-pane", terminal_id="duplicate-terminal")
      fake.panes[duplicate["pane_id"]] = duplicate
    elif change == "moved":
      pane["workspace_id"] = "different-workspace"
    else:
      pane["terminal_id"] = "different-terminal"
  client.barriers[("workspace.create", "after", 1)] = drift
  try:
    with pytest.raises(TermcfgError):
      launch(client, settings, state, binding)
    assert state.pending(binding["owner"])
    assert client.call_counts["pane.report_metadata"] == 0
    assert state.load_binding(binding["owner"]) is None
  finally:
    state.close()


def test_lost_commit_reply_is_observed_without_resending_commit(tmp_path, monkeypatch):
  client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
  client.fail("pane.report_metadata", when="after", error=TermcfgError(4, "synthetic commit response lost"))
  try:
    launch(client, settings, state, binding)
    commits = [params for method, params in client.requests if method == "pane.report_metadata"
      and "rw2_commit" in params["tokens"]]
    assert len(commits) == 1 and commits[0]["source"] == LAUNCH_SOURCE
    assert state.pending(binding["owner"]) == []
  finally:
    state.close()


def test_original_operation_can_finalize_proved_acceptance_without_replaying_create(tmp_path, monkeypatch):
  client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
  original = state.save_binding
  monkeypatch.setattr(state, "save_binding", lambda *a: (_ for _ in ()).throw(TermcfgError(6, "synthetic fs failure")))
  try:
    with pytest.raises(TermcfgError):
      launch(client, settings, state, binding)
    pending = state.pending(binding["owner"])
    assert len(pending) == 1 and pending[0]["phase"] == "accepted"
    monkeypatch.setattr(state, "save_binding", original)
    pane = work.finalize_instance_v2(client, state, pending[0]["op"])
    assert pane["workspace_id"] == state.load_binding(binding["owner"])["workspace_id"]
    assert state.pending(binding["owner"]) == []
    assert client.call_counts["workspace.create"] == 1
    assert client.call_counts["pane.report_metadata"] == 1
  finally:
    state.close()


def test_known_failed_acceptance_is_never_finalized_as_success(tmp_path, monkeypatch):
  client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
  def failed(fake, params):
    if params["tokens"].get("rw2_pending", "missing") is None:
      pane = next(iter(fake.panes.values()))
      pane["tokens"]["rw2_phase"] = "failed"
      pane["tokens"].pop("rw2_commit", None)
  client.barriers[("workspace.report_metadata", "after", 2)] = failed
  try:
    with pytest.raises(TermcfgError):
      launch(client, settings, state, binding)
    assert state.pending(binding["owner"])
    assert client.call_counts["workspace.create"] == 1
    assert client.call_counts["pane.focus"] == 0
  finally:
    state.close()


def test_existing_unmarked_live_owner_without_private_binding_blocks_duplicate(tmp_path, monkeypatch):
  client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
  native = client.request("workspace.create", {"cwd": binding["workspace_start"], "label": "Native", "focus": False, "env": {}})
  client.panes[native["root_pane"]["pane_id"]]["tokens"] = {"rw2_owner": binding["owner"]}
  try:
    with pytest.raises(TermcfgError):
      launch(client, settings, state, binding)
    assert client.call_counts["workspace.create"] == 1
    assert state.intents() == []
  finally:
    state.close()


@pytest.mark.parametrize("existing", [False, True])
def test_connection_only_records_proof_for_explicitly_started_server(tmp_path, monkeypatch, existing):
  from types import SimpleNamespace
  client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
  calls = []
  session = {"socket_path": client.socket_path}
  sequence = iter([session] if existing else [None, session])
  monkeypatch.setattr(work_config, "prepared_config", lambda: (tmp_path / "native.toml", "a" * 64))
  monkeypatch.setattr(work_config, "validate_native_config", lambda *a: calls.append("diagnostics"))
  monkeypatch.setattr(work_config, "resolve_executable", lambda value: str(value))
  monkeypatch.setattr(herdr, "verify_schema", lambda *a, **kw: calls.append(("schema", kw)))
  monkeypatch.setattr(herdr, "discover", lambda *a: next(sequence))
  monkeypatch.setattr(herdr, "start_headless", lambda *a: calls.append("start") or SimpleNamespace(pid=1234))
  monkeypatch.setattr(herdr, "observe_process", lambda pid: calls.append("process") or {"pid": pid})
  monkeypatch.setattr(herdr, "native_inputs", lambda *a: calls.append("inputs") or {"synthetic": "inputs"})
  monkeypatch.setattr(herdr, "record_startup_evidence", lambda *a: calls.append("record"))
  monkeypatch.setattr(herdr, "HerdrClient", lambda *a, **kw: client)
  try:
    with work.connected(settings, client.deadline, start=True) as (actual, _):
      assert actual is client
    assert ("schema", {"structured": True}) in calls
    if existing:
      assert not {"record", "start", "process", "inputs", "diagnostics"}.intersection(
        item for item in calls if isinstance(item, str))
    else:
      assert calls.index("inputs") < calls.index("start") < calls.index("process") < calls.index("record")
  finally:
    state.close()


@pytest.mark.parametrize("name", ["src/termcfg/work_state.py", "src/termcfg/work_shell.py",
  "src/termcfg/work_config.py", "schemas/local.schema.json"])
def test_v2_critical_source_tampering_changes_launch_digest(tmp_path, name):
  assert name in work.LAUNCH_FILES
  for relative in work.LAUNCH_FILES:
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((work_config.ROOT / relative).read_bytes())
  before = work.source_digest(tmp_path)
  with (tmp_path / name).open("ab") as stream:
    stream.write(b"\n")
  assert work.source_digest(tmp_path) != before


def test_existing_workspace_can_bind_a_previously_uninstantiated_type(tmp_path, monkeypatch):
  client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
  try:
    launch(client, settings, state, binding)
    current = state.load_binding(binding["owner"])
    previous_default = current["types"]["problem"]["default"]
    definition = {"label": "Shell", "launcher": "shell"}
    settings.structured["templates"]["trial"]["tab_types"]["shell"] = definition
    settings.structured["templates"]["trial"]["order"].append("shell")
    current["types"]["shell"] = work_config.prepare_launch(settings, definition, current["workspace_start"])
    pane = work.create_instance_v2(client, settings, state, current, "shell", binary=settings.herdr_binary)
    saved = state.load_binding(binding["owner"])
    assert saved["types"]["shell"]["default"]
    assert saved["types"]["problem"]["default"] == previous_default
    assert pane["workspace_id"] == saved["workspace_id"]
    assert client.call_counts["workspace.create"] == client.call_counts["tab.create"] == 1
  finally:
    state.close()

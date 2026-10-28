"""停止记录入口：真实 CLI/恢复协调器，宿主和现场观察为隔离替身。"""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import stopped_sessions, tool_maintenance as flow, workspace
from agentcfg.sessions import HostResumeBackend, LaunchReceipt
from rotom import cli, preferences, resume
from rotom.context import InputGateway
from test_rotom_interaction import Stream
from test_rotom_tool_maintenance import known, workflow, RUNS, SESSION
from test_rotom_tool_workflow_cli import command, stopped as stop_workflow, updated as update_workflow


BATCH = "b" * 32
RUN = "a" * 32


@pytest.fixture
def history_case(tmp_path, monkeypatch):
  local = str(tmp_path / "local.toml")
  ws = SimpleNamespace(agent="dsh", profile="dsh-default", local_path=Path(local),
    instance=tmp_path / "instance", binding={"machine": "fixture", "local": local, "profile": "dsh-default"})
  target = known(ws, SESSION, tmp_path)
  row = {"agent": ws.agent, "profile": ws.profile, "scope": {**ws.binding, "agent": ws.agent},
    "batch_id": BATCH, "run_id": RUN, "session_id": SESSION, "cwd": str(tmp_path),
    "title": "修复示例", "title_source": "user", "source": "workflow", "session_ref": asdict(target.ref),
    "stop_status": "stopped", "restore_status": "available", "restorable": True, "observed_at_ns": 1,
    "next_commands": {"status": ["rotom", "agent", "maintenance", "status", "--batch", BATCH], "restore": None}}
  state = SimpleNamespace(ws=ws, target=target, rows=[row], issues=[], incomplete=False,
    queries=[], loads=[], launches=[], restores=[], query_override=None,
    streams=InputGateway(Stream(tty=False), Stream(tty=False), Stream(tty=False)))
  def query(path, **filters):
    state.queries.append((path, filters))
    if state.query_override is not None:
      return state.query_override(path, **filters)
    rows = [row for row in state.rows if all(value is None or row[key] == value for key, value in (
      ("profile", filters["profile"]), ("agent", filters["agent"]),
      ("batch_id", filters["batch_id"]), ("run_id", filters["run_id"])))]
    return {"schema_version": 1, "sessions": deepcopy(rows), "issues": deepcopy(state.issues), "incomplete": state.incomplete}
  def load(path, profile):
    state.loads.append((path, profile))
    return ws
  class Backend(HostResumeBackend):
    def resume_session(self, selected, *, location, before_dispatch, after_dispatch):
      assert location == "here"
      state.launches.append(selected)
      before_dispatch("f" * 32)
      after_dispatch("f" * 32)
      return LaunchReceipt("f" * 32, 17)
  monkeypatch.setattr(stopped_sessions, "for_scope", query)
  monkeypatch.setattr(workspace, "load_workspace", load)
  monkeypatch.setattr(flow, "lookup_session", lambda selected, identifier: state.target)
  monkeypatch.setattr(resume, "backend_for_workspace", lambda selected, target, **kwargs: Backend())
  def restore(selected, batch_id, *, run_id, launch):
    state.restores.append((selected, batch_id, run_id))
    code = launch(state.target, expected_deployment="d" * 64)
    return code, {"scope": {**ws.binding, "agent": ws.agent}, "batch_id": batch_id,
      "restores": {run_id: {"action": "restore-result", "exit_code": code}}}
  monkeypatch.setattr(flow, "restore", restore)
  monkeypatch.setattr(cli, "InputGateway", lambda: state.streams)
  monkeypatch.setattr(preferences, "load_preferences", lambda: SimpleNamespace(get=lambda key: None))
  state.prefix = ["--no-input", "resume", "--local", local, "--stopped"]
  return state


def test_json_list_is_readonly_without_tool_profile_session_or_tty(history_case, tmp_path):
  state = history_case
  before = set(tmp_path.rglob("*"))
  assert cli.main([*state.prefix, "--list", "--format", "json"]) == 0
  result = json.loads(state.streams.stdout.getvalue())
  assert result["sessions"] == state.rows and result["incomplete"] is False
  assert state.queries == [(state.ws.local_path, {"profile": None, "agent": None, "batch_id": None, "run_id": None})]
  assert state.loads == state.launches == [] and state.streams.stdin.reads == 0
  assert set(tmp_path.rglob("*")) == before


def test_incomplete_list_keeps_known_rows_and_returns_four(history_case):
  state = history_case
  state.incomplete = True
  state.issues = [{"profile": "dsh-default", "batch_id": "c" * 32, "reason": "history-unavailable"}]
  assert cli.main([*state.prefix, "--list"]) == 4
  result = json.loads(state.streams.stdout.getvalue())
  assert result["sessions"] == state.rows and result["issues"] == state.issues
  assert state.loads == state.launches == []


def test_empty_list_succeeds_but_empty_restore_does_not_guess(history_case):
  state = history_case
  state.rows = []
  assert cli.main([*state.prefix, "--list"]) == 0
  assert cli.main([*state.prefix, "--batch", BATCH, "--run", RUN]) == 4
  assert state.loads == state.launches == []


@pytest.mark.parametrize("suffix", [[], ["--batch", BATCH], ["--run", RUN]])
def test_nontty_missing_target_never_reads_or_queries(history_case, suffix):
  state = history_case
  assert cli.main([*state.prefix, *suffix]) == 2
  assert state.queries == state.loads == state.launches == [] and state.streams.stdin.reads == 0


@pytest.mark.parametrize("options", [
  ["--stopped", "--session", SESSION], ["--stopped", "--list", "--original"], ["--stopped", "--list", "--new-tab"],
  ["--list"], ["--batch", BATCH], ["--run", RUN], ["--stopped", "--batch", "bad", "--list"],
  ["--stopped", "--run", "A" * 32, "--list"],
  ["--stopped", "--batch", BATCH, "--batch", BATCH, "--list"],
  ["--stopped", "--run", RUN, "--run", RUN, "--list"],
])
def test_conflicts_and_bad_ids_fail_before_backend(history_case, options):
  state = history_case
  assert cli.main(["--no-input", "resume", "--local", str(state.ws.local_path), *options]) == 2
  assert state.queries == state.loads == state.launches == [] and state.streams.stdin.reads == 0


@pytest.mark.parametrize("interactive", [False, True])
def test_tty_selects_once_then_hands_off_without_continue_menu(history_case, interactive):
  state = history_case
  state.streams = InputGateway(Stream("1\n"), Stream(), Stream())
  prefix = ["--interactive"] if interactive else []
  assert cli.main([*prefix, "resume", "--local", str(state.ws.local_path), "--stopped"]) == 17
  assert state.streams.stdin.reads == 1 and state.launches == [state.target]
  text = state.streams.stderr.getvalue()
  assert all(part in text for part in ("修复示例", SESSION, state.target.cwd, "不需要 Herdr", "不发送继续"))
  assert "人工继续选项" not in text
  assert state.queries[-1][1] == {"profile": "dsh-default", "agent": "dsh", "batch_id": BATCH, "run_id": RUN}


def test_explicit_workflow_record_rechecks_exact_scope_and_preserves_native_exit(history_case):
  state = history_case
  assert cli.main([*state.prefix, "--batch", BATCH, "--run", RUN, "--here"]) == 17
  assert state.loads == [(state.ws.local_path, "dsh-default")]
  assert state.launches == [state.target] and state.streams.stdin.reads == 0


@pytest.mark.parametrize("field,value", [("cwd", "/synthetic/changed"), ("source", "stop"),
  ("session_ref", None), ("restorable", False), ("session_id", "different")])
def test_record_drift_before_restore_never_dispatches(history_case, field, value):
  state = history_case
  def query(*args, **kwargs):
    row = deepcopy(state.rows[0])
    if len(state.queries) == 2:
      row[field] = value
    return {"schema_version": 1, "sessions": [row], "issues": [], "incomplete": False}
  state.query_override = query
  assert cli.main([*state.prefix, "--batch", BATCH, "--run", RUN]) == 4
  assert state.launches == []


def test_workspace_binding_drift_never_dispatches(history_case):
  state = history_case
  state.ws.binding = {**state.ws.binding, "machine": "other"}
  assert cli.main([*state.prefix, "--batch", BATCH, "--run", RUN]) == 4
  assert len(state.queries) == 1 and state.launches == []


@pytest.mark.parametrize("advertised_ready", [False, True])
def test_stop_snapshot_only_offers_manual_command_and_never_quick_launches(history_case, advertised_ready):
  state = history_case
  row = state.rows[0]
  row.update(source="stop", restorable=advertised_ready, restore_status="manual-review")
  manual = ["rotom", "resume", "dsh", "--local", str(state.ws.local_path), "--profile", "dsh-default",
    "--session", SESSION, "--here"]
  row["next_commands"]["manual_restore"] = manual
  assert cli.main([*state.prefix, "--list", "--format", "human"]) == 0
  assert "人工核对后可自行执行：rotom resume dsh" in state.streams.stdout.getvalue()
  assert SESSION in state.streams.stdout.getvalue()
  assert "可尝试恢复" not in state.streams.stdout.getvalue()
  state.streams.stdout.seek(0)
  state.streams.stdout.truncate()
  assert cli.main([*state.prefix, "--list", "--format", "json"]) == 0
  assert json.loads(state.streams.stdout.getvalue())["sessions"][0]["next_commands"]["manual_restore"] == manual
  assert cli.main([*state.prefix, "--batch", BATCH, "--run", RUN]) == 4
  assert state.loads == state.launches == state.restores == []


def test_workflow_disappearing_before_recheck_never_uses_snapshot_fallback(history_case):
  state = history_case
  def query(*args, **kwargs):
    row = deepcopy(state.rows[0])
    if len(state.queries) == 2:
      row.update(source="stop", restorable=False, restore_status="manual-review")
    return {"schema_version": 1, "sessions": [row], "issues": [], "incomplete": False}
  state.query_override = query
  assert cli.main([*state.prefix, "--batch", BATCH, "--run", RUN]) == 4
  assert state.restores == state.launches == []


def test_human_list_escapes_untrusted_display_text(history_case):
  state = history_case
  state.rows[0]["title"] = "title\n\x1b[31m"
  assert cli.main([*state.prefix, "--list", "--format", "human"]) == 0
  text = state.streams.stdout.getvalue()
  assert "title\\n?[31m" in text and "\x1b" not in text
  assert "可尝试恢复（启动前复核）" in text


def test_human_list_replaces_bidi_without_truncating_cwd_or_id(history_case):
  state = history_case
  state.rows[0]["cwd"] = "/synthetic/" + "x" * 400 + "\u202ebeta\u200b/file\nnext\u2028line\u2029end"
  state.rows[0]["profile"] = "dsh\u202d-default"
  assert cli.main([*state.prefix, "--list", "--format", "human"]) == 0
  text = state.streams.stdout.getvalue()
  assert not any(char in text for char in ("\u202e", "\u202d", "\u200b", "\u2028", "\u2029"))
  assert "/synthetic/" + "x" * 400 + "?beta?/file\\nnext?line?end" in text
  assert "dsh?-default" in text and SESSION in text and RUN in text


def stopped_resume(state, *args):
  return cli.main(["--no-input", "resume", state.ws.agent, "--local", str(state.ws.local_path),
    "--profile", state.ws.profile, "--stopped", *args])


def test_three_tool_saved_workflow_list_restore_and_no_replay(command, capsys):
  state = command
  result = update_workflow(state, capsys)
  def saved():
    return {str(path.relative_to(state.ws.state_root)): path.read_bytes()
      for path in state.ws.state_root.rglob("*") if path.is_file()}
  before = saved()
  assert stopped_resume(state, "--list", "--format", "json") == 0
  rows = json.loads(state.streams.stdout.getvalue())["sessions"]
  assert saved() == before
  assert len(rows) == 2 and all(row["source"] == "workflow" and row["restorable"] for row in rows)
  assert stopped_resume(state, "--batch", state.batch, "--run", RUNS[0]) == 17
  assert len(state.backend_calls) == 1 and state.deployment_bindings == [result["setup"]["deployment"]]
  assert stopped_resume(state, "--batch", state.batch, "--run", RUNS[0]) == 4
  assert len(state.backend_calls) == 1


def test_missing_whole_workflow_directory_never_replays_snapshot(command, capsys, monkeypatch):
  from agentcfg import dsh_stop_client, pi_session_observation, run_stop_fence, sessions
  state = command
  update_workflow(state, capsys)
  store = flow.Store(state.ws, state.batch)
  store.append(store.read(), "restore-intent", run_id=RUNS[0])
  store.registry.root.rename(state.ws.state_root / "archived-workflows")
  (state.ws.state_root / ("run-owners.stop-snapshot-" + state.batch + ".json")).write_text("{}")
  target = replace(state.sessions[SESSION], run_id=RUNS[0])
  monkeypatch.setattr(run_stop_fence, "read_snapshot", lambda *args: {"schema_version": 2, "records": {}})
  monkeypatch.setattr(sessions, "from_run_records", lambda *a, **kw: (target,))
  monkeypatch.setattr(pi_session_observation, "from_records", lambda *args: ())
  monkeypatch.setattr(dsh_stop_client, "status_stop", lambda *a, **kw: {
    "scope": {**state.ws.binding, "agent": state.ws.agent}, "status": "stopped", "protected": False,
    "targets": [{"run_id": RUNS[0], "lifecycle_state": "idle_confirmed"}]})
  assert stopped_resume(state, "--list", "--format", "json") == 0
  row = json.loads(state.streams.stdout.getvalue())["sessions"][0]
  assert row["source"] == "stop" and row["restore_status"] == "manual-review" and not row["restorable"]
  assert row["next_commands"]["manual_restore"][-3:] == ["--session", SESSION, "--here"]
  assert stopped_resume(state, "--batch", state.batch, "--run", RUNS[0]) == 4
  assert state.backend_calls == []


@pytest.mark.parametrize("blocked", ["pending-update", "cancelled", "existing-intent"])
@pytest.mark.parametrize("stale_candidate", [False, True])
def test_three_tool_workflow_gates_remain_in_force(command, capsys, monkeypatch, blocked, stale_candidate):
  state = command
  if blocked == "pending-update":
    stop_workflow(state, capsys)
  else:
    update_workflow(state, capsys)
    store = flow.Store(state.ws, state.batch)
    if blocked == "cancelled":
      flow.cancel(state.ws, state.batch)
    else:
      store.append(store.read(), "restore-intent", run_id=RUNS[0])
  if stale_candidate:
    original = stopped_sessions.for_scope
    def stale(*args, **kwargs):
      result = original(*args, **kwargs)
      for row in result["sessions"]:
        row["restorable"] = True
      return result
    monkeypatch.setattr(stopped_sessions, "for_scope", stale)
  assert stopped_resume(state, "--batch", state.batch, "--run", RUNS[0]) == 4
  assert state.backend_calls == []


@pytest.mark.parametrize("label", ["bad=Title", RUN + "=", RUN + "= bad", RUN + "=line\nbreak", RUN + "=" + "x" * 161])
def test_invalid_label_fails_before_scope_or_input(history_case, label):
  state = history_case
  assert cli.main(["--no-input", "agent", "maintenance", "plan", "--run", RUN, "--label", label]) == 2
  assert state.loads == [] and state.streams.stdin.reads == 0


@pytest.mark.parametrize("suffix", [
  ["--run", RUN, "--label", RUN + "=A", "--label", RUN + "=B"],
  ["--run", RUN, "--label", "c" * 32 + "=Other"],
  ["--batch", BATCH, "--label", RUN + "=Title"],
])
def test_label_duplicate_foreign_run_or_batch_plan_fails_before_business(history_case, suffix):
  state = history_case
  assert cli.main(["--no-input", "agent", "maintenance", "plan", *suffix]) == 2
  assert state.loads == [] and state.streams.stdin.reads == 0


def test_three_tool_labels_saved_and_shown_in_history(command, capsys):
  state = command
  args = [*state.prefix, "plan", *state.target_args, "--label", RUNS[0] + "=用户备注", "--format", "json"]
  assert cli.main(args) == 0
  plan = json.loads(capsys.readouterr().out)
  assert plan["display"][RUNS[0]] == {"title": "用户备注", "source": "user"}
  args = [*state.prefix, "stop", *state.target_args, "--label", RUNS[0] + "=用户备注",
    "--plan-id", plan["plan_id"], "--format", "json"]
  assert cli.main(args) == 0
  result = json.loads(capsys.readouterr().out)
  assert stopped_resume(state, "--list", "--format", "json") == 0
  rows = json.loads(state.streams.stdout.getvalue())["sessions"]
  selected = next(row for row in rows if row["run_id"] == RUNS[0])
  assert selected["title"] == "用户备注" and selected["title_source"] == "user"
  assert selected["batch_id"] == result["batch_id"] and selected["restorable"] is False


def test_help_and_completion_include_stopped_and_labels_without_backend(history_case, capsys, monkeypatch):
  monkeypatch.setattr(stopped_sessions, "for_scope", lambda *a, **kw: pytest.fail("help queried stopped history"))
  assert cli.main(["resume", "--help"]) == 0
  help_text = capsys.readouterr().out
  assert all(option in help_text for option in ("--stopped", "--list", "--batch", "--run", "--format", "不需要 Herdr"))
  assert cli.main(["agent", "maintenance", "plan", "--help"]) == 0
  assert "--label" in capsys.readouterr().out
  source = (Path(__file__).resolve().parents[1] / "terminals/zsh/_rotom").read_text()
  assert "--stopped --list --batch --run --format" in source
  assert "--session --label --format" in source


@pytest.mark.parametrize("location", ["original", "new-tab"])
def test_saved_workflow_location_rechecks_then_dispatches(history_case, monkeypatch, location):
  import sys
  state = history_case
  calls = []
  def dispatch_location(ws, batch_id, run_id, context, *, location, deadline=None):
    calls.append((ws, batch_id, run_id, location))
    return 19
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(dispatch_location=dispatch_location))
  assert cli.main([*state.prefix, "--batch", BATCH, "--run", RUN, "--" + location]) == 19
  assert calls == [(state.ws, BATCH, RUN, location)]
  assert len(state.queries) == 2 and state.launches == state.restores == []


@pytest.mark.parametrize("location", ["here", "original", "new-tab"])
def test_list_location_is_parameter_error_before_history(history_case, location):
  state = history_case
  assert cli.main([*state.prefix, "--list", "--" + location]) == 2
  assert state.queries == state.loads == state.launches == []


@pytest.fixture
def batch_history(history_case):
  state = history_case
  second = deepcopy(state.rows[0])
  second.update(run_id="c" * 32, session_id="second-session")
  second["session_ref"]["native_ref"] = "second-session"
  state.rows.append(second)
  return state


@pytest.mark.parametrize("location", ["new-tab", "original"])
def test_batch_all_aggregates_each_location_without_stdin(batch_history, monkeypatch, location):
  import sys
  state = batch_history
  calls = []
  def dispatch_location(ws, batch_id, run_id, context, *, location, deadline=None):
    assert len(state.loads) >= 2
    calls.append((run_id, location))
    print(json.dumps({"run_id": run_id, "handoff": True, "request_id": run_id}), file=context.input_gateway.stdout)
    return 0
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(dispatch_location=dispatch_location))
  assert cli.main([*state.prefix, "--batch", BATCH, "--all", "--" + location]) == 0
  result = json.loads(state.streams.stdout.getvalue())
  assert result["batch_id"] == BATCH and result["location"] == location
  assert [item["run_id"] for item in result["results"]] == [RUN, "c" * 32]
  assert all(item["exit_code"] == 0 and item["result"]["handoff"] for item in result["results"])
  assert result["load_confirmation"] == "unknown" and result["continue_status"] == "not_sent"
  assert calls == [(RUN, location), ("c" * 32, location)] and state.streams.stdin.reads == 0


@pytest.mark.parametrize("damage", ["unrestorable", "unknown-source", "scope", "incomplete", "duplicate"])
def test_batch_all_rejects_entire_invalid_batch_before_dispatch(batch_history, monkeypatch, damage):
  import sys
  state = batch_history
  if damage == "unrestorable": state.rows[1]["restorable"] = False
  elif damage == "unknown-source": state.rows[1]["source"] = "stop"
  elif damage == "scope": state.rows[1]["scope"]["profile"] = "other"
  elif damage == "incomplete": state.incomplete = True
  else: state.rows.append(deepcopy(state.rows[0]))
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(
    dispatch_location=lambda *args, **kwargs: pytest.fail("invalid batch dispatched")))
  assert cli.main([*state.prefix, "--batch", BATCH, "--all", "--new-tab"]) == 4
  result = json.loads(state.streams.stdout.getvalue())
  assert all(item["result"]["status"] == "not_dispatched" for item in result["results"])
  assert state.streams.stdin.reads == 0


@pytest.mark.parametrize("options", [["--all"], ["--stopped", "--all", "--new-tab"],
  ["--stopped", "--batch", BATCH, "--all"], ["--stopped", "--batch", BATCH, "--all", "--here"],
  ["--stopped", "--batch", BATCH, "--all", "--new-tab", "--run", RUN],
  ["--stopped", "--batch", BATCH, "--all", "--new-tab", "--list"],
  ["--stopped", "--batch", BATCH, "--all", "--original", "--session", SESSION]])
def test_batch_all_invalid_combinations_fail_before_history(history_case, options):
  state = history_case
  assert cli.main(["--no-input", "resume", "--local", str(state.ws.local_path), *options]) == 2
  assert state.queries == state.loads == state.launches == []


@pytest.mark.parametrize("failure_index", [0, 1])
@pytest.mark.parametrize("failure", ["nonzero", "no-json", "exception", "config", "credential"])
def test_batch_all_stops_on_first_unconfirmed_item_and_retains_prior_facts(batch_history, monkeypatch, failure_index, failure):
  import sys
  from agentcfg.storage import Conflict
  state = batch_history
  third = deepcopy(state.rows[1])
  third.update(run_id="d" * 32, session_id="third-session")
  third["session_ref"]["native_ref"] = "third-session"
  state.rows.append(third)
  calls = []
  def dispatch_location(ws, batch_id, run_id, context, *, location, deadline=None):
    calls.append(run_id)
    if len(calls) - 1 == failure_index:
      if failure == "exception": raise Conflict("synthetic private detail")
      if failure == "config":
        from agentcfg.schema import ConfigError
        raise ConfigError("synthetic-configuration-change")
      if failure == "credential":
        from agentcfg.secrets import CredentialError
        raise CredentialError()
      if failure == "no-json": return 0
      return 5
    print(json.dumps({"run_id": run_id, "handoff": True}), file=context.input_gateway.stdout)
    return 0
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(dispatch_location=dispatch_location))
  assert cli.main([*state.prefix, "--batch", BATCH, "--all", "--new-tab"]) == 4
  result = json.loads(state.streams.stdout.getvalue())
  assert calls == [RUN, "c" * 32][:failure_index + 1]
  assert result["results"][failure_index]["result"]["status"] == "unknown"
  assert all(item["result"]["status"] == "not_dispatched" for item in result["results"][failure_index + 1:])
  if failure_index:
    assert result["results"][0]["exit_code"] == 0 and result["results"][0]["result"]["handoff"]
  assert "private detail" not in state.streams.stderr.getvalue()
  assert state.streams.stdin.reads == 0


def test_batch_all_rechecks_every_target_before_first_dispatch(batch_history, monkeypatch):
  import sys
  state = batch_history
  def query(path, **filters):
    rows = [deepcopy(row) for row in state.rows if filters["run_id"] in (None, row["run_id"])]
    if filters["run_id"] == "c" * 32:
      rows[0]["cwd"] = "/synthetic/drift"
    return {"schema_version": 1, "sessions": rows, "issues": [], "incomplete": False}
  state.query_override = query
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(
    dispatch_location=lambda *args, **kwargs: pytest.fail("drifted batch dispatched")))
  assert cli.main([*state.prefix, "--batch", BATCH, "--all", "--new-tab"]) == 4
  assert all(item["result"]["status"] == "not_dispatched"
    for item in json.loads(state.streams.stdout.getvalue())["results"])


def test_batch_all_human_output_is_per_item_without_json_fragments(batch_history, monkeypatch):
  import sys
  state = batch_history
  def dispatch_location(ws, batch_id, run_id, context, *, location, deadline=None):
    print(json.dumps({"handoff": True}), file=context.input_gateway.stdout)
    return 0
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(dispatch_location=dispatch_location))
  assert cli.main([*state.prefix, "--batch", BATCH, "--all", "--original", "--format", "human"]) == 0
  text = state.streams.stdout.getvalue()
  assert text.count("已交接") == 2 and RUN in text and "c" * 32 in text
  assert "加载待确认，不发送继续" in text and '"handoff"' not in text


def test_batch_all_repeated_command_never_replays_previous_intents(batch_history, monkeypatch):
  import sys
  state = batch_history
  calls = []
  def dispatch_location(ws, batch_id, run_id, context, *, location, deadline=None):
    calls.append(run_id)
    next(row for row in state.rows if row["run_id"] == run_id).update(restorable=False, restore_status="unknown")
    print(json.dumps({"handoff": True}), file=context.input_gateway.stdout)
    return 0
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(dispatch_location=dispatch_location))
  argv = [*state.prefix, "--batch", BATCH, "--all", "--new-tab"]
  assert cli.main(argv) == 0
  state.streams.stdout.seek(0)
  state.streams.stdout.truncate()
  assert cli.main(argv) == 4
  assert calls == [RUN, "c" * 32]
  assert all(item["result"]["status"] == "not_dispatched"
    for item in json.loads(state.streams.stdout.getvalue())["results"])


def test_batch_all_help_is_static_and_explains_exact_limits(history_case, capsys, monkeypatch):
  monkeypatch.setattr(stopped_sessions, "for_scope", lambda *args, **kwargs: pytest.fail("help read history"))
  assert cli.main(["resume", "--help"]) == 0
  text = capsys.readouterr().out
  for expected in ("--all", "--stopped --batch", "不接受 --run/--session/--list/--here", "not_dispatched",
      "逐项独立交接", "逐工具/Linux/Herdr/驻留准入", "--all --new-tab"):
    assert expected in text
  definition = cli._registry(cli.build_parser())[("resume",)]
  assert any(parameter.name == "all" for parameter in definition.parameters)


@pytest.mark.parametrize("expire_stage", ["preflight", "first", "second-recheck"])
def test_batch_ready_budget_is_shared_and_expired_items_not_dispatched(batch_history, monkeypatch, expire_stage):
  import sys
  from rotom import stopped
  from rotom.restore_deadline import ReadyDeadline
  state = batch_history
  now = [10.0]
  deadline = ReadyDeadline(2, clock=lambda: now[0])
  validate = stopped._validated_row
  checks = []
  def checked(*args):
    checks.append(args[1]["run_id"])
    result = validate(*args)
    if expire_stage == "preflight" or expire_stage == "second-recheck" and len(checks) == 4:
      now[0] = 12
    return result
  monkeypatch.setattr(stopped, "_validated_row", checked)
  calls = []
  def dispatch_location(ws, batch_id, run_id, context, *, location, deadline):
    assert deadline is shared
    calls.append(run_id)
    now[0] = 12 if expire_stage == "first" else 11
    print(json.dumps({"handoff": True}), file=context.input_gateway.stdout)
    return 0
  shared = deadline
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(dispatch_location=dispatch_location))
  # 复用真实 CLI 产生的 context，再向批次入口注入可控时钟。
  original = stopped._restore_all
  def restore(context, batch_id, observed, location, **kwargs):
    return original(context, batch_id, observed, location, deadline=shared)
  monkeypatch.setattr(stopped, "_restore_all", restore)
  assert cli.main([*state.prefix, "--batch", BATCH, "--all", "--new-tab"]) == 4
  result = json.loads(state.streams.stdout.getvalue())
  assert calls == ([] if expire_stage == "preflight" else [RUN])
  assert result["results"][-1]["result"] == {"status": "not_dispatched", "reason": "restore_ready_timeout"} or (
    expire_stage == "preflight" and result["results"][-1]["result"]["reason"] == "restore_ready_timeout")
  if calls:
    assert result["results"][0]["result"]["handoff"] is True


def test_single_selected_restore_budget_excludes_interactive_selection(history_case, monkeypatch):
  import sys
  from rotom import stopped
  from rotom.restore_deadline import ReadyDeadline
  state = history_case
  now = [10.0]
  created = []
  def deadline(seconds):
    created.append(now[0])
    return ReadyDeadline(seconds, clock=lambda: now[0])
  monkeypatch.setattr(stopped, "ReadyDeadline", deadline)
  from rotom.context import InputGateway
  def choose(self, *args, **kwargs):
    now[0] += 500
    return "0"
  monkeypatch.setattr(InputGateway, "choose", choose)
  def dispatch_location(ws, batch_id, run_id, context, *, location, deadline):
    assert deadline.remaining() == 120
    assert deadline.expires_at == 630
    return 0
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(dispatch_location=dispatch_location))
  state.streams = InputGateway(Stream(), Stream(), Stream())
  assert cli.main(["--interactive", *state.prefix[1:], "--new-tab", "--wait-seconds", "120"]) == 0
  assert created == [510]


def test_batch_timeout_after_dispatch_retains_unknown_and_skips_later(batch_history, monkeypatch):
  import sys
  from termcfg.errors import TermcfgError
  state = batch_history
  calls = []
  def dispatch_location(ws, batch_id, run_id, context, **kwargs):
    calls.append(run_id)
    raise TermcfgError(4, "restore_ready_timeout")
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(dispatch_location=dispatch_location))
  assert cli.main([*state.prefix, "--batch", BATCH, "--all", "--new-tab"]) == 4
  results = json.loads(state.streams.stdout.getvalue())["results"]
  assert calls == [RUN]
  assert results[0]["result"] == {"status": "unknown", "reason": "restore_ready_timeout"}
  assert results[1]["result"] == {"status": "not_dispatched", "reason": "restore_ready_timeout"}


def test_batch_items_consume_one_cumulative_ready_budget(batch_history, monkeypatch):
  import sys
  from rotom import stopped
  from rotom.restore_deadline import ReadyDeadline
  state = batch_history
  third = deepcopy(state.rows[1])
  third.update(run_id="d" * 32, session_id="third-session")
  third["session_ref"]["native_ref"] = "third-session"
  state.rows.append(third)
  now = [10.0]
  shared = ReadyDeadline(2, clock=lambda: now[0])
  original = stopped._restore_all
  monkeypatch.setattr(stopped, "_restore_all", lambda context, batch_id, observed, location, **kwargs:
    original(context, batch_id, observed, location, deadline=shared))
  calls = []
  def dispatch_location(ws, batch_id, run_id, context, *, location, deadline):
    assert deadline is shared
    calls.append((run_id, deadline.remaining()))
    now[0] += 1
    print(json.dumps({"handoff": True}), file=context.input_gateway.stdout)
    return 0
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(dispatch_location=dispatch_location))
  assert cli.main([*state.prefix, "--batch", BATCH, "--all", "--original"]) == 4
  results = json.loads(state.streams.stdout.getvalue())["results"]
  assert calls == [(RUN, 2), ("c" * 32, 1)]
  assert all(item["result"]["handoff"] for item in results[:2])
  assert results[2]["result"] == {"status": "not_dispatched", "reason": "restore_ready_timeout"}


@pytest.mark.parametrize("selection", [["--run", RUN], ["--all"]])
def test_explicit_target_initial_query_consumes_ready_budget(history_case, monkeypatch, selection):
  import sys
  from rotom import stopped
  from rotom.restore_deadline import ReadyDeadline
  state = history_case
  now = [10.0]
  monkeypatch.setattr(stopped, "ReadyDeadline", lambda seconds: ReadyDeadline(seconds, clock=lambda: now[0]))
  original = stopped._query
  def query(*args, **kwargs):
    result = original(*args, **kwargs)
    now[0] += 1
    return result
  monkeypatch.setattr(stopped, "_query", query)
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(
    dispatch_location=lambda *args, **kwargs: pytest.fail("expired query must not dispatch")))
  assert cli.main([*state.prefix, "--batch", BATCH, *selection, "--original", "--wait-seconds", "1"]) == 4
  results = json.loads(state.streams.stdout.getvalue())["results"]
  assert len(results) == len(state.rows)
  assert all(item["result"]["status"] == "not_dispatched" and
    item["result"]["reason"] == "restore_ready_timeout" for item in results)

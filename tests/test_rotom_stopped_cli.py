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
  ["--stopped", "--session", SESSION], ["--stopped", "--original"], ["--stopped", "--new-tab"],
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

"""停止历史：真实临时 workflow 日志，合成停止/宿主，默认不访问真实会话。"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from agentcfg import stopped_sessions as history, tool_maintenance as flow
from agentcfg.storage import Conflict
from test_rotom_tool_maintenance import (
  BATCH, RUNS, SESSION, SECOND, begin, payloads, rehash, update, workflow,
)


def rows(state, **filters):
  return history.history([state.ws], **filters)


def test_empty_history_does_not_create_state(workflow):
  state = workflow
  state.ws.state_root = state.ws.state_root / "missing-state"
  assert rows(state) == {"schema_version": 1, "sessions": [], "issues": [], "incomplete": False}
  assert not state.ws.state_root.exists()


def test_history_tracks_setup_and_preserves_exact_titles_without_native_reads(workflow, monkeypatch):
  state = workflow
  title = "配置更新前的合成任务"
  state.plan = flow.plan(state.ws, selected_runs=RUNS[:2], sessions=state.mapping, labels={RUNS[0]: title})
  begin(state)
  before = payloads(state.ws.state_root)
  monkeypatch.setattr(flow, "lookup_session", lambda *args: pytest.fail("历史查询不得读原生会话"))
  pending = rows(state)
  assert not pending["incomplete"]
  assert {row["restore_status"] for row in pending["sessions"]} == {"update-required"}
  first = next(row for row in pending["sessions"] if row["run_id"] == RUNS[0])
  assert first["session_id"] == SESSION and first["title"] == title and first["title_source"] == "user"
  assert first["cwd"] == state.sessions[SESSION].cwd
  assert first["next_commands"]["restore"] is None and not first["restorable"]
  assert payloads(state.ws.state_root) == before


def test_updated_history_offers_scope_complete_single_item_command(workflow):
  state = workflow
  update(state)
  before = payloads(state.ws.state_root)
  result = rows(state, batch_id=BATCH, run_id=RUNS[0])
  assert not result["incomplete"] and len(result["sessions"]) == 1
  row = result["sessions"][0]
  assert row["restorable"] and row["restore_status"] == "available"
  assert row["next_commands"]["restore"] == ["rotom", "resume", state.ws.agent,
    "--local", str(state.ws.local_path), "--profile", state.ws.profile,
    "--stopped", "--batch", BATCH, "--run", RUNS[0], "--here"]
  assert row["observed_at_ns"] == 100
  assert payloads(state.ws.state_root) == before


@pytest.mark.parametrize("stage", ["pending", "cancelled", "setup-intent", "restore-intent", "restore-result", "deployment-changed"])
def test_history_does_not_offer_unknown_cancelled_dispatched_or_drifted_workflow(workflow, stage):
  state = workflow
  if stage == "setup-intent":
    value = begin(state)
    flow.Store(state.ws, BATCH).append(value, "setup-intent", plan_id="a" * 64, deployment="b" * 64)
  else:
    update(state)
    store = flow.Store(state.ws, BATCH)
    if stage == "pending":
      state.stop_result["status"] = "pending"
    elif stage == "cancelled":
      store.append(store.read(), "cancel")
    elif stage.startswith("restore-"):
      intent = store.append(store.read(), "restore-intent", run_id=RUNS[0])
      if stage == "restore-result":
        store.complete_restore(intent, run_id=RUNS[0], exit_code=0)
    else:
      (state.ws.state_root / "pending.json").write_text("{}")
  result = rows(state, run_id=RUNS[0])
  assert not result["incomplete"]
  row = result["sessions"][0]
  assert not row["restorable"] and row["next_commands"]["restore"] is None
  assert row["restore_status"] == {"pending": "stop-unconfirmed", "cancelled": "cancelled",
    "setup-intent": "unknown", "restore-intent": "unknown", "restore-result": "dispatched",
    "deployment-changed": "deployment-changed"}[stage]


@pytest.mark.parametrize("damage", ["manifest", "symlink", "unknown-field"])
def test_damaged_workflow_never_falls_back_to_stop_snapshot(workflow, monkeypatch, damage):
  state = workflow
  begin(state)
  directory = flow.Store(state.ws, BATCH).registry.root
  if damage == "manifest":
    (directory / "manifest.json").write_text("{}")
  elif damage == "symlink":
    moved = directory.with_name("f" * 32)
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
  else:
    import json
    path = directory / "manifest.json"
    value = json.loads(path.read_text())
    value["unknown"] = True
    path.write_text(json.dumps(value))
  (state.ws.state_root / ("run-owners.stop-snapshot-" + BATCH + ".json")).write_text("{}")
  monkeypatch.setattr(history, "_stop_rows", lambda *args: pytest.fail("损坏 workflow 不得退回普通恢复"))
  result = rows(state, batch_id=BATCH)
  assert result["incomplete"] and result["sessions"] == []
  assert any(issue["reason"] == "batch-unavailable" for issue in result["issues"])


def test_v1_manifest_remains_readable_without_titles(workflow):
  state = workflow
  state.plan["schema_version"] = 1
  state.plan.pop("display")
  rehash(state.plan)
  update(state)
  result = rows(state)
  assert not result["incomplete"] and len(result["sessions"]) == 2
  assert all(row["title"] is None and row["title_source"] == "unavailable" for row in result["sessions"])


@pytest.mark.parametrize("bad", ["", " spaced ", "line\nnext", "tab\tx", "escape\x1b[31m", "bidi\u202e", "line\u2028next", "a" * 161, 7])
def test_invalid_explicit_labels_are_rejected_before_stop(workflow, bad):
  state = workflow
  with pytest.raises(ValueError):
    flow.plan(state.ws, selected_runs=RUNS[:2], sessions=state.mapping, labels={RUNS[0]: bad})
  assert not (state.ws.state_root / "maintenance-workflows").exists()


def test_labels_do_not_change_session_identity_but_are_part_of_approval(workflow):
  state = workflow
  labelled = flow.plan(state.ws, selected_runs=RUNS[:2], sessions=state.mapping, labels={RUNS[0]: "合成摘要"})
  assert labelled["targets"] == state.plan["targets"]
  assert labelled["plan_id"] != state.plan["plan_id"]
  bad = deepcopy(labelled)
  bad["display"][RUNS[0]]["source"] = "unknown"
  with pytest.raises(Conflict):
    flow.Store(state.ws, BATCH).begin(rehash(bad))


def test_omp_title_projection_saved_before_stop_only_when_identity_matches(workflow, monkeypatch):
  state = workflow
  if state.ws.agent != "omp":
    return
  from types import SimpleNamespace
  from agentcfg import tool_session_headers
  monkeypatch.setattr(tool_session_headers, "lookup", lambda ws, identifier:
    SimpleNamespace(known=state.sessions[identifier], title="合成原生标题"))
  planned = flow.plan(state.ws, selected_runs=RUNS[:2], sessions=state.mapping)
  assert planned["display"][RUNS[0]] == {"title": "合成原生标题", "source": "native-omp"}
  monkeypatch.setattr(tool_session_headers, "lookup", lambda ws, identifier:
    SimpleNamespace(known=replace(state.sessions[identifier], cwd="/different"), title="错误标题"))
  planned = flow.plan(state.ws, selected_runs=RUNS[:2], sessions=state.mapping)
  assert planned["display"][RUNS[0]] == {"title": None, "source": "unavailable"}


@pytest.mark.parametrize("state_name", ["stopped", "pending", "protected", "unknown-run", "missing-session", "missing-cwd", "missing-workflow"])
def test_standalone_snapshot_projection_requires_observed_session_and_confirmed_stop(workflow, monkeypatch, state_name):
  state = workflow
  from agentcfg import dsh_stop_client, run_stop_fence, sessions, pi_session_observation
  snapshot = {"schema_version": 2, "records": {}}
  monkeypatch.setattr(run_stop_fence, "read_snapshot", lambda *args: snapshot)
  value = {"scope": {**state.ws.binding, "agent": state.ws.agent}, "status": "stopped", "protected": False,
    "targets": [{"run_id": RUNS[0], "lifecycle_state": "idle_confirmed"}]}
  target = replace(state.sessions[SESSION], run_id=RUNS[0])
  if state_name == "pending": value["status"] = "pending"
  if state_name == "protected": value["protected"] = True
  if state_name == "unknown-run": value["targets"][0]["lifecycle_state"] = "unknown"
  if state_name == "missing-cwd": target = replace(target, cwd=None, cwd_status="unknown")
  known = () if state_name == "missing-session" else (target,)
  monkeypatch.setattr(sessions, "from_run_records", lambda *args, **kwargs: known)
  monkeypatch.setattr(pi_session_observation, "from_records", lambda *args: ())
  monkeypatch.setattr(dsh_stop_client, "status_stop", lambda *args, **kwargs: value)
  if state_name == "missing-workflow":
    import shutil
    update(state)
    store = flow.Store(state.ws, BATCH)
    store.append(store.read(), "restore-intent", run_id=RUNS[0])
    shutil.rmtree(store.registry.root)
    (state.ws.state_root / ("run-owners.stop-snapshot-" + BATCH + ".json")).write_text("{}")
    row = rows(state, batch_id=BATCH)["sessions"][0]
  else:
    row = history._stop_rows(state.ws, BATCH)[0]
  assert row["source"] == "stop" and not row["restorable"]
  assert row["next_commands"]["restore"] is None
  if state_name in ("stopped", "missing-workflow"):
    assert row["restore_status"] == "manual-review"
    assert row["next_commands"]["manual_restore"] == ["rotom", "resume", state.ws.agent,
      "--local", str(state.ws.local_path), "--profile", state.ws.profile, "--session", SESSION, "--here"]
  else:
    assert row["next_commands"]["manual_restore"] is None
  if state_name == "missing-session":
    assert row["session_id"] is None and row["cwd"] is None


def test_history_incomplete_preserves_valid_rows_and_exact_filters(workflow, monkeypatch):
  state = workflow
  update(state)
  bad = state.ws.state_root / "maintenance-workflows" / ("f" * 32)
  bad.mkdir(mode=0o700)
  result = rows(state)
  assert result["incomplete"] and len(result["sessions"]) == 2
  assert rows(state, batch_id=BATCH)["incomplete"] is False
  assert rows(state, batch_id=BATCH, run_id=RUNS[2])["sessions"] == []
  with pytest.raises(ValueError): rows(state, batch_id="prefix")
  with pytest.raises(ValueError): rows(state, run_id="../escape")


def test_display_title_never_emits_terminal_or_direction_controls():
  assert history.display_title(" \x1b[31m\u202etitle\n ") == "?[31m?title?"
  assert history.display_title(None) is None
  assert history.display_title(" ") is None
  assert len(history.display_title("a" * 1000)) == 160

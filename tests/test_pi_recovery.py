"""Pi 多文件投影的故障恢复与合法引用轮换，不触碰认证、任务库或运行包。"""

from copy import deepcopy
import json

import pytest

from agentcfg import deployment as dep
from agentcfg.adapter import Artifact, ManagedTarget, Ownership
from agentcfg.render import RenderCandidate
from agentcfg.storage import Conflict, Tree

BINDING = {"machine": "fixture", "profile": "pi-fixture"}


def candidate(version):
  token = "$KEY_" + version
  artifacts = [Artifact(ManagedTarget("pi-home/models.json", Ownership.FIELDS, "json", "/providers/fake/apiKey", (token,)), json.dumps(token).encode()),
    Artifact(ManagedTarget("pi-home/settings.json", Ownership.FIELDS, "json", "/quietStartup"), b"true" if version == "B" else b"false"),
    Artifact(ManagedTarget("pi-home/APPEND_SYSTEM.md", Ownership.FILE, "text"), version.encode()),
    Artifact(ManagedTarget("pi-home/keybindings.json", Ownership.INITIALIZE, "json"), b"{}")]
  return RenderCandidate(version, tuple(artifacts))


def install(tmp_path, version):
  return dep.apply(tmp_path / "instance", tmp_path / "state", candidate(version), BINDING,
    {"lock_identity": "lock-" + version, "runtime_identity": "historical-slice-" + version})


@pytest.mark.parametrize("point", ["pending.json", "pi-home/models.json", "pi-home/settings.json", "pi-home/APPEND_SYSTEM.md", "deployment.json"])
def test_failure_at_each_write_restores_original_config_and_previous_backup(tmp_path, monkeypatch, point):
  install(tmp_path, "A"); install(tmp_path, "B")
  state = (tmp_path / "state/deployment.json").read_bytes()
  native = {name: (tmp_path / "instance" / name).read_bytes() for name in ("pi-home/models.json", "pi-home/settings.json", "pi-home/APPEND_SYSTEM.md")}
  original_replace, original_write = Tree.replace, Tree.write_state
  failed = False
  def fail(name):
    nonlocal failed
    if not failed and name == point:
      failed = True
      raise OSError("fixture interruption")
  def replace(tree, name, *args, **kwargs):
    fail(name); return original_replace(tree, name, *args, **kwargs)
  def write(tree, name, *args, **kwargs):
    fail(name); return original_write(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", replace); monkeypatch.setattr(Tree, "write_state", write)
  with pytest.raises(OSError):
    install(tmp_path, "C")
  assert failed
  assert (tmp_path / "state/deployment.json").read_bytes() == state
  assert not (tmp_path / "state/pending.json").exists()
  for name, value in native.items():
    assert (tmp_path / "instance" / name).read_bytes() == value


def test_rollback_keeps_runtime_auth_database_initialize_and_unknown_fields(tmp_path):
  install(tmp_path, "A")
  home = tmp_path / "instance/pi-home"
  for name, content in (("auth.json", "synthetic-auth"), ("runtime.db", "synthetic-db"), ("keybindings.json", '{"user":"key"}')):
    (home / name).write_text(content)
  settings = home / "settings.json"
  settings.write_text(json.dumps({"quietStartup": False, "unknown": [], "runtime": {"flag": False}}))
  install(tmp_path, "B")
  dep.rollback(tmp_path / "instance", tmp_path / "state", BINDING)
  assert json.loads((home / "models.json").read_text())["providers"]["fake"]["apiKey"] == "$KEY_A"
  assert json.loads(settings.read_text()) == {"quietStartup": False, "unknown": [], "runtime": {"flag": False}}
  assert (home / "auth.json").read_text() == "synthetic-auth"
  assert (home / "runtime.db").read_text() == "synthetic-db"
  assert (home / "keybindings.json").read_text() == '{"user":"key"}'
  state = json.loads((tmp_path / "state/deployment.json").read_text())
  assert state["current"]["launch"]["runtime_identity"] == "historical-slice-A"
  assert state["previous"] is None
  assert b"synthetic-auth" not in (tmp_path / "state/deployment.json").read_bytes()


@pytest.mark.parametrize("location", ["current", "previous", "change", "removed-guard"])
def test_invalid_saved_secret_never_becomes_rollback_input(tmp_path, location):
  install(tmp_path, "A"); install(tmp_path, "B")
  path = tmp_path / "state/deployment.json"
  saved = json.loads(path.read_text())
  if location in ("current", "previous", "removed-guard"):
    current = saved["current"] if location == "current" else saved["previous"]["current"]
    item = next(item for item in current["items"].values() if item.get("guard"))
    item["baseline"]["value"] = "synthetic-illegal-secret"
    if location == "removed-guard": item.pop("guard")
  else:
    change = next(item for item in saved["previous"]["changes"] if item.get("before_guard"))
    change["before"]["value"] = "synthetic-illegal-secret"
  path.write_text(json.dumps(saved))
  original = (tmp_path / "instance/pi-home/models.json").read_bytes()
  with pytest.raises(Conflict):
    dep.rollback(tmp_path / "instance", tmp_path / "state", BINDING)
  assert (tmp_path / "instance/pi-home/models.json").read_bytes() == original


def test_first_rollback_removes_only_initialized_managed_fields(tmp_path):
  install(tmp_path, "A")
  dep.rollback(tmp_path / "instance", tmp_path / "state", BINDING)
  assert not (tmp_path / "instance/pi-home/models.json").exists()
  assert not (tmp_path / "state/pending.json").exists()


def test_one_sided_drift_keeps_baseline_and_bilateral_change_conflicts(tmp_path):
  install(tmp_path, "A")
  path = tmp_path / "instance/pi-home/settings.json"
  path.write_text('{"quietStartup":[],"unknown":false}')
  state = tmp_path / "state/deployment.json"
  before = state.read_bytes()
  assert install(tmp_path, "A")["drift"] == 1
  assert state.read_bytes() == before
  with pytest.raises(Conflict):
    install(tmp_path, "B")
  assert json.loads(path.read_text()) == {"quietStartup": [], "unknown": False}


def test_pending_invalid_secret_is_retained_and_never_replayed(tmp_path):
  install(tmp_path, "A")
  with Tree(tmp_path / "state") as state, Tree(tmp_path / "instance") as target:
    old = dep.read_state(state)
    planned = dep.plan(target, old, candidate("B"), BINDING, {})
    change = next(row for row in planned.changes if row["item"].get("guard"))
    change["before"]["value"] = "synthetic-invalid-pending-secret"
    state.write_state("pending.json", dep.json_bytes({"after_state": {**old, "current": planned.current}, "changes": planned.changes}))
    before = target.read("pi-home/models.json")[0]
    with pytest.raises(Conflict):
      dep.recover(target, state)
    assert state.read("pending.json") is not None
    assert target.read("pi-home/models.json")[0] == before

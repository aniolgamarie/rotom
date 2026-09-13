"""DEP：真实临时文件上的三方部署、单份备份、故障恢复和活动锁。"""

from copy import deepcopy
import json
import os

import pytest

from agentcfg.adapter import Artifact, ManagedTarget, Ownership
from agentcfg import deployment as dep
from agentcfg.render import RenderCandidate
from agentcfg.storage import Conflict, Tree, instance_lock


BINDING = {"machine": "test", "local": "/synthetic/local.toml", "profile": "test"}
LAUNCH = {"lock_identity": "fixture", "secrets": ["secret:key"]}


def candidate(value="A", *, field=False, extra=True):
  artifacts = []
  if value is not None:
    target = ManagedTarget("dsh-home/settings.yaml" if field else "rules.md",
                           Ownership.FIELDS if field else Ownership.FILE,
                           "yaml" if field else "bytes", "/ui/theme" if field else None)
    content = json.dumps(value).encode() if field else value.encode()
    artifacts.append(Artifact(target, content))
  if extra:
    artifacts.append(Artifact(ManagedTarget("skills/中文 空格/resource", Ownership.FILE, "bytes"), b"resource"))
  return RenderCandidate(str((value, field, extra)), tuple(artifacts))


@pytest.fixture
def instance(tmp_path):
  return tmp_path / "instance", tmp_path / "state"


def apply(instance, value="A", **options):
  return dep.apply(*instance, candidate(value, **options), BINDING, LAUNCH)


def state(instance):
  with Tree(instance[1]) as tree:
    return dep.read_state(tree)


def test_apply_noop_rotates_only_previous_and_rollback(instance):
  assert apply(instance)["changes"] == 2
  root, store = instance
  before = (root / "rules.md").stat()
  manifest = (store / "deployment.json").read_bytes()
  assert apply(instance)["changes"] == 0
  assert (root / "rules.md").stat() == before
  assert (store / "deployment.json").read_bytes() == manifest
  apply(instance, "B")
  apply(instance, "C")
  dep.rollback(*instance, BINDING)
  assert (root / "rules.md").read_text() == "B"
  assert state(instance)["previous"] is None
  with pytest.raises(Conflict):
    dep.rollback(*instance, BINDING)


def test_unmanaged_initial_file_and_binding_conflict(instance):
  root, _ = instance
  root.mkdir(mode=0o700)
  (root / "rules.md").write_text("unmanaged")
  with pytest.raises(Conflict):
    apply(instance)
  assert (root / "rules.md").read_text() == "unmanaged"
  (root / "rules.md").unlink()
  apply(instance)
  with pytest.raises(Conflict):
    dep.apply(*instance, candidate("B"), {**BINDING, "machine": "other"}, LAUNCH)


def test_shared_file_keeps_unknown_oauth_and_drift_baseline(instance):
  import yaml
  apply(instance, field=True)
  path = instance[0] / "dsh-home/settings.yaml"
  path.write_text("ui:\n  theme: local\noauth:\n  runtime: synthetic-token\nunknown: retained\n")
  assert apply(instance, field=True)["drift"] == 1
  item = next(i for i in state(instance)["current"]["items"].values() if i["selector"])
  assert item["baseline"] == dep.encoded("A")
  assert apply(instance, field=True)["drift"] == 1
  with pytest.raises(Conflict):
    apply(instance, "B", field=True)
  # C=D：用户已手动改成期望值，不重写共享文件。
  path.write_text(path.read_text().replace("theme: local", "theme: B"))
  before = path.stat()
  assert apply(instance, "B", field=True)["changes"] == 0
  assert path.stat() == before
  apply(instance, "C", field=True)
  dep.rollback(*instance, BINDING)
  current = yaml.safe_load(path.read_text())
  assert current["ui"]["theme"] == "B"
  assert current["oauth"]["runtime"] == "synthetic-token"
  assert b"synthetic-token" not in (instance[1] / "deployment.json").read_bytes()


def test_deselection_deletes_only_unchanged_managed_files(instance):
  apply(instance)
  (instance[0] / "skills/中文 空格/unmanaged").write_text("keep")
  apply(instance, None, extra=False)
  assert not (instance[0] / "rules.md").exists()
  assert (instance[0] / "skills/中文 空格/unmanaged").read_text() == "keep"
  dep.rollback(*instance, BINDING)
  assert (instance[0] / "rules.md").read_text() == "A"


def test_first_rollback_keeps_runtime_and_conflicting_change(instance):
  apply(instance)
  (instance[0] / "session").write_text("runtime")
  (instance[0] / "rules.md").write_text("edited")
  with pytest.raises(Conflict):
    dep.rollback(*instance, BINDING)
  assert state(instance)["previous"] is not None
  (instance[0] / "rules.md").write_text("A")
  dep.rollback(*instance, BINDING)
  assert not (instance[0] / "rules.md").exists()
  assert (instance[0] / "session").read_text() == "runtime"


def test_failed_write_recovers_and_keeps_old_backup(instance, monkeypatch):
  apply(instance)
  apply(instance, "B")
  old = (instance[1] / "deployment.json").read_bytes()
  original = Tree.write_state
  def fail_once(self, name, data):
    if name == "deployment.json":
      monkeypatch.setattr(Tree, "write_state", original)
      raise OSError("synthetic write failure")
    return original(self, name, data)
  monkeypatch.setattr(Tree, "write_state", fail_once)
  with pytest.raises(OSError):
    apply(instance, "C")
  assert (instance[0] / "rules.md").read_text() == "B"
  assert (instance[1] / "deployment.json").read_bytes() == old
  assert not (instance[1] / "pending.json").exists()


def test_pending_recovery_preserves_native_later_fields(instance):
  import yaml
  apply(instance, field=True)
  with Tree(instance[1]) as store, Tree(instance[0]) as target:
    old = dep.read_state(store)
    plan = dep.plan(target, old, candidate("B", field=True), BINDING, LAUNCH)
    after = {**old, "current": plan.current}
    store.write_state("pending.json", dep.json_bytes({"after_state": after, "changes": plan.changes}))
    dep.write_changes(target, plan.changes)
    path = instance[0] / "dsh-home/settings.yaml"
    path.write_text(path.read_text() + "runtime: keep\n")
    dep.recover(target, store)
    document = yaml.safe_load(path.read_text())
    assert document == {"ui": {"theme": "A"}, "runtime": "keep"}
    assert dep.read_state(store) == old


def test_lock_blocks_apply_rollback_and_other_lock(instance):
  apply(instance)
  with Tree(instance[1]) as store, instance_lock(store):
    with pytest.raises(Conflict):
      apply(instance, "B")
    with pytest.raises(Conflict):
      dep.rollback(*instance, BINDING)


def test_write_race_and_symlink_are_not_overwritten(instance, monkeypatch):
  apply(instance)
  original = Tree.replace
  def race(self, path, data, mode=0o600, *, expected):
    if path == "rules.md" and data == b"B":
      (self.root / path).write_bytes(b"raced")
    return original(self, path, data, mode, expected=expected)
  monkeypatch.setattr(Tree, "replace", race)
  with pytest.raises(Conflict):
    apply(instance, "B")
  assert (instance[0] / "rules.md").read_bytes() == b"raced"
  assert (instance[1] / "pending.json").exists()


def test_state_snapshots_contain_no_secret_values(instance):
  apply(instance)
  apply(instance, "B")
  assert b"secret:key" in (instance[1] / "deployment.json").read_bytes()
  assert b"synthetic-unused-key" not in (instance[1] / "deployment.json").read_bytes()


def test_declared_runtime_file_accepts_new_absent_fields_only(instance):
  launch = {**LAUNCH, "shared_files": ["dsh-home/settings.yaml"]}
  dep.apply(*instance, candidate(None, extra=True), BINDING, launch)
  path = instance[0] / "dsh-home/settings.yaml"
  path.parent.mkdir()
  path.write_text("oauth:\n  dynamic: retained\n")
  dep.apply(*instance, candidate("A", field=True), BINDING, launch)
  assert "dynamic: retained" in path.read_text()
  assert b"dynamic" not in (instance[1] / "deployment.json").read_bytes()


def test_initialize_only_value_and_json_types_are_distinct(instance):
  target = ManagedTarget("settings.json", Ownership.INITIALIZE, "json", "/welcome")
  a = RenderCandidate("init", (Artifact(target, b"true"),))
  dep.apply(*instance, a, BINDING, LAUNCH)
  (instance[0] / "settings.json").write_text('{"welcome":false,"runtime":"keep"}')
  dep.apply(*instance, a, BINDING, LAUNCH)
  assert json.loads((instance[0] / "settings.json").read_text())["welcome"] is False
  assert not dep.same(dep.encoded(False), dep.encoded(0))


def test_first_field_deployment_rollback_and_reapply(instance):
  apply(instance, field=True)
  dep.rollback(*instance, BINDING)
  assert not (instance[0] / "dsh-home/settings.yaml").exists()
  assert apply(instance, field=True)["changes"] == 2


def test_rollback_keeps_unknown_empty_runtime_objects(instance):
  import yaml
  apply(instance, field=True)
  path = instance[0] / "dsh-home/settings.yaml"
  path.write_text("ui:\n  theme: A\n  unknown: {}\n")
  dep.rollback(*instance, BINDING)
  assert yaml.safe_load(path.read_text()) == {"ui": {"unknown": {}}}


def test_instance_owner_survives_first_rollback_and_runtime_data(instance):
  launch = {**LAUNCH, "shared_files": ["dsh-home/settings.yaml"]}
  dep.apply(*instance, candidate("A", field=True), BINDING, launch)
  path = instance[0] / "dsh-home/settings.yaml"
  path.write_text(path.read_text() + "oauth: retained\n")
  dep.rollback(*instance, BINDING)
  with pytest.raises(Conflict):
    dep.apply(*instance, candidate("B", field=True), {**BINDING, "machine": "other"}, launch)
  dep.apply(*instance, candidate("B", field=True), BINDING, launch)
  assert "oauth: retained" in path.read_text()

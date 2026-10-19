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


def write_identity(info):
  # 读取可能推进atime；无变化部署仍必须保持inode、正文形状、权限与写入时间。
  return tuple(getattr(info, name) for name in (
    "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns"))


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


def test_retired_field_prunes_only_owned_empty_parents_across_generations(instance):
  apply(instance, "A", field=True)
  apply(instance, "B", field=True)
  apply(instance, "C", field=True)
  root, _ = instance
  native = root / "dsh-home/settings.yaml"
  document = dep.parse_native(native.read_bytes(), "yaml")
  document["unmanaged"] = {"keep": "SYNTHETIC"}
  native.write_bytes(dep.encode_native(document, "yaml"))
  apply(instance, None, field=True)
  assert dep.parse_native(native.read_bytes(), "yaml") == {"unmanaged": {"keep": "SYNTHETIC"}}
  dep.rollback(*instance, BINDING)
  assert dep.parse_native(native.read_bytes(), "yaml") == {"unmanaged": {"keep": "SYNTHETIC"}, "ui": {"theme": "C"}}


def test_retired_field_keeps_user_created_empty_parent(instance):
  launch = {**LAUNCH, "shared_files": ["dsh-home/settings.yaml"]}
  dep.apply(*instance, candidate(), BINDING, launch)
  native = instance[0] / "dsh-home/settings.yaml"
  native.parent.mkdir()
  native.write_text("ui: {}\n")
  native.chmod(0o600)
  dep.apply(*instance, candidate("A", field=True), BINDING, launch)
  dep.apply(*instance, candidate(None, field=True), BINDING, launch)
  assert dep.parse_native(native.read_bytes(), "yaml") == {"ui": {}}


def test_retired_field_keeps_new_native_children_in_owned_parent(instance):
  apply(instance, "A", field=True)
  native = instance[0] / "dsh-home/settings.yaml"
  document = dep.parse_native(native.read_bytes(), "yaml")
  document["ui"]["userPreference"] = False
  native.write_bytes(dep.encode_native(document, "yaml"))
  apply(instance, None, field=True)
  assert dep.parse_native(native.read_bytes(), "yaml") == {"ui": {"userPreference": False}}


def test_dynamic_shared_file_reselection_keeps_native_values_and_owner(instance):
  apply(instance, extra=False)
  apply(instance, field=True, extra=False)
  native = instance[0] / "dsh-home/settings.yaml"
  native.write_text(native.read_text() + "runtime: SYNTHETIC_NATIVE_VALUE\n")
  apply(instance, None, field=True, extra=False)
  apply(instance, None, field=True, extra=False)
  assert not state(instance)["current"]["items"]
  assert dep.parse_native(native.read_bytes(), "yaml") == {"runtime": "SYNTHETIC_NATIVE_VALUE"}
  apply(instance, field=True, extra=False)
  assert dep.parse_native(native.read_bytes(), "yaml") == {
    "runtime": "SYNTHETIC_NATIVE_VALUE", "ui": {"theme": "A"}}
  assert state(instance)["owner"]["shared_files"] == ["dsh-home/settings.yaml"]
  assert b"SYNTHETIC_NATIVE_VALUE" not in (instance[1] / "deployment.json").read_bytes()
  dep.rollback(*instance, BINDING)
  assert state(instance)["owner"]["shared_files"] == ["dsh-home/settings.yaml"]
  apply(instance, field=True, extra=False)


def test_unselected_shared_file_does_not_preclaim_existing_native_file(instance, sentinel_factory):
  apply(instance, extra=False)
  native = instance[0] / "dsh-home/settings.yaml"
  native.parent.mkdir()
  native.write_text("runtime: SYNTHETIC_UNOWNED\n")
  assert state(instance)["owner"]["shared_files"] == []
  target_before, state_before = sentinel_factory(instance[0]), sentinel_factory(instance[1])
  with pytest.raises(Conflict):
    apply(instance, field=True, extra=False)
  target_before.assert_unchanged()
  state_before.assert_unchanged()


def test_retired_shared_path_still_rejects_existing_managed_field(instance, sentinel_factory):
  apply(instance, field=True, extra=False)
  apply(instance, None, field=True, extra=False)
  apply(instance, None, field=True, extra=False)
  assert not state(instance)["current"]["items"]
  native = instance[0] / "dsh-home/settings.yaml"
  native.write_text("ui: {theme: native}\n")
  target_before, state_before = sentinel_factory(instance[0]), sentinel_factory(instance[1])
  with pytest.raises(Conflict):
    apply(instance, field=True, extra=False)
  target_before.assert_unchanged()
  state_before.assert_unchanged()


@pytest.mark.parametrize("fail_commit", [False, True])
def test_shared_file_provenance_backfill_is_atomic_and_preserves_backup(instance, monkeypatch, fail_commit):
  apply(instance, field=True, extra=False)
  # 模拟旧版本已部署字段但尚未登记动态共享文件来源。
  with Tree(instance[1]) as store:
    old = dep.read_state(store)
    old["owner"]["shared_files"] = []
    store.write_state("deployment.json", dep.json_bytes(old))
  before_state = (instance[1] / "deployment.json").read_bytes()
  native = instance[0] / "dsh-home/settings.yaml"
  before_native = native.read_bytes(), write_identity(native.stat())
  if fail_commit:
    original = Tree.write_state
    def fail_once(self, name, data):
      if name == "deployment.json":
        monkeypatch.setattr(Tree, "write_state", original)
        raise OSError("synthetic provenance commit failure")
      return original(self, name, data)
    monkeypatch.setattr(Tree, "write_state", fail_once)
    with pytest.raises(OSError):
      apply(instance, field=True, extra=False)
    assert (instance[1] / "deployment.json").read_bytes() == before_state
    assert not (instance[1] / "pending.json").exists()
  assert apply(instance, field=True, extra=False)["changes"] == 0
  saved = state(instance)
  assert saved["owner"]["shared_files"] == ["dsh-home/settings.yaml"]
  assert saved["current"] == old["current"] and saved["previous"] == old["previous"]
  assert (native.read_bytes(), write_identity(native.stat())) == before_native
  committed = write_identity((instance[1] / "deployment.json").stat())
  assert apply(instance, field=True, extra=False)["changes"] == 0
  assert write_identity((instance[1] / "deployment.json").stat()) == committed


def test_saved_parent_ownership_cannot_target_an_unrelated_container(instance):
  apply(instance, "A", field=True)
  saved = state(instance)
  item = next(i for i in saved["current"]["items"].values() if i["selector"])
  item["created_parents"] = ["/unmanaged"]
  with pytest.raises(Conflict): dep.validate_saved_state(saved)


@pytest.mark.parametrize("operation", ["recover", "rollback"])
def test_pending_recovery_checks_all_native_references_before_restoring_any_file(instance, operation):
  def protected_candidate(value):
    return RenderCandidate(value, (
      Artifact(ManagedTarget("aaa-managed.txt", Ownership.FILE, "text"), value.encode()),
      Artifact(ManagedTarget("pi-home/models.json", Ownership.FIELDS, "json", "/providers/demo/apiKey", ("$DEMO_KEY",)),
        json.dumps("$DEMO_KEY").encode()),
    ))
  dep.apply(*instance, protected_candidate("A"), BINDING, LAUNCH)
  root, store = instance
  with Tree(store) as saved, Tree(root) as target:
    old = dep.read_state(saved)
    planned = dep.plan(target, old, protected_candidate("B"), BINDING, LAUNCH)
    after = {**old, "current": planned.current, "previous": {"current": old["current"], "changes": planned.changes}}
    saved.write_state("pending.json", dep.json_bytes({"after_state": after, "changes": planned.changes}))
  # 模拟中断已改首文件，但未提交state；后面的认证字段独立漂移成明文。
  first = root / "aaa-managed.txt"
  first.write_text("B")
  native = root / "pi-home/models.json"
  native.write_text(json.dumps({"providers": {"demo": {"apiKey": "SYNTHETIC_LITERAL_NEVER_LOGGED"}}}))
  before = {p: (p.read_bytes(), p.stat().st_ino) for p in (first, native, store / "pending.json", store / "deployment.json")}
  with pytest.raises(Conflict):
    if operation == "rollback": dep.rollback(root, store, BINDING)
    else:
      with Tree(store) as saved, Tree(root) as target: dep.recover(target, saved)
  assert before == {p: (p.read_bytes(), p.stat().st_ino) for p in before}


def test_optional_state_guard_runs_under_lock_before_target_creation_or_recovery(tmp_path):
  root, store = tmp_path / "instance", tmp_path / "state"
  def reject(saved):
    assert saved["current"] is None and saved["pending"] is None
    with Tree(store) as tree, pytest.raises(Conflict):
      with instance_lock(tree):
        pytest.fail("部署 guard 必须处于已有实例锁内")
    raise Conflict("fixture guard denied")
  with pytest.raises(Conflict, match="fixture guard denied"):
    dep.apply(root, store, candidate(), BINDING, LAUNCH, state_guard=reject)
  assert not root.exists()
  assert not (store / "deployment.json").exists()
  assert not (store / "pending.json").exists()


def test_apply_noop_rotates_only_previous_and_rollback(instance):
  assert apply(instance)["changes"] == 2
  root, store = instance
  before = (root / "rules.md").stat()
  manifest = (store / "deployment.json").read_bytes()
  assert apply(instance)["changes"] == 0
  assert write_identity((root / "rules.md").stat()) == write_identity(before)
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
  assert write_identity(path.stat()) == write_identity(before)
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


def initialization_candidate(theme="A", preference=True, owner=Ownership.INITIALIZE):
  base = candidate(theme, field=True, extra=False)
  target = ManagedTarget("dsh-home/settings.yaml", owner, "yaml", "/ui/compact")
  return RenderCandidate(str((theme, preference, owner.value)), base.artifacts + (Artifact(target, json.dumps(preference).encode()),))


def test_existing_preference_in_owned_shared_file_consumes_initialization_without_baseline(instance):
  apply(instance, field=True, extra=False)
  path = instance[0] / "dsh-home/settings.yaml"
  path.write_text("ui:\n  theme: A\n  compact: false\n  unknown: {keep: true}\n")
  original = path.read_bytes(), path.stat()
  proposal = initialization_candidate()
  assert dep.apply(*instance, proposal, BINDING, LAUNCH)["changes"] == 0
  assert (path.read_bytes(), path.stat()) == original
  imported = next(item for item in state(instance)["current"]["items"].values() if item["selector"] == "/ui/compact")
  assert imported["baseline"] == dep.ABSENT
  assert "desired" not in imported
  assert dep.apply(*instance, proposal, BINDING, LAUNCH)["changes"] == 0
  # 来源改为相反值也不重启初始化；后续配置回滚只处理真实写入的 theme。
  assert dep.apply(*instance, initialization_candidate("B", False), BINDING, LAUNCH)["changes"] == 1
  with Tree(instance[1]) as tree:
    changes = dep.read_state(tree)["previous"]["changes"]
  assert [change["item"]["selector"] for change in changes] == ["/ui/theme"]
  dep.rollback(*instance, BINDING)
  assert dep.parse_native(path.read_bytes(), "yaml") == dep.parse_native(original[0], "yaml")


@pytest.mark.parametrize("owner", [Ownership.INITIALIZE, Ownership.FIELDS])
def test_unowned_nonempty_file_rejects_initialization_and_managed_fields(instance, owner, sentinel_factory):
  root, store = instance
  with Tree(root, create=True) as tree:
    tree.write_state("dsh-home/settings.yaml", b"ui: {compact: false, unknown: keep}\n")
  unchanged = sentinel_factory(root)
  proposal = RenderCandidate("unowned", (Artifact(ManagedTarget("dsh-home/settings.yaml", owner, "yaml", "/ui/compact"), b"true"),))
  with pytest.raises(Conflict):
    dep.apply(root, store, proposal, BINDING, LAUNCH)
  unchanged.assert_unchanged()
  with Tree(store) as tree:
    assert dep.read_state(tree)["current"] is None


def test_owned_shared_file_existing_managed_field_still_conflicts(instance, sentinel_factory):
  apply(instance, field=True, extra=False)
  path = instance[0] / "dsh-home/settings.yaml"
  path.write_text("ui: {theme: A, compact: false, unknown: keep}\n")
  root_before, state_before = sentinel_factory(instance[0]), sentinel_factory(instance[1])
  with pytest.raises(Conflict):
    dep.apply(*instance, initialization_candidate(owner=Ownership.FIELDS), BINDING, LAUNCH)
  root_before.assert_unchanged()
  state_before.assert_unchanged()

"""只观察选定机器的合成实例；不启动、停止或扫描原生会话。"""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agentcfg import lifecycle, local, run_owners as owners, workspace
from agentcfg.omp_identity import lifecycle_guard as omp_guard
from agentcfg.storage import Conflict
from rotom import cli


MANAGER = {"pid": 1234, "birth_id": "synthetic-manager"}


@pytest.fixture
def machine(tmp_path, monkeypatch):
  config = tmp_path / "local.toml"
  config.write_text("synthetic config; not parsed by the workspace spy\n")
  config.chmod(0o600)
  workspaces = {}
  calls = []
  for agent, profile in (("dsh", "dsh-default"), ("dsh", "dsh-extra"),
      ("pi", "pi-base"), ("omp", "omp-default")):
    w = SimpleNamespace(agent=agent, profile=profile,
      instance=tmp_path / "instances" / profile, state_root=tmp_path / "state" / profile,
      binding={"machine": "synthetic", "local": str(config), "profile": profile})
    with (omp_guard(w, create=True) if agent == "omp" else lifecycle.guard(w)):
      pass
    workspaces[profile] = w
  monkeypatch.setattr(local, "available_profiles", lambda: [(p, w.agent) for p, w in workspaces.items()])
  def selected(path, profiles, **kwargs):
    assert path == config
    calls.extend(profiles)
    return [workspaces[profile] for profile in profiles]
  monkeypatch.setattr(workspace, "load_instance_workspaces", selected, raising=False)
  monkeypatch.setattr(owners, "observed_process_identity", lambda pid: deepcopy(MANAGER), raising=False)
  return SimpleNamespace(local=config, workspaces=workspaces, calls=calls)


def register(machine, profile="dsh-default", *, state="active", legacy=False):
  w = machine.workspaces[profile]
  native = w.instance / "native-home"
  native.mkdir(mode=0o700, exist_ok=True)
  registry = owners.Registry(w.state_root / "run-owners", w.binding)
  if legacy:
    run = registry.register(MANAGER, session_ref="unqualified-legacy-id")
  else:
    kinds = {"dsh": "dsh-home", "pi": "pi-home", "omp": "omp-managed-home"}
    run = registry.register_v2(MANAGER, {"agent": w.agent, "backend": "managed", "profile": profile,
      "machine_ref": {k: w.binding[k] for k in ("machine", "local")},
      "start_cwd": {"path": str(native), "source": "launch-spec", "confirmation": "confirmed", "observed_at_ns": 1},
      "native_home_ref": {"kind": kinds[w.agent], "path": str(native), "source": "deployed-contract", "confirmation": "confirmed"},
      "deployed_identity": {"deployment": "b" * 64, "runtime": "c" * 64}, "coordination_domain": None})
  if state == "unknown":
    registry.mark_unknown(run, MANAGER)
  elif state == "idle_confirmed":
    registry.finish_current(run, MANAGER, owners.ReleaseObservation(run, MANAGER, True, True))
  return registry, run


def test_machine_view_does_not_filter_by_default_profile(machine):
  register(machine)
  register(machine, "dsh-extra")
  report = owners.instances(machine.local, agent="dsh")
  assert machine.calls == ["dsh-default", "dsh-extra"]
  assert {r["profile"] for r in report["instances"]} == {"dsh-default", "dsh-extra"}


def test_explicit_profile_and_tool_are_hard_constraints(machine):
  register(machine, "pi-base")
  report = owners.instances(machine.local, agent="pi", profile="pi-base")
  assert [r["profile"] for r in report["instances"]] == ["pi-base"]
  with pytest.raises(ValueError):
    owners.instances(machine.local, agent="dsh", profile="pi-base")
  with pytest.raises(ValueError):
    owners.instances(machine.local, profile="missing-profile")


def test_profile_tool_change_during_source_loading_cannot_cross_explicit_scope(machine, monkeypatch):
  # 发现公开元数据后、构造Workspace前的源变更不得改变已接受的工具范围。
  initial = local.available_profiles()
  monkeypatch.setattr(local, "available_profiles", lambda: initial)
  machine.workspaces["dsh-default"].agent = "pi"
  with pytest.raises(Conflict):
    owners.instances(machine.local, agent="dsh", profile="dsh-default")


@pytest.mark.parametrize("state,expected", [("active", "active"), ("unknown", "unknown"),
  ("idle_confirmed", "stopped")])
def test_process_session_and_terminal_are_separate_facts(machine, state, expected):
  registry, run = register(machine, state=state)
  row = owners.instances(machine.local, agent="dsh", profile="dsh-default")["instances"][0]
  assert row["run_id"] == run and row["process"]["status"] == expected
  assert row["process"]["manager_identity"] == MANAGER
  assert row["process"]["host_identity"] is None
  assert row["process"]["source"] and row["process"]["observed_at_ns"] > 0
  assert row["session"]["status"] == "unknown" and row["session"]["ref"] is None
  assert row["terminal"]["status"] == "unknown"
  assert row["start_cwd"]["path"] and row["session_cwd"] is None
  assert owners.record_state(registry.snapshot()[run]) == state


def test_old_registration_or_reused_pid_does_not_prove_active_or_idle(machine, monkeypatch):
  registry, run = register(machine)
  monkeypatch.setattr(owners, "observed_process_identity", lambda pid: {**MANAGER, "birth_id": "reused"})
  row = owners.instances(machine.local, agent="dsh", profile="dsh-default")["instances"][0]
  assert row["process"]["status"] == "unknown"
  assert owners.record_state(registry.snapshot()[run]) == "active"


def test_missing_manager_is_not_complete_release(machine, monkeypatch):
  registry, run = register(machine)
  monkeypatch.setattr(owners, "observed_process_identity", lambda pid: None)
  row = owners.instances(machine.local, agent="dsh", profile="dsh-default")["instances"][0]
  assert row["process"]["status"] == "unknown"
  assert owners.record_state(registry.snapshot()[run]) == "active"


def test_legacy_id_is_not_promoted_to_a_scoped_session(machine):
  register(machine, legacy=True)
  row = owners.instances(machine.local, agent="dsh", profile="dsh-default")["instances"][0]
  assert row["schema_version"] == 1 and row["session"]["ref"] is None
  assert row["session"]["status"] == "unknown" and row["start_cwd"] is None


def test_saved_session_is_historical_and_never_enables_resume(machine):
  registry, run = register(machine)
  path = registry.root / (run + ".json")
  record = registry.snapshot()[run]
  record["session_observation"] = {"session": {"agent": "dsh", "backend": "managed",
    "native_home_ref": owners.native_home_key(record["native_home_ref"]), "native_ref": "session-example"},
    "run_id": run, "emitter_epoch": "epoch-example", "sequence": 1,
    "confirmation": "confirmed", "source": "synthetic-public-event", "observed_at_ns": 2}
  path.write_text(json.dumps(record))
  row = owners.instances(machine.local, agent="dsh", profile="dsh-default")["instances"][0]
  assert row["session"]["status"] == "historical"
  assert row["session"]["ref"]["native_ref"] == "session-example"
  assert row["session"]["resume_available"] is False
  assert row["process"]["status"] == "active"


def test_unregistered_physical_lease_remains_visible(machine):
  w = machine.workspaces["dsh-default"]
  with lifecycle.guard(w, shared=True, create=False):
    report = owners.instances(machine.local, agent="dsh", profile=w.profile)
  assert report["instances"][0]["kind"] == "unregistered-or-unverified"
  assert report["instances"][0]["process"]["status"] == "unknown"
  assert report["instances"][0]["run_id"] is None


def test_omp_without_registry_is_not_reported_as_zero_runs(machine):
  report = owners.instances(machine.local, agent="omp")
  assert report["instances"][0]["kind"] == "unregistered-or-unverified"
  assert report["coverage"][0]["registration"] == "unsupported"
  assert report["instances"][0]["process"]["status"] == "unknown"


def test_corrupt_registry_is_visible_and_incomplete_not_empty(machine):
  registry, run = register(machine)
  path = registry.root / (run + ".json")
  record = registry.snapshot()[run]
  record["unexpected"] = "synthetic"
  path.write_text(json.dumps(record))
  report = owners.instances(machine.local, agent="dsh", profile="dsh-default")
  assert report["incomplete"] is True and report["instances"]
  assert report["coverage"][0]["status"] == "unknown"


def test_read_only_query_does_not_mutate_files_or_spawn(machine, sentinel_factory, fake_subprocess, monkeypatch):
  registry, run = register(machine, state="unknown")
  sentinel = sentinel_factory(machine.local.parent)
  monkeypatch.setattr(owners.Registry, "reconcile", lambda *a, **kw: pytest.fail("no reconciliation"))
  report = owners.instances(machine.local)
  assert report["instances"] and fake_subprocess.calls == []
  sentinel.assert_unchanged()


def test_mutating_one_query_cannot_change_persisted_or_later_observations(machine):
  registry, run = register(machine)
  first = owners.instances(machine.local, profile="dsh-default")
  first["instances"][0]["process"]["manager_identity"]["birth_id"] = "caller-mutated"
  first["instances"][0]["start_cwd"]["path"] = "/synthetic/changed"
  assert registry.snapshot()[run]["manager_identity"] == MANAGER
  later = owners.instances(machine.local, profile="dsh-default")["instances"][0]
  assert later["process"]["manager_identity"] == MANAGER
  assert later["start_cwd"]["path"] != "/synthetic/changed"


@pytest.mark.parametrize("format", ["json", "human"])
def test_cli_list_uses_explicit_scope_and_output_mode(machine, capsys, format):
  register(machine)
  assert cli.main(["--no-input", "agent", "--local", str(machine.local), "instances", "list",
    "--agent", "dsh", "--format", format]) == 0
  output = capsys.readouterr()
  if format == "json":
    data = json.loads(output.out)
    assert data["scope"]["local"] == str(machine.local)
    assert data["scope"]["profile"] is None
    assert data["instances"][0]["process"]["manager_identity"]["pid"] == MANAGER["pid"]
  else:
    assert "dsh-default" in output.out and "1234" in output.out
    assert "unknown" in output.out and "source=" in output.out


def test_cli_corruption_returns_four_with_structured_result(machine, capsys):
  registry, run = register(machine)
  (registry.root / (run + ".json")).write_text("{}")
  assert cli.main(["--no-input", "agent", "--local", str(machine.local), "--profile", "dsh-default",
    "instances", "list", "--format", "json"]) == 4
  assert json.loads(capsys.readouterr().out)["incomplete"] is True


@pytest.mark.parametrize("failure", [None, "changed", "missing", "malformed"])
def test_selected_process_observer_only_reads_boot_and_target_stat(monkeypatch, failure):
  from pathlib import Path
  boot = "00000000-0000-4000-8000-000000000001"
  samples = []
  def read(path, **kwargs):
    text = str(path)
    assert text in ("/proc/sys/kernel/random/boot_id", "/proc/1234/stat")
    if text.endswith("boot_id"):
      return boot
    if failure == "missing":
      raise FileNotFoundError()
    if failure == "malformed":
      return "malformed-stat"
    samples.append(text)
    tail = ["S"] + ["1"] * 18 + ["222" if failure == "changed" and len(samples) > 1 else "111"]
    return "1234 (synthetic (name)) " + " ".join(tail)
  with monkeypatch.context() as patch:
    patch.setattr(owners.sys, "platform", "linux")
    patch.setattr(Path, "read_text", read)
    result = owners.observed_process_identity(1234)
  assert result == ({"pid": 1234, "birth_id": "linux:" + boot + ":111"} if failure is None else None)


def test_unprepared_profiles_do_not_create_any_state(machine, sentinel_factory):
  import shutil
  w = machine.workspaces["dsh-extra"]
  shutil.rmtree(w.instance)
  sentinel = sentinel_factory(machine.local.parent)
  report = owners.instances(machine.local, profile=w.profile)
  assert report["instances"] == [] and report["coverage"][0]["status"] == "not-prepared"
  sentinel.assert_unchanged()


def test_human_output_escapes_control_characters_in_saved_session(machine, capsys):
  registry, run = register(machine)
  path = registry.root / (run + ".json")
  record = registry.snapshot()[run]
  record["session_observation"] = {"session": {"agent": "dsh", "backend": "managed",
    "native_home_ref": owners.native_home_key(record["native_home_ref"]), "native_ref": "session\x1b[31m\nexample"},
    "run_id": run, "emitter_epoch": "epoch-example", "sequence": 1,
    "confirmation": "historical", "source": "synthetic-public-event", "observed_at_ns": 2}
  path.write_text(json.dumps(record))
  assert cli.main(["agent", "--local", str(machine.local), "--profile", "dsh-default",
    "instances", "list", "--format", "human"]) == 0
  output = capsys.readouterr().out
  assert "\x1b" not in output and "session?[31m\\nexample" in output


def test_instance_context_uses_single_config_snapshot_without_runtime_resolution(tmp_path, monkeypatch):
  from agentcfg import config
  from test_runtime import local_file
  path = tmp_path / "machine.toml"
  local_file(path)
  original = workspace.load_local
  calls = []
  def load(*args, **kwargs):
    result = original(*args, **kwargs)
    calls.append(result[0].data["machine"]["id"])
    path.write_text(path.read_text().replace('id="runtime"', 'id="changed"'))
    return result
  monkeypatch.setattr(workspace, "load_local", load)
  monkeypatch.setattr(workspace, "load_public_catalog", lambda **kw: pytest.fail("inventory needs no model catalog"))
  monkeypatch.setattr(workspace, "resolve_config", lambda *a, **kw: pytest.fail("inventory is not launch readiness"))
  monkeypatch.setattr(config, "load_secrets", lambda *a, **kw: pytest.fail("query cannot resolve credentials"))
  loaded = workspace.load_instance_workspaces(path, ["dsh-default", "pi-base"])
  assert calls == ["runtime"]
  assert {w.binding["machine"] for w in loaded} == {"runtime"}


@pytest.mark.parametrize("damage", ["profile-field", "local-field", "other-profile-option",
  "profile-reference", "path", "filename", "agent-type", "nonfinite"])
def test_instance_context_strictly_rejects_all_read_sources(tmp_path, damage):
  from agentcfg.schema import ConfigError
  root = tmp_path / "public"
  (root / "profiles").mkdir(parents=True)
  (root / "profiles/selected.toml").write_text('schema_version=1\nid="selected"\nagent="dsh"\n')
  other = root / "profiles/other.toml"
  other.write_text('schema_version=1\nid="other"\nagent="dsh"\n')
  path = tmp_path / "local.toml"
  content = 'schema_version=1\n[machine]\nid="synthetic"\n'
  if damage == "profile-field":
    other.write_text(other.read_text() + 'unknown=true\n')
  elif damage == "local-field":
    content = 'unknown=true\n' + content
  elif damage == "other-profile-option":
    content += '[overrides.profiles.other.agent_options]\nterminal_images="wrong"\n'
  elif damage == "profile-reference":
    content += '[overrides.profiles.missing]\nproviders=[]\n'
  elif damage == "path":
    content += '[machine.paths]\nstate_root="../escape"\n'
  elif damage == "filename":
    other.write_text('schema_version=1\nid="mismatch"\nagent="dsh"\n')
  elif damage == "agent-type":
    other.write_text('schema_version=1\nid="other"\n[agent]\nname="dsh"\n')
  else:
    other.write_text(other.read_text() + '[agent_options]\nvalue=nan\n')
  path.write_text(content)
  path.chmod(0o600)
  with pytest.raises(ConfigError):
    workspace.load_instance_workspaces(path, ["selected"], repository=root)


def test_instance_context_rejects_linked_public_source(tmp_path):
  root = tmp_path / "public"
  (root / "profiles").mkdir(parents=True)
  target = tmp_path / "unrelated.toml"
  target.write_text("must not be consumed\n")
  (root / "profiles/linked.toml").symlink_to(target)
  with pytest.raises(Conflict):
    workspace.load_instance_workspaces(tmp_path / "unused.toml", ["linked"], repository=root)


@pytest.mark.parametrize("facade", [False, True])
def test_instance_scope_discovery_rejects_links_before_any_following_read(tmp_path, monkeypatch, facade):
  from pathlib import Path
  root = tmp_path / "public"
  (root / "profiles").mkdir(parents=True)
  target = tmp_path / "unrelated.toml"
  target.write_text("must not be consumed\n")
  linked = root / "profiles/linked.toml"
  linked.symlink_to(target)
  monkeypatch.setattr(local, "__file__", str(root / "src/agentcfg/local.py"))
  original = Path.read_text
  def read(path, *args, **kwargs):
    if path in (target, linked):
      pytest.fail("profile discovery must not follow a source link")
    return original(path, *args, **kwargs)
  monkeypatch.setattr(Path, "read_text", read)
  if facade:
    assert cli.main(["--no-input", "agent", "--local", str(tmp_path / "unused.toml"),
      "--profile", "linked", "instances", "list"]) == 4
  else:
    with pytest.raises(Conflict):
      owners.instances(tmp_path / "unused.toml")


@pytest.mark.parametrize("profile", ["dsh-default", "pi-base", "omp-default"])
@pytest.mark.parametrize("custom_paths", [False, True])
def test_instance_context_matches_runtime_physical_binding(tmp_path, profile, custom_paths):
  from test_runtime import local_file
  path = tmp_path / "local.toml"
  local_file(path)
  if custom_paths:
    with path.open("a") as stream:
      stream.write('[machine.paths]\n')
      for name in ("instances_root", "state_root", "cache_root"):
        stream.write(name + '=' + json.dumps(str(tmp_path / (name + " custom"))) + '\n')
  observed, = workspace.load_instance_workspaces(path, [profile])
  runnable = workspace.load_workspace(path, profile, allow_missing_local_values=True)
  for name in ("agent", "profile", "instance", "state_root", "binding"):
    assert getattr(observed, name) == getattr(runnable, name)


def test_instance_help_describes_readonly_query_without_capability_stub(capsys):
  effects = cli.command_effects(("agent", "instances", "list"))
  assert "capability:not-admitted" not in effects and "write:none" in effects
  assert cli.main(["agent", "instances", "list", "--help"]) == 0
  assert "read:selected-machine" in capsys.readouterr().out

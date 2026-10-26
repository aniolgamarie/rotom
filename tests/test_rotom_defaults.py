"""入口偏好的格式、引用与安全保存边界。"""

from contextlib import contextmanager
import os
from pathlib import Path

import pytest

from agentcfg.storage import Tree
from rotom import preferences


def config_path():
  return Path(os.environ["XDG_CONFIG_HOME"]) / "rotom" / "config.toml"


def write_config(text="schema_version = 1\n", *, mode=0o600):
  path = config_path()
  path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
  path.parent.chmod(0o700)
  path.write_text(text)
  path.chmod(mode)
  return path


def write_machine(namespace, identifier):
  home = Path(os.environ["XDG_CONFIG_HOME"])
  directory = home / ("termcfg" if namespace == "term" else "agentcfg") / "machines"
  directory.mkdir(mode=0o700, parents=True, exist_ok=True)
  directory.chmod(0o700)
  path = directory / (identifier + ".toml")
  text = ('machine_id = "' + identifier + '"\n') if namespace == "term" else (
    'schema_version = 1\n[machine]\nid = "' + identifier + '"\n')
  path.write_text(text)
  path.chmod(0o600)
  return path


def test_missing_preferences_show_is_read_only():
  before = config_path().parent.exists()
  result = preferences.load_preferences()
  assert result.data == {"schema_version": 1}
  assert result.get("run_profiles.pi") is None
  assert config_path().parent.exists() == before


def test_load_does_not_read_machine_or_resolve_stale_references(monkeypatch):
  write_config('schema_version = 1\n[defaults]\nagent_machine = "missing-machine"\n')
  monkeypatch.setattr(preferences, "validate_reference", lambda *args: pytest.fail("reference read"))
  assert preferences.load_preferences().get("defaults.agent_machine") == "missing-machine"


@pytest.mark.parametrize("body", [
  "schema_version = 2\n",
  "schema_version = true\n",
  "schema_version = 1\nunknown = 'synthetic-secret-marker'\n",
  "schema_version = 1\nschema_version = 1\n",
  "schema_version = 1\n[defaults]\nunknown = 'synthetic-secret-marker'\n",
  "schema_version = 1\n[defaults]\nagent_machine = 1\n",
  "schema_version = 1\n[run_profiles]\npi = inf\n",
  "schema_version = 1\n[run_profiles]\npi = nan\n",
  "schema_version = 1\n[run_profiles]\npi = 'escape/value'\n",
  "schema_version = 1\n[defaults]\nterm_machine = 'bad.name'\n",
])
def test_invalid_document_is_fixed_error_without_private_context(body):
  write_config(body)
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.load_preferences()
  assert caught.value.exit_code == 2
  assert "synthetic-secret-marker" not in str(caught.value)
  assert caught.value.__context__ is None


@pytest.mark.parametrize("file_mode,directory_mode", [(0o644, 0o700), (0o600, 0o755)])
def test_unsafe_preferences_permissions_fail(file_mode, directory_mode):
  path = write_config(mode=file_mode)
  path.parent.chmod(directory_mode)
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.load_preferences()
  assert caught.value.exit_code == 4


def test_preferences_file_link_is_not_followed(tmp_path):
  outside = tmp_path / "outside"
  outside.write_text("synthetic-private-marker")
  outside.chmod(0o600)
  path = config_path()
  path.parent.mkdir(mode=0o700)
  path.symlink_to(outside)
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.load_preferences()
  assert caught.value.exit_code == 4
  assert outside.read_text() == "synthetic-private-marker"


def test_preferences_parent_link_is_not_followed(tmp_path):
  outside = tmp_path / "outside"
  outside.mkdir(mode=0o700)
  config_path().parent.symlink_to(outside, target_is_directory=True)
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.load_preferences()
  assert caught.value.exit_code == 4
  assert not list(outside.iterdir())


def test_preferences_hardlink_is_rejected(tmp_path):
  path = write_config()
  os.link(path, tmp_path / "other")
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.load_preferences()
  assert caught.value.exit_code == 4


def test_explicit_profile_save_and_clear_have_private_modes():
  result = preferences.update_preference("run_profiles.pi", "pi-pro")
  assert result.get("run_profiles.pi") == "pi-pro"
  assert config_path().stat().st_mode & 0o777 == 0o600
  assert config_path().parent.stat().st_mode & 0o777 == 0o700
  assert preferences.load_preferences().get("run_profiles.pi") == "pi-pro"
  result = preferences.update_preference("run_profiles.pi", None)
  assert result.get("run_profiles.pi") is None


@pytest.mark.parametrize("key,value", [
  ("schema_version", "1"),
  ("defaults.unknown", "workstation"),
  ("run_profiles.pi", "dsh-default"),
  ("run_profiles.omp", "missing-profile"),
  ("defaults.agent_machine", "missing-machine"),
  ("defaults.term_machine", "missing-machine"),
  ("defaults.work_machine", "missing-machine"),
])
def test_invalid_explicit_reference_does_not_create_preferences(key, value):
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.update_preference(key, value)
  assert caught.value.exit_code == 2
  assert not config_path().parent.exists()


@pytest.mark.parametrize("key,namespace", [
  ("defaults.agent_machine", "agent"),
  ("defaults.term_machine", "term"),
  ("defaults.work_machine", "work"),
])
def test_each_management_preference_validates_its_own_reference(key, namespace):
  write_machine(namespace, "workstation")
  assert preferences.update_preference(key, "workstation").get(key) == "workstation"


def test_term_machine_does_not_accept_agent_machine_file():
  write_machine("agent", "workstation")
  with pytest.raises(preferences.PreferenceError):
    preferences.update_preference("defaults.term_machine", "workstation")
  assert not config_path().exists()


def test_unset_can_remove_stale_reference_without_resolving_it():
  path = write_config('schema_version = 1\n[run_profiles]\npi = "missing-profile"\ndsh = "dsh-default"\n')
  result = preferences.update_preference("run_profiles.pi", None)
  assert result.get("run_profiles.pi") is None
  assert result.get("run_profiles.dsh") == "dsh-default"
  assert path.exists()


def test_save_detects_external_edit_before_locked_update(monkeypatch):
  path = write_config()
  external = 'schema_version = 1\n[run_profiles]\npi = "pi-base"\n'
  original = preferences._preference_lock

  @contextmanager
  def changed(tree):
    with original(tree):
      path.write_text(external)
      yield
  monkeypatch.setattr(preferences, "_preference_lock", changed)
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.update_preference("run_profiles.pi", "pi-pro")
  assert caught.value.exit_code == 4
  assert path.read_text() == external


def test_save_detects_external_edit_before_replace(monkeypatch):
  path = write_config()
  external = 'schema_version = 1\n[run_profiles]\npi = "pi-base"\n'
  original = Tree.replace

  def changed(tree, target, data, mode=0o600, *, expected):
    path.write_text(external)
    return original(tree, target, data, mode, expected=expected)
  monkeypatch.setattr(Tree, "replace", changed)
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.update_preference("run_profiles.pi", "pi-pro")
  assert caught.value.exit_code == 4
  assert path.read_text() == external


def test_write_failure_preserves_previous_bytes(monkeypatch):
  path = write_config()
  original = path.read_bytes()
  def failed(*args, **kwargs):
    raise OSError("synthetic-private-marker")
  monkeypatch.setattr(Tree, "replace", failed)
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.update_preference("run_profiles.pi", "pi-pro")
  assert caught.value.exit_code == 6
  assert "synthetic-private-marker" not in str(caught.value)
  assert path.read_bytes() == original


def test_invalid_xdg_is_not_expanded_or_repaired(monkeypatch):
  monkeypatch.setenv("XDG_CONFIG_HOME", "relative/$HOME")
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.load_preferences()
  assert caught.value.exit_code == 2


def test_reference_unsafe_file_is_ownership_conflict():
  target = write_machine("agent", "workstation")
  target.chmod(0o644)
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.update_preference("defaults.agent_machine", "workstation")
  assert caught.value.exit_code == 4
  assert not config_path().exists()


def test_lock_link_is_not_followed(tmp_path):
  path = write_config()
  outside = tmp_path / "outside-lock"
  outside.write_text("synthetic-lock-marker")
  outside.chmod(0o600)
  (path.parent / "preferences.lock").symlink_to(outside)
  with pytest.raises(preferences.PreferenceError) as caught:
    preferences.update_preference("run_profiles.pi", "pi-pro")
  assert caught.value.exit_code == 4
  assert outside.read_text() == "synthetic-lock-marker"


def test_preferences_lock_contention_does_not_write():
  path = write_config()
  before = path.read_bytes()
  with Tree(path.parent) as tree:
    with preferences._preference_lock(tree):
      with pytest.raises(preferences.PreferenceError) as caught:
        preferences.update_preference("run_profiles.pi", "pi-pro")
      assert caught.value.exit_code == 4
  assert path.read_bytes() == before

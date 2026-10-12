"""Shell 纯准备：假可执行文件、临时 HOME、默认进程和联网守卫。"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from agentcfg.pi_shell_preparation import prepare_shell
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


@pytest.fixture
def shell_case(tmp_path):
  project = tmp_path / "project"
  project.mkdir()
  executable = tmp_path / "fake-shell"
  executable.write_bytes(b"synthetic executable, never executed\n")
  executable.chmod(0o700)
  return {"command_ref": "tool:shell", "binding": {"executable": str(executable),
    "project_root": "project", "read_roots": ["project"], "write_roots": ["project"], "timeout_seconds": 30},
    "command": "printf '%s\\n' 'private shell marker' | cat > output\nvalue=$(cat output)\nprintf '%s' \"$value\"",
    "cwd": str(project), "policy_generation": 1,
    "declared_roots": {"project": {"path": str(project), "purpose": "project"}},
    "permission_policy": {"schema_version": 1, "default": "deny", "rules": [
      {"id": "allow-shell", "kind": "command", "effect": "allow", "command_ref": "tool:shell",
       "tool_ids": ["bash"], "operations": ["execute"]}]}}


def test_script_is_private_and_preserved_without_parsing(shell_case, tmp_path, sentinel_factory, monkeypatch):
  sentinel = sentinel_factory(tmp_path)
  def forbidden(*args, **kwargs):
    raise AssertionError("pure preparation must not write or allocate")
  from agentcfg.storage import Tree
  from agentcfg.activity import ExecutionStore
  monkeypatch.setattr(Tree, "write_immutable", forbidden)
  monkeypatch.setattr(ExecutionStore, "allocate", forbidden)
  value = prepare_shell(**shell_case)
  sentinel.assert_unchanged()
  assert value["private_input"] == {"command": shell_case["command"]}
  assert value["private_input"]["command"].encode() == shell_case["command"].encode()
  public = json.dumps({"resolution": value["resolution"], "physical": value["physical"]})
  assert "private shell marker" not in public
  assert hashlib.sha256(shell_case["command"].encode()).hexdigest() not in public
  resolved = value["resolution"]
  assert (resolved["kind"], resolved["tool_name"], resolved["backend"], resolved["network"], resolved["services"]) == (
    "shell-command", "bash", "linux-bwrap-v1", "deny", [])
  assert set(resolved["target"]) == {"command_ref", "executable", "timeout_ms"}
  assert resolved["workspace_keys"] == []
  assert resolved["policy"]["requires_human"] is True
  assert resolved["target"]["timeout_ms"] == 30000
  assert value["physical"]["executable_identity"] == resolved["target"]["executable"]
  other = prepare_shell(**{**shell_case, "command": "other private script"})
  assert other["resolution"] == resolved
  assert other["physical"] == value["physical"]


@pytest.mark.parametrize("command", ["", "a\0b", "\ud800", "界" * 21846, "a" * 65537, None],
  ids=["empty", "nul", "surrogate", "utf8-overflow", "ascii-overflow", "non-string"])
def test_invalid_script_is_rejected_without_body(shell_case, command):
  with pytest.raises(ConfigError, match="pi-shell-command") as caught:
    prepare_shell(**{**shell_case, "command": command})
  assert str(caught.value) == str(ConfigError("pi-shell-command"))


def test_utf8_byte_limit_and_multiline(shell_case):
  value = prepare_shell(**{**shell_case, "command": "界" * 21845 + "a"})
  assert len(value["private_input"]["command"].encode()) == 65536


@pytest.mark.parametrize("timeout", [0, -1, 31, True, 1.5, "1"])
def test_timeout_ceiling(shell_case, timeout):
  with pytest.raises(ConfigError): prepare_shell(**{**shell_case, "timeout_seconds": timeout})


def test_timeout_is_part_of_resolution(shell_case):
  value = prepare_shell(**{**shell_case, "timeout_seconds": 2})
  assert value["resolution"]["target"]["timeout_ms"] == 2000
  assert value["physical"]["timeout_seconds"] == 2


def test_unselected_readonly_ceiling_is_kept_for_physical_alias_checks(shell_case, tmp_path):
  protected = tmp_path / "readonly"
  protected.mkdir()
  shell_case["declared_roots"]["readonly"] = {"path": str(protected), "purpose": "read"}
  shell_case["permissions"] = {"readonly_roots": ["readonly"]}
  value = prepare_shell(**shell_case)
  assert value["physical"].get("readonly_paths") == [str(protected)]
  assert str(protected) not in value["physical"]["read_roots"]


@pytest.mark.parametrize("mutation", ["deny", "no-allow", "wrong-tool", "wrong-ref"])
def test_command_allow_required_and_deny_wins(shell_case, mutation):
  rules = shell_case["permission_policy"]["rules"]
  if mutation == "deny": rules.append({**rules[0], "id": "deny-shell", "effect": "deny"})
  elif mutation == "no-allow": rules.clear()
  elif mutation == "wrong-tool": rules[0]["tool_ids"] = ["read"]
  else: rules[0]["command_ref"] = "tool:other"
  with pytest.raises(Conflict, match="PERMISSION_DENIED"): prepare_shell(**shell_case)


@pytest.mark.parametrize("mutation", ["args", "env", "root-extra", "permission-extra", "policy-extra", "duplicate-rule", "unknown-root", "unknown-denied"])
def test_closed_shapes_and_references(shell_case, mutation):
  if mutation in ("args", "env"): shell_case["binding"][mutation] = [] if mutation == "args" else {}
  elif mutation == "root-extra": shell_case["declared_roots"]["project"]["extra"] = True
  elif mutation == "permission-extra": shell_case["permissions"] = {"extra": True}
  elif mutation == "policy-extra": shell_case["permission_policy"]["extra"] = True
  elif mutation == "duplicate-rule":
    shell_case["permission_policy"]["rules"].append({**shell_case["permission_policy"]["rules"][0], "effect": "deny"})
  elif mutation == "unknown-denied": shell_case["permissions"] = {"denied_roots": ["missing"]}
  else:
    shell_case["permission_policy"]["rules"].append(file_deny("missing", "."))
  with pytest.raises(ConfigError): prepare_shell(**shell_case)


def file_deny(root, relative):
  return {"id": "deny-file", "kind": "file", "effect": "deny", "root_ref": root,
    "relative_path": relative, "match": "subtree", "tool_ids": ["read"], "operations": ["read"]}


@pytest.mark.parametrize("permission", ["denied_roots", "readonly_roots"])
def test_denied_and_readonly_roots(shell_case, permission):
  shell_case["permissions"] = {permission: ["project"]}
  with pytest.raises(Conflict, match="PERMISSION_DENIED"): prepare_shell(**shell_case)


def test_readonly_descendant_overlaps_writer(shell_case):
  child = Path(shell_case["cwd"]) / "readonly"
  child.mkdir()
  shell_case["declared_roots"]["child"] = {"path": str(child), "purpose": "read"}
  shell_case["permissions"] = {"readonly_roots": ["child"]}
  with pytest.raises(Conflict, match="PERMISSION_DENIED"): prepare_shell(**shell_case)


def test_readonly_permission_allows_read_scope_and_policy_ref_is_bound(shell_case):
  shell_case["binding"]["write_roots"] = []
  shell_case["permissions"] = {"readonly_roots": ["project"], "policy_ref": "selected"}
  first = prepare_shell(**shell_case)
  assert first["resolution"]["write_roots"] == []
  shell_case["permissions"]["policy_ref"] = "other"
  second = prepare_shell(**shell_case)
  assert first["resolution"]["policy"]["ceiling_digest"] != second["resolution"]["policy"]["ceiling_digest"]


def test_protected_ancestor_denies_selected_root(shell_case, tmp_path):
  shell_case["protected_roots"] = [str(tmp_path)]
  with pytest.raises(Conflict, match="PERMISSION_DENIED"): prepare_shell(**shell_case)


def test_denial_symlink_does_not_follow_alias(shell_case, tmp_path):
  hidden = Path(shell_case["cwd"]) / "hidden"
  hidden.symlink_to(tmp_path)
  shell_case["permission_policy"]["rules"].append(file_deny("project", "hidden"))
  with pytest.raises(ConfigError, match="denial"): prepare_shell(**shell_case)


def test_unmounted_missing_protected_path_needs_no_placeholder(shell_case, tmp_path, sentinel_factory):
  absent = tmp_path / "unmounted-private"
  shell_case["protected_roots"] = [str(absent)]
  sentinel = sentinel_factory(tmp_path)
  assert str(absent) in prepare_shell(**shell_case)["physical"]["denied_paths"]
  sentinel.assert_unchanged()


@pytest.mark.parametrize("source", ["protected", "file", "git"])
def test_denials_project_to_existing_paths(shell_case, source):
  path = Path(shell_case["cwd"]) / (".git" if source == "git" else "hidden")
  path.mkdir()
  if source == "protected": shell_case["protected_roots"] = [str(path)]
  elif source == "file": shell_case["permission_policy"]["rules"].append(file_deny("project", "hidden"))
  value = prepare_shell(**shell_case)
  assert str(path) in value["physical"]["denied_paths"]


def test_unrelated_symlinks_are_not_scanned(shell_case, tmp_path):
  (Path(shell_case["cwd"]) / "unrelated").symlink_to(tmp_path)
  prepare_shell(**shell_case)


def test_missing_denial_does_not_create_placeholder(shell_case, sentinel_factory, tmp_path):
  shell_case["permission_policy"]["rules"].append(file_deny("project", "missing"))
  sentinel = sentinel_factory(tmp_path)
  with pytest.raises(ConfigError, match="denial"): prepare_shell(**shell_case)
  sentinel.assert_unchanged()


def test_git_symlink_rejected(shell_case, tmp_path):
  (Path(shell_case["cwd"]) / ".git").symlink_to(tmp_path)
  with pytest.raises(Conflict): prepare_shell(**shell_case)


@pytest.mark.parametrize("mutation", ["cwd-outside", "no-read-project", "bad-write-purpose", "root-symlink", "root-file", "root-alias", "filesystem-root", "home-root"])
def test_root_boundaries(shell_case, tmp_path, mutation):
  root = shell_case["declared_roots"]["project"]
  if mutation == "cwd-outside": shell_case["cwd"] = str(tmp_path)
  elif mutation == "no-read-project": shell_case["binding"]["read_roots"] = []
  elif mutation == "bad-write-purpose": root["purpose"] = "read"
  elif mutation == "root-symlink":
    alias = tmp_path / "alias"
    alias.symlink_to(shell_case["cwd"])
    root["path"] = str(alias)
  elif mutation == "root-file": root["path"] = shell_case["binding"]["executable"]
  elif mutation == "root-alias":
    shell_case["declared_roots"]["alias"] = deepcopy(root)
    shell_case["binding"]["read_roots"].append("alias")
  else:
    root["path"] = "/" if mutation == "filesystem-root" else os.environ["HOME"]
    shell_case["cwd"] = root["path"]
  with pytest.raises((ConfigError, Conflict)): prepare_shell(**shell_case)


@pytest.mark.parametrize("mutation", ["symlink", "directory", "writable", "setuid", "setgid", "non-executable", "relative"])
def test_executable_boundaries(shell_case, tmp_path, mutation):
  executable = Path(shell_case["binding"]["executable"])
  if mutation == "symlink":
    alias = tmp_path / "alias"
    alias.symlink_to(executable)
    shell_case["binding"]["executable"] = str(alias)
  elif mutation == "directory": shell_case["binding"]["executable"] = shell_case["cwd"]
  elif mutation == "relative": shell_case["binding"]["executable"] = "fake-shell"
  else: executable.chmod({"writable": 0o722, "setuid": 0o4700, "setgid": 0o2700, "non-executable": 0o600}[mutation])
  with pytest.raises((ConfigError, Conflict)): prepare_shell(**shell_case)


def test_replaced_root_and_executable_change_identity(shell_case, tmp_path):
  before = prepare_shell(**shell_case)
  root = Path(shell_case["cwd"])
  root.rename(tmp_path / "old-project")
  root.mkdir()
  after = prepare_shell(**shell_case)
  assert before["resolution"]["read_roots"] != after["resolution"]["read_roots"]
  executable = Path(shell_case["binding"]["executable"])
  executable.rename(tmp_path / "old-executable")
  executable.write_bytes(b"different synthetic executable\n")
  executable.chmod(0o700)
  latest = prepare_shell(**shell_case)
  assert after["resolution"]["target"]["executable"] != latest["resolution"]["target"]["executable"]


def test_root_replaced_during_preparation_is_rejected(shell_case, tmp_path, monkeypatch):
  import agentcfg.pi_shell_preparation as module
  original = module._executable
  def replace(path):
    identity = original(path)
    root = Path(shell_case["cwd"])
    root.rename(tmp_path / "old-project")
    root.mkdir()
    return identity
  monkeypatch.setattr(module, "_executable", replace)
  with pytest.raises(Conflict, match="ROOT_IDENTITY"): prepare_shell(**shell_case)


@pytest.mark.parametrize("constraint", ["readonly", "denied", "file"])
def test_reserved_project_ref_maps_to_selected_root(shell_case, constraint):
  shell_case["declared_roots"]["work"] = shell_case["declared_roots"].pop("project")
  shell_case["binding"].update(project_root="work", read_roots=["work"], write_roots=[])
  if constraint == "readonly":
    shell_case["permissions"] = {"readonly_roots": ["project"]}
    assert prepare_shell(**shell_case)["physical"]["read_roots"] == [shell_case["cwd"]]
  elif constraint == "denied":
    shell_case["permissions"] = {"denied_roots": ["project"]}
    with pytest.raises(Conflict, match="PERMISSION_DENIED"): prepare_shell(**shell_case)
  else:
    path = Path(shell_case["cwd"]) / "hidden"
    path.mkdir()
    shell_case["permission_policy"]["rules"].append(file_deny("project", "hidden"))
    assert str(path) in prepare_shell(**shell_case)["physical"]["denied_paths"]


def test_explicit_reserved_project_conflict_is_rejected(shell_case, tmp_path):
  shell_case["declared_roots"]["work"] = shell_case["declared_roots"].pop("project")
  shell_case["binding"].update(project_root="work", read_roots=["work"], write_roots=[])
  other = tmp_path / "other-project"
  other.mkdir()
  shell_case["declared_roots"]["project"] = {"path": str(other), "purpose": "project"}
  with pytest.raises(Conflict, match="SHELL_COMMAND_PROJECT_CONFLICT"): prepare_shell(**shell_case)


def test_explicit_reserved_project_same_identity_is_allowed(shell_case):
  shell_case["declared_roots"]["work"] = deepcopy(shell_case["declared_roots"]["project"])
  shell_case["binding"].update(project_root="work", read_roots=["work"], write_roots=[])
  shell_case["permissions"] = {"readonly_roots": ["project"]}
  assert prepare_shell(**shell_case)["physical"]["read_roots"] == [shell_case["cwd"]]

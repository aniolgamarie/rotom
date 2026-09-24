from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg.omp import OmpAdapter, validate_managed_argv, validate_model_selection
from agentcfg.omp_identity import native_identity
from agentcfg.paths import PathError
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree

from test_omp_adapter import REPO, omp_data
from test_omp_runtime_foundation import runtime_workspace


@pytest.mark.parametrize("profile", ["", "default", "../escape", "a/b"])
def test_invalid_or_reserved_native_profile_identity_is_rejected(profile, tmp_path):
  with pytest.raises(PathError):
    native_identity(profile, tmp_path / "instance")


def test_profile_rename_creates_new_identity_and_diagnostic_migration_hint(tmp_path):
  adapter = OmpAdapter(REPO)
  data = omp_data()
  workspace = type("Workspace", (), {"profile": "omp-validation", "instance": tmp_path / "one",
    "resolved": type("Resolved", (), {"data": data})()})()
  first = adapter.identity_diagnostics(workspace)
  data = deepcopy(data)
  data["profile"]["id"] = "omp-renamed"
  renamed = type("Workspace", (), {"profile": "omp-renamed", "instance": tmp_path / "two",
    "resolved": type("Resolved", (), {"data": data})()})()
  second = adapter.identity_diagnostics(renamed)
  assert first["native_name"] != second["native_name"]
  assert second["migration"] == "new-profile-relogin-required"


def test_full_hash_identity_is_kept_beyond_truncated_native_name(tmp_path, monkeypatch):
  class Digest:
    def __init__(self, value): self.value = value
    def hexdigest(self): return "a" * 24 + self.value.encode().hex().ljust(40, "0")[:40]
  monkeypatch.setattr(hashlib, "sha256", lambda value: Digest(value.decode()))
  one = native_identity("one", tmp_path / "one")
  two = native_identity("two", tmp_path / "two")
  assert one.native_name == two.native_name and one.profile_hash != two.profile_hash


def test_identity_diagnostics_reports_default_keybindings_digest_without_modifying_it(tmp_path):
  data = omp_data()
  workspace = type("Workspace", (), {"profile": "omp-validation", "instance": tmp_path / "instance",
    "resolved": type("Resolved", (), {"data": data})()})()
  default = workspace.instance / "user-home/.omp/agent/keybindings.yml"
  default.parent.mkdir(parents=True)
  default.write_text("app.history.search: Ctrl+F\n")
  before = default.read_bytes()
  report = OmpAdapter(REPO).identity_diagnostics(workspace)
  assert report["default_keybindings"] == {"path": str(default), "sha256": hashlib.sha256(before).hexdigest()}
  assert report["source_policy"]["project_resources"] is False
  assert report["project_sources_status"] == "not-inspected-without-launch-cwd"
  assert report["layout_conflict"] is None
  assert default.read_bytes() == before


def test_capture_projection_for_reads_only_selected_profile(tmp_path):
  workspace, _ = runtime_workspace(tmp_path)
  selected = native_identity(workspace.profile, workspace.instance)
  foreign = selected.home / ".omp/profiles/rotom-ffffffffffffffffffffffff/agent"
  foreign.mkdir(parents=True)
  (foreign / "config.yml").write_text("theme: {dark: foreign}\n")
  with Tree(workspace.instance) as tree:
    assert workspace.adapter.capture_projection_for(workspace, tree) == {}


@pytest.mark.parametrize("argv", [["--profile=other"], ["--profile", "other"], ["-c"],
  ["--api-key=x"], ["daemon"], ["--provider", "gateway", "--provider", "gateway"]])
def test_parser_rejections_are_profile_independent(argv):
  for profile in ("omp-alpha", "omp-beta"):
    data = omp_data()
    data["profile"]["id"] = profile
    with pytest.raises(ConfigError):
      validate_managed_argv(argv)
  validate_managed_argv(["--", "--profile=prompt-text", "daemon"])


def test_exact_model_selection_is_profile_independent():
  for profile in ("omp-alpha", "omp-beta"):
    data = omp_data()
    data["profile"]["id"] = profile
    validate_model_selection(data, ["--model", "gateway/large-v1"])
    with pytest.raises(ConfigError):
      validate_model_selection(data, ["--model", "large-v1"])


def test_xdg_alternate_profile_and_second_state_binding_are_rejected(tmp_path):
  workspace, _ = runtime_workspace(tmp_path)
  identity = native_identity(workspace.profile, workspace.instance)
  alternate = identity.xdg_config / "omp/profiles" / identity.native_name
  alternate.mkdir(parents=True)
  with pytest.raises(Conflict, match="XDG"):
    with workspace.adapter.lifecycle_guard(workspace):
      pass
  assert workspace.adapter.identity_diagnostics(workspace)["layout_conflict"] == "xdg-or-identity-layout-conflict"
  alternate.rmdir()
  saved = workspace.adapter.runtime_binding(workspace.resolved.data, workspace.instance)
  workspace.state_root = tmp_path / "other-state/omp/omp-test"
  with pytest.raises(Conflict, match="重新plan/apply"):
    workspace.adapter.validate_runtime_binding(workspace, saved)


def test_project_policy_root_change_requires_reapply(tmp_path):
  workspace, _ = runtime_workspace(tmp_path)
  saved = workspace.adapter.runtime_binding(workspace.resolved.data, workspace.instance)
  discovery = workspace.resolved.data["profile"]["agent_options"]["discovery"]
  discovery.update(project_resources=True, project_roots=[str(tmp_path / "project")])
  with pytest.raises(Conflict, match="重新plan/apply"):
    workspace.adapter.validate_runtime_binding(workspace, saved)

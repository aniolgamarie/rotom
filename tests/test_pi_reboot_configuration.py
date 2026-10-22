"""新 Pi 公共来源切换契约；仅校验合成配置，不启动宿主。"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from agentcfg.schema import ConfigError
from agentcfg.adapter import Ownership
from agentcfg import deployment
from agentcfg.workspace import load_public_catalog, load_workspace


REPOSITORY = Path(__file__).resolve().parents[1]
OLD_PROFILES = {"pi-default", "pi-managed", "pi-cursor", "pi-codex"}


def local(path, *, profile="pi-base", extra=""):
  path.write_text('schema_version=1\n[machine]\nid="reboot-test"\n'
    f'default_profile="{profile}"\n'
    '[overrides.providers.example]\nprotocol="openai-compatible"\n'
    'base_url="https://example.invalid/v1"\nauth_kind="api-key"\n'
    'credential_ref="secret:example_key"\n'
    '[overrides.models.example-main]\nprovider="example"\n'
    'remote_id="fictional-chat"\ninput=["text"]\n'
    f'[overrides.profiles.{profile}]\nproviders=["example"]\nmodels=["example-main"]\n'
    f'[overrides.profiles.{profile}.roles]\nmain="example-main"\n'
    + extra + '\n[secrets]\nexample_key="SYNTHETIC_REBOOT_SENTINEL"\n')
  return path


def test_complete_catalog_contains_new_profiles_and_retires_old_ids():
  catalog, adapters = load_public_catalog(repository=REPOSITORY)
  assert {"pi-base", "pi-pro"} <= set(catalog.profiles)
  assert not OLD_PROFILES & set(catalog.profiles)
  assert {"dsh", "pi", "omp"} == set(adapters)
  assert {"dsh-default", "omp-default"} <= set(catalog.profiles)


@pytest.mark.parametrize("profile", ["pi-base", "pi-pro"])
def test_base_and_pro_resolve_through_the_complete_public_catalog(tmp_path, profile):
  workspace = load_workspace(local(tmp_path / "local.toml", profile=profile), repository=REPOSITORY)
  options = workspace.resolved.data["profile"]["agent_options"]
  assert workspace.profile == profile
  assert workspace.agent == "pi"
  assert options["runtime"]["engine"] == "node"
  assert options["discovery"]["project_resources"] is False
  assert options["collaboration"]["enabled"] is False
  assert workspace.resolved.data["models"]["example-main"]["remote_id"] == "fictional-chat"


@pytest.mark.parametrize("retired", ["task_keeper", "model_delegate", "permissions"])
def test_retired_options_fail_even_when_explicitly_disabled(tmp_path, retired):
  catalog, _ = load_public_catalog(repository=REPOSITORY)
  assert "pi-base" in catalog.profiles
  extra = f'[overrides.profiles.pi-base.agent_options.{retired}]\nenabled=false\n'
  with pytest.raises(ConfigError):
    load_workspace(local(tmp_path / "local.toml", extra=extra), repository=REPOSITORY)


@pytest.mark.parametrize("profile", sorted(OLD_PROFILES))
def test_old_profile_ids_are_not_silently_routed(tmp_path, profile):
  catalog, _ = load_public_catalog(repository=REPOSITORY)
  assert "pi-base" in catalog.profiles
  with pytest.raises(ConfigError):
    load_workspace(local(tmp_path / "local.toml", profile=profile), repository=REPOSITORY)


def settings_fields(workspace):
  return {artifact.target.selector: (artifact.target, json.loads(artifact.content))
    for artifact in workspace.adapter.render(workspace.resolved.data)
    if artifact.target.path == "pi-home/settings.json"}


def test_render_is_pure_without_lock_or_installed_package_and_contains_no_old_platform(tmp_path):
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  candidate = workspace.candidate("synthetic-unlocked-config-check")
  assert candidate.artifacts
  assert not workspace.instance.exists()
  assert not workspace.adapter.requires_render_context
  paths = [artifact.target.path for artifact in candidate.artifacts]
  assert not any(word in path for path in paths for word in ("subagents", "runtime-api", "task-keeper", "codex-home"))
  assert not any(path.endswith("auth.json") for path in paths)
  assert all(b"SYNTHETIC_REBOOT_SENTINEL" not in artifact.content for artifact in candidate.artifacts)


def test_native_baseline_is_explicit_and_ui_is_initialized(tmp_path):
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  fields = settings_fields(workspace)
  expected = {"/defaultThinkingLevel": "medium", "/steeringMode": "one-at-a-time",
    "/followUpMode": "one-at-a-time", "/compaction/enabled": True,
    "/compaction/reserveTokens": 16384, "/compaction/keepRecentTokens": 20000,
    "/retry/enabled": True, "/retry/maxRetries": 3, "/retry/provider/maxRetries": 0,
    "/quietStartup": "header", "/tuiMode": "fullscreen", "/editorPaddingX": 0,
    "/outputPad": 1, "/autocompleteMaxVisible": 5, "/terminal/hyperlinks": "auto",
    "/terminal/images": "auto", "/terminal/trueColor": "auto", "/cacheWarming": "streaming",
    "/theme": "catppuccin-mocha"}
  for selector, expected_value in expected.items():
    assert fields[selector][1] == expected_value
  for selector in ("/theme", "/quietStartup", "/tuiMode", "/terminal/images"):
    assert fields[selector][0].ownership is Ownership.INITIALIZE


def test_empty_selection_and_false_settings_are_not_replaced_by_defaults(tmp_path):
  extra = ('[overrides.profiles.pi-base.agent_options.resources]\nprompts=[]\nextensions=[]\n'
    '[overrides.profiles.pi-base.agent_options.settings.compaction]\nenabled=false\n'
    '[overrides.profiles.pi-base.agent_options.settings.retry]\nenabled=false\n')
  workspace = load_workspace(local(tmp_path / "local.toml", extra=extra), repository=REPOSITORY)
  fields = settings_fields(workspace)
  assert fields["/compaction/enabled"][1] is False
  assert fields["/retry/enabled"][1] is False
  assert workspace.resolved.data["profile"]["agent_options"]["resources"]["prompts"] == []
  assert set(workspace.resolved.data["plugins"]) == {"pi-footer"}
  assert workspace.resolved.data["mcp"] == {}


def test_apply_preserves_existing_ui_preferences_and_unmanaged_fields(tmp_path):
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  settings = workspace.instance / "pi-home/settings.json"
  candidate = workspace.candidate("synthetic-config-lock")
  contract = {"shared_files": list(workspace.adapter.shared_files)}
  deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, contract)
  native = json.loads(settings.read_bytes())
  native.update(theme="catppuccin-latte", tuiMode="regular", unmanaged={"keep": True})
  settings.write_text(json.dumps(native))
  deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, contract)
  current = json.loads(settings.read_bytes())
  assert current["theme"] == "catppuccin-latte" and current["tuiMode"] == "regular"
  assert current["unmanaged"] == {"keep": True}


@pytest.mark.parametrize("option", ["collaboration", "unknown"])
def test_unready_collaboration_or_unknown_option_is_rejected(tmp_path, option):
  extra = f'[overrides.profiles.pi-base.agent_options.{option}]\nenabled=true\n'
  with pytest.raises(ConfigError):
    load_workspace(local(tmp_path / "local.toml", extra=extra), repository=REPOSITORY)


def test_base_and_pro_share_resources_but_own_separate_instances(tmp_path):
  first = load_workspace(local(tmp_path / "first.toml"), repository=REPOSITORY)
  second = load_workspace(local(tmp_path / "second.toml", profile="pi-pro"), repository=REPOSITORY)
  assert first.instance != second.instance and first.state_root != second.state_root
  assert first.resolved.data["profile"]["skills"] == second.resolved.data["profile"]["skills"]
  assert first.resolved.data["profile"]["agent_options"]["resources"] == second.resolved.data["profile"]["agent_options"]["resources"]
  assert first.resolved.data["adapter_documents"]["agent"]["resources"] == second.resolved.data["adapter_documents"]["agent"]["resources"]


def test_capture_returns_allowlisted_proposal_without_accepting_arbitrary_native_fields(tmp_path):
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  adapter = workspace.adapter
  before = deepcopy(workspace.resolved.data)
  proposal = adapter.capture_configuration({"theme": "catppuccin-latte"}, before)
  assert proposal == {"agent_options": {"ui": {"theme": "catppuccin-latte"}}}
  with pytest.raises(ConfigError):
    adapter.capture_configuration({"packages": ["npm:unmanaged"]}, before)
  assert workspace.resolved.data == before

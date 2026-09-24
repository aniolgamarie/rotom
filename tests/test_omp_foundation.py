import hashlib
from pathlib import Path

import pytest

from agentcfg.adapter import Artifact, ContractError, ManagedTarget, Ownership
from agentcfg.deployment import desired_items
from agentcfg.native_projection import reference_guard, validate_item_guard, validate_projection
from agentcfg.native_projection import validate_change
from agentcfg.omp_identity import native_identity, validate_layout
from agentcfg.storage import Conflict
from agentcfg.workspace import load_workspace
from agentcfg.schema import ConfigError, _read_schema
from agentcfg.render import RenderCandidate
from agentcfg.omp_env import generated_name, is_generated_name


def test_native_identity_is_stable_and_isolated(tmp_path):
  identity = native_identity("omp-default", tmp_path / "instances/omp/omp-default")
  digest = hashlib.sha256(b"omp-default").hexdigest()
  assert identity.native_name == "rotom-" + digest[:24]
  assert identity.profile_hash == digest
  assert identity.home == tmp_path / "instances/omp/omp-default/user-home"
  assert identity.agent_dir == identity.home / ".omp/profiles" / identity.native_name / "agent"
  assert ".omp/profiles" not in str(identity.xdg_config)


@pytest.mark.parametrize("profile", ["", ".", "..", "a/b", "a\\b"])
def test_native_identity_rejects_unsafe_profile(profile, tmp_path):
  with pytest.raises(Exception):
    native_identity(profile, tmp_path)


@pytest.mark.parametrize("kind", ["xdg_config", "xdg_data", "xdg_cache", "xdg_state"])
def test_xdg_profile_redirect_layout_is_a_conflict(tmp_path, kind):
  identity = native_identity("omp-default", tmp_path / "instance")
  redirected = getattr(identity, kind) / "omp/profiles" / identity.native_name
  redirected.mkdir(parents=True)
  with pytest.raises(Conflict):
    validate_layout(identity)


def test_versioned_omp_guard_and_legacy_guard_are_distinct():
  omp = reference_guard(("AGENTCFG_OMP_PROVIDER_0123456789ABCDEF01234567_KEY",))
  legacy = reference_guard(("$API_KEY",))
  assert omp["kind"] == "omp-env-name"
  assert legacy["kind"] == "environment-reference"
  validate_projection({"present": True, "value": "AGENTCFG_OMP_PROVIDER_0123456789ABCDEF01234567_KEY"}, omp)
  with pytest.raises(Conflict):
    validate_projection({"present": True, "value": "$API_KEY"}, omp)


def test_managed_target_accepts_only_registered_bare_omp_env():
  ManagedTarget("a.json", Ownership.FIELDS, "json", "/secret", ("AGENTCFG_OMP_PROVIDER_0123456789ABCDEF01234567_KEY",))
  with pytest.raises(ContractError):
    ManagedTarget("a.json", Ownership.FIELDS, "json", "/secret", ("OMP_KEY",))


def test_omp_historical_secret_leaf_cannot_lose_guard():
  change = {"item": {"path": "user-home/.omp/profiles/rotom-x/agent/models.yml", "selector": "/providers/x/apiKey"},
            "before": {"present": True, "value": "AGENTCFG_OMP_PROVIDER_0123456789ABCDEF01234567_KEY"}, "after": {"present": False}}
  with pytest.raises(Conflict):
    validate_change(change)


def test_omp_bare_guard_is_rejected_outside_classified_secret_leaf():
  item = {"path": "arbitrary.json", "selector": "/value",
          "guard": reference_guard(("AGENTCFG_OMP_MCP_0123456789ABCDEF01234567_ENV",))}
  with pytest.raises(Conflict):
    validate_item_guard(item, {"present": True, "value": "AGENTCFG_OMP_MCP_0123456789ABCDEF01234567_ENV"})


def test_omp_and_pi_secret_leaf_reject_forged_guard_kind():
  omp_item = {"path": "user-home/.omp/profiles/rotom-x/agent/models.yml", "selector": "/providers/x/apiKey",
              "guard": reference_guard(("$KEY",))}
  with pytest.raises(Conflict, match="omp-env-name"):
    validate_item_guard(omp_item, {"present": True, "value": "$KEY"})
  pi_item = {"path": "pi-home/models.json", "selector": "/providers/x/apiKey",
             "guard": reference_guard(("AGENTCFG_OMP_PROVIDER_0123456789ABCDEF01234567_KEY",))}
  with pytest.raises(Conflict, match="environment-reference"):
    validate_item_guard(pi_item, {"present": True, "value": "AGENTCFG_OMP_PROVIDER_0123456789ABCDEF01234567_KEY"})


def test_generated_omp_environment_names_have_contract_suffix_and_collision_guard(monkeypatch):
  claimed = {}
  provider = generated_name("provider", "openai-compatible", "key", claimed=claimed)
  mcp_env = generated_name("mcp", "echo", "env:SERVICE_TOKEN", claimed=claimed)
  mcp_header = generated_name("mcp", "echo", "header:Authorization", claimed=claimed)
  assert provider.endswith("_KEY") and mcp_env.endswith("_ENV") and mcp_header.endswith("_HEADER")
  assert all(is_generated_name(value) for value in (provider, mcp_env, mcp_header))
  monkeypatch.setattr("agentcfg.omp_env.hashlib.sha256", lambda value: type("Digest", (), {"hexdigest": lambda self: "a" * 64})())
  collision_claims = {}
  generated_name("provider", "one", "key", claimed=collision_claims)
  with pytest.raises(ConfigError, match="collision"):
    generated_name("provider", "two", "key", claimed=collision_claims)


def test_omp_mcp_env_leaf_requires_guard_even_when_intent_omits_tokens():
  target = ManagedTarget("user-home/.omp/profiles/rotom-x/agent/mcp.json", Ownership.FIELDS,
    "json", "/mcpServers/echo/env/SERVICE_TOKEN")
  with pytest.raises(Conflict):
    desired_items(RenderCandidate("generation", (Artifact(target, b'"literal-secret"'),)))


def omp_local(path, extra=""):
  path.write_text('schema_version=1\n[machine]\nid="omp-test"\ndefault_profile="omp-default"\n' + extra)


def test_empty_bootstrap_loads_and_renders_only_protected_settings(tmp_path):
  local = tmp_path / "local.toml"
  omp_local(local)
  workspace = load_workspace(local)
  candidate = workspace.candidate("a" * 64)
  assert workspace.agent == "omp"
  assert len(candidate.artifacts) == 8
  assert all(artifact.target.path.startswith("user-home/.omp/profiles/rotom-") for artifact in candidate.artifacts)
  assert {artifact.target.selector for artifact in candidate.artifacts} == {
    "/skills/enablePiUser", "/skills/enablePiProject", "/mcp/enableProjectConfig", "/enabledProviders",
    "/disabledProviders", "/startup/checkUpdate", "/marketplace/autoUpdate", "/autolearn/enabled"}


def test_omp_profile_options_reject_unknown_fields(tmp_path):
  local = tmp_path / "local.toml"
  omp_local(local, '[overrides.profiles.omp-default.agent_options]\nraw_native=true\n')
  with pytest.raises(Exception):
    load_workspace(local)


def test_keybinding_schema_preserves_string_and_empty_array(tmp_path):
  local = tmp_path / "local.toml"
  omp_local(local, '[overrides.profiles.omp-default.agent_options.ui]\n'
    '[overrides.profiles.omp-default.agent_options.ui.keybindings]\n'
    '"app.model.cycleForward"="Ctrl+P"\n"app.history.search"=[]\n')
  workspace = load_workspace(local)
  values = workspace.resolved.data["profile"]["agent_options"]["ui"]["keybindings"]
  assert values == {"app.model.cycleForward": "Ctrl+P", "app.history.search": []}


def test_checked_in_omp_schemas_use_supported_strict_subset():
  agent = _read_schema("omp-agent")
  assert agent["additionalProperties"] is False
  resources = agent["$defs"]["profile"]["properties"]["agent_options"]["properties"]["resources"]["properties"]
  assert set(resources) == {"prompts", "themes"}
  native = _read_schema("omp-native")
  assert len(native["oneOf"]) == 8
  assert native["$defs"]["keybindings"]["properties"]["path"]["const"] == "keybindings.yml"

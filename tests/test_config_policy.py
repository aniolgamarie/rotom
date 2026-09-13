"""CFG-03：机器字面语义、明确凭据通道与认证拥有者。"""

from dataclasses import replace
import os
from pathlib import Path

import pytest

from agentcfg import schema
from test_config_resolution import PRIVATE, resolution_inputs, resolve


@pytest.mark.parametrize("xdg", [True, False])
def test_path_defaults_use_xdg_or_home_only_when_missing(tmp_path, monkeypatch, xdg):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  if not xdg:
    for name in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
      monkeypatch.delenv(name)
  result = resolve(catalog, local)
  home = Path(os.environ["HOME"])
  assert result.data["machine"]["paths"] == {
    "instances_root": str((home / "data" if xdg else home / ".local/share") / "agentcfg/instances"),
    "state_root": str((home / "state" if xdg else home / ".local/state") / "agentcfg"),
    "cache_root": str((home / "cache" if xdg else home / ".cache") / "agentcfg"),
  }
  assert result.provenance[("machine", "paths", "state_root")] == "defaults"


@pytest.mark.parametrize("value", ["/自定义 磁盘/实例", "~/中文 路径/实例"])
def test_configured_paths_are_literal_and_do_not_require_existing_directory(tmp_path, value):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  local.data["machine"]["paths"] = {"instances_root": value}
  result = resolve(catalog, local)
  expected = value.replace("~/", os.environ["HOME"] + "/", 1) if value.startswith("~/") else value
  assert result.data["machine"]["paths"]["instances_root"] == expected
  assert result.provenance[("machine", "paths", "instances_root")] == "local"


@pytest.mark.parametrize("value", ["", "relative/path", "~someone/path", "~", "$HOME/path", "/$(cmd)", "/`cmd`", "/a/../b"])
def test_invalid_configured_paths_never_fall_back(tmp_path, value):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  local.data["machine"]["paths"] = {"state_root": value}
  with pytest.raises(schema.ConfigError):
    resolve(catalog, local)


def test_empty_xdg_is_not_an_implicit_default(tmp_path, monkeypatch):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  monkeypatch.setenv("XDG_DATA_HOME", "")
  with pytest.raises(schema.ConfigError):
    resolve(catalog, local)
  local.data["machine"]["paths"] = {"instances_root": "/explicit/instances"}
  assert resolve(catalog, local).data["machine"]["paths"]["instances_root"] == "/explicit/instances"


@pytest.mark.parametrize("value", ["nvim", "nonexistent-editor", "/Applications/编辑器 App/editor", "~/工具 空格/editor"])
def test_editor_is_single_literal_argv_zero_without_existence_check(tmp_path, value):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  local.data["machine"]["editor"] = value
  result = resolve(catalog, local)
  expected = value.replace("~/", os.environ["HOME"] + "/", 1) if value.startswith("~/") else value
  assert result.data["machine"]["editor"] == expected


@pytest.mark.parametrize("value", ["", "nvim -f", "env EDITOR=x nvim", "nvim;cmd", "nvim|cmd", "./nvim", "~user/nvim", "$EDITOR", "$(cmd)", "`cmd`", "/apps/${EDITOR}", "nvim\ncmd"])
def test_editor_rejects_bare_command_arguments_and_interpolation(tmp_path, value):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  local.data["machine"]["editor"] = value
  with pytest.raises(schema.ConfigError):
    resolve(catalog, local)


@pytest.mark.parametrize("channel", ["inherit", "values"])
@pytest.mark.parametrize("name", ["HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR", "FIXTURE_KEY", "LC_*", "9INVALID", "HAS-DASH", "BAD\n", PRIVATE])
def test_environment_rejects_reserved_controls_credentials_and_invalid_names(tmp_path, channel, name):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  local.data["machine"]["environment"] = {channel: [name] if channel == "inherit" else {name: "value"}}
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local)
  assert PRIVATE not in repr(caught.value)


def test_environment_accepts_explicit_nonsecret_literals_without_parent_inheritance(tmp_path, monkeypatch):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  monkeypatch.setenv("PRIVATE_PARENT_SECRET", "must-not-be-in-resolved-config")
  local.data["machine"]["environment"] = {"inherit": ["CUSTOM_PUBLIC", "LANG"],
    "values": {"LANG": "中文 UTF-8", "EMPTY": "", "LITERAL": "$(not-executed)`literal`"}}
  result = resolve(catalog, local)
  assert result.data["machine"]["environment"] == local.data["machine"]["environment"]
  assert "must-not-be-in-resolved-config" not in str(result.data)


@pytest.mark.parametrize("value", ["secret:key", "https://user:password@example.invalid/path", "https://example.invalid/?api_key=private", "x\0y", 4])
def test_environment_value_credential_channels_are_rejected(tmp_path, value):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  local.data["machine"]["environment"] = {"values": {"PUBLIC": value}}
  with pytest.raises(schema.ConfigError):
    resolve(catalog, local)


@pytest.mark.parametrize("name", ["API_KEY", "ACCESS_TOKEN", "PASSWORD", "AUTHORIZATION"])
@pytest.mark.parametrize("channel", ["inherit", "values"])
def test_explicit_credential_field_names_are_not_generic_environment_channels(tmp_path, name, channel):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  local.data["machine"]["environment"] = {channel: [name] if channel == "inherit" else {name: "opaque"}}
  with pytest.raises(schema.ConfigError):
    resolve(catalog, local)


@pytest.mark.parametrize("kind,field", [("providers", "base_url"), ("mcp", "url")])
@pytest.mark.parametrize("url", ["https://user:password@example.invalid", "https://example.invalid/?access_token=private"])
def test_entity_urls_cannot_smuggle_credentials_even_unselected(tmp_path, kind, field, url):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  entity = "public" if kind == "providers" else "first"
  catalog.registry[kind][entity][field] = url
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local)
  assert "password" not in repr(caught.value) and "example.invalid" not in repr(caught.value)


@pytest.mark.parametrize("claims", [(("public", "first"), ("public", "second")),
                                   (("public", "first"), ("public", "first")),
                                   ((PRIVATE, "first"),), (("public", ""),),
                                   (("public", "../owner"),), ()])
def test_explicit_normalized_authentication_claims_require_one_owner_per_selected_provider(tmp_path, claims):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  bundle = catalog.adapter_schemas.bundles["fixture-json"]
  catalog.adapter_schemas.bundles["fixture-json"] = replace(bundle, authentication_claims=lambda data: tuple(
    schema.AuthenticationClaim(provider, owner) for provider, owner in claims))
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local)
  assert caught.value.code == "authentication-owner"
  assert PRIVATE not in repr(caught.value)


def test_authentication_owner_comes_from_adapter_mapping_not_provider_name(tmp_path):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  catalog.adapter_documents["fixture-json"]["bindings"]["owner"] = "arbitrary-auth-implementation"
  assert list(resolve(catalog, local).data["providers"]) == ["public"]


@pytest.mark.parametrize("missing", ["policy", "authentication_claims"])
def test_incomplete_adapter_resolution_contract_fails_honestly(tmp_path, missing):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  bundle = catalog.adapter_schemas.bundles["fixture-json"]
  catalog.adapter_schemas.bundles["fixture-json"] = replace(bundle, **{missing: None})
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local)
  assert caught.value.code == "adapter"

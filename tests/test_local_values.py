"""provider 私人 URL 引用：纯配置解析与候选拒绝，不启动第三方宿主。"""

from copy import deepcopy
from pathlib import Path

import pytest

from agentcfg.config import (AdapterSources, LocalConfig, SourceInputs, load_sources,
                             public_diagnostics, resolve_config)
from agentcfg.dsh import DshAdapter
from agentcfg.local_values import validate_local_url
from agentcfg.omp import OmpAdapter
from agentcfg.pi import PiAdapter
from agentcfg.render import RenderError, render_candidate
from agentcfg.schema import AdapterSchemas, ConfigError, validate_document


REPO = Path(__file__).resolve().parents[1]


def catalog_and_adapters():
  adapters = {"dsh": DshAdapter(REPO), "pi": PiAdapter(REPO), "omp": OmpAdapter(REPO)}
  schemas = AdapterSchemas({name: adapter.schemas().bundles[name]
                            for name, adapter in adapters.items()})
  registries = tuple(sorted((REPO / "shared").glob("*.toml")))
  for name in adapters:
    content = REPO / "agents" / name / "content.toml"
    if content.exists():
      registries += (content,)
  sources = SourceInputs(registries, tuple(sorted((REPO / "profiles").glob("*.toml"))), {
    name: AdapterSources(*(REPO / "agents" / name / f"{kind}.toml"
      for kind in ("agent", "bindings", "plugins"))) for name in adapters},
    REPO / "shared/defaults/models.toml")
  return load_sources(sources, adapter_schemas=schemas), adapters


def local(values=None, overrides=None):
  result = {"schema_version": 1, "machine": {"id": "local-url-test"}}
  if values is not None:
    result["local_values"] = values
  if overrides is not None:
    result["overrides"] = overrides
  return LocalConfig(result)


def referenced_catalog(provider_id="deepseek_openai", local_name="private_url"):
  loaded, adapters = catalog_and_adapters()
  providers = deepcopy(loaded.registry["providers"])
  providers[provider_id].pop("base_url", None)
  providers[provider_id]["base_url_ref"] = "local:" + local_name
  loaded = type(loaded)({**loaded.registry, "providers": providers}, loaded.profiles,
    loaded.adapter_documents, loaded.adapter_schemas, loaded.model_defaults)
  return loaded, adapters


@pytest.mark.parametrize("value", [
  "https://gateway.example.invalid/v1",
  "http://127.0.0.1:8080/v1?mode=test",
])
def test_validate_local_url_accepts_absolute_http_urls(value):
  assert validate_local_url(value) == value


@pytest.mark.parametrize("value", [
  "", "ftp://gateway.example.invalid", "/v1", "https://user@gateway.example.invalid/v1",
  "https://gateway.example.invalid/v1?api_key=private-canary",
  "https://gateway.example.invalid/bad path", "https://gateway.example.invalid\\evil",
  "https://gateway.example.invalid/v1#fragment", "https://gateway.example.invalid:99999/v1",
])
def test_validate_local_url_rejects_ambiguous_or_credential_urls_without_leak(value):
  with pytest.raises(ConfigError) as caught:
    validate_local_url(value)
  if value:
    assert value not in repr(caught.value)
    assert value not in str(caught.value)


def test_local_schema_is_closed_and_provider_endpoint_forms_are_mutually_exclusive():
  validate_document("local", {"schema_version": 1, "machine": {"id": "fixture"},
    "local_values": {"private_url": ""}})
  with pytest.raises(ConfigError):
    validate_document("local", {"schema_version": 1, "machine": {"id": "fixture"},
      "unknown": {}})
  with pytest.raises(ConfigError):
    validate_document("local", {"schema_version": 1, "machine": {"id": "fixture"},
      "overrides": {"providers": {"gateway": {
        "base_url": "https://literal.example.invalid/v1", "base_url_ref": "local:private_url"}}}})


def test_selected_missing_ref_is_strict_but_diagnostic_mode_returns_only_metadata():
  loaded, adapters = referenced_catalog()
  with pytest.raises(ConfigError) as caught:
    resolve_config(loaded, local({"private_url": ""}), profile_id="dsh-default",
      adapter_schemas=loaded.adapter_schemas)
  assert caught.value.code == "local-value"

  resolved = resolve_config(loaded, local({"private_url": ""}), profile_id="dsh-default",
    adapter_schemas=loaded.adapter_schemas, allow_missing_local_values=True)
  assert resolved.local_value_refs == (("deepseek_openai", "private_url"),)
  assert resolved.missing_local_values == resolved.local_value_refs
  assert "local_values" not in resolved.data
  assert "base_url_ref" not in resolved.data["providers"]["deepseek_openai"]
  assert "base_url" not in resolved.data["providers"]["deepseek_openai"]
  assert "private_url" not in repr(resolved)
  with pytest.raises(RenderError):
    render_candidate(resolved, adapter=adapters["dsh"],
      adapter_schemas=loaded.adapter_schemas, lock_identity="a" * 64)


def test_unselected_profile_missing_refs_do_not_block_selected_profile():
  loaded, _ = catalog_and_adapters()
  resolved = resolve_config(loaded, local({"tf_openai_url": "", "tf_anthropic_url": "",
    "unrelated_private_value": "ordinary private text"}),
    profile_id="dsh-default", adapter_schemas=loaded.adapter_schemas)
  assert resolved.data["profile"]["agent"] == "dsh"
  assert resolved.missing_local_values == ()


def test_local_provider_endpoint_override_replaces_inherited_other_form():
  loaded, _ = referenced_catalog()
  literal = "https://literal.example.invalid/v1"
  resolved = resolve_config(loaded, local(overrides={"providers": {
    "deepseek_openai": {"base_url": literal}}}), profile_id="dsh-default",
    adapter_schemas=loaded.adapter_schemas)
  assert resolved.data["providers"]["deepseek_openai"]["base_url"] == literal
  assert resolved.local_value_refs == ()

  loaded, _ = catalog_and_adapters()
  resolved = resolve_config(loaded, local({"private_url": "https://private.example.invalid/v1"},
    {"providers": {"deepseek_openai": {"base_url_ref": "local:private_url"}}}),
    profile_id="dsh-default", adapter_schemas=loaded.adapter_schemas)
  assert resolved.local_value_refs == (("deepseek_openai", "private_url"),)
  assert resolved.missing_local_values == ()
  assert resolved.data["providers"]["deepseek_openai"]["base_url"].startswith("https://private.")


@pytest.mark.parametrize("profile,provider", [
  ("dsh-default", "deepseek_openai"),
  ("pi-default", "deepseek_openai"),
  ("omp-default", "deepseek_anthropic"),
])
def test_all_adapters_resolve_materialized_private_url(profile, provider):
  loaded, _ = referenced_catalog(provider)
  url = "https://adapter.example.invalid/v1"
  resolved = resolve_config(loaded, local({"private_url": url}), profile_id=profile,
    adapter_schemas=loaded.adapter_schemas)
  assert resolved.data["providers"][provider]["base_url"] == url
  assert resolved.provenance[("providers", provider, "base_url")] == "local"
  assert url not in repr(public_diagnostics(resolved))
  assert "private_url" not in repr(public_diagnostics(resolved))
  assert resolved.local_value_refs == ((provider, "private_url"),)
  assert resolved.missing_local_values == ()

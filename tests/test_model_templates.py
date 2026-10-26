"""单层公共模型规格：严格引用、显式覆盖与路线凭据/计价隔离。"""

from copy import deepcopy
from pathlib import Path
import tomllib

import pytest

from agentcfg.config import SourceInputs, load_sources
from agentcfg.model_templates import materialize_models
from agentcfg.schema import AdapterSchemas, ConfigError, validate_document


REPO = Path(__file__).resolve().parents[1]
CORE = {"remote_id": "model", "input": ["text"], "context_window": 1000,
        "max_output_tokens": 100, "source": "https://spec.example.invalid/model",
        "reasoning": True, "notes": "client cap only"}


def registry():
  return {"model_templates": {"core": deepcopy(CORE)}, "models": {
    "official": {"template": "core", "provider": "official"},
    "gateway": {"template": "core", "provider": "gateway", "context_window": 500,
      "native": {"pi": {"compat": {"thinkingFormat": "openai"}}}},
  }}


def test_materialization_is_pure_and_overrides_are_explicit():
  raw = registry()
  original = deepcopy(raw)
  full = materialize_models(raw)
  assert raw == original
  assert "model_templates" not in full
  assert full["models"]["official"] == {key: value for key, value in CORE.items() if key != "notes"} | {"provider": "official"}
  assert full["models"]["gateway"]["context_window"] == 500
  assert full["models"]["gateway"]["native"] == {"pi": {"compat": {"thinkingFormat": "openai"}}}
  assert "native" not in full["models"]["official"]
  assert all("template" not in item and "notes" not in item for item in full["models"].values())


@pytest.mark.parametrize("kind,field,value", [
  ("template", "provider", "forbidden"), ("template", "template", "recursive"),
  ("template", "native", {}), ("template", "pricing", {}),
  ("template", "base_url", "https://example.invalid"), ("template", "auth_kind", "api-key"),
  ("template", "key", "PRIVATE-CANARY"), ("template", "context_windows", 10),
  ("binding", "templates", "core"), ("binding", "notes", "not binding metadata"),
  ("binding", "native", {"omp": {"thinking": {"requiresEfforts": True}}}),
  ("binding", "native", {"omp": {"thinking": {"requiresEffort": "true"}}}),
])
def test_template_and_binding_unknown_fields_fail_safely(kind, field, value):
  raw = registry()
  item = raw["model_templates"]["core"] if kind == "template" else raw["models"]["official"]
  item[field] = value
  with pytest.raises(ConfigError) as error:
    materialize_models(raw)
  assert "PRIVATE-CANARY" not in str(error.value)


def test_missing_template_and_incomplete_materialized_model_fail():
  raw = registry()
  raw["models"]["official"]["template"] = "missing"
  with pytest.raises(ConfigError) as error:
    materialize_models(raw)
  assert error.value.code == "reference"
  raw = registry()
  del raw["model_templates"]["core"]["remote_id"]
  with pytest.raises(ConfigError):
    materialize_models(raw)


def test_load_sources_supports_forward_reference_and_rejects_duplicate_template(tmp_path):
  binding = tmp_path / "bindings.toml"
  binding.write_text('schema_version = 1\n[models.route]\ntemplate = "core"\nprovider = "provider"\n')
  template = tmp_path / "core.toml"
  template.write_text('schema_version = 1\n[model_templates.core]\nremote_id = "model"\ninput = ["text"]\ncontext_window = 1000\nmax_output_tokens = 100\nsource = "https://spec.example.invalid/model"\n')
  result = load_sources(SourceInputs(registries=(binding, template)), adapter_schemas=AdapterSchemas())
  assert result.registry["models"]["route"] == {"provider": "provider", "remote_id": "model", "input": ["text"],
    "context_window": 1000, "max_output_tokens": 100, "source": "https://spec.example.invalid/model"}
  with pytest.raises(ConfigError) as error:
    load_sources(SourceInputs(registries=(template, template)), adapter_schemas=AdapterSchemas())
  assert error.value.code == "duplicate"


def test_private_model_overrides_cannot_introduce_template_controls():
  for override in ({"template": "core"}, {"notes": "control"}):
    with pytest.raises(ConfigError):
      validate_document("local", {"schema_version": 1, "machine": {"id": "fixture"},
        "overrides": {"models": {"model": override}}})


def test_public_protocol_and_gateway_bindings_share_core_with_isolated_billing():
  raw = tomllib.loads((REPO / "shared/model-templates.toml").read_text())
  templates = raw["model_templates"]
  assert len(templates) == 13
  documents = [REPO / name for name in ("shared/model-templates.toml", "shared/providers.toml",
    "shared/models.toml", "agents/omp/content.toml")]
  catalog = load_sources(SourceInputs(registries=tuple(documents)), adapter_schemas=AdapterSchemas())
  models = catalog.registry["models"]
  assert len(models) == 33
  # 新增两种 K3.1 核心规格，分别绑定两种公开协议及独立网关路线。
  for template_id, remote_id, suffix in (
    ("kimi_k31_pro", "k3.1-pro", "k31_pro"),
    ("kimi_k31_pro_highspeed", "k3.1-pro-highspeed", "k31_pro_highspeed"),
  ):
    assert templates[template_id]["remote_id"] == remote_id
    for protocol in ("openai", "anthropic"):
      model = models["kimi_code_" + suffix + "_" + protocol]
      assert model["provider"] == "kimi_code_" + protocol
      assert model["remote_id"] == remote_id
    gateway = models["omp-kimi_tf-" + remote_id]
    assert gateway["provider"] == "kimi_tf"
    assert gateway["remote_id"] == remote_id
  for template_id, core in templates.items():
    matches = [item for item in models.values() if item["remote_id"] == core["remote_id"]]
    assert matches
    for item in matches:
      assert {key: item[key] for key in core if key != "notes"} == {key: value for key, value in core.items() if key != "notes"}
      if item["provider"].endswith("_tf") or not item["provider"].startswith("deepseek_"):
        assert "pricing" not in item
  for suffix in ("openai", "anthropic"):
    assert models["deepseek_flash_" + suffix]["pricing"]["standard"] == {"input": .30, "output": 1.20, "cache_read": .006}
    assert models["deepseek_pro_" + suffix]["pricing"]["standard"] == {"input": 1.32, "output": 3.96, "cache_read": .044}
    assert models["deepseek_pro_" + suffix]["pricing"]["checked_on"] == "2026-10-06"
  tf = catalog.registry["providers"]["deepseek_tf"]
  assert tf["base_url_ref"] == "local:tf_openai_url"
  assert tf["credential_ref"] == "secret:omp_deepseek_tf_key"


def test_toml_disabled_level_control_is_explicitly_normalized(tmp_path):
  path = tmp_path / "models.toml"
  path.write_text('schema_version = 1\n[models.model]\nprovider = "provider"\nremote_id = "model"\ninput = ["text"]\n[models.model.native.pi]\ndisabled_thinking_levels = ["off"]\n')
  catalog = load_sources(SourceInputs(registries=(path,)), adapter_schemas=AdapterSchemas())
  assert catalog.registry["models"]["model"]["native"]["pi"] == {"thinkingLevelMap": {"off": None}}


@pytest.mark.parametrize("pi", [
  {"disabled_thinking_levels": ["low"]},
  {"disabled_thinking_levels": ["off", "off"]},
  {"disabledThinkingLevels": ["off"]},
  {"disabled_thinking_levels": ["off"], "thinkingLevelMap": {"off": None}},
])
def test_disabled_levels_reject_unknown_duplicate_and_conflicting_declarations(pi):
  raw = registry()
  raw["models"]["official"]["native"] = {"pi": pi}
  with pytest.raises(ConfigError):
    materialize_models(raw)


def test_unreferenced_incomplete_template_is_rejected():
  raw = registry()
  raw["model_templates"]["unused"] = {"remote_id": "unused", "input": ["text"]}
  with pytest.raises(ConfigError) as error:
    materialize_models(raw)
  assert error.value.code == "schema"

"""TF 目录与共享引用的离线验收；只读取虚构临时机器/密钥。"""

import json
from pathlib import Path
import tomllib

import pytest

from agentcfg.adapter import SecretRef
from agentcfg.dependencies import read_lock
from agentcfg.schema import ConfigError
from agentcfg.workspace import load_workspace


ROOT = Path(__file__).resolve().parents[1]
CANARY = "SYNTHETIC-TF-KEY-CANARY"


def tf_machine(tmp_path, *, keys=False):
  document = (ROOT / "examples/dsh-tf.local.toml").read_text()
  secret = tmp_path / "shared-keys.toml"
  document = document.replace('"~/.config/agentcfg/secrets.toml"', json.dumps(str(secret)))
  document = document.replace('tf_openai_url = ""', 'tf_openai_url = "https://fixture.invalid/v1"')
  document = document.replace('tf_anthropic_url = ""', 'tf_anthropic_url = "https://fixture.invalid/anthropic"')
  local = tmp_path / "machine.toml"
  local.write_text(document)
  local.chmod(0o600)
  if keys:
    secret.write_text('schema_version = 1\n[providers.kimi_tf]\nomp_kimi_tf_key = "' + CANARY + '"\n')
    secret.chmod(0o600)
  return local


def test_tf_catalog_uses_existing_provider_key_and_url_refs_without_changing_main(tmp_path):
  workspace = load_workspace(tf_machine(tmp_path))
  data = workspace.resolved.data
  assert data["profile"]["roles"]["main"] == "kimi_code_openai"
  ids = {key for key in data["models"] if key.startswith("dsh-")}
  assert len(ids) == 13
  omp = tomllib.loads((ROOT / "agents/omp/content.toml").read_text())
  dsh = tomllib.loads((ROOT / "agents/dsh/content.toml").read_text())
  for key in ids:
    equivalent = data["models"][key]
    original = omp["models"][key.replace("dsh-", "omp-", 1)]
    assert equivalent["provider"] == original["provider"]
    assert dsh["models"][key]["template"] == original["template"]
  for key in ("kimi_tf", "zhipu_tf", "deepseek_tf"):
    assert data["providers"][key]["credential_ref"] == omp["providers"][key]["credential_ref"]
  candidate = workspace.candidate(read_lock(ROOT).identity)
  fields = {a.target.selector: json.loads(a.content) for a in candidate.artifacts if a.target.serialization == "cordis-yaml"}
  for key, api in (("kimi_tf", "openai-completions"), ("zhipu_tf", "anthropic-messages"), ("deepseek_tf", "openai-completions")):
    root = "/llm-pi-ai/config/providers/agentcfg-" + key
    assert fields[root + "/api"] == api
    assert fields[root + "/retryPolicy"]["maxRetries"] == 0
    assert fields[root + "/apiKeyEnv"].startswith("AGENTCFG_KEY_")
  models = fields["/llm-pi-ai/config/providers/agentcfg-kimi_tf/models"]
  assert {m["id"] for m in models} == {"kimi-for-coding", "k3", "k3-256k", "k3.1-pro", "k3.1-pro-highspeed", "kimi-for-coding-highspeed"}
  assert next(m for m in models if m["id"] == "k3")["reasoningEfforts"] == {"low": "low", "high": "high", "max": "max"}
  assert next(m for m in models if m["id"] == "k3.1-pro")["reasoningEfforts"] == {"low": "low", "high": "high", "max": "max"}
  assert next(m for m in models if m["id"] == "kimi-for-coding-highspeed")["reasoningEfforts"] == {"high": "high"}
  assert all("native" not in m and "thinking" not in m for m in models)
  deepseek = fields["/llm-pi-ai/config/providers/agentcfg-deepseek_tf/models"]
  assert all(m["reasoningEfforts"]["max"] == "high" for m in deepseek)
  assert all(m["compat"]["requiresReasoningContentOnAssistantMessages"] for m in deepseek)


def test_tf_shared_key_is_resolved_only_for_launch_and_never_rendered(tmp_path):
  workspace = load_workspace(tf_machine(tmp_path, keys=True))
  assert workspace.secret_store.resolve(SecretRef("secret:omp_kimi_tf_key")) == CANARY
  candidate = workspace.candidate(read_lock(ROOT).identity)
  assert all(CANARY.encode() not in a.content for a in candidate.artifacts)
  assert CANARY not in candidate.generation
  spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=tmp_path,
    instance_root=workspace.instance, runtime_root=tmp_path / "runtime", lock_identity="fixture")
  refs = {v.value.reference for v in spec.environment if isinstance(v.value, SecretRef)}
  assert {"secret:omp_kimi_tf_key", "secret:omp_zhipu_tf_key", "secret:omp_deepseek_tf_key"} <= refs


def test_tf_requires_explicit_urls_but_unselected_tf_does_not_block_dsh(tmp_path):
  local = tmp_path / "machine.toml"
  local.write_text('schema_version=1\n[machine]\nid="no-tf"\n')
  local.chmod(0o600)
  assert "kimi_tf" not in load_workspace(local).resolved.data["providers"]
  local.write_text((ROOT / "examples/dsh-tf.local.toml").read_text())
  with pytest.raises(ConfigError, match="local-value"):
    load_workspace(local)


def test_native_dsh_model_unknown_fields_fail_and_omp_options_are_not_used(tmp_path):
  local = tf_machine(tmp_path)
  with local.open("a") as stream:
    stream.write('\n[overrides.models.dsh-kimi_tf-k3.native.dsh]\nprivateField=true\n')
  with pytest.raises(ConfigError):
    load_workspace(local)

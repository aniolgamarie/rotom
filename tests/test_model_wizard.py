"""私有模型向导：脱敏、语义校验与原子写入。"""

import builtins
import getpass
import os
from pathlib import Path
import sys
import tomllib
import warnings
from types import SimpleNamespace

import pytest

from agentcfg import cli
from agentcfg import model_wizard


def local_file():
  return Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines/default.toml"


def interactive(monkeypatch, answers, *, secret="private-key-canary"):
  values = iter(answers)
  monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
  monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
  monkeypatch.setattr(builtins, "input", lambda prompt: next(values))
  monkeypatch.setattr("agentcfg.model_wizard.getpass.getpass", lambda prompt: secret)


def test_add_private_model_preserves_comments_and_hides_key(monkeypatch, capsys):
  assert cli.main(["init-local"]) == 0
  path = local_file()
  path.write_text("# user comment\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
  interactive(monkeypatch, ["private_gateway", "private_main", "", "https://example.invalid/v1",
    "model-live", "", "", "", "yes"])
  assert cli.main(["model", "add"]) == 0
  content = path.read_text(encoding="utf-8")
  assert content.startswith("# user comment\n")
  document = tomllib.loads(content)
  assert document["overrides"]["providers"]["private_gateway"]["base_url"] == "https://example.invalid/v1"
  assert document["overrides"]["models"]["private_main"]["remote_id"] == "model-live"
  assert document["overrides"]["profiles"]["dsh-default"]["roles"]["main"] == "private_main"
  assert document["secrets"]["private_gateway_key"] == "private-key-canary"
  output = capsys.readouterr()
  assert "private-key-canary" not in output.out + output.err
  assert cli.main(["validate"]) == 0


def test_add_model_cancel_keeps_file_unchanged(monkeypatch):
  assert cli.main(["init-local"]) == 0
  path = local_file()
  before = path.read_bytes()
  interactive(monkeypatch, ["private_gateway", "private_main", "", "https://example.invalid/v1",
    "model-live", "", "", "", "no"])
  assert cli.main(["model", "add"]) == 0
  assert path.read_bytes() == before


def test_add_omp_model_requires_explicit_capacity(monkeypatch):
  assert cli.main(["init-local", "--profile", "omp-default"]) == 0
  interactive(monkeypatch, ["private_gateway", "private_main", "", "https://example.invalid/v1",
    "model-live", "text,image", "", "128000", "8192", "provider documentation", "yes"])
  assert cli.main(["model", "add"]) == 0
  model = tomllib.loads(local_file().read_text(encoding="utf-8"))["overrides"]["models"]["private_main"]
  assert model["context_window"] == 128000
  assert model["max_output_tokens"] == 8192
  assert cli.main(["validate"]) == 0


def test_pi_model_uses_same_wizard_fields(monkeypatch):
  interactive(monkeypatch, ["private_gateway", "private_main", "", "https://example.invalid/v1",
    "model-live", "", "", ""])
  provider_id, model_id, role, secret_name, secret, provider, model = model_wizard._answers(
    SimpleNamespace(agent="pi"))
  assert (provider_id, model_id, role) == ("private_gateway", "private_main", "main")
  assert provider["protocol"] == "openai-compatible"
  assert model["remote_id"] == "model-live"
  assert secret_name == "private_gateway_key"
  assert secret == "private-key-canary"


def test_dsh_wizard_rejects_unsupported_protocol_before_secret_prompt(monkeypatch):
  assert cli.main(["init-local"]) == 0
  before = local_file().read_bytes()
  interactive(monkeypatch, ["private_gateway", "private_main", "anthropic-messages"])
  assert cli.main(["model", "add"]) == 2
  assert local_file().read_bytes() == before


def test_add_second_model_keeps_first_and_other_local_fields(monkeypatch):
  assert cli.main(["init-local"]) == 0
  interactive(monkeypatch, ["provider_one", "model_one", "", "https://one.example.invalid/v1",
    "one", "", "", "", "yes"], secret="first-private-key")
  assert cli.main(["model", "add"]) == 0
  interactive(monkeypatch, ["provider_two", "model_two", "", "https://two.example.invalid/v1",
    "two", "", "", "", "yes"], secret="second-private-key")
  assert cli.main(["model", "add"]) == 0
  document = tomllib.loads(local_file().read_text(encoding="utf-8"))
  assert list(document["overrides"]["providers"]) == ["provider_one", "provider_two"]
  assert document["overrides"]["profiles"]["dsh-default"]["models"] == ["model_one", "model_two"]
  assert document["secrets"]["provider_one_key"] == "first-private-key"
  assert document["secrets"]["provider_two_key"] == "second-private-key"


def test_add_model_requires_terminal_before_reading_local(monkeypatch):
  assert cli.main(["init-local"]) == 0
  assert cli.main(["model", "add"]) == 2
  assert local_file().exists()


def test_add_model_rejects_visible_secret_input_fallback(monkeypatch):
  assert cli.main(["init-local"]) == 0
  before = local_file().read_bytes()
  interactive(monkeypatch, ["private_gateway", "private_main", "", "https://example.invalid/v1",
    "model-live", "", "", ""])
  def unsafe_getpass(prompt):
    warnings.warn("terminal echo cannot be disabled", getpass.GetPassWarning)
    return "secret-would-be-visible"
  monkeypatch.setattr("agentcfg.model_wizard.getpass.getpass", unsafe_getpass)
  assert cli.main(["model", "add"]) == 2
  assert local_file().read_bytes() == before


def test_add_model_without_key_does_not_select_broken_provider(monkeypatch):
  assert cli.main(["init-local"]) == 0
  before = local_file().read_bytes()
  interactive(monkeypatch, ["private_gateway", "private_main", "", "https://example.invalid/v1",
    "model-live", "", "", ""], secret="")
  assert cli.main(["model", "add"]) == 2
  assert local_file().read_bytes() == before


def test_add_model_rejects_credential_in_url_without_writing(monkeypatch, capsys):
  assert cli.main(["init-local"]) == 0
  path = local_file()
  before = path.read_bytes()
  interactive(monkeypatch, ["private_gateway", "private_main", "", "https://user:secret-url-canary@example.invalid/v1",
    "model-live", "", "", "", "yes"])
  assert cli.main(["model", "add"]) == 2
  assert path.read_bytes() == before
  output = capsys.readouterr()
  assert "secret-url-canary" not in output.out + output.err


def test_add_model_detects_change_before_atomic_replace(monkeypatch):
  assert cli.main(["init-local"]) == 0
  path = local_file()
  answers = iter(["private_gateway", "private_main", "", "https://example.invalid/v1",
    "model-live", "", "", ""])
  monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
  monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
  def answer(prompt):
    if "写入私人机器文件" in prompt:
      path.write_text(path.read_text(encoding="utf-8") + "# concurrent edit\n", encoding="utf-8")
      return "yes"
    return next(answers)
  monkeypatch.setattr(builtins, "input", answer)
  monkeypatch.setattr("agentcfg.model_wizard.getpass.getpass", lambda prompt: "private-key-canary")
  assert cli.main(["model", "add"]) == 4
  assert "# concurrent edit" in path.read_text(encoding="utf-8")
  assert "private_gateway" not in path.read_text(encoding="utf-8")


def test_add_model_detects_change_during_workspace_resolution(monkeypatch):
  assert cli.main(["init-local"]) == 0
  path = local_file()
  original = model_wizard.load_workspace
  def changed(local, profile):
    path.write_text(path.read_text(encoding="utf-8") + "# concurrent edit\n", encoding="utf-8")
    return original(local, profile)
  monkeypatch.setattr(model_wizard, "load_workspace", changed)
  monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
  monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
  assert cli.main(["model", "add"]) == 4
  assert "# concurrent edit" in path.read_text(encoding="utf-8")


def test_public_presets_list_without_local_file(capsys):
  assert cli.main(["model", "presets"]) == 0
  output = capsys.readouterr().out
  for name in ("deepseek-flash", "kimi-k3", "glm-5.3"):
    assert name in output
  assert "https://api.moonshot.cn/anthropic" in output
  assert "USD/1000000" in output and "CNY/1000000" in output


def test_enable_preset_requires_key_and_keeps_file_unchanged(monkeypatch):
  assert cli.main(["init-local"]) == 0
  path = local_file()
  before = path.read_bytes()
  interactive(monkeypatch, [], secret="")
  assert cli.main(["model", "enable", "deepseek"]) == 2
  assert path.read_bytes() == before
  assert cli.main(["validate"]) == 0


def test_enable_public_preset_preserves_subscription_and_comments(monkeypatch, capsys):
  assert cli.main(["init-local"]) == 0
  path = local_file()
  path.write_text("# machine note\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
  interactive(monkeypatch, ["yes"], secret="preset-key-canary")
  assert cli.main(["model", "enable", "deepseek"]) == 0
  content = path.read_text(encoding="utf-8")
  data = tomllib.loads(content)
  profile = data["overrides"]["profiles"]["dsh-default"]
  assert content.startswith("# machine note\n")
  assert "codex" in profile["providers"] and "cursor" in profile["providers"]
  assert "deepseek_openai" in profile["providers"]
  assert "deepseek_flash_openai" in profile["models"]
  assert data["secrets"]["deepseek_key"] == "preset-key-canary"
  assert "preset-key-canary" not in capsys.readouterr().out
  assert cli.main(["validate"]) == 0
  interactive(monkeypatch, [], secret="unused")
  assert cli.main(["model", "enable", "deepseek"]) == 0


def test_enable_omp_uses_anthropic_and_keeps_existing_roles(monkeypatch):
  assert cli.main(["init-local", "--profile", "omp-default"]) == 0
  interactive(monkeypatch, ["yes"], secret="omp-key-canary")
  assert cli.main(["model", "enable", "kimi"]) == 0
  data = tomllib.loads(local_file().read_text(encoding="utf-8"))
  profile = data["overrides"]["profiles"]["omp-default"]
  assert profile["providers"] == ["kimi_anthropic"]
  assert profile["models"] == ["kimi_k3_anthropic"]
  assert profile["roles"]["main"] == "kimi_k3_anthropic"
  assert cli.main(["validate"]) == 0


def test_enable_preset_rejects_unsupported_protocol_without_edit(monkeypatch):
  assert cli.main(["init-local"]) == 0
  before = local_file().read_bytes()
  interactive(monkeypatch, [], secret="unused")
  assert cli.main(["model", "enable", "glm", "--protocol", "anthropic"]) == 2
  assert local_file().read_bytes() == before


def test_enable_pi_projects_deepseek_native_compat(monkeypatch, capsys):
  assert cli.main(["init-local", "--profile", "pi-default"]) == 0
  interactive(monkeypatch, ["yes"], secret="pi-key-canary")
  assert cli.main(["model", "enable", "deepseek"]) == 0
  w = model_wizard.load_workspace(local_file(), "pi-default")
  models = [value for target, value in w.adapter._fields(w.resolved.data)
    if target.path == "pi-home/models.json" and target.selector.endswith("/models")]
  deepseek = next(model for group in models for model in group if model["id"] == "deepseek-flash")
  assert deepseek["compat"]["requiresReasoningContentOnAssistantMessages"] is True
  assert deepseek["compat"]["reasoningEffortMap"]["xhigh"] == "max"
  assert w.candidate("offline-candidate").artifacts
  assert "pi-key-canary" not in capsys.readouterr().err


def test_enable_omp_deepseek_openai_projects_tool_compat(monkeypatch):
  from agentcfg.omp import _native_model_providers
  assert cli.main(["init-local", "--profile", "omp-default"]) == 0
  interactive(monkeypatch, ["yes"], secret="omp-deepseek-key")
  assert cli.main(["model", "enable", "deepseek", "--protocol", "openai"]) == 0
  w = model_wizard.load_workspace(local_file(), "omp-default")
  provider = _native_model_providers(w.resolved.data)["deepseek_openai"]
  model = provider["models"][0]
  assert provider["authHeader"] is True
  assert model["compat"]["supportsToolChoice"] is False
  assert model["compat"]["requiresReasoningContentForToolCalls"] is True
  assert model["compat"]["requiresAssistantContentForToolCalls"] is True


def test_price_schema_rejects_incomplete_rate_and_schedule():
  from agentcfg.schema import ConfigError, validate_document
  model = {"provider": "p", "remote_id": "m", "input": ["text"],
    "pricing": {"currency": "USD", "per_tokens": 1000000,
      "source": "https://example.invalid", "checked_on": "2026-09-27",
      "standard": {"output": 1.0}}}
  with pytest.raises(ConfigError):
    validate_document("registry", {"schema_version": 1, "models": {"m": model}})
  model["pricing"]["standard"]["input"] = 1.0
  model["pricing"]["off_peak"] = {"input": 0.5, "output": 0.5}
  with pytest.raises(ConfigError):
    validate_document("registry", {"schema_version": 1, "models": {"m": model}})


def test_one_key_enables_same_vendor_in_two_profiles(monkeypatch):
  assert cli.main(["init-local"]) == 0
  interactive(monkeypatch, ["yes"], secret="shared-secret-canary")
  assert cli.main(["model", "enable", "kimi"]) == 0
  interactive(monkeypatch, ["yes"], secret="unused")
  assert cli.main(["--profile", "omp-default", "model", "enable", "kimi"]) == 0
  data = tomllib.loads(local_file().read_text(encoding="utf-8"))
  assert data["secrets"] == {"deepseek_key": "", "kimi_key": "shared-secret-canary", "glm_key": ""}
  assert data["overrides"]["profiles"]["dsh-default"]["models"] == ["kimi_k3_openai"]
  assert data["overrides"]["profiles"]["omp-default"]["models"] == ["kimi_k3_anthropic"]


def test_model_status_reports_partial_omp_keys_without_values(capsys):
  assert cli.main(["init-local", "--profile", "omp-kernel"]) == 0
  path = local_file()
  original = path.read_text(encoding="utf-8")
  path.write_text(original + '\nomp_kimi_tf_key = "status-key-canary"\n', encoding="utf-8")
  assert cli.main(["model", "status"]) == 0
  output = capsys.readouterr().out
  assert "kimi_tf: key 已配置" in output
  assert "zhipu_tf: key 缺失" in output
  assert "status-key-canary" not in output

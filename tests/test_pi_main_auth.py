"""主会话私密文件到受管环境；不启动Pi/Codex，不调用认证服务。"""
import hashlib

import pytest

from agentcfg.adapter import SecretRef
from agentcfg.pi import PiAdapter, key_variable
from agentcfg.process import launch_environment
from agentcfg.secret_files import load_secrets
from agentcfg.secrets import CredentialError
from agentcfg.storage import Conflict, ensure_private
from test_pi_model_config import fixture, ROOT


def setup(tmp_path, body=None):
  private = tmp_path / "keys"; ensure_private(private)
  path = private / "secrets.toml"
  if body is not None: path.write_text(body); path.chmod(0o600)
  local = tmp_path / "local.toml"
  store = load_secrets({"schema_version": 1, "secrets_file": str(path)}, local)
  data = fixture(tmp_path)
  spec = PiAdapter(ROOT).launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime",
    instance_root=tmp_path / "instance", lock_identity="synthetic-lock")
  return data, spec, store, path


def test_main_private_file_key_is_only_in_bound_environment_and_preserves_native_accounts(tmp_path, monkeypatch):
  marker = "synthetic-main-private-key"
  data, spec, store, path = setup(tmp_path, 'schema_version=1\n[shared]\nfixture="' + marker + '"\n')
  auth = tmp_path / "instance/pi-home"; ensure_private(auth)
  account = auth / "auth.json"; account.write_text('{"synthetic-native-account":"sentinel"}\n'); account.chmod(0o600)
  before = account.read_bytes()
  monkeypatch.setenv("OPENAI_API_KEY", "unselected-parent-key")
  monkeypatch.setenv("HTTPS_PROXY", "http://unselected.invalid:8123")
  env = launch_environment(spec, data["machine"], store)
  assert env[key_variable("fictional")] == marker
  assert "OPENAI_API_KEY" not in env and "HTTPS_PROXY" not in env
  assert env["HOME"] == str(tmp_path / "instance/user-home")
  assert env["PI_CODING_AGENT_DIR"] == str(auth)
  assert "CODEX_HOME" not in env and account.read_bytes() == before
  artifacts = PiAdapter(ROOT).render(data)
  body = b"".join(item.content for item in artifacts).decode()
  assert marker not in body and hashlib.sha256(marker.encode()).hexdigest() not in body
  assert marker not in repr(spec) and marker not in repr(store)
  assert path.read_text().endswith('fixture="' + marker + '"\n')


@pytest.mark.parametrize("body,reason", [
  (None, "missing"), ('schema_version=1\n[shared]\n', "missing"),
  ('schema_version=1\n[shared]\nfixture=""\n', "empty"),
])
def test_missing_or_empty_main_key_stays_unresolved_without_parent_credential_fallback(tmp_path, monkeypatch, body, reason):
  data, spec, store, _ = setup(tmp_path, body)
  monkeypatch.setenv("OPENAI_API_KEY", "unselected-parent-key")
  monkeypatch.setenv(key_variable("fictional"), "unselected-preexisting-key")
  env = launch_environment(spec, data["machine"], store)
  assert key_variable("fictional") not in env and "OPENAI_API_KEY" not in env
  with pytest.raises(CredentialError) as error: store.resolve(SecretRef("secret:fixture"))
  assert error.value.exit_code == 3 and error.value.reason == reason
  assert "unselected" not in str(error.value)
  # Pi已声明延迟认证；此测试不把可构造环境当作主会话请求通过。
  assert next(row for row in spec.environment if row.name == key_variable("fictional")).required is False


def test_unreadable_main_key_file_is_a_sanitized_ownership_conflict(tmp_path, monkeypatch):
  private = tmp_path / "keys"; ensure_private(private)
  path = private / "secrets.toml"; path.write_text('schema_version=1\n[shared]\nfixture="synthetic-private"\n'); path.chmod(0o600)
  def denied(_path): raise PermissionError("synthetic-private-underlying-error")
  monkeypatch.setattr("agentcfg.secret_files.read_private_file", denied)
  with pytest.raises(Conflict) as error:
    load_secrets({"schema_version": 1, "secrets_file": str(path)}, tmp_path / "local.toml")
  assert error.value.exit_code == 4 and "synthetic-private" not in str(error.value)


@pytest.mark.parametrize("entry,label", [("", "未填写"), ('deepseek_key=""\n', "为空")],
                         ids=["selected-missing", "selected-empty"])
def test_pi_base_configuration_status_labels_selected_key_without_parent_fallback(
    tmp_path, monkeypatch, capsys, entry, label):
  import os
  from pathlib import Path
  from agentcfg import cli

  assert cli.main(["init-local", "--profile", "pi-base"]) == 0
  path = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/secrets.toml"
  path.write_text("schema_version=1\n[shared]\n" + entry)
  path.chmod(0o600)
  before = path.read_bytes()
  auth = tmp_path / "native-pi-home"; ensure_private(auth)
  account = auth / "auth.json"
  account.write_text('{"own-native-account":"synthetic-native-auth-sentinel"}\n')
  account.chmod(0o600)
  native_before = account.read_bytes()
  marker = "synthetic-unselected-parent-key"
  monkeypatch.setenv("DEEPSEEK_API_KEY", marker)
  monkeypatch.setenv("OPENAI_API_KEY", marker)
  monkeypatch.setenv(key_variable("deepseek_openai"), marker)
  monkeypatch.setenv("PI_CODING_AGENT_DIR", str(auth))
  capsys.readouterr()
  assert cli.main(["--profile", "pi-base", "model", "status", "--verbose"]) == 0
  output = capsys.readouterr()
  assert "模型配置  pi / pi-base" in output.out
  row = next(line for line in output.out.splitlines()
             if line.split("|")[0].strip() == "deepseek_openai")
  assert row.split("|")[3].strip() == label
  assert "已填写" not in row
  for sentinel in (marker, "synthetic-native-auth-sentinel"):
    assert sentinel not in output.out + output.err
    assert hashlib.sha256(sentinel.encode()).hexdigest() not in output.out + output.err
  assert path.read_bytes() == before and account.read_bytes() == native_before

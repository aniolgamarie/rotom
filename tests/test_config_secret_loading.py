"""CFG-01：配置操作不读取共享凭据；显式解析保留完整校验。"""

import os
from pathlib import Path
import pickle
import traceback

import pytest

from agentcfg import cli, commands, secret_files
from agentcfg.adapter import SecretRef
from agentcfg.config import load_local
from agentcfg.process import launch_environment
from agentcfg.schema import ConfigError
from agentcfg.secrets import CredentialError
from agentcfg.storage import Conflict
from agentcfg.workspace import load_workspace


CANARY = "SYNTHETIC-SECRET-LOADING-CANARY"


@pytest.fixture
def credential_files():
  assert cli.main(["init-local"]) == 0
  root = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg"
  return root / "machines/default.toml", root / "secrets.toml"


def damage_shared(local, shared, damage):
  if damage == "symlink":
    target = shared.with_name("synthetic-target.toml")
    shared.rename(target)
    shared.symlink_to(target)
  elif damage == "duplicate-source":
    shared.write_text(f'schema_version = 1\n[shared]\ndeepseek_key = "{CANARY}"\n')
    with local.open("a") as stream:
      stream.write(f'\n[secrets]\ndeepseek_key = "{CANARY}"\n')
  elif damage == "duplicate-reference":
    shared.write_text(f'schema_version = 1\n[shared]\ndeepseek_key = "{CANARY}"\n'
      '[providers.synthetic]\ndeepseek_key = "another-synthetic-key"\n')
  else:
    shared.write_text(f'schema_version = 1\n[shared]\nkey = "{CANARY}')


@pytest.mark.parametrize("damage", ["malformed", "symlink", "duplicate-source"])
@pytest.mark.parametrize("command", ["validate", "render", "plan", "sync", "apply", "doctor"])
def test_configuration_commands_never_read_shared_credentials(credential_files, monkeypatch, command, damage):
  local, shared = credential_files
  damage_shared(local, shared, damage)
  def forbidden_read(path):
    raise AssertionError("configuration command read shared credentials")
  monkeypatch.setattr(secret_files, "read_secrets_document", forbidden_read)
  # 依赖同步由假后端完成；其余命令执行真实离线解析和临时目录部署。
  monkeypatch.setattr(commands, "sync_backend", lambda *args: {"status": "synthetic-sync"})
  workspace = load_workspace(local)
  assert CANARY not in repr(workspace.resolved)
  assert cli.main([command]) == 0


def test_deferred_resolution_loads_once_and_rejects_invalid_calls_first(credential_files, monkeypatch):
  local, shared = credential_files
  shared.write_text(f'schema_version = 1\n[shared]\ndeepseek_key = "{CANARY}"\n')
  original = secret_files.read_secrets_document
  reads = []
  def read(path):
    reads.append(path)
    return original(path)
  monkeypatch.setattr(secret_files, "read_secrets_document", read)
  config, store = load_local(local, load_credentials=False)
  assert "secrets" not in config.data
  assert repr(store) == "SecretStore()"
  with pytest.raises(TypeError):
    pickle.dumps(store)
  for reference, required in ((CANARY, True), (SecretRef("secret:deepseek_key"), 1)):
    with pytest.raises(CredentialError):
      store.resolve(reference, required=required)
  assert reads == []
  assert store.resolve(SecretRef("secret:deepseek_key")) == CANARY
  shared.write_text("malformed after first resolution")
  assert store.resolve(SecretRef("secret:deepseek_key")) == CANARY
  assert reads == [shared]


@pytest.mark.parametrize("damage,error,exit_code", [
  ("malformed", ConfigError, 2), ("symlink", Conflict, 4),
  ("duplicate-source", ConfigError, 2), ("duplicate-reference", ConfigError, 2),
])
def test_runtime_resolution_and_status_preserve_credential_validation(credential_files, damage, error, exit_code, capsys):
  local, shared = credential_files
  damage_shared(local, shared, damage)
  workspace = load_workspace(local)
  spec = workspace.adapter.launch_spec(workspace.resolved.data,
    cwd=Path.cwd(), runtime_root=workspace.cache / "synthetic-runtime",
    instance_root=workspace.instance, lock_identity="synthetic-lock")
  with pytest.raises(error) as caught:
    launch_environment(spec, workspace.resolved.data["machine"], workspace.secret_store)
  assert CANARY not in "".join(traceback.format_exception(caught.value))
  assert cli.main(["model", "status"]) == exit_code
  output = capsys.readouterr()
  assert CANARY not in output.out + output.err
  # 直接调用的兼容接口仍立即执行完全相同的凭据校验。
  with pytest.raises(error):
    load_local(local)


def test_deferred_inline_placeholders_still_use_shared_values(credential_files):
  local, shared = credential_files
  shared.write_text(f'schema_version = 1\n[shared]\ndeepseek_key = "{CANARY}"\n')
  with local.open("a") as stream:
    stream.write('\n[secrets]\ndeepseek_key = ""\ninline_key = "synthetic-inline"\n')
  workspace = load_workspace(local)
  assert workspace.secret_store.resolve(SecretRef("secret:deepseek_key")) == CANARY
  assert workspace.secret_store.resolve(SecretRef("secret:inline_key")) == "synthetic-inline"
  assert "secrets" not in workspace.resolved.data

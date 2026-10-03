"""共享凭据与状态指引；只使用临时 HOME、假输入和秘密哨兵。"""

import getpass
import os
from pathlib import Path
import sys
import tomllib
import warnings

import pytest

from agentcfg import cli
from agentcfg.adapter import SecretRef
from agentcfg.config import load_local
from agentcfg.schema import ConfigError
from agentcfg.secret_files import load_secrets, save_shared_key
from agentcfg.storage import Conflict
from agentcfg.workspace import load_workspace


CANARY = "PRIVATE-SHARED-KEY-CANARY"


def machine(name="default"):
  return Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines" / f"{name}.toml"


def shared():
  return Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/secrets.toml"


def terminal(monkeypatch, value=CANARY):
  monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
  monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
  monkeypatch.setattr(getpass, "getpass", lambda prompt: value)


def write_shared(content):
  shared().write_text(content, encoding="utf-8")
  shared().chmod(0o600)


def test_key_command_shares_across_machines_profiles_and_protocols(monkeypatch, capsys):
  assert cli.main(["init-local"]) == 0
  assert cli.main(["init-local", "--machine", "second", "--profile", "omp-kernel"]) == 0
  before = {path: path.read_bytes() for path in (machine(), machine("second"))}
  terminal(monkeypatch)
  assert cli.main(["model", "key", "kimi"]) == 0
  assert shared().stat().st_mode & 0o777 == 0o600
  assert shared().parent.stat().st_mode & 0o777 == 0o700
  for path, original in before.items():
    assert path.read_bytes() == original
    for profile in ("dsh-default", "pi-default", "omp-default", "omp-kernel"):
      workspace = load_workspace(path, profile, proposal={"local_values": {
        "tf_openai_url": "https://tf-gateway.example.invalid/v1",
        "tf_anthropic_url": "https://tf-gateway.example.invalid/anthropic"}})
      assert workspace.secret_store.resolve(SecretRef("secret:kimi_key")) == CANARY
      identity = "offline-config-only" if workspace.agent == "pi" else workspace.backend.read_lock(workspace.repository).identity
      candidate = workspace.candidate(identity)
      assert all(CANARY.encode() not in artifact.content for artifact in candidate.artifacts)
  assert CANARY not in capsys.readouterr().out


def test_key_rotation_and_empty_cancel_do_not_change_machine(monkeypatch, capsys):
  assert cli.main(["init-local"]) == 0
  before = machine().read_bytes()
  terminal(monkeypatch)
  assert cli.main(["model", "key", "deepseek"]) == 0
  terminal(monkeypatch, "ROTATED-PRIVATE-CANARY")
  assert cli.main(["model", "key", "deepseek"]) == 0
  saved = shared().read_bytes()
  terminal(monkeypatch, "")
  assert cli.main(["model", "key", "deepseek"]) == 0
  assert shared().read_bytes() == saved
  assert machine().read_bytes() == before
  assert tomllib.loads(saved.decode())["shared"]["deepseek_key"] == "ROTATED-PRIVATE-CANARY"
  output = capsys.readouterr().out
  assert CANARY not in output and "ROTATED-PRIVATE-CANARY" not in output


def test_key_requires_hidden_terminal_input(monkeypatch):
  assert cli.main(["init-local"]) == 0
  before = shared().read_bytes()
  assert cli.main(["model", "key", "glm"]) == 2
  terminal(monkeypatch)
  def no_echo(prompt):
    warnings.warn("no hidden input", getpass.GetPassWarning)
  monkeypatch.setattr(getpass, "getpass", no_echo)
  assert cli.main(["model", "key", "glm"]) == 2
  assert shared().read_bytes() == before


def test_tf_key_uses_selected_provider_reference(monkeypatch):
  assert cli.main(["init-local", "--profile", "omp-kernel"]) == 0
  terminal(monkeypatch)
  assert cli.main(["model", "key", "kimi_tf"]) == 0
  document = tomllib.loads(shared().read_text())
  assert document["providers"]["kimi_tf"] == {"omp_kimi_tf_key": CANARY}
  assert cli.main(["model", "key", "nonexistent-provider"]) == 2


def test_custom_secrets_file_and_empty_legacy_placeholders(tmp_path):
  assert cli.main(["init-local"]) == 0
  before = shared().read_bytes()
  custom = tmp_path / "vault"
  custom.mkdir(mode=0o700)
  path = custom / "keys.toml"
  path.write_text(f'schema_version = 1\n[secrets]\nkimi_key = "{CANARY}"\n')
  path.chmod(0o600)
  document = {"schema_version": 1, "machine": {"id": "default"}, "secrets_file": str(path),
    "secrets": {"kimi_key": "", "other": "legacy"}}
  store = load_secrets(document, machine())
  assert store.resolve(SecretRef("secret:kimi_key")) == CANARY
  assert store.resolve(SecretRef("secret:other")) == "legacy"
  assert shared().read_bytes() == before


def test_nonempty_duplicate_sources_fail_without_leaking():
  assert cli.main(["init-local"]) == 0
  write_shared(f'schema_version = 1\n[secrets]\nkimi_key = "{CANARY}"\n')
  with pytest.raises(ConfigError, match="duplicate-credential-source") as caught:
    load_secrets({"secrets": {"kimi_key": CANARY}}, machine())
  assert CANARY not in str(caught.value)
  assert caught.value.__context__ is None


@pytest.mark.parametrize("content", [
  'schema_version = 1\n[secrets]\nkimi_key = "PRIVATE-SHARED-KEY-CANARY',
  'schema_version = 1\nunknown = "PRIVATE-SHARED-KEY-CANARY"\n[secrets]\n',
  'schema_version = 1\n[secrets]\nkimi_key = ["PRIVATE-SHARED-KEY-CANARY"]\n',
])
def test_malformed_shared_file_is_redacted(content):
  assert cli.main(["init-local"]) == 0
  write_shared(content)
  with pytest.raises(ConfigError) as caught:
    load_local(machine())
  assert CANARY not in str(caught.value)
  assert caught.value.__context__ is None


@pytest.mark.parametrize("unsafe", ["mode", "symlink", "hardlink", "parent-mode"])
def test_shared_file_rejects_unsafe_files_before_use(tmp_path, unsafe):
  assert cli.main(["init-local"]) == 0
  write_shared(f'schema_version = 1\n[secrets]\nkimi_key = "{CANARY}"\n')
  if unsafe == "mode":
    shared().chmod(0o644)
  elif unsafe == "symlink":
    target = tmp_path / "original"
    shared().rename(target)
    shared().symlink_to(target)
  elif unsafe == "hardlink":
    os.link(shared(), tmp_path / "other")
  else:
    shared().parent.chmod(0o755)
  with pytest.raises(Conflict) as caught:
    load_secrets({}, machine())
  assert CANARY not in str(caught.value)


def test_missing_shared_file_does_not_create_anything():
  assert cli.main(["init-local"]) == 0
  shared().unlink()
  _, store = load_local(machine())
  assert store.resolve(SecretRef("secret:kimi_key"), required=False) is None
  assert not shared().exists()


def test_missing_shared_file_keeps_legacy_parent_permissions_compatible():
  assert cli.main(["init-local"]) == 0
  shared().unlink()
  shared().parent.chmod(0o755)
  _, store = load_local(machine())
  assert store.resolve(SecretRef("secret:kimi_key"), required=False) is None
  with pytest.raises(Conflict, match="0700"):
    save_shared_key({}, machine(), "kimi_key", CANARY)
  assert not shared().exists()


def test_key_command_reports_unsafe_new_parent_without_internal_error(monkeypatch, capsys):
  assert cli.main(["init-local"]) == 0
  shared().unlink()
  shared().parent.chmod(0o755)
  terminal(monkeypatch)
  assert cli.main(["model", "key", "kimi"]) == 4
  output = capsys.readouterr()
  assert "0700" in output.err and "内部操作失败" not in output.err
  assert CANARY not in output.out + output.err
  assert not shared().exists()


def test_shared_key_rolls_back_if_model_config_commit_fails():
  assert cli.main(["init-local"]) == 0
  write_shared('schema_version = 1\n# preserve note\n[secrets]\nother = "old"\n')
  before = shared().read_bytes()
  def fail():
    raise Conflict("synthetic concurrent config edit")
  with pytest.raises(Conflict, match="synthetic"):
    save_shared_key({}, machine(), "kimi_key", CANARY, after_write=fail)
  assert shared().read_bytes() == before


def test_status_has_default_and_extra_sources_actionable_commands_and_no_key(monkeypatch, capsys):
  assert cli.main(["init-local", "--machine", "workstation", "--profile", "omp-kernel"]) == 0
  terminal(monkeypatch)
  assert cli.main(["--machine", "workstation", "model", "key", "kimi"]) == 0
  assert cli.main(["--machine", "workstation", "model", "status", "--verbose"]) == 0
  output = capsys.readouterr().out
  assert "全局默认" in output and "profile 扩展" in output
  assert "deepseek_anthropic" in output and "kimi_tf" in output
  assert "--machine workstation --profile omp-kernel model key deepseek" in output
  assert "--machine workstation --profile omp-kernel model key zhipu_tf" in output
  assert "main" in output and "kimi-for-coding" in output and "缺 key" in output
  assert CANARY not in output


def test_legacy_inline_key_update_keeps_single_source(monkeypatch):
  assert cli.main(["init-local"]) == 0
  before = shared().read_bytes()
  with machine().open("a") as stream:
    stream.write('\n[secrets]\nkimi_key = "old-inline"\n')
  terminal(monkeypatch)
  assert cli.main(["model", "key", "kimi"]) == 0
  assert shared().read_bytes() == before
  _, store = load_local(machine())
  assert store.resolve(SecretRef("secret:kimi_key")) == CANARY

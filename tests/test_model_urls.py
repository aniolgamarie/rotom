"""私人 URL 的 CLI 闭环；临时 HOME、隐藏输入替身，不连接服务。"""

import getpass
import os
from pathlib import Path
import sys
import tomllib
import warnings

import pytest

from agentcfg import cli
from agentcfg.workspace import load_workspace


URL = "https://private-url-canary.example.invalid/v1"


def machine():
  return Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines/default.toml"


def terminal(monkeypatch, value=URL):
  monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
  monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
  monkeypatch.setattr(getpass, "getpass", lambda prompt: value)


def test_missing_urls_have_actionable_status_and_block_deployment(capsys):
  assert cli.main(["init-local", "--profile", "omp-kernel"]) == 0
  assert cli.main(["model", "status", "--verbose"]) == 0
  output = capsys.readouterr().out
  assert "model url kimi_tf" in output and "model url zhipu_tf" in output
  assert "tf_openai_url" in output and "缺 URL" in output
  for command in (["plan"], ["apply"], ["run", "omp"]):
    assert cli.main(command) == 2
    assert "model status" in capsys.readouterr().err


def test_hidden_urls_can_be_filled_sequentially_and_updated(monkeypatch, capsys):
  assert cli.main(["init-local", "--profile", "omp-kernel"]) == 0
  original = tomllib.loads(machine().read_text())
  assert original.pop("local_values") == {"tf_openai_url": "", "tf_anthropic_url": ""}
  terminal(monkeypatch)
  assert cli.main(["model", "url", "kimi_tf"]) == 0
  assert cli.main(["model", "status", "--verbose"]) == 0
  output = capsys.readouterr().out
  assert "model url kimi_tf" not in output
  assert "model url zhipu_tf" in output
  assert URL not in output
  terminal(monkeypatch, URL + "/anthropic")
  assert cli.main(["model", "url", "zhipu_tf"]) == 0
  workspace = load_workspace(machine())
  assert workspace.resolved.data["providers"]["kimi_tf"]["base_url"] == URL
  assert workspace.resolved.missing_local_values == ()
  terminal(monkeypatch, URL + "/updated")
  assert cli.main(["model", "url", "kimi_tf"]) == 0
  document = tomllib.loads(machine().read_text())
  assert document.pop("local_values") == {"tf_openai_url": URL + "/updated", "tf_anthropic_url": URL + "/anthropic"}
  assert document == original
  assert machine().stat().st_mode & 0o777 == 0o600
  assert cli.main(["model", "status", "--verbose"]) == 0
  output = capsys.readouterr().out
  assert URL not in output and "缺 URL" not in output


def test_literal_endpoint_uses_private_override(monkeypatch, capsys):
  assert cli.main(["init-local", "--profile", "omp-default"]) == 0
  terminal(monkeypatch)
  assert cli.main(["model", "url", "deepseek_anthropic"]) == 0
  document = tomllib.loads(machine().read_text())
  assert document["overrides"]["providers"]["deepseek_anthropic"]["base_url"] == URL
  assert load_workspace(machine()).resolved.data["providers"]["deepseek_anthropic"]["base_url"] == URL
  assert URL not in capsys.readouterr().out


@pytest.mark.parametrize("value", ["file:///private-url-canary", "https://user:private-url-canary@example.invalid", "https://example.invalid?api_key=private-url-canary", "https://private-url-canary example.invalid"])
def test_bad_input_is_redacted_and_does_not_write(monkeypatch, capsys, value):
  assert cli.main(["init-local", "--profile", "omp-kernel"]) == 0
  before = machine().read_bytes()
  terminal(monkeypatch, value)
  assert cli.main(["model", "url", "kimi_tf"]) == 2
  assert machine().read_bytes() == before
  output = capsys.readouterr()
  assert "private-url-canary" not in output.out + output.err


def test_empty_input_and_hidden_input_failure_leave_file_unchanged(monkeypatch):
  assert cli.main(["init-local", "--profile", "omp-kernel"]) == 0
  before = machine().read_bytes()
  assert cli.main(["model", "url", "kimi_tf"]) == 2
  terminal(monkeypatch, "")
  assert cli.main(["model", "url", "kimi_tf"]) == 0
  def unavailable(prompt):
    warnings.warn("hidden input unavailable", getpass.GetPassWarning)
  monkeypatch.setattr(getpass, "getpass", unavailable)
  assert cli.main(["model", "url", "kimi_tf"]) == 2
  assert machine().read_bytes() == before


def test_concurrent_machine_edit_is_preserved(monkeypatch):
  assert cli.main(["init-local", "--profile", "omp-kernel"]) == 0
  terminal(monkeypatch)
  changed = machine().read_bytes() + b"\n# concurrent edit\n"
  def concurrent(prompt):
    machine().write_bytes(changed)
    return URL
  monkeypatch.setattr(getpass, "getpass", concurrent)
  assert cli.main(["model", "url", "kimi_tf"]) == 4
  assert machine().read_bytes() == changed


def test_unselected_missing_urls_do_not_block_default_profile():
  assert cli.main(["init-local", "--profile", "omp-kernel"]) == 0
  for profile in ("omp-default", "dsh-default", "pi-default"):
    workspace = load_workspace(machine(), profile)
    assert not workspace.resolved.missing_local_values
    assert "local_values" not in workspace.resolved.data

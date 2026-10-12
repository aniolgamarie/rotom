"""凭据分类在真实 CLI 流程中的展示；仅使用临时 HOME 与隐藏输入替身。"""

import getpass
import os
from pathlib import Path
import sys
import tomllib

from agentcfg import cli


def test_status_explains_empty_placeholder_groups_without_changing_file(capsys):
  assert cli.main(["init-local", "--machine", "workstation", "--profile", "omp-kernel"]) == 0
  path = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/secrets.toml"
  before = path.read_bytes()
  assert cli.main(["--machine", "workstation", "model", "status", "--verbose"]) == 0
  output = capsys.readouterr().out
  assert "填写位置（可直接用编辑器修改）" in output
  assert "[shared]" in output and "[providers.kimi_tf]" in output
  assert "omp_kimi_tf_key" in output and "kimi_code_key" in output
  assert "model key kimi_tf" in output
  assert path.read_bytes() == before
  document = tomllib.loads(before.decode())
  assert document["shared"] == {"kimi_code_key": "", "glm_coding_key": "", "deepseek_key": ""}
  assert document["providers"]["kimi_tf"] == {"omp_kimi_tf_key": ""}


def test_cli_saves_default_and_extra_credentials_in_distinct_groups(monkeypatch, capsys):
  assert cli.main(["init-local", "--profile", "omp-kernel"]) == 0
  monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
  monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
  monkeypatch.setattr(getpass, "getpass", lambda prompt: "PRIVATE-GROUP-KEY-CANARY")
  assert cli.main(["model", "key", "kimi-code"]) == 0
  assert cli.main(["model", "key", "kimi_tf"]) == 0
  path = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/secrets.toml"
  document = tomllib.loads(path.read_text())
  assert document["shared"]["kimi_code_key"] == "PRIVATE-GROUP-KEY-CANARY"
  assert document["providers"]["kimi_tf"]["omp_kimi_tf_key"] == "PRIVATE-GROUP-KEY-CANARY"
  assert "secrets" not in document
  assert cli.main(["model", "status"]) == 0
  output = capsys.readouterr().out
  assert "文件分组：[shared]" in output and "文件分组：[providers.kimi_tf]" in output
  assert "PRIVATE-GROUP-KEY-CANARY" not in output


def test_existing_flat_key_remains_readable_and_labelled(monkeypatch, capsys):
  assert cli.main(["init-local", "--profile", "omp-kernel"]) == 0
  path = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/secrets.toml"
  path.write_text('schema_version = 1\n# old note\n[secrets]\ndeepseek_key = "PRIVATE-OLD-CANARY"\n')
  path.chmod(0o600)
  monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
  monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
  monkeypatch.setattr(getpass, "getpass", lambda prompt: "PRIVATE-NEW-CANARY")
  assert cli.main(["model", "key", "deepseek"]) == 0
  assert cli.main(["model", "status"]) == 0
  output = capsys.readouterr().out
  assert "旧格式" in output
  assert "PRIVATE-OLD-CANARY" not in output and "PRIVATE-NEW-CANARY" not in output
  assert tomllib.loads(path.read_text())["secrets"]["deepseek_key"] == "PRIVATE-NEW-CANARY"
  assert "# old note" in path.read_text()


def test_status_distinguishes_missing_and_empty_keys_without_touching_native_auth(capsys):
  assert cli.main(["init-local", "--profile", "pi-base"]) == 0
  path = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/secrets.toml"
  path.write_text('schema_version=1\n[shared]\ndeepseek_key=""\n')
  path.chmod(0o600)
  before = path.read_bytes()
  account = Path(os.environ["HOME"]) / "native-auth.json"
  account.write_text('{"own-native-account":"synthetic-sentinel"}\n')
  native_before = account.read_bytes()
  assert cli.main(["model", "status", "--verbose"]) == 0
  output = capsys.readouterr().out
  rows = {name: next(line for line in output.splitlines() if line.strip().startswith(name))
          for name in ("deepseek_openai", "kimi_code_openai")}
  assert "为空" in rows["deepseek_openai"] and "未填写" in rows["kimi_code_openai"]
  assert "synthetic-sentinel" not in output
  assert path.read_bytes() == before and account.read_bytes() == native_before

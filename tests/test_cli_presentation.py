"""真实命令的展示边界：离线临时 HOME，脚本输出与原生 tail 不被格式化。"""

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from agentcfg import cli
from agentcfg.progress import Progress


def test_cli_validate_format_selection_keeps_same_json_payload(monkeypatch, capsys):
  assert cli.main(["init-local"]) == 0
  capsys.readouterr()
  assert cli.main(["validate"]) == 0
  piped = capsys.readouterr()
  expected = json.loads(piped.out)
  assert expected["valid"] is True and "校验配置" in piped.err
  monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
  assert cli.main(["validate"]) == 0
  human = capsys.readouterr()
  assert "配置有效" in human.out and "未检查（离线）" in human.out
  assert "校验配置" not in human.out
  assert cli.main(["validate", "--format", "json"]) == 0
  assert json.loads(capsys.readouterr().out) == expected
  monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
  assert cli.main(["validate", "--format", "human"]) == 0
  assert "配置有效" in capsys.readouterr().out


def test_cli_plan_and_doctor_expose_summary_and_next_command(capsys):
  assert cli.main(["init-local", "--machine", "workstation"]) == 0
  capsys.readouterr()
  prefix = ["--machine", "workstation"]
  assert cli.main(prefix + ["plan", "--format", "human"]) == 0
  plan = capsys.readouterr().out
  assert "待变更" in plan and "定位条目" in plan
  assert "<redacted>" not in plan
  assert cli.main(prefix + ["doctor", "--input", "--format", "human"]) == 0
  doctor = capsys.readouterr().out
  assert "doctor：需要处理" in doctor and "尚未部署配置" in doctor
  assert "./agentcfg --machine workstation --profile dsh-default setup" in doctor
  assert "诊断 stdin 为终端" in doctor
  assert "当前后端不提供受管输入事件" in doctor


def test_model_default_summary_and_verbose_catalog_are_read_only(capsys):
  assert cli.main(["init-local", "--machine", "workstation", "--profile", "omp-kernel"]) == 0
  root = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg"
  machine = root / "machines/workstation.toml"
  keys = root / "secrets.toml"
  before = (machine.read_bytes(), keys.read_bytes())
  capsys.readouterr()
  prefix = ["--machine", "workstation", "model", "status"]
  assert cli.main(prefix) == 0
  summary = capsys.readouterr().out
  assert "2 个地址待填写" in summary and "5 个 key 未填写" in summary
  assert "完整模型目录" not in summary and "kimi-for-coding-highspeed" not in summary
  assert "[providers.kimi_tf]" in summary and "omp_kimi_tf_key ← kimi_tf" in summary
  assert "[local_values]" in summary and str(machine) in summary and str(keys) in summary
  assert "--machine workstation --profile omp-kernel model status --verbose" in summary
  assert cli.main(prefix + ["--verbose"]) == 0
  detailed = capsys.readouterr().out
  assert "完整模型目录" in detailed and "kimi-for-coding-highspeed" in detailed
  assert "--machine workstation --profile omp-kernel model url kimi_tf" in detailed
  assert "--machine workstation --profile omp-kernel model key kimi_tf" in detailed
  assert (machine.read_bytes(), keys.read_bytes()) == before


def test_presets_default_hides_public_reference_detail(capsys):
  assert cli.main(["model", "presets"]) == 0
  output = capsys.readouterr().out
  for model in ("deepseek-flash", "kimi-k3", "glm-5.3"):
    assert model in output
  assert "默认加入" in output and "model presets --verbose" in output
  assert "https://" not in output and "source:" not in output


def test_profiles_terminal_table_retains_pipe_tsv(monkeypatch, capsys):
  assert cli.main(["profiles"]) == 0
  assert "omp-kernel\tomp" in capsys.readouterr().out
  monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
  assert cli.main(["profiles"]) == 0
  output = capsys.readouterr().out
  assert "Profile" in output and "omp-kernel" in output and "\t" not in output


def test_missing_url_error_explains_reason_before_action_with_selectors(capsys):
  assert cli.main(["init-local", "--machine", "workstation", "--profile", "omp-kernel"]) == 0
  capsys.readouterr()
  assert cli.main(["--machine", "workstation", "plan", "--format", "json"]) == 2
  output = capsys.readouterr()
  assert output.out == ""
  assert output.err.index("原因:") < output.err.index("下一步:")
  assert "./agentcfg --machine workstation --profile omp-kernel model status" in output.err
  assert "doctor" not in output.err


def test_repeated_progress_snapshot_does_not_restart_wait_or_repeat(capsys):
  args = SimpleNamespace(command="sync")
  progress = Progress("sync", args)
  progress.stage("固定阶段", hint="doctor")
  started = progress.started
  progress.stage("固定阶段", hint="plan")
  assert progress.started == started and args.progress_hint == "plan"
  assert capsys.readouterr().err.count("固定阶段") == 1


def test_format_option_does_not_consume_native_arguments():
  parser = cli.build_parser()
  assert parser.parse_args(["usage", "--format", "native"]).passthrough == ["--format", "native"]
  assert parser.parse_args(["run", "--", "--format", "native"]).passthrough == ["--format", "native"]
  with pytest.raises(SystemExit) as error:
    parser.parse_args(["run", "--format", "json"])
  assert error.value.code == 2

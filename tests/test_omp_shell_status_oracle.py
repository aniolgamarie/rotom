"""不执行shell或生产TS，核对数字状态参数差量的独立预期。"""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/omp-shell-status-oracle.py"
spec = importlib.util.spec_from_file_location("status_oracle", SOURCE)
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def test_status_positions_quotes_and_redirections():
  assert oracle.expected_status_parse('ls missing; echo "exit=$?"') == {
    "status": "complete", "commands": [
      {"connector": "start", "argv": ["ls", "missing"]},
      {"connector": ";", "argv": ["echo", "exit=$?"], "statusExpansions": [1]},
    ],
  }
  assert oracle.expected_status_parse("printf '%s' $?")["commands"][0]["statusExpansions"] == [2]
  for command in ["echo '$?'", 'echo "\\$?"']:
    assert oracle.expected_status_parse(command) == {
      "status": "complete", "commands": [{"connector": "start", "argv": ["echo", "$?"]}],
    }
  assert "statusExpansions" not in oracle.expected_status_parse("echo \\$?")["commands"][0]
  assert oracle.expected_status_parse("echo ok # $?\nls")["commands"] == [
    {"connector": "start", "argv": ["echo", "ok"]}, {"connector": ";", "argv": ["ls"]},
  ]


def test_status_must_be_numeric_output_not_execution_or_target():
  for command in ["$? arg", "cat $?", "git show $?", "command -v $?", "sh -c 'echo $?'",
    "echo ok >$?", "echo ok 2>&$?", "echo ${?}", "echo $!", "echo $$", "echo $1",
    "echo $?$(id)", 'echo "exit=$? $PATH"', "sleep 1 & echo $!"]:
    assert oracle.expected_status_parse(command) == oracle.UNSUPPORTED


def test_frozen_independent_status_delta_reproduces_exact_entries():
  fixture = ROOT / "tests/fixtures/omp/command-scenarios/grammar-status-upgrade-20261010.json"
  raw = fixture.read_bytes()
  assert len(raw) == 105519
  assert hashlib.sha256(raw).hexdigest() == "64dcdb505c0e884fbbc5493fd3f750f1eb564969ef9f2d8030d05f1e679ebe5f"
  fixed = json.loads(raw)
  assert fixed == oracle.build_overlay()
  assert fixed["count"] == len({entry["id"] for entry in fixed["entries"]}) == 65
  assert fixed["sourceOracleSha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()

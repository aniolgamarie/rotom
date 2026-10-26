import hashlib
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("history_scenarios", ROOT / "scripts/omp-history-scenarios.py")
scenes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenes)


@pytest.fixture(autouse=True)
def history_temporary_root(tmp_path, isolated_environment, monkeypatch):
  # 合成压缩产物使用本测试的临时根，不借助系统 /tmp 路径豁免。
  monkeypatch.setattr(scenes.history.tempfile, "gettempdir", lambda: str(tmp_path))


def corpus(commands):
  counters = dict.fromkeys(("files", "events", "extracted", "unsupportedCommandCarrier", "malformed", "redactionSkipped",
    "dynamicCommandSkipped", "nonCommand", "jsScripts", "jsLiteralCommands", "jsUnresolvedCalls", "jsMalformedScripts", "secondPassSkipped"), 0)
  stats = {s: dict(counters) for s in scenes.history.SOURCES}
  stats["pi"]["extracted"] = len(commands)
  return {"schemaVersion": 1, "redactionVersion": 2, "publication": "private-review-required", "statistics": stats,
    "records": [{"id": hashlib.sha256(c.encode()).hexdigest(), "command": c, "sources": ["pi"], "occurrences": 1} for c in commands]}


@pytest.mark.parametrize("left,right", [
  ("ls first.txt", "ls second.txt"),
  ("cat '/REDACTED_PATH/file-a'", "cat '/REDACTED_PATH/file-b'"),
  ("echo 123", "echo 456"),
  ("git -C sample_one status", "git -C sample_two status"),
  ("echo alpha # note", "echo beta # comment"),
])
def test_ordinary_values_share_a_scenario(left, right):
  assert scenes.classify(left)[0] == scenes.classify(right)[0]


@pytest.mark.parametrize("left,right", [
  ("ls *.jar", 'ls "*.jar"'),
  ("ls prefix*", "ls *suffix"),
  ("ls a*b", "ls *ab"),
  ("ls **/*.txt", "ls */*.txt"),
  ("echo ''", "echo"),
  ("echo '' ''", "echo ''"),
  ("echo 'a'b", "echo 'ab'"),
  (r"echo a\ b", "echo 'a b'"),
  ("echo ok && pwd", "echo ok || pwd"),
  ("cat file | head", "head | cat file"),
  ("ls; rm -rf /", "rm -rf /; ls"),
  ("ls; ls", "ls"),
  ("rm -rf /", "rm -rf target"),
  ("rm -rf target", "rm -i target"),
  ("git push --force", "git push"),
  ("git -C sample push", "git -C sample status"),
  ("env DEMO=value rm -rf /", "env DEMO=value ls /"),
  ("cat file > output", "cat file >> output"),
  ("ls 2>/dev/null", "ls 1>/dev/null"),
  ("echo 2 > output", "echo 2>output"),
  ("ls > file", "ls >/dev/null"),
  ("ls < file", "ls > file"),
  ("echo x 2>&1", "echo x 2>&2"),
  ("echo x 1>&2", "echo x 1>&1"),
  ('sh -c "rm -rf /"', 'sh -c "ls /"'),
  ('command sh -c "rm -rf /"', 'command sh -c "ls /"'),
  ('sudo sh -c "rm -rf /"', 'sudo sh -c "ls /"'),
  ('env sh -c "rm -rf /"', 'env sh -c "ls /"'),
  ('timeout 5 sh -c "rm -rf /"', 'timeout 5 sh -c "ls /"'),
  ('busybox sh -c "rm -rf /"', 'busybox sh -c "ls /"'),
  ('launcher python -c "print(1)"', 'launcher python -c "print(2)"'),
  ('bash --command "rm -rf /"', 'bash --command "ls /"'),
  ('python --eval="print(1)"', 'python --eval="print(2)"'),
  ('env -S "rm -rf /"', 'env -S "ls /"'),
  ('python -c "print(1)"', 'python -c "print(2)"'),
  ("cp first.txt first.txt", "cp first.txt second.txt"),
  ("cp /etc/shadow target.txt", "cp target.txt /etc/shadow"),
  ("echo '# note'", "echo # note"),
  ("echo ok # note", "echo ok # ; rm -rf /"),
  ("echo ok # note", "echo ok # $(id)"),
  ("echo ok; pwd", "echo ok\npwd"),
  ("echo '$HOME'", 'echo "$HOME"'),
  ("echo ok", "echo 'ok"),
  ("cat <<EOF\nvalue\nEOF", "cat <<'EOF'\nvalue\nEOF"),
])
def test_distinct_syntax_or_risk_boundaries_do_not_merge(left, right):
  assert scenes.classify(left)[0] != scenes.classify(right)[0]


def test_groups_keep_shortest_deterministic_representative_and_all_occurrences():
  commands = ["ls shorter.txt", "ls a_longer_filename.txt", "ls *.jar", 'ls "*.jar"', "ls; rm -rf /"]
  result = scenes.compact(corpus(commands))
  assert result["selection"]["scenarioCount"] == 4
  assert result["selection"]["removedDuplicateCommands"] == 1
  assert result["selection"]["preservedOccurrences"] == 5
  group = next(r for r in result["records"] if r["scenario"]["members"] == 2)
  assert group["command"] == "ls shorter.txt"
  assert group["occurrences"] == 2
  assert scenes.compact(corpus(list(reversed(commands)))) == result
  assert result["selection"]["secondPassFailures"] == 0


def test_second_pass_refuses_unsanitized_input_without_echoing_it(tmp_path, capsys):
  data = corpus(["echo TOKEN=PrivateSentinel123"])
  input_path = tmp_path / "input.json"
  input_path.write_text(json.dumps(data))
  destination = tmp_path / "private/scenarios.json"
  assert scenes.main(["--input", str(input_path), "--output", str(destination)]) == 2
  assert not destination.exists()
  captured = capsys.readouterr()
  assert "PrivateSentinel123" not in captured.out + captured.err


def test_schema_and_identity_validation_fail_closed():
  data = corpus(["pwd"])
  with pytest.raises(ValueError):
    scenes.compact({**data, "unknown": True})
  with pytest.raises(ValueError):
    scenes.compact({**data, "redactionVersion": 1})
  with pytest.raises(ValueError):
    scenes.compact({**data, "schemaVersion": True})
  with pytest.raises(ValueError):
    scenes.compact({**data, "records": data["records"] * 2})
  data["records"][0]["occurrences"] = 2
  with pytest.raises(ValueError):
    scenes.compact(data)


def test_private_compressed_output_is_deterministic_and_has_no_filename(tmp_path):
  input_path = tmp_path / "input.json"
  input_path.write_text(json.dumps(corpus(["ls first.txt", "ls other.txt"])))
  outputs = [tmp_path / "private" / name for name in ("first.json.gz", "second.json.gz")]
  for output in outputs:
    assert scenes.main(["--input", str(input_path), "--output", str(output)]) == 0
    assert output.stat().st_mode & 0o777 == 0o600
  assert outputs[0].read_bytes() == outputs[1].read_bytes()
  assert outputs[0].read_bytes()[3] & 8 == 0
  assert json.loads(gzip.decompress(outputs[0].read_bytes())) == scenes.compact(corpus(["ls first.txt", "ls other.txt"]))
  assert scenes.main(["--input", str(input_path), "--output", str(outputs[0])]) == 2


def test_each_fixed_fixture_shape_survives_independent_of_parser_status():
  cases = json.loads((ROOT / "tests/fixtures/omp/command-history/cases.json").read_text())["cases"]
  results = {c["id"]: scenes.classify(c["command"]) for c in cases}
  assert len({r[0] for r in results.values()}) > 50
  assert all(results[i][1] == "comment" for i in ["H077", "H078", "H079"])
  assert len({results[i][0] for i in ["H077", "H078", "H079"]}) == 3
  assert scenes.classify("find sample -type f | head -50")[1] == "compound"
  assert scenes.classify("ls *.jar 2>/dev/null")[1] == "redirection"

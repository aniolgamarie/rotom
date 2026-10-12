"""只读日常oracle纯数据证据；不执行C++/Shell/编辑器或新进程。"""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).parent / "fixtures/pi/two-profiles/checker.py"


@pytest.fixture
def oracle():
  spec = importlib.util.spec_from_file_location("_daily_oracle", SOURCE)
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  return module


def observed(oracle, case="cpp"):
  records = [{"kind": "compiler", "exit_code": 0, "stdout": "", "stderr": ""}]
  if case == "cpp":
    records += [{"kind": "program", "key": key, "snapshot": snapshot, "exit_code": 0, "stdout": expected.decode(), "stderr": ""} for key, snapshot, expected in oracle.CASES]
    files = {}
  else:
    records = [{"kind": case, "exit_code": 0, "stdout": "alpha\nbeta\ngamma\n" if case == "shell" else "", "stderr": ""}]
    files = {"shell-lines.txt": "alpha\nbeta\ngamma\n"} if case == "shell" else {"editor-note.txt": "visibility: checked\nboundary: inclusive\n"}
  return {"schema_version": 2, "scenario_id": "daily-mvcc-boundary-v1", "case": case, "input_identity": "a" * 64, "records": records, "files": files}


def verify(oracle, value):
  return oracle.verify_observations(value, expected_input_identity="a" * 64)


def test_checker_has_no_process_start_or_write_api():
  tree = ast.parse(SOURCE.read_text())
  assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and "subprocess" in ast.unparse(node) for node in ast.walk(tree))
  assert not any(isinstance(node, ast.Attribute) and node.attr in {"write_bytes", "write_text", "mkdir", "chmod", "run", "Popen"} for node in ast.walk(tree))
  assert '"--run"' not in SOURCE.read_text()


@pytest.mark.parametrize("case,checks", [("cpp", 16), ("shell", 2), ("editor", 1)])
def test_only_independent_exact_results_match(oracle, case, checks):
  result = verify(oracle, observed(oracle, case))
  assert result == {"case": case, "result": "matched", "checks": checks, "failures": []}
  assert not any(key in result for key in ("terminated", "isolated", "passed"))


@pytest.mark.parametrize("fault", ["empty", "missing", "duplicate", "extra-case", "key-bool", "snapshot-bool", "compiler-failed", "program-failed", "exit-bool", "empty-output", "stdout-limit", "stderr-limit", "extra-root", "extra-record", "version-bool", "wrong-identity", "bad-identity", "unknown-case", "unexpected-files"])
def test_invalid_or_unusable_cpp_observations_fail_closed(oracle, fault):
  value = observed(oracle)
  if fault == "empty": value["records"] = []
  if fault == "missing": value["records"].pop()
  if fault == "duplicate": value["records"][-1] = deepcopy(value["records"][1])
  if fault == "extra-case": value["records"][1]["key"] = 999
  if fault == "key-bool": value["records"][1]["key"] = True
  if fault == "snapshot-bool": value["records"][1]["snapshot"] = False
  if fault == "compiler-failed": value["records"][0]["exit_code"] = 1
  if fault == "program-failed": value["records"][1]["exit_code"] = 1
  if fault == "exit-bool": value["records"][1]["exit_code"] = False
  if fault == "empty-output": value["records"][1]["stdout"] = ""
  if fault == "stdout-limit": value["records"][1]["stdout"] = "中" * 2731
  if fault == "stderr-limit": value["records"][1]["stderr"] = "x" * 8193
  if fault == "extra-root": value["isolated"] = True
  if fault == "extra-record": value["records"][1]["passed"] = True
  if fault == "version-bool": value["schema_version"] = True
  if fault == "wrong-identity": value["input_identity"] = "b" * 64
  if fault == "bad-identity": value["input_identity"] = "bad"
  if fault == "unknown-case": value["case"] = "other"
  if fault == "unexpected-files": value["files"]["expected.txt"] = "pass"
  with pytest.raises(ValueError, match="^DAILY_OBSERVATION_INVALID$"): verify(oracle, value)


def test_wrong_result_is_mismatch_even_when_program_exits_zero(oracle):
  value = observed(oracle); value["records"][3]["stdout"] = "missing\n"
  result = verify(oracle, value)
  assert result["result"] == "mismatch" and result["checks"] == 16 and result["failures"] == [{"key": 7, "snapshot": 2}]


@pytest.mark.parametrize("case", ["shell", "editor"])
def test_parent_file_content_is_an_independent_required_match(oracle, case):
  value = observed(oracle, case); value["files"][next(iter(value["files"]))] = "wrong\n"
  assert verify(oracle, value)["result"] == "mismatch"
  value["files"] = {}
  with pytest.raises(ValueError, match="DAILY_OBSERVATION_INVALID"): verify(oracle, value)


@pytest.mark.parametrize("raw", [b"", b"{}", b'{"x":1,"x":2}', b'{"x":NaN}', b"[1]"])
def test_json_missing_duplicate_or_nonfinite_rejects(oracle, tmp_path, raw):
  path = tmp_path / "observation.json"; path.write_bytes(raw)
  with pytest.raises(ValueError, match="DAILY_OBSERVATION_INVALID"):
    oracle.load_observations(path, expected_input_identity="a" * 64)


def test_real_bounded_file_read_and_json_oracle(oracle, tmp_path):
  path = tmp_path / "observation.json"; path.write_text(json.dumps(observed(oracle)))
  assert oracle.load_observations(path, expected_input_identity="a" * 64)["result"] == "matched"
  path.write_bytes(b"x" * (oracle.MAX_JSON_BYTES + 1))
  with pytest.raises(ValueError, match="DAILY_OBSERVATION_INVALID"):
    oracle.load_observations(path, expected_input_identity="a" * 64)


def test_large_lstat_refuses_before_open(oracle, tmp_path, monkeypatch):
  path = tmp_path / "large"; path.write_bytes(b"x" * (oracle.MAX_JSON_BYTES + 1))
  monkeypatch.setattr(oracle.os, "open", lambda *args: pytest.fail("must bound before open"))
  with pytest.raises(ValueError, match="DAILY_OBSERVATION_INVALID"):
    oracle.bounded_bytes(path, oracle.MAX_JSON_BYTES)


def test_file_growth_read_is_still_bounded(oracle, tmp_path, monkeypatch):
  path = tmp_path / "small"; path.write_bytes(b"x")
  calls = []
  def read(fd, count):
    calls.append(count); return b"x" * count
  monkeypatch.setattr(oracle.os, "read", read)
  with pytest.raises(ValueError, match="DAILY_OBSERVATION_INVALID"): oracle.bounded_bytes(path, 10)
  assert sum(calls) <= 11


def test_symlink_is_not_followed(oracle, tmp_path):
  target = tmp_path / "target"; target.write_text("{}")
  path = tmp_path / "link"; path.symlink_to(target)
  with pytest.raises(ValueError, match="DAILY_OBSERVATION_INVALID"): oracle.bounded_bytes(path, 100)


def test_regular_to_fifo_replacement_cannot_block_open_or_reach_read(oracle, tmp_path, monkeypatch):
  path = tmp_path / "replaced"; path.write_text("original")
  original_open = oracle.os.open; opened = []
  def raced_open(target, flags):
    # 旧实现缺NONBLOCK时直接失败，测试自身绝不等待FIFO writer。
    assert flags & oracle.os.O_NONBLOCK
    path.unlink(); oracle.os.mkfifo(path, 0o600)
    fd = original_open(target, flags); opened.append(fd); return fd
  monkeypatch.setattr(oracle.os, "open", raced_open)
  monkeypatch.setattr(oracle.os, "read", lambda *args: pytest.fail("replaced object must not be read"))
  with pytest.raises(ValueError, match="DAILY_OBSERVATION_INVALID"): oracle.bounded_bytes(path, 100)
  assert len(opened) == 1
  with pytest.raises(OSError): oracle.os.fstat(opened[0])


def test_default_static_is_not_run_and_creates_nothing(oracle, tmp_path):
  tmp_path.chmod(0o700)
  (tmp_path / "main.cpp").write_text("synthetic source")
  (tmp_path / "editor-note.txt").write_text("visibility: pending\nboundary: inclusive\n")
  before = sorted(path.name for path in tmp_path.iterdir())
  assert oracle.static(tmp_path) == {"scenario_id": "daily-mvcc-boundary-v1", "result": "not-run", "checks": 0, "layer": "static"}
  assert sorted(path.name for path in tmp_path.iterdir()) == before


@pytest.mark.parametrize("bad", ["a" * 63, "A" * 64, True, None])
def test_expected_identity_cannot_be_absent_or_malformed(oracle, bad):
  with pytest.raises(ValueError, match="DAILY_OBSERVATION_INVALID"):
    oracle.verify_observations(observed(oracle), expected_input_identity=bad)


def test_fixture_has_no_passing_product_claim(oracle):
  value = observed(oracle); value["records"][1]["stdout"] = "value=999\n"
  assert verify(oracle, value)["result"] == "mismatch"
  assert "--compiler" not in SOURCE.read_text() and "--editor" not in SOURCE.read_text()

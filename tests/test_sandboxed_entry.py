"""显式 bwrap 入口的离线契约；默认仅使用合成文件和进程替身。"""

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def executor(tmp_path, monkeypatch):
  script = Path(__file__).resolve().parents[1] / "scripts/test-sandboxed.py"
  spec = importlib.util.spec_from_file_location("sandboxed_tests", script)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  repository = tmp_path / "repository"
  repository.mkdir()
  files = {"pyproject.toml": b"[tool.pytest.ini_options]\n", "uv.lock": b"synthetic lock\n",
           "src/agentcfg/fixture.py": b"synthetic source\n", "locks/fixture.json": b"{}\n"}
  for name, data in files.items():
    target = repository / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
  venv = tmp_path / "venv"
  (venv / "bin").mkdir(parents=True)
  (venv / "pyvenv.cfg").write_text("version = 3.11.9\nhome = /synthetic/bin\n")
  distribution = tmp_path / "python-distribution"
  (distribution / "bin").mkdir(parents=True)
  python = distribution / "bin/python3.11"
  python.write_bytes(b"synthetic Python; never executed\n")
  python.chmod(0o700)
  standard_library = distribution / "lib/python3.11"
  standard_library.mkdir(parents=True)
  (standard_library / "os.py").write_bytes(b"synthetic standard library; never imported\n")
  (venv / "bin/python").symlink_to(python)
  bwrap = tmp_path / "bwrap"
  bwrap.write_bytes(b"synthetic bwrap; never executed\n")
  bwrap.chmod(0o700)
  monkeypatch.setattr(module, "ROOT", repository)
  monkeypatch.setattr(module, "BWRAP", bwrap)
  monkeypatch.setattr(module, "SYSTEM", ())
  calls = []
  fixture = SimpleNamespace(module=module, repository=repository, venv=venv, files=files,
                            evidence=tmp_path / "evidence", calls=calls, baseline_exit=0, pytest_exit=0, timeout=False,
                            distribution=distribution)
  def run(argv, **kwargs):
    calls.append((list(argv), kwargs))
    if argv[0] == module.GIT:
      assert kwargs["cwd"] == repository
      return subprocess.CompletedProcess(argv, 0, "\0".join(files).encode() + b"\0", b"")
    assert argv[0] == str(bwrap)
    assert kwargs["env"] == module.ENVIRONMENT
    if fixture.timeout:
      raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
    kwargs["stdout"].write(b"synthetic bounded child log\n")
    code = fixture.baseline_exit if "-c" in argv else fixture.pytest_exit
    return subprocess.CompletedProcess(argv, code)
  monkeypatch.setattr(module.subprocess, "run", run)
  return fixture


def invoke(executor, *, suite="full"):
  return executor.module.main(["--allow-sandbox", "--evidence", str(executor.evidence), "--venv", str(executor.venv), "--suite", suite])


def test_sandbox_entry_requires_explicit_consent_before_writes_or_processes(executor, capsys):
  with pytest.raises(SystemExit) as caught:
    executor.module.main(["--evidence", str(executor.evidence), "--venv", str(executor.venv)])
  assert caught.value.code == 2
  assert "--allow-sandbox is required" in capsys.readouterr().err
  assert not executor.evidence.exists()
  assert executor.calls == []


def test_sandbox_entry_exact_mounts_snapshot_and_empty_environment(executor, monkeypatch, capsys):
  monkeypatch.setenv("PRIVATE_EXECUTOR_CANARY", "private-environment-value")
  assert invoke(executor) == 0
  stdout = capsys.readouterr().out
  assert json.loads(stdout)["status"] == "PASS"
  assert "private-environment-value" not in stdout
  assert str(executor.evidence) not in stdout
  report = json.loads((executor.evidence / "result.json").read_text())
  assert report["status"] == "PASS"
  assert set(report["source_manifest"]) == set(executor.files)
  assert set(report["lock_identity"]) == {"uv.lock", "locks/fixture.json"}
  assert (executor.evidence / "source/.venv").resolve() == executor.venv
  for name, data in executor.files.items():
    assert (executor.evidence / "source" / name).read_bytes() == data
  for argv, kwargs in executor.calls[1:]:
    assert kwargs["cwd"] == executor.repository
    assert kwargs["env"] == executor.module.ENVIRONMENT
    assert 0 < kwargs["timeout"] <= 7200
    assert "--clearenv" not in argv
    for flag in ("--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts", "--die-with-parent"):
      assert flag in argv
    writable = [argv[index + 1:index + 3] for index, item in enumerate(argv) if item == "--bind"]
    assert writable == [[str(executor.evidence / "output"), "/evidence"]]
    readonly = [argv[index + 1:index + 3] for index, item in enumerate(argv) if item == "--ro-bind"]
    assert [str(executor.evidence / "source"), "/workspace/rotom"] in readonly
    assert [str(executor.venv), str(executor.venv)] in readonly
    assert argv.index("--tmpfs", argv.index("--tmpfs") + 1) < argv.index("--ro-bind")
    assert argv.index("--bind") < argv.index("--remount-ro")
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert ["--remount-ro", "/"] == argv[argv.index("--cap-drop") - 2:argv.index("--cap-drop")]
  assert executor.calls[-1][0][-len(executor.module.PYTEST):] == executor.module.PYTEST
  assert stat.S_IMODE(executor.evidence.stat().st_mode) == 0o700
  for path in [executor.evidence / "result.json", *sorted((executor.evidence / "output").iterdir())]:
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("failure", ["baseline", "timeout"])
def test_sandbox_entry_never_runs_pytest_after_failed_baseline(executor, failure, capsys):
  executor.baseline_exit = 1
  executor.timeout = failure == "timeout"
  assert invoke(executor) == 1
  report = json.loads((executor.evidence / "result.json").read_text())
  assert report["status"] == "BLOCKED"
  assert not any("pytest" in argv for argv, _ in executor.calls)
  assert len(executor.calls) == 2
  recorded = json.loads((executor.evidence / "output/baseline-argv.json").read_text())
  assert recorded["argv"] == executor.calls[-1][0]
  if failure == "timeout":
    assert json.loads((executor.evidence / "output/baseline-result.json").read_text())["exit_code"] is None
  assert "supported outer userns executor" in capsys.readouterr().out


def test_sandbox_entry_retains_real_pytest_failure_category(executor, capsys):
  executor.pytest_exit = 1
  assert invoke(executor) == 1
  report = json.loads((executor.evidence / "result.json").read_text())
  assert report["status"] == "FAIL"
  assert report["stages"][-1]["exit_code"] == 1
  assert json.loads(capsys.readouterr().out)["reason"] == "offline_pytest_failed"


def test_sandbox_entry_does_not_read_symlinked_source(executor, tmp_path):
  outside = tmp_path / "private-canary"
  outside.write_bytes(b"synthetic private canary\n")
  source = executor.repository / "src/agentcfg/fixture.py"
  source.unlink()
  source.symlink_to(outside)
  assert invoke(executor) == 1
  report = json.loads((executor.evidence / "result.json").read_text())
  assert (report["status"], report["reason"]) == ("BLOCKED", "symlinked_tracked_source")
  assert len(executor.calls) == 1
  assert "synthetic private canary" not in (executor.evidence / "result.json").read_text()


def test_sandbox_entry_missing_tool_does_not_fall_back(executor, monkeypatch):
  monkeypatch.setattr(executor.module, "BWRAP", executor.repository / "missing-bwrap")
  assert invoke(executor) == 1
  assert executor.calls == []
  assert json.loads((executor.evidence / "result.json").read_text())["status"] == "BLOCKED"


def test_sandbox_entry_existing_evidence_is_not_changed(executor):
  executor.evidence.mkdir()
  sentinel = executor.evidence / "untouched"
  sentinel.write_bytes(b"sentinel")
  with pytest.raises(SystemExit) as caught:
    invoke(executor)
  assert caught.value.code == 2
  assert sentinel.read_bytes() == b"sentinel"
  assert list(executor.evidence.iterdir()) == [sentinel]
  assert executor.calls == []


def test_sandbox_entry_rejects_unprepared_python_without_starting_executor(executor):
  (executor.venv / "pyvenv.cfg").write_text("version = 3.10.9\n")
  assert invoke(executor) == 1
  assert executor.calls == []
  report = json.loads((executor.evidence / "result.json").read_text())
  assert (report["status"], report["reason"]) == ("BLOCKED", "python_311_or_newer_required")


@pytest.mark.parametrize("protected", ["/", "/home", "/root", "/run/user", "/tmp", "/var/tmp"])
def test_sandbox_entry_rejects_account_or_root_binding(executor, protected):
  with pytest.raises(executor.module.Blocked, match="unsafe_python_binding"):
    executor.module.validate_binding(Path(protected))


@pytest.mark.parametrize("source", ["environment_home", "account_home", "source_ancestor"])
def test_sandbox_entry_binding_guards_do_not_trust_home_environment_alone(executor, monkeypatch, source):
  if source == "environment_home":
    monkeypatch.setenv("HOME", str(executor.venv))
  elif source == "account_home":
    monkeypatch.setenv("HOME", "/synthetic-unrelated-home")
    monkeypatch.setattr(executor.module.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(executor.distribution)))
  else:
    monkeypatch.setattr(executor.module, "ROOT", executor.distribution / "repository")
  assert invoke(executor) == 1
  assert executor.calls == []
  report = json.loads((executor.evidence / "result.json").read_text())
  assert (report["status"], report["reason"]) == ("BLOCKED", "unsafe_python_binding")


def test_sandbox_entry_refuses_to_expand_nonstandard_distribution(executor):
  (executor.distribution / "lib/python3.11/os.py").unlink()
  assert invoke(executor) == 1
  assert executor.calls == []
  report = json.loads((executor.evidence / "result.json").read_text())
  assert report["reason"] == "unsupported_python_distribution_layout"


def test_sandbox_entry_records_interruption_before_returning_blocked(executor, monkeypatch):
  original = executor.module.subprocess.run
  def interrupted(argv, **kwargs):
    if argv[0] != executor.module.GIT:
      raise KeyboardInterrupt()
    return original(argv, **kwargs)
  monkeypatch.setattr(executor.module.subprocess, "run", interrupted)
  assert invoke(executor) == 1
  report = json.loads((executor.evidence / "result.json").read_text())
  assert report["status"] == "BLOCKED"
  assert report["reason"] == "executor_interrupted"
  stage = json.loads((executor.evidence / "output/baseline-result.json").read_text())
  assert (stage["reason"], stage["exit_code"]) == ("interrupted", None)
  assert (executor.evidence / "output/baseline-argv.json").is_file()


def test_sandbox_entry_explicit_home_subtrees_do_not_mount_home_parent(executor, monkeypatch):
  synthetic_home = executor.venv.parent
  for name in ("synthetic-auth-sibling", "synthetic-session-sibling"):
    (synthetic_home / name).mkdir()
  monkeypatch.setenv("HOME", str(synthetic_home))
  monkeypatch.setattr(executor.module.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(synthetic_home)))
  assert invoke(executor) == 0
  for argv, _ in executor.calls[1:]:
    readonly = [argv[index + 1:index + 3] for index, item in enumerate(argv) if item == "--ro-bind"]
    assert [str(executor.venv), str(executor.venv)] in readonly
    assert [str(executor.distribution), str(executor.distribution)] in readonly
    assert [str(synthetic_home), str(synthetic_home)] not in readonly
    assert not any(str(synthetic_home / name) in pair for pair in readonly
                   for name in ("synthetic-auth-sibling", "synthetic-session-sibling"))


def test_sandbox_entry_filesystem_suite_has_only_fixed_testfiles(executor):
  assert invoke(executor, suite="filesystem") == 0
  command = executor.calls[-1][0]
  assert command[-2:] == ["tests/test_paths.py", "tests/test_execution_environment.py"]
  report = json.loads((executor.evidence / "result.json").read_text())
  assert report["suite"] == "filesystem"


def test_sandbox_entry_rejects_arbitrary_suite_without_processes(executor):
  with pytest.raises(SystemExit) as caught:
    invoke(executor, suite="--allow-host")
  assert caught.value.code == 2
  assert executor.calls == []

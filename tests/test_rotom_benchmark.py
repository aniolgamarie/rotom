"""只验证合成负载与隔离边界；默认 pytest 不启动基准冷进程。"""

import importlib.util
import json
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def benchmark():
  path = Path(__file__).parent / "benchmarks/rotom_cli.py"
  spec = importlib.util.spec_from_file_location("rotom_benchmark", path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


@pytest.fixture
def public_source(tmp_path):
  source = tmp_path / "public-source"
  for relative in ("rotom", "src/rotom/cli.py", "src/agentcfg/workspace.py",
      "schemas/rotom/run-record.schema.json", "shared/registry.toml", "agents/dsh/agent.toml",
      ".private/secret", ".git/config", ".cache/host.py", "agents/dsh/packages/host/index.py"):
    path = source / relative
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text("synthetic source\n")
  return source


def test_public_snapshot_uses_allowlist_without_copying_private_or_host_inputs(benchmark, public_source, tmp_path):
  work = benchmark.build_workload(public_source, tmp_path / "empty", {"public_profiles": 0,
    "machines": 0, "runs": 0}, tmp_path / "prepared-venv")
  names = set(work["source_manifest"])
  assert {"rotom", "src/rotom/cli.py", "src/agentcfg/workspace.py"} <= names
  assert not any(name.startswith((".private/", ".git/", ".cache/", "agents/dsh/packages/")) for name in names)
  assert not (work["checkout"] / ".private").exists()
  assert (work["checkout"] / ".venv").is_symlink()


def test_versioned_catalog_has_exact_public_profile_and_machine_counts(benchmark, public_source, tmp_path):
  definition = json.loads(benchmark.CONVENTION.read_text())["workloads"]["catalog"]
  work = benchmark.build_workload(public_source, tmp_path / "catalog", definition, tmp_path / "prepared-venv")
  assert len(work["profiles"]) == len(list((work["checkout"] / "profiles").glob("*.toml"))) == 100
  machines = Path(work["environment"]["XDG_CONFIG_HOME"]) / "agentcfg/machines"
  assert len(work["machines"]) == len(list(machines.glob("*.toml"))) == 32
  assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in machines.glob("*.toml"))


def test_thousand_run_workload_is_strict_v2_and_never_contains_active_processes(benchmark, public_source, tmp_path):
  from agentcfg import lifecycle, run_owners
  definition = json.loads(benchmark.CONVENTION.read_text())["workloads"]["runs"]
  work = benchmark.build_workload(public_source, tmp_path / "runs", definition, tmp_path / "prepared-venv")
  profile = work["profiles"][0]
  root = Path(work["environment"]["XDG_STATE_HOME"]) / "agentcfg/dsh" / profile
  instance = Path(work["environment"]["XDG_DATA_HOME"]) / "agentcfg/instances/dsh" / profile
  local = Path(work["environment"]["XDG_CONFIG_HOME"]) / "agentcfg/machines/bench-machine-000.toml"
  workspace = SimpleNamespace(instance=instance, state_root=root, profile=profile,
    binding={"machine": "bench-machine-000", "local": str(local), "profile": profile})
  before = benchmark.snapshot(work["root"])
  with lifecycle.guard(workspace, create=False, shared=True):
    records = run_owners.Registry(root / "run-owners", workspace.binding).snapshot()
  assert len(records) == 1000
  assert {record["schema_version"] for record in records.values()} == {2}
  assert {record["lifecycle_state"] for record in records.values()} == {"unknown", "idle_confirmed"}
  assert all(record["session_observation"] is record["terminal_ref"] is None for record in records.values())
  assert benchmark.snapshot(work["root"]) == before


def test_cold_process_contract_uses_fresh_environment_and_validates_each_result(benchmark, public_source,
    tmp_path, monkeypatch):
  monkeypatch.setenv("SYNTHETIC_PARENT_SECRET", "never-forward-this")
  work = benchmark.build_workload(public_source, tmp_path / "empty", {"public_profiles": 0,
    "machines": 0, "runs": 0}, tmp_path / "prepared-venv")
  calls = []
  def cold(argv, **options):
    calls.append((argv, options))
    assert options["env"] == work["environment"]
    assert "SYNTHETIC_PARENT_SECRET" not in options["env"]
    assert all(Path(options["env"][key]).is_relative_to(work["root"]) for key in
      ("HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "TMPDIR", "PATH", "PYTHONPATH"))
    assert options["stdin"] == subprocess.DEVNULL
    return subprocess.CompletedProcess(argv, 0, b"usage: rotom\n", b"")
  monkeypatch.setattr(benchmark.subprocess, "run", cold)
  output = tmp_path / "report"
  output.mkdir(mode=0o700)
  scenario = json.loads(benchmark.CONVENTION.read_text())["scenarios"][0]
  result = benchmark.measure(scenario, work, Path("/prepared/python"), 3, output)
  assert len(calls) == len(result["samples"]) == 3
  assert all(call[0][-1] == "--help" for call in calls)
  assert result["passed"] and result["readonly_unchanged"]


def test_correct_exit_cannot_hide_missing_or_wrong_candidates(benchmark):
  scenario = {"output": "machines"}
  assert not benchmark.valid_output(scenario, {"machines": ["machine-a"]}, b"")
  assert not benchmark.valid_output(scenario, {"machines": ["machine-a"]}, b"machine-b\0")


def test_single_scenario_selection_keeps_fixture_defined_sample_count(benchmark):
  convention = json.loads(benchmark.CONVENTION.read_text())
  args = benchmark.build_parser(convention).parse_args(["--output", "/tmp/example-report",
    "--scenario", "complete-catalog-profiles"])
  assert args.scenario == ["complete-catalog-profiles"] and args.phase is None
  assert convention["iterations"] == 30


@pytest.mark.parametrize("arguments", [["--scenario", "invented"],
  ["--scenario", "list-runs", "--phase", "help"], ["--iterations", "1"]])
def test_scenario_selection_cannot_invent_workloads_or_reduce_iterations(benchmark, arguments):
  convention = json.loads(benchmark.CONVENTION.read_text())
  with pytest.raises(SystemExit) as caught:
    benchmark.build_parser(convention).parse_args(["--output", "/tmp/example-report", *arguments])
  assert caught.value.code == 2


@pytest.mark.parametrize("location", ["relative", "inside", "existing", "alias", "outer-repository", "detached-worktree"])
def test_raw_measurements_cannot_be_written_into_a_repository_or_existing_directory(benchmark,
    public_source, tmp_path, location):
  repository = public_source
  if location == "relative":
    output = Path("relative-benchmark-results")
  elif location == "inside":
    output = repository / "raw-results"
  elif location == "existing":
    output = tmp_path / "already-present"
    output.mkdir(mode=0o700)
  elif location == "alias":
    alias = tmp_path / "checkout-alias"
    alias.symlink_to(repository, target_is_directory=True)
    output = alias / "raw-results"
  else:
    outer = tmp_path / "outer-repository"
    (outer / ".git").mkdir(parents=True)
    repository = tmp_path / "detached-worktree" if location == "detached-worktree" else outer / "nested-worktree"
    repository.mkdir()
    (repository / ".git").write_text("gitdir: " + str(outer / ".git/worktrees/synthetic-worktree") + "\n")
    output = outer / "raw-results"
  with pytest.raises(ValueError):
    benchmark.validate_output(output, repository)
  assert not output.exists() or location == "existing"


def test_new_absolute_output_outside_repositories_is_accepted_without_creating_it(benchmark,
    public_source, tmp_path):
  output = tmp_path / "private-measurements"
  assert benchmark.validate_output(output, public_source) == output
  assert not output.exists()


def test_unrelated_git_marker_is_not_project_ownership(benchmark, public_source, tmp_path):
  unrelated = tmp_path / "unrelated-directory"
  (unrelated / ".git").mkdir(parents=True)
  output = unrelated / "private-measurements"
  assert benchmark.validate_output(output, public_source) == output
  assert not output.exists()

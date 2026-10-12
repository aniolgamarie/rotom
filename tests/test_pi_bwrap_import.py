"""显式导入只写经验证内容寻址片段；不执行构建或产物。"""
import hashlib
import json
from pathlib import Path
import stat

import pytest

from agentcfg import pi_bwrap_import as importer
from agentcfg import pi_built_assets as assets, pi_bwrap_build as build
from agentcfg.pi_lock_layout import dependency_layout
from agentcfg.schema import ConfigError
from test_pi_built_assets import built_fixture


def fixture(tmp_path, monkeypatch):
  staging = tmp_path / "staging"; staging.mkdir(mode=0o700)
  source, record, archive = built_fixture(staging, monkeypatch)
  candidate = tmp_path / "candidate"; candidate.mkdir(mode=0o700)
  sources = tmp_path / "sources"; sources.mkdir(mode=0o700)
  (candidate / "candidate.json").write_bytes(build._json(record))
  (candidate / record["archive"]).write_bytes(archive)
  for key, item in build.INPUTS.items(): (sources / item["name"]).write_bytes(key.encode())
  for directory in (candidate, sources):
    for path in directory.iterdir(): path.chmod(0o600)
  repository = tmp_path / "repository"; repository.mkdir(mode=0o700)
  return repository, candidate, sources, record, archive


def files(repository):
  return {str(path.relative_to(repository)): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
    for path in repository.rglob("*") if path.is_file()}


def test_import_is_content_addressed_and_idempotent(tmp_path, monkeypatch):
  repository, candidate, sources, record, archive = fixture(tmp_path, monkeypatch)
  sentinel = repository / "sentinel"; sentinel.write_bytes(b"preserve")
  source = importer.import_candidate(repository, candidate, sources)
  assert "url" not in source
  assert source["vendor_path"] == "vendor/pi-bwrap-" + record["archive_sha256"] + ".tar.gz"
  assert source["license_files"] == ["agents/pi/build/licenses/bubblewrap-0.13.0/COPYING", "agents/pi/build/licenses/libcap-2.77/License"]
  assert assets.load_record(repository, dependency_layout(family="modern"), source) == record
  assert (repository / "locks/pi-modern" / source["vendor_path"]).read_bytes() == archive
  before = files(repository)
  assert importer.import_candidate(repository, candidate, sources) == source
  assert files(repository) == before and sentinel.read_bytes() == b"preserve"
  assert all(mode == 0o600 for name, (_, mode) in before.items() if name != "sentinel")
  assert not (repository / "agents/pi/dependencies-modern.json").exists()


@pytest.mark.parametrize("bad", ["input", "record", "archive", "duplicate-json", "candidate-link", "input-link"])
def test_invalid_inputs_produce_no_repository_writes(tmp_path, monkeypatch, bad):
  repository, candidate, sources, record, archive = fixture(tmp_path, monkeypatch)
  if bad == "input": (sources / build.INPUTS["libcap"]["name"]).write_bytes(b"private-marker")
  elif bad == "record": record["status"] = "passed"; (candidate / "candidate.json").write_bytes(build._json(record))
  elif bad == "archive": (candidate / record["archive"]).write_bytes(b"private-marker")
  elif bad == "duplicate-json": (candidate / "candidate.json").write_bytes(b'{"schema_version":1,"schema_version":1}')
  else:
    path = candidate / "candidate.json" if bad == "candidate-link" else sources / build.INPUTS["libcap"]["name"]
    path.rename(path.with_suffix(".original")); path.symlink_to(path.with_suffix(".original"))
  with pytest.raises(ConfigError) as error: importer.import_candidate(repository, candidate, sources)
  assert "private-marker" not in str(error.value) and list(repository.iterdir()) == []


@pytest.mark.parametrize("bad", ["different", "symlink", "hardlink", "mode"])
def test_all_targets_are_prechecked_before_any_write(tmp_path, monkeypatch, bad):
  repository, candidate, sources, _, _ = fixture(tmp_path, monkeypatch)
  target = repository / "agents/pi/build/licenses/libcap-2.77/License"
  target.parent.mkdir(parents=True, mode=0o700)
  if bad == "symlink": target.symlink_to(candidate / "candidate.json")
  elif bad == "hardlink":
    import os
    os.link(candidate / "candidate.json", target)
  else:
    target.write_bytes(b"different" if bad == "different" else b"libcap license")
    target.chmod(0o600 if bad == "different" else 0o666)
  with pytest.raises(ConfigError): importer.import_candidate(repository, candidate, sources)
  assert not (repository / "locks").exists()


def test_interrupted_verified_import_can_be_completed_without_overwrite(tmp_path, monkeypatch):
  repository, candidate, sources, _, _ = fixture(tmp_path, monkeypatch)
  original = importer.Tree.write_new; calls = []
  def fail(self, name, raw):
    calls.append(name)
    if len(calls) == 3: raise OSError("private-marker")
    return original(self, name, raw)
  monkeypatch.setattr(importer.Tree, "write_new", fail)
  with pytest.raises(ConfigError): importer.import_candidate(repository, candidate, sources)
  partial = files(repository); assert len(partial) == 2
  monkeypatch.setattr(importer.Tree, "write_new", original)
  source = importer.import_candidate(repository, candidate, sources)
  assert all(files(repository)[name] == value for name, value in partial.items())
  assert assets.load_record(repository, dependency_layout(family="modern"), source)["status"] == "built-not-executed"


def test_target_ancestor_link_cannot_redirect_import(tmp_path, monkeypatch):
  repository, candidate, sources, _, _ = fixture(tmp_path, monkeypatch)
  external = tmp_path / "external"; external.mkdir(mode=0o700)
  (repository / "locks").symlink_to(external, target_is_directory=True)
  with pytest.raises(ConfigError): importer.import_candidate(repository, candidate, sources)
  assert list(external.iterdir()) == [] and not (repository / "agents").exists()


def test_cli_outputs_only_source_and_rejects_unknown_arguments(tmp_path, monkeypatch, capsys):
  import runpy
  repository, candidate, sources, _, _ = fixture(tmp_path, monkeypatch)
  namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/import-pi-bwrap.py"))
  assert namespace["main"](["--repository", str(repository), "--candidate", str(candidate), "--sources", str(sources)]) == 0
  source = json.loads(capsys.readouterr().out)
  assert source["build_record"]["recipe"] == "bubblewrap-v1" and "url" not in source
  assert namespace["main"](["--unknown-private-marker"]) == 2
  output = capsys.readouterr()
  assert "private-marker" not in output.err and output.out == ""


def test_incomplete_input_is_not_filled_from_candidate_staging(tmp_path, monkeypatch):
  repository, candidate, sources, _, _ = fixture(tmp_path, monkeypatch)
  (sources / build.INPUTS["meson"]["name"]).unlink()
  with pytest.raises(ConfigError): importer.import_candidate(repository, candidate, sources)
  assert list(repository.iterdir()) == []


def test_git_checkout_public_0644_files_import_idempotently(tmp_path, monkeypatch):
  repository, candidate, sources, _, _ = fixture(tmp_path, monkeypatch)
  source = importer.import_candidate(repository, candidate, sources)
  for path in repository.rglob("*"):
    if path.is_file(): path.chmod(0o644)
  before = files(repository)
  assert importer.import_candidate(repository, candidate, sources) == source
  assert files(repository) == before
  assert all(mode == 0o644 for _, mode in before.values())

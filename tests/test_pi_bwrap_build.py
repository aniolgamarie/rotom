"""原生依赖构建只在显式入口执行；默认测试用假构建器，不执行编译器或宿主。"""
import hashlib
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

from agentcfg import pi_bwrap_build as build
from agentcfg.schema import ConfigError


def inputs(monkeypatch):
  monkeypatch.setattr(build, "verified_inputs", lambda _root: {
    "bwrap-source": (("COPYING", b"bubblewrap license", 0o644),),
    "libcap": (("License", b"libcap license", 0o644),),
    "meson": (("mesonbuild/__init__.py", b"", 0o644),)})
  monkeypatch.setattr(build, "bootstrap_identity", lambda: {"path": "/usr/bin/bwrap", "sha256": "a" * 64})


def elf():
  raw = bytearray(64); raw[:6] = b"\x7fELF\x02\x01"; raw[16:20] = b"\x03\x00\x3e\x00"
  return bytes(raw)


def fake_build(calls):
  def run(argv, **kwargs):
    calls.append((argv, kwargs))
    work = Path(argv[argv.index("--bind") + 1])
    (work / "bwrap-build").mkdir()
    (work / "bwrap-build/bwrap").write_bytes(elf())
    (work / "bwrap-build/bwrap").chmod(0o700)
    (work / "build-observation.json").write_text(json.dumps({"schema_version": 1,
      "toolchains": {**{name: {"path": "/usr/bin/" + name, "sha256": "b" * 64, "version": "synthetic compiler"} for name in build.TOOLS}, "meson": {"version": "1.9.0"}}, "needed": ["libc.so.6"], "glibc_versions": ["GLIBC_2.28"]}))
    return SimpleNamespace(returncode=0)
  return run


def test_candidate_uses_offline_isolated_builder_and_never_executes_result(tmp_path, monkeypatch):
  inputs(monkeypatch); calls = []
  monkeypatch.setattr(build.subprocess, "run", fake_build(calls))
  output = tmp_path / "candidate"
  result = build.build_candidate(tmp_path, output)
  assert result["status"] == "built-not-executed"
  assert result["binary_sha256"] == hashlib.sha256(elf()).hexdigest()
  assert len(calls) == 1
  argv, options = calls[0]
  assert argv[0] == "/usr/bin/bwrap" and "--unshare-all" in argv and "--cap-drop" in argv
  assert "--share-net" not in argv and "--ro-bind" in argv
  assert not any("pi-home" in str(value) or str(Path.home()) == value for value in argv)
  assert options["env"]["HOME"] == "/work/home"
  assert set(options["env"]) == {"HOME", "PATH", "LC_ALL", "TMPDIR", "SOURCE_DATE_EPOCH", "PYTHONNOUSERSITE"}
  assert options["timeout"] == 300
  archive = output / result["archive"]
  assert hashlib.sha256(archive.read_bytes()).hexdigest() == result["archive_sha256"]
  with tarfile.open(archive, "r:gz") as packed:
    assert packed.extractfile("bin/pi-bwrap").read() == elf()
    assert packed.extractfile("licenses/bubblewrap-COPYING").read() == b"bubblewrap license"
    assert packed.extractfile("licenses/libcap-License").read() == b"libcap license"
  assert (output / "candidate.json").is_file()


def test_existing_output_is_untouched_before_build(tmp_path, monkeypatch):
  output = tmp_path / "candidate"; output.mkdir(mode=0o700)
  sentinel = output / "sentinel"; sentinel.write_bytes(b"preserve")
  calls = []
  monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: calls.append(a))
  with pytest.raises(ConfigError): build.build_candidate(tmp_path, output)
  assert sentinel.read_bytes() == b"preserve" and calls == []


def test_invalid_input_fails_before_output_or_process(tmp_path, monkeypatch):
  calls = []
  monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: calls.append(a))
  with pytest.raises(ConfigError): build.build_candidate(tmp_path, tmp_path / "candidate")
  assert calls == [] and not (tmp_path / "candidate").exists()


@pytest.mark.parametrize("corruption", ["process-failed", "wrong-elf", "unexpected-library", "linked-output"])
def test_failed_build_never_publishes_candidate(tmp_path, monkeypatch, corruption):
  inputs(monkeypatch); calls = []
  def run(argv, **kwargs):
    result = fake_build(calls)(argv, **kwargs)
    work = Path(argv[argv.index("--bind") + 1])
    if corruption == "process-failed": result.returncode = 1
    if corruption == "wrong-elf": (work / "bwrap-build/bwrap").write_bytes(b"#!/bin/sh")
    if corruption == "unexpected-library":
      record = json.loads((work / "build-observation.json").read_text())
      record["needed"].append("libcap.so.2")
      (work / "build-observation.json").write_text(json.dumps(record))
    if corruption == "linked-output":
      (work / "bwrap-build/bwrap").rename(work / "real")
      (work / "bwrap-build/bwrap").symlink_to(work / "real")
    return result
  monkeypatch.setattr(build.subprocess, "run", run)
  output = tmp_path / "candidate"
  with pytest.raises(ConfigError): build.build_candidate(tmp_path, output)
  assert not (output / "candidate.json").exists()
  assert not list(output.glob("*.tar.gz"))


def test_empty_existing_output_also_refuses(tmp_path, monkeypatch):
  inputs(monkeypatch)
  output = tmp_path / "empty"; output.mkdir(mode=0o700)
  monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: pytest.fail("must not build"))
  with pytest.raises(ConfigError): build.build_candidate(tmp_path, output)
  assert list(output.iterdir()) == []


def test_bootstrap_rejection_does_not_create_output(tmp_path, monkeypatch):
  inputs(monkeypatch)
  def reject(): raise ConfigError("fixture-bootstrap")
  monkeypatch.setattr(build, "bootstrap_identity", reject)
  with pytest.raises(ConfigError): build.build_candidate(tmp_path, tmp_path / "candidate")
  assert not (tmp_path / "candidate").exists()


def test_shared_writable_ancestor_is_rejected_before_creating_output(tmp_path, monkeypatch):
  inputs(monkeypatch)
  shared = tmp_path / "shared"; shared.mkdir(mode=0o777); shared.chmod(0o777)
  parent = shared / "parent"; parent.mkdir(mode=0o700)
  monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: pytest.fail("must not build"))
  with pytest.raises(ConfigError): build.build_candidate(tmp_path, parent / "candidate")
  assert not (parent / "candidate").exists()


def test_publication_failure_leaves_only_unreferenced_archive(tmp_path, monkeypatch):
  inputs(monkeypatch); calls = []
  monkeypatch.setattr(build.subprocess, "run", fake_build(calls))
  original = build.Tree.write_new
  def fail_marker(self, name, raw):
    if name == "candidate.json": raise OSError("synthetic disk-full")
    return original(self, name, raw)
  monkeypatch.setattr(build.Tree, "write_new", fail_marker)
  output = tmp_path / "candidate"
  with pytest.raises(ConfigError): build.build_candidate(tmp_path, output)
  assert not (output / "candidate.json").exists()
  assert len(list(output.glob("*.tar.gz"))) == 1


def test_mounts_are_closed_and_build_script_only_reads_product(tmp_path, monkeypatch):
  inputs(monkeypatch); calls = []; script = []
  def run(argv, **kwargs):
    work = Path(argv[argv.index("--bind") + 1])
    script.append((work / "build.py").read_text())
    return fake_build(calls)(argv, **kwargs)
  monkeypatch.setattr(build.subprocess, "run", run)
  build.build_candidate(tmp_path, tmp_path / "candidate")
  argv, options = calls[0]
  mounts = [argv[index + 1:index + 3] for index, value in enumerate(argv) if value == "--ro-bind"]
  assert mounts == [[item, item] for item in ["/usr", "/bin", "/lib", "/lib64", "/etc/ld.so.cache"]]
  assert argv.count("--bind") == 1 and options["shell"] is False
  assert argv[-3:] == ["/usr/bin/python3.11", "-I", "/work/build.py"]
  assert "--wrap-mode=nodownload" in script[0] and "install-static-cap" in script[0]
  assert "readelf" in script[0] and "ldd" not in script[0]
  assert "[\"/work/bwrap-build/bwrap\"]" not in script[0]


@pytest.mark.parametrize("kind", ["duplicate", "traversal", "link", "special", "file-parent"])
def test_tar_input_paths_fail_closed(kind):
  stream = io.BytesIO()
  with tarfile.open(fileobj=stream, mode="w:xz") as archive:
    names = {"duplicate": ["libcap-2.77/a", "libcap-2.77/a"],
      "traversal": ["libcap-2.77/../outside"], "link": ["libcap-2.77/a"],
      "special": ["libcap-2.77/a"], "file-parent": ["libcap-2.77/a", "libcap-2.77/a/b"]}[kind]
    for name in names:
      item = tarfile.TarInfo(name); item.size = 1; item.mode = 0o644
      if kind == "link": item.type = tarfile.SYMTYPE; item.linkname = "elsewhere"; item.size = 0
      if kind == "special": item.mode = 0o4644
      archive.addfile(item, io.BytesIO(b"x") if item.size else None)
  with pytest.raises(ConfigError): build._tar_entries(stream.getvalue(), "libcap-2.77")


@pytest.mark.parametrize("corruption", ["unknown-key", "bad-tool", "wrong-schema", "duplicate-key"])
def test_invalid_observation_is_not_a_candidate(tmp_path, monkeypatch, corruption):
  inputs(monkeypatch); calls = []
  def run(argv, **kwargs):
    result = fake_build(calls)(argv, **kwargs)
    work = Path(argv[argv.index("--bind") + 1]); path = work / "build-observation.json"
    record = json.loads(path.read_text())
    if corruption == "unknown-key": record["extra"] = "private-marker"
    if corruption == "bad-tool": record["toolchains"]["gcc"]["sha256"] = "unverified"
    if corruption == "wrong-schema": record["schema_version"] = True
    path.write_text(json.dumps(record) if corruption != "duplicate-key" else '{"schema_version":1,"schema_version":1}')
    return result
  monkeypatch.setattr(build.subprocess, "run", run)
  output = tmp_path / "candidate"
  with pytest.raises(ConfigError) as error: build.build_candidate(tmp_path, output)
  assert "private-marker" not in str(error.value)
  assert not (output / "candidate.json").exists() and not list(output.glob("*.tar.gz"))


def test_archive_is_deterministic_and_modes_are_intentional():
  entries = (("bin/pi-bwrap", elf(), 0o755), ("licenses/license", b"license", 0o644))
  packed = build._archive(entries)
  assert packed == build._archive(tuple(reversed(entries)))
  with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as archive:
    assert [(item.name, item.mode, item.uid, item.gid, item.mtime) for item in archive] == [
      ("bin/pi-bwrap", 0o755, 0, 0, 0), ("licenses/license", 0o644, 0, 0, 0)]


def test_zip_nested_paths_remain_distinct_and_links_are_rejected():
  import zipfile
  stream = io.BytesIO()
  with zipfile.ZipFile(stream, "w") as archive:
    archive.writestr("mesonbuild/a.py", b"root")
    archive.writestr("mesonbuild/sub/a.py", b"nested")
  result = build._zip_entries(stream.getvalue())
  assert dict((name, raw) for name, raw, _ in result) == {"mesonbuild/a.py": b"root", "mesonbuild/sub/a.py": b"nested"}
  stream = io.BytesIO()
  with zipfile.ZipFile(stream, "w") as archive:
    item = zipfile.ZipInfo("mesonbuild/link"); item.create_system = 3; item.external_attr = 0o120777 << 16
    archive.writestr(item, b"target")
  with pytest.raises(ConfigError): build._zip_entries(stream.getvalue())


def test_fixed_digest_cannot_be_bypassed_by_well_formed_archive(tmp_path):
  for metadata in build.INPUTS.values(): (tmp_path / metadata["name"]).write_bytes(b"not-fixed-source")
  with pytest.raises(ConfigError): build.verified_inputs(tmp_path)


@pytest.mark.parametrize("limit", ["bytes", "entries"])
def test_expansion_limits_are_applied_before_materializing(limit, monkeypatch):
  import zipfile
  monkeypatch.setattr(build, "MAX_EXPANDED" if limit == "bytes" else "MAX_ENTRIES", 1)
  stream = io.BytesIO()
  with zipfile.ZipFile(stream, "w") as archive:
    archive.writestr("a", b"xx")
    archive.writestr("b", b"x")
  with pytest.raises(ConfigError): build._zip_entries(stream.getvalue())
  stream = io.BytesIO()
  with tarfile.open(fileobj=stream, mode="w:xz") as archive:
    for name in ("a", "b"):
      item = tarfile.TarInfo("libcap-2.77/" + name); item.mode = 0o644; item.size = 2
      archive.addfile(item, io.BytesIO(b"xx"))
  with pytest.raises(ConfigError): build._tar_entries(stream.getvalue(), "libcap-2.77")


def test_verified_inputs_parses_all_fixed_sources_without_process(tmp_path, monkeypatch):
  import zipfile
  raw = {}
  for root, directory, filename in [("bwrap-source", "bubblewrap-0.13.0", "COPYING"), ("libcap", "libcap-2.77", "License")]:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:xz") as archive:
      item = tarfile.TarInfo(directory + "/" + filename); item.mode = 0o644; item.size = 7
      archive.addfile(item, io.BytesIO(b"license"))
    raw[root] = stream.getvalue()
  stream = io.BytesIO()
  with zipfile.ZipFile(stream, "w") as archive: archive.writestr("mesonbuild/__init__.py", b"")
  raw["meson"] = stream.getvalue()
  metadata = {key: {**item, "sha256": hashlib.sha256(raw[key]).hexdigest()} for key, item in build.INPUTS.items()}
  monkeypatch.setattr(build, "INPUTS", metadata)
  monkeypatch.setattr(build.pi_bwrap_source, "ARCHIVE_SHA256", metadata["bwrap-source"]["sha256"])
  for key, item in metadata.items(): (tmp_path / item["name"]).write_bytes(raw[key])
  monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: pytest.fail("input parsing must not start a process"))
  result = build.verified_inputs(tmp_path)
  assert result == {"bwrap-source": (("COPYING", b"license", 0o644),),
    "libcap": (("License", b"license", 0o644),), "meson": (("mesonbuild/__init__.py", b"", 0o644),)}
  (tmp_path / metadata["libcap"]["name"]).write_bytes(b"corruption")
  with pytest.raises(ConfigError): build.verified_inputs(tmp_path)

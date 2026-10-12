"""本地构建来源绑定只验证合成字节；不编译、不执行产物。"""
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from agentcfg import pi_built_assets as assets
from agentcfg import pi_bwrap_build as build
from agentcfg.pi_lock_layout import dependency_layout
from agentcfg.schema import ConfigError


def built_fixture(repository: Path, monkeypatch):
  """共享离线fixture；排他新建，不覆盖调用方已有文件。"""
  def write(name, raw):
    path = repository / name
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with path.open("xb") as stream: stream.write(raw)
    path.chmod(0o600)
  fixed = {key: {"name": key + ".archive", "sha256": hashlib.sha256(key.encode()).hexdigest(), "url": "https://example.invalid/" + key}
    for key in ("bwrap-source", "libcap", "meson")}
  monkeypatch.setattr(build, "INPUTS", fixed)
  monkeypatch.setattr(build, "BUILD_SCRIPT", "synthetic private driver")
  licenses = {"bubblewrap-COPYING": b"bubblewrap license", "libcap-License": b"libcap license"}
  monkeypatch.setattr(assets, "LICENSE_DIGESTS", {name: hashlib.sha256(raw).hexdigest() for name, raw in licenses.items()})
  binary = bytearray(64); binary[:6] = b"\x7fELF\x02\x01"; binary[16:20] = b"\x03\x00\x3e\x00"; binary = bytes(binary)
  provenance = {"schema_version": 1, "inputs": fixed, "build_script_sha256": hashlib.sha256(build.BUILD_SCRIPT.encode()).hexdigest(),
    "bootstrap": {"path": "/usr/bin/bwrap", "sha256": "b" * 64}, "observation": {"schema_version": 1,
      "toolchains": {**{name: {"path": "/usr/bin/" + name, "sha256": "c" * 64, "version": "synthetic"} for name in build.TOOLS},
        "meson": {"version": "1.9.0"}}, "needed": ["libc.so.6"], "glibc_versions": ["GLIBC_2.28"]}}
  archive = build._archive((("bin/pi-bwrap", binary, 0o755), ("build/source-record.json", build._json(provenance), 0o644),
    *(("licenses/" + name, raw, 0o644) for name, raw in licenses.items())))
  record = {**provenance, "status": "built-not-executed", "archive": "pi-bwrap-linux-x86_64.tar.gz",
    "archive_sha256": hashlib.sha256(archive).hexdigest(), "binary_sha256": hashlib.sha256(binary).hexdigest()}
  raw = build._json(record); digest = hashlib.sha256(raw).hexdigest()
  source = {"kind": "asset", "format": "tar.gz", "platform": "linux-x86_64", "target": "bin/pi-bwrap",
    "archive_member": "bin/pi-bwrap", "archive_digest": record["archive_sha256"], "vendor_path": "vendor/pi-bwrap.tar.gz",
    "build_record": {"recipe": "bubblewrap-v1", "path": "build-records/" + digest + ".json", "digest": digest},
    "license_files": ["agents/pi/build/licenses/" + name for name in licenses]}
  write("locks/pi-modern/" + source["build_record"]["path"], raw)
  write("locks/pi-modern/" + source["vendor_path"], archive)
  for key, item in fixed.items(): write("locks/pi-modern/build-inputs/" + item["sha256"] + "/" + item["name"], key.encode())
  for name, content in licenses.items(): write("agents/pi/build/licenses/" + name, content)
  return source, record, archive


def test_local_provenance_round_trip(tmp_path, monkeypatch):
  source, record, archive = built_fixture(tmp_path, monkeypatch)
  assert assets.validate_reference(source) is None
  assert assets.load_record(tmp_path, dependency_layout(family="modern"), source) == record
  assert hashlib.sha256(assets.verify_archive(archive, source, record)).hexdigest() == record["binary_sha256"]


@pytest.mark.parametrize("change", ["unknown-ref", "url", "no-vendor", "path", "digest", "recipe", "platform", "target", "format", "kind"])
def test_reference_fails_closed(tmp_path, monkeypatch, change):
  source, _, _ = built_fixture(tmp_path, monkeypatch)
  if change == "unknown-ref": source["build_record"]["extra"] = "private"
  elif change == "url": source["url"] = "https://example.invalid/binary"
  elif change == "no-vendor": del source["vendor_path"]
  elif change == "path": source["build_record"]["path"] = "../record"
  elif change == "digest": source["build_record"]["digest"] = "d" * 64
  elif change == "recipe": source["build_record"]["recipe"] = "another"
  else: source[change] = "invalid"
  with pytest.raises(ConfigError): assets.validate_reference(source)


@pytest.mark.parametrize("change", ["missing-record", "wrong-family", "record-bytes", "input", "license", "missing-input"])
def test_record_checks_family_inputs_and_licenses(tmp_path, monkeypatch, change):
  source, _, _ = built_fixture(tmp_path, monkeypatch)
  layout = dependency_layout(family="modern")
  if change == "missing-record": (tmp_path / layout.lock_directory / source["build_record"]["path"]).unlink()
  elif change == "wrong-family": layout = dependency_layout(family="legacy")
  elif change == "record-bytes": (tmp_path / layout.lock_directory / source["build_record"]["path"]).write_bytes(b"private-marker")
  elif change == "license": (tmp_path / source["license_files"][0]).write_bytes(b"private-marker")
  else:
    item = build.INPUTS["libcap"]; path = tmp_path / layout.lock_directory / "build-inputs" / item["sha256"] / item["name"]
    if change == "missing-input": path.unlink()
    else: path.write_bytes(b"private-marker")
  with pytest.raises(ConfigError) as error: assets.load_record(tmp_path, layout, source)
  assert "private-marker" not in str(error.value)


def repack(archive, change):
  stream = io.BytesIO()
  with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as original:
    entries = [(item, original.extractfile(item).read()) for item in original]
  with tarfile.open(fileobj=stream, mode="w:gz") as result:
    for item, raw in entries:
      if change == "binary" and item.name == "bin/pi-bwrap": raw = b"script"
      if change == "inline" and item.name == "build/source-record.json": raw += b" "
      if change == "license" and item.name == "licenses/libcap-License": raw = b"foreign"
      if change == "mode": item.mode = 0o600
      if change == "uid": item.uid = 1
      if change == "link" and item.name == "bin/pi-bwrap": item.type = tarfile.SYMTYPE; item.linkname = "other"; raw = b""
      item.size = len(raw); result.addfile(item, io.BytesIO(raw))
    if change in ("extra", "duplicate"):
      item = tarfile.TarInfo("extra" if change == "extra" else "bin/pi-bwrap"); result.addfile(item, io.BytesIO(b""))
  return stream.getvalue()


@pytest.mark.parametrize("change", ["binary", "inline", "license", "mode", "uid", "link", "extra", "duplicate"])
def test_archive_structure_is_bound_even_with_recomputed_archive_digest(tmp_path, monkeypatch, change):
  source, record, archive = built_fixture(tmp_path, monkeypatch)
  archive = repack(archive, change)
  source["archive_digest"] = record["archive_sha256"] = hashlib.sha256(archive).hexdigest()
  with pytest.raises(ConfigError): assets.verify_archive(archive, source, record)


@pytest.mark.parametrize("change", ["unknown", "schema-bool", "status", "archive", "input-url", "script", "bootstrap", "observation", "duplicates"])
def test_rehashed_record_still_requires_fixed_recipe(tmp_path, monkeypatch, change):
  source, record, _ = built_fixture(tmp_path, monkeypatch)
  if change == "unknown": record["extra"] = "private-marker"
  elif change == "schema-bool": record["schema_version"] = True
  elif change == "status": record["status"] = "passed"
  elif change == "archive": record["archive"] = "other.tar.gz"
  elif change == "input-url":
    record = copy.deepcopy(record); record["inputs"]["libcap"]["url"] = "https://foreign.invalid/"
  elif change == "script": record["build_script_sha256"] = "f" * 64
  elif change == "bootstrap": record["bootstrap"]["path"] = "/tmp/bwrap"
  elif change == "observation": record["observation"]["needed"] = ["libc.so.6", "libcap.so.2"]
  raw = build._json(record)
  if change == "duplicates": raw = raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1)
  digest = hashlib.sha256(raw).hexdigest()
  source["build_record"].update(digest=digest, path="build-records/" + digest + ".json")
  path = tmp_path / "locks/pi-modern" / source["build_record"]["path"]
  path.write_bytes(raw); path.chmod(0o600)
  with pytest.raises(ConfigError) as error: assets.load_record(tmp_path, dependency_layout(family="modern"), source)
  assert "private-marker" not in str(error.value)


def test_archive_digest_and_binary_digest_are_independent(tmp_path, monkeypatch):
  source, record, archive = built_fixture(tmp_path, monkeypatch)
  with pytest.raises(ConfigError): assets.verify_archive(archive + b"trailing", source, record)
  record["binary_sha256"] = "d" * 64
  with pytest.raises(ConfigError): assets.verify_archive(archive, source, record)


def test_tar_hidden_entries_after_end_marker_are_rejected(tmp_path, monkeypatch):
  import gzip
  source, record, archive = built_fixture(tmp_path, monkeypatch)
  extra = io.BytesIO()
  with tarfile.open(fileobj=extra, mode="w") as packed:
    packed.addfile(tarfile.TarInfo("hidden"))
  archive = gzip.compress(gzip.decompress(archive) + extra.getvalue(), mtime=0)
  source["archive_digest"] = record["archive_sha256"] = hashlib.sha256(archive).hexdigest()
  with pytest.raises(ConfigError): assets.verify_archive(archive, source, record)


@pytest.mark.parametrize("limit", ["compressed", "expanded"])
def test_archive_caps_before_tar_parsing(tmp_path, monkeypatch, limit):
  source, record, archive = built_fixture(tmp_path, monkeypatch)
  monkeypatch.setattr(assets, "MAX_ARCHIVE" if limit == "compressed" else "MAX_EXPANDED", 1)
  with pytest.raises(ConfigError): assets.verify_archive(archive, source, record)


def test_shared_fixture_does_not_overwrite_existing_repository(tmp_path, monkeypatch):
  sentinel = tmp_path / "sentinel"; sentinel.write_bytes(b"preserve")
  built_fixture(tmp_path, monkeypatch)
  assert sentinel.read_bytes() == b"preserve"
  with pytest.raises(FileExistsError): built_fixture(tmp_path, monkeypatch)
  assert sentinel.read_bytes() == b"preserve"


def test_even_complete_legacy_family_cannot_supply_built_asset(tmp_path, monkeypatch):
  import shutil
  source, _, _ = built_fixture(tmp_path, monkeypatch)
  shutil.copytree(tmp_path / "locks/pi-modern", tmp_path / "locks/pi")
  with pytest.raises(ConfigError): assets.load_record(tmp_path, dependency_layout(family="legacy"), source)


def test_license_reference_must_use_repository_license_prefix(tmp_path, monkeypatch):
  source, _, _ = built_fixture(tmp_path, monkeypatch)
  source["license_files"][0] = "elsewhere/COPYING"
  with pytest.raises(ConfigError): assets.validate_reference(source)


def test_unknown_source_field_is_rejected_without_disclosing_value(tmp_path, monkeypatch):
  source, _, _ = built_fixture(tmp_path, monkeypatch)
  source["extra"] = "sensitive-marker-do-not-disclose"
  with pytest.raises(ConfigError) as error: assets.validate_reference(source)
  assert "sensitive-marker" not in str(error.value)

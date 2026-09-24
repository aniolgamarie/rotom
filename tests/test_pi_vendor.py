"""归档只读临时源树；验证字节、执行位和全部相对资源，不执行被迁移脚本。"""

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

import pytest

from agentcfg.pi_vendor import build_archive
from agentcfg.schema import ConfigError


def fixture(tmp_path):
  source = tmp_path / "packages/example"
  source.mkdir(parents=True)
  (source / "package.json").write_text('{"name":"fixture-package","version":"1.0.0"}')
  (source / "LICENSE").write_text("synthetic license")
  (source / "scripts").mkdir()
  (source / "scripts/helper.sh").write_text("#!/bin/sh\nexit 99\n")
  (source / "scripts/helper.sh").chmod(0o755)
  recipe = {"kind": "local", "source_path": "packages/example", "package": "fixture-package", "version": "1.0.0",
    "license_files": ["LICENSE"], "exclude": []}
  return recipe, source


def test_archive_is_deterministic_and_carries_relative_files_and_execution_bits(tmp_path):
  recipe, source = fixture(tmp_path)
  first, record = build_archive(tmp_path, recipe)
  os.utime(source / "scripts/helper.sh", (100, 100))
  assert build_archive(tmp_path, recipe) == (first, record)
  with tarfile.open(fileobj=io.BytesIO(first)) as archive:
    assert archive.getnames() == ["package/LICENSE", "package/package.json", "package/scripts/helper.sh"]
    script = archive.getmember("package/scripts/helper.sh")
    assert script.mode == 0o755 and script.uid == 0 and script.mtime == 0
  (source / "scripts/helper.sh").chmod(0o644)
  assert build_archive(tmp_path, recipe)[1]["source_tree_digest"] != record["source_tree_digest"]


@pytest.mark.parametrize("invalid", ["absolute", "link", "dependency", "license", "untracked-install"])
def test_archive_refuses_machine_inputs_and_missing_complete_sources(tmp_path, invalid):
  recipe, source = fixture(tmp_path)
  if invalid == "absolute":
    recipe["source_path"] = str(source)
  elif invalid == "link":
    (source / "escape").symlink_to(tmp_path)
  elif invalid == "dependency":
    (source / "package.json").write_text('{"name":"fixture-package","version":"1.0.0","dependencies":{"private":"file:/old/home/pkg"}}')
  elif invalid == "license":
    (source / "LICENSE").unlink()
  else:
    (source / "node_modules").mkdir()
  from agentcfg.paths import PathError
  with pytest.raises((ConfigError, PathError)):
    build_archive(tmp_path, recipe)


def test_missing_source_is_explicitly_not_ready_before_any_download(tmp_path, monkeypatch):
  import agentcfg.pi_vendor as vendor
  recipe, source = fixture(tmp_path)
  recipe["source_path"] = "packages/not-migrated"
  calls = []
  monkeypatch.setattr(vendor, "checked", lambda *a, **k: calls.append(a))
  with pytest.raises(ConfigError, match="pi-build-source-not-ready"):
    build_archive(tmp_path, recipe)
  assert calls == []


def test_lock_fills_missing_shrinkwrap_integrity_from_exact_metadata_and_reuses_it(tmp_path, monkeypatch):
  import base64
  from copy import deepcopy
  import agentcfg.pi_vendor as vendor
  checksum = "sha512-" + base64.b64encode(hashlib.sha512(b"synthetic archive").digest()).decode()
  record = {"version": "1.2.3", "resolved": "https://example.invalid/exact.tgz"}
  lock = {"packages": {"": {}, "node_modules/host/node_modules/@fixture/core": record}}
  calls = []
  def checked(argv, **kwargs):
    calls.append(argv)
    return json.dumps({"tarball": record["resolved"], "integrity": checksum})
  monkeypatch.setattr(vendor, "checked", checked)
  cache = {}
  second = deepcopy(lock)
  assert vendor.complete_resolution_integrity(lock, cwd=tmp_path, env={}, metadata=cache)
  assert vendor.complete_resolution_integrity(second, cwd=tmp_path, env={}, metadata=cache)
  assert record["integrity"] == checksum
  assert calls == [["npm", "view", "@fixture/core@1.2.3", "dist", "--json"]]
  assert not vendor.complete_resolution_integrity(lock, cwd=tmp_path, env={}, metadata=cache)


def test_lock_never_substitutes_a_different_tarball_to_fill_integrity(tmp_path, monkeypatch):
  import agentcfg.pi_vendor as vendor
  record = {"version": "1.2.3", "resolved": "https://example.invalid/original.tgz"}
  monkeypatch.setattr(vendor, "checked", lambda *a, **k: '{"tarball":"https://example.invalid/changed.tgz","integrity":"sha512-AA=="}')
  with pytest.raises(ConfigError, match="integrity-unverified"):
    vendor.complete_resolution_integrity({"packages": {"node_modules/fixture": record}}, cwd=tmp_path, env={}, metadata={})
  assert "integrity" not in record


def test_explicit_license_overlay_is_installed_but_never_overwrites_conflicting_license(tmp_path):
  from agentcfg.pi_vendor import install_source_licenses
  from agentcfg.storage import Tree
  from agentcfg.process import DependencyError
  source_path = "agents/pi/build/licenses/fixture/LICENSE"
  record = {"kind": "npm", "package": "fixture", "license_files": ["LICENSE"], "license_sources": {"LICENSE": source_path}}
  with Tree(tmp_path / "source", create=True) as source, Tree(tmp_path / "runtime", create=True) as target:
    source.write_state(source_path, b"synthetic full license")
    install_source_licenses(source, target, Path("profile"), record)
    assert target.read("profile/node_modules/fixture/LICENSE")[0] == b"synthetic full license"
    install_source_licenses(source, target, Path("profile"), record)
    target.write_state("profile/node_modules/fixture/LICENSE", b"different existing license")
    with pytest.raises(DependencyError, match="冲突"):
      install_source_licenses(source, target, Path("profile"), record)
    assert target.read("profile/node_modules/fixture/LICENSE")[0] == b"different existing license"


def test_pi_npm_uses_only_private_cache_and_no_ambient_configuration(tmp_path, monkeypatch):
  from agentcfg.pi_vendor import npm_environment
  for name in ("NPM_CONFIG_USERCONFIG", "NPM_CONFIG_GLOBALCONFIG", "NPM_CONFIG_CACHE", "NPM_TOKEN"):
    monkeypatch.setenv(name, "synthetic-unselected")
  env = npm_environment(tmp_path)
  assert env["NPM_CONFIG_USERCONFIG"] == str(tmp_path / "npm-user.rc")
  assert env["NPM_CONFIG_GLOBALCONFIG"] == str(tmp_path / "npm-global.rc")
  assert env["NPM_CONFIG_CACHE"] == str(tmp_path / "npm-cache")
  assert env["NPM_CONFIG_IGNORE_SCRIPTS"] == "true" and "NPM_TOKEN" not in env


def test_install_proxy_is_validated_and_never_enters_normal_host_environment(tmp_path, monkeypatch):
  from agentcfg.pi_vendor import npm_environment, installation_network, INSTALL_PROXY_NAMES
  from agentcfg.process import environment
  from agentcfg.schema import ConfigError
  for name in INSTALL_PROXY_NAMES: monkeypatch.delenv(name, raising=False)
  monkeypatch.setenv("https_proxy", "http://127.0.0.1:8123")
  monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
  assert npm_environment(tmp_path)["https_proxy"] == "http://127.0.0.1:8123"
  assert not INSTALL_PROXY_NAMES.intersection(environment(home=tmp_path))
  for value in ("http://user:synthetic-secret@proxy.invalid", "http://proxy.invalid/?token=synthetic", "http://proxy.invalid\n"):
    monkeypatch.setenv("https_proxy", value)
    with pytest.raises(ConfigError, match="pi-install-proxy-invalid"): installation_network()

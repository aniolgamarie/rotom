"""固定发布父目录许可旁车；自足离线146行npm许可图，仅读取数据和复制临时文件。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg.pi_license_bundle import validate_source
from agentcfg.pi_runtime_files import install_files, lock_files
from agentcfg.schema import ConfigError


ROOT = Path(__file__).resolve().parents[1]
OWN = "agents/pi/build/licenses/pi-modern/"
TARGET = "licenses/pi-modern/"
BODY = "STANDARDWEBHOOKS-1.1.1-LICENSE.txt"
SHA = "5ec8c7b26b64d881a6706617bed25c049f97f2f35de034c756de8546fd6dbe27"
PACKAGE_SHA = "686397f0f0202e0b693cfd3f6241d7a8da3df326f9642867a484fbbd295690b6"
COMMIT = "b4d2c14fc5b4ccff3ff271e3b087dff812254c59"
BLOB = "55b14b3a3ce649a2f1b05428dcc9c6db95b37c04"
RESOLUTION_FIXTURE = "tests/fixtures/pi-modern-license-npm-resolution.json"
FIXTURE_SHA = "81ffc03098df7c5423e5a750ed3a6f513f949921b67a8639d44e4c1450381d79"
FULL_SOURCE_LOCK_SHA = "7a6ad8e47f7b165d2c35b218a72e7734cf74a8ee26044d20e993419ba9c5bee1"
DECLARATION = {"source": OWN + BODY, "path": TARGET + BODY, "transform": "copy"}
EXPECTED_BODY = {"path": BODY,
  "source_url": "https://raw.githubusercontent.com/standard-webhooks/standard-webhooks/" + COMMIT + "/libraries/LICENSE",
  "source_api_url": "https://api.github.com/repos/standard-webhooks/standard-webhooks/git/blobs/" + BLOB,
  "blob_sha": BLOB, "sha256": SHA, "bytes": 1088, "kind": "fixed-upstream-source-text",
  "from_package_archive": False, "exact_upstream_source_commit": COMMIT}


def read_json(path):
  return json.loads(path.read_bytes())


def candidate():
  return read_json(ROOT / "agents/pi/dependencies-modern.json")


def resolution():
  raw = (ROOT / RESOLUTION_FIXTURE).read_bytes()
  assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA
  value = json.loads(raw)
  assert len(value["packages"]) == 146
  assert all(item["resolved"].startswith("https://registry.npmjs.org/") for item in value["packages"].values())
  return value


def declarations(*, own_only=False):
  rows = candidate()["profiles"]["pi-base"]["runtime_files"]
  return [deepcopy(row) for row in rows if not own_only or row["source"].startswith(OWN)]


def row(registry, name):
  return next(item for item in registry["packages"] if item["name"] == name)


def require_standard_supplement(registry):
  standard = row(registry, "standardwebhooks")
  assert standard["status"] == "fixed-source-body"
  assert standard["supplemental_files"] == [{"path": TARGET + BODY, "sha256": SHA}]
  assert standard["archive_files"] == []
  assert standard["package_json_sha256"] == PACKAGE_SHA and standard["declared_license"] == "MIT"
  return standard


def own_fixture(tmp_path):
  repository = tmp_path / "repository"; repository.mkdir(mode=0o700)
  rows = declarations(own_only=True)
  require_standard_supplement(read_json(ROOT / OWN / "REGISTRY.json"))
  assert rows.count(DECLARATION) == 1
  for declaration in rows:
    path = repository / declaration["source"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((ROOT / declaration["source"]).read_bytes())
  piece = {"runtime_files": lock_files(repository, rows)}
  graph = resolution()
  require_standard_supplement(validate_source(repository, piece, graph, allow_unresolved=True))
  return repository, piece, graph


def test_independent_fixed_parent_source_scope_and_original_body():
  document = read_json(ROOT / OWN / "TRANSITIVE-SOURCE.json")
  record = next(item for item in document["records"] if item["name"] == "standardwebhooks")
  assert record["status"] == "fixed-source-body"
  assert record["body"] == EXPECTED_BODY
  assert record["git_head"] == COMMIT and record["package_json_sha256"] == PACKAGE_SHA
  assert record["name"] == "standardwebhooks" and record["version"] == "1.1.1" and record["declared_license"] == "MIT"
  assert record["archive_license_or_notice_files"] == []
  assert "libraries/javascript" in record["limitation"] and "parent" in record["limitation"]
  assert PACKAGE_SHA in record["limitation"] and "archive" in record["limitation"] and "legal" in record["limitation"]
  raw = (ROOT / OWN / BODY).read_bytes()
  assert len(raw) == 1088 and hashlib.sha256(raw).hexdigest() == SHA
  assert hashlib.sha1(b"blob 1088\x00" + raw).hexdigest() == BLOB
  assert raw.startswith(b"The MIT License\n\nCopyright (c) 2023 Svix (https://www.svix.com)\n") and raw.endswith(b"\n")
  proxy = next(item for item in document["records"] if item["name"] == "proxy-agent-negotiate")
  assert proxy["status"] == "body-scope-unresolved" and proxy["body"] is None
  assert document["upstream_packages_modified"] is False
  assert document["base_candidate_lock_sha256"] == FULL_SOURCE_LOCK_SHA


def test_candidate_declarations_and_offline_npm_license_graph_keep_proxy_gate():
  document = candidate()
  piece = {"runtime_files": lock_files(ROOT, declarations())}
  graph = resolution()
  registry = validate_source(ROOT, piece, graph, allow_unresolved=True)
  require_standard_supplement(registry)
  assert len(registry["packages"]) == 146
  assert {item["name"] for item in registry["packages"] if item["status"] == "body-scope-unresolved"} == {"proxy-agent-negotiate"}
  evidence_raw = (ROOT / OWN / "TRANSITIVE-SOURCE.json").read_bytes()
  evidence_sha = hashlib.sha256(evidence_raw).hexdigest()
  for item in registry["packages"]:
    for reference in item["evidence_files"]:
      if reference["path"] == TARGET + "TRANSITIVE-SOURCE.json": assert reference["sha256"] == evidence_sha
  assert declarations().count(DECLARATION) == 1
  bindings = document["capability_bindings"]; selection = bindings["selections"]["pi-base"]
  assert selection["state"] == "candidate"
  assert bindings["catalog"]["revision"] == selection["revision"] == selection["source_revision"] == 2
  assert all(provider["verified_host_versions"] == [] for provider in bindings["providers"].values())
  assert "pi-node-linux-x86_64" in document["profiles"]["pi-base"]["source_ids"]
  with pytest.raises(ConfigError): validate_source(ROOT, piece, graph, allow_unresolved=False)


@pytest.mark.parametrize("kind,fault", [("body", "drift"), ("body", "missing"), ("evidence", "drift"), ("evidence", "missing")])
def test_locked_own_body_or_evidence_damage_refused_without_refreezing(tmp_path, kind, fault):
  repository, piece, graph = own_fixture(tmp_path)
  target = repository / OWN / (BODY if kind == "body" else "TRANSITIVE-SOURCE.json")
  if fault == "drift": target.write_bytes(b"synthetic changed source")
  else: target.unlink()
  with pytest.raises(ConfigError): validate_source(repository, piece, graph, allow_unresolved=True)
  stage = tmp_path / "stage"; stage.mkdir(mode=0o700)
  with pytest.raises(ConfigError): install_files(repository, stage, piece["runtime_files"])
  assert not list(stage.iterdir())


def test_public_copy_is_own_sidecar_without_upstream_overlay(tmp_path):
  repository, piece, graph = own_fixture(tmp_path)
  stage = tmp_path / "stage"; stage.mkdir(mode=0o700)
  upstream = stage / "pi-base/node_modules/standardwebhooks"; upstream.mkdir(parents=True)
  upstream_manifest = b'{"name":"standardwebhooks","version":"1.1.1","license":"MIT"}\n'
  (upstream / "package.json").write_bytes(upstream_manifest)
  before = sorted((path.relative_to(upstream).as_posix(), path.read_bytes()) for path in upstream.rglob("*") if path.is_file())
  install_files(repository, stage, piece["runtime_files"])
  copied = (stage / TARGET / BODY).read_bytes()
  assert copied == (ROOT / OWN / BODY).read_bytes() and hashlib.sha256(copied).hexdigest() == SHA
  assert (stage / TARGET / BODY).stat().st_mode & 0o777 == 0o600
  after = sorted((path.relative_to(upstream).as_posix(), path.read_bytes()) for path in upstream.rglob("*") if path.is_file())
  assert after == before and not (upstream / "LICENSE").exists()
  require_standard_supplement(validate_source(repository, piece, graph, allow_unresolved=True))
  with pytest.raises(ConfigError): validate_source(repository, piece, graph, allow_unresolved=False)

"""Node 格式只用小型合成归档和临时 Tree。"""

import copy
import dataclasses
import io
import json
from pathlib import Path
import traceback

import jsonschema
import pytest

from agentcfg import pi_assets, pi_node_asset as node
from agentcfg.pi_lock_layout import dependency_layout
from agentcfg.process import DependencyError
from agentcfg.storage import Tree, ensure_private
from test_pi_node_archive import fixture as archive_fixture, declaration, BINARY, LICENSE


TOOLS = {"node": "v24.14.0", "npm": "11.0.0", "bun": "1.0.0"}


def source(raw, vendor=False):
  snapshot = declaration(raw)
  root = "node-" + snapshot["release"] + "-linux-x64"
  row = {"kind": "asset", "format": "node.tar.gz", "url": "https://nodejs.org/download/release/v24.14.0/" + root + ".tar.gz", "platform": "linux-x86_64", "archive_digest": snapshot["archive_sha256"], "archive_member": root + "/bin/node", "target": "bin/pi-node", "license_files": ["agents/pi/build/licenses/node-v24.14.0/LICENSE"], "node_archive": snapshot}
  if vendor: row["vendor_path"] = "vendor/" + root + "-" + snapshot["archive_sha256"] + ".tar.gz"
  return row


def invalid(action):
  try: raise RuntimeError("SYNTHETIC_SECRET")
  except RuntimeError:
    with pytest.raises(DependencyError) as caught: action()
  error = caught.value
  assert type(error) is DependencyError and error.args == ("Pi Node资产无效",)
  assert error.__cause__ is None and error.__context__ is None
  assert "SYNTHETIC_SECRET" not in "".join(traceback.format_exception(error))


def setup(tmp_path, monkeypatch, vendor=False, family="modern"):
  raw = archive_fixture(long=True); row = source(raw, vendor)
  repo = tmp_path / "repo"; repo.mkdir()
  stage = tmp_path / "stage"; ensure_private(stage)
  license = repo / row["license_files"][0]; license.parent.mkdir(parents=True); license.write_bytes(LICENSE)
  layout = dependency_layout(family=family)
  calls = []
  def download(reference): calls.append(reference.url); return io.BytesIO(raw)
  monkeypatch.setattr(node, "open_node_download", download)
  if vendor:
    p = repo / layout.lock_directory / row["vendor_path"]; p.parent.mkdir(parents=True); p.write_bytes(raw)
  manifest = {"sources": {"node-fixture": row}, "toolchains": dict(TOOLS)}
  return raw, row, repo, stage, manifest, calls


def install(repo, stage, manifest, family="modern", ids=None):
  pi_assets.install_assets(repo, stage, {"source_ids": ids or ["node-fixture"]}, manifest, "linux-x86_64", lock_family=family)


def test_exact_metadata_snapshot_and_frozen_independence():
  row = source(archive_fixture()); reference = node.capture_node_asset(row)
  row["node_archive"]["release"] = "v0.0.0"; row["license_files"][0] = "changed"
  assert reference.selection.release == "v24.14.0" and reference.license_file.endswith("/LICENSE")
  with pytest.raises(dataclasses.FrozenInstanceError): reference.url = "changed"


@pytest.mark.parametrize("field,value", [("kind", "npm"), ("format", "tar.gz"), ("url", "https://mirror.invalid/node"), ("platform", "all"), ("archive_digest", "0"*64), ("archive_member", "node/bin/node"), ("target", "bin/node"), ("license_files", []), ("license_files", ("a",)), ("license_files", [1]), ("vendor_path", "vendor/other"), ("build_record", {}), ("size", 1), ("extra", "x")])
def test_closed_source_and_derived_fields(field, value):
  row = source(archive_fixture()); row[field] = value
  invalid(lambda: node.capture_node_asset(row))


@pytest.mark.parametrize("tools", [None, {}, {"node": "wrong", "npm": "x", "bun": "y"}, {**TOOLS, "extra": "x"}, {**TOOLS, "bun": 1}])
def test_toolchain_closed_and_version_association(tools):
  invalid(lambda: node.validate_node_asset_toolchain(source(archive_fixture()), tools))


def test_types_before_foreign_hooks():
  calls = []; armed = False
  class Key(str):
    def __hash__(self):
      if armed: calls.append("hash"); raise AssertionError()
      return str.__hash__(self)
    def __eq__(self, other): calls.append("eq"); raise AssertionError()
  class Dict(dict):
    def items(self): calls.append("items"); raise AssertionError()
  row = {Key("kind"): "asset"}; armed = True
  invalid(lambda: node.capture_node_asset(row))
  invalid(lambda: node.capture_node_asset(Dict()))
  invalid(lambda: node.validate_node_asset_toolchain(source(archive_fixture()), row))
  invalid(lambda: node.open_node_download(object()))
  assert calls == []


@pytest.mark.parametrize("bad", ["uninitialized", "selection", "url", "vendor_path", "license_file"])
def test_opener_reference_revalidates_before_network(monkeypatch, bad):
  calls = []; monkeypatch.setattr(node, "build_opener", lambda *args: calls.append(args))
  ref = node.capture_node_asset(source(archive_fixture()))
  if bad == "uninitialized": ref = object.__new__(node.NodeAssetReference)
  else: object.__setattr__(ref, bad, object() if bad == "selection" else "wrong")
  invalid(lambda: node.open_node_download(ref)); assert calls == []


def test_opener_disables_proxy_and_keeps_exact_request(monkeypatch):
  ref = node.capture_node_asset(source(archive_fixture())); calls = []
  class Opener:
    def open(self, request, timeout): calls.append((request, timeout)); return "original-response"
  def build(*handlers):
    assert handlers[0].proxies == {}
    assert type(handlers[1]) is node.NodeHTTPSRedirects
    return Opener()
  monkeypatch.setattr(node, "build_opener", build)
  assert node.open_node_download(ref) == "original-response"
  request, timeout = calls[0]
  assert request.full_url == ref.url and timeout == 60
  assert request.get_header("Authorization") is None
  assert request.get_header("User-agent") == "agentcfg"


@pytest.mark.parametrize("newurl", ["https://mirror.invalid/a", "http://nodejs.org/a", "https://nodejs.org/download/release/v24.14.0/node-v24.14.0-linux-x64.tar.gz?x=1", None])
def test_redirect_drift_never_delegates(newurl):
  ref = node.capture_node_asset(source(archive_fixture()))
  invalid(lambda: node.NodeHTTPSRedirects(ref.url).redirect_request(None, None, 302, "", {}, newurl))


def test_exact_redirect_uses_original_public_parent(monkeypatch):
  ref = node.capture_node_asset(source(archive_fixture())); calls=[]
  def redirect(self, *args): calls.append(args); return "same"
  monkeypatch.setattr(node.HTTPRedirectHandler, "redirect_request", redirect)
  assert node.NodeHTTPSRedirects(ref.url).redirect_request(None,None,302,"",{},ref.url) == "same"
  assert len(calls)==1


@pytest.mark.parametrize("vendor,family", [(False,"modern"),(True,"modern"),(True,"legacy")])
def test_install_exact_two_original_bodies_and_private_modes(tmp_path, monkeypatch, vendor, family):
  _, row, repo, stage, manifest, calls = setup(tmp_path,monkeypatch,vendor,family)
  install(repo,stage,manifest,family)
  for name, expected, mode in [("bin/pi-node",BINARY,0o700),("licenses/node-fixture/0-LICENSE",LICENSE,0o600)]:
    p=stage/name; assert p.read_bytes()==expected and p.stat().st_mode&0o777==mode and p.stat().st_nlink==1
  assert len(calls)==(0 if vendor else 1)


@pytest.mark.parametrize("fault", ["missing_vendor","bad_vendor","wrong_family","license_missing","license_bad","binary_exists","license_exists","toolchain_missing","toolchain_wrong","download_bad","limit"])
def test_failure_before_publication_has_zero_target_writes(tmp_path, monkeypatch, fault):
  vendor=fault in ("missing_vendor","bad_vendor","wrong_family")
  raw,row,repo,stage,manifest,calls=setup(tmp_path,monkeypatch,vendor)
  if fault=="missing_vendor": (repo/"locks/pi-modern"/row["vendor_path"]).unlink()
  if fault=="bad_vendor": (repo/"locks/pi-modern"/row["vendor_path"]).write_bytes(b"wrong")
  if fault=="license_missing": (repo/row["license_files"][0]).unlink()
  if fault=="license_bad": (repo/row["license_files"][0]).write_bytes(b"summary")
  if fault.endswith("_exists"):
    p=stage/("bin/pi-node" if fault=="binary_exists" else "licenses/node-fixture/0-LICENSE");p.parent.mkdir(parents=True);p.write_bytes(b"old")
  if fault=="toolchain_missing": del manifest["toolchains"]
  if fault=="toolchain_wrong": manifest["toolchains"]["node"]="v0.0.0"
  if fault=="download_bad": monkeypatch.setattr(node,"open_node_download",lambda ref:io.BytesIO(b"bad"))
  if fault=="limit": monkeypatch.setattr(node,"MAX_ARCHIVE",1)
  writes=[]
  monkeypatch.setattr(Tree,"replace",lambda *a,**k:writes.append("replace"))
  monkeypatch.setattr(Tree,"write_new",lambda *a,**k:writes.append("write_new"))
  invalid(lambda:install(repo,stage,manifest,"legacy" if fault=="wrong_family" else "modern"))
  assert writes==[]
  if vendor or fault.startswith("toolchain"): assert calls==[]


def test_second_write_io_failure_preserves_unready_stage_and_foreign_error(tmp_path,monkeypatch):
  _,_,repo,stage,manifest,_=setup(tmp_path,monkeypatch)
  foreign=OSError("SYNTHETIC_SECRET"); calls=[]
  def fail(self,*args): calls.append(args);raise foreign
  monkeypatch.setattr(Tree,"write_new",fail)
  invalid(lambda:install(repo,stage,manifest))
  assert (stage/"bin/pi-node").read_bytes()==BINARY and not (stage/"licenses/node-fixture/0-LICENSE").exists()
  assert len(calls)==1 and foreign.args==("SYNTHETIC_SECRET",)


def test_unselected_node_does_not_touch_body_or_helpers(tmp_path,monkeypatch):
  _,_,repo,stage,manifest,calls=setup(tmp_path,monkeypatch)
  manifest["sources"]["node-fixture"]["platform"]="darwin-arm64"
  monkeypatch.setattr(node,"install_node_asset",lambda *a:pytest.fail("unselected"))
  pi_assets.install_assets(repo,stage,{"source_ids":["node-fixture"]},manifest,"linux-x86_64",lock_family="modern")
  assert calls==[] and list(stage.iterdir())==[]


def schema_validator():
  root=Path(__file__).resolve().parents[1]
  schema=json.loads((root/"schemas/pi-lock.schema.json").read_text())["properties"]["sources"]["additionalProperties"]
  return jsonschema.Draft202012Validator(schema)


def test_local_schema_accepts_closed_node_inline():
  schema_validator().validate(source(archive_fixture()))


@pytest.mark.parametrize("format,kind", [("raw","asset"),("tar.gz","asset"),("node.tar.gz","npm"),("node.tar.gz","git"),("node.tar.gz","local")])
def test_schema_rejects_node_field_on_every_old_route(format,kind):
  row=source(archive_fixture());row.update(format=format,kind=kind)
  assert list(schema_validator().iter_errors(row))


@pytest.mark.parametrize("fault", ["missing","unknown","size","build_record","platform","target","license","metadata_extra"])
def test_schema_node_dual_closed_constraints(fault):
  row=source(archive_fixture())
  if fault=="missing":del row["node_archive"]
  if fault=="unknown":row["extra"]=1
  if fault in ("size","build_record"):row[fault]=1 if fault=="size" else {}
  if fault=="platform":row["platform"]="all"
  if fault=="target":row["target"]="bin/other"
  if fault=="license":row["license_files"].append("other")
  if fault=="metadata_extra":row["node_archive"]["extra"]=1
  assert list(schema_validator().iter_errors(row))


@pytest.mark.parametrize("source_id", [None, 1, "UPPER", "../bad", "a"*65])
def test_source_id_rejects_before_io(source_id):
  class NoIO:
    def __getattr__(self, name): pytest.fail("unexpected IO")
  invalid(lambda: node.install_node_asset(NoIO(), NoIO(), source_id, source(archive_fixture()), TOOLS, NoIO()))


@pytest.mark.parametrize("tools", [None, {**TOOLS,"node":"v0.0.0"}])
def test_selected_platform_validation_checks_toolchain_inside_fixed_boundary(tools):
  row=source(archive_fixture())
  manifest={"sources":{"node-fixture":row},"platforms":["linux-x86_64"]}
  if tools is not None: manifest["toolchains"]=tools
  invalid(lambda:pi_assets.validate_asset_platforms({"source_ids":["node-fixture"]},manifest))


def test_unselected_platform_metadata_does_not_call_node_toolchain(monkeypatch):
  manifest={"sources":{"node-fixture":source(archive_fixture())},"platforms":["linux-x86_64"]}
  monkeypatch.setattr(node,"validate_node_asset_toolchain",lambda *a:pytest.fail("unselected metadata"))
  pi_assets.validate_asset_platforms({"source_ids":[]},manifest)


def test_download_foreign_failure_fixed_without_mutating_cause(monkeypatch):
  foreign=OSError("SYNTHETIC_SECRET")
  def fail(*args):raise foreign
  monkeypatch.setattr(node,"build_opener",fail)
  invalid(lambda:node.open_node_download(node.capture_node_asset(source(archive_fixture()))))
  assert foreign.args==("SYNTHETIC_SECRET",) and foreign.__cause__ is None


@pytest.mark.parametrize("chunk", [None, bytearray(b"x"), b"x"*(1024*1024+1)])
def test_download_chunks_are_exact_bounded_bytes_before_publication(tmp_path,monkeypatch,chunk):
  _,_,repo,stage,manifest,_=setup(tmp_path,monkeypatch)
  class Response:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):assert limit==1024*1024;return chunk
  monkeypatch.setattr(node,"open_node_download",lambda ref:Response())
  invalid(lambda:install(repo,stage,manifest))
  assert list(stage.iterdir())==[]


@pytest.mark.parametrize("route", ["npm", "git", "local", "tar.gz", "raw"])
def test_legal_old_source_rejects_only_added_node_archive(route):
  row = {"kind": route, "license_files": ["agents/pi/build/licenses/fixture/LICENSE"]}
  if route == "npm":
    row.update(package="fixture", version="1.0.0", resolved="https://example.invalid/fixture.tgz", integrity="sha512-fixture")
  elif route in ("git", "local"):
    row.update(package="fixture", version="1.0.0", source_path="agents/pi/packages/fixture", source_tree_digest="0"*64, vendor_path="vendor/fixture.tgz", archive_digest="1"*64)
    if route == "git": row["commit"] = "2"*40
  else:
    row.update(kind="asset", format=route, url="https://example.invalid/fixture", archive_digest="1"*64)
    if route == "tar.gz": row.update(platform="linux-x86_64", target="bin/fixture", archive_member="fixture")
    else: row.update(platform="all", target="data/fixture", size=1)
  validator = schema_validator()
  assert list(validator.iter_errors(row)) == []
  with_node = {**row, "node_archive": declaration(archive_fixture())}
  assert set(with_node) - set(row) == {"node_archive"}
  assert list(validator.iter_errors(with_node))

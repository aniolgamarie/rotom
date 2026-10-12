"""只核合成安装描述与受信context，不加载资源或读取账号。"""
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.pi_capabilities import RESOURCE_KINDS
from agentcfg.storage import Tree, ensure_private


def inventory_fixture(tmp_path):
  root = tmp_path / "package"
  ensure_private(root)
  resources = {kind:[] for kind in RESOURCE_KINDS}
  resources["extensions"] = [{"id":"fixture-extension", "capability_id":"native", "path":"pi-base/node_modules/synthetic/extension.js"}]
  context = {"profile_id":"pi-base", "runtime_root":root, "lock_identity":"a" * 64,
    "runtime_identity":"b" * 64, "slice_identity":"c" * 64, "expected_resources":resources}
  document = {"schema_version":2, "profile_id":"pi-base", "package_path":"pi-base/package.json", "engine":"node",
    "entrypoint":"pi-base/node_modules/synthetic/index.js", "resources":deepcopy(resources),
    "lock_identity":"a" * 64, "runtime_identity":"b" * 64, "slice_identity":"c" * 64,
    "sdk_package":"synthetic", "sdk_version":"1.0.0", "ai_package":"synthetic-ai", "ai_version":"1.0.2",
    "toolchains":{"node":"v24.14.0", "npm":"11.19.1", "bun":"1.4.0"}, "platform":"linux-x86_64"}
  write_document(context, document)
  return context, document


def write_document(context, document):
  with Tree(context["runtime_root"]) as tree:
    tree.write_state("runtime/profile.json", (json.dumps(document, separators=(",", ":")) + "\n").encode())


def inspect(context, dependencies="installed", profile_id="pi-base"):
  from agentcfg.pi_installed_resource_diagnostics import installed_resource_inventory
  return installed_resource_inventory(context=context, dependencies=dependencies, profile_id=profile_id)


def test_modern_host_plan_wires_actual_recorded_descriptor_without_claiming_load(tmp_path, monkeypatch):
  from agentcfg import pi_diagnostics
  from test_pi_modern_diagnostics import modern_projection, inputs
  context, _ = inventory_fixture(tmp_path)
  projection = modern_projection(tmp_path)
  projection.update(dependencies="installed", installed_resource_context=context)
  monkeypatch.setattr(pi_diagnostics, "diagnostic_identity", lambda _: inputs()["identity"])
  host = next(row for row in pi_diagnostics.capabilities(projection) if row["id"] == "pi-host")
  value = host["profile_plan"]["installed_resource_inventory"]
  assert value["status"] == "matched"
  assert value["resources"] == [{"kind":"extensions", "id":"fixture-extension", "capability_id":"native"}]
  assert host["load_evidence"] == host["execution_evidence"] == "not-run"
  assert host["observed_at"] == {}
  assert host["profile_plan"]["permission_isolation"]["complete_coverage"] is False
  assert all(host["profile_plan"]["discovery_plan"][kind]["observed"] == "not-run" for kind in ("global", "package", "ancestor", "project"))
  assert "node_modules" not in json.dumps(value) and str(context["runtime_root"]) not in json.dumps(value)


def test_missing_context_or_uninstalled_dependencies_never_open_any_runtime(tmp_path, monkeypatch):
  context, _ = inventory_fixture(tmp_path)
  from agentcfg import pi_installed_resource_diagnostics as helper
  monkeypatch.setattr(helper, "Tree", lambda *_args, **_kwargs: pytest.fail("unexpected descriptor read"))
  assert inspect(context, dependencies="missing")["status"] == "not-inspected"
  assert inspect(None)["status"] == "not-inspected"
  assert inspect(context, profile_id="pi-full")["status"] == "stale"


@pytest.mark.parametrize("field", ["profile_id", "lock_identity", "runtime_identity", "slice_identity"])
def test_wrong_valid_identity_is_stale_with_no_partial_public_resources(tmp_path, field):
  context, document = inventory_fixture(tmp_path)
  document[field] = "pi-full" if field == "profile_id" else "d" * 64
  write_document(context, document)
  value = inspect(context)
  assert value["status"] == "stale" and value["resources"] == [] and value["counts"]["total"] == 0


@pytest.mark.parametrize("fault", ["extra-field", "bool-schema", "wrong-engine", "duplicate-id", "cross-kind-duplicate", "unknown-kind", "resource-field", "absolute-path", "escape-path", "entrypoint-type", "sdk-version", "toolchains-field", "invalid-utf8-id"])
def test_malformed_installed_descriptor_is_fixed_invalid_and_never_exports_body(tmp_path, fault):
  context, document = inventory_fixture(tmp_path)
  if fault == "extra-field": document["SYNTHETIC_PRIVATE"] = "private body"
  elif fault == "bool-schema": document["schema_version"] = True
  elif fault == "wrong-engine": document["engine"] = "bun"
  elif fault == "duplicate-id": document["resources"]["extensions"] *= 2
  elif fault == "cross-kind-duplicate": document["resources"]["skills"] = deepcopy(document["resources"]["extensions"])
  elif fault == "unknown-kind": document["resources"]["auth"] = []
  elif fault == "resource-field": document["resources"]["extensions"][0]["secret"] = "SYNTHETIC_PRIVATE"
  elif fault == "absolute-path": document["resources"]["extensions"][0]["path"] = "/SYNTHETIC_PRIVATE"
  elif fault == "escape-path": document["resources"]["extensions"][0]["path"] = "pi-base/../escape"
  elif fault == "entrypoint-type": document["entrypoint"] = 1
  elif fault == "sdk-version": document["sdk_version"] = "not-a-version"
  elif fault == "toolchains-field": document["toolchains"]["unknown"] = "SYNTHETIC_PRIVATE"
  elif fault == "invalid-utf8-id": document["resources"]["extensions"][0]["id"] = "\ud800"
  write_document(context, document)
  value = inspect(context)
  assert value["status"] == "invalid" and value["resources"] == []
  assert "SYNTHETIC_PRIVATE" not in json.dumps(value)


def test_complete_resources_are_compared_including_nonpublic_path_and_capability(tmp_path):
  context, document = inventory_fixture(tmp_path)
  document["resources"]["extensions"][0]["path"] = "pi-base/node_modules/synthetic/other.js"
  write_document(context, document)
  assert inspect(context)["status"] == "stale"
  document["resources"]["extensions"][0]["capability_id"] = "other-capability"
  write_document(context, document)
  assert inspect(context)["status"] == "stale"


@pytest.mark.parametrize("kind", ["duplicate-json", "nan", "infinity", "oversize", "missing", "file-link", "directory-link"])
def test_fixed_descriptor_read_refuses_nonfinite_duplicate_oversize_or_links(tmp_path, kind):
  context, document = inventory_fixture(tmp_path)
  path = context["runtime_root"] / "runtime/profile.json"
  if kind == "missing": path.unlink()
  elif kind == "file-link":
    path.rename(path.with_name("untrusted.json")); path.symlink_to("untrusted.json")
  elif kind == "directory-link":
    directory = path.parent; directory.rename(directory.with_name("untrusted-runtime")); directory.symlink_to("untrusted-runtime", target_is_directory=True)
  else:
    raw = json.dumps(document).encode()
    if kind == "duplicate-json": raw = raw.replace(b"\"schema_version\": 2", b"\"schema_version\": 2,\"schema_version\": 2")
    elif kind == "nan": raw = raw.replace(b"\"schema_version\": 2", b"\"schema_version\": NaN")
    elif kind == "infinity": raw = raw.replace(b"\"schema_version\": 2", b"\"schema_version\": Infinity")
    elif kind == "oversize": raw = b" " * (128 * 1024 + 1)
    path.write_bytes(raw)
  value = inspect(context)
  assert value["status"] == ("missing" if kind == "missing" else "invalid") and value["resources"] == []


def test_context_and_public_output_resource_limits_are_bounded(tmp_path):
  context, document = inventory_fixture(tmp_path)
  context["expected_resources"]["extensions"] = [{"id":"resource-" + str(i).zfill(5), "capability_id":"native", "path":"pi-base/data"} for i in range(4097)]
  assert inspect(context)["status"] == "invalid"
  rows = [{"id":"r" + "a" * 58 + str(i).zfill(5), "capability_id":"n" + "b" * 63, "path":"pi-base/data"} for i in range(600)]
  context["expected_resources"]["extensions"] = rows; document["resources"]["extensions"] = deepcopy(rows)
  write_document(context, document)
  assert inspect(context)["status"] == "invalid"


def test_read_drift_discards_whole_inventory(tmp_path, monkeypatch):
  context, _ = inventory_fixture(tmp_path)
  original = Tree.open_read
  @contextmanager
  def drift(tree, name, **kwargs):
    with original(tree, name, **kwargs) as (stream, info):
      class MutatingReader:
        def read(self, count):
          raw = stream.read(count)
          path = context["runtime_root"] / "runtime/profile.json"
          path.write_bytes(path.read_bytes() + b" ")
          return raw
      yield MutatingReader(), info
  monkeypatch.setattr(Tree, "open_read", drift)
  assert inspect(context)["status"] == "invalid"


def test_context_unknown_fields_and_foreign_types_refuse_before_file_access(tmp_path, monkeypatch):
  context, _ = inventory_fixture(tmp_path)
  from agentcfg import pi_installed_resource_diagnostics as helper
  monkeypatch.setattr(helper, "Tree", lambda *_args, **_kwargs: pytest.fail("invalid context read"))
  wrong = dict(context, unknown="SYNTHETIC_PRIVATE")
  assert inspect(wrong)["status"] == "invalid"
  class ForeignString(str):
    def __eq__(self, _): pytest.fail("foreign equality")
  assert inspect(context, profile_id=ForeignString("pi-base"))["status"] == "invalid"
  assert inspect(context, dependencies=ForeignString("installed"))["status"] == "not-inspected"


def test_legacy_rows_do_not_import_installed_inventory_helper(tmp_path, monkeypatch):
  import builtins
  from agentcfg import pi_diagnostics
  from test_pi_doctor import projection
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    assert not name.endswith("pi_installed_resource_diagnostics")
    return original(name, *args, **kwargs)
  with monkeypatch.context() as guard:
    guard.setattr(builtins, "__import__", guarded)
    rows = pi_diagnostics.capabilities(projection(tmp_path))
  assert all("profile_plan" not in row for row in rows)


def test_original_doctor_produces_context_from_validated_current_lock_and_runtime_root(tmp_path, monkeypatch, fake_subprocess):
  from agentcfg import commands, pi_diagnostics
  from agentcfg.pi import PiAdapter
  from agentcfg.pi_dependencies import PiBackend
  from test_pi_adapter import ROOT
  from test_pi_capability_manifest import binding_repository
  from test_pi_dependencies import fake_installer
  from test_pi_modern_diagnostics import inputs
  from test_pi_profile_projection import resolved
  workspace, _ = binding_repository(tmp_path)
  backend = PiBackend(profile="pi-base")
  lock = backend.read_lock(workspace.repository)
  calls = []
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer(calls))
  data = resolved({"plugins":[], "skills":[], "rules":[]})
  for name, provider in data["providers"].items():
    provider["base_url"] = "https://synthetic.invalid/v1"
    provider["credential_ref"] = "secret:synthetic-unfilled-" + name
  for name, model in data["models"].items(): model["remote_id"] = "synthetic-" + name
  workspace.agent = "pi"; workspace.adapter = PiAdapter(ROOT); workspace.backend = backend
  workspace.resolved = SimpleNamespace(data=data)
  workspace.cache = tmp_path / "cache"; workspace.local_path = tmp_path / "local.toml"
  workspace.local_path.write_text("schema_version=1\n")
  workspace.binding = {"machine": data["machine"]["id"], "local": str(workspace.local_path), "profile": workspace.profile}
  installed = backend.sync(workspace, lock)
  identity = backend.runtime_identity(workspace, lock)
  seen = []; results = []
  original = pi_diagnostics.capabilities
  def capture(projection):
    seen.append(projection)
    return original(projection)
  monkeypatch.setattr(commands, "workspace", lambda _: workspace)
  monkeypatch.setattr(workspace.adapter, "capability_diagnostics", capture)
  monkeypatch.setattr(pi_diagnostics, "diagnostic_identity", lambda _: inputs()["identity"])
  monkeypatch.setattr(commands, "output", lambda _workspace, _name, value, **_: results.append(value))
  assert commands.cmd_doctor(SimpleNamespace(live=False, input=False)) == 0
  context = seen[0]["installed_resource_context"]
  assert set(context) == {"profile_id", "runtime_root", "lock_identity", "runtime_identity", "slice_identity", "expected_resources"}
  assert context == {"profile_id":"pi-base", "runtime_root":backend.root(workspace, installed["identity"]),
    "lock_identity":lock.identity, "runtime_identity":identity,
    "slice_identity":lock.metadata["profile_slices"]["pi-base"]["identity"],
    "expected_resources":lock.metadata["profile_slices"]["pi-base"]["resource_manifest"]}
  host = next(row for row in results[0]["capabilities"] if row["id"] == "pi-host")
  assert host["profile_plan"]["installed_resource_inventory"]["status"] == "matched"
  assert host["load_evidence"] == host["execution_evidence"] == "not-run"
  assert len(calls) == 3 and fake_subprocess.calls == []

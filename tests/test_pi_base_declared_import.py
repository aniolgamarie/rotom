"""仅Base声明物化与私有命名空间cold import；不执行监督者业务。"""

from contextlib import contextmanager
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import uuid

import pytest

from agentcfg.pi_runtime_files import lock_files, install_files, validate_files


ROOT = Path(__file__).resolve().parents[1]
HELPER = "supervisor/src/agentcfg/pi_lock_resolution.py"
FULL_ONLY = {"pi_delegate", "pi_auxiliary", "pi_delegate_spawn", "pi_login", "pi_reviewer_authority",
  "pi_reviewer_ledger", "pi_reviewer_scopes", "pi_owner_origin", "pi_installed_source", "pi_durable_owner_store",
  "pi_durable_service_index", "pi_python_bundle_runtime", "pi_python_bundle_stage"}


@contextmanager
def materialized():
  declarations = json.loads((ROOT / "agents/pi/dependencies-modern.json").read_bytes())["profiles"]["pi-base"]["runtime_files"]
  rows = lock_files(ROOT, declarations)
  with tempfile.TemporaryDirectory(prefix="pi-base-declared-import-", dir="/tmp") as directory:
    stage = Path(directory)
    install_files(ROOT, stage, rows)
    validate_files(stage, rows, generated=())
    yield stage, rows
  assert not stage.exists()


@contextmanager
def cold_package(stage):
  package = stage / "supervisor/src/agentcfg"
  prefix = "_pi_base_declared_" + uuid.uuid4().hex
  original_cache = {name: module for name, module in sys.modules.items() if name == "agentcfg" or name.startswith("agentcfg.")}
  original_bytecode = sys.dont_write_bytecode
  try:
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(prefix, package / "__init__.py", submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[prefix] = module
    spec.loader.exec_module(module)
    yield prefix, package
  finally:
    for name in tuple(sys.modules):
      if name == prefix or name.startswith(prefix + "."):
        del sys.modules[name]
    sys.dont_write_bytecode = original_bytecode
    actual_cache = {name: module for name, module in sys.modules.items() if name == "agentcfg" or name.startswith("agentcfg.")}
    assert actual_cache.keys() == original_cache.keys()
    assert all(actual_cache[name] is module for name, module in original_cache.items())
    assert not any(name == prefix or name.startswith(prefix + ".") for name in sys.modules)


def test_actual_base_materialized_package_cold_imports_shared_host_definitions(record_property):
  with materialized() as (stage, rows), cold_package(stage) as (prefix, package):
    host = importlib.import_module(prefix + ".pi_host")
    assert host.HostSupervisor.__module__ == prefix + ".pi_host"
    declared = {row["path"]: row for row in rows}
    helper = declared[HELPER]
    assert helper["transform"] == "copy" and helper["mode"] == 0o600
    assert (stage / HELPER).read_bytes() == (ROOT / helper["source"]).read_bytes()
    observed = []
    for name, module in tuple(sys.modules.items()):
      if name != prefix and not name.startswith(prefix + "."):
        continue
      path = Path(module.__file__).resolve()
      assert path.is_relative_to(package.resolve())
      relative = path.relative_to(stage).as_posix()
      row = declared[relative]
      digest = hashlib.sha256(path.read_bytes()).hexdigest()
      assert digest == row["digest"] and (path.stat().st_mode & 0o777) == row["mode"]
      observed.append({"name": name, "file": str(path), "sha256": digest})
    names = {entry["name"].removeprefix(prefix + ".") for entry in observed}
    assert "pi_lock_resolution" in names and not names & FULL_ONLY
    assert not list(stage.rglob("*.pyc")) and not list(stage.rglob("__pycache__"))
    record_property("owned_module_files", json.dumps(observed, sort_keys=True))
    record_property("declared_rows", len(rows))
    record_property("qualification", "private namespace only; shared stdlib/third-party modules, no fresh interpreter/host qualification")


def test_removed_shared_helper_causes_real_missing_module_without_live_fallback(record_property):
  with materialized() as (stage, rows):
    (stage / HELPER).unlink()
    with cold_package(stage) as (prefix, package):
      with pytest.raises(ModuleNotFoundError) as caught:
        importlib.import_module(prefix + ".pi_host")
      assert caught.value.name == prefix + ".pi_lock_resolution"
      loaded = {name.removeprefix(prefix + ".") for name in sys.modules if name.startswith(prefix + ".")}
      assert not loaded & FULL_ONLY
      record_property("missing_module", caught.value.name)
      record_property("qualified_before_deletion", "original lock_files/install_files/validate_files generated=() completed")

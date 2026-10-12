"""静态产品探针包；仅临时文件、合成源与系统事实，不启动进程。"""

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from agentcfg import pi_shell_product_probe_bundle as module
from agentcfg.pi_runtime_files import lock_files
from agentcfg.schema import ConfigError


@pytest.fixture
def bundle(tmp_path, monkeypatch):
  repository = tmp_path / "repository"; repository.mkdir(mode=0o700)
  source = repository / "src/agentcfg/example.py"; source.parent.mkdir(parents=True)
  source.write_bytes(b"VALUE = 1\n"); source.chmod(0o600)
  rows = lock_files(repository, [{"source": "src/agentcfg/example.py", "path": "supervisor/src/agentcfg/example.py", "transform": "copy"}])
  monkeypatch.setattr(module, "ROOT", repository)
  controller = repository / "src/agentcfg/controller.py"
  controller.write_bytes(b"from .pi_runtime_files import value\ndef unused():\n  from .pi_shell_probe import value\n"); controller.chmod(0o600)
  for name, data in {"__init__.py": b"\"\"\"synthetic package\"\"\"\n", "pi_runtime_files.py": b"value = 1\n",
      "pi_shell_probe.py": b"from .pi_shell_probe_protocol import value\nfrom .helper import value\n",
      "pi_shell_probe_protocol.py": b"value = 1\n", "helper.py": b"value = 1\n"}.items():
    path = source.parent / name; path.write_bytes(data); path.chmod(0o600)
  monkeypatch.setattr(module, "CONTROLLERS", ("src/agentcfg/controller.py",))
  data = repository / "agents/pi/schemas/options.schema.json"
  data.parent.mkdir(parents=True); data.write_bytes(b"{}\n"); data.chmod(0o600)
  monkeypatch.setattr(module, "sources", lambda: (b"synthetic-helper-never-executed", rows))
  monkeypatch.setattr(module, "file_identity", lambda path: {"path": str(path),
    "sha256": module.sha(path.read_bytes()) if path.is_relative_to(repository) else "c" * 64, "device": 1, "inode": 2})
  monkeypatch.setattr(module, "dependencies", lambda: {"path": "/synthetic-python-deps", "device": 1, "inode": 3})
  directory = tmp_path / "bundle"
  plan = module.prepare(directory)
  return directory, plan, repository


def save(directory, plan):
  (directory / "plan.json").write_bytes(module.json_bytes(plan))


def refresh(directory, plan):
  plan["files"], plan["directories"] = module.inventory(directory)
  save(directory, plan)


def test_prepare_has_fixed_cases_synthetic_receipt_and_no_writer_or_execution(bundle):
  directory, plan, _ = bundle
  assert module.preflight(directory) == plan
  assert plan["cases"] == ["allowed", "denied", "background"]
  runtime = directory / "inputs" / plan["runtime_identity"]
  helper = runtime / "bin/pi-bwrap"
  assert helper.read_bytes() == b"synthetic-helper-never-executed" and helper.stat().st_mode & 0o777 == 0o700
  receipt = json.loads((runtime / ".agentcfg-receipt.json").read_bytes())
  assert receipt["schema_version"] == 2 and receipt["identity"] == plan["runtime_identity"]
  assert receipt["lock_identity"] == plan["lock_identity"] and receipt["slice_identity"] == plan["slice_identity"]
  assert ".agentcfg-receipt.json" not in receipt["files"]
  actual = {path.relative_to(runtime).as_posix() for path in runtime.rglob("*") if path.is_file()}
  assert set(receipt["files"]) == actual - {".agentcfg-receipt.json"}
  assert plan["files"]["inputs/" + plan["runtime_identity"] + "/.agentcfg-receipt.json"]["sha256"] == module.sha((runtime / ".agentcfg-receipt.json").read_bytes())
  for case in module.CASES:
    root = directory / "cases" / case
    assert (root / "work/project/.git/HEAD").read_bytes() == module.HEAD
    assert not (root / "work/project/.git/agentcfg").exists()
    for empty in ("state", "instance", "private-account-home", "observations", "work/home"):
      assert (root / empty).is_dir() and (root / empty).stat().st_mode & 0o777 == 0o700
    for path, data in module.CANARIES.items(): assert (root / "work" / path).read_bytes() == data
  assert not (directory / "execution-started.json").exists()


@pytest.mark.parametrize("fault", ["extra-file", "extra-dir", "symlink", "hardlink", "mode", "dir-mode", "helper", "source-output", "receipt", "profile", "commands", "canary", "payload", "heartbeat", "head", "prebuilt-writer", "replay"])
def test_preflight_rejects_even_resealed_bundle_drift(bundle, fault):
  directory, plan, _ = bundle
  runtime = directory / "inputs" / plan["runtime_identity"]
  work = directory / "cases/allowed/work"
  if fault == "extra-file": (runtime / "extra").write_bytes(b"extra"); (runtime / "extra").chmod(0o600)
  elif fault == "extra-dir": (directory / "extra").mkdir(mode=0o700)
  elif fault == "symlink": (directory / "link").symlink_to(runtime / "bin/pi-bwrap")
  elif fault == "hardlink": os.link(runtime / "bin/pi-bwrap", directory / "alias")
  elif fault == "mode": (runtime / "bin/pi-bwrap").chmod(0o600)
  elif fault == "dir-mode": (work / "readonly").chmod(0o755)
  elif fault == "helper": (runtime / "bin/pi-bwrap").write_bytes(b"changed")
  elif fault == "source-output": (runtime / "supervisor/src/agentcfg/example.py").write_bytes(b"VALUE = 2\n")
  elif fault in ("receipt", "profile", "commands"):
    path = {"receipt": ".agentcfg-receipt.json", "profile": "runtime/profile.json", "commands": "runtime/commands.json"}[fault]
    (runtime / path).write_bytes(b"{}\n")
  elif fault in ("canary", "payload", "heartbeat", "head"):
    path = {"canary": "outside/canary", "payload": "readonly/payload.py", "heartbeat": "readonly/heartbeat.py", "head": "project/.git/HEAD"}[fault]
    (work / path).write_bytes(b"changed")
  elif fault == "prebuilt-writer": (work / "project/.git/agentcfg").mkdir(mode=0o700)
  else: (directory / "execution-started.json").write_bytes(b"{}\n"); (directory / "execution-started.json").chmod(0o600)
  if fault not in ("symlink", "hardlink", "mode", "dir-mode"):
    refresh(directory, plan)
  with pytest.raises(ConfigError, match="pi-shell-product-probe-bundle"): module.preflight(directory)


@pytest.mark.parametrize("fault", ["unknown", "schema-bool", "cases-order", "nonce", "nonce-duplicate", "runtime", "lock", "slice", "helper", "controllers", "rows", "system-bool", "file-mode-bool", "dir-duplicate"])
def test_plan_closed_types_and_independent_values(bundle, fault):
  directory, original, _ = bundle; plan = deepcopy(original)
  if fault == "unknown": plan["secret"] = "must not appear"
  elif fault == "schema-bool": plan["schema_version"] = True
  elif fault == "cases-order": plan["cases"].reverse()
  elif fault == "nonce": plan["nonces"]["allowed"] = "A" * 32
  elif fault == "nonce-duplicate": plan["nonces"]["allowed"] = plan["nonces"]["denied"]
  elif fault in ("runtime", "lock", "slice", "helper"): plan[fault + "_identity"] = "f" * 64
  elif fault == "controllers": plan["controllers"]["extra"] = "c" * 64
  elif fault == "rows": plan["source_rows"][0]["secret"] = True
  elif fault == "system-bool": plan["system"]["python"]["device"] = True
  elif fault == "file-mode-bool": next(iter(plan["files"].values()))["mode"] = True
  else: plan["directories"].append(plan["directories"][0])
  save(directory, plan)
  with pytest.raises(ConfigError, match="pi-shell-product-probe-bundle") as error: module.preflight(directory)
  assert "must not appear" not in str(error.value)


@pytest.mark.parametrize("raw", [b'{"schema_version":1,"schema_version":1}', b'NaN', b'Infinity', b'\xff', b'{} trailing'])
def test_plan_ambiguous_json_rejected(bundle, raw):
  directory, _, _ = bundle; (directory / "plan.json").write_bytes(raw)
  with pytest.raises(ConfigError, match="pi-shell-product-probe-bundle"): module.preflight(directory)


def test_prepare_refuses_existing_or_relative_directory(bundle):
  directory, plan, _ = bundle
  with pytest.raises(ConfigError): module.prepare(directory)
  with pytest.raises(ConfigError): module.prepare(Path("relative"))
  assert module.preflight(directory) == plan


def test_current_repository_input_drift_is_not_repaired_by_bundle_manifest(bundle):
  directory, plan, repository = bundle
  (repository / "src/agentcfg/example.py").write_bytes(b"VALUE = 9\n")
  refresh(directory, plan)
  with pytest.raises(ConfigError): module.preflight(directory)


def test_current_controller_drift_refuses_old_bundle(bundle):
  directory, _, repository = bundle
  (repository / "src/agentcfg/controller.py").write_bytes(b"CONTROL = 2\n")
  with pytest.raises(ConfigError, match="pi-shell-product-probe-bundle"): module.preflight(directory)


@pytest.mark.parametrize("name", ["pi_shell_probe_protocol.py", "helper.py", "pi_runtime_files.py", "__init__.py"])
def test_actual_static_auxiliary_closure_drift_cannot_be_resealed(bundle, name):
  directory, plan, repository = bundle
  (repository / "src/agentcfg" / name).write_bytes(b"value = 99\n")
  refresh(directory, plan)
  with pytest.raises(ConfigError, match="pi-shell-product-probe-bundle"): module.preflight(directory)


def test_static_closure_binds_function_imports_without_copying_or_executing_them(bundle):
  directory, plan, _ = bundle
  assert set(plan["controllers"]) == {"agents/pi/schemas/options.schema.json"} | {"src/agentcfg/" + name for name in
    ("controller.py", "__init__.py", "pi_runtime_files.py", "pi_shell_probe.py", "pi_shell_probe_protocol.py", "helper.py")}
  runtime = directory / "inputs" / plan["runtime_identity"]
  assert not (runtime / "supervisor/src/agentcfg/helper.py").exists()


@pytest.mark.parametrize("target", ["/tmp", "/home/synthetic-new-bundle", "/var/tmp/synthetic-bundle", "/tmp/../home/synthetic-bundle"])
def test_bundle_directory_is_strict_tmp_descendant_before_sources_or_writes(monkeypatch, target):
  monkeypatch.setattr(module, "sources", lambda: pytest.fail("invalid directory must precede source reads"))
  with pytest.raises(ConfigError, match="pi-shell-product-probe-bundle"): module.prepare(target)


def test_missing_static_local_import_refuses_before_bundle_creation(tmp_path, bundle):
  _, _, repository = bundle
  (repository / "src/agentcfg/helper.py").unlink()
  target = tmp_path / "new-bundle"
  with pytest.raises(ConfigError, match="pi-shell-product-probe-bundle"): module.prepare(target)
  assert not target.exists()


def test_parent_options_schema_drift_is_independently_bound(bundle):
  directory, plan, repository = bundle
  (repository / "agents/pi/schemas/options.schema.json").write_bytes(b"{\"changed\":true}\n")
  refresh(directory, plan)
  with pytest.raises(ConfigError, match="pi-shell-product-probe-bundle"): module.preflight(directory)

"""单一真实 codec 运行映射；只读字节/临时 Tree，不执行 Node。"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import stat

import pytest
from agentcfg.pi_runtime_files import lock_files, verify_sources, install_files, validate_files, validate_manifest
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, ensure_private

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "agents/pi/packages/durable-service/src/owner-message.ts"
TARGET = "runtime/durable-owner-message.mjs"
SHA = "ae51f5ab739a80006639feead7b22822c5f135430e41926f59420ec2127a1238"


def declaration(): return {"source": SOURCE, "path": TARGET, "transform": "ts-module"}
def locked(): return {**declaration(), "input_digest": SHA, "digest": SHA, "mode": 0o600}


@pytest.fixture
def selected(tmp_path):
  repository, stage = tmp_path / "repository", tmp_path / "stage"
  ensure_private(repository); ensure_private(stage)
  raw = (ROOT / SOURCE).read_bytes(); assert len(raw) == 8790 and hashlib.sha256(raw).hexdigest() == SHA
  path = repository / SOURCE; path.parent.mkdir(parents=True); path.write_bytes(raw)
  return repository, stage, path, raw


def test_actual_codec_declaration_lock_transform_install_and_full_closure(selected):
  repository, stage, path, raw = selected
  rows = lock_files(repository, [declaration()]); assert rows == [locked()]
  validate_manifest(rows); verify_sources(repository, rows); install_files(repository, stage, rows)
  output = stage / TARGET
  assert output.read_bytes() == raw and hashlib.sha256(output.read_bytes()).hexdigest() == SHA
  assert stat.S_IMODE(output.stat().st_mode) == 0o600 and output.stat().st_nlink == 1
  validate_files(stage, rows, generated=())
  assert {p.relative_to(stage).as_posix() for p in stage.rglob("*")} == {"runtime", TARGET}


def test_exact_locked_row_is_permitted_without_relaxing_locked_validation():
  validate_manifest([locked()])


@pytest.mark.parametrize("bad_source", [
  "agents/pi/packages/durable-service/src/owner-messages.ts", "agents/pi/packages/durable-service/src/storage.ts",
  "agents/pi/packages/durable-service/src/nested/owner-message.ts", "agents/pi/packages/other/src/owner-message.ts",
])
def test_neighbor_or_other_package_source_is_not_whitelisted(selected, bad_source):
  repository, stage, _, raw = selected; path = repository / bad_source; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
  row = {**declaration(), "source": bad_source}
  with pytest.raises(ConfigError): lock_files(repository, [row])
  assert not list(stage.iterdir())
  with pytest.raises(ConfigError): validate_manifest([{**locked(), "source": bad_source}])


@pytest.mark.parametrize("fault", ["target-js", "target-ts", "target-other", "copy", "transform-other", "unknown", "escape", "mode", "bad-hash"])
def test_exact_target_transform_and_closed_row_fields(selected, fault):
  repository, stage, _, _ = selected; row = declaration()
  if fault == "target-js": row["path"] = "runtime/durable-owner-message.js"
  if fault == "target-ts": row["path"] = "runtime/durable-owner-message.ts"
  if fault == "target-other": row["path"] = "runtime/owner-message.mjs"
  if fault == "copy": row["transform"] = "copy"
  if fault == "transform-other": row["transform"] = "typescript"
  if fault == "unknown": row["role"] = "synthetic-secret"
  if fault == "escape": row["source"] = "../" + SOURCE
  if fault == "mode": row["mode"] = 0o777
  if fault == "bad-hash": row["digest"] = "bad"
  with pytest.raises(ConfigError): lock_files(repository, [row])
  assert not list(stage.iterdir())
  bad = {**locked(), **row}
  if fault == "mode": bad["mode"] = 0o777
  if fault == "bad-hash": bad["digest"] = "bad"
  with pytest.raises(ConfigError): validate_manifest([bad])


@pytest.mark.parametrize("reverse", [False, True])
def test_different_legitimate_sources_cannot_share_target(selected, reverse):
  repository, stage, _, raw = selected
  legacy = {"source": "agents/pi/runtime/durable-owner-message.ts", "path": TARGET, "transform": "ts-module"}
  path = repository / legacy["source"]; path.parent.mkdir(parents=True); path.write_bytes(raw)
  assert lock_files(repository, [legacy])[0]["path"] == TARGET
  assert lock_files(repository, [declaration()])[0]["path"] == TARGET
  rows = [legacy, declaration()]; rows = list(reversed(rows)) if reverse else rows
  with pytest.raises(ConfigError): lock_files(repository, rows)
  with pytest.raises(ConfigError): validate_manifest([{**row, "input_digest": SHA, "digest": SHA, "mode": 0o600} for row in rows])
  assert not list(stage.iterdir())


@pytest.mark.parametrize("fault", ["source-changed", "source-missing", "input-digest", "output-digest"])
def test_stale_input_and_output_digest_never_install(selected, fault):
  repository, stage, path, _ = selected; rows = lock_files(repository, [declaration()])
  if fault == "source-changed": path.write_bytes(path.read_bytes()+b"\n")
  if fault == "source-missing": path.unlink()
  if fault == "input-digest": rows[0]["input_digest"] = "f"*64
  if fault == "output-digest": rows[0]["digest"] = "f"*64
  with pytest.raises(ConfigError): verify_sources(repository, rows)
  with pytest.raises(ConfigError): install_files(repository, stage, rows)
  assert not list(stage.iterdir())


@pytest.mark.parametrize("fault", ["bytes", "mode", "extra-file", "extra-directory"])
def test_installed_byte_mode_and_inventory_drift_reject(selected, fault):
  repository, stage, _, _ = selected; rows = lock_files(repository, [declaration()]); install_files(repository, stage, rows)
  output = stage / TARGET
  if fault == "bytes": output.write_bytes(b"changed")
  if fault == "mode": output.chmod(0o700)
  if fault == "extra-file": (output.parent / "extra.mjs").write_bytes(b"extra")
  if fault == "extra-directory": (output.parent / "extra").mkdir()
  with pytest.raises(Conflict): validate_files(stage, rows, generated=())

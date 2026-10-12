"""真实临时源码映射/转换/安装；不启动Node或任何bootstrap/proc/fd3。"""
import hashlib
from pathlib import Path

import pytest

from agentcfg.pi_runtime_files import install_files, lock_files, validate_files
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict

ROOT = Path(__file__).resolve().parents[1]
DECLARATIONS = [
  {"source":"agents/pi/runtime/durable-owner-bootstrap.ts", "path":"runtime/durable-owner-bootstrap.mjs", "transform":"ts-module"},
  {"source":"agents/pi/packages/durable-service/src/owner-message.ts", "path":"runtime/durable-owner-message.mjs", "transform":"ts-module"},
]


def fixture(tmp_path):
  repository = tmp_path / "source"; repository.mkdir(mode=0o700)
  for row in DECLARATIONS:
    path = repository / row["source"]; path.parent.mkdir(parents=True); path.write_bytes((ROOT / row["source"]).read_bytes())
  stage = tmp_path / "stage"; stage.mkdir(mode=0o700)
  rows = lock_files(repository, DECLARATIONS)
  install_files(repository, stage, rows)
  return repository, stage, rows


def test_real_owner_bootstrap_codec_mapping_preserves_exact_plain_JS_and_mode(tmp_path):
  repository, stage, rows = fixture(tmp_path)
  validate_files(stage, rows, generated=())
  assert [row["path"] for row in rows] == sorted(row["path"] for row in DECLARATIONS)
  for row in rows:
    raw = (ROOT / row["source"]).read_bytes(); target = stage / row["path"]
    assert target.read_bytes() == raw and row["input_digest"] == row["digest"] == hashlib.sha256(raw).hexdigest()
    assert row["mode"] == 0o600 and target.stat().st_mode & 0o777 == 0o600
  assert b'from "./durable-owner-message.mjs"' in (stage / "runtime/durable-owner-bootstrap.mjs").read_bytes()


@pytest.mark.parametrize("fault", ["source", "installed", "mode", "extra", "missing"])
def test_real_owner_bootstrap_mapping_drift_is_rejected(tmp_path, fault):
  repository, stage, rows = fixture(tmp_path)
  target = stage / "runtime/durable-owner-bootstrap.mjs"
  if fault == "source":
    (repository / DECLARATIONS[0]["source"]).write_bytes(b"changed source")
    with pytest.raises(ConfigError): install_files(repository, stage, rows)
  else:
    if fault == "installed": target.write_bytes(b"changed installed bytes")
    elif fault == "mode": target.chmod(0o700)
    elif fault == "extra": (stage / "runtime/extra.mjs").write_bytes(b"extra")
    else: target.unlink()
    with pytest.raises((ValueError, Conflict)): validate_files(stage, rows, generated=())

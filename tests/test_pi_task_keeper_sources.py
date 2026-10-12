"""生成包来源边界；默认编译器是固定fixture替身，不运行Node/SDK。"""
import hashlib
import json
from pathlib import Path
import pytest
from agentcfg import pi_task_keeper_sources as sources
from agentcfg.schema import ConfigError


def fixture(tmp_path, monkeypatch):
  original = b"export const value: number = 1;\n"
  output = b"export const value = 1;\n"
  source = "agents/pi/packages/task-keeper/src/fixture.ts"
  target = "src/fixture.mjs"
  directory = tmp_path / "agents/pi/packages/task-keeper-modern"
  (tmp_path / source).parent.mkdir(parents=True)
  (tmp_path / source).write_bytes(original)
  (directory / target).parent.mkdir(parents=True)
  (directory / target).write_bytes(output)
  compiler = {"name": "node", "version": "v24.14.0", "sha256": "a" * 64,
    "api": "node:module.stripTypeScriptTypes", "mode": "transform"}
  fixed_compiler = dict(compiler)
  row = {"source": source, "path": target, "source_sha256": hashlib.sha256(original).hexdigest(),
    "sha256": hashlib.sha256(output).hexdigest(), "size": len(output)}
  document = {"schema_version": 2, "transform": "own-runtime-node24-transform", "compiler": compiler, "files": [row]}
  calls = []
  def compile_rows(rows):
    calls.append(rows)
    assert rows[0]["typescript"] is True
    assert rows[0]["text"] == original.decode()
    return {target: output}, fixed_compiler
  monkeypatch.setattr(sources, "compile_sources", compile_rows)
  def save(): (directory / "core-source-manifest.json").write_text(json.dumps(document))
  save()
  return directory, document, save, calls


def test_compiled_core_requires_original_source_and_reproducible_public_compiler_output(tmp_path, monkeypatch):
  directory, document, save, calls = fixture(tmp_path, monkeypatch)
  sources.verify_generated(tmp_path, "agents/pi/packages/task-keeper-modern")
  assert len(calls) == 1
  # 同时篡改output与自身pin仍必须由原固定compiler的再生比较拒绝。
  body = b"export const value = 2;\n"
  (directory / "src/fixture.mjs").write_bytes(body)
  document["files"][0].update(sha256=hashlib.sha256(body).hexdigest(), size=len(body)); save()
  with pytest.raises(ConfigError, match="pi-task-keeper-generated-source"):
    sources.verify_generated(tmp_path, "agents/pi/packages/task-keeper-modern")


@pytest.mark.parametrize("change", ["unknown-source", "missing-output", "foreign-compiler"])
def test_unknown_or_incomplete_generated_closure_is_unavailable(tmp_path, monkeypatch, change):
  directory, document, save, calls = fixture(tmp_path, monkeypatch)
  if change == "unknown-source": document["files"][0]["source"] = "shared/unselected.ts"
  elif change == "missing-output": (directory / "src/fixture.mjs").unlink()
  else: document["compiler"]["sha256"] = "b" * 64
  save()
  with pytest.raises(ConfigError, match="pi-task-keeper-generated-source"):
    sources.verify_generated(tmp_path, "agents/pi/packages/task-keeper-modern")
  if change != "foreign-compiler": assert calls == []

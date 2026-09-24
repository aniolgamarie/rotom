"""固定模型数据的格式、大小和摘要检查；只用合成 GGUF 头，不执行推理。"""
import hashlib
import json

import pytest

from agentcfg import pi_readseek_vision as vision
from agentcfg.process import DependencyError
from agentcfg.storage import Tree


def prepared(tmp_path, monkeypatch):
  stage = tmp_path / "stage"
  content = b"GGUF\x03\0\0\0synthetic model; never execute"
  expected = {name: {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()} for name in vision.FILES}
  monkeypatch.setattr(vision, "FILES", expected)
  with Tree(stage, create=True) as tree:
    for name in expected: tree.write_new(vision.target(name), content)
  return stage, {"source_ids": sorted(vision.SOURCE_IDS)}


def test_model_pair_matches_the_native_cache_layout_and_stays_unexecuted(tmp_path, monkeypatch):
  stage, piece = prepared(tmp_path, monkeypatch)
  vision.install_vision(stage, piece)
  receipt = json.loads((stage / "runtime/readseek-vision.json").read_text())
  assert receipt["revision"] == vision.REVISION and receipt["model_execution"] == "not-run"
  assert (stage / vision.HUB / vision.REPOSITORY / "blobs").is_dir()
  assert all((stage / value["path"]).is_file() for value in receipt["files"].values())


@pytest.mark.parametrize("kind", ["closure", "missing", "size", "header", "digest"])
def test_invalid_vision_assets_never_create_a_ready_receipt(tmp_path, monkeypatch, kind):
  stage, piece = prepared(tmp_path, monkeypatch)
  path = stage / vision.target(next(iter(vision.FILES)))
  if kind == "closure": piece["source_ids"].pop()
  if kind == "missing": path.unlink()
  if kind == "size": path.write_bytes(path.read_bytes()[:-1])
  if kind == "header": path.write_bytes(b"FAIL" + path.read_bytes()[4:])
  if kind == "digest": path.write_bytes(path.read_bytes()[:-1] + b"!")
  with pytest.raises(DependencyError): vision.install_vision(stage, piece)
  assert not (stage / "runtime/readseek-vision.json").exists()


def test_selected_readseek_cannot_omit_its_data_dependencies():
  with pytest.raises(ValueError): vision.validate_closure(["pi-readseek"])
  with pytest.raises(ValueError): vision.validate_closure(["pi-readseek", "readseek-vision-model"])
  vision.validate_closure(["pi-readseek", *vision.SOURCE_IDS])

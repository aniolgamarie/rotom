"""大模型资产使用有界流和假下载器；不访问模型网络或启动宿主。"""
import hashlib
import io
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from agentcfg.pi_assets import install_assets, validate_asset, validate_asset_platforms
from agentcfg.pi_runtime_packages import inventory
from agentcfg.process import DependencyError
from agentcfg.storage import Conflict, Tree


def fixture(tmp_path):
  body = b"GGUF synthetic model data " * 100000
  source = {"kind": "asset", "format": "raw", "platform": "all", "url": "https://models.example.invalid/fixed/model.gguf",
    "target": "data/readseek/model.gguf", "size": len(body), "archive_digest": hashlib.sha256(body).hexdigest(),
    "license_files": ["agents/pi/build/licenses/model/LICENSE"]}
  repo, stage = tmp_path / "repo", tmp_path / "stage"
  with Tree(repo, create=True) as tree: tree.write_new(source["license_files"][0], b"synthetic license")
  with Tree(stage, create=True): pass
  piece = {"source_ids": ["model"]}
  manifest = {"platforms": ["linux-x86_64", "linux-arm64", "darwin-x86_64", "darwin-arm64"], "sources": {"model": source}}
  return repo, stage, piece, manifest, body


def test_data_asset_streams_with_exact_size_hash_and_platform_independence(tmp_path, monkeypatch):
  repo, stage, piece, manifest, body = fixture(tmp_path)
  calls = []
  class Stream(io.BytesIO):
    def read(self, count=-1):
      assert 0 < count <= 1024 * 1024; calls.append(count)
      return super().read(count)
  monkeypatch.setattr("agentcfg.pi_assets.open_download", lambda _: Stream(body))
  validate_asset(manifest["sources"]["model"]); validate_asset_platforms(piece, manifest)
  install_assets(repo, stage, piece, manifest, "linux-x86_64")
  target = stage / "data/readseek/model.gguf"
  assert target.read_bytes() == body and target.stat().st_nlink == 1
  assert target.stat().st_mode & 0o777 == 0o600 and len(calls) > 2
  # 运行包盘点必须流式计算，不能把整个模型交给 Tree.read。
  monkeypatch.setattr(Tree, "read", lambda *a, **k: pytest.fail("unbounded inventory read"))
  assert inventory(stage)["data/readseek/model.gguf"]["sha256"] == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("kind", ["short", "long", "digest", "existing", "broken-stream"])
def test_failed_data_download_never_publishes_partial_bytes_or_overwrites_existing_files(tmp_path, monkeypatch, kind):
  repo, stage, piece, manifest, body = fixture(tmp_path)
  if kind == "short": body = body[:-1]
  if kind == "long": body += b"extra"
  if kind == "digest": body = b"x" + body[1:]
  if kind == "existing":
    with Tree(stage) as tree: tree.write_new("data/readseek/model.gguf", b"existing sentinel")
  class Stream(io.BytesIO):
    def read(self, count=-1):
      if kind == "broken-stream" and self.tell(): raise OSError("synthetic signed URL must not escape")
      return super().read(count)
  monkeypatch.setattr("agentcfg.pi_assets.open_download", lambda _: Stream(body))
  with pytest.raises(DependencyError) as error: install_assets(repo, stage, piece, manifest, "linux-x86_64")
  assert "signed URL" not in str(error.value)
  assert not list(stage.rglob(".asset-*"))
  target = stage / "data/readseek/model.gguf"
  assert target.read_bytes() == b"existing sentinel" if kind == "existing" else not target.exists()


def test_raw_asset_schema_rejects_executable_layout_missing_size_and_mixed_platform_sources(tmp_path):
  _, _, piece, manifest, _ = fixture(tmp_path)
  source = manifest["sources"]["model"]
  schema = json.loads((Path(__file__).parents[1] / "schemas/pi-lock.schema.json").read_text())["properties"]["sources"]["additionalProperties"]
  assert Draft202012Validator(schema).is_valid(source)
  assert not Draft202012Validator(schema).is_valid({key: value for key, value in source.items() if key != "size"})
  assert not Draft202012Validator(schema).is_valid({**source, "platform": "linux-x86_64"})
  with pytest.raises(ValueError): validate_asset({**source, "target": "bin/model"})
  manifest["sources"]["duplicate"] = {**source, "platform": "linux-x86_64"}; piece["source_ids"].append("duplicate")
  with pytest.raises(ValueError): validate_asset_platforms(piece, manifest)


def test_stream_checks_identity_at_close_and_never_follows_a_replaced_leaf(tmp_path):
  with Tree(tmp_path / "state", create=True) as tree:
    tree.write_new("source", b"original")
    with pytest.raises(Conflict):
      with tree.open_read("source") as (stream, info):
        assert info.st_size == 8 and stream.read(4) == b"orig"
        (tree.root / "source").unlink(); (tree.root / "source").write_bytes(b"replacement")
    (tree.root / "source").unlink(); (tree.root / "source").symlink_to(tmp_path / "outside")
    with pytest.raises(Conflict):
      with tree.open_read("source"): pytest.fail("symlink should not open")

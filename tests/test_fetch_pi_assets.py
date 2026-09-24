"""vendor资产重建脚本只接受固定来源与摘要一致的内容；urlopen用夹具替身，不建真实网络。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

from agentcfg.schema import ConfigError

_spec = importlib.util.spec_from_file_location("fetch_pi_assets", Path(__file__).resolve().parents[1] / "scripts" / "fetch-pi-assets.py")
fetch_pi_assets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_pi_assets)


def repository(tmp_path, content=b"synthetic asset bytes\n"):
  root = tmp_path / "repo"
  digest = hashlib.sha256(content).hexdigest()
  document = {"schema_version": 1, "sources": {
    "fixture-asset": {"kind": "asset", "url": "https://fixtures.invalid/asset.tgz", "archive_digest": digest,
      "platform": "linux-x86_64", "archive_member": "fixture", "target": "bin/fixture", "license_files": ["agents/pi/build/licenses/fixture/LICENSE"],
      "vendor_path": "vendor/fixture-asset-" + digest + ".tgz"},
    "fixture-raw": {"kind": "asset", "format": "raw", "platform": "all", "url": "https://fixtures.invalid/model.gguf",
      "archive_digest": digest, "size": len(content), "target": "data/readseek/model.gguf", "license_files": ["agents/pi/build/licenses/fixture/LICENSE"],
      "vendor_path": "vendor/fixture-raw-" + digest + ".gguf"}}}
  (root / "agents/pi").mkdir(parents=True)
  (root / "agents/pi/dependencies.json").write_text(json.dumps(document))
  return root, content


class FakeResponse:
  def __init__(self, body, status=200):
    self.body, self.status = body, status
  def read(self, size=-1):
    chunk, self.body = self.body[:size], self.body[size:]
    return chunk
  def __enter__(self): return self
  def __exit__(self, *_args): return False


def fake_urlopen(content, *, cut=None, calls=None):
  state = {"cut": cut}
  def opener(request, timeout=0):
    headers = dict(request.header_items())
    offset = 0
    if "Range" in headers:
      offset = int(headers["Range"].split("=")[1].split("-")[0])
    if calls is not None: calls.append(offset)
    body = content[offset:]
    if state["cut"] is not None and offset == 0:
      body = body[:state["cut"]]; state["cut"] = None
    return FakeResponse(body, 206 if offset else 200)
  return opener


def test_fetch_publishes_only_digest_verified_assets_and_skips_existing(tmp_path, monkeypatch):
  root, content = repository(tmp_path)
  monkeypatch.setattr(fetch_pi_assets, "urlopen", fake_urlopen(content))
  assert fetch_pi_assets.main(["--repository", str(root)]) == 0
  document = json.loads((root / "agents/pi/dependencies.json").read_text())
  for source in document["sources"].values():
    published = root / "locks/pi/vendor" / Path(source["vendor_path"]).name
    assert published.read_bytes() == content and published.stat().st_mode & 0o777 == 0o600
  # 已存在且摘要一致时跳过，不重复下载。
  calls = []
  monkeypatch.setattr(fetch_pi_assets, "urlopen", fake_urlopen(content, calls=calls))
  assert fetch_pi_assets.main(["--repository", str(root)]) == 0
  assert calls == []


def test_resumed_transfer_reassembles_and_verifies(tmp_path, monkeypatch):
  root, content = repository(tmp_path)
  # 首次传输在cut处截断，续传从Range偏移补齐；最终内容必须完整且通过摘要校验。
  calls = []
  monkeypatch.setattr(fetch_pi_assets, "urlopen", fake_urlopen(content, cut=len(content) // 2, calls=calls))
  monkeypatch.setattr(fetch_pi_assets.time, "sleep", lambda _seconds: None)
  assert fetch_pi_assets.main(["--repository", str(root), "--only", "fixture-asset"]) == 0
  document = json.loads((root / "agents/pi/dependencies.json").read_text())
  published = root / "locks/pi/vendor" / Path(document["sources"]["fixture-asset"]["vendor_path"]).name
  assert published.read_bytes() == content


def test_digest_mismatch_never_publishes_and_refuses_unverified_existing(tmp_path, monkeypatch):
  root, content = repository(tmp_path)
  monkeypatch.setattr(fetch_pi_assets, "urlopen", fake_urlopen(b"corrupted transfer\n"))
  with pytest.raises(ConfigError, match="digest-mismatch"):
    fetch_pi_assets.main(["--repository", str(root)])
  assert not list((root / "locks/pi/vendor").glob("fixture*"))
  # 摘要不一致的已存在文件默认拒绝覆盖；--force重下并修复。
  document = json.loads((root / "agents/pi/dependencies.json").read_text())
  key = "fixture-asset"
  bad = root / "locks/pi/vendor" / (Path(document["sources"][key]["vendor_path"]).name)
  bad.write_bytes(b"stale content")
  with pytest.raises(ConfigError, match="exists-unverified"):
    fetch_pi_assets.main(["--repository", str(root)])
  monkeypatch.setattr(fetch_pi_assets, "urlopen", fake_urlopen(content))
  assert fetch_pi_assets.main(["--repository", str(root), "--force"]) == 0
  assert bad.read_bytes() == content


def test_fixed_url_rejects_credentials_and_non_https():
  with pytest.raises(ConfigError):
    fetch_pi_assets.validate_fixed_url("https://user:secret@example.com/a.tgz")
  with pytest.raises(ConfigError):
    fetch_pi_assets.validate_fixed_url("https://example.com/a.tgz?sig=secret")
  with pytest.raises(ConfigError):
    fetch_pi_assets.validate_fixed_url("http://example.com/a.tgz")

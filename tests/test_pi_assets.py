"""原生资产测试只使用合成文件头和内存下载，不启动任何宿主。"""

import hashlib
import io
import json
import tarfile

import pytest

from agentcfg import pi_assets
from agentcfg.pi_dependencies import PiBackend
from agentcfg.process import DependencyError
from agentcfg.storage import ensure_private
from test_pi_dependencies import fixture_repository, digest, payload


def executable(platform="linux-x86_64"):
  raw = bytearray(64)
  if platform.startswith("linux"):
    raw[:6] = b"\x7fELF\x02\x01"
    raw[16:18] = (2).to_bytes(2, "little")
    raw[18:20] = (62 if platform.endswith("x86_64") else 183).to_bytes(2, "little")
  else:
    raw[:4] = b"\xcf\xfa\xed\xfe"
    raw[4:8] = (0x1000007 if platform.endswith("x86_64") else 0x100000c).to_bytes(4, "little")
    raw[12:16] = (2).to_bytes(4, "little")
  return bytes(raw)


def test_official_codex_closes_linux_bwrap_dependencies_without_inventing_macos_assets():
  from pathlib import Path
  from agentcfg.pi_vendor import read_inputs
  root = Path(__file__).resolve().parents[1]
  _, inputs = read_inputs(root)
  piece = inputs["profiles"]["pi-codex"]
  pi_assets.validate_asset_platforms(piece, inputs)
  selected = [inputs["sources"][name] for name in piece["source_ids"] if name.startswith("codex-bwrap-")]
  assert {row["platform"] for row in selected} == {"linux-x86_64", "linux-arm64"}
  assert {row["target"] for row in selected} == {"bin/codex-resources/bwrap"}
  assert all("rust-v0.154.0/" in row["url"] for row in selected)
  for target in ("bin/codex", "bin/codex-code-mode-host", "bin/codex-responses-api-proxy"):
    platforms = {inputs["sources"][name]["platform"] for name in piece["source_ids"]
      if inputs["sources"][name].get("target") == target}
    assert platforms == set(inputs["platforms"])
  partial = {**piece, "source_ids": [name for name in piece["source_ids"] if name != "codex-bwrap-linux-arm64"]}
  with pytest.raises(ValueError, match="platform-incomplete"): pi_assets.validate_asset_platforms(partial, inputs)
  invalid = {**selected[0], "target": "bin/arbitrary/nested"}
  with pytest.raises(ValueError, match="layout-invalid"): pi_assets.validate_asset(invalid)


def archive_bytes(entries):
  result = io.BytesIO()
  with tarfile.open(fileobj=result, mode="w:gz") as archive:
    for name, data, kind in entries:
      info = tarfile.TarInfo(name)
      info.mode, info.type = 0o755, kind
      if kind in (tarfile.LNKTYPE, tarfile.SYMTYPE):
        info.linkname = "outside"
      info.size = len(data) if kind == tarfile.REGTYPE else 0
      archive.addfile(info, io.BytesIO(data) if info.size else None)
  return result.getvalue()


def fixture(tmp_path, monkeypatch, entries=None):
  root = tmp_path / "checkout"
  root.mkdir()
  license_path = "agents/pi/build/licenses/fixture/LICENSE"
  (root / license_path).parent.mkdir(parents=True)
  (root / license_path).write_text("synthetic license")
  stage = tmp_path / "stage"
  ensure_private(stage)
  raw = archive_bytes(entries or [("codex", executable(), tarfile.REGTYPE)])
  source = {"kind": "asset", "url": "https://example.invalid/codex.tar.gz", "platform": "linux-x86_64",
    "archive_digest": hashlib.sha256(raw).hexdigest(), "archive_member": "codex", "target": "bin/codex", "license_files": [license_path]}
  calls = []
  def download(url):
    calls.append(url)
    return io.BytesIO(raw)
  monkeypatch.setattr(pi_assets, "open_download", download)
  return root, stage, source, calls


def install(root, stage, source, platform="linux-x86_64"):
  pi_assets.install_assets(root, stage, {"source_ids": ["codex"]}, {"sources": {"codex": source}}, platform)


def test_matching_platform_downloads_verified_entry_and_license_only(tmp_path, monkeypatch):
  root, stage, source, calls = fixture(tmp_path, monkeypatch)
  install(root, stage, source, "darwin-arm64")
  assert calls == [] and list(stage.iterdir()) == []
  install(root, stage, source)
  assert calls == [source["url"]]
  assert (stage / "bin/codex").read_bytes() == executable()
  assert (stage / "bin/codex").stat().st_mode & 0o777 == 0o700
  assert (stage / "licenses/codex/0-LICENSE").read_text() == "synthetic license"


@pytest.mark.parametrize("kind", ["digest", "platform", "missing", "duplicate", "traversal", "symlink", "hardlink", "limit"])
def test_invalid_asset_never_installs_executable(tmp_path, monkeypatch, kind):
  entries = [("codex", executable(), tarfile.REGTYPE)]
  if kind == "platform":
    entries[0] = ("codex", executable("darwin-arm64"), tarfile.REGTYPE)
  elif kind == "missing":
    entries[0] = ("other", executable(), tarfile.REGTYPE)
  elif kind == "duplicate":
    entries *= 2
  elif kind == "traversal":
    entries.append(("../escape", b"bad", tarfile.REGTYPE))
  elif kind in ("symlink", "hardlink"):
    entries.append(("link", b"", tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE))
  root, stage, source, calls = fixture(tmp_path, monkeypatch, entries)
  if kind == "digest":
    source["archive_digest"] = "0" * 64
  if kind == "limit":
    monkeypatch.setattr(pi_assets, "MAX_ARCHIVE", 1)
  with pytest.raises(DependencyError):
    install(root, stage, source)
  assert not (stage / "bin/codex").exists()


@pytest.mark.parametrize("platform", ["linux-x86_64", "linux-arm64", "darwin-x86_64", "darwin-arm64"])
def test_binary_header_platform_is_checked_without_execution(platform):
  assert pi_assets.binary_platform(executable(platform)) == platform


def test_remote_assets_do_not_require_download_for_offline_lock_validation(tmp_path, monkeypatch):
  root, manifest = fixture_repository(tmp_path)
  _, _, source, calls = fixture(tmp_path, monkeypatch)
  manifest["sources"]["codex"] = source
  manifest["platforms"] = ["linux-x86_64"]
  piece = manifest["profile_slices"]["pi-fixture"]
  piece["source_ids"].append("codex")
  piece["identity"] = digest({k: v for k, v in piece.items() if k != "identity"})
  manifest["identity"] = digest({k: v for k, v in manifest.items() if k != "identity"})
  (root / "locks/pi/manifest.json").write_bytes(payload(manifest))
  assert PiBackend().read_lock(root).identity == manifest["identity"]
  assert calls == []


def test_download_failure_does_not_expose_signed_url(tmp_path, monkeypatch):
  root, stage, source, calls = fixture(tmp_path, monkeypatch)
  def fail(url):
    raise OSError("sensitive-signed-query")
  monkeypatch.setattr(pi_assets, "open_download", fail)
  with pytest.raises(DependencyError) as error:
    install(root, stage, source)
  assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("format", ["tar.gz", "raw"])
@pytest.mark.parametrize("fault", [None, "missing", "digest"])
def test_modern_vendor_assets_never_read_or_fall_back_to_legacy(tmp_path, monkeypatch, format, fault):
  root, stage, source, calls = fixture(tmp_path, monkeypatch)
  source["vendor_path"] = "vendor/fixture.bin" if format == "raw" else "vendor/fixture.tgz"
  if format == "raw":
    raw = b"synthetic-modern-data"
    source.update(format="raw", platform="all", size=len(raw), target="data/fixture.bin")
    source.pop("archive_member")
  else:
    raw = archive_bytes([("codex", executable() + b"modern", tarfile.REGTYPE)])
  source["archive_digest"] = hashlib.sha256(raw).hexdigest()
  # 旧目录有完全匹配的诱饵；modern缺失或坏摘要也不得补齐。
  legacy = root / "locks/pi" / source["vendor_path"]
  legacy.parent.mkdir(parents=True); legacy.write_bytes(raw)
  modern = root / "locks/pi-modern" / source["vendor_path"]
  if fault != "missing":
    modern.parent.mkdir(parents=True); modern.write_bytes(b"bad digest" if fault == "digest" else raw)
  reads = []
  from agentcfg.storage import Tree
  original_read, original_open = Tree.read, Tree.open_read
  def read(tree, path, **options):
    reads.append(str(path)); return original_read(tree, path, **options)
  def open_read(tree, path, **options):
    reads.append(str(path)); return original_open(tree, path, **options)
  monkeypatch.setattr(Tree, "read", read); monkeypatch.setattr(Tree, "open_read", open_read)
  def run():
    pi_assets.install_assets(root, stage, {"source_ids": ["fixture"]}, {"sources": {"fixture": source}}, "linux-x86_64", lock_family="modern")
  if fault:
    with pytest.raises(DependencyError): run()
    assert not (stage / source["target"]).exists()
  else:
    run()
    assert (stage / source["target"]).read_bytes() == (raw if format == "raw" else executable() + b"modern")
  assert calls == []
  vendor_reads = [path for path in reads if path.startswith("locks/")]
  assert vendor_reads and set(vendor_reads) == {"locks/pi-modern/" + source["vendor_path"]}


def test_default_vendor_asset_remains_in_legacy_family(tmp_path, monkeypatch):
  root, stage, source, calls = fixture(tmp_path, monkeypatch)
  raw = archive_bytes([("codex", executable(), tarfile.REGTYPE)])
  source.update(vendor_path="vendor/fixture.tgz", archive_digest=hashlib.sha256(raw).hexdigest())
  legacy = root / "locks/pi/vendor/fixture.tgz"; legacy.parent.mkdir(parents=True); legacy.write_bytes(raw)
  modern = root / "locks/pi-modern/vendor/fixture.tgz"; modern.parent.mkdir(parents=True); modern.write_bytes(b"poison")
  install(root, stage, source)
  assert (stage / "bin/codex").read_bytes() == executable() and calls == []


def test_invalid_asset_family_is_rejected_before_tree_or_download(tmp_path, monkeypatch):
  from agentcfg.schema import ConfigError
  from agentcfg.storage import Tree
  monkeypatch.setattr(Tree, "__init__", lambda *_args, **_kwargs: pytest.fail("filesystem touched before family validation"))
  monkeypatch.setattr(pi_assets, "open_download", lambda *_args: pytest.fail("download before family validation"))
  with pytest.raises(ConfigError) as error:
    pi_assets.install_assets(tmp_path / "missing", tmp_path / "stage", {"source_ids": []}, {"sources": {}}, "linux-x86_64", lock_family="../synthetic-private")
  assert error.value.code == "pi-lock-layout" and "synthetic-private" not in str(error.value)

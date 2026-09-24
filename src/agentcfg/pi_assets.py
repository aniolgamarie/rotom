"""固定原生发行物：只在显式 sync 下载，不执行宿主，不使用归档路径写文件。"""

import hashlib
import os
import tarfile
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .paths import relative_path
from .process import DependencyError
from .storage import Tree


MAX_ARCHIVE = 128 * 1024 * 1024
MAX_BINARY = 512 * 1024 * 1024


def validate_asset(source):
  url = urlsplit(source["url"])
  if (url.scheme != "https" or not url.hostname or url.username is not None
      or url.password is not None or url.query or url.fragment or url.port not in (None, 443)):
    raise ValueError("pi-asset-url-invalid")
  data = source.get("format") == "raw"
  if data:
    if source["platform"] != "all" or type(source.get("size")) is not int or not 1 <= source["size"] <= 4 * 1024**3 or "archive_member" in source:
      raise ValueError("pi-data-asset-invalid")
  elif source.get("format", "tar.gz") != "tar.gz": raise ValueError("pi-asset-format-invalid")
  for name in ([source["archive_member"]] if not data else []) + [source["target"], *source["license_files"]]:
    relative_path(name)
  if ((not source["target"].startswith("data/") if data else not source["target"].startswith("bin/")
        or len(Path(source["target"]).parts) != 2 and source["target"] != "bin/codex-resources/bwrap")
      or not source["license_files"] or any(not name.startswith("agents/pi/build/licenses/") for name in source["license_files"])):
    raise ValueError("pi-asset-layout-invalid")


def validate_asset_platforms(piece, manifest):
  from .pi_readseek_vision import validate_closure
  validate_closure(piece["source_ids"])
  targets = {}
  for key in piece["source_ids"]:
    source = manifest["sources"][key]
    if source["kind"] != "asset":
      continue
    platforms = targets.setdefault(source["target"], set())
    if source["platform"] in platforms:
      raise ValueError("pi-asset-platform-collision")
    platforms.add(source["platform"])
  expected = set(manifest["platforms"])
  for target, platforms in targets.items():
    allowed = ({platform for platform in expected if platform.startswith("linux-")},) if target == "bin/codex-resources/bwrap" else (expected, {"all"})
    if platforms not in allowed: raise ValueError("pi-asset-platform-incomplete")


class HTTPSRedirects(HTTPRedirectHandler):
  def redirect_request(self, req, fp, code, msg, headers, newurl):
    url = urlsplit(newurl)
    if url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None:
      raise DependencyError("Pi发行物下载重定向无效")
    return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_download(url):
  return build_opener(HTTPSRedirects()).open(Request(url, headers={"User-Agent": "agentcfg"}), timeout=60)


def binary_platform(raw):
  # 校验文件头而不运行发行物；拒绝脚本、胖二进制或错误体系结构。
  if len(raw) >= 64 and raw[:6] == b"\x7fELF\x02\x01":
    architecture = {62: "x86_64", 183: "arm64"}.get(int.from_bytes(raw[18:20], "little"))
    if architecture and int.from_bytes(raw[16:18], "little") in (2, 3):
      return "linux-" + architecture
  if len(raw) >= 32 and raw[:4] == b"\xcf\xfa\xed\xfe":
    architecture = {0x1000007: "x86_64", 0x100000c: "arm64"}.get(int.from_bytes(raw[4:8], "little"))
    if architecture and int.from_bytes(raw[12:16], "little") == 2:
      return "darwin-" + architecture
  raise DependencyError("Pi发行物不是声明平台的原生可执行文件")


def extract_binary(stream, source):
  result = None
  seen, total = set(), 0
  with tarfile.open(fileobj=stream, mode="r:gz") as archive:
    for member in archive:
      relative_path(member.name)
      if member.name in seen or not (member.isfile() or member.isdir()) or member.issparse():
        raise DependencyError("Pi发行物包含重复或不支持的归档条目")
      seen.add(member.name)
      total += member.size
      if len(seen) > 1024 or total > MAX_BINARY:
        raise DependencyError("Pi发行物解压内容超过限制")
      if member.name == source["archive_member"]:
        if not member.isfile() or member.size <= 0 or not member.mode & 0o111:
          raise DependencyError("Pi发行物缺少可执行入口")
        with archive.extractfile(member) as entry:
          result = entry.read(MAX_BINARY + 1)
        if len(result) != member.size:
          raise DependencyError("Pi发行物入口不完整")
  if result is None or binary_platform(result) != source["platform"]:
    raise DependencyError("Pi发行物平台或入口不匹配")
  return result


def install_assets(repository, stage, piece, manifest, platform):
  selected = [(key, manifest["sources"][key]) for key in piece["source_ids"]
    if manifest["sources"][key]["kind"] == "asset" and manifest["sources"][key]["platform"] in (platform, "all")]
  if len({source["target"] for _, source in selected}) != len(selected):
    raise DependencyError("Pi发行物入口冲突")
  with Tree(repository, private=False) as checkout, Tree(stage) as target:
    for key, source in selected:
      try:
        validate_asset(source)
        licenses = {}
        for index, name in enumerate(source["license_files"]):
          raw = checkout.read(name, max_bytes=1024 * 1024)
          if raw is None:
            raise DependencyError("Pi发行物许可证缺失")
          licenses[f"licenses/{key}/{index}-{Path(name).name}"] = raw[0]
        if source.get("format") == "raw":
          if "vendor_path" in source:
            with checkout.open_read("locks/pi/" + source["vendor_path"], max_bytes=source["size"]) as (stream, _):
              install_data(target, stream, source)
          else:
            with open_download(source["url"]) as stream: install_data(target, stream, source)
          for name, data in licenses.items(): target.write_new(name, data)
          continue
        with tempfile.TemporaryFile(dir=stage) as archive:
          checksum, size = hashlib.sha256(), 0
          if "vendor_path" in source:
            raw = checkout.read("locks/pi/" + source["vendor_path"], max_bytes=MAX_ARCHIVE)
            if raw is None:
              raise DependencyError("Pi发行物归档缺失")
            archive.write(raw[0])
            checksum.update(raw[0])
          else:
            with open_download(source["url"]) as response:
              while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE:
                  raise DependencyError("Pi发行物下载超过限制")
                archive.write(chunk)
                checksum.update(chunk)
          if checksum.hexdigest() != source["archive_digest"]:
            raise DependencyError("Pi发行物归档摘要不匹配")
          archive.seek(0)
          binary = extract_binary(archive, source)
        if target.read(source["target"]) is not None:
          raise DependencyError("Pi发行物入口已经存在")
        target.replace(source["target"], binary, mode=0o700, expected=None)
        for name, data in licenses.items():
          target.write_new(name, data)
      except DependencyError:
        raise
      except Exception:
        # URL/网络错误可能带签名参数，固定错误不泄露下载地址的临时秘密。
        raise DependencyError("Pi发行物下载或校验失败") from None


def install_data(target, stream, source):
  """按固定大小与摘要流式校验，以单链接原子发布；失败不留下可用的半份模型。"""
  with target.parent(source["target"], create=True) as (parent, name):
    temporary = ".asset-" + uuid.uuid4().hex
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
      with os.fdopen(fd, "wb") as output:
        checksum, size = hashlib.sha256(), 0
        while chunk := stream.read(min(1024 * 1024, source["size"] - size + 1)):
          size += len(chunk)
          if size > source["size"]: raise DependencyError("Pi数据资产下载超过声明大小")
          checksum.update(chunk); output.write(chunk)
        if size != source["size"] or checksum.hexdigest() != source["archive_digest"]:
          raise DependencyError("Pi数据资产大小或摘要不匹配")
        output.flush(); os.fsync(output.fileno())
      # link 对已存在目标原子失败，不以 stat+replace 覆盖另一次同步的产物。
      os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
      os.unlink(temporary, dir_fd=parent); temporary = None
      os.fsync(parent)
    finally:
      if temporary is not None: os.unlink(temporary, dir_fd=parent)

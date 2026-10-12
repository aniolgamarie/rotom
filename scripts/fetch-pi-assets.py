#!/usr/bin/env python3
"""按锁固定来源重建 locks/pi/vendor 资产：下载→大小/摘要校验→原子发布。

vendor 资产不进入版本库；任何机器取得仓库后可用本脚本从 dependencies.json
固定的 URL 重建完整输入。只接受摘要校验一致的内容；传输失败不留半份可用文件。
也可以由制品镜像/离线拷贝先把文件放到 locks/pi/<vendor_path>，本脚本同样只做校验。
现代自建资产必须预先显式构建并导入；这里只校验来源记录、固定输入和归档，不运行构建器。
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentcfg.schema import ConfigError
from agentcfg.pi_lock_layout import dependency_layout


def load_asset_sources(repository, *, profile=None):
  layout = dependency_layout(profile=profile)
  try:
    document = json.loads((repository / layout.dependencies_path).read_text())
    if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
        or document["schema_version"] != layout.schema_version or not isinstance(document.get("sources"), dict)
        or any(not isinstance(row, dict) for row in document["sources"].values())):
      raise ValueError()
  except (OSError, ValueError, UnicodeError):
    raise ConfigError("pi-asset-input-missing-or-invalid") from None
  selected = None
  if profile is not None:
    try:
      if type(document["schema_version"]) is not int or document["schema_version"] != layout.schema_version: raise ValueError()
      selected = set(document["profiles"][profile]["source_ids"])
      if selected - document["sources"].keys(): raise ValueError()
    except (KeyError, TypeError, ValueError):
      raise ConfigError("pi-asset-profile") from None
  sources = []
  for key, source in sorted(document["sources"].items()):
    if selected is not None and key not in selected: continue
    if source.get("kind") == "asset" and "vendor_path" in source:
      sources.append((key, source))
  return sources


def validate_fixed_url(url):
  from urllib.parse import urlsplit
  parsed = urlsplit(url)
  if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
      or parsed.password is not None or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
    raise ConfigError("pi-asset-url-invalid")


def verify_asset(key, source, raw):
  digest = hashlib.sha256(raw).hexdigest()
  if digest != source["archive_digest"]:
    raise ConfigError("pi-asset-digest-mismatch:" + key)
  if source.get("format") == "raw" and len(raw) != source["size"]:
    raise ConfigError("pi-asset-size-mismatch:" + key)


def fetch(url, source, *, attempts=8, timeout=300):
  # 固定发行物URL不含凭据；重试与续传只面向公开内容，不带签名参数进日志。
  validate_fixed_url(url)
  temporary = tempfile.NamedTemporaryFile(prefix="agentcfg-asset-", delete=False)
  temporary.close()
  try:
    for attempt in range(attempts):
      try:
        offset = os.path.getsize(temporary.name)
        headers = {"User-Agent": "agentcfg"}
        if offset: headers["Range"] = "bytes=" + str(offset) + "-"
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
          if offset and response.status != 206:
            os.truncate(temporary.name, 0)
          if not offset and response.status not in (200, 206):
            raise ConfigError("pi-asset-fetch-status")
          with open(temporary.name, "ab") as output:
            shutil.copyfileobj(response, output, 1024 * 1024)
        # 截断或损坏的传输常常不报错；每轮完整校验，失败整体重下（续传仅用于连接中断）。
        try: verify_asset("fetch", source, Path(temporary.name).read_bytes())
        except ConfigError:
          if attempt == attempts - 1: raise
          os.truncate(temporary.name, 0)
          continue
        return Path(temporary.name)
      except Exception:
        if attempt == attempts - 1: raise
        time.sleep(min(2 ** attempt, 20))
  except Exception:
    os.unlink(temporary.name)
    raise


def main(argv=None):
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--repository", type=Path, default=ROOT)
  parser.add_argument("--profile", help="只重建所选配方资产；现代配方使用独立锁目录")
  parser.add_argument("--only", action="append", help="只处理指定资产标识，可重复")
  parser.add_argument("--force", action="store_true", help="重下已存在但摘要不匹配的文件（先删除旧文件）")
  args = parser.parse_args(argv)
  repository = args.repository.resolve(strict=True)
  layout = dependency_layout(profile=args.profile)
  sources = load_asset_sources(repository, profile=args.profile)
  vendor = repository / layout.lock_directory / "vendor"
  for key, source in sources:
    if args.only and key not in args.only: continue
    if "build_record" in source:
      from agentcfg.pi_assets import validate_asset
      from agentcfg.pi_built_assets import MAX_ARCHIVE, load_record, verify_archive
      from agentcfg.storage import Tree
      validate_asset(source)
      record = load_record(repository, layout, source)
      with Tree(repository, private=False) as checkout:
        raw = checkout.read(layout.lock_directory + "/" + source["vendor_path"], max_bytes=MAX_ARCHIVE)
      if raw is None: raise ConfigError("pi-built-asset-import-required")
      verify_archive(raw[0], source, record)
      print(key, "built-verified", flush=True)
      continue
    vendor.mkdir(parents=True, exist_ok=True)
    target = vendor / Path(source["vendor_path"]).name
    if target.exists():
      raw = target.read_bytes()
      try: verify_asset(key, source, raw)
      except ConfigError:
        if not args.force: raise ConfigError("pi-asset-exists-unverified:" + key + "（使用--force重下或人工核对）")
        target.unlink()
      else:
        print(key, "verified", flush=True); continue
    print(key, "fetching", flush=True)
    temporary = fetch(source["url"], source)
    try:
      raw = temporary.read_bytes()
      verify_asset(key, source, raw)
      published = vendor / (".partial-" + target.name)
      shutil.move(str(temporary), published)
      os.chmod(published, 0o600)
      os.replace(published, target)
      print(key, "published", flush=True)
    except BaseException:
      if temporary.exists(): temporary.unlink()
      raise
  return 0


if __name__ == "__main__":
  try: sys.exit(main())
  except ConfigError as error:
    sys.stderr.write(str(error) + "\n"); sys.exit(2)

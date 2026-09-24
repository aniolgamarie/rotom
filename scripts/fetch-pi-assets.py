#!/usr/bin/env python3
"""按锁固定来源重建 locks/pi/vendor 资产：下载→大小/摘要校验→原子发布。

vendor 资产不进入版本库；任何机器取得仓库后可用本脚本从 dependencies.json
固定的 URL 重建完整输入。只接受摘要校验一致的内容；传输失败不留半份可用文件。
也可以由制品镜像/离线拷贝先把文件放到 locks/pi/<vendor_path>，本脚本同样只做校验。
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


def load_asset_sources(repository):
  document = json.loads((repository / "agents/pi/dependencies.json").read_text())
  sources = []
  for key, source in sorted(document["sources"].items()):
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
  parser.add_argument("--only", action="append", help="只处理指定资产标识，可重复")
  parser.add_argument("--force", action="store_true", help="重下已存在但摘要不匹配的文件（先删除旧文件）")
  args = parser.parse_args(argv)
  repository = args.repository.resolve(strict=True)
  vendor = repository / "locks/pi/vendor"
  vendor.mkdir(parents=True, exist_ok=True)
  missing = []
  for key, source in load_asset_sources(repository):
    if args.only and key not in args.only: continue
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

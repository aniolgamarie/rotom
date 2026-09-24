"""ReadSeek 原生实现要求的固定本地视觉资产；运行时只绑定只读缓存，不发下载请求。"""
import hashlib
from pathlib import Path

from .deployment import json_bytes
from .process import DependencyError
from .storage import Tree, ensure_private


REVISION = "52d6c8ffea26cc873ac5ad116f8631268d7eb503"
REPOSITORY = "models--Qwen--Qwen3-VL-2B-Instruct-GGUF"
HUB = "data/readseek/hub"
FILES = {
  "Qwen3VL-2B-Instruct-Q4_K_M.gguf": {"size": 1107409952, "sha256": "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae"},
  "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf": {"size": 445053216, "sha256": "f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82"},
}
SOURCE_IDS = {"readseek-vision-model", "readseek-vision-projector"}


def validate_closure(source_ids):
  sources = set(source_ids)
  selected = SOURCE_IDS & sources
  if ("pi-readseek" in sources or selected) and selected != SOURCE_IDS:
    raise ValueError("pi-readseek-vision-closure")


def target(name):
  if name not in FILES: raise DependencyError("ReadSeek视觉资产名称未知")
  return HUB + "/" + REPOSITORY + "/snapshots/" + REVISION + "/" + name


def install_vision(stage, piece):
  try: validate_closure(piece.get("source_ids", []))
  except ValueError: raise DependencyError("ReadSeek视觉资产闭包不完整") from None
  selected = SOURCE_IDS & set(piece.get("source_ids", []))
  if not selected: return
  if selected != SOURCE_IDS: raise DependencyError("ReadSeek视觉资产闭包不完整")
  receipt = {"schema_version": 1, "revision": REVISION, "hub": HUB, "files": {}, "model_execution": "not-run"}
  with Tree(stage) as tree:
    for name, expected in FILES.items():
      try:
        with tree.open_read(target(name), max_bytes=expected["size"]) as (stream, opened):
          if opened.st_size != expected["size"]: raise DependencyError("ReadSeek视觉文件大小不匹配")
          header = stream.read(8)
          if header != b"GGUF\x03\0\0\0": raise DependencyError("ReadSeek视觉文件不是已选GGUF格式")
          checksum, size = hashlib.sha256(header), len(header)
          while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > expected["size"]: raise DependencyError("ReadSeek视觉文件读取时大小变化")
            checksum.update(chunk)
          if size != expected["size"]: raise DependencyError("ReadSeek视觉文件读取时大小变化")
          if checksum.hexdigest() != expected["sha256"]: raise DependencyError("ReadSeek视觉文件摘要不匹配")
      except FileNotFoundError: raise DependencyError("ReadSeek视觉资产未安装；运行时不会下载") from None
      receipt["files"][name] = {**expected, "path": target(name)}
    # 原生实现先检查这两个目录；预建目录使只读运行包无需写模型缓存。
    ensure_private(Path(stage) / HUB / REPOSITORY / "blobs")
    tree.write_new("runtime/readseek-vision.json", json_bytes(receipt))

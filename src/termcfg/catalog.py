"""只接受仓库内逐文件声明的公开来源。"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator

from .errors import TermcfgError


REPO_ROOT = Path(__file__).resolve().parents[2]


def _relative_path(raw: str) -> Path:
  if not isinstance(raw, str) or not raw or "\\" in raw:
    raise TermcfgError(2, "invalid_catalog_path")
  path = PurePosixPath(raw)
  if path.is_absolute() or any(part in {"", ".", ".."} for part in raw.split("/")):
    raise TermcfgError(2, "invalid_catalog_path")
  return Path(*path.parts)


@dataclass(frozen=True)
class SourceArtifact:
  id: str
  component: str
  source: Path
  destination: Path
  sha256: str
  mode: int

  def bytes(self) -> bytes:
    if self.source.is_symlink() or not self.source.is_file() or not self.source.resolve().is_relative_to(REPO_ROOT):
      raise TermcfgError(2, "unsafe_source")
    data = self.source.read_bytes()
    if hashlib.sha256(data).hexdigest() != self.sha256:
      raise TermcfgError(5, "source_digest_mismatch")
    return data


@dataclass(frozen=True)
class Component:
  id: str
  sources: tuple[SourceArtifact, ...]
  required_program: str | None
  optional_programs: tuple[str, ...] = ()


@dataclass(frozen=True)
class LockedAsset:
  component: str
  identity: str
  platform: str
  url: str
  size: int
  sha256: str
  archive: str
  entry: str
  resources: tuple[str, ...]


def components(catalog: tuple[SourceArtifact, ...] | None = None) -> tuple[Component, ...]:
  catalog = catalog or load_catalog()
  return (
    Component("zsh", tuple(item for item in catalog if item.component == "zsh"), "zsh"),
    Component("tmux", tuple(item for item in catalog if item.component == "tmux"), "tmux", ("fzf",)),
    Component("mihomo", tuple(item for item in catalog if item.component == "mihomo"), None),
  )


def load_catalog(path: Path | None = None) -> tuple[SourceArtifact, ...]:
  path = path or REPO_ROOT / "terminals/catalog.json"
  try:
    data = json.loads(path.read_text())
    schema = json.loads((REPO_ROOT / "schemas/termcfg/catalog.schema.json").read_text())
    Draft202012Validator(schema).validate(data)
  except (OSError, ValueError, Exception) as exc:
    # jsonschema 使用多种异常类型；不把原始输入写入诊断。
    raise TermcfgError(2, "invalid_catalog") from exc
  ids: set[str] = set()
  destinations: set[Path] = set()
  artifacts: list[SourceArtifact] = []
  for item in data["targets"]:
    source = REPO_ROOT / _relative_path(item["source"])
    destination = _relative_path(item["destination"])
    if item["id"] in ids or destination in destinations or any(destination in old.parents or old in destination.parents for old in destinations):
      raise TermcfgError(2, "catalog_overlap")
    ids.add(item["id"])
    destinations.add(destination)
    artifact = SourceArtifact(item["id"], item["component"], source, destination, item["sha256"], int(item["mode"], 8))
    artifact.bytes()
    artifacts.append(artifact)
  return tuple(artifacts)

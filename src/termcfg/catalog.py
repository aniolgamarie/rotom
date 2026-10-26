"""只接受仓库内逐文件声明的公开来源。"""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator

from .errors import TermcfgError


REPO_ROOT = Path(__file__).resolve().parents[2]


def _strict_pairs(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      raise ValueError("duplicate field")
    result[key] = value
  return result


def _invalid_constant(value):
  raise ValueError("unsupported number")


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
class GeneratedArtifact:
  id: str
  component: str
  destination: Path
  sha256: str
  mode: int
  payload: bytes = field(repr=False)
  source_inputs_digest: str
  write_before: dict = field(repr=False)
  generator_version: int = 1
  kind: str = "rotom-entry-binding"
  previous_repository: str | None = None

  def bytes(self) -> bytes:
    return self.payload

  def verify_source(self) -> None:
    from rotom.entry import parse_binding
    parse_binding(self.payload)


@dataclass(frozen=True)
class GeneratedTemplate:
  id: str
  component: str
  destination: Path
  mode: int
  generator_version: int
  kind: str = "rotom-entry-binding"

  def materialize(self, machine, entry_repo=None) -> GeneratedArtifact:
    from rotom import entry
    from .home_targets import inspect_target, read_regular
    before = inspect_target(machine.target_home, self.destination)
    directory = machine.target_home / self.destination.parent
    if directory.exists() or directory.is_symlink():
      fd = entry._call(entry.entry_locator._directory, directory, private=True)
      import os
      os.close(fd)
    if before.kind not in ("file", "absent"):
      raise TermcfgError(4, "unsafe_entry_binding_target")
    if before.kind == "file":
      if before.mode != 0o600:
        raise TermcfgError(4, "unsafe_entry_binding_target")
      previous = read_regular(machine.target_home, self.destination, before)
      # 换绑只检查旧内容的固定结构，不需要执行或重新打开旧 checkout。
      old_binding = entry.parse_binding(previous, check_source=entry_repo is None)
    else:
      previous = None
    payload = previous if previous is not None and entry_repo is None else entry.serialize_binding(
      entry.create_binding(Path(entry_repo) if entry_repo is not None else entry.REPO_ROOT))
    digest = hashlib.sha256(payload).hexdigest()
    return GeneratedArtifact(self.id, self.component, self.destination, digest, self.mode,
      payload, digest, before.as_dict(), self.generator_version,
      previous_repository=old_binding["repository"] if previous is not None else None)


@dataclass(frozen=True)
class Component:
  id: str
  sources: tuple[SourceArtifact, ...]
  required_program: str | None
  optional_programs: tuple[str, ...] = ()


def components(catalog: tuple[SourceArtifact, ...] | None = None) -> tuple[Component, ...]:
  catalog = catalog or load_catalog()
  return (
    Component("zsh", tuple(item for item in catalog if item.component == "zsh"), "zsh"),
    Component("tmux", tuple(item for item in catalog if item.component == "tmux"), "tmux", ("fzf",)),
    Component("herdr", tuple(item for item in catalog if item.component == "herdr"), "herdr"),
  )


def load_catalog(path: Path | None = None) -> tuple[SourceArtifact | GeneratedTemplate, ...]:
  path = path or REPO_ROOT / "terminals/catalog.json"
  try:
    data = json.loads(path.read_text(), object_pairs_hook=_strict_pairs, parse_constant=_invalid_constant)
    schema = json.loads((REPO_ROOT / "schemas/termcfg/catalog.schema.json").read_text())
    Draft202012Validator(schema).validate(data)
    if type(data["version"]) is not int or data["version"] not in (1, 2):
      raise ValueError("invalid version")
    if data["version"] == 1 and any(item.get("kind", "static") != "static" for item in data["targets"]):
      raise ValueError("generated declaration requires v2")
  except (OSError, ValueError, Exception) as exc:
    # jsonschema 使用多种异常类型；不把原始输入写入诊断。
    raise TermcfgError(2, "invalid_catalog") from exc
  ids: set[str] = set()
  destinations: set[Path] = set()
  artifacts: list[SourceArtifact] = []
  for item in data["targets"]:
    destination = _relative_path(item["destination"])
    if item["id"] in ids or destination in destinations or any(destination in old.parents or old in destination.parents for old in destinations):
      raise TermcfgError(2, "catalog_overlap")
    ids.add(item["id"])
    destinations.add(destination)
    if item.get("kind") == "rotom-entry-binding":
      if type(item["generator_version"]) is not int:
        raise TermcfgError(2, "invalid_catalog")
      artifact = GeneratedTemplate(item["id"], item["component"], destination,
        int(item["mode"], 8), item["generator_version"])
    else:
      source = REPO_ROOT / _relative_path(item["source"])
      artifact = SourceArtifact(item["id"], item["component"], source, destination, item["sha256"], int(item["mode"], 8))
      artifact.bytes()
    artifacts.append(artifact)
  return tuple(artifacts)

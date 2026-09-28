"""官方固定资产的显式锁定和私人版本化安装。"""

import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import tarfile
import time
import urllib.request
import uuid

from .catalog import REPO_ROOT
from .config import MachineSelection, require_current_machine, xdg_path
from .diagnostics import Progress, heartbeat
from .errors import TermcfgError
from .lease import operation_lease, repository_lease
from .state import atomic_bytes, private_dir, read_state, require_no_pending_recovery, state_file, write_json


ASSET_NAME = "mihomo-linux-amd64-compatible-{version}.gz"
OFFICIAL_API = "https://api.github.com/repos/MetaCubeX/mihomo/releases/tags/"
MAX_ARCHIVE = 150 * 1024 * 1024
MAX_BINARY = 200 * 1024 * 1024


def _unpack_single_gzip(data: bytes) -> bytes:
  try:
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
      binary = stream.read(MAX_BINARY + 1)
      if stream.read(1) or not binary or len(binary) > MAX_BINARY:
        raise TermcfgError(5, "asset_unpack_failed")
      return binary
  except OSError as exc:
    raise TermcfgError(5, "asset_unpack_failed") from exc


def current_platform() -> str:
  system = platform.system().lower()
  machine = platform.machine().lower()
  return f"{system}-{'x86_64' if machine in {'amd64', 'x86_64'} else machine}"


def lock_path(component: str) -> Path:
  return REPO_ROOT / "locks/termcfg" / ("mihomo.json" if component == "mihomo" else "plugins.json")


def _read_lock_raw(component: str) -> tuple[dict, str]:
  path = lock_path(component)
  try:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
      raise TermcfgError(2, "invalid_asset_lock")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    try:
      checked = os.fstat(fd)
      if (checked.st_dev, checked.st_ino) != (info.st_dev, info.st_ino):
        raise TermcfgError(4, "lock_file_changed")
      with os.fdopen(fd, "rb", closefd=False) as stream:
        data = stream.read()
    finally:
      os.close(fd)
    value = json.loads(data)
  except (OSError, ValueError) as exc:
    raise TermcfgError(2, "invalid_asset_lock") from exc
  if set(value) != {"version", "component", "assets"} or value["version"] != 1 or not isinstance(value["assets"], dict):
    raise TermcfgError(2, "invalid_asset_lock")
  if component == "mihomo":
    if value["component"] != "mihomo":
      raise TermcfgError(2, "invalid_asset_lock")
    for key, asset in value["assets"].items():
      _validate_asset(key, asset)
  else:
    if value["component"] != "plugins" or set(value["assets"]) != {"zsh", "tmux"} or any(not isinstance(v, list) for v in value["assets"].values()):
      raise TermcfgError(2, "invalid_asset_lock")
    for key in ("zsh", "tmux"):
      seen = set()
      for asset in value["assets"][key]:
        _validate_plugin_asset(asset)
        if asset["id"] in seen:
          raise TermcfgError(2, "duplicate_plugin_asset")
        seen.add(asset["id"])
  return value, hashlib.sha256(data).hexdigest()


def _safe_member_path(raw: str) -> Path:
  if not isinstance(raw, str) or not raw or "\\" in raw or raw.startswith("/") or any(part in {"", ".", ".."} for part in raw.split("/")):
    raise TermcfgError(2, "invalid_plugin_path")
  return Path(*PurePosixPath(raw).parts)


def _validate_plugin_asset(asset: dict) -> None:
  fields = {"id", "repo", "commit", "platform", "url", "size", "sha256", "archive", "entry", "resources"}
  if not isinstance(asset, dict) or set(asset) != fields:
    raise TermcfgError(2, "invalid_plugin_lock")
  identifier = asset["id"]
  repo = asset["repo"]
  commit = asset["commit"]
  if (not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", identifier) or
      not isinstance(repo, str) or not repo.startswith(("tmux-plugins/", "zdharma-continuum/")) or
      repo.split("/")[-1] != identifier or not isinstance(commit, str) or len(commit) != 40 or
      any(c not in "0123456789abcdef" for c in commit) or asset["platform"] != "all" or
      asset["url"] != f"https://codeload.github.com/{repo}/tar.gz/{commit}" or
      not isinstance(asset["size"], int) or not 0 < asset["size"] <= MAX_ARCHIVE or
      not isinstance(asset["sha256"], str) or len(asset["sha256"]) != 64 or
      any(c not in "0123456789abcdef" for c in asset["sha256"]) or
      asset["archive"] != "tar.gz" or not isinstance(asset["resources"], list)):
    raise TermcfgError(2, "invalid_plugin_lock")
  _safe_member_path(asset["entry"])
  paths = set()
  for resource in asset["resources"]:
    if not isinstance(resource, dict) or set(resource) != {"path", "sha256", "mode"}:
      raise TermcfgError(2, "invalid_plugin_lock")
    path = _safe_member_path(resource["path"])
    digest = resource["sha256"]
    if (str(path) in paths or str(path) in {"archive.tar.gz", "receipt.json"} or
        resource["mode"] not in {"0600", "0700"} or not isinstance(digest, str) or
        len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
      raise TermcfgError(2, "invalid_plugin_lock")
    paths.add(str(path))
  if any(left in Path(right).parents for left in map(Path, paths) for right in paths):
    raise TermcfgError(2, "plugin_resource_overlap")
  if asset["entry"] not in paths or not paths:
    raise TermcfgError(2, "plugin_entry_missing")


def _validate_asset(platform_id: str, asset: dict) -> None:
  if not isinstance(asset, dict) or set(asset) != {"version", "platform", "name", "url", "size", "sha256", "archive", "entry", "resources"}:
    raise TermcfgError(2, "invalid_asset_lock")
  version = asset["version"]
  if (not isinstance(version, str) or not version.startswith("v1.") or
      asset["platform"] != platform_id or platform_id != "linux-x86_64" or
      asset["name"] != ASSET_NAME.format(version=version) or
      asset["url"] != f"https://github.com/MetaCubeX/mihomo/releases/download/{version}/{asset['name']}" or
      not isinstance(asset["size"], int) or not 0 < asset["size"] <= MAX_ARCHIVE or
      not isinstance(asset["sha256"], str) or len(asset["sha256"]) != 64 or
      any(c not in "0123456789abcdef" for c in asset["sha256"]) or
      asset["archive"] != "gzip-single" or asset["entry"] != "mihomo" or asset["resources"] != []):
    raise TermcfgError(2, "invalid_asset_lock")


def core_asset() -> tuple[dict, str]:
  value, digest = _read_lock_raw("mihomo")
  asset = value["assets"].get(current_platform())
  if asset is None:
    raise TermcfgError(5, "unsupported_platform", "./termcfg doctor")
  return asset, digest


def _download(url: str, *, expected_size: int | None, timeout: int, progress: Progress, component: str) -> bytes:
  request = urllib.request.Request(url, headers={"User-Agent": "termcfg/0.1"})
  start = time.monotonic()
  result = io.BytesIO()
  progress.stage("download", component=component, item="0 bytes")
  try:
    with heartbeat(progress, "download", component=component), urllib.request.urlopen(request, timeout=min(10, timeout)) as response:
      while True:
        if time.monotonic() - start > timeout:
          raise TermcfgError(5, "download_total_timeout", "./termcfg sync --component " + component)
        chunk = response.read(256 * 1024)
        if not chunk:
          break
        result.write(chunk)
        if result.tell() > MAX_ARCHIVE:
          raise TermcfgError(5, "asset_too_large")
        progress.stage("download", component=component, item=f"{result.tell()} bytes", force=False)
  except (OSError, TimeoutError) as exc:
    raise TermcfgError(5, "download_failed", "./termcfg sync --component " + component) from exc
  data = result.getvalue()
  if expected_size is not None and len(data) != expected_size:
    raise TermcfgError(5, "asset_length_mismatch")
  return data


def _verify_package(directory: Path, asset: dict) -> Path:
  if directory.is_symlink() or not directory.is_dir():
    raise TermcfgError(5, "package_missing")
  info = directory.stat()
  if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
    raise TermcfgError(5, "package_permission_invalid")
  if {path.name for path in directory.iterdir()} != {"archive.gz", "mihomo", "receipt.json"}:
    raise TermcfgError(5, "package_shape_invalid")
  archive, binary, receipt = (directory / name for name in ("archive.gz", "mihomo", "receipt.json"))
  for path, mode in ((archive, 0o600), (binary, 0o700), (receipt, 0o600)):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != mode:
      raise TermcfgError(5, "package_permission_invalid")
  archive_bytes = archive.read_bytes()
  if len(archive_bytes) != asset["size"] or hashlib.sha256(archive_bytes).hexdigest() != asset["sha256"]:
    raise TermcfgError(5, "package_digest_invalid")
  try:
    data = _unpack_single_gzip(archive_bytes)
    metadata = json.loads(receipt.read_text())
  except (OSError, ValueError) as exc:
    raise TermcfgError(5, "package_invalid") from exc
  if len(data) > MAX_BINARY or binary.read_bytes() != data or metadata != {"asset_sha256": asset["sha256"], "binary_sha256": hashlib.sha256(data).hexdigest()}:
    raise TermcfgError(5, "package_binary_invalid")
  return binary


def package_path(machine: MachineSelection, asset: dict) -> Path:
  return xdg_path("XDG_DATA_HOME") / "termcfg" / "packages" / "mihomo" / (asset["version"] + "-" + asset["sha256"][:16])


def installed_core(machine: MachineSelection) -> Path:
  asset, _ = core_asset()
  return _verify_package(package_path(machine, asset), asset)


def _plugin_group_root(component: str) -> Path:
  return xdg_path("XDG_DATA_HOME") / "termcfg" / "packages" / "plugins" / component


def _plugin_members(data: bytes, asset: dict) -> dict[str, bytes]:
  try:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
      files = {}
      for member in archive.getmembers():
        parts = member.name.split("/", 1)
        if len(parts) != 2:
          continue
        relative = parts[1]
        if member.isdir() or member.issym() or member.islnk():
          continue
        if not member.isfile():
          raise TermcfgError(5, "plugin_archive_shape_invalid")
        _safe_member_path(relative)
        if relative in files:
          raise TermcfgError(5, "plugin_archive_duplicate")
        stream = archive.extractfile(member)
        if stream is None:
          raise TermcfgError(5, "plugin_archive_shape_invalid")
        blob = stream.read(MAX_BINARY + 1)
        if len(blob) > MAX_BINARY:
          raise TermcfgError(5, "plugin_resource_too_large")
        files[relative] = blob
  except (OSError, tarfile.TarError) as exc:
    raise TermcfgError(5, "plugin_archive_invalid") from exc
  expected = {resource["path"]: resource for resource in asset["resources"]}
  if set(files) != set(expected):
    raise TermcfgError(5, "plugin_resource_set_mismatch")
  for name, blob in files.items():
    if hashlib.sha256(blob).hexdigest() != expected[name]["sha256"]:
      raise TermcfgError(5, "plugin_resource_digest_mismatch")
  return files


def _write_plugin_group(stage: Path, assets: list[dict], archives: dict[str, bytes]) -> None:
  for asset in assets:
    package = stage / asset["id"]
    package.mkdir(mode=0o700)
    data = archives[asset["id"]]
    members = _plugin_members(data, asset)
    for resource in asset["resources"]:
      relative = _safe_member_path(resource["path"])
      destination = package / relative
      for directory in reversed(list(destination.parents)):
        if directory == package or not directory.is_relative_to(package):
          continue
        if not directory.exists():
          directory.mkdir(mode=0o700)
      atomic_bytes(destination, members[resource["path"]], mode=int(resource["mode"], 8))
    atomic_bytes(package / "archive.tar.gz", data)
    atomic_bytes(package / "receipt.json", json.dumps({"sha256": asset["sha256"], "commit": asset["commit"]}, sort_keys=True).encode())


def _verify_plugin_group(group: Path, assets: list[dict]) -> None:
  info = group.lstat()
  if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
    raise TermcfgError(5, "plugin_package_unsafe")
  if {path.name for path in group.iterdir()} != {asset["id"] for asset in assets}:
    raise TermcfgError(5, "plugin_package_shape_invalid")
  for asset in assets:
    package = group / asset["id"]
    info = package.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
      raise TermcfgError(5, "plugin_package_unsafe")
    archive = package / "archive.tar.gz"
    receipt = package / "receipt.json"
    expected_files = {resource["path"] for resource in asset["resources"]} | {"archive.tar.gz", "receipt.json"}
    found = set()
    for path in package.rglob("*"):
      info = path.lstat()
      if info.st_uid != os.getuid():
        raise TermcfgError(5, "plugin_package_unsafe")
      if stat.S_ISDIR(info.st_mode):
        if stat.S_IMODE(info.st_mode) != 0o700:
          raise TermcfgError(5, "plugin_package_unsafe")
        continue
      if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise TermcfgError(5, "plugin_package_unsafe")
      relative = str(path.relative_to(package))
      if relative not in expected_files:
        raise TermcfgError(5, "plugin_package_shape_invalid")
      found.add(relative)
      mode = 0o600 if relative in {"archive.tar.gz", "receipt.json"} else int(next(resource["mode"] for resource in asset["resources"] if resource["path"] == relative), 8)
      if stat.S_IMODE(info.st_mode) != mode:
        raise TermcfgError(5, "plugin_package_unsafe")
    if found != expected_files:
      raise TermcfgError(5, "plugin_package_shape_invalid")
    data = archive.read_bytes()
    if len(data) != asset["size"] or hashlib.sha256(data).hexdigest() != asset["sha256"]:
      raise TermcfgError(5, "plugin_package_digest_invalid")
    members = _plugin_members(data, asset)
    for path, blob in members.items():
      if (package / path).read_bytes() != blob:
        raise TermcfgError(5, "plugin_package_digest_invalid")
    if json.loads(receipt.read_text()) != {"sha256": asset["sha256"], "commit": asset["commit"]}:
      raise TermcfgError(5, "plugin_package_digest_invalid")


def _sync_plugins(machine: MachineSelection, component: str, assets: list[dict], snapshot: str,
                  *, timeout: int, progress: Progress) -> dict:
  root = _plugin_group_root(component)
  group = root / snapshot[:24]
  if not group.exists():
    archives = {}
    for index, asset in enumerate(assets, 1):
      progress.stage("download", component=component, item=f"{index}/{len(assets)} {asset['id']}")
      data = _download(asset["url"], expected_size=asset["size"], timeout=timeout,
                       progress=progress, component=component)
      if hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise TermcfgError(5, "plugin_archive_digest_mismatch")
      _plugin_members(data, asset)
      archives[asset["id"]] = data
    private_dir(root)
    stage = root / (".stage-" + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    try:
      progress.stage("verify", component=component)
      _write_plugin_group(stage, assets, archives)
      _verify_plugin_group(stage, assets)
      with repository_lease(REPO_ROOT, exclusive=False):
        if _read_lock_raw(component)[1] != snapshot:
          raise TermcfgError(4, "lock_snapshot_changed", "./termcfg sync --component " + component)
        progress.stage("activate", component=component)
        if group.exists():
          _verify_plugin_group(group, assets)
        else:
          os.replace(stage, group)
          _verify_plugin_group(group, assets)
        _activate_plugin_group(root, group)
    finally:
      if stage.exists():
        shutil.rmtree(stage)
  else:
    _verify_plugin_group(group, assets)
    with repository_lease(REPO_ROOT, exclusive=False):
      if _read_lock_raw(component)[1] != snapshot:
        raise TermcfgError(4, "lock_snapshot_changed", "./termcfg sync --component " + component)
      _activate_plugin_group(root, group)
  return {"component": component, "prepared": [asset["id"] for asset in assets],
          "package": str(group), "next_command": "./termcfg doctor"}


def _activate_plugin_group(root: Path, group: Path) -> None:
  current = root / "current"
  if current.exists() and not current.is_symlink():
    raise TermcfgError(4, "plugin_activation_conflict")
  if current.is_symlink():
    link = os.readlink(current)
    if "/" in link or link.startswith("."):
      raise TermcfgError(4, "plugin_activation_conflict")
  temporary = root / (".current-" + uuid.uuid4().hex)
  try:
    os.symlink(group.name, temporary)
    os.replace(temporary, current)
  finally:
    temporary.unlink(missing_ok=True)
  if current.resolve() != group.resolve():
    raise TermcfgError(4, "plugin_activation_conflict")


def installed_plugins(component: str) -> bool:
  if component not in {"zsh", "tmux"}:
    raise TermcfgError(2, "invalid_component")
  lock, snapshot = _read_lock_raw(component)
  root = _plugin_group_root(component)
  current = root / "current"
  group = root / snapshot[:24]
  if not current.is_symlink() or os.readlink(current) != group.name:
    return False
  _verify_plugin_group(group, lock["assets"][component])
  return True


def sync(machine: MachineSelection, component: str, *, timeout: int = 300) -> dict:
  if component not in {"zsh", "tmux", "mihomo"}:
    raise TermcfgError(2, "invalid_component")
  progress = Progress("sync")
  with operation_lease(machine.machine_id):
    require_current_machine(machine)
    require_no_pending_recovery(machine)
    progress.stage("resolve", component=component)
    with repository_lease(REPO_ROOT, exclusive=False):
      lock, snapshot = _read_lock_raw(component)
      asset = lock["assets"].get(current_platform()) if component == "mihomo" else None
      if component == "mihomo" and asset is None:
        raise TermcfgError(5, "unsupported_platform")
    if component != "mihomo":
      return _sync_plugins(machine, component, lock["assets"][component], snapshot,
                           timeout=timeout, progress=progress)
    destination = package_path(machine, asset)
    if destination.exists():
      _verify_package(destination, asset)
    else:
      data = _download(asset["url"], expected_size=asset["size"], timeout=timeout,
                       progress=progress, component=component)
      progress.stage("verify", component=component)
      if hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise TermcfgError(5, "asset_digest_mismatch")
      binary = _unpack_single_gzip(data)
      private_dir(destination.parent)
      stage = destination.parent / (".stage-" + uuid.uuid4().hex)
      stage.mkdir(mode=0o700)
      try:
        atomic_bytes(stage / "archive.gz", data)
        atomic_bytes(stage / "mihomo", binary, mode=0o700)
        atomic_bytes(stage / "receipt.json", json.dumps({"asset_sha256": asset["sha256"], "binary_sha256": hashlib.sha256(binary).hexdigest()}).encode())
        _verify_package(stage, asset)
        progress.stage("activate", component=component)
        with repository_lease(REPO_ROOT, exclusive=False):
          if _read_lock_raw(component)[1] != snapshot:
            raise TermcfgError(4, "lock_snapshot_changed", "./termcfg sync --component mihomo")
          if destination.exists():
            _verify_package(destination, asset)
          else:
            os.replace(stage, destination)
            _verify_package(destination, asset)
          state = read_state(machine)
          if state["selected_core"] != asset["sha256"]:
            state["selected_core"] = asset["sha256"]
            state["pending_core_effect"] = True
            write_json(state_file(machine), state)
      finally:
        if stage.exists():
          shutil.rmtree(stage)
      return {"component": component, "package": str(destination),
              "pending_core_effect": read_state(machine)["pending_core_effect"],
              "next_command": "./termcfg doctor"}
    with repository_lease(REPO_ROOT, exclusive=False):
      if _read_lock_raw(component)[1] != snapshot:
        raise TermcfgError(4, "lock_snapshot_changed", "./termcfg sync --component mihomo")
      state = read_state(machine)
      if state["selected_core"] != asset["sha256"]:
        state["selected_core"] = asset["sha256"]
        state["pending_core_effect"] = True
        write_json(state_file(machine), state)
    return {"component": component, "package": str(destination),
            "pending_core_effect": read_state(machine)["pending_core_effect"],
            "next_command": "./termcfg doctor"}


def lock_mihomo(version: str, *, timeout: int = 300) -> dict:
  if not version.startswith("v1.") or any(char not in "0123456789.v" for char in version):
    raise TermcfgError(2, "invalid_version")
  progress = Progress("lock")
  with repository_lease(REPO_ROOT, exclusive=False):
    previous, identity = _read_lock_raw("mihomo")
  progress.stage("resolve", component="mihomo")
  metadata = _download(OFFICIAL_API + version, expected_size=None, timeout=timeout,
                       progress=progress, component="mihomo")
  try:
    release = json.loads(metadata)
    if release["tag_name"] != version:
      raise ValueError("tag")
    name = ASSET_NAME.format(version=version)
    match = [asset for asset in release["assets"] if asset["name"] == name]
    if len(match) != 1:
      raise ValueError("asset")
    selected = match[0]
    digest = selected["digest"]
    asset = {"version": version, "platform": "linux-x86_64", "name": name,
             "url": selected["browser_download_url"], "size": selected["size"],
             "sha256": digest.removeprefix("sha256:"), "archive": "gzip-single",
             "entry": "mihomo", "resources": []}
    if not digest.startswith("sha256:"):
      raise ValueError("digest")
    _validate_asset("linux-x86_64", asset)
  except (KeyError, TypeError, ValueError) as exc:
    raise TermcfgError(5, "official_release_metadata_invalid") from exc
  downloaded = _download(asset["url"], expected_size=asset["size"], timeout=timeout,
                         progress=progress, component="mihomo")
  progress.stage("verify", component="mihomo")
  if hashlib.sha256(downloaded).hexdigest() != asset["sha256"]:
    raise TermcfgError(5, "asset_digest_mismatch")
  binary = _unpack_single_gzip(downloaded)
  updated = {"version": 1, "component": "mihomo", "assets": {"linux-x86_64": asset}}
  with repository_lease(REPO_ROOT, exclusive=True):
    if _read_lock_raw("mihomo")[1] != identity:
      raise TermcfgError(4, "lock_snapshot_changed", "./termcfg lock --component mihomo --version " + version)
    progress.stage("activate", component="mihomo")
    atomic_bytes(lock_path("mihomo"), (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode(), mode=0o644)
  return {"component": "mihomo", "version": version, "platform": "linux-x86_64",
          "sha256": asset["sha256"], "size": asset["size"],
          "next_command": "./termcfg sync --component mihomo"}


def lock_plugin(component: str, plugin_id: str, commit: str, *, timeout: int = 300) -> dict:
  if component not in {"zsh", "tmux"} or not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
    raise TermcfgError(2, "invalid_plugin_version")
  progress = Progress("lock")
  with repository_lease(REPO_ROOT, exclusive=False):
    original, identity = _read_lock_raw(component)
  old = next((item for item in original["assets"][component] if item["id"] == plugin_id), None)
  if old is None:
    raise TermcfgError(2, "unknown_plugin")
  url = f"https://codeload.github.com/{old['repo']}/tar.gz/{commit}"
  progress.stage("resolve", component=component, item=plugin_id)
  data = _download(url, expected_size=None, timeout=timeout, progress=progress, component=component)
  resources = []
  try:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
      seen = set()
      for member in archive.getmembers():
        if not member.isfile():
          if member.isdir() or member.issym() or member.islnk():
            continue
          raise TermcfgError(5, "plugin_archive_shape_invalid")
        parts = member.name.split("/", 1)
        if len(parts) != 2:
          raise TermcfgError(5, "plugin_archive_shape_invalid")
        relative = parts[1]
        _safe_member_path(relative)
        if relative in seen:
          raise TermcfgError(5, "plugin_archive_duplicate")
        seen.add(relative)
        stream = archive.extractfile(member)
        if stream is None:
          raise TermcfgError(5, "plugin_archive_shape_invalid")
        blob = stream.read(MAX_BINARY + 1)
        if len(blob) > MAX_BINARY:
          raise TermcfgError(5, "plugin_resource_too_large")
        resources.append({"path": relative, "sha256": hashlib.sha256(blob).hexdigest(),
                          "mode": "0700" if member.mode & 0o111 else "0600"})
  except (OSError, tarfile.TarError) as exc:
    raise TermcfgError(5, "plugin_archive_invalid") from exc
  progress.stage("verify", component=component, item=plugin_id)
  asset = {**old, "commit": commit, "url": url, "size": len(data),
           "sha256": hashlib.sha256(data).hexdigest(),
           "resources": sorted(resources, key=lambda item: item["path"])}
  _validate_plugin_asset(asset)
  _plugin_members(data, asset)
  updated = json.loads(json.dumps(original))
  updated["assets"][component] = [asset if item["id"] == plugin_id else item for item in original["assets"][component]]
  with repository_lease(REPO_ROOT, exclusive=True):
    if _read_lock_raw(component)[1] != identity:
      raise TermcfgError(4, "lock_snapshot_changed", "./termcfg lock --component " + component + " --plugin " + plugin_id + " --version " + commit)
    progress.stage("activate", component=component, item=plugin_id)
    atomic_bytes(lock_path(component), (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode(), mode=0o644)
  return {"component": component, "plugin": plugin_id, "commit": commit,
          "sha256": asset["sha256"], "size": asset["size"],
          "next_command": "./termcfg sync --component " + component}

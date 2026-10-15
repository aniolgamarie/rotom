"""官方固定资产的显式锁定和私人版本化安装。"""

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
from .state import atomic_bytes, private_dir, read_state, require_no_pending_recovery


MAX_ARCHIVE = 150 * 1024 * 1024
MAX_BINARY = 200 * 1024 * 1024

# 允许锁定的插件仓库前缀（GitHub owner）；新增插件必须属于这些来源之一。
_PLUGIN_REPO_PREFIXES = ("tmux-plugins/", "zdharma-continuum/", "zdharma/",
                         "zsh-users/", "skywind3000/", "ohmyzsh/")


def current_platform() -> str:
  system = platform.system().lower()
  machine = platform.machine().lower()
  return f"{system}-{'x86_64' if machine in {'amd64', 'x86_64'} else machine}"


def lock_path(component: str) -> Path:
  if component not in {"zsh", "tmux"}:
    raise TermcfgError(2, "invalid_component")
  return REPO_ROOT / "locks/termcfg/plugins.json"


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
  if (not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", identifier) or
      not isinstance(repo, str) or not repo.startswith(_PLUGIN_REPO_PREFIXES) or
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
  # O(n) 前缀冲突检测：任一资源的祖先目录若也是资源即冲突。
  # 原先逐对比较 Path.parents 是 O(n²)，ohmyzsh 这类上千文件的插件会卡数十秒。
  path_parts = [PurePosixPath(item).parts for item in paths]
  for parts in path_parts:
    for depth in range(1, len(parts)):
      if "/".join(parts[:depth]) in paths:
        raise TermcfgError(2, "plugin_resource_overlap")
  if asset["entry"] not in paths or not paths:
    raise TermcfgError(2, "plugin_entry_missing")


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
  if component not in {"zsh", "tmux"}:
    raise TermcfgError(2, "invalid_component")
  progress = Progress("sync")
  with operation_lease(machine.machine_id):
    require_current_machine(machine)
    require_no_pending_recovery(machine)
    read_state(machine)
    progress.stage("resolve", component=component)
    with repository_lease(REPO_ROOT, exclusive=False):
      lock, snapshot = _read_lock_raw(component)
    return _sync_plugins(machine, component, lock["assets"][component], snapshot,
                         timeout=timeout, progress=progress)


def lock_plugin(component: str, plugin_id: str, commit: str, *, repo: str | None = None,
                entry: str | None = None, timeout: int = 300) -> dict:
  if component not in {"zsh", "tmux"} or not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
    raise TermcfgError(2, "invalid_plugin_version")
  progress = Progress("lock")
  with repository_lease(REPO_ROOT, exclusive=False):
    original, identity = _read_lock_raw(component)
  old = next((item for item in original["assets"][component] if item["id"] == plugin_id), None)
  adding = old is None
  if adding:
    # 新增插件：必须由维护者显式提供仓库与入口文件，骨架先过一遍格式校验。
    if not repo or not entry:
      raise TermcfgError(2, "plugin_add_requires_repo_entry",
                         "./termcfg lock --component " + component + " --plugin " + plugin_id +
                         " --repo <owner/name> --entry <path> --version <完整提交>")
    old = {"id": plugin_id, "repo": repo, "commit": commit,
           "platform": "all", "url": f"https://codeload.github.com/{repo}/tar.gz/{commit}",
           "size": 1, "sha256": "0" * 64, "archive": "tar.gz", "entry": entry,
           "resources": [{"path": entry, "sha256": "0" * 64, "mode": "0600"}]}
    _validate_plugin_asset(old)
  elif repo is not None or entry is not None:
    raise TermcfgError(2, "plugin_already_locked")
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
  if adding:
    updated["assets"][component] = original["assets"][component] + [asset]
  else:
    updated["assets"][component] = [asset if item["id"] == plugin_id else item for item in original["assets"][component]]
  with repository_lease(REPO_ROOT, exclusive=True):
    if _read_lock_raw(component)[1] != identity:
      raise TermcfgError(4, "lock_snapshot_changed", "./termcfg lock --component " + component + " --plugin " + plugin_id + " --version " + commit)
    progress.stage("activate", component=component, item=plugin_id)
    atomic_bytes(lock_path(component), (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode(), mode=0o644)
  return {"component": component, "plugin": plugin_id, "commit": commit,
          "sha256": asset["sha256"], "size": asset["size"],
          "next_command": "./termcfg sync --component " + component}

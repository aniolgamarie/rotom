"""OMP standalone 完整锁、按内容核验的运行包及缓存租约。"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import errno
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import tomllib
import uuid

from jsonschema import Draft202012Validator
from .deployment import json_bytes
from .paths import relative_path, safe_id
from .process import DependencyError
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private

ROOT = Path(__file__).resolve().parents[2]
TAG = "v18.3.0"
COMMIT = "62bc57be1b03ef0802a33cf7f5f530e534527531"
SOURCE_URL = "https://codeload.github.com/can1357/oh-my-pi/tar.gz/" + COMMIT
SOURCE_SHA256 = "edcc0f93a0ab0c0223d0651bba3624c55a32d25494a43b0257ea626be1dff97d"
RELEASE_URL = "https://github.com/can1357/oh-my-pi/releases/download/" + TAG + "/"
ASSETS = {name: {"url": RELEASE_URL + asset, "sha256": digest} for name, asset, digest in (
  ("linux-x64", "omp-linux-x64", "d2fdaa29affe96e596eb9c78d42f548f1f291df28608631bcc00750a84b94bc3"),
  ("linux-arm64", "omp-linux-arm64", "bdfb9c494e17a2fee1956dae16a010a1953574ce4172c4db8efe06fbe477c637"),
  ("macos-x64", "omp-darwin-x64", "be74498e0edcde7e018247b925f0e0ebf00a7748a1006b3a02eb62ca9e021baf"),
  ("macos-arm64", "omp-darwin-arm64", "d61fb411f24146bed48dd901b13b5912a297d899ee691dda69c4b5b7ab8c35dc"),
)}
UPSTREAM = {"upstream/" + name for name in ("bun.lock", "LICENSE", "THIRD-PARTY-NOTICES.txt", "provenance.json", "NOTICE.md")}
PYTHON_REQUIREMENT = {"kind": "manager-python", "implementation": "cpython", "minimum": [3, 11]}


def sha(value):
  return hashlib.sha256(value).hexdigest()


def platform_id():
  machine = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
  if machine not in ("x64", "arm64"):
    raise DependencyError("OMP首版不支持此架构")
  if sys.platform.startswith("linux") and platform.libc_ver()[0].lower() == "glibc":
    return "linux-" + machine
  if sys.platform == "darwin":
    return "macos-" + machine
  raise DependencyError("OMP首版仅支持glibc Linux和macOS")


def _files(directory):
  """列举实际普通文件；不跟随目录或文件链接。"""
  if directory.is_symlink():
    raise Conflict("OMP包目录不得为链接")
  result = []
  if not directory.exists():
    return result
  for root, directories, files in os.walk(directory, followlinks=False):
    for name in directories:
      if (Path(root) / name).is_symlink():
        raise Conflict("OMP包不得包含链接")
    for name in files:
      path = Path(root) / name
      info = path.lstat()
      if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise Conflict("OMP包必须包含普通单链接文件")
      result.append(path.relative_to(directory).as_posix())
  return sorted(result)


def _read(tree, path):
  relative_path(path)
  result = tree.read(path)
  if result is None:
    raise ValueError()
  return result


def _download(url):
  from .omp_download import download_bytes
  return download_bytes(url)


def interpreter_identity(requirements):
  if not requirements:
    return {}
  if requirements != {"python": PYTHON_REQUIREMENT} or platform.python_implementation() != "CPython" or sys.version_info < (3, 11):
    raise DependencyError("OMP MCP需要已准备的CPython 3.11或以上")
  executable = Path(sys.executable).resolve(strict=True)
  info = executable.stat()
  if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
    raise DependencyError("OMP MCP解释器身份无效")
  return {"python": {"path": str(executable), "version": platform.python_version(),
    "implementation": "cpython", "sha256": sha(executable.read_bytes())}}


@dataclass(frozen=True)
class OmpLock:
  identity: str
  metadata: dict = field(repr=False)


class OmpBackend:
  adapter_id = "omp"
  adapter_version = "omp-1"

  def read_lock(self, repository):
    try:
      repository = Path(repository)
      with Tree(repository / "locks/omp", private=False) as tree:
        data = json.loads(_read(tree, "manifest.json")[0])
        schema = json.loads((ROOT / "schemas/omp-lock.schema.json").read_bytes())
        Draft202012Validator(schema).validate(data)
        if (data["source"] != {"url": SOURCE_URL, "sha256": SOURCE_SHA256}
            or data["assets"] != ASSETS or set(data["upstream"]) != UPSTREAM):
          raise ValueError()
        if sha(json_bytes({key: value for key, value in data.items() if key != "identity"})) != data["identity"]:
          raise ValueError()
        for path, digest in data["upstream"].items():
          if sha(_read(tree, path)[0]) != digest:
            raise ValueError()
      targets = set()
      with Tree(repository, private=False) as tree:
        for path, digest in data["recipe"].items():
          if sha(_read(tree, path)[0]) != digest:
            raise ValueError()
        for entry in data["resources"]:
          relative_path(entry["target"])
          if entry["target"] in targets or entry["target"].split("/")[0] not in ("packages", "resources", "skills", "rules"):
            raise ValueError()
          targets.add(entry["target"])
          raw = _read(tree, entry["path"])
          if sha(raw[0]) != entry["sha256"] or bool(raw[1] & 0o111) != entry["executable"]:
            raise ValueError()
        for name, package in data["packages"].items():
          safe_id(name)
          relative_path(package["source"])
          entries = [entry for entry in data["resources"] if entry["target"].startswith("packages/" + name + "/")]
          if package["tree_digest"] != sha(json_bytes(entries)) or not entries:
            raise ValueError()
          paths = {entry["target"].removeprefix("packages/" + name + "/") for entry in entries}
          if set(_files(repository / package["source"])) != paths:
            raise ValueError()
          for path in package["entrypoints"]:
            relative_path(path)
            if path not in paths:
              raise ValueError()
      if data["interpreters"] not in ({}, {"python": PYTHON_REQUIREMENT}):
        raise ValueError()
      if any(entry["target"].endswith(".py") for entry in data["resources"]) and not data["interpreters"]:
        raise ValueError()
      resources, packages, recipe = self._resources(repository)
      if (data["resources"], data["packages"], data["recipe"]) != (resources, packages, recipe):
        raise ValueError()
      return OmpLock(data["identity"], data)
    except Exception:
      raise ConfigError("omp-lock-missing-or-stale") from None

  def resolve_lock(self, repository, *, source_archive=None, checksums=None):
    """显式维护操作；固定来源校验成功后写入完整锁，绝不执行上游。"""
    repository = Path(repository)
    archive = Path(source_archive).read_bytes() if source_archive is not None else _download(SOURCE_URL)
    if sha(archive) != SOURCE_SHA256:
      raise ConfigError("omp-source-integrity")
    sums = Path(checksums).read_bytes() if checksums is not None else _download(RELEASE_URL + "SHA256SUMS.txt")
    entries = {parts[1].lstrip("*"): parts[0] for line in sums.decode().splitlines() if len(parts := line.split()) == 2}
    if any(entries.get(asset["url"].rsplit("/", 1)[1]) != asset["sha256"] for asset in ASSETS.values()):
      raise ConfigError("omp-release-integrity")
    upstream = {}
    try:
      with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        for name in ("bun.lock", "LICENSE", "THIRD-PARTY-NOTICES.txt"):
          members = [member for member in bundle.getmembers() if len(Path(member.name).parts) == 2 and Path(member.name).name == name]
          if len(members) != 1 or not members[0].isfile():
            raise ValueError()
          upstream["upstream/" + name] = bundle.extractfile(members[0]).read()
    except Exception:
      raise ConfigError("omp-source-shape") from None
    upstream["upstream/provenance.json"] = json_bytes({"tag": TAG, "commit": COMMIT,
      "source": {"url": SOURCE_URL, "sha256": SOURCE_SHA256}, "assets": ASSETS,
      "build": "Official standalone, embedded Bun; no source patches or install scripts executed."})
    upstream["upstream/NOTICE.md"] = ("# OMP upstream notices\n\nFixed " + TAG + " / " + COMMIT
      + "\n\nSee LICENSE and complete THIRD-PARTY-NOTICES.txt beside this file.\n"
      + "Official binaries embed their runtime; the Bun lock records source dependency resolution, not a claim of reproducible release builds.\n").encode()
    resources, packages, recipe = self._resources(repository)
    body = {"version": 1, "adapter_version": self.adapter_version, "tag": TAG, "commit": COMMIT,
      "source": {"url": SOURCE_URL, "sha256": SOURCE_SHA256}, "assets": ASSETS,
      "upstream": {name: sha(value) for name, value in upstream.items()}, "resources": resources,
      "packages": packages, "recipe": recipe,
      "interpreters": {"python": PYTHON_REQUIREMENT} if any(entry["target"].endswith(".py") for entry in resources) else {}}
    manifest = {"identity": sha(json_bytes(body)), **body}
    directory = repository / "locks/omp"
    directory.mkdir(parents=True, exist_ok=True)
    with Tree(directory, private=False) as tree:
      for name, value in upstream.items():
        tree.write_state(name, value)
      tree.write_state("manifest.json", json_bytes(manifest))
    return self.read_lock(repository)

  def _resources(self, repository):
    resources, packages, recipe = [], {}, {}
    declarations = repository / "agents/omp/plugins.toml"
    plugins = tomllib.loads(declarations.read_text()).get("plugins", {}) if declarations.exists() else {}
    with Tree(repository, private=False) as tree:
      for kind in ("resources", "packages"):
        directory = repository / "agents/omp" / kind
        for name in _files(directory):
          source = "agents/omp/" + kind + "/" + name
          raw = _read(tree, source)
          resources.append({"path": source, "target": kind + "/" + name,
            "sha256": sha(raw[0]), "executable": bool(raw[1] & 0o111)})
      for directory in sorted((repository / "agents/omp/packages").glob("*")):
        if not directory.is_dir() or directory.is_symlink():
          raise ConfigError("omp-package-directory")
        name = directory.name
        entries = [entry for entry in resources if entry["target"].startswith("packages/" + name + "/")]
        declared = plugins.get(name, {})
        manifest_path = directory / "package.json"
        if manifest_path.exists():
          package_manifest = json.loads(_read(tree, manifest_path.relative_to(repository).as_posix())[0])
          if any(package_manifest.get(key) for key in ("dependencies", "optionalDependencies", "peerDependencies", "bundledDependencies")):
            raise ConfigError("omp-package-unlocked-dependency")
        entrypoints = declared.get("entrypoints", [candidate for candidate in ("index.ts", "server.py") if (directory / candidate).is_file()])
        if not entries or not entrypoints:
          raise ConfigError("omp-package-entrypoints")
        packages[name] = {"source": "agents/omp/packages/" + name, "entrypoints": entrypoints,
          "tree_digest": sha(json_bytes(entries)), "license": declared.get("license", "MIT"), "compatibility": TAG}
      # OMP 输入配方与完整验收技能均纳入闭包；不锁入其他工具的运行产物。
      inputs = sorted((repository / "agents/omp").glob("*.toml")) + sorted((repository / "profiles").glob("omp-*.toml"))
      discovery_manifest = repository / "agents/omp/discovery-manifest.json"
      if discovery_manifest.exists() or discovery_manifest.is_symlink():
        inputs.append(discovery_manifest)
      fixture = repository / "tests/fixtures/omp"
      for name in _files(fixture):
        path = "tests/fixtures/omp/" + name
        raw = _read(tree, path)
        if name.startswith("skills/"):
          resources.append({"path": path, "target": name, "sha256": sha(raw[0]), "executable": bool(raw[1] & 0o111)})
        else:
          recipe[path] = sha(raw[0])
      # 完整公共资源目录可由local选择；锁入可选资源而不依赖机器秘密。
      catalogs = sorted((repository / "shared").glob("*.toml"))
      omp_catalog = repository / "agents/omp/content.toml"
      if omp_catalog.exists():
        catalogs.append(omp_catalog)
      fixture_catalog = fixture / "registry.toml"
      if fixture_catalog.exists():
        catalogs.append(fixture_catalog)
      known = {entry["target"]: entry for entry in resources}
      for catalog in catalogs:
        path = catalog.relative_to(repository).as_posix()
        raw = _read(tree, path)
        recipe[path] = sha(raw[0])
        document = tomllib.loads(raw[0].decode())
        for kind in ("rules", "skills"):
          for name, definition in document.get(kind, {}).items():
            safe_id(name)
            source = definition["path"]
            relative_path(source)
            entries = _files(repository / source) if kind == "skills" else [""]
            for child in entries:
              source_path = source + ("/" + child if child else "")
              target = kind + "/" + name + (("/" + child) if child else ".md")
              raw = _read(tree, source_path)
              entry = {"path": source_path, "target": target, "sha256": sha(raw[0]), "executable": bool(raw[1] & 0o111)}
              if target in known and known[target] != entry:
                raise ConfigError("omp-resource-target-collision")
              if target not in known:
                resources.append(entry)
                known[target] = entry
      for path in inputs:
        relative = path.relative_to(repository).as_posix()
        recipe[relative] = sha(_read(tree, relative)[0])
    return resources, packages, recipe

  def runtime_identity(self, workspace, lock):
    return lock.identity + "-" + platform_id()

  def root(self, workspace, identity):
    safe_id(identity)
    return workspace.cache / "runtimes" / identity

  def executable_paths(self, root):
    return (root / "bin",)

  @contextmanager
  def runtime_guard(self, workspace, identity, *, exclusive=False):
    safe_id(identity)
    with Tree(workspace.cache / "leases", create=True) as tree:
      with tree.parent(identity + ".lock") as (parent, name):
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
      try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
          raise Conflict("OMP运行包租约文件不安全")
        try:
          fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except OSError as error:
          if error.errno in (errno.EAGAIN, errno.EACCES):
            raise Conflict("OMP运行包正在使用或维护") from None
          raise
        yield fd
      finally:
        os.close(fd)

  def _receipt(self, workspace, lock, identity):
    return {"version": 1, "adapter_version": self.adapter_version, "identity": identity,
      "lock_identity": lock.identity, "platform": platform_id(), "binary_sha256": lock.metadata["assets"][platform_id()]["sha256"],
      "source_sha256": lock.metadata["source"]["sha256"], "path": str(self.root(workspace, identity)),
      "resources_digest": sha(json_bytes(lock.metadata["resources"])),
      "interpreters": interpreter_identity(lock.metadata["interpreters"])}

  def _verify(self, root, receipt, lock):
    expected = {"bin/omp": (receipt["binary_sha256"], 0o700),
      **{entry["target"]: (entry["sha256"], 0o700 if entry["executable"] else 0o600) for entry in lock.metadata["resources"]}}
    if set(_files(root)) != {*expected, ".agentcfg-receipt.json"}:
      raise ValueError()
    # 空目录也属于包形状，不能因没有文件而绕过完整闭包核验。
    expected_directories = {parent.as_posix() for name in expected
      for parent in Path(name).parents if parent != Path(".")}
    actual_directories = set()
    for directory, children, _ in os.walk(root, followlinks=False):
      for child in children:
        path = Path(directory) / child
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
          raise ValueError()
        actual_directories.add(path.relative_to(root).as_posix())
    if actual_directories != expected_directories:
      raise ValueError()
    with Tree(root) as tree:
      raw = _read(tree, ".agentcfg-receipt.json")
      if raw[1] != 0o600 or json.loads(raw[0]) != receipt:
        raise ValueError()
      for name, (digest, mode) in expected.items():
        with tree.open_read(name) as (stream, info):
          checksum = hashlib.sha256()
          while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
          if checksum.hexdigest() != digest or stat.S_IMODE(info.st_mode) != mode:
            raise ValueError()

  def status(self, workspace, identity):
    root = self.root(workspace, identity)
    if (root.parent / (".pending-" + identity + ".json")).exists():
      return "damaged"
    if not root.exists() and not root.is_symlink():
      return "missing"
    try:
      lock = self.read_lock(workspace.repository)
      if identity != self.runtime_identity(workspace, lock):
        return "damaged"
      self._verify(root, self._receipt(workspace, lock, identity), lock)
      return "installed"
    except Exception:
      return "damaged"

  def _recover_activation(self, workspace, lock, identity):
    root = self.root(workspace, identity)
    if not root.parent.exists():
      return
    name = ".pending-" + identity + ".json"
    with Tree(root.parent) as tree:
      raw = tree.read(name)
      if raw is None:
        return
      try:
        journal = json.loads(raw[0])
        if (raw[1] != 0o600 or set(journal) != {"version", "identity", "old", "stage"}
            or journal["version"] != 1 or journal["identity"] != identity):
          raise ValueError()
        for key, prefix in (("old", ".previous-"), ("stage", ".stage-")):
          safe_id(journal[key])
          if not journal[key].startswith(prefix):
            raise ValueError()
        old, stage = root.parent / journal["old"], root.parent / journal["stage"]
        for path in (root, old, stage):
          if path.exists() or path.is_symlink():
            with Tree(path):
              pass
      except Exception:
        raise Conflict("OMP运行包激活日志或路径无效；保留恢复现场") from None
      if old.exists():
        if root.exists():
          try:
            self._verify(root, self._receipt(workspace, lock, identity), lock)
          except Exception:
            raise Conflict("OMP激活中断后新包未通过校验；保留旧包与日志") from None
          shutil.rmtree(old)
        else:
          os.rename(old, root)
        os.fsync(tree.fd)
      if stage.exists():
        shutil.rmtree(stage)
        os.fsync(tree.fd)
      tree.replace(name, None, expected=raw[2])

  def sync(self, workspace, lock):
    # 从受信仓库重读，防止调用者用伪造的内存对象绕过锁完整性。
    current = self.read_lock(workspace.repository)
    if current != lock:
      raise ConfigError("omp-lock-changed")
    identity = self.runtime_identity(workspace, lock)
    root = self.root(workspace, identity)
    with self.runtime_guard(workspace, identity, exclusive=True):
      self._recover_activation(workspace, lock, identity)
      if self.status(workspace, identity) == "installed":
        return {"status": "installed", "identity": identity}
      asset = lock.metadata["assets"][platform_id()]
      from .omp_download import ensure_cached_asset
      downloads = workspace.cache / "downloads"
      ensure_cached_asset(downloads, asset["url"], asset["sha256"])
      ensure_private(root.parent)
      stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=root.parent))
      old = root.parent / (".previous-" + uuid.uuid4().hex)
      moved = False
      try:
        receipt = self._receipt(workspace, lock, identity)
        with Tree(stage) as target, Tree(workspace.repository, private=False) as source:
          # 大型二进制从已校验cache流式写入私有stage，避免WSL安装阶段整包驻内存。
          with Tree(downloads) as cache, cache.open_read(asset["sha256"]) as (binary, info):
            if stat.S_IMODE(info.st_mode) != 0o600:
              raise DependencyError("OMP下载缓存权限无效")
            with target.parent("bin/omp", create=True) as (parent, name):
              fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o700, dir_fd=parent)
              with os.fdopen(fd, "wb") as output:
                checksum = hashlib.sha256()
                while chunk := binary.read(1024 * 1024):
                  output.write(chunk)
                  checksum.update(chunk)
                output.flush()
                os.fsync(output.fileno())
              os.fsync(parent)
            if checksum.hexdigest() != asset["sha256"]:
              raise DependencyError("OMP缓存资产摘要不匹配；未激活运行包")
          for entry in lock.metadata["resources"]:
            raw = _read(source, entry["path"])
            if sha(raw[0]) != entry["sha256"] or bool(raw[1] & 0o111) != entry["executable"]:
              raise DependencyError("OMP包来源在安装期间变化")
            target.replace(entry["target"], raw[0], 0o700 if entry["executable"] else 0o600, expected=None)
          target.write_new(".agentcfg-receipt.json", json_bytes(receipt))
        self._verify(stage, receipt, lock)
        with Tree(root.parent) as activation:
          journal_name = ".pending-" + identity + ".json"
          activation.write_new(journal_name, json_bytes({"version": 1, "identity": identity,
            "old": old.name, "stage": stage.name}))
          if root.exists() or root.is_symlink():
            # 排他租约内替换；先持久化日志，再移动旧包，下一次sync可恢复。
            with Tree(root):
              pass
            os.rename(root, old)
            moved = True
            os.fsync(activation.fd)
          try:
            os.rename(stage, root)
            os.fsync(activation.fd)
          except BaseException:
            if moved:
              os.rename(old, root)
              moved = False
              os.fsync(activation.fd)
            pending = activation.read(journal_name)
            activation.replace(journal_name, None, expected=pending[2])
            raise
          if moved:
            shutil.rmtree(old)
            os.fsync(activation.fd)
          pending = activation.read(journal_name)
          activation.replace(journal_name, None, expected=pending[2])
        return {"status": "installed", "identity": identity}
      finally:
        if stage.exists():
          shutil.rmtree(stage)

  def toolchain(self, lock):
    return {"omp": lock.metadata["tag"], "host": "standalone", "external": lock.metadata["interpreters"]}

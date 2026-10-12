"""显式离线构建候选；不执行产物，不安装，不修改上游源码。"""
import gzip
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import tarfile
import tempfile
import zipfile

from . import pi_bwrap_source
from .paths import _absolute_directory, relative_path
from .schema import ConfigError
from .storage import Tree


INPUTS = {
  "bwrap-source": {"name": "bubblewrap-0.13.0.tar.xz", "sha256": pi_bwrap_source.ARCHIVE_SHA256, "url": pi_bwrap_source.SOURCE_URL},
  "libcap": {"name": "libcap-2.77.tar.xz", "sha256": "897bc18b44afc26c70e78cead3dbb31e154acc24bee085a5a09079a88dbf6f52", "url": "https://www.kernel.org/pub/linux/libs/security/linux-privs/libcap2/libcap-2.77.tar.xz"},
  "meson": {"name": "meson-1.9.0-py3-none-any.whl", "sha256": "45e51ddc41e37d961582d06e78c48e0f9039011587f3495c4d6b0781dad92357", "url": "https://files.pythonhosted.org/packages/23/ed/a449e8fb5764a7f6df6e887a2d350001deca17efd6ecd5251d2fb6202009/meson-1.9.0-py3-none-any.whl"},
}
MAX_ARCHIVE = 4 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024
MAX_ENTRIES = 2048
TOOLS = ("gcc", "make", "ar", "ranlib", "ninja", "pkg-config", "python3.11", "readelf", "ld.bfd")


def _record(records, name, directory):
  path = relative_path(name)
  if path.is_absolute() or name in records:
    raise ValueError()
  if any(records.get(parent.as_posix()) is False for parent in path.parents):
    raise ValueError()
  if not directory and any(item.startswith(name + "/") for item in records):
    raise ValueError()
  records[name] = directory


def _tar_entries(raw, prefix):
  try:
    if type(raw) is not bytes or not raw or len(raw) > MAX_ARCHIVE: raise ValueError()
    decoder = lzma.LZMADecompressor(memlimit=64 * 1024 * 1024)
    limit = MAX_EXPANDED + MAX_ENTRIES * 4096 + 10240
    expanded = decoder.decompress(raw, max_length=limit + 1)
    if len(expanded) > limit or not decoder.eof or decoder.unused_data:
      raise ValueError()
    records, files, total, count = {}, [], 0, 0
    with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
      for item in archive:
        count += 1
        if count > MAX_ENTRIES or item.mode & ~0o777 or item.issparse(): raise ValueError()
        if item.name == prefix:
          if not item.isdir() or "" in records: raise ValueError()
          records[""] = True
          continue
        if not item.name.startswith(prefix + "/"): raise ValueError()
        name = item.name[len(prefix) + 1:]
        _record(records, name, item.isdir())
        if item.isdir():
          if item.size: raise ValueError()
          continue
        if item.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or item.size < 0: raise ValueError()
        total += item.size
        if total > MAX_EXPANDED: raise ValueError()
        with archive.extractfile(item) as stream: data = stream.read(item.size + 1)
        if len(data) != item.size: raise ValueError()
        files.append((name, data, 0o755 if item.mode & 0o111 else 0o644))
    if not files: raise ValueError()
    return tuple(sorted(files))
  except Exception:
    raise ConfigError("pi-bwrap-build-input") from None


def _zip_entries(raw):
  try:
    if type(raw) is not bytes or not raw or len(raw) > MAX_ARCHIVE: raise ValueError()
    records, files, total = {}, [], 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
      entries = archive.infolist()
      if len(entries) > MAX_ENTRIES: raise ValueError()
      for item in entries:
        if item.orig_filename != item.filename: raise ValueError()
        directory = item.is_dir()
        name = item.filename[:-1] if directory else item.filename
        mode = item.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if mode & 0o7000 or kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG) or item.flag_bits & 1:
          raise ValueError()
        _record(records, name, directory)
        total += item.file_size
        if total > MAX_EXPANDED: raise ValueError()
        if directory:
          if item.file_size: raise ValueError()
          continue
        with archive.open(item) as stream: data = stream.read(item.file_size + 1)
        if len(data) != item.file_size: raise ValueError()
        files.append((name, data, 0o755 if mode & 0o111 else 0o644))
    if not files: raise ValueError()
    return tuple(sorted(files))
  except Exception:
    raise ConfigError("pi-bwrap-build-input") from None


def verified_inputs(sources):
  """摘要固定在代码中；不存在调用方提供摘要的绕过入口。"""
  try:
    result = {}
    with Tree(Path(sources), private=False) as tree:
      for key, metadata in INPUTS.items():
        record = tree.read(metadata["name"], max_bytes=MAX_ARCHIVE)
        if record is None or hashlib.sha256(record[0]).hexdigest() != metadata["sha256"]: raise ValueError()
        raw = record[0]
        result[key] = (pi_bwrap_source.source_entries(raw) if key == "bwrap-source" else
          _tar_entries(raw, "libcap-2.77") if key == "libcap" else _zip_entries(raw))
    return result
  except Exception:
    raise ConfigError("pi-bwrap-build-input") from None


def bootstrap_identity():
  """系统工具只是断网包装器身份，不是候选产品验证证据。"""
  try:
    if platform.system() != "Linux" or platform.machine() != "x86_64": raise ValueError()
    path = Path("/usr/bin/bwrap")
    if path.resolve() != path: raise ValueError()
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
      opened = os.fstat(stream.fileno())
      identity = lambda item: (item.st_dev, item.st_ino, item.st_uid, item.st_mode, item.st_nlink, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
      if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_mode & 0o7022
          or not opened.st_mode & 0o111 or opened.st_size > MAX_ARCHIVE or identity(before) != identity(opened)):
        raise ValueError()
      raw = stream.read(MAX_ARCHIVE + 1)
      if len(raw) > MAX_ARCHIVE or identity(opened) != identity(os.fstat(stream.fileno())) or identity(opened) != identity(path.lstat()):
        raise ValueError()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
  except Exception:
    raise ConfigError("pi-bwrap-build-bootstrap") from None


BUILD_SCRIPT = r'''# 自有构建驱动；不修改第三方源码，绝不执行生成的bwrap。
import hashlib, json, os, pathlib, re, runpy, subprocess, sys
os.umask(0o077)
for name in ("home", "tmp"):
  pathlib.Path("/work", name).mkdir(mode=0o700, exist_ok=True)
tools = {}
for name in ("gcc", "make", "ar", "ranlib", "ninja", "pkg-config", "python3.11", "readelf", "ld.bfd"):
  path = "/usr/bin/" + name
  tools[name] = {"path": path, "sha256": hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest(),
    "version": subprocess.check_output([path, "--version"], text=True).splitlines()[0]}
tools["meson"] = {"version": "1.9.0"}
subprocess.run(["/usr/bin/make", "-C", "/work/libcap/libcap", "install-static-cap", "prefix=/work/cap", "lib=lib",
  "SHARED=no", "PTHREADS=no", "GOLANG=no", "USE_GPERF=no", "CC=/usr/bin/gcc", "BUILD_CC=/usr/bin/gcc",
  "AR=/usr/bin/ar", "RANLIB=/usr/bin/ranlib", "COPTS=-O2", "BUILD_LDFLAGS=-fuse-ld=bfd"], check=True)
# 固定已挂载的GNU linker；系统ld的/etc/alternatives链接不扩大进构建根。
os.environ.update(CC="/usr/bin/gcc", PKG_CONFIG_LIBDIR="/work/cap/lib/pkgconfig",
  CFLAGS="-O2 -ffile-prefix-map=/work=. -fdebug-prefix-map=/work=.", LDFLAGS="-fuse-ld=bfd -Wl,-z,relro,-z,now")
sys.path.insert(0, "/work/meson")
sys.argv = ["meson", "setup", "/work/bwrap-build", "/work/bwrap-source", "--buildtype=release", "--wrap-mode=nodownload",
  "-Dprefer_static=true", "-Db_lto=false", "-Db_pie=true", "-Dselinux=disabled", "-Dtests=false", "-Dman=disabled",
  "-Dbash_completion=disabled", "-Dzsh_completion=disabled", "-Dpython=/usr/bin/python3.11"]
try:
  runpy.run_module("mesonbuild.mesonmain", run_name="__main__")
except SystemExit as exc:
  if exc.code not in (None, 0): raise
subprocess.run(["/usr/bin/ninja", "-C", "/work/bwrap-build", "bwrap"], check=True)
binary = "/work/bwrap-build/bwrap"
dynamic = subprocess.check_output(["/usr/bin/readelf", "-d", binary], text=True)
versions = subprocess.check_output(["/usr/bin/readelf", "--version-info", binary], text=True)
observation = {"schema_version": 1, "toolchains": tools,
  "needed": sorted(re.findall(r"\(NEEDED\).*?\[(.*?)\]", dynamic)),
  "glibc_versions": sorted(set(re.findall(r"\bGLIBC_[0-9]+(?:\.[0-9]+)+\b", versions)))}
pathlib.Path("/work/build-observation.json").write_text(json.dumps(observation, sort_keys=True))
'''


def _json(value):
  return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def _object(pairs):
  result = {}
  for key, value in pairs:
    if key in result: raise ValueError()
    result[key] = value
  return result


def _observation(raw):
  value = json.loads(raw, object_pairs_hook=_object)
  if (type(value) is not dict or set(value) != {"schema_version", "toolchains", "needed", "glibc_versions"}
      or type(value["schema_version"]) is not int or value["schema_version"] != 1
      or type(value["toolchains"]) is not dict or not value["toolchains"] or value["needed"] != ["libc.so.6"]
      or type(value["glibc_versions"]) is not list or not value["glibc_versions"]
      or any(type(item) is not str or not re.fullmatch(r"GLIBC_[0-9]+(?:\.[0-9]+)+", item) for item in value["glibc_versions"])):
    raise ValueError()
  if set(value["toolchains"]) != {*TOOLS, "meson"} or value["toolchains"]["meson"] != {"version": "1.9.0"}:
    raise ValueError()
  for name in TOOLS:
    tool = value["toolchains"][name]
    if (type(tool) is not dict or set(tool) != {"path", "sha256", "version"} or tool["path"] != "/usr/bin/" + name
        or type(tool["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", tool["sha256"])
        or type(tool["version"]) is not str or not tool["version"] or len(tool["version"]) > 1024
        or any(ord(char) < 32 or ord(char) == 127 for char in tool["version"])):
      raise ValueError()
  if value["glibc_versions"] != sorted(set(value["glibc_versions"])): raise ValueError()
  return value


def _archive(entries):
  buffer = io.BytesIO()
  with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0, filename="") as compressed:
    with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
      for name, raw, mode in sorted(entries):
        item = tarfile.TarInfo(name); item.size = len(raw); item.mode = mode
        item.uid = item.gid = item.mtime = 0
        archive.addfile(item, io.BytesIO(raw))
  return buffer.getvalue()


def build_candidate(sources, output):
  """先校验输入和包装器；只发布built-not-executed，不提供安装或运行接口。"""
  try:
    output = Path(output)
    if not output.is_absolute() or ".." in output.parts or os.path.lexists(output): raise ValueError()
    entries = verified_inputs(Path(sources))
    bootstrap = bootstrap_identity()
    # 输入完整有效之前没有任何目录写入；失败日志保留于新的私有输出目录。
    # 创建前按私人路径规则验证全部祖先，不能把只读源码信任规则用于写入。
    with _absolute_directory(output.parent) as fd:
      os.mkdir(output.name, mode=0o700, dir_fd=fd)
      os.fsync(fd)
    with Tree(output) as destination:
      with tempfile.TemporaryDirectory(prefix=".build-", dir=output) as directory:
        work = Path(directory)
        with Tree(work) as tree:
          for root, files in entries.items():
            for name, raw, mode in files:
              leaf = root + "/" + name
              tree.write_new(leaf, raw)
              if mode & 0o111:
                with tree.parent(leaf) as (parent, filename):
                  fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                  try: os.fchmod(fd, 0o700)
                  finally: os.close(fd)
          tree.write_new("build.py", BUILD_SCRIPT.encode())
        argv = ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
          "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
        for path in ("/usr", "/bin", "/lib", "/lib64", "/etc/ld.so.cache"):
          argv += ["--ro-bind", path, path]
        argv += ["--bind", str(work), "/work", "--chdir", "/work", "/usr/bin/python3.11", "-I", "/work/build.py"]
        env = {"HOME": "/work/home", "PATH": "/usr/bin:/bin", "LC_ALL": "C", "TMPDIR": "/work/tmp",
          "SOURCE_DATE_EPOCH": "0", "PYTHONNOUSERSITE": "1"}
        # 固定日志文件先排他创建，避免打开调用者放置的链接。
        with destination.parent("build.stdout.log") as (parent, _):
          stdout_fd = os.open("build.stdout.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(stdout_fd, "wb") as stdout:
          with destination.parent("build.stderr.log") as (parent, _):
            stderr_fd = os.open("build.stderr.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
          with os.fdopen(stderr_fd, "wb") as stderr:
            result = subprocess.run(argv, env=env, shell=False, timeout=300, stdout=stdout, stderr=stderr)
        if result.returncode != 0: raise ValueError()
        with Tree(work) as tree:
          binary = tree.read("bwrap-build/bwrap", max_bytes=MAX_EXPANDED)
          observed = tree.read("build-observation.json", max_bytes=1024 * 1024)
        if binary is None or observed is None: raise ValueError()
        raw = binary[0]
        if (len(raw) < 64 or raw[:6] != b"\x7fELF\x02\x01" or raw[7] not in (0, 3) or raw[18:20] != b"\x3e\x00"
            or raw[16:18] not in (b"\x02\x00", b"\x03\x00") or not binary[1] & 0o111): raise ValueError()
        observation = _observation(observed[0])
        provenance = {"schema_version": 1, "inputs": INPUTS, "build_script_sha256": hashlib.sha256(BUILD_SCRIPT.encode()).hexdigest(),
          "bootstrap": bootstrap, "observation": observation}
        licenses = {root: dict((name, data) for name, data, _ in files) for root, files in entries.items()}
        packed = _archive((("bin/pi-bwrap", raw, 0o755),
          ("licenses/bubblewrap-COPYING", licenses["bwrap-source"]["COPYING"], 0o644),
          ("licenses/libcap-License", licenses["libcap"]["License"], 0o644),
          ("build/source-record.json", _json(provenance), 0o644)))
        candidate = {**provenance, "status": "built-not-executed", "archive": "pi-bwrap-linux-x86_64.tar.gz",
          "archive_sha256": hashlib.sha256(packed).hexdigest(), "binary_sha256": hashlib.sha256(raw).hexdigest()}
        serialized = _json(candidate)
        destination.write_new(candidate["archive"], packed)
        destination.write_new("candidate.json", serialized)
        return candidate
  except Exception:
    raise ConfigError("pi-bwrap-build-failed") from None

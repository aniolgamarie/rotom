"""显式 Node 资产接线；仅管理器的暂存 Tree 可调用安装。"""

import hashlib
import re
import tempfile
from dataclasses import dataclass
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .pi_node_archive import NodeArchiveSelection, capture_node_archive_selection, select_node_archive
from .process import DependencyError


MAX_ARCHIVE = 128 * 1024 * 1024
_FIELDS = {"kind", "format", "url", "platform", "archive_digest", "archive_member", "target", "license_files", "node_archive"}


@dataclass(frozen=True, slots=True)
class NodeAssetReference:
  selection: NodeArchiveSelection
  url: str
  vendor_path: str | None
  license_file: str


def _invalid():
  try:
    raise DependencyError("Pi Node资产无效")
  except DependencyError as error:
    error.__context__ = None
    error.__cause__ = None
    raise


def _boundary(operation, *args):
  failed = False
  try:
    result = operation(*args)
  except Exception:
    failed = True
  if failed: _invalid()
  return result


def _snapshot(value):
  if type(value) is not dict: _invalid()
  items = tuple(value.items())
  if any(type(key) is not str for key, _ in items): _invalid()
  return dict(items)


def _capture(source):
  data = _snapshot(source)
  if set(data) not in (_FIELDS, _FIELDS | {"vendor_path"}): _invalid()
  for name in ("kind", "format", "url", "platform", "archive_digest", "archive_member", "target"):
    if type(data[name]) is not str: _invalid()
  selection = capture_node_archive_selection(data["node_archive"])
  root = "node-" + selection.release + "-linux-x64"
  url = "https://nodejs.org/download/release/" + selection.release + "/" + root + ".tar.gz"
  license_file = "agents/pi/build/licenses/node-" + selection.release + "/LICENSE"
  if (data["kind"] != "asset" or data["format"] != "node.tar.gz" or data["url"] != url
      or data["platform"] != selection.platform or data["archive_digest"] != selection.archive_sha256
      or data["archive_member"] != root + "/bin/node" or data["target"] != "bin/pi-node"): _invalid()
  licenses = data["license_files"]
  if type(licenses) is not list: _invalid()
  licenses = tuple(licenses)
  if len(licenses) != 1 or type(licenses[0]) is not str or licenses[0] != license_file: _invalid()
  vendor = data.get("vendor_path")
  if "vendor_path" in data and (type(vendor) is not str or vendor != "vendor/" + root + "-" + selection.archive_sha256 + ".tar.gz"): _invalid()
  return NodeAssetReference(selection, url, vendor, license_file)


def capture_node_asset(source):
  return _boundary(_capture, source)


def _toolchain(source, toolchains):
  reference = _capture(source)
  tools = _snapshot(toolchains)
  if set(tools) != {"node", "npm", "bun"} or any(type(value) is not str for value in tools.values()): _invalid()
  if tools["node"] != reference.selection.release: _invalid()
  return reference


def validate_node_asset_toolchain(source, toolchains):
  return _boundary(_toolchain, source, toolchains)


def _reference(reference):
  if type(reference) is not NodeAssetReference: _invalid()
  selection = reference.selection
  if type(selection) is not NodeArchiveSelection: _invalid()
  metadata = {name: getattr(selection, name) for name in ("schema", "release", "platform", "archive_sha256", "binary_sha256", "license_sha256")}
  selection = capture_node_archive_selection(metadata)
  root = "node-" + selection.release + "-linux-x64"
  data = {"kind": "asset", "format": "node.tar.gz", "url": reference.url, "platform": selection.platform,
    "archive_digest": selection.archive_sha256, "archive_member": root + "/bin/node", "target": "bin/pi-node",
    "license_files": [reference.license_file], "node_archive": metadata}
  if reference.vendor_path is not None: data["vendor_path"] = reference.vendor_path
  return _capture(data)


class NodeHTTPSRedirects(HTTPRedirectHandler):
  def __init__(self, expected_url):
    super().__init__()
    if type(expected_url) is not str: _invalid()
    self.expected_url = expected_url

  def redirect_request(self, req, fp, code, msg, headers, newurl):
    if type(newurl) is not str or newurl != self.expected_url: _invalid()
    return _boundary(super().redirect_request, req, fp, code, msg, headers, newurl)


def _open(reference):
  reference = _reference(reference)
  opener = build_opener(ProxyHandler({}), NodeHTTPSRedirects(reference.url))
  return opener.open(Request(reference.url, headers={"User-Agent": "agentcfg"}), timeout=60)


def open_node_download(reference):
  return _boundary(_open, reference)


def _copy_archive(stream, output):
  checksum, size = hashlib.sha256(), 0
  while True:
    chunk = stream.read(1024 * 1024)
    if type(chunk) is not bytes or len(chunk) > 1024 * 1024: _invalid()
    if not chunk: break
    size += len(chunk)
    if size > MAX_ARCHIVE: _invalid()
    output.write(chunk)
    checksum.update(chunk)
  return checksum.hexdigest()


def _install(checkout, target, source_id, source, toolchains, layout):
  if type(source_id) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", source_id): _invalid()
  reference = _toolchain(source, toolchains)
  with tempfile.TemporaryFile(dir=target.root) as archive:
    if reference.vendor_path is not None:
      with checkout.open_read(layout.lock_directory + "/" + reference.vendor_path, max_bytes=MAX_ARCHIVE) as (stream, _):
        checksum = _copy_archive(stream, archive)
    else:
      with open_node_download(reference) as stream:
        checksum = _copy_archive(stream, archive)
    if checksum != reference.selection.archive_sha256: _invalid()
    archive.seek(0)
    files = select_node_archive(archive.read(MAX_ARCHIVE + 1), reference.selection)
  license_record = checkout.read(reference.license_file, max_bytes=1024 * 1024)
  if license_record is None or type(license_record[0]) is not bytes or license_record[0] != files.license: _invalid()
  license_target = "licenses/" + source_id + "/0-LICENSE"
  if target.read("bin/pi-node", max_bytes=1) is not None or target.read(license_target, max_bytes=1) is not None: _invalid()
  target.replace("bin/pi-node", files.binary, mode=0o700, expected=None)
  target.write_new(license_target, files.license)


def install_node_asset(checkout, target, source_id, source, toolchains, layout):
  return _boundary(_install, checkout, target, source_id, source, toolchains, layout)

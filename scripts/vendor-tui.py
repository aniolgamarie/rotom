#!/usr/bin/env python3
"""将发布包中 bundled workspace 引用变为同包内已核实版本，不改运行代码。"""

import argparse
import base64
import difflib
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def build(archive, metadata, output):
  content = archive.read_bytes()
  meta = json.loads(metadata.read_text())
  if "sha512-" + base64.b64encode(hashlib.sha512(content).digest()).decode() != meta["dist"]["integrity"]:
    raise ValueError("published archive integrity mismatch")
  entries, versions = {}, {}
  with tarfile.open(fileobj=io.BytesIO(content)) as source:
    for member in source.getmembers():
      path = Path(member.name)
      if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
        raise ValueError("unsafe archive")
      if member.isfile():
        data = source.extractfile(member).read()
        entries[member.name] = (data, member.mode)
        if member.name.endswith("/package.json"):
          document = json.loads(data)
          if "name" in document and "version" in document:
            versions.setdefault(document["name"], set()).add(document["version"])
  changes, patches = {}, []
  for name, (data, mode) in list(entries.items()):
    if not name.endswith("/package.json"):
      continue
    doc = json.loads(data)
    replaced = False
    for section in ("dependencies", "optionalDependencies", "peerDependencies", "devDependencies"):
      for key, value in doc.get(section, {}).items():
        if value.startswith("workspace:"):
          if len(versions.get(key, ())) != 1:
            raise ValueError("ambiguous bundled workspace identity")
          doc[section][key] = next(iter(versions[key]))
          replaced = True
    if replaced:
      after = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode()
      entries[name] = (after, mode)
      changes[name] = {"before": hashlib.sha256(data).hexdigest(), "after": hashlib.sha256(after).hexdigest()}
      patches.extend(difflib.unified_diff(data.decode().splitlines(True), after.decode().splitlines(True), "a/" + name, "b/" + name))
  if not changes:
    raise ValueError("expected workspace references absent")
  provenance = {"commit": "78081cebde1ee1b47a561ef57c04f128c5623476", "version": meta["version"],
    "source_integrity": meta["dist"]["integrity"], "changes": changes,
    "runtime_code": "unchanged", "reason": "npm frozen installation rejects bundled workspace:* metadata"}
  entries["package/agentcfg-provenance.json"] = ((json.dumps(provenance, indent=2) + "\n").encode(), 0o644)
  buf = io.BytesIO()
  with tarfile.open(fileobj=buf, mode="w") as archive_out:
    for name, (data, mode) in sorted(entries.items()):
      info = tarfile.TarInfo(name)
      info.mode, info.size, info.mtime = mode & 0o777, len(data), 0
      archive_out.addfile(info, io.BytesIO(data))
  output.parent.mkdir(parents=True, exist_ok=True)
  output.write_bytes(gzip.compress(buf.getvalue(), mtime=0))
  (output.parent / "tui-bundled-metadata.patch").write_text("".join(patches))
  (output.parent / "tui-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("archive", type=Path)
  parser.add_argument("metadata", type=Path)
  parser.add_argument("output", type=Path)
  args = parser.parse_args()
  build(args.archive, args.metadata, args.output)

#!/usr/bin/env python3
"""固定源码归档 -> 可审查隔离补丁 -> 确定性本地 npm tarball；不执行第三方代码。"""

import argparse
import difflib
import gzip
import hashlib
import io
import json
import re
from pathlib import Path
import tarfile


COMMIT = "793978ee3b72a1c81d8b769b269ac2fa3bc90654"


def build(archive, output):
  data = archive.read_bytes()
  files = {}
  with tarfile.open(fileobj=io.BytesIO(data)) as source:
    for member in source.getmembers():
      name = Path(member.name)
      if name.is_absolute() or ".." in name.parts or member.issym() or member.islnk():
        raise ValueError("unsafe source archive")
      if name.parts[0] != "dsh-plugin-oauth-subs-" + COMMIT:
        raise ValueError("source commit prefix mismatch")
      if member.isfile():
        files[Path(*name.parts[1:]).as_posix()] = source.extractfile(member).read()
  patch = []
  hashes = {}
  for name in ("lib/oauth/controller.js", "src/oauth/controller.ts"):
    before = files[name].decode()
    after = before
    for provider in ("cursor", "ollama", "kimi", "copilot"):
      old = f"this.{provider}AutoImport = {provider}AutoImport ?? !process.env.NODE_TEST_CONTEXT"
      if after.count(old) != 1:
        raise ValueError("auto-import source changed")
      after = after.replace(old, f"this.{provider}AutoImport = false")
    for signature in ("async checkUpdate(payload = {}) {", "async checkDshUpdate(payload = {}) {"):
      if after.count(signature) != 1:
        raise ValueError("update source changed")
      after = after.replace(signature, signature + '\n    if (payload.apply) throw new Error("Updates are managed by agentcfg lock/sync");')
    signature = "startAutoUpdateWatch({ intervalMs = AUTO_UPDATE_INTERVAL_MS } = {}) {"
    if after.count(signature) != 1:
      raise ValueError("watch source changed")
    after = after.replace(signature, signature + "\n    return; // agentcfg: no background updater")
    files[name] = after.encode()
    hashes[name] = {"before": hashlib.sha256(before.encode()).hexdigest(), "after": hashlib.sha256(files[name]).hexdigest()}
    patch.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "a/"+name, "b/"+name))
  for name in ("lib/index.js", "src/index.ts"):
    before = files[name].decode()
    old = "stampDshHostVersion(pluginClientJsPath(), localDshInfo().version)"
    if before.count(old) != 1:
      raise ValueError("runtime package stamp changed")
    after = before.replace(old, "void 0 /* agentcfg: immutable installed package */")
    registration = '''
    // agentcfg: terminal-native login; no credential import, no auxiliary web server.
    ctx.inject(['commands'], (scope) => {
      scope.effect(() => scope.commands.register({
        name: 'cursor-login',
        description: 'Sign in to Cursor subscription in this isolated DSH instance',
        handler: async (invocation) => {
          try {
            if (invocation.rawInput.trim() === 'cancel') {
              await controller.cancel('cursor');
              return { kind: 'success', text: 'Cursor login cancelled.' };
            }
            if (invocation.rawInput.trim()) {
              return { kind: 'error', text: 'Usage: /cursor-login [cancel]' };
            }
            if (!proxy) return { kind: 'error', text: 'Cursor proxy is not ready.' };
            const result = await controller.login('cursor', {});
            return { kind: 'success', text: 'Open this URL to finish Cursor login:\\n' + result.authorizeUrl + '\\nAfter login, select oauth-cursor in /model.' };
          } catch {
            return { kind: 'error', text: 'Cursor login could not start; cancel an existing attempt and retry.' };
          }
        },
      }), 'agentcfg Cursor terminal login');
    });
'''
    after, count = re.subn(r"(?m)^([ \t]+)registerRpc\(ctx, controller\);?[ \t]*$",
                          lambda match: match[0] + ";" + registration, after)
    if count != 1:
      raise ValueError("RPC registration source changed")
    files[name] = after.encode()
    hashes[name] = {"before": hashlib.sha256(before.encode()).hexdigest(), "after": hashlib.sha256(files[name]).hexdigest()}
    patch.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "a/"+name, "b/"+name))
  manifest = json.loads(files["package.json"])
  manifest["version"] = "0.0.88-agentcfg.1"
  files["package.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
  provenance = {"commit": COMMIT, "source_sha256": hashlib.sha256(data).hexdigest(),
                "version": manifest["version"], "patches": hashes,
                "build": "upstream checked-in lib with equivalent source/lib isolation patches and native cursor-login command; no compilation"}
  files["agentcfg-provenance.json"] = (json.dumps(provenance, indent=2) + "\n").encode()
  buffer = io.BytesIO()
  with tarfile.open(fileobj=buffer, mode="w") as tar:
    for name, content in sorted(files.items()):
      if not (name.startswith(("lib/", "src/")) or name in ("package.json", "LICENSE", "README.md", "README.zh.md", "cordis.patch.yml", "agentcfg-provenance.json")):
        continue
      info = tarfile.TarInfo("package/" + name)
      info.size, info.mode, info.mtime = len(content), 0o644, 0
      tar.addfile(info, io.BytesIO(content))
  output.parent.mkdir(parents=True, exist_ok=True)
  output.write_bytes(gzip.compress(buffer.getvalue(), mtime=0))
  (output.parent / "cursor-managed.patch").write_text("".join(patch))
  (output.parent / "cursor-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("archive", type=Path)
  parser.add_argument("output", type=Path)
  args = parser.parse_args()
  build(args.archive, args.output)

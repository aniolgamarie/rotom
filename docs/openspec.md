# Optional OpenSpec integration for Pi projects

Pi's optional `openspec` capability uses locked OpenSpec 1.11.0 and twelve complete skills, separate from any global development CLI used to maintain rotom. Select `openspec` explicitly in the Pi profile's `plugins`, retaining other needed plugins when replacing the array. See [Pi usage](pi.md). DSH provides no OpenSpec initialization capability or automatic injection; removing it does not authorize project cleanup.

```sh
./agentcfg --local /private/pi-local.toml --profile pi-default sync
./agentcfg --local /private/pi-local.toml --profile pi-default project init openspec --path /path/to/worktree
```

Initialization runs upstream `init --tools agents --profile core --no-animation` in a private staging directory, then checks same-named target files, the manifest, and pre-write changes in the selected project. It does not scan other projects. Apply/sync do not initialize projects automatically. Repeating with identical content avoids unnecessary writes; modified same-named files conflict.

The supported upstream `agents` integration generates `.agents/skills/openspec-*` and `.agents/skills/.openspec-target`. Pi stores the manager's `.agentcfg-openspec.json` digest manifest under protected Git metadata `agentcfg-project/`, without account data or local keys. Generated skills are not proof of loading: project discovery and permission policy still require explicit selection.

Initialize at a verifiable Git worktree root, including linked worktrees with a `.git` file. A subdirectory of an existing repository fails before writes. The manager does not run git init for projects.

Generation and target writes are not an atomic directory-wide transaction. On failure, existing outputs remain for inspection. Upgrades do not automatically delete old project files. In particular, project-owned `openspec/`, `.specify/`, `specs/`, and `.agents/skills/` must never be removed merely because their directory names resemble integration output.

Stale locks, unselected capabilities, and missing CLI entries fail explicitly without global OpenSpec fallback or unversioned downloads. The Pi backend checks selection, runtime, and the locked 1.11.0 entry before invoking it. DSH rejects this capability. Initial-load/repeat-init evidence must match the selected Pi profile and current lock; historical DSH evidence or installation alone is insufficient. See [testing](testing.md) and [known issues](known-issues.md).

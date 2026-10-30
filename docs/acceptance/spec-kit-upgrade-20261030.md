# Spec Kit 1.2.5 upgrade

Date: 2026-10-30. Scope: Specify CLI and this repository's installed Spec Kit tooling.

## Source and scope

The starting CLI and project integration were `1.0.6`. The installed integration was
Codex in skills mode, using Bash scripts and the `-` invocation separator.
The official stable target is [Spec Kit v1.2.5](https://github.com/github/spec-kit/releases/tag/v1.2.5).

The existing uv-tool Git installation channel was retained. The exact CLI upgrade was:

```sh
uv tool install --force --index-url https://pypi.org/simple \
  --from git+https://github.com/github/spec-kit.git@v1.2.5 specify-cli
```

The installer exited `0`. Installed distribution metadata reports `specify-cli==1.2.5`,
requested revision `v1.2.5`, and source commit
`4572a67fe0e72a6837e2d7bb0fda875bc41482e5` from the official GitHub repository.
`specify --help` exited `0` and exposed the integration and self-management commands.

Project files use the official [manifest-aware upgrade path](https://github.com/github/spec-kit/blob/v1.2.5/docs/upgrade.md).
No force-refresh or broad reinitialization was used. Global CLI dependencies remain in the
uv tool environment; this operation does not introduce a new managed agent runtime lock.

## Preservation checks

- Before the project upgrade, all 22 manifest-owned files matched their previous recorded hashes:
  10 Codex skills and 12 shared scripts, templates, and ignore metadata.
- The existing constitution and 142 existing specification files were inventoried before editing.
  Their final preservation checks are recorded below.
- The primary checkout's pre-existing Pi lock/package changes are outside this upgrade.
- No extension was installed, so there was no extension update to perform.

## Project upgrade and validation

`specify integration upgrade codex` exited `0` without `--force`. The final diff changes
12 existing managed files: three skills, four Bash scripts, and five metadata/ignore files.
No managed file was added or removed. All 22 managed files and their manifest hashes match
a fresh official 1.2.5 Codex skills/Bash rendering byte for byte.

`specify integration status` exited `0`, with zero modified, missing, or invalid managed files.
`specify workflow update speckit` exited `0` and correctly skipped the bundled, non-catalog
workflow. Its version remains `1.0.1`, byte-identical to the workflow bundled with CLI 1.2.5;
it is not meant to share the CLI's version number.

The isolated reference was created with the current CLI syntax:

```sh
specify init <temporary-reference> --integration codex \
  --integration-options=--skills --script sh --ignore-agent-tools --non-interactive
```

The initialization exited `0`. An initial attempt with the obsolete `--no-git` option was
rejected; the accepted invocation above follows 1.2.5's public options. No agent was started.

The isolated verification script completed **42 assertions** with exit `0`, covering:

- All managed file/hash comparisons and the bundled workflow.
- Syntax checks for all six Bash scripts.
- Fictional feature creation, side-effect-free dry runs, plan and task-template composition.
- Existing plan preservation and refusal of empty plans, empty/missing templates, or an
  invalid explicitly selected project.
- Refusal to overwrite a modified managed skill without force, and preservation of unknown
  custom skill files.
- Unchanged constitution and all 142 pre-existing specification files.

Two additional dry-run scenarios exercised the changed Unicode name handling, with exit `0`
for each: a Chinese short name produced valid UTF-8 JSON, and a long multibyte name was
truncated to 244 bytes without breaking UTF-8. Neither scenario changed feature state.

The worktree-local ignored feature pointer selects `specs/009-dsh-permissions-experience`.
The paths-only prerequisite query exited `0`. That check resolves context only; it does not
claim that formal permission feature specifications, plans, or tasks already exist.

The final managed hashes were rechecked against the verified candidate. Final whitespace
and public-content checks apply before committing. Full-repository product tests and real
DSH/agent startup were not run for this tooling-only change.

The upstream `speckit-taskstoissues` skill now carries its official deprecation notice.
The suggested replacement GitHub extension was not installed automatically.

## Permission-design worktree

The user requested a retained worktree for future DSH permission and approval changes.
Its branch is `009-dsh-permissions-experience`, created from
`6bef81c301c901e5aef82c8422918540fdeaca1c`; its location relative to the primary checkout is
`.cache/worktrees/dsh-permissions-experience`.

The DSH permission design is a separate workstream. The Spec Kit tooling upgrade can be
accepted independently; it does not establish that any new permission plugin is implemented,
installed, or enabled. The design worktree is retained at the user's request.

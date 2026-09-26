# OMP resources

`prompts/rotom-review.md` is an original rotom resource under the repository MIT license.

`themes/rotom-dark.json` is the complete OMP titanium theme with only its display name and schema reference changed.
`schemas/omp-theme.schema.json` in the repository is a formatting-only copy of the complete upstream theme schema.
Both are from can1357/oh-my-pi commit `62bc57be1b03ef0802a33cf7f5f530e534527531` (v18.3.0):

- `packages/tui/src/theme/defaults/titanium.json`
- `packages/tui/src/theme/theme-schema.json`

The applicable upstream MIT license is retained at `themes/LICENSE`.
The schema itself permits color variable references; the adapter must also check that references exist and do not form cycles.
No OMP runtime or theme loader has been executed as part of this static preparation.

The kernel agents, confirmation rule, Kanagawa theme and four skill packages were imported from the user's explicitly selected native kernel/Pi-user skill configuration on 2026-09-26. No authentication, session, database or cache content is included. Local `.bak` history files are excluded. Kanagawa's redundant unsupported `colors.link` equals `colors.mdLink` and was removed; all supported colors are preserved. Codex-delegate's runner example, project-path examples and bundled tests were made portable. Its machine-specific proxy was replaced with direct connection by default and an explicit credential-free child-only override; receipts record only the mode. Synthetic credential test strings were renamed to explicit SYNTHETIC sentinels. Agent Markdown trailing whitespace was normalized. Existing package notices and script execution bits are retained.

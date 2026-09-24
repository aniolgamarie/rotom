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

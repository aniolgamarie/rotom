Rename a symbol at a source location. Resolvable same-named bindings are preserved; verified edits apply by default. Set `apply: false` to preview the plan before changing files.

## Parameters

- `path` — source file containing the cursor.
- `line` — one-based cursor line.
- `column` — optional one-based cursor byte column for disambiguation.
- `to` — new plain identifier.
- `workspace` — expand across the project. The cursor file remains binding-aware;
  other files use name matching where binding resolution is unavailable.
- `apply` — defaults to `true`; set `false` to return only the verified plan.

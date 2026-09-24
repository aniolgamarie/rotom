Find references or usages of an identifier by name or cursor binding. Results include enclosing symbols and line hashes usable as `LINE:HASH` anchors. Without cursor scope, results are identifier-name matches; with scope, they follow one binding and exclude shadows. Use text search for literal occurrences in strings or comments, and use this tool before renaming or deleting a symbol.

## Parameters

- `name` — identifier to find; required unless `scope` is set with `line`.
- `path` — file or directory; defaults to the current directory.
- `language` — language override for ambiguous, extensionless, or generated source.
- `scope` — restrict results to the binding at `line` / `column` in one file;
  requires `line`. `name` is optional when scoped.
- `line` — one-based cursor line used with `scope`.
- `column` — optional one-based cursor byte column for disambiguation; used with
  `scope`. Cursor fields require `scope`.
- `cached` — search tracked/indexed files in a Git repository.
- `others` — search untracked files in a Git repository.
- `ignored` — include ignored untracked files; requires `others`.


In a Git work tree, directory search includes tracked/indexed and untracked
non-ignored files by default. Setting `cached` or `others` restricts the set;
`ignored` requires `others`.

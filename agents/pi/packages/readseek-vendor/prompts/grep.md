Search text or regex in files and return edit-ready `LINE:HASH` anchors. Use for identifiers, strings, configuration, errors, comments, and documentation.

## Modes

- Default: return matching lines as `path:>>LINE:HASH|content`.
- `context: N`: include N surrounding lines. Context rows use
  `path:  LINE:HASH|content`; overlapping ranges are merged.
- `summary: true`: return per-file counts only. Use this first for a broad
  search, then narrow by `path`, `glob`, or pattern.
- `scope: "symbol"`: group matches by their enclosing symbol. By default the
  full symbol is returned; `scopeContext: N` clips each match to ±N lines inside
  it, and `0` returns only matching lines. `summary` ignores symbol scope.

## Parameters

- `pattern` — regular expression by default; set `literal: true` for exact text.
- `path` — file or directory; defaults to the current directory.
- `glob` — file-name filter such as `*.ts` or `**/*.test.ts`.
- `ignoreCase` — case-insensitive search.
- `context` — surrounding lines in normal mode.
- `limit` — maximum matches; defaults to 100.
- `summary` — return counts without anchors.
- `scope` — only `"symbol"` is supported.
- `scopeContext` — non-negative context inside symbol scope.

If `limit` or the display budget truncates output, start with `summary`, narrow
the file set and pattern, then request context or symbol blocks.

Edit existing text files with fresh `LINE:HASH` anchors. Read or search the file first when no fresh anchors are available. Each `edits[]` item must use exactly one nested object: `{"set_line":{"anchor":"LINE:HASH","new_text":"..."}}`, `{"replace_lines":{"start_anchor":"LINE:HASH","end_anchor":"LINE:HASH","new_text":"..."}}`, `{"insert_after":{"anchor":"LINE:HASH","new_text":"..."}}`, `{"replace_symbol":{"symbol":"name","new_body":"..."}}`, or `{"replace":{"old_text":"...","new_text":"..."}}`.

Anchors come from `readSeek_digest`, `readSeek_grep`, `readSeek_search`,
`readSeek_refs`, `readSeek_def`, or `readSeek_write`.

## Variants

| Variant          | Use                                              | Required anchor               |
| ---------------- | ------------------------------------------------ | ----------------------------- |
| `set_line`       | Replace or delete one line                       | `anchor`                      |
| `replace_lines`  | Replace or delete one contiguous range           | `start_anchor`, `end_anchor`  |
| `insert_after`   | Insert after one line                            | `anchor`                      |
| `replace_symbol` | Replace one mapped symbol                        | `symbol` instead of an anchor |
| `replace`        | Replace exact text; one match unless `all: true` | None                          |

Use `new_text: ""` to delete lines and `new_text: "\n"` for a blank line.
Prefer anchored variants. Use `replace_symbol` for a whole symbol and `replace`
only when anchors are impractical.

Each `edits[]` item contains exactly one variant. `new_text` and `new_body` are
plain file content, not a diff or hashline output.

```json
{
  "path": "src/foo.ts",
  "edits": [
    { "set_line": { "anchor": "42:ab1cde", "new_text": "const x = 2;" } },
    {
      "replace_lines": {
        "start_anchor": "50:c3d4e5",
        "end_anchor": "55:e4f5a6",
        "new_text": "const y = 3;\nreturn y;"
      }
    },
    { "insert_after": { "anchor": "60:f5a6b7", "new_text": "// TODO\n" } }
  ]
}
```

## Exact and symbol replacement

`replace` requires exact text. It fails when the text is absent or appears more
than once unless `all: true` is set.

`replace_symbol` accepts `Name`, a qualified name such as `Class.method`, or
`Name@<line>` in a mappable source file. `new_body` must be non-empty and
unindented. Do not overlap a symbol replacement with anchored edits.

## Stale anchors and validation

A stale-anchor response reports the current hash for the requested line. Read or
search again before retrying.

All edits validate before writing; a hard failure writes nothing. Anchored edits
run bottom-up. `no-op` means no content changed. For languages with a tree-sitter
parser, `readseek.syntaxValidation` controls newly introduced parse errors:
`warn` (default), `block`, or `off`.

Set `postEditVerify: true` to read back the file and compare persisted content,
including its BOM and line endings. Verification returns a compact anchored
diff, unified patch, and structured `details.diffData`.

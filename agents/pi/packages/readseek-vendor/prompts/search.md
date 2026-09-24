Search code by AST structure using ast-grep-style patterns. Results include line hashes usable as `LINE:HASH` anchors. Use `readSeek_grep` for identifiers, strings, comments, configuration, documentation, or other plain text and regex.

## Parameters

- `pattern` — AST pattern to match.
- `path` — file or directory; defaults to the current directory.
- `language` — language override for ambiguous, extensionless, generated, or
  JSX-like source.
- `cached` — search tracked/indexed files in a Git repository.
- `others` — search untracked files in a Git repository.
- `ignored` — include ignored untracked files; requires `others`.

## Pattern syntax

- `$NAME` matches one AST node.
- `$_` matches one node without capturing a reusable value.
- `$$$ARGS` matches zero or more sibling nodes, such as arguments, statements,
  object fields, or JSX children.
- Reusing a metavariable requires every occurrence to match the same source text.

Patterns are code, not text. Formatting is mostly ignored, but syntax and
required punctuation must be valid for the selected language.

```text
console.log($$$ARGS)
import $NAME from '$SOURCE'
export function $NAME($$$PARAMS) { $$$BODY }
$OBJ.$METHOD($$$ARGS)
<$TAG $$$ATTRS>$$$CHILDREN</$TAG>
if ($COND) { $$$BODY }
```

In a Git work tree, directory search includes tracked/indexed and untracked
non-ignored files by default. Setting `cached` or `others` restricts the set;
`ignored` requires `others`.

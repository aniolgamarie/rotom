Go to a symbol definition or declaration by name. Accepts qualified or unqualified names; use this instead of text search for functions, methods, classes, types, and other declarations.

## Parameters

- `name` — qualified or unqualified symbol name.
- `path` — file or directory; defaults to the current directory.
- `language` — language override when detection is ambiguous.
- `cached`, `others`, `ignored` — Git file selection; `ignored` requires
  `others`.

After `readSeek_digest` with `select: "identity"`, use
`identity.identifier.text` for the token under the cursor. Use
`identity.symbol.qualified_name` only when intentionally navigating to the
enclosing declaration.

Digest source content and images into the native CLI envelope. Returns `metadata` plus requested facets unchanged from `readseek digest`.

Use this for anchored content, diagnostics, cursor identity, or a shallow structural
map. Prefer `def`, `refs`, or `search` when the question targets a symbol.

## Parameters

- `path` — file path.
- `select` — facets: `metadata`, `content`, `map`, `diagnostics`, `identity`.
  Accepts one facet, an array, or a comma-separated string. Default `content`.
- `at` — location: `line:N[:COLUMN]`, `hash:HASH[:COLUMN]`, or `symbol:NAME`.
- `end` — last line to include (with content).
- `limit` — maximum lines to include (with content).
- `depth` — maximum structural depth for `map`; agent tools default to `1`.
- `language` — language override when detection is ambiguous.
- `visionMode` — standalone image mode: `none`, `all`, `ocr`, `caption`, or
  `objects`.
- `visionLevel` — vision inference level: `low` (default), `medium`, or `high`;
  requires `visionMode`.

## Facets

| select         | Purpose                                              |
| -------------- | ---------------------------------------------------- |
| `metadata`     | File kind, language, and engine                      |
| `content`      | Anchored text or prepared/analyzed image payload     |
| `map`          | Structural outline; start shallow and deepen as needed |
| `diagnostics`  | Parser errors and missing syntax nodes               |
| `identity`     | Token and enclosing symbol at `at`                   |

Combine facets with a comma or array, e.g. `map,diagnostics` or
`["identity"]` with `at: "line:12:4"`.

## Output

Text content is the native JSON envelope. `details.readSeekValue.envelope`
holds the same object. `metadata` is always present; other keys appear only
when selected.

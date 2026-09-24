# pi-readseek

Pi extension for anchored file operations, structural search, symbol navigation,
and document inspection.

## Install

```sh
pi install npm:pi-readseek
```

The extension uses the native binary supplied by `@jarkkojs/readseek-api`. Set
`READSEEK_BINARY` to an absolute executable path to override it.

## Tools

`readSeek_edit`, `readSeek_write`, `readSeek_grep`, `readSeek_search`,
`readSeek_def`, `readSeek_refs`, `readSeek_rename`, `readSeek_digest`, and
`readSeek_view`.

## Settings

Add `readseek` to `~/.pi/agent/settings.json` or `.pi/settings.json`:

```json
{
  "readseek": {
    "overrideTools": [],
    "imageMode": "auto",
    "syntaxValidation": "warn",
    "timeoutMs": 120000,
    "grep": { "maxLines": 2000, "maxBytes": 51200 },
    "display": {
      "grep": "compact",
      "edit": "expanded",
      "write": "expanded"
    }
  }
}
```

`overrideTools` accepts `read`, `edit`, `write`, and `grep`. `imageMode` is
`auto`, `on`, or `off`; `syntaxValidation` is `warn`, `block`, or `off`.

## Development

```sh
npm install
npm test
npm run typecheck
```


## Licensing

`pi-readseek` is licensed under the Apache 2.0 license. See [LICENSE](LICENSE)
for more information.


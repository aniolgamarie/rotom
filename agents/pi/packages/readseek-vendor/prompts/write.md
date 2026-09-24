Create or replace a complete text file and return `LINE:HASH` anchors. Use anchored edits for small changes to an existing file.

Existing files are replaced without confirmation. Binary-looking content is
rejected before writing.

## Parameters

- `path` — file path.
- `content` — complete file content.

## Output

Text output uses `LINE:HASH|content` and is capped at {{DEFAULT_MAX_LINES}} lines
or {{DEFAULT_MAX_BYTES}}. Complete anchors remain in `readSeekValue`. Results
also include a compact diff and structured `details.diffData`.

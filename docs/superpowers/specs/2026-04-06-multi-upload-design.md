# Multi-File Upload Design

## Context

Replace the single-file upload UI in `app/templates/index.html` with one that
accepts multiple files and entire folders (including subfolders), uploads each
file sequentially to the existing `POST /api/upload` endpoint, and shows a
live per-file queue with status badges.

## Decisions

- **Per-file sequential uploads** — backend unchanged, each file is one POST
- **Two inputs** — `#file-input` (`multiple`) for files, `#folder-input`
  (`webkitdirectory`) for folders; browser handles recursive subfolder traversal
- **Queue replaces result area** — `#upload-result` shows `.queue-row` elements
  with filename + badge: pending → uploading → done / duplicate / error
- **MIME filtering** — `collectFiles()` filters out non-audio/video files that
  may appear inside a folder (e.g. `.DS_Store`, `.txt`)
- **HTMX removed from form** — all uploads go through plain `fetch()`; HTMX
  kept only for status-panel/entries-panel auto-refresh

## Badge States

| Badge class       | Meaning                        |
|-------------------|-------------------------------|
| `badge-pending`   | In queue, not yet started      |
| `badge-uploading` | In-flight fetch                |
| `badge-done`      | HTTP 200                       |
| `badge-duplicate` | HTTP 409 (existing file)       |
| `badge-failed`    | Any other HTTP error / network |

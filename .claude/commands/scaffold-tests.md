You are implementing the Phase 1 test suite for the Saraswati personal knowledge base (FastAPI).

## Step 1 — Read source files

Read all of these before writing any code:
- `ROADMAP.md` — authoritative test plan under "Phase 1 — Tests"
- `CLAUDE.md` — project conventions and architecture
- `app/models.py` — FileRecord and Entry SQLModel definitions
- `app/database.py` — module-level `engine` and `get_session()`
- `app/config.py` — Settings singleton
- `app/routes/upload.py` — POST /api/upload
- `app/routes/status.py` — GET /api/status, GET /api/status/table
- `app/routes/process.py` — POST /api/process
- `app/services/cleanup.py` — delete_expired_files()
- `app/services/nextcloud.py` — upload_file()
- `main.py` — FastAPI app factory and lifespan

## Conventions (non-negotiable)

- Test runner: `pytest` with `pytest-asyncio`
- HTTP client: `httpx.AsyncClient` with `transport=ASGITransport(app=app)`
- Database: real SQLite in `tmp_path` — **no mocks of business logic**
- `app/database.py` creates a module-level `engine` at import time pointing at the real DB. Tests must override it: patch `app.database.engine` with a tmp engine, then call `SQLModel.metadata.create_all(tmp_engine)` to create tables.
- Also patch `app.config.settings.input_dir` to a `tmp_path` subdirectory so uploads don't land in the real `input/` folder.
- All files go in `tests/`; create `tests/__init__.py`.

## Required files and test cases

### `tests/conftest.py`

Provide an async `app_client` fixture (scope=`function`) that:
1. Creates `tmp_path / "db" / "test.db"` and a SQLite engine for it
2. Patches `app.database.engine` with the tmp engine
3. Creates `tmp_path / "input"` and patches `app.config.settings.input_dir` to it
4. Calls `SQLModel.metadata.create_all(tmp_engine)` (import `app.models` first so metadata is populated)
5. Yields `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`
6. Tears down (tmp dirs cleaned automatically by pytest)

Provide a `sample_audio` fixture that returns 1 KB of pseudo-random bytes (use `b"FAKE_AUDIO" * 100` — the upload route does not validate audio format).

Mark the module with `pytestmark = pytest.mark.anyio`.

### `tests/test_upload.py`

- `test_upload_valid` — POST multipart file, assert HTTP 200, response is valid FileRecord JSON with `status == "pending"`, `sha256` matches `hashlib.sha256(bytes).hexdigest()`, `filename` equals the sent name
- `test_upload_duplicate` — POST the same bytes twice; assert second response is HTTP 409, `detail["existing"]["id"]` equals the first record's id
- `test_upload_path_traversal` — POST with filename `../../evil.mp3`; assert response `filename` field equals `evil.mp3` (basename only, no path separators)
- `test_upload_no_filename` — POST with filename `""` (empty string); assert HTTP 200 and `filename` in response equals `"upload"` (the fallback in `upload.py`)

### `tests/test_status.py`

- `test_status_empty` — fresh DB, GET /api/status returns HTTP 200 and `[]`
- `test_status_after_upload` — upload one file, GET /api/status, assert the record appears with correct `filename`
- `test_status_pagination` — upload 5 different files (different bytes each), GET /api/status?limit=2&offset=0 returns 2 items, GET /api/status?limit=2&offset=4 returns 1 item
- `test_status_table_html` — upload one file, GET /api/status/table, assert HTTP 200, Content-Type contains `text/html`, body contains the filename string

### `tests/test_process.py`

- `test_process_trigger` — POST /api/process, assert HTTP 200, `response.json()["status"] == "triggered"`

### `tests/test_cleanup.py`

Call `delete_expired_files()` directly (import from `app.services.cleanup`). Build FileRecord rows directly in the tmp DB session rather than via HTTP. Use `monkeypatch` to redirect `app.database.engine` (already done by `app_client` fixture if reused, or replicate the engine patch if testing without HTTP).

- `test_cleanup_ignores_pending` — FileRecord with `status="pending"`, `delete_after` 1 day ago, `nextcloud_path="remote/path"`, real file on disk; run cleanup; file still exists
- `test_cleanup_ignores_no_nextcloud_path` — `status="done"`, `delete_after` past, `nextcloud_path=None`, real file; run cleanup; file still exists
- `test_cleanup_ignores_future_delete_after` — `status="done"`, `nextcloud_path` set, `delete_after` = tomorrow; run cleanup; file still exists
- `test_cleanup_deletes_eligible_file` — `status="done"`, `nextcloud_path` set, `delete_after` past, real file on disk; run cleanup; file no longer exists on disk; DB record still present (select by id to confirm)
- `test_cleanup_missing_file_no_crash` — same eligibility as above but file is NOT on disk; run cleanup; no exception raised (exercises the `logger.warning` path)

### `tests/test_nextcloud.py`

- `test_nextcloud_skips_when_unconfigured` — patch `app.config.settings.nextcloud_url` to `""`; call `await upload_file("some/local/path", "file.mp3")`; assert return value is `""` and the function returns without raising (no network call is attempted because the early-return guard fires first)
- Add a placeholder: `@pytest.mark.skip(reason="integration: requires live Nextcloud") async def test_nextcloud_real_upload(): ...`

## Dependencies

Check `requirements.txt`. Add these if missing: `pytest`, `pytest-asyncio`, `anyio[trio]`, `httpx`.

Also create `pytest.ini` (or add `[tool.pytest.ini_options]` to `pyproject.toml` if it exists) with:
```ini
[pytest]
asyncio_mode = auto
```

## Output

Write all seven files:
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/test_upload.py`
- `tests/test_status.py`
- `tests/test_process.py`
- `tests/test_cleanup.py`
- `tests/test_nextcloud.py`

After writing, activate the venv (`source .venv/bin/activate.fish` or `.venv/bin/python -m pytest`) and run `pytest tests/ -v`. Fix any failures before declaring done.

Finally, mark the "Phase 1 test suite" checkbox in `ROADMAP.md` as `[x]`.

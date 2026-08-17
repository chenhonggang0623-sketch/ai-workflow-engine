# Task Report: Context Manager + Artifact System (Epic 3)

## Status: DONE

## Files Created

### `app/context/__init__.py`
Package init, exports `ContextManager`.

### `app/context/manager.py`
- **`ContextManager(db_session, redis_client)`** — manages execution context as shared data dict
- Redis for fast access (`ctx:{execution_id}` key, JSON serialized), PostgreSQL for persistence
- `init()` — creates context in Redis with initial data
- `get()` — reads from Redis, falls back to DB (Execution.context column), re-populates Redis
- `set_value()` / `get_value()` — dotted JSONPath navigation (`$.product_doc.title`)
- `snapshot()` — persists current Redis state to DB
- `commit()` — alias for snapshot
- `apply_input_mapping()` / `apply_output_mapping()` — transforms between context and node I/O using `InputMapping`/`OutputMapping` from `engine/types.py`

### `app/artifact/__init__.py`
Package init, exports `ArtifactManager`.

### `app/artifact/manager.py`
- **`ArtifactManager(db_session, storage_path)`** — stores artifacts on filesystem with DB tracking
- `store()` — writes content (str/bytes) to `{storage_path}/{workflow_id}/{execution_id}/{node_id}/{name}`, auto-creates directories, computes SHA256 checksum
- `get()` — fetches Artifact model from DB
- `get_content()` — reads file content from filesystem
- `list()` — filtered query (execution_id, node_id, type)
- `delete()` — removes file + DB row
- `update_status()` — sets status (draft/review/published/archived)

### `tests/test_context_manager.py` — 16 tests
### `tests/test_artifact_manager.py` — 11 tests
### `tests/conftest.py` — shared fixtures

## Pre-existing Issues Fixed (required for tests to run)
1. `app/engine/types.py:61` — `model_config` field renamed to `model_params` with `alias="model_config"` (Pydantic v2 reserved name)
2. `app/models/workflow.py:69` — `metadata` column renamed to `log_metadata` with column name `"metadata"` (SQLAlchemy reserved attribute)
3. `app/schemas/contract.py:16` — same Pydantic `model_config` fix as #1
4. `app/models/artifact.py:26` — `metadata` renamed to `extra_metadata` with column name `"metadata"`
5. Updated `app/artifact/manager.py` to use `extra_metadata` param name

## Commits
No commits — project is not a git repository.

## Test Summary
```
27 passed in 0.55s
```

## Concerns
- `get_content()` guesses read mode (text vs binary) from `mime_type` — may misdetect; could use explicit `mode` param in future
- No locking/transactions around concurrent context writes — Redis atomicity assumed sufficient for single-writer-per-execution
- `apply_input_mapping()` returns `None` for missing JSONPath values silently — caller should validate

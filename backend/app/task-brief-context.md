# Task: Implement Context Manager and Artifact System

## Context
These modules manage runtime data passing between nodes (Context) and persistent file storage (Artifact). Types are defined in `app/engine/types.py`.

## Files to create

### 1. `backend/app/context/manager.py` — ContextManager

```python
class ContextManager:
    """
    Manages execution context — shared data dict that flows between nodes.
    
    - init(execution_id, initial_data) → creates context snapshot
    - get(execution_id) → returns current context dict
    - set(execution_id, path, value) → sets value at JSONPath, e.g. "$.product_doc"
    - get_value(execution_id, path) → gets value at JSONPath
    - snapshot(execution_id) → saves context snapshot to DB
    - apply_input_mapping(execution_id, mappings: list[InputMapping]) → dict for node input
    - apply_output_mapping(execution_id, mappings: list[OutputMapping], output: dict) → updates context
    - commit(execution_id) → flush to DB

    JSONPath implementation: simple dotted path access, e.g. "product_doc.title"
    Context stored in Redis for fast access + PostgreSQL for persistence.
    """

    def __init__(self, db_session, redis_client): ...

    async def init(self, execution_id: UUID, initial_data: dict) -> None: ...
    async def get(self, execution_id: UUID) -> dict: ...
    async def set_value(self, execution_id: UUID, path: str, value) -> None: ...
    async def get_value(self, execution_id: UUID, path: str): ...
    async def snapshot(self, execution_id: UUID) -> None: ...
    async def apply_input_mapping(self, execution_id: UUID, mappings: list) -> dict: ...
    async def apply_output_mapping(self, execution_id: UUID, mappings: list, output: dict) -> None: ...
    async def commit(self, execution_id: UUID) -> None: ...
```

### 2. `backend/app/artifact/manager.py` — ArtifactManager

```python
class ArtifactManager:
    """
    Stores and retrieves execution artifacts (files, code, documents).
    
    - store(execution_id, node_id, name, content, type, metadata) → Artifact
    - get(artifact_id) → Artifact with content
    - list(execution_id, node_id, type) → list[Artifact]
    - delete(artifact_id)
    - update_status(artifact_id, status) (draft/review/published/archived)

    Content stored on filesystem (storage_path from config), metadata in PostgreSQL.
    """

    def __init__(self, db_session, storage_path: str): ...

    async def store(self, execution_id: UUID, node_id: str, name: str,
                    content: str | bytes, type: str, metadata: dict = None) -> Artifact: ...
    async def get(self, artifact_id: UUID) -> Artifact: ...
    async def get_content(self, artifact_id: UUID) -> str | bytes: ...
    async def list(self, execution_id: UUID = None, node_id: str = None,
                   type: str = None) -> list[Artifact]: ...
    async def delete(self, artifact_id: UUID) -> None: ...
    async def update_status(self, artifact_id: UUID, status: str) -> None: ...
```

## Constraints
- Storage path: `{config.storage_path}/{workflow_id}/{execution_id}/{node_id}/{name}`
- Create directories automatically
- Support both text (str) and binary (bytes) content
- Generate SHA256 checksum for stored content
- Context commits to DB should be async (use async SQLAlchemy)

## Output
- Status: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
- Report file: `backend/app/task-brief-context-report.md`
- Commits made
- Test output

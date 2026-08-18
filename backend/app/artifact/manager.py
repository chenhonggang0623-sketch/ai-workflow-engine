import hashlib
import os
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact


class ArtifactManager:
    def __init__(self, db_session: AsyncSession, storage_path: str):
        self.db = db_session
        self.storage_path = storage_path

    def _content_path(
        self, workflow_id: UUID, execution_id: UUID, node_id: str, name: str
    ) -> str:
        return os.path.join(
            self.storage_path,
            str(workflow_id),
            str(execution_id),
            node_id,
            name,
        )

    def _relative_path(
        self, workflow_id: UUID, execution_id: UUID, node_id: str, name: str
    ) -> str:
        return os.path.join(
            str(workflow_id),
            str(execution_id),
            node_id,
            name,
        )

    def _compute_checksum(self, content: str | bytes) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    async def store(
        self,
        execution_id: UUID,
        node_id: str,
        name: str,
        content: str | bytes,
        type: str,
        workflow_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> Artifact:
        if workflow_id is None:
            workflow_id = uuid4()

        abs_path = self._content_path(workflow_id, execution_id, node_id, name)
        rel_path = self._relative_path(workflow_id, execution_id, node_id, name)

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        mode = "w" if isinstance(content, str) else "wb"
        with open(abs_path, mode) as f:
            f.write(content)

        checksum = self._compute_checksum(content)
        size = len(content) if isinstance(content, bytes) else len(content.encode("utf-8"))

        artifact = Artifact(
            id=uuid4(),
            execution_id=execution_id,
            workflow_id=workflow_id,
            node_id=node_id,
            name=name,
            type=type,
            size=size,
            storage_path=rel_path,
            checksum=checksum,
            extra_metadata=metadata or {},
        )
        self.db.add(artifact)
        await self.db.flush()
        return artifact

    async def get(self, artifact_id: UUID) -> Artifact | None:
        result = await self.db.execute(
            select(Artifact).where(Artifact.id == artifact_id)
        )
        return result.scalar_one_or_none()

    async def get_content(self, artifact_id: UUID) -> str | bytes | None:
        artifact = await self.get(artifact_id)
        if artifact is None:
            return None

        abs_path = os.path.join(self.storage_path, artifact.storage_path)
        if not os.path.exists(abs_path):
            return None

        mode = "rb" if "b" in (artifact.mime_type or "") else "r"
        with open(abs_path, mode) as f:
            return f.read()

    async def list_artifacts(
        self,
        execution_id: UUID | None = None,
        node_id: str | None = None,
        type: str | None = None,
    ) -> list[Artifact]:
        query = select(Artifact)
        if execution_id is not None:
            query = query.where(Artifact.execution_id == execution_id)
        if node_id is not None:
            query = query.where(Artifact.node_id == node_id)
        if type is not None:
            query = query.where(Artifact.type == type)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def delete(self, artifact_id: UUID) -> bool:
        artifact = await self.get(artifact_id)
        if artifact is None:
            return False

        abs_path = os.path.join(self.storage_path, artifact.storage_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)

        await self.db.delete(artifact)
        await self.db.flush()
        return True

    async def update_status(self, artifact_id: UUID, status: str) -> Artifact | None:
        artifact = await self.get(artifact_id)
        if artifact is None:
            return None
        artifact.status = status
        await self.db.flush()
        return artifact

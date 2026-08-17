import os
import hashlib
import tempfile
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.artifact.manager import ArtifactManager


@pytest.fixture
def tmp_storage():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mgr(mock_db, tmp_storage):
    return ArtifactManager(mock_db, tmp_storage)


@pytest.mark.asyncio
async def test_store_text_content(mgr, mock_db, tmp_storage):
    eid, nid, name = uuid4(), "node1", "hello.txt"
    wid = uuid4()

    art = await mgr.store(
        execution_id=eid,
        node_id=nid,
        name=name,
        content="Hello World",
        type="text",
        workflow_id=wid,
    )

    assert art.name == "hello.txt"
    assert art.type == "text"
    assert art.checksum == hashlib.sha256(b"Hello World").hexdigest()
    assert art.size == 11

    fpath = os.path.join(tmp_storage, str(wid), str(eid), nid, name)
    assert os.path.exists(fpath)
    with open(fpath) as f:
        assert f.read() == "Hello World"

    assert art.storage_path == os.path.join(str(wid), str(eid), nid, name)
    mock_db.add.assert_called_once()
    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_binary_content(mgr, mock_db, tmp_storage):
    eid, nid, name = uuid4(), "tool1", "data.bin"
    wid = uuid4()
    content = b"\x00\x01\x02\xff"

    art = await mgr.store(
        execution_id=eid,
        node_id=nid,
        name=name,
        content=content,
        type="binary",
        workflow_id=wid,
    )

    assert art.size == 4
    fpath = os.path.join(tmp_storage, str(wid), str(eid), nid, name)
    with open(fpath, "rb") as f:
        assert f.read() == content


@pytest.mark.asyncio
async def test_store_auto_generates_workflow_id(mgr, mock_db):
    art = await mgr.store(
        execution_id=uuid4(),
        node_id="n1",
        name="f.txt",
        content="data",
        type="text",
    )
    assert art.workflow_id is not None


@pytest.mark.asyncio
async def test_get_returns_artifact(mgr, mock_db):
    aid = uuid4()
    art_mock = MagicMock()
    art_mock.id = aid
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=art_mock))

    result = await mgr.get(aid)
    assert result is art_mock


@pytest.mark.asyncio
async def test_get_content_text(mgr, mock_db, tmp_storage):
    aid = uuid4()
    art_mock = MagicMock()
    art_mock.storage_path = "wid/eid/n1/f.txt"
    art_mock.mime_type = "text/plain"
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=art_mock))

    os.makedirs(os.path.join(tmp_storage, "wid/eid/n1"), exist_ok=True)
    with open(os.path.join(tmp_storage, "wid/eid/n1/f.txt"), "w") as f:
        f.write("file content")

    result = await mgr.get_content(aid)
    assert result == "file content"


@pytest.mark.asyncio
async def test_get_content_missing(mgr, mock_db):
    aid = uuid4()
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=None))
    result = await mgr.get_content(aid)
    assert result is None


@pytest.mark.asyncio
async def test_list_filters(mgr, mock_db):
    eid = uuid4()
    scalars_result = MagicMock()
    scalars_result.all.return_value = ["a", "b"]
    mock_db._make_execute_result(scalars=MagicMock(return_value=scalars_result))

    result = await mgr.list(execution_id=eid, type="code")
    assert result == ["a", "b"]


@pytest.mark.asyncio
async def test_delete_removes_file_and_db(mgr, mock_db, tmp_storage):
    aid = uuid4()
    art_mock = MagicMock()
    art_mock.storage_path = "wid/eid/n1/del.txt"
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=art_mock))

    fpath = os.path.join(tmp_storage, "wid/eid/n1/del.txt")
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w") as f:
        f.write("delete me")

    result = await mgr.delete(aid)
    assert result is True
    assert not os.path.exists(fpath)
    mock_db.delete.assert_called_once_with(art_mock)
    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_missing_returns_false(mgr, mock_db):
    aid = uuid4()
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=None))

    result = await mgr.delete(aid)
    assert result is False


@pytest.mark.asyncio
async def test_update_status(mgr, mock_db):
    aid = uuid4()
    art_mock = MagicMock()
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=art_mock))

    result = await mgr.update_status(aid, "published")
    assert art_mock.status == "published"
    assert result is art_mock
    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_missing(mgr, mock_db):
    aid = uuid4()
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=None))

    result = await mgr.update_status(aid, "published")
    assert result is None

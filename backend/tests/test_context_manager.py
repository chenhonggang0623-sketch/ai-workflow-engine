import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.context.manager import ContextManager
from app.engine.types import InputMapping, OutputMapping


@pytest.fixture
def ctx(mock_db, mock_redis):
    return ContextManager(mock_db, mock_redis)


@pytest.mark.asyncio
async def test_init_stores_json_in_redis(ctx, mock_redis):
    eid = uuid4()
    await ctx.init(eid, {"foo": "bar"})
    mock_redis.set.assert_awaited_once()
    args = mock_redis.set.call_args
    assert args[0][0] == f"ctx:{eid}"
    assert json.loads(args[0][1]) == {"foo": "bar"}


@pytest.mark.asyncio
async def test_get_returns_from_redis(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({"a": 1})
    result = await ctx.get(eid)
    assert result == {"a": 1}


@pytest.mark.asyncio
async def test_get_falls_back_to_db(ctx, mock_redis, mock_db):
    eid = uuid4()
    mock_redis.get.return_value = None
    exec_mock = MagicMock()
    exec_mock.context = {"from": "db"}
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=exec_mock))

    result = await ctx.get(eid)
    assert result == {"from": "db"}
    mock_redis.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_returns_empty_if_no_execution(ctx, mock_redis, mock_db):
    eid = uuid4()
    mock_redis.get.return_value = None
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=None))

    result = await ctx.get(eid)
    assert result == {}


@pytest.mark.asyncio
async def test_set_value_simple(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({})
    await ctx.set_value(eid, "$.name", "hello")
    stored = json.loads(mock_redis.set.call_args[0][1])
    assert stored == {"name": "hello"}


@pytest.mark.asyncio
async def test_set_value_nested(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({})
    await ctx.set_value(eid, "$.product.title", "My Doc")
    stored = json.loads(mock_redis.set.call_args[0][1])
    assert stored == {"product": {"title": "My Doc"}}


@pytest.mark.asyncio
async def test_set_value_overwrites(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({"product": {"title": "Old"}})
    await ctx.set_value(eid, "$.product.title", "New")
    stored = json.loads(mock_redis.set.call_args[0][1])
    assert stored["product"]["title"] == "New"


@pytest.mark.asyncio
async def test_get_value_simple(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({"x": 42})
    val = await ctx.get_value(eid, "$.x")
    assert val == 42


@pytest.mark.asyncio
async def test_get_value_nested(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({"a": {"b": {"c": "deep"}}})
    val = await ctx.get_value(eid, "$.a.b.c")
    assert val == "deep"


@pytest.mark.asyncio
async def test_get_value_missing_returns_none(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({"a": 1})
    val = await ctx.get_value(eid, "$.b")
    assert val is None


@pytest.mark.asyncio
async def test_snapshot_updates_db(ctx, mock_redis, mock_db):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({"key": "val"})
    exec_mock = MagicMock()
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=exec_mock))

    await ctx.snapshot(eid)
    assert exec_mock.context == {"key": "val"}
    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_input_mapping(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({"user": {"name": "Alice"}})
    mappings = [InputMapping(source="$.user.name", target="username")]
    result = await ctx.apply_input_mapping(eid, mappings)
    assert result == {"username": "Alice"}


@pytest.mark.asyncio
async def test_apply_input_mapping_multiple(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({"a": 1, "b": 2})
    mappings = [
        InputMapping(source="$.a", target="x"),
        InputMapping(source="$.b", target="y"),
    ]
    result = await ctx.apply_input_mapping(eid, mappings)
    assert result == {"x": 1, "y": 2}


@pytest.mark.asyncio
async def test_apply_output_mapping(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({})
    output = {"result": "done"}
    mappings = [OutputMapping(source="result", target="$.status")]
    await ctx.apply_output_mapping(eid, mappings, output)
    stored = json.loads(mock_redis.set.call_args[0][1])
    assert stored == {"status": "done"}


@pytest.mark.asyncio
async def test_apply_output_mapping_nested(ctx, mock_redis):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({})
    output = {"doc": "text"}
    mappings = [OutputMapping(source="doc", target="$.product.doc")]
    await ctx.apply_output_mapping(eid, mappings, output)
    stored = json.loads(mock_redis.set.call_args[0][1])
    assert stored == {"product": {"doc": "text"}}


@pytest.mark.asyncio
async def test_commit_calls_snapshot(ctx, mock_redis, mock_db):
    eid = uuid4()
    mock_redis.get.return_value = json.dumps({"data": 1})
    exec_mock = MagicMock()
    mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=exec_mock))

    await ctx.commit(eid)
    assert exec_mock.context == {"data": 1}
    mock_db.flush.assert_awaited_once()

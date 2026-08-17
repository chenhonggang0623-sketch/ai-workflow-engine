from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_redis():
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock()
    return client


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()

    def make_execute_result(**attrs):
        result = MagicMock()
        for k, v in attrs.items():
            setattr(result, k, v)
        session.execute = AsyncMock(return_value=result)
        return result

    session._make_execute_result = make_execute_result
    return session

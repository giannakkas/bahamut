"""Mock database connections for testing."""
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

patch('sqlalchemy.ext.asyncio.create_async_engine', return_value=MagicMock()).start()

import sqlalchemy
def _mock_engine(*a, **kw):
    m = MagicMock()
    m.connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
    m.connect.return_value.__exit__ = MagicMock(return_value=False)
    return m
patch('sqlalchemy.create_engine', side_effect=_mock_engine).start()

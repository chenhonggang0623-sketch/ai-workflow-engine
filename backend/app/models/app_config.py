from datetime import UTC, datetime

from sqlalchemy import Column, String, Text, DateTime

from app.core.db import Base


class AppConfig(Base):
    __tablename__ = "app_configs"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), onupdate=lambda: datetime.now(UTC).replace(tzinfo=None))
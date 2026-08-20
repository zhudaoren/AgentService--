from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Generic, List, Optional, TypeVar
from uuid import UUID

T = TypeVar("T")


class BaseEntity:
    id: UUID
    created_at: datetime
    updated_at: datetime

    def __init__(self, **kwargs: Any):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()


class ValueObject:
    """值对象基类 - 不可变，通过值相等判断"""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return self.__dict__ == other.__dict__

    def __hash__(self) -> int:
        return hash(tuple(sorted(self.__dict__.items())))


class BaseRepository(ABC, Generic[T]):
    """仓储基类 - 定义通用CRUD接口"""

    @abstractmethod
    async def get(self, entity_id: UUID) -> Optional[T]:
        ...

    @abstractmethod
    async def list(
        self, page: int = 1, page_size: int = 20, **filters: Any
    ) -> tuple[List[T], int]:
        ...

    @abstractmethod
    async def create(self, entity: T) -> T:
        ...

    @abstractmethod
    async def update(self, entity: T) -> T:
        ...

    @abstractmethod
    async def delete(self, entity_id: UUID) -> None:
        ...


class DomainEvent:
    """领域事件基类"""

    event_type: str
    occurred_at: datetime
    payload: dict

    def __init__(self, event_type: str, payload: dict):
        self.event_type = event_type
        self.payload = payload
        self.occurred_at = datetime.utcnow()

"""SQLAlchemy ORM 模型 - 所有数据库表的映射

按数据库init.sql中的20张表定义，使用SQLAlchemy 2.0风格。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Text, Integer, Float, Boolean, DateTime, JSON, Enum,
    ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.db import Base


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    default_params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agents: Mapped[list["Agent"]] = relationship(back_populates="llm_config", cascade="all, delete-orphan")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    llm_config_id: Mapped[str] = mapped_column(String(36), ForeignKey("llm_configs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Enum("created", "deployed", "running", "paused", "stopped", "error"), default="created")
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    cloned_from_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    top_p: Mapped[float] = mapped_column(Float, default=0.9)
    memory_strategy: Mapped[str] = mapped_column(String(32), default="standard")
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    llm_config: Mapped["LLMConfig"] = relationship(back_populates="agents")
    long_term_memory: Mapped[Optional["LongTermMemory"]] = relationship(back_populates="agent", uselist=False, cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class LongTermMemory(Base):
    __tablename__ = "long_term_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), unique=True, nullable=False)
    user_profile: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    environment_facts: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    experience: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    shared_items: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="long_term_memory")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(Enum("active", "archived", "deleted"), default="active")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    message_type: Mapped[str] = mapped_column(Enum("user", "assistant", "system", "tool_call", "tool_result", "error"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

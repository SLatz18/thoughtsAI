"""
Database module for the Thinking Partner application.

Handles PostgreSQL connection, SQLAlchemy models, and database operations.
Uses async SQLAlchemy for non-blocking database operations.
"""

import os
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Column, String, Text, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.future import select
from dotenv import load_dotenv

load_dotenv()


def get_database_url() -> str:
    """
    Get the database URL, converting Railway's format if needed.

    Railway provides DATABASE_URL as postgres://... but asyncpg requires
    postgresql+asyncpg://... format.
    """
    url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/thinking_partner")

    # Convert Railway's postgres:// to postgresql+asyncpg://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return url


# Database URL from environment
DATABASE_URL = get_database_url()

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL debugging
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# ============================================================================
# SQLAlchemy Models
# ============================================================================

class Document(Base):
    """
    Stores the organized markdown document for a user.

    The document is stored both as structured JSONB (for programmatic updates)
    and as rendered markdown (for display and export).
    """
    __tablename__ = "documents"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(String(50), default="default_user", index=True)
    title = Column(String(255), default="My Thinking Session")
    content = Column(JSONB, default={"sections": []})
    markdown = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="document")


class DocumentVersion(Base):
    """
    Stores previous versions of documents for history tracking.
    Created automatically before each document update.
    """
    __tablename__ = "document_versions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id = Column(PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    content = Column(JSONB)
    markdown = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    document = relationship("Document", back_populates="versions")


class Session(Base):
    """
    Represents a thinking session.

    A session starts when the user clicks "Start Thinking Session" and ends
    when they click "End Session". All transcripts and conversations during
    this time are associated with this session.
    """
    __tablename__ = "sessions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(String(50), default="default_user", index=True)
    document_id = Column(PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    transcript = Column(Text, default="")
    status = Column(String(20), default="active")

    # Relationships
    document = relationship("Document", back_populates="sessions")
    conversations = relationship("Conversation", back_populates="session", cascade="all, delete-orphan")


class Conversation(Base):
    """
    Stores individual conversation messages (user thoughts and AI responses).
    """
    __tablename__ = "conversations"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("Session", back_populates="conversations")


# ============================================================================
# Pydantic Schemas for API responses
# ============================================================================

class DocumentSchema(BaseModel):
    """Pydantic schema for document responses."""
    id: UUID
    user_id: str
    title: str
    content: dict
    markdown: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SessionSchema(BaseModel):
    """Pydantic schema for session responses."""
    id: UUID
    user_id: str
    document_id: Optional[UUID]
    started_at: datetime
    ended_at: Optional[datetime]
    transcript: str
    status: str

    class Config:
        from_attributes = True


class ConversationSchema(BaseModel):
    """Pydantic schema for conversation responses."""
    id: UUID
    session_id: UUID
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Database Operations
# ============================================================================

async def get_db_session() -> AsyncSession:
    """Get an async database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """
    Initialize database tables.

    Note: For production, use Alembic migrations instead.
    This is a convenience for development/testing.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def create_document(
    session: AsyncSession,
    user_id: str = "default_user",
    title: str = "My Thinking Session"
) -> Document:
    """Create a new document."""
    document = Document(
        user_id=user_id,
        title=title,
        content={"sections": []},
        markdown=""
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return document


async def get_document(session: AsyncSession, document_id: UUID) -> Optional[Document]:
    """Get a document by ID."""
    result = await session.execute(
        select(Document).where(Document.id == document_id)
    )
    return result.scalar_one_or_none()


async def get_user_documents(session: AsyncSession, user_id: str = "default_user") -> list[Document]:
    """Get all documents for a user."""
    result = await session.execute(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.updated_at.desc())
    )
    return result.scalars().all()


async def update_document(
    session: AsyncSession,
    document_id: UUID,
    content: dict,
    markdown: str,
    save_version: bool = True
) -> Optional[Document]:
    """
    Update a document's content and markdown.
    Optionally saves the previous version for history.
    """
    document = await get_document(session, document_id)
    if not document:
        return None

    # Save previous version if requested
    if save_version and (document.content or document.markdown):
        version = DocumentVersion(
            document_id=document_id,
            content=document.content,
            markdown=document.markdown
        )
        session.add(version)

    # Update document
    document.content = content
    document.markdown = markdown
    await session.commit()
    await session.refresh(document)
    return document


async def create_session(
    db_session: AsyncSession,
    user_id: str = "default_user",
    document_id: Optional[UUID] = None
) -> Session:
    """Create a new thinking session."""
    thinking_session = Session(
        user_id=user_id,
        document_id=document_id,
        status="active"
    )
    db_session.add(thinking_session)
    await db_session.commit()
    await db_session.refresh(thinking_session)
    return thinking_session


async def get_session(db_session: AsyncSession, session_id: UUID) -> Optional[Session]:
    """Get a session by ID."""
    result = await db_session.execute(
        select(Session).where(Session.id == session_id)
    )
    return result.scalar_one_or_none()


async def end_session(db_session: AsyncSession, session_id: UUID) -> Optional[Session]:
    """End a thinking session."""
    thinking_session = await get_session(db_session, session_id)
    if thinking_session:
        thinking_session.ended_at = datetime.utcnow()
        thinking_session.status = "ended"
        await db_session.commit()
        await db_session.refresh(thinking_session)
    return thinking_session


async def update_session_transcript(
    db_session: AsyncSession,
    session_id: UUID,
    transcript: str
) -> Optional[Session]:
    """Update the transcript for a session."""
    thinking_session = await get_session(db_session, session_id)
    if thinking_session:
        thinking_session.transcript = transcript
        await db_session.commit()
        await db_session.refresh(thinking_session)
    return thinking_session


async def add_conversation(
    db_session: AsyncSession,
    session_id: UUID,
    role: str,
    content: str
) -> Conversation:
    """Add a conversation message to a session."""
    conversation = Conversation(
        session_id=session_id,
        role=role,
        content=content
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    return conversation


async def get_session_conversations(
    db_session: AsyncSession,
    session_id: UUID,
    limit: int = 20
) -> list[Conversation]:
    """Get recent conversations for a session."""
    result = await db_session.execute(
        select(Conversation)
        .where(Conversation.session_id == session_id)
        .order_by(Conversation.created_at.desc())
        .limit(limit)
    )
    conversations = result.scalars().all()
    # Return in chronological order
    return list(reversed(conversations))

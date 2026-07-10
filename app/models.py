"""SQLAlchemy ORM models for the Oneiros database."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Integer, SmallInteger, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Client(Base):
    __tablename__ = "clients"

    client_id: Mapped[UUID] = mapped_column(PG_UUID, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tier: Mapped[str] = mapped_column(Text, default="free", nullable=False)
    tier_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(
        Text, unique=True, nullable=True
    )

    dreams = relationship("Dream", back_populates="client", cascade="all, delete-orphan")
    dialogues = relationship("Dialogue", back_populates="client", cascade="all, delete-orphan")
    backups = relationship("Backup", back_populates="client", cascade="all, delete-orphan")


class Dream(Base):
    __tablename__ = "dreams"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    client_id: Mapped[UUID] = mapped_column(
        PG_UUID, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extraction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)
    mood: Mapped[str | None] = mapped_column(Text, nullable=True)

    client = relationship("Client", back_populates="dreams")
    dialogue = relationship("Dialogue", back_populates="dream", uselist=False, cascade="all, delete-orphan")


class Dialogue(Base):
    __tablename__ = "dialogues"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    dream_id: Mapped[str] = mapped_column(
        Text, ForeignKey("dreams.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[UUID] = mapped_column(
        PG_UUID, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False
    )
    history: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    grounded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", onupdate="now()"
    )

    dream = relationship("Dream", back_populates="dialogue")
    client = relationship("Client", back_populates="dialogues")


class Backup(Base):
    __tablename__ = "backups"

    phrase_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[UUID] = mapped_column(
        PG_UUID, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    restored_count: Mapped[int] = mapped_column(SmallInteger, default=0)

    client = relationship("Client", back_populates="backups")


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    stripe_event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

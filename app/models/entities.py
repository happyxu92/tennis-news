from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


class Tournament(Base):
    """Stored tennis tournament metadata."""

    __tablename__ = "tournaments"
    __table_args__ = (
        UniqueConstraint("source", "source_tournament_id", name="uq_tournament_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    source_tournament_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    tour: Mapped[str] = mapped_column(String(50), index=True)
    level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    surface: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    matches: Mapped[list[Match]] = relationship(back_populates="tournament")


class Match(Base):
    """Stored tennis match state."""

    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("source", "source_match_id", name="uq_match_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    source_match_id: Mapped[str] = mapped_column(String(255), index=True)
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournaments.id"),
        nullable=True,
        index=True,
    )
    round_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scheduled_at_utc: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
        index=True,
    )
    court_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    player1_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    player2_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    player1_country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    player2_country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    player1_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player2_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    score_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    winner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_key_match: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    tournament: Mapped[Tournament | None] = relationship(back_populates="matches")
    snapshots: Mapped[list[MatchSnapshot]] = relationship(back_populates="match")


class MatchSnapshot(Base):
    """Raw snapshots used for diffing and traceability."""

    __tablename__ = "match_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    snapshot_type: Mapped[str] = mapped_column(String(50), index=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    match: Mapped[Match] = relationship(back_populates="snapshots")


class PublishJob(Base):
    """Pending or completed publishing job."""

    __tablename__ = "publish_jobs"
    __table_args__ = (
        UniqueConstraint("biz_key", "content_hash", name="uq_publish_job_biz_content"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(50), index=True)
    biz_key: Mapped[str] = mapped_column(String(255), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )


class PublishedArticle(Base):
    """Published WeChat article record."""

    __tablename__ = "published_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("publish_jobs.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    wechat_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    publish_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    article_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

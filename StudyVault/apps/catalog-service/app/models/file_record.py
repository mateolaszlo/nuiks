from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


ROOT_FOLDER_SENTINEL = "__root__"


class FolderRow(Base):
    __tablename__ = "folders"
    __table_args__ = (
        Index(
            "uq_folders_active_sibling_name",
            "owner_id",
            text(f"coalesce(parent_folder_id, '{ROOT_FOLDER_SENTINEL}')"),
            "normalized_name",
            unique=True,
            sqlite_where=text("trashed_at IS NULL"),
        ),
        Index(
            "idx_folders_owner_parent_active",
            "owner_id",
            "parent_folder_id",
            sqlite_where=text("trashed_at IS NULL"),
        ),
        Index(
            "idx_folders_owner_purge_after",
            "owner_id",
            "purge_after",
            sqlite_where=text("trashed_at IS NOT NULL"),
        ),
        Index("idx_folders_owner_trashed_at", "owner_id", "trashed_at"),
    )

    folder_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    parent_folder_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("folders.folder_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    path_depth: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_parent_folder_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_by_cascade: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    parent: Mapped["FolderRow | None"] = relationship(remote_side=[folder_id], backref="children")


class FileRow(Base):
    __tablename__ = "files"
    __table_args__ = (
        Index(
            "uq_files_active_sibling_name",
            "owner_id",
            text(f"coalesce(parent_folder_id, '{ROOT_FOLDER_SENTINEL}')"),
            text("lower(filename)"),
            unique=True,
            sqlite_where=text("trashed_at IS NULL"),
        ),
        Index(
            "idx_files_owner_parent_active",
            "owner_id",
            "parent_folder_id",
            sqlite_where=text("trashed_at IS NULL"),
        ),
        Index(
            "idx_files_owner_purge_after",
            "owner_id",
            "purge_after",
            sqlite_where=text("trashed_at IS NOT NULL"),
        ),
        Index("idx_files_owner_trashed_at", "owner_id", "trashed_at"),
    )

    file_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(255), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(BigInteger)
    object_key: Mapped[str] = mapped_column(String(512))
    tags: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    parent_folder_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("folders.folder_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_parent_folder_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

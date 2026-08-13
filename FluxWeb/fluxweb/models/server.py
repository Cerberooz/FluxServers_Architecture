"""Provisioned server records."""

from __future__ import annotations

from datetime import UTC, datetime

from fluxweb.extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ServerStatus:
    ACTIVE = "Active"
    SUSPENDED = "Suspended"
    EXPIRED = "Expired"
    DELETED = "Deleted"


class ServerRecord(db.Model):
    __tablename__ = "server_record"
    __table_args__ = (
        # Every account page load and every stats poll hits these (audit P-3).
        db.Index("ix_server_record_user_status", "user_id", "status"),
        db.Index("ix_server_record_identifier_user", "pelican_server_identifier", "user_id"),
        db.Index("ix_server_record_panel_id", "pelican_server_id"),
        db.Index("ix_server_record_expires", "expires_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("game_plan.id"), nullable=True)
    plan_name = db.Column(db.String(100))

    pelican_server_id = db.Column(db.Integer)
    pelican_server_identifier = db.Column(db.String(20))

    payment_ref = db.Column(db.String(100))
    status = db.Column(db.String(20), default=ServerStatus.ACTIVE)

    created_at = db.Column(db.DateTime, default=utcnow)
    expires_at = db.Column(db.DateTime)
    last_synced_at = db.Column(db.DateTime, nullable=True)

    ip_address = db.Column(db.String(50))
    node_name = db.Column(db.String(50))

    plan = db.relationship("GamePlan", lazy="joined")

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at < utcnow()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ServerRecord {self.id} {self.pelican_server_identifier} {self.status}>"

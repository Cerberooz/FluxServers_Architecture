"""Editorial and status content managed from the admin dashboard."""

from __future__ import annotations

from datetime import UTC, datetime

from fluxweb.extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Announcement(db.Model):
    __tablename__ = "announcement"
    __table_args__ = (db.Index("ix_announcement_active", "active"),)

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class MaintenanceUpdate(db.Model):
    __tablename__ = "maintenance_update"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="Scheduled")
    created_at = db.Column(db.DateTime, default=utcnow, index=True)


class ServiceStatus(db.Model):
    __tablename__ = "service_status"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default="Operational")
    flag_icon = db.Column(db.String(10), nullable=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class FAQ(db.Model):
    __tablename__ = "faq"

    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(255), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default="General")
    order = db.Column(db.Integer, default=0, index=True)


class GlobeLocation(db.Model):
    __tablename__ = "globe_location"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)


class ReferralCode(db.Model):
    __tablename__ = "referral_code"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    target_url = db.Column(db.String(255), nullable=False)
    clicks = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)

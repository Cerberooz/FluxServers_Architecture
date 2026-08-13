"""SQLAlchemy models.

Table and column names match the pre-existing schema exactly so this maps onto
the current production database without a rename migration.
"""

from fluxweb.models.billing import Coupon, ItemKind, Order, OrderItem, OrderStatus, Payment
from fluxweb.models.content import (
    FAQ,
    Announcement,
    GlobeLocation,
    MaintenanceUpdate,
    ReferralCode,
    ServiceStatus,
)
from fluxweb.models.plan import GamePlan, PlanCategory, PlanSubcategory
from fluxweb.models.server import ServerRecord, ServerStatus
from fluxweb.models.user import User, VerificationToken

__all__ = [
    "Announcement",
    "Coupon",
    "FAQ",
    "GamePlan",
    "GlobeLocation",
    "ItemKind",
    "MaintenanceUpdate",
    "Order",
    "OrderItem",
    "OrderStatus",
    "Payment",
    "PlanCategory",
    "PlanSubcategory",
    "ReferralCode",
    "ServerRecord",
    "ServerStatus",
    "ServiceStatus",
    "User",
    "VerificationToken",
]

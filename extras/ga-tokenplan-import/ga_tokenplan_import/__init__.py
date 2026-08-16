"""Optional TokenPlan → GenericAgent key-import package."""

from .subscription_portal import (  # noqa: F401
    apply_tokenplan_snippet,
    start_subscription_portal,
    ensure_callback_server,
    stop_callback_server,
    is_available,
)

__version__ = "1.0.0"

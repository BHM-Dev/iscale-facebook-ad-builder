from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func


class RateLimiter:
    """Database-backed rolling window rate limiter for Facebook API calls"""

    def __init__(self, max_calls: int = 200, window_minutes: int = 59):
        self.max_calls = max_calls
        self.window_minutes = window_minutes

    def _window_usage(self, db: Session):
        """(calls in the rolling window, timestamp of the oldest call in it).

        Reads ApiUsageLog — the table the scraper actually writes one row to per search. (This used to read
        SearchLog, which nothing ever writes, so the limiter always saw 0 calls and never rejected.)
        """
        from app.models import ApiUsageLog

        window_start = datetime.now(timezone.utc) - timedelta(minutes=self.window_minutes)
        in_window = (ApiUsageLog.endpoint == "facebook_ads_library", ApiUsageLog.created_at >= window_start)
        total_calls = db.query(func.sum(ApiUsageLog.api_calls)).filter(*in_window).scalar() or 0
        oldest = db.query(func.min(ApiUsageLog.created_at)).filter(*in_window).scalar() if total_calls else None
        return int(total_calls), oldest

    def _reset_seconds(self, oldest) -> int:
        if oldest is None:
            return 0
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        reset_time = oldest + timedelta(minutes=self.window_minutes)
        return max(0, int((reset_time - datetime.now(timezone.utc)).total_seconds()))

    def check_limit(self, db: Session) -> Tuple[bool, int, int]:
        """
        Check if rate limit allows another call.
        Returns: (allowed, remaining, reset_seconds)
        """
        total_calls, oldest = self._window_usage(db)
        remaining = max(0, self.max_calls - total_calls)
        allowed = total_calls < self.max_calls
        return allowed, remaining, (self._reset_seconds(oldest) if not allowed else 0)

    def get_usage_stats(self, db: Session) -> Dict:
        """Get current usage statistics"""
        total_calls, oldest = self._window_usage(db)
        return {
            "limit": self.max_calls,
            "used": total_calls,
            "remaining": max(0, self.max_calls - total_calls),
            "reset_in_seconds": self._reset_seconds(oldest),
            "window_minutes": self.window_minutes
        }


# Global rate limiter instance
rate_limiter = RateLimiter(max_calls=200, window_minutes=59)

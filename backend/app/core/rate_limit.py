import os
from slowapi import Limiter
from slowapi.util import get_remote_address

# Rate limiter - uses client IP for rate limiting.
# Set DISABLE_RATE_LIMIT=true in test environments to prevent the 5/min
# cap from causing 429s across the test suite (all tests share one IP).
_enabled = os.getenv("DISABLE_RATE_LIMIT", "").lower() not in ("1", "true", "yes")
limiter = Limiter(key_func=get_remote_address, enabled=_enabled)

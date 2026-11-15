import pytest
from fastapi import HTTPException

from app.core import user_rate_limit as url


def test_limit_trips_per_user_and_bucket():
    url._CALLS.clear()
    for _ in range(3):
        url.check("b", "u1", 3, 600)
    with pytest.raises(HTTPException) as e:
        url.check("b", "u1", 3, 600)
    assert e.value.status_code == 429
    url.check("b", "u2", 3, 600)      # other user unaffected
    url.check("other", "u1", 3, 600)  # other bucket unaffected


def test_window_expires(monkeypatch):
    url._CALLS.clear()
    t = [1000.0]
    monkeypatch.setattr(url.time, "monotonic", lambda: t[0])
    url.check("b", "u", 1, 10)
    t[0] += 11
    url.check("b", "u", 1, 10)

"""Unit tests for the CAPI quality service's defensive parsing + concurrency-safe
upsert. Parsing tests are pure (no DB). The upsert/concurrency tests use the
real `db_session` fixture (Postgres) since `_upsert_snapshot` uses a
Postgres-specific `INSERT ... ON CONFLICT` and can't be exercised against a
non-Postgres backend.
"""
from datetime import date

import pytest

from app.services.capi_quality_service import (
    _extract_freshness,
    _extract_percentage,
    _parse_dataset_quality,
    _parse_match_key_feedback,
    _safe_float,
    _upsert_snapshot,
)
from app.models import CapiQualitySnapshot


# ---------------------------------------------------------------------------
# _safe_float / _extract_percentage — numeric/string/malformed EMQ + coverage
# ---------------------------------------------------------------------------

def test_safe_float_accepts_number():
    assert _safe_float(6.2) == 6.2


def test_safe_float_accepts_numeric_string():
    assert _safe_float("7.5") == 7.5


def test_safe_float_none_is_none():
    assert _safe_float(None) is None


def test_safe_float_malformed_string_is_none():
    assert _safe_float("not-a-number") is None


def test_safe_float_malformed_type_is_none():
    # A list/dict landing where a number was expected shouldn't raise.
    assert _safe_float([1, 2, 3]) is None
    assert _safe_float({"unexpected": "shape"}) is None


def test_extract_percentage_from_object():
    assert _extract_percentage({"percentage": 93.3}) == 93.3


def test_extract_percentage_from_bare_number():
    assert _extract_percentage(12.4) == 12.4


def test_extract_percentage_from_numeric_string():
    assert _extract_percentage("55.0") == 55.0


def test_extract_percentage_missing_is_none():
    assert _extract_percentage(None) is None


def test_extract_percentage_object_without_percentage_key_is_none():
    assert _extract_percentage({"description": "no percentage here"}) is None


def test_extract_percentage_malformed_object_value_is_none():
    # percentage present but itself malformed
    assert _extract_percentage({"percentage": "garbage"}) is None


def test_extract_freshness_from_object():
    assert _extract_freshness({"upload_frequency": "real_time"}) == "real_time"


def test_extract_freshness_from_object_falls_back_to_description():
    assert _extract_freshness({"description": "hourly batches"}) == "hourly batches"


def test_extract_freshness_from_bare_string():
    assert _extract_freshness("hourly") == "hourly"


def test_extract_freshness_missing_is_none():
    assert _extract_freshness(None) is None


def test_extract_freshness_malformed_type_is_none():
    assert _extract_freshness(12345) is None
    assert _extract_freshness([1, 2]) is None


# ---------------------------------------------------------------------------
# _parse_match_key_feedback — malformed match-key entries
# ---------------------------------------------------------------------------

def test_parse_match_key_feedback_normal_shape():
    emq_obj = {
        "match_key_feedback": [
            {"identifier": "email", "coverage": {"percentage": 93.3}},
            {"identifier": "phone", "coverage": {"percentage": 90.0}},
        ]
    }
    assert _parse_match_key_feedback(emq_obj) == {"email": 93.3, "phone": 90.0}


def test_parse_match_key_feedback_bare_number_coverage():
    emq_obj = {"match_key_feedback": [{"identifier": "ip_address", "coverage": 100}]}
    assert _parse_match_key_feedback(emq_obj) == {"ip_address": 100.0}


def test_parse_match_key_feedback_numeric_string_coverage():
    emq_obj = {"match_key_feedback": [{"identifier": "user_agent", "coverage": "99.9"}]}
    assert _parse_match_key_feedback(emq_obj) == {"user_agent": 99.9}


def test_parse_match_key_feedback_missing_coverage():
    emq_obj = {"match_key_feedback": [{"identifier": "fbp"}]}
    assert _parse_match_key_feedback(emq_obj) == {"fbp": None}


def test_parse_match_key_feedback_missing_key_entirely():
    assert _parse_match_key_feedback({}) is None


def test_parse_match_key_feedback_not_a_list():
    # Meta (or a future/mock response) sending an object instead of an array
    assert _parse_match_key_feedback({"match_key_feedback": {"email": 100}}) is None


def test_parse_match_key_feedback_item_not_a_dict():
    # A malformed item (e.g. a bare string) is skipped, not fatal
    emq_obj = {"match_key_feedback": ["not-a-dict", {"identifier": "email", "coverage": {"percentage": 50}}]}
    assert _parse_match_key_feedback(emq_obj) == {"email": 50.0}


def test_parse_match_key_feedback_missing_identifier_is_skipped():
    emq_obj = {"match_key_feedback": [{"coverage": {"percentage": 50}}]}
    assert _parse_match_key_feedback(emq_obj) is None


def test_parse_match_key_feedback_non_string_identifier_is_skipped():
    emq_obj = {"match_key_feedback": [{"identifier": 42, "coverage": {"percentage": 50}}]}
    assert _parse_match_key_feedback(emq_obj) is None


def test_parse_match_key_feedback_all_malformed_returns_none():
    emq_obj = {"match_key_feedback": ["garbage", 123, None]}
    assert _parse_match_key_feedback(emq_obj) is None


# ---------------------------------------------------------------------------
# _parse_dataset_quality — full response shapes, including malformed ones
# ---------------------------------------------------------------------------

def test_parse_dataset_quality_real_shape():
    raw = {
        "web": [
            {
                "event_name": "Lead",
                "event_match_quality": {
                    "composite_score": 9.3,
                    "match_key_feedback": [
                        {"identifier": "email", "coverage": {"percentage": 100}},
                    ],
                },
                "acr": {"percentage": 12.4},
                "event_coverage": {"percentage": 100.0},
                "data_freshness": {"upload_frequency": "real_time"},
            }
        ]
    }
    parsed = _parse_dataset_quality(raw)
    assert len(parsed) == 1
    row = parsed[0]
    assert row["event_name"] == "Lead"
    assert row["event_match_quality"] == 9.3
    assert row["match_key_feedback"] == {"email": 100.0}
    assert row["acr"] == 12.4
    assert row["event_coverage"] == 100.0
    assert row["data_freshness"] == "real_time"


def test_parse_dataset_quality_multiple_events_no_aggregate():
    raw = {
        "web": [
            {"event_name": "Lead", "event_match_quality": {"composite_score": 9.3}},
            {"event_name": "AddToCart", "event_match_quality": {"composite_score": 8.6}},
        ]
    }
    parsed = _parse_dataset_quality(raw)
    assert {p["event_name"] for p in parsed} == {"Lead", "AddToCart"}


def test_parse_dataset_quality_empty_web_list():
    parsed = _parse_dataset_quality({"web": []})
    assert len(parsed) == 1
    assert parsed[0]["event_name"] is None
    assert parsed[0]["event_match_quality"] is None
    assert "no 'web' rows returned" in parsed[0]["diagnostics"]["note"]


def test_parse_dataset_quality_missing_web_key():
    parsed = _parse_dataset_quality({})
    assert len(parsed) == 1
    assert parsed[0]["event_match_quality"] is None


def test_parse_dataset_quality_response_not_a_dict():
    # Defensive against a completely unexpected top-level shape
    parsed = _parse_dataset_quality(None)
    assert len(parsed) == 1
    assert parsed[0]["event_match_quality"] is None
    assert "not a JSON object" in parsed[0]["diagnostics"]["note"]

    parsed2 = _parse_dataset_quality(["unexpected", "list"])
    assert len(parsed2) == 1
    assert parsed2[0]["event_match_quality"] is None


def test_parse_dataset_quality_event_match_quality_not_a_dict():
    # composite_score/match_key_feedback normally live inside an object —
    # a bare number here shouldn't crash, it should just yield no metrics.
    raw = {"web": [{"event_name": "Lead", "event_match_quality": 9.3}]}
    parsed = _parse_dataset_quality(raw)
    assert parsed[0]["event_name"] == "Lead"
    assert parsed[0]["event_match_quality"] is None
    assert parsed[0]["match_key_feedback"] is None


def test_parse_dataset_quality_web_not_a_list():
    raw = {"web": {"unexpected": "object instead of list"}}
    parsed = _parse_dataset_quality(raw)
    assert len(parsed) == 1
    assert parsed[0]["event_match_quality"] is None


def test_parse_dataset_quality_row_not_a_dict_is_skipped_not_fatal():
    raw = {"web": ["garbage-string", {"event_name": "Lead", "event_match_quality": {"composite_score": 9.3}}]}
    parsed = _parse_dataset_quality(raw)
    assert len(parsed) == 1
    assert parsed[0]["event_name"] == "Lead"
    assert parsed[0]["event_match_quality"] == 9.3


def test_parse_dataset_quality_all_rows_malformed():
    raw = {"web": ["garbage", 123, None]}
    parsed = _parse_dataset_quality(raw)
    assert len(parsed) == 1
    assert parsed[0]["event_match_quality"] is None
    assert "all malformed" in parsed[0]["diagnostics"]["note"]


def test_parse_dataset_quality_acr_and_coverage_as_bare_numbers():
    # Not first-party-confirmed to always be objects — handle the plain-number
    # case too.
    raw = {
        "web": [
            {
                "event_name": "Purchase",
                "event_match_quality": {"composite_score": 7.8},
                "acr": 15.0,
                "event_coverage": 88.5,
            }
        ]
    }
    parsed = _parse_dataset_quality(raw)
    assert parsed[0]["acr"] == 15.0
    assert parsed[0]["event_coverage"] == 88.5


# ---------------------------------------------------------------------------
# _upsert_snapshot — concurrency / repeated writes (needs real Postgres)
# ---------------------------------------------------------------------------

def _snapshot_values(**overrides):
    from app.models import generate_uuid
    values = {
        "id": generate_uuid(),
        "pixel_id": "test-pixel-capi-quality",
        "fb_account_id": "act_test_capi_quality",
        "account_name": "Test Account",
        "pixel_name": "Test Pixel",
        "event_name": "Lead",
        "snapshot_date": date(2026, 1, 1),
        "event_match_quality": 9.1,
        "acr": None,
        "event_coverage": None,
        "data_freshness": "real_time",
        "match_key_feedback": {"email": 90.0},
        "diagnostics": {"raw_row": {}},
        "fetch_error": None,
    }
    values.update(overrides)
    return values


@pytest.fixture(autouse=True)
def _cleanup_capi_quality_rows(db_session):
    """Keep this test file self-contained — don't leave scratch rows behind
    in a shared test DB, matching the existing test_user cleanup convention
    in conftest.py.
    """
    yield
    db_session.query(CapiQualitySnapshot).filter(
        CapiQualitySnapshot.pixel_id == "test-pixel-capi-quality"
    ).delete()
    db_session.commit()


def test_upsert_snapshot_inserts_new_row(db_session):
    _upsert_snapshot(db_session, _snapshot_values())
    rows = db_session.query(CapiQualitySnapshot).filter(
        CapiQualitySnapshot.pixel_id == "test-pixel-capi-quality"
    ).all()
    assert len(rows) == 1
    assert float(rows[0].event_match_quality) == 9.1


def test_upsert_snapshot_repeated_write_updates_not_duplicates(db_session):
    """Simulates the daily scheduled job and a manual "Sync now" both writing
    the same (pixel, account, event, day) — must end up as ONE row with the
    latest values, not two rows.
    """
    _upsert_snapshot(db_session, _snapshot_values(event_match_quality=9.1))
    _upsert_snapshot(db_session, _snapshot_values(event_match_quality=9.3))

    rows = db_session.query(CapiQualitySnapshot).filter(
        CapiQualitySnapshot.pixel_id == "test-pixel-capi-quality"
    ).all()
    assert len(rows) == 1
    assert float(rows[0].event_match_quality) == 9.3


def test_upsert_snapshot_error_then_success_clears_fetch_error(db_session):
    """A failed sync followed by a successful re-sync for the same key should
    leave no stale fetch_error behind.
    """
    _upsert_snapshot(db_session, _snapshot_values(
        event_match_quality=None, fetch_error="HTTP 500: transient failure",
    ))
    _upsert_snapshot(db_session, _snapshot_values(
        event_match_quality=9.3, fetch_error=None,
    ))

    rows = db_session.query(CapiQualitySnapshot).filter(
        CapiQualitySnapshot.pixel_id == "test-pixel-capi-quality"
    ).all()
    assert len(rows) == 1
    assert rows[0].fetch_error is None
    assert float(rows[0].event_match_quality) == 9.3


def test_upsert_snapshot_different_events_same_pixel_are_separate_rows(db_session):
    """Two different event_names for the same (pixel, account, day) must NOT
    collide — this is the whole point of keying on event_name too.
    """
    _upsert_snapshot(db_session, _snapshot_values(event_name="Lead", event_match_quality=9.3))
    _upsert_snapshot(db_session, _snapshot_values(event_name="AddToCart", event_match_quality=8.6))

    rows = db_session.query(CapiQualitySnapshot).filter(
        CapiQualitySnapshot.pixel_id == "test-pixel-capi-quality"
    ).all()
    assert len(rows) == 2
    by_event = {r.event_name: float(r.event_match_quality) for r in rows}
    assert by_event == {"Lead": 9.3, "AddToCart": 8.6}


def test_upsert_snapshot_concurrent_writes_do_not_duplicate(db_session):
    """Two "concurrent" upserts for the exact same key (simulating the daily
    scheduler and a manual Sync-now landing at the same moment) must collapse
    to one row via ON CONFLICT, not raise a duplicate-key error and not create
    two rows. Runs both upserts on independent sessions bound to the same
    engine to approximate two separate request/job contexts.
    """
    from sqlalchemy.orm import sessionmaker
    Session2 = sessionmaker(bind=db_session.get_bind())
    session_a = db_session
    session_b = Session2()
    try:
        _upsert_snapshot(session_a, _snapshot_values(event_match_quality=9.1))
        _upsert_snapshot(session_b, _snapshot_values(event_match_quality=9.3))
    finally:
        session_b.close()

    rows = db_session.query(CapiQualitySnapshot).filter(
        CapiQualitySnapshot.pixel_id == "test-pixel-capi-quality"
    ).all()
    assert len(rows) == 1

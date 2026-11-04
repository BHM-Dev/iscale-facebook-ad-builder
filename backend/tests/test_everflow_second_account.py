from datetime import date

from app.services.everflow_service import EverflowService


def _row(cid, offer, day, sub3="1234567890123"):
    return {"conversion_id": cid, "offer": offer, "conversion_date": day, "revenue": "10", "sub3": sub3}


def _patched(monkeypatch, first_rows, second_rows):
    def fake(self, f, t, tz):
        return list(second_rows if self.api_key == "k2" else first_rows)
    monkeypatch.setattr(EverflowService, "_fetch_single_account_rows", fake)
    monkeypatch.setenv("SWITCHBOARD_EVERFLOW_API_KEY", "k1")


def test_no_second_key_is_unchanged(monkeypatch):
    monkeypatch.delenv("SWITCHBOARD_EVERFLOW_2_API_KEY", raising=False)
    first = [_row("a", "Fast Auto Quote.org", "2026-11-02")]
    _patched(monkeypatch, first, [])
    assert EverflowService()._fetch_conversion_rows_uncached("2026-10-01", "2026-11-04", 90) == first


def test_cutover_swaps_auto_source(monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_EVERFLOW_2_API_KEY", "k2")
    first = [
        _row("oct", "Fast Auto Quote.org", "2026-10-30"),      # before cutover: kept
        _row("nov-auto", "Fast Auto Quote.org", "2026-11-02"),  # network auto, after cutover: ignored
        _row("nov-gbc", "Get Business Coverage", "2026-11-02"), # commercial: untouched
    ]
    second = [
        _row("s-oct", "Fast Auto Quote", "2026-10-31"),         # before cutover: ignored
        _row("s-nov", "Fast Auto Quote", "2026-11-03", sub3=""),
        _row("s-other", "Get Business Coverage", "2026-11-03"),  # not an auto offer: never admitted from key2
    ]
    first.append(_row("nov-variant", " fast auto quote.ORG ", "2026-11-02"))  # spelling variant still dropped
    _patched(monkeypatch, first, second)
    rows = EverflowService()._fetch_conversion_rows_uncached("2026-10-01", "2026-11-04", 90)
    ids = {r["conversion_id"]: r for r in rows}
    assert set(ids) == {"oct", "nov-gbc", "s-nov"}
    assert ids["s-nov"]["_realm"] == 2 and "_realm" not in ids["oct"]


def test_range_before_cutover_never_calls_second_account(monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_EVERFLOW_2_API_KEY", "k2")
    first = [_row("oct", "Fast Auto Quote.org", "2026-10-30")]
    _patched(monkeypatch, first, [_row("boom", "x", "2026-11-03")])
    assert EverflowService()._fetch_conversion_rows_uncached("2026-10-01", "2026-10-31", 90) == first

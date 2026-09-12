"""Unit tests for FacebookService.get_all_adsets_for_account.

This is the account-level ad set fetch that replaced the per-campaign loop in
/facebook/sync. The per-campaign version burst through Meta's per-ad-account
rate limit on a large account and silently truncated the sync, dropping real ad
sets — and the Everflow revenue P&L attributes to them — out of the
FacebookAdSet table. These tests lock in the three properties that make the
replacement correct: it issues a bounded number of calls, it UNIONS two passes
(neither of which is complete alone), and it never reports a partial result as
if it were a full one.

Pure tests — the Meta account object is a stub, no API and no DB.
"""
import pytest

from app.services.facebook_service import FacebookService


class _StubAccount:
    """Stands in for AdAccount, recording the params of each get_ad_sets call."""

    def __init__(self, unfiltered=None, archived=None, raises=None):
        self.unfiltered = unfiltered or []
        self.archived = archived or []
        self.raises = raises or {}
        self.calls = []

    def get_ad_sets(self, fields=None, params=None):
        params = params or {}
        key = 'archived' if params.get('effective_status') else 'unfiltered'
        self.calls.append(key)
        if key in self.raises:
            raise self.raises[key]
        return self.archived if key == 'archived' else self.unfiltered


def _svc(account, monkeypatch):
    svc = FacebookService()
    monkeypatch.setattr(svc, '_get_account', lambda ad_account_id=None: account)
    # Both passes are separated by a real sleep in production; skip the wait.
    monkeypatch.setattr('app.services.facebook_service.time.sleep', lambda *_: None)
    return svc


def test_unions_both_passes(monkeypatch):
    """The archived pass contributes ad sets the unfiltered pass cannot see."""
    account = _StubAccount(
        unfiltered=[{'id': '1', 'name': 'live'}, {'id': '2', 'name': 'derived'}],
        archived=[{'id': '1', 'name': 'live'}, {'id': '3', 'name': 'archived-only'}],
    )
    adsets, failures = _svc(account, monkeypatch).get_all_adsets_for_account('act_1')

    assert failures == []
    assert {a['id'] for a in adsets} == {'1', '2', '3'}


def test_derived_status_adsets_survive(monkeypatch):
    """Regression: an explicit effective_status filter drops CAMPAIGN_PAUSED ad
    sets, so a single filtered call loses them. Two of the ten ad sets in the
    original RHO revenue gap were exactly this case."""
    account = _StubAccount(
        unfiltered=[{'id': 'cp', 'effective_status': 'CAMPAIGN_PAUSED'}],
        archived=[{'id': 'arch', 'effective_status': 'ARCHIVED'}],
    )
    adsets, _ = _svc(account, monkeypatch).get_all_adsets_for_account('act_1')

    assert {a['id'] for a in adsets} == {'cp', 'arch'}


def test_unfiltered_pass_wins_dedupe(monkeypatch):
    """On conflict keep the unfiltered row — it carries the live status."""
    account = _StubAccount(
        unfiltered=[{'id': '1', 'effective_status': 'CAMPAIGN_PAUSED'}],
        archived=[{'id': '1', 'effective_status': 'ARCHIVED'}],
    )
    adsets, _ = _svc(account, monkeypatch).get_all_adsets_for_account('act_1')

    assert len(adsets) == 1
    assert adsets[0]['effective_status'] == 'CAMPAIGN_PAUSED'


def test_call_count_is_bounded(monkeypatch):
    """The whole point: ~2 calls for the account, not one per campaign."""
    account = _StubAccount(unfiltered=[{'id': '1'}], archived=[{'id': '2'}])
    _svc(account, monkeypatch).get_all_adsets_for_account('act_1')

    assert account.calls == ['unfiltered', 'archived']


def test_partial_result_is_reported_not_swallowed(monkeypatch):
    """A failed pass must surface in `failures`. Returning the survivors with an
    empty failure list is what let a truncated sync look successful."""
    account = _StubAccount(
        unfiltered=[{'id': '1'}],
        raises={'archived': RuntimeError('boom')},
    )
    adsets, failures = _svc(account, monkeypatch).get_all_adsets_for_account('act_1')

    assert [a['id'] for a in adsets] == ['1']
    assert len(failures) == 1
    assert 'archived' in failures[0]


def test_both_passes_failing_yields_no_adsets_and_two_failures(monkeypatch):
    account = _StubAccount(raises={
        'unfiltered': RuntimeError('down'),
        'archived': RuntimeError('down'),
    })
    adsets, failures = _svc(account, monkeypatch).get_all_adsets_for_account('act_1')

    assert adsets == []
    assert len(failures) == 2


def test_adsets_without_id_are_dropped(monkeypatch):
    account = _StubAccount(unfiltered=[{'id': '1'}, {'name': 'no id'}, {'id': ''}])
    adsets, _ = _svc(account, monkeypatch).get_all_adsets_for_account('act_1')

    assert [a['id'] for a in adsets] == ['1']

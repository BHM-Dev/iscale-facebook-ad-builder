from app.services.drive_drift_guard import (
    ALERT_AFTER_ANY_SIGHTINGS,
    MAX_HEALS_PER_PACKAGE,
    MAX_HEALS_PER_RUN,
    run_guard,
)


class Harness:
    def __init__(self, alert_ok=True):
        self.state = None
        self.healed = []
        self.alerts = []
        self.heal_error_for = set()
        self.alert_ok = alert_ok

    def run(self, missing):
        def heal(folder_id):
            if folder_id in self.heal_error_for:
                raise RuntimeError("drive unavailable or locked")
            self.healed.append(folder_id)

        def alert(summary, detail):
            self.alerts.append((summary, detail))
            return self.alert_ok

        return run_guard(
            {"all_missing_packages": missing},
            load_state=lambda: self.state,
            save_state=lambda s: setattr(self, "state", s),
            heal=heal,
            alert=alert,
        )


def gap(folder_id, missing=5):
    return {"folder_id": folder_id, "path": f"Brand / Cat / {folder_id}", "media_count": 10, "missing_count": missing}


def test_first_sighting_heals_but_does_not_alert():
    h = Harness()

    out = h.run([gap("a")])

    assert h.healed == ["a"] and h.alerts == [] and out["persistent"] == 0


def test_gap_that_survives_a_successful_resync_alerts_once_with_the_package_named():
    h = Harness()
    h.run([gap("a")])   # healed
    h.run([gap("a")])   # still there after a re-sync that ran -> alert
    h.run([gap("a")])   # same set: no second alert

    assert len(h.alerts) == 1 and "Brand / Cat / a" in h.alerts[0][1]


def test_gap_that_heals_never_alerts_and_resets_counts():
    h = Harness()
    h.run([gap("a")])
    h.run([])
    h.run([gap("a")])

    assert h.alerts == [] and h.state["sightings"] == {"a": 1}


def test_a_heal_that_never_ran_does_not_trigger_the_resync_failed_alert_early():
    h = Harness()
    h.heal_error_for = {"a"}   # e.g. lock contention every time

    for _ in range(ALERT_AFTER_ANY_SIGHTINGS - 1):
        h.run([gap("a")])
    assert h.alerts == []

    h.run([gap("a")])          # but silence can't last forever
    assert len(h.alerts) == 1


def test_a_stubborn_package_stops_being_healed_and_does_not_starve_others():
    h = Harness()
    for _ in range(MAX_HEALS_PER_PACKAGE + 2):
        h.run([gap("stubborn", 50), gap("other", 1), gap("third", 2)])

    assert h.healed.count("stubborn") == MAX_HEALS_PER_PACKAGE
    assert "other" in h.healed and "third" in h.healed


def test_heals_are_capped_per_run_fewest_heals_then_largest_gap_first():
    h = Harness()

    h.run([gap("small", 1), gap("big", 50), gap("mid", 9)])

    assert len(h.healed) == MAX_HEALS_PER_RUN and h.healed[0] == "big" and "small" not in h.healed


def test_a_failed_alert_is_retried_next_run_not_recorded_as_sent():
    h = Harness(alert_ok=False)
    h.run([gap("a")])
    h.run([gap("a")])
    assert h.state["alerted_hash"] is None

    h.alert_ok = True
    h.run([gap("a")])

    assert len(h.alerts) == 2 and h.state["alerted_hash"] is not None


def test_gaps_beyond_the_top_ten_are_still_seen_via_the_full_list():
    h = Harness()

    out = h.run([gap(f"p{i}", 20 - i) for i in range(15)])

    assert out["gaps"] == 15


def test_an_unusable_report_does_not_wipe_the_guards_memory():
    h = Harness()
    h.run([gap("a")])
    before = dict(h.state)

    out = run_guard(
        {"last_error": "drive listing failed"},
        load_state=lambda: h.state,
        save_state=lambda s: (_ for _ in ()).throw(AssertionError("must not save")),
        heal=lambda f: None,
        alert=lambda *a: True,
    )

    assert out["skipped"] is True and h.state == before

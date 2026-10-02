"""Close the loop on Drive drift: heal what the hourly health check finds, alert on what won't heal.

The Package Health snapshot already compares Drive to the library per package. Until now a
gap only mattered if someone happened to read the page. This guard runs right after each
snapshot:

  gap seen            -> re-sync that package's folder (idempotent; the same recovery used by hand
                         for CA-PROVEN / CI-CALLOUT / LLC Rate Check, 2026-10-02)
  still there after a SUCCESSFUL re-sync -> one alert naming the packages
  never got a successful re-sync (lock contention, errors) after several sightings -> alert too,
                         so silence can never come from the heal simply not running

Bounded on purpose: MAX_HEALS_PER_RUN packages per run, fewest-heals-first so one stubborn
package can't starve the others, and a package is retried at most MAX_HEALS_PER_PACKAGE times
before it is left to the alert. Archive folders never count (the snapshot already excludes them).
"""
import hashlib
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_KEY = "drift_guard_state"
MAX_HEALS_PER_RUN = 2
MAX_HEALS_PER_PACKAGE = 3
ALERT_AFTER_HEALED_SIGHTINGS = 2   # gap still there after a re-sync that ran
ALERT_AFTER_ANY_SIGHTINGS = 4      # gap seen this many times regardless of heal outcome


def run_guard(
    report: Dict[str, Any],
    *,
    load_state: Callable[[], Optional[Dict[str, Any]]],
    save_state: Callable[[Dict[str, Any]], None],
    heal: Callable[[str], None],
    alert: Callable[[str, str], Any],
) -> Dict[str, Any]:
    """Decision logic; every side effect is injected so it can be tested."""
    # An unusable report (rebuild failed, or no drift fields) must not wipe the guard's memory:
    # it would restart every stuck gap's count and re-alert from scratch.
    if report.get("last_error") or ("all_missing_packages" not in report and "missing_packages" not in report):
        return {"gaps": 0, "healed": [], "persistent": 0, "alerted": False, "skipped": True}
    state = load_state() or {}
    prev_sightings: Dict[str, int] = state.get("sightings") or {}
    prev_heals: Dict[str, int] = state.get("heal_counts") or {}
    prev_healed_ok = set(state.get("healed_last_run") or [])
    alerted_hash = state.get("alerted_hash")

    gaps: List[Dict[str, Any]] = [
        p for p in (report.get("all_missing_packages") or report.get("missing_packages") or []) if p.get("missing_count")
    ]
    sightings = {g["folder_id"]: int(prev_sightings.get(g["folder_id"], 0)) + 1 for g in gaps}
    # A gap only counts as "survived a re-sync" if a re-sync of that folder actually succeeded
    # on the previous run.
    survived_heal = {g["folder_id"] for g in gaps if g["folder_id"] in prev_healed_ok}
    heal_counts = {g["folder_id"]: int(prev_heals.get(g["folder_id"], 0)) for g in gaps}

    healed_ok: List[str] = []
    candidates = sorted(
        (g for g in gaps if heal_counts[g["folder_id"]] < MAX_HEALS_PER_PACKAGE),
        key=lambda g: (heal_counts[g["folder_id"]], -g["missing_count"]),
    )
    for gap in candidates:
        if len(healed_ok) >= MAX_HEALS_PER_RUN:
            break
        try:
            heal(gap["folder_id"])
            healed_ok.append(gap["folder_id"])
            heal_counts[gap["folder_id"]] += 1
        except Exception:  # noqa: BLE001 - one bad package must not stop the others
            logger.exception("Drive drift guard could not re-sync %s", gap.get("path"))

    persistent = [
        g for g in gaps
        if (g["folder_id"] in survived_heal and sightings[g["folder_id"]] >= ALERT_AFTER_HEALED_SIGHTINGS)
        or sightings[g["folder_id"]] >= ALERT_AFTER_ANY_SIGHTINGS
    ]
    new_hash = None
    alert_sent = False
    if persistent:
        new_hash = hashlib.sha1(",".join(sorted(g["folder_id"] for g in persistent)).encode()).hexdigest()
        if new_hash != alerted_hash:
            lines = [f"{g['path']} — {g['missing_count']} of {g['media_count']} files not in the picker" for g in persistent[:6]]
            try:
                alert_sent = bool(alert(
                    f"{len(persistent)} Drive package(s) still have files missing from the picker",
                    "\n> ".join(lines) + "\nAn automatic re-sync did not fix them. Check Drive Package Health.",
                ))
            except Exception:  # noqa: BLE001
                logger.exception("Drive drift guard could not send its alert")
            if not alert_sent:
                new_hash = alerted_hash  # not delivered: try again next run rather than going quiet
        else:
            new_hash = alerted_hash
    save_state({
        "sightings": sightings,
        "heal_counts": heal_counts,
        "healed_last_run": healed_ok,
        "alerted_hash": new_hash,
    })
    return {"gaps": len(gaps), "healed": healed_ok, "persistent": len(persistent), "alerted": alert_sent}

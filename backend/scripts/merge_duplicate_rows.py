"""One-off cleanup: merge duplicate local campaign / ad set rows and drop CLAUDE TEST leftovers.

Why: legacy data has TWO local rows per Meta object — one created by the Ad Builder (id like
camp_… / adset_… / uuid) and one imported by /facebook/sync (id == the Meta id) — with ads and
auto-pause rules split between the copies. Sync only refreshed one copy, so the other stayed
"never synced" and showed stale status/budget.

What it does (LOCAL DATABASE ONLY — it never calls Meta):
  1. Deletes local rows whose name contains "CLAUDE TEST" (campaigns + ad sets; ads cascade).
     Aborts if any of them carries an auto-pause rule.
  2. For each duplicated fb_campaign_id: keeps one canonical row, re-points child ad sets to it,
     copies a missing account tag / brand, deletes the extra row.
  3. For each duplicated fb_adset_id: same, plus moves ads and auto-pause rules (dropping a rule or
     ad that is an exact duplicate of one the canonical row already has) and rule-log history.

Canonical row = tagged to an ad account > has synced_at > id equals the Meta id > most children.

Usage (inside the backend container, from /app):
    python scripts/merge_duplicate_rows.py            # dry run — prints the plan, changes nothing
    python scripts/merge_duplicate_rows.py --apply    # does it, in ONE transaction

Take a pg_dump of facebook_campaigns, facebook_adsets, facebook_ads, auto_pause_rules and
auto_pause_rule_logs first.
"""
import sys

from sqlalchemy import text

from app.database import SessionLocal

APPLY = "--apply" in sys.argv
db = SessionLocal()


def q(sql, **p):
    return db.execute(text(sql), p).fetchall()


def ex(sql, **p):
    return db.execute(text(sql), p)


def counts():
    return {t: q(f"select count(*) from {t}")[0][0] for t in (
        "facebook_campaigns", "facebook_adsets", "facebook_ads", "auto_pause_rules", "auto_pause_rule_logs")}


def pick(rows):
    """rows: list of dicts with id, fb_id, fb_account_id, synced_at, children, created_at."""
    return max(rows, key=lambda r: (
        r["fb_account_id"] is not None, r["synced_at"] is not None, r["id"] == r["fb_id"], r["children"],
        -r["created_at"].timestamp()))


def log(msg):
    print(("[apply] " if APPLY else "[dry-run] ") + msg)


before = counts()
print("BEFORE:", before)

# 1. CLAUDE TEST leftovers ---------------------------------------------------------------
test_camps = [r[0] for r in q("select id from facebook_campaigns where name ilike '%claude test%'")]
test_adsets = [r[0] for r in q(
    "select id from facebook_adsets where name ilike '%claude test%' or campaign_id = any(:ids)", ids=test_camps)]
rules_on_tests = q("select count(*) from auto_pause_rules where adset_id = any(:ids)", ids=test_adsets)[0][0]
if rules_on_tests:
    sys.exit(f"ABORT: {rules_on_tests} auto-pause rule(s) are attached to CLAUDE TEST ad sets — review by hand.")
test_ads = q("select count(*) from facebook_ads where adset_id = any(:ids)", ids=test_adsets)[0][0]
log(f"delete {len(test_camps)} CLAUDE TEST campaign rows, {len(test_adsets)} ad set rows, {test_ads} ad rows")
ex("delete from facebook_adsets where id = any(:ids)", ids=test_adsets)
ex("delete from facebook_campaigns where id = any(:ids)", ids=test_camps)

# 2. duplicate campaigns -------------------------------------------------------------------
for (fb,) in q("select fb_campaign_id from facebook_campaigns where fb_campaign_id is not null "
               "group by fb_campaign_id having count(*) > 1"):
    rows = [dict(id=r[0], fb_id=fb, fb_account_id=r[1], synced_at=r[2], created_at=r[3], brand=r[4], children=r[5])
            for r in q("""select c.id, c.fb_account_id, c.synced_at, c.created_at, c.brand_id,
                          (select count(*) from facebook_adsets a where a.campaign_id = c.id)
                          from facebook_campaigns c where c.fb_campaign_id = :fb""", fb=fb)]
    keep = pick(rows)
    for dup in (r for r in rows if r["id"] != keep["id"]):
        log(f"campaign {fb}: keep {keep['id']} (acct={keep['fb_account_id']}), merge {dup['id']} "
            f"(acct={dup['fb_account_id']}, {dup['children']} ad sets)")
        ex("update facebook_adsets set campaign_id = :k where campaign_id = :d", k=keep["id"], d=dup["id"])
        if keep["fb_account_id"] is None and dup["fb_account_id"] is not None:
            ex("update facebook_campaigns set fb_account_id = :a where id = :k", a=dup["fb_account_id"], k=keep["id"])
            keep["fb_account_id"] = dup["fb_account_id"]
        if keep["brand"] is None and dup["brand"] is not None:
            ex("update facebook_campaigns set brand_id = :b where id = :k", b=dup["brand"], k=keep["id"])
        ex("delete from facebook_campaigns where id = :d", d=dup["id"])

# 3. duplicate ad sets ---------------------------------------------------------------------
RULE_KEY = "coalesce(metric,''), coalesce(operator,''), coalesce(threshold,-1), coalesce(min_spend,-1), " \
           "coalesce(action,''), coalesce(scope,''), coalesce(fb_ad_id,'')"
for (fb,) in q("select fb_adset_id from facebook_adsets where fb_adset_id is not null "
               "group by fb_adset_id having count(*) > 1"):
    rows = [dict(id=r[0], fb_id=fb, fb_account_id=r[1], synced_at=r[2], created_at=r[3], brand=r[4], children=r[5])
            for r in q("""select a.id, a.fb_account_id, a.synced_at, a.created_at, a.brand_id,
                          (select count(*) from facebook_ads x where x.adset_id = a.id)
                          + (select count(*) from auto_pause_rules r where r.adset_id = a.id)
                          from facebook_adsets a where a.fb_adset_id = :fb""", fb=fb)]
    keep = pick(rows)
    for dup in (r for r in rows if r["id"] != keep["id"]):
        dup_ads = q("select count(*) from facebook_ads where adset_id = :d", d=dup["id"])[0][0]
        dup_rules = q("select count(*) from auto_pause_rules where adset_id = :d", d=dup["id"])[0][0]
        log(f"ad set {fb}: keep {keep['id']}, merge {dup['id']} ({dup_ads} ads, {dup_rules} rules)")
        # ads: drop an ad the canonical row already has (same Meta ad id), move the rest
        ex("""delete from facebook_ads d using facebook_ads k
              where d.adset_id = :d and k.adset_id = :k and d.fb_ad_id is not null and d.fb_ad_id = k.fb_ad_id""",
           d=dup["id"], k=keep["id"])
        ex("update facebook_ads set adset_id = :k where adset_id = :d", k=keep["id"], d=dup["id"])
        # rules: drop exact duplicates of a rule the canonical row already has, move the rest
        ex(f"""delete from auto_pause_rules d where d.adset_id = :d and exists (
                 select 1 from auto_pause_rules k where k.adset_id = :k
                 and (coalesce(k.metric,''), coalesce(k.operator,''), coalesce(k.threshold,-1), coalesce(k.min_spend,-1),
                      coalesce(k.action,''), coalesce(k.scope,''), coalesce(k.fb_ad_id,''))
                   = (coalesce(d.metric,''), coalesce(d.operator,''), coalesce(d.threshold,-1), coalesce(d.min_spend,-1),
                      coalesce(d.action,''), coalesce(d.scope,''), coalesce(d.fb_ad_id,'')))""",
           d=dup["id"], k=keep["id"])
        ex("update auto_pause_rules set adset_id = :k where adset_id = :d", k=keep["id"], d=dup["id"])
        ex("update auto_pause_rule_logs set adset_id = :k where adset_id = :d", k=keep["id"], d=dup["id"])
        if keep["fb_account_id"] is None and dup["fb_account_id"] is not None:
            ex("update facebook_adsets set fb_account_id = :a where id = :k", a=dup["fb_account_id"], k=keep["id"])
            keep["fb_account_id"] = dup["fb_account_id"]
        if keep["brand"] is None and dup["brand"] is not None:
            ex("update facebook_adsets set brand_id = :b where id = :k", b=dup["brand"], k=keep["id"])
        ex("delete from facebook_adsets where id = :d", d=dup["id"])

after = counts()
remaining = (q("select count(*) from (select fb_campaign_id from facebook_campaigns where fb_campaign_id is not null "
               "group by fb_campaign_id having count(*) > 1) t")[0][0],
             q("select count(*) from (select fb_adset_id from facebook_adsets where fb_adset_id is not null "
               "group by fb_adset_id having count(*) > 1) t")[0][0])
print("AFTER :", after)
print("remaining duplicate groups (campaigns, ad sets):", remaining)

if APPLY:
    db.commit()
    print("COMMITTED")
else:
    db.rollback()
    print("DRY RUN — rolled back, nothing changed. Re-run with --apply to commit.")
db.close()

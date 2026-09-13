import os
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.adimage import AdImage
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.advideo import AdVideo
from facebook_business.exceptions import FacebookRequestError
from dotenv import load_dotenv
from pathlib import Path
from facebook_business.adobjects.user import User
import time

# Load .env from project root (parent of backend)
env_path = Path(__file__).resolve().parent.parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)


class FacebookAPIError(RuntimeError):
    """Raised when Meta's Graph API rejects a call. Carries the numeric error
    code/subcode through to the HTTP layer so callers (e.g. the Bulk Match
    Import loop) can detect rate-limit/throttle responses (codes 17, 613,
    80000-80014) instead of just getting a flattened string message."""

    def __init__(self, message, code=None, subcode=None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode


class FacebookService:
    def __init__(self):
        # Try standard names first, then VITE_ prefixed names (common in this project)
        self.access_token = os.getenv("FACEBOOK_ACCESS_TOKEN") or os.getenv("VITE_FACEBOOK_ACCESS_TOKEN")
        self.ad_account_id = os.getenv("FACEBOOK_AD_ACCOUNT_ID") or os.getenv("VITE_FACEBOOK_AD_ACCOUNT_ID")
        self.app_id = os.getenv("FACEBOOK_APP_ID") or os.getenv("VITE_FACEBOOK_APP_ID")
        self.app_secret = os.getenv("FACEBOOK_APP_SECRET") or os.getenv("VITE_FACEBOOK_APP_SECRET")
        self.api = None
        self.account = None
        
        if self.access_token and self.ad_account_id:
            self.initialize()

    def initialize(self):
        """Initialize the Facebook API connection."""
        try:
            FacebookAdsApi.init(
                app_id=self.app_id,
                app_secret=self.app_secret,
                access_token=self.access_token
            )
            self.api = FacebookAdsApi.get_default_api()
            
            # Only set up the AdAccount object if we have an ID
            if self.ad_account_id:
                # Ensure ad account ID has 'act_' prefix
                account_id = self.ad_account_id
                if not account_id.startswith('act_'):
                    account_id = f'act_{account_id}'
                self.account = AdAccount(account_id)
            
            return True
        except Exception as e:
            # Re-raise the exception so the caller knows what went wrong
            raise Exception(f"Facebook API Init Error: {str(e)}")


    def get_ad_accounts(self):
        """Fetch all ad accounts for the current user."""
        if not self.api:
            # Try to initialize if not already done
            self.initialize()
        
        # Use the SDK's User object to fetch ad accounts
        print("Fetching ad accounts for user 'me'...")
        try:
            me = User(fbid='me', api=self.api)
            # timezone_name / timezone_offset_hours_utc matter for money, not display:
            # Meta reports insights on the AD ACCOUNT's billing day, while
            # Switchboard revenue is pulled on a timezone we choose. If the two
            # drift apart, spend and revenue land in different day buckets and the
            # P&L is quietly wrong. These were never requested before, so the app
            # could not even see that an account had changed timezone — which is
            # exactly what happened on 2026-08-06.
            #
            # Derive day boundaries from `timezone_name` (IANA) ONLY. Meta gives no
            # DST contract for `timezone_offset_hours_utc` — it tracks the account's
            # current local offset and can move across a DST transition, so
            # arithmetic on it silently breaks twice a year. It is informational.
            #
            # Adding a field here is not free: Graph validates `fields` as a whole
            # and 400s the ENTIRE call on one unknown name, which would take out
            # every ad-account picker in the app. Verify a field exists in the SDK's
            # adaccount.py before adding it.
            my_accounts = me.get_ad_accounts(fields=[
                'id', 'name', 'account_id', 'account_status', 'currency',
                'balance', 'amount_spent', 'spend_cap',
                'timezone_name', 'timezone_offset_hours_utc',
            ])
            print(f"Found {len(my_accounts)} accounts.")
            return [dict(acc) for acc in my_accounts]
        except Exception as e:
            print(f"Error fetching ad accounts: {e}")
            raise e

    # Meta returns usage telemetry on the headers of EVERY Graph response. These
    # are the three it uses; which ones appear depends on the endpoint and token.
    #   x-business-use-case-usage — per ad account, the one that matters here
    #   x-app-usage               — per app, shared across every account
    #   x-ad-account-usage        — older per-account header, still sent sometimes
    USAGE_HEADERS = (
        'x-business-use-case-usage',
        'x-app-usage',
        'x-ad-account-usage',
    )

    @staticmethod
    def _header_lookup(headers, name):
        """Case-insensitive header read.

        requests gives the SDK a CaseInsensitiveDict for normal calls, but the
        SDK's batch path constructs FacebookResponse with a plain dict — so we
        cannot rely on the mapping being case-insensitive.
        """
        if not headers:
            return None
        try:
            direct = headers.get(name)
        except AttributeError:
            return None
        if direct is not None:
            return direct
        lowered = name.lower()
        for key, value in headers.items():
            if str(key).lower() == lowered:
                return value
        return None

    @staticmethod
    def _meta_error(e, prefix):
        """Build a FacebookAPIError that preserves Meta's numeric code/subcode.

        Without the code, the HTTP layer can only forward a flattened string and
        callers lose the ability to tell a throttle (17 / 613 / 80000-family)
        apart from a real rejection.
        """
        body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
        err = body.get('error', {}) if isinstance(body, dict) else {}
        user_msg = err.get('error_user_msg') or err.get('message') or (
            e.api_error_message() if hasattr(e, 'api_error_message') and callable(e.api_error_message) else str(e)
        )
        code = e.api_error_code() if hasattr(e, 'api_error_code') and callable(e.api_error_code) else err.get('code')
        subcode = e.api_error_subcode() if hasattr(e, 'api_error_subcode') and callable(e.api_error_subcode) else err.get('error_subcode')
        return FacebookAPIError(f"{prefix}: {user_msg}", code=code, subcode=subcode)

    def get_rate_limit_usage(self, ad_account_id=None):
        """Report how much of Meta's rate-limit budget this ad account has used.

        Meta only reports usage on the headers of a real response, so this makes
        the cheapest call available — reading just `id` off the ad account — and
        parses the headers off it. One extra request buys an accurate reading,
        because the counters reflect every call made before it.

        Returns a dict that is always safe to render:
            {
              "account_id": "act_123",
              "usage": {"call_count": 28, "total_cputime": 25, "total_time": 25,
                        "estimated_time_to_regain_access": 0, "type": "ads_management"},
              "app_usage": {...} | None,
              "source": "x-ad-account-usage" | "x-business-use-case-usage" | "x-app-usage" | None,
              "scope": "ad_account" | "business" | "app" | None,
              "available": True/False,
            }

        `available: False` means Meta sent no usage headers. Callers must treat
        that as "unknown", never as zero — reporting 0% when we simply could not
        read it would be worse than saying nothing.
        """
        account = self._get_account(ad_account_id)
        account_id = account.get_id_assured() if hasattr(account, 'get_id_assured') else str(account)

        try:
            response = self.api.call('GET', (account_id,), params={'fields': 'id'})
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            user_msg = err.get('error_user_msg') or err.get('message') or str(e)
            code = e.api_error_code() if hasattr(e, 'api_error_code') and callable(e.api_error_code) else err.get('code')
            subcode = e.api_error_subcode() if hasattr(e, 'api_error_subcode') and callable(e.api_error_subcode) else err.get('error_subcode')
            raise FacebookAPIError(f"Facebook API: {user_msg}", code=code, subcode=subcode) from e

        headers = response.headers() if hasattr(response, 'headers') and callable(response.headers) else {}

        result = {
            'account_id': account_id,
            'usage': None,
            'app_usage': None,
            'source': None,
            'scope': None,
            'available': False,
        }

        app_raw = self._header_lookup(headers, 'x-app-usage')
        if app_raw:
            parsed = self._parse_usage_header(app_raw, account_id, 'x-app-usage')
            if parsed:
                parsed.pop('_key_matched_account', None)
                result['app_usage'] = parsed

        # x-ad-account-usage is per ad account by definition, so it goes first.
        #
        # x-business-use-case-usage CAN be keyed by Business Manager id, in which
        # case its counters aggregate several ad accounts — but a live response
        # on 2026-09-10 came back keyed by the ad account id instead. Rather than
        # assume either way, _parse_usage_header reports whether the key matched
        # the account we asked about and the scope is labelled from that.
        for header_name, default_scope in (
            ('x-ad-account-usage', 'ad_account'),
            ('x-business-use-case-usage', 'business'),
        ):
            raw = self._header_lookup(headers, header_name)
            if not raw:
                continue
            parsed = self._parse_usage_header(raw, account_id, header_name)
            if parsed:
                matched = parsed.pop('_key_matched_account', False)
                result['usage'] = parsed
                result['source'] = header_name
                # x-ad-account-usage is per-account by definition. The
                # business-use-case header is only per-account when its key was
                # actually this account id — otherwise it is aggregated.
                result['scope'] = 'ad_account' if (default_scope == 'ad_account' or matched) else 'business'
                result['available'] = True
                break

        if not result['available'] and result['app_usage']:
            # App-level is shared by every account this app touches — the least
            # specific reading, but better than showing nothing. Labelled as such.
            result['usage'] = result['app_usage']
            result['source'] = 'x-app-usage'
            result['scope'] = 'app'
            result['available'] = True

        return result

    @staticmethod
    def _parse_usage_header(raw, account_id, header_name=None):
        """Normalize a Meta usage header into a flat dict of percentages.

        The headers are JSON but not one consistent shape:
          x-business-use-case-usage -> {"<id>": [{...}, ...]}  (keyed, list per id)
          x-app-usage               -> {...}                    (flat object)
        Returns None on anything unparseable — a malformed header must not take
        down the caller, since this is telemetry, not a result.
        """
        import json as _json

        if isinstance(raw, (dict, list)):
            data = raw
        else:
            try:
                data = _json.loads(raw)
            except (TypeError, ValueError):
                return None

        entry = None
        # Whether the header key is THIS ad account, which decides how the
        # reading may be labelled. Verified against a live response 2026-09-10:
        # x-business-use-case-usage came back keyed by the ad account id
        # (521142087204815), not a Business Manager id. It can be keyed by
        # business id in other setups, so this is detected per response rather
        # than assumed either way — mislabelling business-wide usage as "this
        # account" (or the reverse) tells a media buyer something untrue.
        key_matched_account = False
        if isinstance(data, dict):
            numeric_id = str(account_id).replace('act_', '')
            for key in (numeric_id, str(account_id)):
                if key in data:
                    entry = data[key]
                    key_matched_account = True
                    break
            if entry is None:
                values = [v for v in data.values() if isinstance(v, (list, dict))]
                if len(values) == 1:
                    # A single entry under a key we don't recognise — most likely
                    # a business id aggregating several ad accounts. Usable, but
                    # it must not be presented as this account's own usage.
                    entry = values[0]
                elif not values:
                    entry = data  # flat shape, e.g. x-app-usage
        elif isinstance(data, list):
            entry = data

        if isinstance(entry, list):
            if not entry:
                return None
            # More than one use-case can be reported; the binding constraint is
            # whichever is highest, so surface that one rather than the first.
            def _peak(item):
                if not isinstance(item, dict):
                    return -1
                return max(
                    [float(item.get(k) or 0) for k in ('call_count', 'total_cputime', 'total_time')]
                    or [-1]
                )
            entry = max(entry, key=_peak)

        if not isinstance(entry, dict):
            return None

        out = {}
        for field in ('call_count', 'total_cputime', 'total_time'):
            if field in entry:
                try:
                    out[field] = float(entry[field])
                except (TypeError, ValueError):
                    pass

        # UNIT TRAP: Meta reports the wait in different units per header.
        #   x-business-use-case-usage.estimated_time_to_regain_access -> MINUTES
        #   x-ad-account-usage.reset_time_duration                    -> SECONDS
        # Normalize both to SECONDS here so nothing downstream has to know which
        # header answered. Treating the business-use-case value as seconds
        # understated a 30-minute lockout as "about 1 minute", which would send a
        # buyer straight back into a still-throttled account.
        if 'estimated_time_to_regain_access' in entry:
            try:
                minutes = float(entry['estimated_time_to_regain_access'])
                out['estimated_time_to_regain_access'] = minutes * 60
            except (TypeError, ValueError):
                pass

        # x-ad-account-usage is a different shape entirely: a single
        # `acc_id_util_pct` percentage plus a reset window, no per-metric
        # breakdown. Map it onto call_count so callers have one field to read
        # regardless of which header answered.
        if 'call_count' not in out and 'acc_id_util_pct' in entry:
            try:
                out['call_count'] = float(entry['acc_id_util_pct'])
            except (TypeError, ValueError):
                pass
        # Already seconds — no conversion, unlike the business-use-case field above.
        if 'reset_time_duration' in entry and 'estimated_time_to_regain_access' not in out:
            try:
                out['estimated_time_to_regain_access'] = float(entry['reset_time_duration'])
            except (TypeError, ValueError):
                pass

        if entry.get('type'):
            out['type'] = entry['type']

        # Capture this BEFORE adding the marker below. The marker is always set,
        # so it would make `out` unconditionally truthy and turn the "nothing
        # parseable in this header" case into a reading that looks available but
        # carries no numbers.
        had_data = bool(out)

        # Consumed by get_rate_limit_usage to label scope; stripped before the
        # dict is returned to callers.
        out['_key_matched_account'] = key_matched_account
        # Which limit tier the account is on materially changes what these
        # percentages are measured against — worth surfacing, not dropping.
        if entry.get('ads_api_access_tier'):
            out['access_tier'] = entry['ads_api_access_tier']
            had_data = True
        return out if had_data else None

    def _get_account(self, ad_account_id=None):
        """Helper to get AdAccount object."""
        if ad_account_id:
            if not ad_account_id.startswith('act_'):
                ad_account_id = f'act_{ad_account_id}'
            return AdAccount(ad_account_id, api=self.api)
        
        if self.account:
            return self.account
            
        raise Exception("No Ad Account ID provided and no default account set.")

    def get_campaigns(self, ad_account_id=None, effective_status=None):
        """Fetch campaigns from the ad account.

        `effective_status` defaults to ACTIVE+PAUSED (the original behavior,
        tuned for the ad-push modal — it should only offer currently-usable
        campaigns). Pass an explicit list (e.g. including 'ARCHIVED') for
        anything that needs the FULL campaign history — notably the
        /facebook/sync ad-set backfill that P&L's Everflow revenue attribution
        depends on: an ad set under an archived campaign is still a real,
        revenue-generating ad set, and excluding it here made it invisible to
        the local FacebookAdSet table, which under-attributed real billable
        revenue to the account that actually earned it (confirmed live
        2026-09-09 — ~$9.1k/month of RHO + RHO 4's own Everflow revenue was
        sitting on ad sets under archived campaigns and never synced).
        """
        account = self._get_account(ad_account_id)

        fields = [
            Campaign.Field.id,
            Campaign.Field.name,
            Campaign.Field.objective,
            Campaign.Field.status,
            Campaign.Field.daily_budget,
            Campaign.Field.lifetime_budget,
            Campaign.Field.budget_remaining,
            Campaign.Field.bid_strategy,
            Campaign.Field.stop_time,
            Campaign.Field.start_time,
            Campaign.Field.special_ad_categories,
            'is_adset_budget_sharing_enabled',
        ]

        # Fetch up to 500 campaigns.
        params = {
            'limit': 500,
            'effective_status': effective_status or ['ACTIVE', 'PAUSED'],
        }
        return account.get_campaigns(fields=fields, params=params)

    def create_campaign(self, campaign_data, ad_account_id=None):
        """Create a new campaign."""
        account = self._get_account(ad_account_id)

        params = {
            Campaign.Field.name: campaign_data.get('name'),
            Campaign.Field.objective: campaign_data.get('objective'),
            Campaign.Field.status: campaign_data.get('status', 'PAUSED'),
            # special_ad_categories is required by Meta — always send the array (empty = no restriction)
            Campaign.Field.special_ad_categories: campaign_data.get('specialAdCategories') or [],
        }

        budget_type = campaign_data.get('budget_type') or campaign_data.get('budgetType')
        budget_schedule = (campaign_data.get('budgetScheduleType') or campaign_data.get('budget_schedule_type') or 'DAILY').upper()

        if budget_type == 'CBO':
            if budget_schedule == 'LIFETIME':
                lifetime_budget = campaign_data.get('lifetime_budget') or campaign_data.get('lifetimeBudget')
                if lifetime_budget:
                    params[Campaign.Field.lifetime_budget] = int(float(lifetime_budget) * 100)
                end_time = campaign_data.get('end_time') or campaign_data.get('endTime')
                if end_time:
                    params[Campaign.Field.stop_time] = end_time
            else:
                daily_budget = campaign_data.get('daily_budget') or campaign_data.get('dailyBudget')
                if daily_budget:
                    params[Campaign.Field.daily_budget] = int(float(daily_budget) * 100)
        else:
            # ABO: budget managed at ad set level
            params['is_adset_budget_sharing_enabled'] = False

        bid_strategy = campaign_data.get('bid_strategy') or campaign_data.get('bidStrategy')
        if bid_strategy:
            params[Campaign.Field.bid_strategy] = bid_strategy

        try:
            return account.create_campaign(params=params)
        except FacebookRequestError as e:
            err = e.api_error_subcode() and {} or {}
            try:
                err = e.body().get('error', {})
            except Exception:
                pass
            user_msg = err.get('error_user_msg') or err.get('message') or (e.api_error_message() if hasattr(e, 'api_error_message') and callable(e.api_error_message) else str(e))
            raise RuntimeError(f"Facebook API: {user_msg}") from e


    def get_pixels(self, ad_account_id=None):
        """Fetch all pixels for the ad account."""
        from facebook_business.adobjects.adspixel import AdsPixel
        
        account = self._get_account(ad_account_id)
        
        fields = [
            AdsPixel.Field.id,
            AdsPixel.Field.name,
        ]
        
        pixels = account.get_ads_pixels(fields=fields)
        return [dict(pixel) for pixel in pixels]

    def get_pages(self, ad_account_id=None):
        """Fetch all Facebook Pages accessible to the user."""
        from facebook_business.adobjects.page import Page
        from facebook_business.adobjects.user import User
        
        # Fetch pages for the current user (not ad account specific)
        me = User(fbid='me', api=self.api)
        
        fields = [
            Page.Field.id,
            Page.Field.name,
            Page.Field.access_token,
            Page.Field.category,
        ]
        
        pages = me.get_accounts(fields=fields)
        result = [dict(page) for page in pages]
        if result:
            return result

        # Fallback: personal tokens without pages_show_list return an empty
        # me/accounts even though the token can still USE pages in creatives.
        # Derive the pages actually in use from this ad account's recent ad
        # creatives (single API call via field expansion), then resolve names.
        # Without this the Push modal's page dropdown is empty and users type
        # the page's public-profile ID, which Meta rejects (error 1443121).
        try:
            account = self._get_account(ad_account_id)
            page_ids = []
            scanned = 0
            for ad in account.get_ads(fields=['creative{object_story_spec}'], params={'limit': 100}):
                scanned += 1
                oss = ((dict(ad).get('creative') or {}).get('object_story_spec') or {})
                pid = str(oss.get('page_id') or '')
                if pid and pid not in page_ids:
                    page_ids.append(pid)
                if scanned >= 200 or len(page_ids) >= 5:
                    break
            derived = []
            for pid in page_ids:
                try:
                    pg = dict(Page(pid).api_get(fields=['id', 'name']))
                    derived.append({'id': pg.get('id', pid), 'name': pg.get('name', f'Page {pid}'), 'category': None})
                except Exception:
                    derived.append({'id': pid, 'name': f'Page {pid}', 'category': None})
            return derived
        except Exception as e:
            print(f"⚠️  get_pages fallback (derive from creatives) failed: {e}")
            return []

    def get_adsets(self, ad_account_id=None, campaign_id=None):
        """Fetch all ad sets and enrich each with parent campaign objective + name.

        The Meta SDK rejects nested field syntax ('campaign{objective,name}') with a UserWarning
        and silently drops it. Instead we fetch campaigns separately (1 extra API call) and
        inject a 'campaign' dict into each adset so the UI can group by campaign and detect
        OUTCOME_LEADS without SDK warnings.
        """
        adset_fields = [
            AdSet.Field.id,
            AdSet.Field.name,
            AdSet.Field.status,
            AdSet.Field.daily_budget,
            AdSet.Field.lifetime_budget,
            AdSet.Field.targeting,
            AdSet.Field.optimization_goal,
            AdSet.Field.billing_event,
            AdSet.Field.bid_amount,
            AdSet.Field.promoted_object,
            AdSet.Field.campaign_id,
            AdSet.Field.start_time,
            AdSet.Field.end_time,
        ]
        campaign_fields = [Campaign.Field.id, Campaign.Field.name, Campaign.Field.objective]

        if campaign_id:
            camp_obj = Campaign(campaign_id, api=self.api)
            adsets = list(camp_obj.get_ad_sets(fields=adset_fields))
            # Single campaign — fetch its meta directly
            try:
                camp_data = camp_obj.api_get(fields=campaign_fields)
                campaign_map = {campaign_id: {'name': camp_data.get('name'), 'objective': camp_data.get('objective')}}
            except Exception:
                campaign_map = {}
        else:
            account = self._get_account(ad_account_id)
            adsets = list(account.get_ad_sets(fields=adset_fields))
            # Fetch all campaigns for this account and build a lookup map
            try:
                campaigns = account.get_campaigns(fields=campaign_fields)
                campaign_map = {c['id']: {'name': c.get('name'), 'objective': c.get('objective')} for c in campaigns}
            except Exception:
                campaign_map = {}

        # Inject campaign dict into each adset (mirrors the shape the frontend expects)
        for adset in adsets:
            cid = adset.get(AdSet.Field.campaign_id)
            if cid and cid in campaign_map:
                adset['campaign'] = campaign_map[cid]

        return adsets

    # Ad set effective_status values Meta's account-level /adsets edge accepts
    # as an explicit filter. VERIFIED LIVE against act_521142087204815 on
    # 2026-09-12 — do NOT extend this from the SDK's enum constants or from
    # memory. A value the edge rejects hard-errors the entire call, and (worse,
    # because it fails silently) a narrower list drops ad sets. See the
    # two-pass explanation in get_all_adsets_for_account.
    _ADSET_ARCHIVED_FILTER = ['ACTIVE', 'PAUSED', 'ARCHIVED']

    # Do NOT add 'DELETED' here or as a third pass. It is a documented ad set
    # effective_status value, but the act_{id}/adsets edge REJECTS it as a
    # filter — verified live 2026-09-12, it returns error 100 "Invalid
    # parameter", which would hard-fail the whole sync. Coverage was checked
    # the useful way instead: every ad set Everflow attributes revenue to on
    # this account falls inside the two-pass union (2026-09-12, $16,472.53 of
    # $16,472.53 matched), so no revenue-bearing ad set is being missed.

    # Meta error codes that mean "throttled, try again" rather than "this call
    # is wrong". Mirrors the set used by the sync endpoint.
    _RATE_LIMIT_CODES = {4, 17, 32, 613, 80004}

    def get_all_adsets_for_account(self, ad_account_id=None):
        """Fetch EVERY ad set on an account in ~2 paginated calls, not one per campaign.

        Returns (adsets, failures) — `failures` is a list of human-readable
        strings, one per pass that could not be completed. An empty list means
        the result is complete. Callers MUST surface a non-empty `failures`
        rather than treating a short list as a full sync: reporting a truncated
        sync as complete is the exact failure mode this function exists to kill.

        Why this exists
        ---------------
        The /facebook/sync backfill used to call get_adsets(campaign_id=...)
        once per campaign. On RHO (act_521142087204815, 92 campaigns) that
        burst reliably trips Meta's per-ad-account rate limit (code 17) partway
        through, truncating the sync and silently leaving real ad sets out of
        the FacebookAdSet table — and with them the Everflow revenue that P&L
        attributes by matching against that table. Confirmed live twice:
        2026-09-11 (0/92 calls got through) and 2026-09-12 (57/92 still failed
        at 2am, so it was never just daytime contention from the team using the
        app). Meta's account-level /adsets edge returns the same ad sets for the
        whole account through one paginated cursor, cutting ~92 calls to ~2 and
        removing the burst rather than pacing it.

        Why TWO passes and not one
        --------------------------
        Neither query alone is complete. Verified live on RHO, 2026-09-12:
          * no effective_status          -> 211 ad sets. Includes DERIVED
            statuses (CAMPAIGN_PAUSED, ADSET_PAUSED, ...) but excludes archived.
          * effective_status=[A,P,ARCH]  -> 261 ad sets. Picks up the archived
            ones but DROPS every derived status, because an explicit filter
            matches effective_status exactly — two of the ten ad sets this bug
            was reported for are CAMPAIGN_PAUSED and disappear from this pass.
        The union of both is the real answer, which is why the "obvious" fix of
        just adding ARCHIVED to a single call would still have lost ad sets.
        """
        fields = [
            AdSet.Field.id,
            AdSet.Field.name,
            AdSet.Field.status,
            AdSet.Field.effective_status,
            AdSet.Field.daily_budget,
            AdSet.Field.lifetime_budget,
            AdSet.Field.optimization_goal,
            AdSet.Field.campaign_id,
        ]
        account = self._get_account(ad_account_id)

        # Unfiltered pass FIRST so its rows win on dedupe — they carry the
        # live/derived effective_status, which is the more accurate view.
        passes = [
            ("unfiltered", {'limit': 500}),
            ("archived", {'limit': 500, 'effective_status': self._ADSET_ARCHIVED_FILTER}),
        ]

        merged = {}
        failures = []
        for idx, (label, params) in enumerate(passes):
            if idx:
                # Space the two passes slightly — a large account paginates a
                # few times per pass and back-to-back bursts are what Meta
                # actually throttles on.
                time.sleep(2)
            try:
                rows = self._fetch_adsets_pass(account, fields, params)
            except Exception as e:
                # _meta_error returns a FacebookAPIError carrying Meta's numeric
                # code; we only want its message text here, not to raise it.
                try:
                    detail = str(self._meta_error(e, 'adsets'))
                except Exception:
                    detail = str(e)[:300]
                # Pass Meta's own wait estimate through verbatim (unit unstated
                # by Meta on this field — do not do arithmetic on it), so a
                # human reading the sync result knows roughly when to re-run.
                try:
                    est = (e.body() or {}).get('error', {}).get('error_data', {}).get('estimated_time_to_regain_access')
                    if est:
                        detail += f" (Meta estimated_time_to_regain_access={est})"
                except Exception:
                    pass
                failures.append(f"{label} pass failed: {detail}")
                continue
            for row in rows:
                fb_id = str(row.get('id') or '')
                if fb_id:
                    merged.setdefault(fb_id, row)

        return list(merged.values()), failures

    def _fetch_adsets_pass(self, account, fields, params, retries=2):
        """One paginated /adsets pass, retried only on a real rate-limit code.

        A non-rate-limit error (bad params, permissions) is raised immediately —
        retrying that just burns the account's remaining budget and misreports a
        real API error as throttling.
        """
        delay = 10
        for attempt in range(retries + 1):
            try:
                return list(account.get_ad_sets(fields=fields, params=params))
            except FacebookRequestError as e:
                code = e.api_error_code() if hasattr(e, 'api_error_code') else None
                if code not in self._RATE_LIMIT_CODES or attempt == retries:
                    raise
                # Deliberately a fixed short backoff rather than sleeping for
                # Meta's estimated_time_to_regain_access. That value's unit is
                # ambiguous (documented as MINUTES on the
                # X-Business-Use-Case-Usage header; the error body's copy is
                # undocumented), and guessing wrong is either a 60x under-sleep
                # that re-trips the limit or a multi-minute hang inside an HTTP
                # request. Out-waiting an ad-account throttle is not this
                # endpoint's job — it retries briefly, then reports the failure
                # so the caller can re-run. The estimate is surfaced in the
                # error text for whoever reads it, not acted on numerically.
                print(f"⚠️  get_all_adsets_for_account: rate limited (code {code}), waiting {delay}s before retry {attempt + 1}/{retries}")
                time.sleep(delay)
                delay *= 2
        # Unreachable: the final attempt either returns or re-raises above.
        raise RuntimeError("adsets pass exhausted retries without returning or raising")

    def get_lead_forms(self, page_id):
        """Fetch active lead gen forms for a Facebook Page.

        The leadgen_forms endpoint requires a page-scoped access token, not a user token.
        We obtain it by calling get_pages() (which returns full page data including tokens)
        and constructing a scoped API instance.
        """
        try:
            from facebook_business.adobjects.page import Page
            from facebook_business.adobjects.leadgenform import LeadgenForm
            from facebook_business.session import FacebookSession
        except ImportError as e:
            raise RuntimeError(
                f"facebook-business SDK missing required module: {e}. Upgrade to >= 3.0"
            ) from e

        # Get the page access token — leadgen_forms requires a page-scoped token
        pages = self.get_pages()
        page_data = next((p for p in pages if p.get('id') == page_id), None)
        page_token = page_data.get('access_token') if page_data else None

        if page_token and self.app_id and self.app_secret:
            page_api = FacebookAdsApi(FacebookSession(self.app_id, self.app_secret, page_token))
            page = Page(page_id, api=page_api)
        else:
            # Fallback: user token (works if user has manage_pages + ads_management)
            page = Page(page_id, api=self.api)

        fields = [
            LeadgenForm.Field.id,
            LeadgenForm.Field.name,
            LeadgenForm.Field.status,
            LeadgenForm.Field.locale,
        ]
        forms = page.get_lead_gen_forms(fields=fields)
        return [dict(f) for f in forms]

    def get_ads(self, adset_id):
        """Fetch all ads for a specific ad set.

        Meta's default effective_status filter on this edge excludes PAUSED
        objects (confirmed against this app's own pattern at get_adsets/
        get_adset_name_map/get_account_insights_bulk, which already pass this
        explicit filter for the same reason) -- and every ad this app creates
        defaults to PAUSED. Without this, a freshly-created, genuinely
        successful ad is invisible to this call until manually activated.
        """
        adset = AdSet(adset_id, api=self.api)
        fields = [
            Ad.Field.id,
            Ad.Field.name,
            Ad.Field.status,
            Ad.Field.creative,
        ]
        return adset.get_ads(fields=fields, params={'effective_status': ['ACTIVE', 'PAUSED']})

    # HEC = Housing, Employment, Credit (Financial Products) — Meta enforces targeting restrictions
    HEC_CATEGORIES = {'HOUSING', 'EMPLOYMENT', 'FINANCIAL_PRODUCTS_SERVICES'}

    def create_adset(self, adset_data, ad_account_id=None):
        """Create a new ad set."""
        account = self._get_account(ad_account_id)

        # Detect HEC special ad categories on the parent campaign
        special_categories = set(adset_data.get('specialAdCategories') or adset_data.get('special_ad_categories') or [])
        is_hec = bool(special_categories & self.HEC_CATEGORIES)
        # Surfaced to the frontend so Joel sees what Meta's HEC rules silently dropped,
        # instead of a targeting mismatch only showing up days later in performance.
        hec_stripped_fields = []

        # Transform targeting from camelCase to snake_case
        targeting = adset_data.get('targeting', {})
        transformed_targeting = {}

        # Handle age fields — HEC: Meta enforces default 18/65+, so we omit custom ranges
        if not is_hec:
            if 'ageMin' in targeting:
                transformed_targeting['age_min'] = targeting['ageMin']
            if 'ageMax' in targeting:
                transformed_targeting['age_max'] = targeting['ageMax']
        elif 'ageMin' in targeting or 'ageMax' in targeting:
            hec_stripped_fields.append('age range (Meta forces default 18–65+ for Housing/Employment/Credit)')

        # Handle genders — HEC: must not filter by gender (omit or pass empty array)
        if 'genders' in targeting and not is_hec:
            transformed_targeting['genders'] = targeting['genders']
        elif 'genders' in targeting and is_hec:
            hec_stripped_fields.append('gender targeting')

        # Handle geo_locations - clean up empty arrays
        if 'geo_locations' in targeting:
            geo_locs = targeting['geo_locations']
            cleaned_geo_locs = {}

            # Keys blocked under HEC: cities, geo_markets, and ALL excluded_* keys
            hec_blocked_keys = {'cities', 'geo_markets', 'excluded_countries', 'excluded_regions',
                                 'excluded_cities', 'excluded_geo_markets'}
            stripped_geo_keys = []

            for key, value in geo_locs.items():
                if is_hec and key in hec_blocked_keys:
                    stripped_geo_keys.append(key)
                    continue  # Strip — Meta will hard-error if these are present
                if isinstance(value, list) and len(value) > 0:
                    cleaned_geo_locs[key] = value
                elif not isinstance(value, list):
                    cleaned_geo_locs[key] = value

            if stripped_geo_keys:
                hec_stripped_fields.append(f"geo targeting: {', '.join(sorted(stripped_geo_keys))}")

            if cleaned_geo_locs:
                transformed_targeting['geo_locations'] = cleaned_geo_locs
        
        # Handle publisher_platforms
        if 'publisher_platforms' in targeting:
            transformed_targeting['publisher_platforms'] = targeting['publisher_platforms']

        # Handle platform-specific positions (Stories / Reels placement targeting)
        if 'facebook_positions' in targeting:
            transformed_targeting['facebook_positions'] = targeting['facebook_positions']
        if 'instagram_positions' in targeting:
            transformed_targeting['instagram_positions'] = targeting['instagram_positions']

        # Fix for Advantage Audience Flag Required error
        # Facebook now requires explicit opt-in/out for Advantage+ Audience
        # Default to 0 (Off) if not provided, unless user explicitly sets it
        advantage_audience = adset_data.get('advantage_audience', 0)
        transformed_targeting['targeting_automation'] = {
            'advantage_audience': advantage_audience
        }

        params = {
            AdSet.Field.name: adset_data.get('name'),
            AdSet.Field.campaign_id: adset_data.get('campaign_id'),
            AdSet.Field.billing_event: 'IMPRESSIONS',
            AdSet.Field.optimization_goal: adset_data.get('optimization_goal') or adset_data.get('optimizationGoal'),
            AdSet.Field.is_dynamic_creative: False,
            AdSet.Field.status: adset_data.get('status', 'PAUSED'),
            AdSet.Field.targeting: transformed_targeting,
        }

        # Handle promoted_object for conversion optimization
        if adset_data.get('optimization_goal') == 'OFFSITE_CONVERSIONS' or adset_data.get('optimizationGoal') == 'OFFSITE_CONVERSIONS':
            pixel_id = adset_data.get('pixelId') or adset_data.get('pixel_id')
            conversion_event = adset_data.get('conversionEvent') or adset_data.get('conversion_event')
            
            if pixel_id and conversion_event:
                params[AdSet.Field.promoted_object] = {
                    'pixel_id': pixel_id,
                    'custom_event_type': conversion_event
                }


        # Handle budget - only set for ABO campaigns (not CBO)
        budget_type = adset_data.get('budget_type') or adset_data.get('budgetType')
        budget_schedule = (adset_data.get('budgetScheduleType') or adset_data.get('budget_schedule_type') or 'DAILY').upper()

        if budget_type != 'CBO':
            if budget_schedule == 'LIFETIME':
                lifetime_budget = adset_data.get('lifetime_budget') or adset_data.get('lifetimeBudget')
                if lifetime_budget:
                    params[AdSet.Field.lifetime_budget] = int(float(lifetime_budget) * 100)
            else:
                daily_budget = adset_data.get('daily_budget') or adset_data.get('dailyBudget')
                if daily_budget:
                    params[AdSet.Field.daily_budget] = int(float(daily_budget) * 100)

        # Handle start time
        if adset_data.get('start_time') or adset_data.get('startTime'):
            start_time = adset_data.get('start_time') or adset_data.get('startTime')
            params[AdSet.Field.start_time] = start_time

        # Handle end time (required for lifetime budget and day parting)
        if adset_data.get('end_time') or adset_data.get('endTime'):
            end_time = adset_data.get('end_time') or adset_data.get('endTime')
            params[AdSet.Field.end_time] = end_time

        # Handle day parting / ad schedule
        # Meta's API field is 'adset_schedule' (NOT 'ad_schedule') — confirmed in SDK source.
        # Facebook requires lifetime_budget when adset_schedule is set.
        ad_schedule = adset_data.get('adSchedule') or adset_data.get('ad_schedule')
        if adset_data.get('adScheduleEnabled') or adset_data.get('ad_schedule_enabled'):
            if ad_schedule:
                params['adset_schedule'] = [
                    {
                        'days': s.get('days', []),
                        'start_minute': s.get('startMinute', s.get('start_minute', 0)),
                        'end_minute': s.get('endMinute', s.get('end_minute', 1440)),
                        'timezone_type': 'USER'
                    }
                    for s in ad_schedule
                ]
                # Required by Facebook when adset_schedule is set
                params['pacing_type'] = ['day_parting']

        # Handle bid strategy and bid amount
        # For CBO campaigns, bid_strategy is set at campaign level - don't set at ad set level
        # For ABO campaigns, we can set bid_strategy at ad set level
        bid_amount = adset_data.get('bid_amount') or adset_data.get('bidAmount')
        bid_strategy = adset_data.get('bid_strategy') or adset_data.get('bidStrategy')

        if bid_amount:
            params[AdSet.Field.bid_amount] = int(float(bid_amount) * 100)
            if bid_strategy:
                params[AdSet.Field.bid_strategy] = bid_strategy
        elif budget_type != 'CBO':
            # Only set default bid_strategy for ABO campaigns
            # CBO campaigns inherit bid_strategy from campaign level
            params[AdSet.Field.bid_strategy] = 'LOWEST_COST_WITHOUT_CAP'

        # Handle attribution window — convert UI value (e.g. '7d_click_1d_view')
        # to Meta's attribution_spec format required by the API.
        #
        # 28-day options removed 2026-08-21 (audit): verified live against
        # Meta's real API for OFFSITE_CONVERSIONS (what every real BHM
        # campaign uses) — Meta's own error is explicit: "Based on the
        # objectives and optimization goals you have selected, supported
        # values is/are attribution window of 1, 7 day(s)." Confirmed by
        # pulling every currently-active real ad set on the account: all of
        # them already use 7d_click/7d_click_1d_view exclusively. 28-day was
        # never actually usable and would hard-fail at ad-set creation.
        _ATTRIBUTION_MAP = {
            '1d_click':           [{'event_type': 'CLICK_THROUGH', 'window_days': 1}],
            '7d_click':           [{'event_type': 'CLICK_THROUGH', 'window_days': 7}],
            '1d_click_1d_view':   [{'event_type': 'CLICK_THROUGH', 'window_days': 1},
                                   {'event_type': 'VIEW_THROUGH',  'window_days': 1}],
            '7d_click_1d_view':   [{'event_type': 'CLICK_THROUGH', 'window_days': 7},
                                   {'event_type': 'VIEW_THROUGH',  'window_days': 1}],
        }
        attribution_setting = (
            adset_data.get('attributionSetting')
            or adset_data.get('attribution_setting')
        )
        if attribution_setting and attribution_setting in _ATTRIBUTION_MAP:
            params['attribution_spec'] = _ATTRIBUTION_MAP[attribution_setting]

        import logging
        logger = logging.getLogger(__name__)
        logger.info("create_adset params being sent to Meta: %s", params)

        try:
            created = account.create_ad_set(params=params)
            result = dict(created)
            if hec_stripped_fields:
                result['_hec_stripped_fields'] = hec_stripped_fields
            return result
        except FacebookRequestError as e:
            err = {}
            try:
                err = e.body().get('error', {})
            except Exception:
                pass
            logger.error("Meta adset creation error. params=%s  error=%s", params, err)
            user_msg = err.get('error_user_msg') or err.get('message') or (e.api_error_message() if hasattr(e, 'api_error_message') and callable(e.api_error_message) else str(e))
            raise RuntimeError(f"Facebook API: {user_msg}") from e

    def upload_image(self, image_path_or_url, ad_account_id=None):
        """Upload an image to the ad library."""
        import tempfile
        import requests

        account = self._get_account(ad_account_id)

        # Check if it's a URL or local file path
        if image_path_or_url.startswith('http://') or image_path_or_url.startswith('https://'):
            # Download the image to a temp file
            response = requests.get(image_path_or_url, timeout=30)
            response.raise_for_status()

            # Get file extension from URL or default to .jpg
            ext = '.jpg'
            if '.' in image_path_or_url.split('/')[-1]:
                ext = '.' + image_path_or_url.split('.')[-1].split('?')[0]

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(response.content)
                local_path = tmp.name

            image = AdImage(parent_id=account.get_id_assured())
            image[AdImage.Field.filename] = local_path
            # Image upload is the FIRST Meta write for every ad in a bulk batch,
            # so it is the most likely place a rate limit is hit. Preserve the
            # numeric code so the launch loop can stop the batch instead of
            # grinding the remaining ads into identical throttle errors.
            try:
                image.remote_create()
            except FacebookRequestError as e:
                raise self._meta_error(e, "Facebook API (image upload)") from e

            # Clean up temp file
            try:
                os.remove(local_path)
            except:
                pass

            return image[AdImage.Field.hash]
        else:
            # Local file path
            image = AdImage(parent_id=account.get_id_assured())
            image[AdImage.Field.filename] = image_path_or_url
            try:
                image.remote_create()
            except FacebookRequestError as e:
                raise self._meta_error(e, "Facebook API (image upload)") from e
            return image[AdImage.Field.hash]

    def upload_video(self, video_path_or_url, ad_account_id=None, wait_for_ready=True, timeout=600):
        """Upload a video to the ad library.

        Args:
            video_path_or_url: Local file path or URL to video
            ad_account_id: Optional ad account ID
            wait_for_ready: Whether to wait for video processing to complete
            timeout: Max seconds to wait for processing (default 10 min)

        Returns:
            dict with video_id, status, and thumbnails (if ready)
        """
        import tempfile
        import requests

        account = self._get_account(ad_account_id)

        # Check if it's a URL or local file path
        if video_path_or_url.startswith('http://') or video_path_or_url.startswith('https://'):
            # Download the video to a temp file
            print(f"Downloading video from URL: {video_path_or_url[:100]}...")
            response = requests.get(video_path_or_url, timeout=120, stream=True)
            response.raise_for_status()

            # Get file extension from URL or default to .mp4
            ext = '.mp4'
            if '.' in video_path_or_url.split('/')[-1]:
                url_ext = video_path_or_url.split('.')[-1].split('?')[0].lower()
                if url_ext in ['mp4', 'mov', 'avi', 'webm']:
                    ext = '.' + url_ext

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                for chunk in response.iter_content(chunk_size=8192):
                    tmp.write(chunk)
                local_path = tmp.name

            print(f"Video downloaded to temp file: {local_path}")
        else:
            local_path = video_path_or_url

        try:
            # Create and upload video
            video = AdVideo(parent_id=account.get_id_assured())
            video[AdVideo.Field.filepath] = local_path
            # Same reason as image upload: this is a per-ad Meta write inside the
            # bulk launch loop, so the throttle code has to survive or the loop
            # cannot tell a rate limit apart from a real rejection.
            try:
                video.remote_create()
            except FacebookRequestError as e:
                raise self._meta_error(e, "Facebook API (video upload)") from e

            video_id = video['id']
            print(f"Video uploaded with ID: {video_id}")

            if wait_for_ready:
                # Wait for video processing to complete
                status = self.wait_for_video_ready(video_id, timeout=timeout)
            else:
                status = self.get_video_status(video_id)

            # Get thumbnails if video is ready
            thumbnails = []
            if status.get('status') == 'ready':
                try:
                    thumbnails = self.get_video_thumbnails(video_id)
                except Exception as e:
                    print(f"Warning: Could not fetch thumbnails: {e}")

            return {
                'video_id': video_id,
                'status': status.get('status', 'processing'),
                'thumbnails': thumbnails
            }

        finally:
            # Clean up temp file if we downloaded it
            if video_path_or_url.startswith('http'):
                try:
                    os.remove(local_path)
                except:
                    pass

    def get_video_status(self, video_id):
        """Check the processing status of a video.

        Returns:
            dict with status ('processing', 'ready', 'error')
        """
        import requests

        url = f"https://graph.facebook.com/v21.0/{video_id}"
        params = {
            'fields': 'id,status,length,source',
            'access_token': self.access_token
        }

        response = requests.get(url, params=params, timeout=30)
        data = response.json()

        if 'error' in data:
            return {'status': 'error', 'error': data['error'].get('message', 'Unknown error')}

        # Facebook video status can be: processing, ready, error
        fb_status = data.get('status', {})
        if isinstance(fb_status, dict):
            video_status = fb_status.get('video_status', 'processing').lower()
        else:
            video_status = str(fb_status).lower()

        return {
            'status': video_status,
            'video_id': video_id,
            'length': data.get('length'),
            'source': data.get('source')
        }

    def wait_for_video_ready(self, video_id, timeout=600, interval=10):
        """Wait for video processing to complete.

        Args:
            video_id: Facebook video ID
            timeout: Max seconds to wait
            interval: Seconds between status checks

        Returns:
            dict with final status
        """
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            status = self.get_video_status(video_id)
            print(f"Video {video_id} status: {status.get('status')}")

            if status.get('status') == 'ready':
                return status
            elif status.get('status') == 'error':
                raise Exception(f"Video processing failed: {status.get('error', 'Unknown error')}")

            time.sleep(interval)

        raise Exception(f"Video processing timeout after {timeout} seconds")

    def get_video_thumbnails(self, video_id):
        """Get auto-generated thumbnails for a video.

        Returns:
            list of thumbnail URLs
        """
        import requests

        url = f"https://graph.facebook.com/v21.0/{video_id}/thumbnails"
        params = {
            'access_token': self.access_token
        }

        response = requests.get(url, params=params, timeout=30)
        data = response.json()

        if 'error' in data:
            print(f"Thumbnail fetch error: {data['error']}")
            return []

        thumbnails = []
        for thumb in data.get('data', []):
            if 'uri' in thumb:
                thumbnails.append(thumb['uri'])

        return thumbnails

    def _get_page_instagram_user_id(self, page_id):
        """Look up the Instagram Business Account connected to a Facebook Page.

        Meta's v22+ Marketing API replaces the legacy `instagram_actor_id`
        creative field with `instagram_user_id`. The Page edge still returns
        the connected Instagram Business Account object/id, and that same id is
        the value Meta expects in `object_story_spec.instagram_user_id`.

        Returns None (never raises) if the page has no linked IG account or the
        lookup itself fails — the caller falls back to a Facebook-only placement
        rather than blocking ad creation entirely.
        """
        try:
            from facebook_business.adobjects.page import Page
            page = Page(page_id, api=self.api).api_get(fields=['instagram_business_account'])
            iba = dict(page).get('instagram_business_account')
            return iba.get('id') if iba else None
        except FacebookRequestError as e:
            # A real API error (expired/revoked token, missing pages_show_list /
            # instagram_basic scope, bad page_id) reads identically to "this page
            # just has no linked IG account" unless we look at the error code —
            # and silently treating a permission problem as "no IG account" would
            # degrade every dual-placement ad to Facebook-only with no visibility,
            # indistinguishable from working-as-intended. Surface it loudly.
            code = e.api_error_code() if hasattr(e, 'api_error_code') and callable(e.api_error_code) else None
            print(f"🚨 Instagram user lookup for page {page_id} failed with a Facebook API "
                  f"error (code {code}), not a clean 'no IG account' result — falling back to "
                  f"Facebook-only placement, but this may be a token/permission problem, not a "
                  f"genuine missing IG account: {e}")
            return None
        except Exception as e:
            print(f"⚠️  Instagram user lookup failed for page {page_id}: {e}")
            return None

    def create_creative(self, creative_data, ad_account_id=None):
        """Create an ad creative (supports both image and video).

        `secondary_image_hash` (optional): the Meta image hash of a 9x16
        vertical asset, obtained via the same `upload_image()` call used for
        the primary `image_hash`. When present alongside `image_hash` (and
        only for the standard image/link path — never video, never lead-gen,
        which this feature does not touch), the creative is built with an
        `asset_feed_spec` instead of a plain `link_data` image so Feed shows
        the square (`image_hash`) and Story shows the vertical
        (`secondary_image_hash`) — both placements live together with the
        same copy. The two `customization_spec` position values used
        (`facebook_positions`/`instagram_positions`: `feed`/`stream` and
        `story`/`story`) are confirmed-documented values per Meta's
        asset-feed-spec + asset_customization_rules docs
        (developers.facebook.com/docs/marketing-api/reference/ad-asset-feed-spec/
        and .../ad-asset-feed-spec-asset-customization-rule/) — Reels-specific
        values are intentionally not included (see comment below). This is
        NOT a general dynamic-creative system — it always builds exactly
        the two rules below (Feed+Story), nothing else, and both
        images are required together when this path is used. When
        `secondary_image_hash` is absent, behavior is byte-identical to
        before this feature — the plain `link_data` single-image path.
        """
        account = self._get_account(ad_account_id)

        page_id = creative_data.get('page_id') or creative_data.get('pageId')
        image_hash = creative_data.get('image_hash')
        secondary_image_hash = creative_data.get('secondary_image_hash') or creative_data.get('secondaryImageHash')
        video_id = creative_data.get('video_id')
        website_url = (creative_data.get('website_url') or creative_data.get('websiteUrl') or '').strip()

        if not page_id:
            raise ValueError('page_id is required to create an ad creative')
        if not image_hash and not video_id:
            raise ValueError('Either image_hash or video_id is required')

        primary_text = creative_data.get('primary_text') or creative_data.get('message') or ''
        headline = creative_data.get('headline') or creative_data.get('name') or 'Ad'
        cta = creative_data.get('cta') or 'LEARN_MORE'
        creative_name = creative_data.get('creative_name') or creative_data.get('creativeName') or f'Creative {headline[:30]}'
        lead_gen_form_id = creative_data.get('lead_gen_form_id')

        # For lead gen creatives, website_url is not required
        if not lead_gen_form_id and (not website_url or not website_url.startswith('http')):
            raise ValueError('website_url must be a valid URL (e.g. https://example.com)')

        # NOTE: RedTrack tracking macros ({{ad.id}} etc.) are NOT injected into the
        # destination link — Meta only expands them in the creative's `url_tags` field
        # (set below, after the params dict is built). The link stays clean.

        # Determine creative type: video, lead gen, or standard image/link
        if video_id:
            # Video creative — CTA value depends on whether this is lead gen or link-click
            if lead_gen_form_id:
                lead_gen_cta = cta if cta not in ('LEARN_MORE', 'SHOP_NOW', 'BOOK_TRAVEL', 'WATCH_MORE') else 'SIGN_UP'
                cta_value = {'lead_gen_form_id': lead_gen_form_id}
                video_cta_type = lead_gen_cta
            else:
                cta_value = {'link': website_url}
                video_cta_type = cta
            object_story_spec = {
                'page_id': page_id,
                'video_data': {
                    'video_id': video_id,
                    'message': primary_text,
                    'title': headline,
                    'call_to_action': {
                        'type': video_cta_type,
                        'value': cta_value
                    }
                }
            }
            if creative_data.get('thumbnail_url'):
                object_story_spec['video_data']['image_url'] = creative_data['thumbnail_url']
        elif lead_gen_form_id:
            # Lead gen creative — attaches an Instant Form; no destination URL needed.
            # Meta requires link_data.link even for lead gen; use the Page URL as placeholder.
            lead_gen_cta = cta if cta not in ('LEARN_MORE', 'SHOP_NOW', 'BOOK_TRAVEL', 'WATCH_MORE') else 'SIGN_UP'
            object_story_spec = {
                'page_id': page_id,
                'link_data': {
                    'image_hash': image_hash,
                    'link': f'https://www.facebook.com/{page_id}',  # required by Meta even for lead gen
                    'message': primary_text,
                    'name': headline,
                    'call_to_action': {
                        'type': lead_gen_cta,
                        'value': {'lead_gen_form_id': lead_gen_form_id}
                    }
                }
            }
        elif secondary_image_hash:
            # Dual-placement image creative: Feed (square) + Stories/Reels
            # (vertical), same copy across both — Bulk Match Import only.
            # object_story_spec carries just page_id here; the rest lives in
            # asset_feed_spec, per Meta's asset-feed-spec contract.
            object_story_spec = {'page_id': page_id}

            # instagram_positions below requires an IG identity on the creative.
            # Use Meta's v22+ field (`instagram_user_id`), while accepting the
            # old input key as a compatibility alias only. Do not emit
            # `instagram_actor_id`: current Graph versions reject it in
            # object_story_spec.
            instagram_user_id = (
                creative_data.get('instagram_user_id')
                or creative_data.get('instagramUserId')
                or creative_data.get('instagram_actor_id')
                or self._get_page_instagram_user_id(page_id)
            )
            has_instagram = bool(instagram_user_id)
            if has_instagram:
                object_story_spec['instagram_user_id'] = instagram_user_id
            else:
                print(f"⚠️  Page {page_id} has no linked Instagram account — "
                      f"dual-placement creative will run Facebook-only (no Stories/Reels IG placement).")

            asset_feed_spec = {
                'ad_formats': ['SINGLE_IMAGE'],
                'images': [
                    {'hash': image_hash, 'adlabels': [{'name': 'feed_image'}]},
                    {'hash': secondary_image_hash, 'adlabels': [{'name': 'story_image'}]},
                ],
                'bodies': [{'text': primary_text}],
                'titles': [{'text': headline}],
                'link_urls': [{'website_url': website_url}],
                'call_to_action_types': [cta],
                **({'descriptions': [{'text': creative_data.get('description')}]} if creative_data.get('description') else {}),
                'asset_customization_rules': [
                    {
                        'customization_spec': {
                            'publisher_platforms': ['facebook', 'instagram'] if has_instagram else ['facebook'],
                            'facebook_positions': ['feed'],
                            **({'instagram_positions': ['stream']} if has_instagram else {}),
                        },
                        'image_label': {'name': 'feed_image'},
                    },
                    {
                        'customization_spec': {
                            'publisher_platforms': ['facebook', 'instagram'] if has_instagram else ['facebook'],
                            # 'facebook_reels' / 'reels' deliberately left out: they are
                            # not documented values for customization_spec on this field
                            # (developers.facebook.com/docs/marketing-api/reference/
                            # ad-asset-feed-spec-asset-customization-rule/) — that Reels
                            # position family belongs to the ad-set-level `targeting`
                            # field instead, which has different accepted values. Add
                            # Reels-specific targeting here only once a documented value
                            # for this field is confirmed; this is a deliberate omission,
                            # not an oversight.
                            'facebook_positions': ['story'],
                            **({'instagram_positions': ['story']} if has_instagram else {}),
                        },
                        'image_label': {'name': 'story_image'},
                    },
                ],
            }
        else:
            # Standard image / link click creative
            object_story_spec = {
                'page_id': page_id,
                'link_data': {
                    'image_hash': image_hash,
                    'link': website_url,
                    'message': primary_text,
                    'name': headline,
                    'description': creative_data.get('description') or '',
                    'call_to_action': {
                        'type': cta,
                        'value': {'link': website_url}
                    }
                }
            }

        instagram_user_id = (
            creative_data.get('instagram_user_id')
            or creative_data.get('instagramUserId')
            or creative_data.get('instagram_actor_id')
        )
        if instagram_user_id and 'instagram_user_id' not in object_story_spec:
            object_story_spec['instagram_user_id'] = instagram_user_id

        params = {
            AdCreative.Field.name: creative_name,
            AdCreative.Field.object_story_spec: object_story_spec,
        }
        if secondary_image_hash and not video_id and not lead_gen_form_id:
            params[AdCreative.Field.asset_feed_spec] = asset_feed_spec

        # RedTrack tracking macros go in the creative's url_tags field. Meta expands
        # {{ad.id}}/{{adset.id}}/{{campaign.id}} there and appends them to the clicked
        # URL at delivery time — they do NOT expand inside link_data.link. Skipped for
        # lead-gen / URL-less flows (build_redtrack_url_tags returns ""). Correct
        # existing macros are not duplicated; wrong existing sub values are
        # overridden by url_tags so RedTrack spend attribution stays keyed to Meta.
        if not lead_gen_form_id and website_url:
            try:
                from app.core.redtrack_macros import build_redtrack_url_tags
                url_tags = build_redtrack_url_tags(website_url)
                if url_tags:
                    params[AdCreative.Field.url_tags] = url_tags
                    # Belt-and-suspenders: a research report (possibly stale /
                    # different SDK) suggested asset_feed_spec.link_urls +
                    # top-level url_tags together don't reliably render the
                    # destination link for dual-placement creatives. We set
                    # url_tags in BOTH places for the dual-placement path
                    # (top-level, above, and asset_feed_spec.link_urls[0]
                    # below) until this is verified live against a real push.
                    # Remove whichever one turns out unnecessary/wrong once
                    # confirmed — do not remove either speculatively.
                    if secondary_image_hash and not video_id and not lead_gen_form_id:
                        asset_feed_spec['link_urls'][0]['url_tags'] = url_tags
            except Exception as _e:
                # Never let macro enforcement block a push — flag and continue without url_tags.
                print(f"⚠️  RedTrack url_tags build skipped: {_e}")

        try:
            return account.create_ad_creative(params=params)
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            user_msg = err.get('error_user_msg') or err.get('message') or (e.api_error_message() if hasattr(e, 'api_error_message') and callable(e.api_error_message) else str(e))
            code = e.api_error_code() if hasattr(e, 'api_error_code') and callable(e.api_error_code) else err.get('code')
            subcode = e.api_error_subcode() if hasattr(e, 'api_error_subcode') and callable(e.api_error_subcode) else err.get('error_subcode')
            raise FacebookAPIError(f"Facebook API: {user_msg}", code=code, subcode=subcode) from e

    def create_ad(self, ad_data, ad_account_id=None):
        """Create an ad."""
        account = self._get_account(ad_account_id)

        adset_id = ad_data.get('adset_id') or ad_data.get('adsetId')
        creative_id = ad_data.get('creative_id') or ad_data.get('creativeId')
        name = ad_data.get('name') or 'Ad'
        status = ad_data.get('status') if ad_data.get('status') in ('ACTIVE', 'PAUSED', 'DELETED', 'ARCHIVED') else 'PAUSED'

        if not adset_id:
            raise ValueError('adset_id is required to create an ad')
        if not creative_id:
            raise ValueError('creative_id is required to create an ad')

        params = {
            Ad.Field.name: name,
            Ad.Field.adset_id: adset_id,
            Ad.Field.creative: {'creative_id': creative_id},
            Ad.Field.status: status,
        }
        # NOTE: RedTrack macros are set on the AdCreative's url_tags field (see
        # create_creative), not on the Ad — Ad has no url_tags field in this SDK.

        try:
            return account.create_ad(params=params)
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            user_msg = err.get('error_user_msg') or err.get('message') or (e.api_error_message() if hasattr(e, 'api_error_message') and callable(e.api_error_message) else str(e))
            code = e.api_error_code() if hasattr(e, 'api_error_code') and callable(e.api_error_code) else err.get('code')
            subcode = e.api_error_subcode() if hasattr(e, 'api_error_subcode') and callable(e.api_error_subcode) else err.get('error_subcode')
            raise FacebookAPIError(f"Facebook API: {user_msg}", code=code, subcode=subcode) from e

    def search_locations(self, query, location_type='city', limit=10, ad_account_id=None):
        """Search for targeting locations."""
        account = self._get_account(ad_account_id)
        
        params = {
            'q': query,
            'type': 'adgeolocation',
            'location_types': [location_type],
            'limit': limit,
        }
        
        return account.get_targeting_search(params=params)


    # ──────────────────────────────────────────────────────────────────────────
    # Insights & Auto-Pause
    # ──────────────────────────────────────────────────────────────────────────

    def get_adset_insights(self, fb_adset_id: str, date_preset: str = 'last_7d') -> dict:
        """Pull spend, leads/conversions, and CPL for a single ad set from Meta Insights API.

        Returns a dict:
          { spend, leads, cpl, impressions, clicks, ctr, date_preset }
        """
        import logging
        logger = logging.getLogger(__name__)

        adset = AdSet(fbid=fb_adset_id)
        fields = [
            'spend',
            'impressions',
            'reach',
            'frequency',
            'clicks',
            'ctr',
            'actions',
            'action_values',
            'cost_per_action_type',
            'purchase_roas',
        ]
        params = {'date_preset': date_preset}

        try:
            results = adset.get_insights(fields=fields, params=params)
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            msg = err.get('message') or str(e)
            logger.error("Meta Insights error for adset %s: %s", fb_adset_id, msg)
            raise RuntimeError(f"Facebook API: {msg}") from e

        if not results:
            return {
                'spend': 0.0, 'leads': 0, 'cpl': None,
                'impressions': 0, 'reach': 0, 'frequency': 0.0,
                'clicks': 0, 'ctr': None,
                'revenue': None, 'roas': None,
                'date_preset': date_preset,
            }

        row = results[0]

        spend = float(row.get('spend', 0) or 0)
        impressions = int(row.get('impressions', 0) or 0)
        reach = int(row.get('reach', 0) or 0)
        frequency = round(float(row.get('frequency', 0) or 0), 2)
        clicks = int(row.get('clicks', 0) or 0)
        # Stay None when Meta omits ctr — see matching comment in
        # get_account_insights_bulk above.
        ctr = float(row['ctr']) if row.get('ctr') is not None else None

        # Count leads: action_type = 'lead' or 'onsite_conversion.lead_grouped'
        leads = 0
        lead_types = {'lead', 'onsite_conversion.lead_grouped', 'offsite_conversion.fb_pixel_lead'}
        for action in (row.get('actions') or []):
            if action.get('action_type') in lead_types:
                leads += int(float(action.get('value', 0)))

        # CPL from cost_per_action_type
        cpl = None
        for cpa in (row.get('cost_per_action_type') or []):
            if cpa.get('action_type') in lead_types:
                cpl = float(cpa.get('value', 0))
                break
        if cpl is None and leads > 0 and spend > 0:
            cpl = round(spend / leads, 2)

        # Revenue from action_values — check purchases first, then leads (lead-gen campaigns
        # pass payout value with every lead event, so this covers both ecomm and lead-gen)
        revenue = None
        purchase_types = {'purchase', 'omni_purchase', 'offsite_conversion.fb_pixel_purchase'}
        for av in (row.get('action_values') or []):
            if av.get('action_type') in purchase_types:
                revenue = round(float(av.get('value', 0)), 2)
                break
        if revenue is None:
            for av in (row.get('action_values') or []):
                if av.get('action_type') in lead_types:
                    revenue = round(float(av.get('value', 0)), 2)
                    break

        # ROAS: use Meta's purchase_roas if available, otherwise calculate from lead revenue
        roas = None
        for r in (row.get('purchase_roas') or []):
            if r.get('action_type') in ('omni_purchase', 'purchase'):
                roas = round(float(r.get('value', 0)), 2)
                break
        if roas is None and revenue is not None and spend > 0:
            roas = round(revenue / spend, 2)

        return {
            'spend': round(spend, 2),
            'leads': leads,
            'cpl': round(cpl, 2) if cpl is not None else None,
            'impressions': impressions,
            'reach': reach,
            'frequency': frequency,
            'clicks': clicks,
            'ctr': round(ctr, 4) if ctr is not None else None,
            'revenue': revenue,
            'roas': roas,
            'date_preset': date_preset,
        }

    def get_account_insights_bulk(
        self,
        ad_account_id: str = None,
        date_preset: str = 'last_7d',
        date_from: str = None,
        date_to: str = None,
    ) -> dict:
        """Fetch Meta Insights for ALL ad sets in the account in a single API call.

        Accepts either date_preset (last_7d, today, yesterday, last_14d, last_30d)
        or explicit date_from / date_to in YYYY-MM-DD format for custom ranges.

        Returns a dict keyed by fb_adset_id:
          { fb_adset_id: { spend, leads, cpl, impressions, reach, frequency,
                           clicks, ctr, revenue, roas, date_preset } }
        """
        import logging
        logger = logging.getLogger(__name__)

        account = self._get_account(ad_account_id)
        fields = [
            'adset_id',
            'adset_name',
            'spend',
            'impressions',
            'reach',
            'frequency',
            'clicks',
            'ctr',
            'actions',
            'action_values',
            'cost_per_action_type',
            'purchase_roas',
        ]
        if date_from and date_to:
            params = {
                'time_range': {'since': date_from, 'until': date_to},
                'level': 'adset',
            }
        else:
            params = {
                'date_preset': date_preset,
                'level': 'adset',
            }

        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(account.get_insights, fields, params)
                try:
                    results = future.result(timeout=20)  # 20s hard cap on Meta API
                except FuturesTimeout:
                    logger.error("Meta bulk insights timed out after 20s")
                    raise RuntimeError("Meta API timeout — try again in a moment")
        except RuntimeError:
            raise
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            msg = err.get('message') or str(e)
            logger.error("Meta bulk insights error: %s", msg)
            raise RuntimeError(f"Facebook API: {msg}") from e

        lead_types = {'lead', 'onsite_conversion.lead_grouped', 'offsite_conversion.fb_pixel_lead'}
        purchase_types = {'purchase', 'omni_purchase', 'offsite_conversion.fb_pixel_purchase'}
        out = {}

        for row in results:
            fb_adset_id = str(row.get('adset_id') or '')
            if not fb_adset_id:
                continue

            adset_name = str(row.get('adset_name') or '')
            spend      = float(row.get('spend', 0) or 0)
            impressions = int(row.get('impressions', 0) or 0)
            reach       = int(row.get('reach', 0) or 0)
            frequency   = round(float(row.get('frequency', 0) or 0), 2)
            clicks      = int(row.get('clicks', 0) or 0)
            # Stay None when Meta omits ctr, matching cpl's pattern below — a
            # 'ctr less_than X' auto-pause rule must not treat "Meta didn't
            # return this field on this row" as "CTR is actually 0", or a
            # transient omission could fire a real pause (flagged in the
            # 2026-08-21 audit).
            ctr = float(row['ctr']) if row.get('ctr') is not None else None

            leads = 0
            for action in (row.get('actions') or []):
                if action.get('action_type') in lead_types:
                    leads += int(float(action.get('value', 0)))

            cpl = None
            for cpa in (row.get('cost_per_action_type') or []):
                if cpa.get('action_type') in lead_types:
                    cpl = float(cpa.get('value', 0))
                    break
            if cpl is None and leads > 0 and spend > 0:
                cpl = round(spend / leads, 2)

            revenue = None
            for av in (row.get('action_values') or []):
                if av.get('action_type') in purchase_types:
                    revenue = round(float(av.get('value', 0)), 2)
                    break
            if revenue is None:
                for av in (row.get('action_values') or []):
                    if av.get('action_type') in lead_types:
                        revenue = round(float(av.get('value', 0)), 2)
                        break

            roas = None
            for r in (row.get('purchase_roas') or []):
                if r.get('action_type') in ('omni_purchase', 'purchase'):
                    roas = round(float(r.get('value', 0)), 2)
                    break
            if roas is None and revenue is not None and spend > 0:
                roas = round(revenue / spend, 2)

            out[fb_adset_id] = {
                'adset_name':  adset_name,
                'spend':       round(spend, 2),
                'leads':       leads,
                'cpl':         round(cpl, 2) if cpl is not None else None,
                'impressions': impressions,
                'reach':       reach,
                'frequency':   frequency,
                'clicks':      clicks,
                'ctr':         round(ctr, 4) if ctr is not None else None,
                'revenue':     revenue,
                'roas':        roas,
                'date_preset': date_preset,
            }

        return out

    def get_account_ads_insights_bulk(
        self,
        ad_account_id: str = None,
        date_preset: str = 'last_7d',
        date_from: str = None,
        date_to: str = None,
    ) -> dict:
        """Fetch Meta Insights for ALL ads in the account in a single API call.

        Accepts either date_preset or explicit date_from/date_to (YYYY-MM-DD).

        Returns a dict keyed by fb_adset_id → list of ads:
          { fb_adset_id: [ { ad_id, ad_name, spend, leads, cpl,
                             impressions, clicks, ctr, roas } ] }
        """
        import logging
        logger = logging.getLogger(__name__)

        account = self._get_account(ad_account_id)
        fields = [
            'ad_id',
            'ad_name',
            'adset_id',
            'spend',
            'impressions',
            'clicks',
            'ctr',
            'actions',
            'cost_per_action_type',
            'purchase_roas',
            'action_values',
        ]
        if date_from and date_to:
            params = {
                'time_range': {'since': date_from, 'until': date_to},
                'level': 'ad',
            }
        else:
            params = {
                'date_preset': date_preset,
                'level': 'ad',
            }

        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(account.get_insights, fields, params)
                try:
                    results = future.result(timeout=20)
                except FuturesTimeout:
                    logger.error("Meta ads bulk insights timed out after 20s")
                    raise RuntimeError("Meta API timeout — try again in a moment")
        except RuntimeError:
            raise
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            msg = err.get('message') or str(e)
            logger.error("Meta ads bulk insights error: %s", msg)
            raise RuntimeError(f"Facebook API: {msg}") from e

        lead_types = {'lead', 'onsite_conversion.lead_grouped', 'offsite_conversion.fb_pixel_lead'}
        purchase_types = {'purchase', 'omni_purchase', 'offsite_conversion.fb_pixel_purchase'}
        out = {}  # keyed by fb_adset_id → list of ads

        for row in results:
            fb_adset_id = str(row.get('adset_id') or '')
            fb_ad_id    = str(row.get('ad_id') or '')
            if not fb_adset_id or not fb_ad_id:
                continue

            spend      = float(row.get('spend', 0) or 0)
            impressions = int(row.get('impressions', 0) or 0)
            clicks      = int(row.get('clicks', 0) or 0)
            ctr         = round(float(row.get('ctr', 0) or 0), 4)

            leads = 0
            for action in (row.get('actions') or []):
                if action.get('action_type') in lead_types:
                    leads += int(float(action.get('value', 0)))

            cpl = None
            for cpa in (row.get('cost_per_action_type') or []):
                if cpa.get('action_type') in lead_types:
                    cpl = round(float(cpa.get('value', 0)), 2)
                    break
            if cpl is None and leads > 0 and spend > 0:
                cpl = round(spend / leads, 2)

            revenue = None
            for av in (row.get('action_values') or []):
                if av.get('action_type') in purchase_types:
                    revenue = round(float(av.get('value', 0)), 2)
                    break
            if revenue is None:
                for av in (row.get('action_values') or []):
                    if av.get('action_type') in lead_types:
                        revenue = round(float(av.get('value', 0)), 2)
                        break

            roas = None
            for r in (row.get('purchase_roas') or []):
                if r.get('action_type') in ('omni_purchase', 'purchase'):
                    roas = round(float(r.get('value', 0)), 2)
                    break
            if roas is None and revenue is not None and spend > 0:
                roas = round(revenue / spend, 2)

            ad_entry = {
                'ad_id':       fb_ad_id,
                'ad_name':     str(row.get('ad_name') or ''),
                'spend':       round(spend, 2),
                'leads':       leads,
                'cpl':         cpl,
                'impressions': impressions,
                'clicks':      clicks,
                'ctr':         ctr,
                'roas':        roas,
            }

            if fb_adset_id not in out:
                out[fb_adset_id] = []
            out[fb_adset_id].append(ad_entry)

        # Sort each adset's ads by spend descending
        for adset_id in out:
            out[adset_id].sort(key=lambda a: a['spend'], reverse=True)

        return out

    def update_adset_status(self, fb_adset_id: str, status: str) -> None:
        """Set an ad set's delivery status (ACTIVE | PAUSED) via Meta API."""
        import logging
        logger = logging.getLogger(__name__)

        adset = AdSet(fbid=fb_adset_id)
        try:
            adset.api_update(params={'status': status})
            logger.info("AdSet %s status → %s", fb_adset_id, status)
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            msg = err.get('message') or str(e)
            logger.error("Failed to update adset %s status: %s", fb_adset_id, msg)
            raise RuntimeError(f"Facebook API: {msg}") from e

    # A cheap sanity floor, NOT Meta's real minimum — Meta's actual minimum budget
    # varies by objective, billing event, optimization goal, and CBO vs ABO (a CBO
    # campaign's floor is roughly the sum of its ad sets' individual minimums, often
    # well above $1/day for a conversion-optimized campaign). This just catches an
    # obviously-broken computed value (e.g. a 99% decrease) before it's sent — a
    # value that clears this floor can still be rejected by Meta's own server-side
    # minimum, which is caught by the FacebookRequestError handling below, not by
    # this constant. $1.00/day, in cents, matching the units Meta's budget fields
    # use everywhere else in this file.
    MIN_BUDGET_CENTS = 100

    def adjust_adset_budget_by_percent(self, fb_adset_id: str, percent_change: float) -> dict:
        """Increase or decrease an ad set's budget by a percentage, live against Meta.

        Auto-pause rules are always scoped to one specific ad set, but that ad set's
        budget doesn't necessarily live on the ad set itself — under a CBO ("Campaign
        Budget Optimization") campaign, budget is set on the CAMPAIGN, and the ad set's
        own daily_budget/lifetime_budget fields are simply absent from Meta's response
        (not zero, not null-but-present — the field key doesn't come back at all).
        Blindly calling adset.api_update({'daily_budget': ...}) in that case doesn't
        error, it just silently does nothing, which is worse than an error for a rule
        meant to run unattended every 30 minutes.

        Always reads the CURRENT budget live from Meta immediately before writing
        (read-modify-write) rather than trusting this app's own locally-synced copy,
        which can be stale if a buyer changed the budget by hand in Ads Manager since
        the last sync.

        Returns a dict describing exactly what happened, for the audit log:
        {level: 'adset'|'campaign', target_id, field: 'daily_budget'|'lifetime_budget',
         old_cents, new_cents}. Raises RuntimeError on any Meta API failure or if
        neither the ad set nor its parent campaign has a budget field set at all
        (e.g. an ad-set-level budget field literally hasn't been configured, which
        would otherwise look identical to "successfully adjusted nothing").
        """
        import logging
        logger = logging.getLogger(__name__)

        adset = AdSet(fbid=fb_adset_id)
        try:
            adset_data = adset.api_get(fields=[
                AdSet.Field.daily_budget,
                AdSet.Field.lifetime_budget,
                AdSet.Field.campaign_id,
            ])
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            msg = err.get('message') or str(e)
            logger.error("Failed to read adset %s for budget adjust: %s", fb_adset_id, msg)
            raise RuntimeError(f"Facebook API: {msg}") from e

        target = None
        field = None
        current_cents = None
        level = None
        target_id = None

        # `is not None`, not bare truthiness — Meta's documented CBO behavior is to
        # omit the field entirely (not return a literal 0), but relying on that
        # alone via `if adset_data.get(...):` would misfire if Meta ever did return
        # an actual 0 for a real budget (bool(0) is False, same as a missing key).
        # This function writes real money; don't let that ambiguity through.
        if adset_data.get(AdSet.Field.daily_budget) is not None:
            target, field, current_cents = adset, AdSet.Field.daily_budget, int(adset_data[AdSet.Field.daily_budget])
            level, target_id = 'adset', fb_adset_id
        elif adset_data.get(AdSet.Field.lifetime_budget) is not None:
            target, field, current_cents = adset, AdSet.Field.lifetime_budget, int(adset_data[AdSet.Field.lifetime_budget])
            level, target_id = 'adset', fb_adset_id
        else:
            # Ad set itself has no budget field — check the parent campaign (CBO).
            campaign_id = adset_data.get(AdSet.Field.campaign_id)
            if not campaign_id:
                raise RuntimeError(
                    f"AdSet {fb_adset_id} has no budget field and no parent campaign_id — cannot adjust budget."
                )
            campaign = Campaign(fbid=campaign_id)
            try:
                campaign_data = campaign.api_get(fields=[Campaign.Field.daily_budget, Campaign.Field.lifetime_budget])
            except FacebookRequestError as e:
                body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
                err = body.get('error', {}) if isinstance(body, dict) else {}
                msg = err.get('message') or str(e)
                logger.error("Failed to read campaign %s for budget adjust: %s", campaign_id, msg)
                raise RuntimeError(f"Facebook API: {msg}") from e

            if campaign_data.get(Campaign.Field.daily_budget) is not None:
                target, field, current_cents = campaign, Campaign.Field.daily_budget, int(campaign_data[Campaign.Field.daily_budget])
                level, target_id = 'campaign', campaign_id
            elif campaign_data.get(Campaign.Field.lifetime_budget) is not None:
                target, field, current_cents = campaign, Campaign.Field.lifetime_budget, int(campaign_data[Campaign.Field.lifetime_budget])
                level, target_id = 'campaign', campaign_id
            else:
                raise RuntimeError(
                    f"Neither AdSet {fb_adset_id} nor its parent Campaign {campaign_id} "
                    "has a budget field set — cannot determine where to adjust."
                )

            # A CBO campaign's budget is shared across EVERY ad set under it, not just
            # the one this rule was scoped to — but a rule is always configured
            # against one specific ad set (per the docstring above). Adjusting the
            # campaign here would silently move budget for sibling ad sets too,
            # including ones performing fine, with nothing in the Slack alert or
            # audit log saying so unless we make that explicit. Caught in domain-
            # expert review (Meta API pass) as the single highest-risk gap in this
            # method — a rule aimed at one loser could quietly cut a winner's spend.
            # Refuse rather than silently proceed whenever another ACTIVE sibling
            # exists; only adjust automatically when this ad set is the sole active
            # one in the campaign (the shared budget is, in effect, just its own).
            try:
                sibling_adsets = list(campaign.get_ad_sets(fields=[AdSet.Field.id, AdSet.Field.status]))
            except FacebookRequestError as e:
                body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
                err = body.get('error', {}) if isinstance(body, dict) else {}
                msg = err.get('message') or str(e)
                logger.error("Failed to list sibling ad sets for campaign %s: %s", campaign_id, msg)
                raise RuntimeError(f"Facebook API: {msg}") from e

            active_siblings = [
                a for a in sibling_adsets
                if a.get(AdSet.Field.id) != fb_adset_id and a.get(AdSet.Field.status) == 'ACTIVE'
            ]
            if active_siblings:
                raise RuntimeError(
                    f"AdSet {fb_adset_id}'s budget is CBO-shared at the campaign level with "
                    f"{len(active_siblings)} other active ad set(s) — refusing to adjust it here, "
                    "since that would silently change budget for all of them. Manage this campaign's "
                    "budget directly, or scope this rule to an ad set that isn't in a shared CBO campaign."
                )

        new_cents = int(round(current_cents * (1 + percent_change / 100)))
        if new_cents < self.MIN_BUDGET_CENTS:
            raise RuntimeError(
                f"Computed new budget ${new_cents / 100:.2f} is below the ${self.MIN_BUDGET_CENTS / 100:.2f} "
                f"floor (current ${current_cents / 100:.2f}, {percent_change:+.0f}%) — refusing to send this to Meta."
            )

        try:
            target.api_update(params={field: new_cents})
            logger.info(
                "%s %s budget %s $%.2f → $%.2f (%+.0f%%)",
                level, target_id, field, current_cents / 100, new_cents / 100, percent_change,
            )
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            msg = err.get('message') or str(e)
            logger.error("Failed to update %s %s budget: %s", level, target_id, msg)
            raise RuntimeError(f"Facebook API: {msg}") from e

        return {
            'level': level,
            'target_id': target_id,
            'field': field,
            'old_cents': current_cents,
            'new_cents': new_cents,
        }

    def update_ad_status(self, fb_ad_id: str, status: str) -> None:
        """Set an individual ad's delivery status (ACTIVE | PAUSED) via Meta API."""
        import logging
        logger = logging.getLogger(__name__)

        ad = Ad(fbid=fb_ad_id)
        try:
            ad.api_update(params={'status': status})
            logger.info("Ad %s status → %s", fb_ad_id, status)
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            msg = err.get('message') or str(e)
            logger.error("Failed to update ad %s status: %s", fb_ad_id, msg)
            raise RuntimeError(f"Facebook API: {msg}") from e

    def get_ad_creative(self, fb_ad_id: str) -> dict:
        """Fetch the creative content (headline, body, CTA, image URL) for a single ad.

        Returns:
            {
                "headline": str | None,
                "body": str | None,
                "cta_label": str | None,   # e.g. "LEARN_MORE", "GET_QUOTE"
                "image_url": str | None,
                "ad_name": str | None,
            }
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            ad = Ad(fbid=fb_ad_id)
            ad_data = ad.api_get(fields=[
                Ad.Field.name,
                'creative{title,body,call_to_action,image_url,thumbnail_url,'
                'object_story_spec{link_data{picture,message,name,link},'
                'video_data{image_url,message,title}},'
                # images/link_urls requested explicitly — the new Bulk Match Import
                # dual-placement creatives (asset_feed_spec, no link_data at all)
                # need these to resolve an image/link at all; titles/bodies were
                # already covered above.
                'asset_feed_spec{images,link_urls,titles,bodies}}',
            ])

            creative = ad_data.get('creative', {})
            oss = creative.get('object_story_spec', {})
            afs = creative.get('asset_feed_spec', {})  # dynamic/asset-feed creatives

            # Headline: title → object_story_spec → asset_feed_spec.titles[0]
            headline = creative.get('title')
            if not headline:
                headline = (
                    oss.get('link_data', {}).get('name') or
                    oss.get('video_data', {}).get('title')
                )
            if not headline:
                titles = afs.get('titles', [])
                headline = titles[0].get('text') if titles else None

            # Body: body → object_story_spec → asset_feed_spec.bodies[0]
            body = creative.get('body')
            if not body:
                body = (
                    oss.get('link_data', {}).get('message') or
                    oss.get('video_data', {}).get('message')
                )
            if not body:
                bodies = afs.get('bodies', [])
                body = bodies[0].get('text') if bodies else None

            # CTA type
            cta_obj = creative.get('call_to_action', {})
            cta_label = cta_obj.get('type') if isinstance(cta_obj, dict) else None

            # asset_feed_spec fallback for the dual-placement (Bulk Match Import)
            # creative shape, which has NO object_story_spec.link_data at all.
            # Prefer the image labeled 'feed_image' (the square/Feed asset — the
            # closest equivalent to what link_data.picture used to return);
            # fall back to the first image in the list if no label matches.
            # NOTE: Meta may only populate `hash` here, not `url`, unless `url`
            # was explicitly requested/stored at creative-creation time — if so
            # this resolves to None and we fall through to the 64×64 thumbnail
            # below rather than crashing.
            afs_images = afs.get('images', []) or []
            afs_feed_image = next(
                (img for img in afs_images if any(
                    label.get('name') == 'feed_image' for label in (img.get('adlabels') or [])
                )),
                None
            )
            afs_image_url = (afs_feed_image or (afs_images[0] if afs_images else {})).get('url')

            afs_link_urls = afs.get('link_urls', []) or []
            afs_link_url = afs_link_urls[0].get('website_url') if afs_link_urls else None

            # Image URL resolution (largest available wins):
            # 1. object_story_spec.link_data.picture — full-size image (what we want for Remix/Iterate)
            # 2. object_story_spec.video_data.image_url — video thumbnail (reasonably sized)
            # 3. asset_feed_spec.images[].url — dual-placement creatives (see note above; may be absent)
            # 4. creative.image_url — 64×64 thumbnail ONLY (avoid for kie.ai inputImage)
            # 5. creative.thumbnail_url — video preview fallback
            image_url = (
                oss.get('link_data', {}).get('picture') or
                oss.get('video_data', {}).get('image_url') or
                afs_image_url or
                creative.get('image_url') or
                creative.get('thumbnail_url')
            )

            # Destination URL: link in link_data, CTA value link, or
            # asset_feed_spec.link_urls[0].website_url (dual-placement creatives)
            cta_value = cta_obj.get('value', {}) if isinstance(cta_obj, dict) else {}
            link_url = (
                oss.get('link_data', {}).get('link') or
                cta_value.get('link') or
                oss.get('video_data', {}).get('link_data', {}).get('link') or
                afs_link_url
            )

            logger.info("Fetched creative for ad %s: headline=%s image=%s link=%s", fb_ad_id, headline, image_url, link_url)

            return {
                "headline": headline,
                "body": body,
                "cta_label": cta_label,
                "image_url": image_url,
                "link_url": link_url,
                "ad_name": ad_data.get('name'),
            }

        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            msg = err.get('message') or str(e)
            logger.error("Failed to fetch creative for ad %s: %s", fb_ad_id, msg)
            raise RuntimeError(f"Facebook API: {msg}") from e

    def get_adset_name_map(self, ad_account_id=None) -> dict:
        """Fetch all ad set IDs → names for the account in one call.

        Used by the copy library sync to resolve adset names without relying on
        the local FacebookAdSet DB table (which may lag or be incomplete).

        Returns {} on failure so the caller can fall back gracefully.
        """
        import logging
        logger = logging.getLogger(__name__)

        account = self._get_account(ad_account_id)
        try:
            cursor = account.get_ad_sets(
                fields=['id', 'name'],
                params={
                    'effective_status': ['ACTIVE', 'PAUSED', 'ARCHIVED'],
                    'limit': 500,
                },
            )
            # Paginate through all pages — accounts with >500 adsets need explicit
            # pagination because the SDK cursor only materialises one page at a time.
            result = {}
            while True:
                for a in cursor:
                    result[str(a['id'])] = str(a.get('name') or '')
                if not cursor.load_next_page():
                    break
            logger.info("get_adset_name_map: fetched %d ad sets", len(result))
            return result
        except Exception as exc:
            logger.warning("get_adset_name_map failed (%s) — falling back to empty map", exc)
            return {}

    def get_ad_insights_map(self, ad_ids, ad_account_id=None) -> dict:
        """Batch-fetch lifetime spend + CPL for a list of ad IDs.

        Returns { fb_ad_id: {"spend": float, "cpl": float | None} }.

        Used by the copy library sync to weight curation + few-shot injection by
        actual campaign outcome. Non-fatal: returns {} (or a partial map) on any
        error so the sync always completes even without performance data. Missing
        entries mean no insight data (zero-spend or brand-new ad).
        """
        import json as _json
        import logging
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        logger = logging.getLogger(__name__)

        ids = [str(a) for a in (ad_ids or []) if a]
        if not ids:
            return {}

        account = self._get_account(ad_account_id)
        lead_types = {'lead', 'onsite_conversion.lead_grouped', 'offsite_conversion.fb_pixel_lead'}
        fields = ['ad_id', 'spend', 'actions', 'cost_per_action_type']
        out = {}

        # Meta accepts up to ~200 IDs per IN filter — chunk defensively.
        for start in range(0, len(ids), 200):
            chunk = ids[start:start + 200]
            params = {
                'level': 'ad',
                'date_preset': 'maximum',   # lifetime
                'filtering': _json.dumps([{
                    'field': 'ad.id',
                    'operator': 'IN',
                    'value': chunk,
                }]),
                'limit': 500,
            }
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(account.get_insights, fields, params)
                    try:
                        # date_preset='maximum' is the widest lookback and can be
                        # slow on the synchronous insights edge — allow more headroom.
                        cursor = future.result(timeout=60)  # hard cap on Meta API
                    except FuturesTimeout:
                        logger.warning("get_ad_insights_map: chunk timed out after 60s — skipping")
                        continue
                rows = []
                while True:
                    for row in cursor:
                        rows.append(row)
                    if not cursor.load_next_page():
                        break
            except FacebookRequestError as e:
                body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
                err = body.get('error', {}) if isinstance(body, dict) else {}
                msg = err.get('message') or str(e)
                logger.warning("get_ad_insights_map: Meta error (%s) — skipping chunk", msg)
                continue
            except Exception as exc:
                logger.warning("get_ad_insights_map: unexpected error (%s) — skipping chunk", exc)
                continue

            for row in rows:
                fb_ad_id = str(row.get('ad_id') or '')
                if not fb_ad_id:
                    continue
                spend = float(row.get('spend', 0) or 0)
                cpl = None
                for cpa in (row.get('cost_per_action_type') or []):
                    if cpa.get('action_type') in lead_types:
                        cpl = float(cpa.get('value', 0))
                        break
                if cpl is None:
                    leads = 0
                    for action in (row.get('actions') or []):
                        if action.get('action_type') in lead_types:
                            leads += int(float(action.get('value', 0)))
                    if leads > 0 and spend > 0:
                        cpl = round(spend / leads, 2)
                out[fb_ad_id] = {"spend": spend, "cpl": cpl}

        logger.info("get_ad_insights_map: resolved %d/%d ads", len(out), len(ids))
        return out

    def get_account_ads_with_creative(self, ad_account_id=None):
        """Bulk-fetch all ACTIVE/PAUSED ads with their creative text for the copy library.

        Uses a single paginated batch call with nested creative fields — much more
        efficient than calling get_ad_creative() per ad.

        Returns a list of dicts:
            {
                "fb_ad_id": str,
                "fb_adset_id": str,
                "adset_name": str,      # raw name — caller extracts niche
                "ad_name": str,
                "headline": str | None,
                "body": str | None,
                "cta_type": str | None,
            }

        Ads missing both headline and body are skipped (no usable copy text).
        """
        import logging
        logger = logging.getLogger(__name__)

        account = self._get_account(ad_account_id)

        # NOTE: The facebook-business SDK silently drops nested field syntax like
        # 'adset{name}' (same issue as 'campaign{objective}' in get_adsets).
        # We do NOT request adset_name here — the caller resolves it via
        # get_adset_name_map() and passes the result separately.
        try:
            ads = account.get_ads(
                fields=[
                    'id',
                    'name',
                    'adset_id',
                    'effective_status',
                    'creative{title,body,'
                    'object_story_spec{link_data{name,message},'
                    'video_data{title,message}},'
                    'asset_feed_spec}',
                ],
                params={
                    'effective_status': ['ACTIVE', 'PAUSED'],
                    'limit': 500,
                },
            )
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            msg = err.get('message') or str(e)
            logger.error("get_account_ads_with_creative failed: %s", msg)
            raise RuntimeError(f"Facebook API: {msg}") from e

        results = []
        for ad in ads:
            fb_ad_id = str(ad.get('id') or '')
            if not fb_ad_id:
                continue

            creative = ad.get('creative') or {}
            oss = creative.get('object_story_spec') or {}
            afs = creative.get('asset_feed_spec') or {}
            link_data = oss.get('link_data') or {}
            video_data = oss.get('video_data') or {}

            # Headline: title → link_data.name → video_data.title → asset_feed_spec.titles[0]
            headline = (
                creative.get('title') or
                link_data.get('name') or
                video_data.get('title') or
                ((afs.get('titles') or [{}])[0].get('text'))
            )

            # Body: body → link_data.message → video_data.message → asset_feed_spec.bodies[0]
            body_text = (
                creative.get('body') or
                link_data.get('message') or
                video_data.get('message') or
                ((afs.get('bodies') or [{}])[0].get('text'))
            )

            # Skip ads with no usable copy
            if not headline and not body_text:
                continue

            results.append({
                'fb_ad_id': fb_ad_id,
                'fb_adset_id': str(ad.get('adset_id') or ''),
                # adset_name intentionally omitted — caller resolves via get_adset_name_map()
                'ad_name': str(ad.get('name') or ''),
                'headline': headline or '',
                'body': body_text or '',
                'status': str(ad.get('effective_status') or ''),
            })

        logger.info("get_account_ads_with_creative: fetched %d ads with copy", len(results))
        return results

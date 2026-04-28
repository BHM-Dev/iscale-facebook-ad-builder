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
            my_accounts = me.get_ad_accounts(fields=['id', 'name', 'account_id', 'account_status', 'currency', 'balance', 'amount_spent'])
            print(f"Found {len(my_accounts)} accounts.")
            return [dict(acc) for acc in my_accounts]
        except Exception as e:
            print(f"Error fetching ad accounts: {e}")
            raise e

    def _get_account(self, ad_account_id=None):
        """Helper to get AdAccount object."""
        if ad_account_id:
            if not ad_account_id.startswith('act_'):
                ad_account_id = f'act_{ad_account_id}'
            return AdAccount(ad_account_id, api=self.api)
        
        if self.account:
            return self.account
            
        raise Exception("No Ad Account ID provided and no default account set.")

    def get_campaigns(self, ad_account_id=None):
        """Fetch all campaigns from the ad account."""
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

        return account.get_campaigns(fields=fields)

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
        return [dict(page) for page in pages]

    def get_adsets(self, ad_account_id=None, campaign_id=None):
        """Fetch all ad sets."""
        fields = [
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

        if campaign_id:
            # Fetch from campaign
            campaign = Campaign(campaign_id, api=self.api)
            return campaign.get_ad_sets(fields=fields)
        
        account = self._get_account(ad_account_id)
        return account.get_ad_sets(fields=fields)

    def get_ads(self, adset_id):
        """Fetch all ads for a specific ad set."""
        adset = AdSet(adset_id, api=self.api)
        fields = [
            Ad.Field.id,
            Ad.Field.name,
            Ad.Field.status,
            Ad.Field.creative,
        ]
        return adset.get_ads(fields=fields)

    # HEC = Housing, Employment, Credit (Financial Products) — Meta enforces targeting restrictions
    HEC_CATEGORIES = {'HOUSING', 'EMPLOYMENT', 'FINANCIAL_PRODUCTS_SERVICES'}

    def create_adset(self, adset_data, ad_account_id=None):
        """Create a new ad set."""
        account = self._get_account(ad_account_id)

        # Detect HEC special ad categories on the parent campaign
        special_categories = set(adset_data.get('specialAdCategories') or adset_data.get('special_ad_categories') or [])
        is_hec = bool(special_categories & self.HEC_CATEGORIES)

        # Transform targeting from camelCase to snake_case
        targeting = adset_data.get('targeting', {})
        transformed_targeting = {}

        # Handle age fields — HEC: Meta enforces default 18/65+, so we omit custom ranges
        if not is_hec:
            if 'ageMin' in targeting:
                transformed_targeting['age_min'] = targeting['ageMin']
            if 'ageMax' in targeting:
                transformed_targeting['age_max'] = targeting['ageMax']

        # Handle genders — HEC: must not filter by gender (omit or pass empty array)
        if 'genders' in targeting and not is_hec:
            transformed_targeting['genders'] = targeting['genders']

        # Handle geo_locations - clean up empty arrays
        if 'geo_locations' in targeting:
            geo_locs = targeting['geo_locations']
            cleaned_geo_locs = {}

            # Keys blocked under HEC: cities, geo_markets, and ALL excluded_* keys
            hec_blocked_keys = {'cities', 'geo_markets', 'excluded_countries', 'excluded_regions',
                                 'excluded_cities', 'excluded_geo_markets'}

            for key, value in geo_locs.items():
                if is_hec and key in hec_blocked_keys:
                    continue  # Strip — Meta will hard-error if these are present
                if isinstance(value, list) and len(value) > 0:
                    cleaned_geo_locs[key] = value
                elif not isinstance(value, list):
                    cleaned_geo_locs[key] = value

            if cleaned_geo_locs:
                transformed_targeting['geo_locations'] = cleaned_geo_locs
        
        # Handle publisher_platforms
        if 'publisher_platforms' in targeting:
            transformed_targeting['publisher_platforms'] = targeting['publisher_platforms']

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
        _ATTRIBUTION_MAP = {
            '1d_click':           [{'event_type': 'CLICK_THROUGH', 'window_days': 1}],
            '7d_click':           [{'event_type': 'CLICK_THROUGH', 'window_days': 7}],
            '28d_click':          [{'event_type': 'CLICK_THROUGH', 'window_days': 28}],
            '1d_click_1d_view':   [{'event_type': 'CLICK_THROUGH', 'window_days': 1},
                                   {'event_type': 'VIEW_THROUGH',  'window_days': 1}],
            '7d_click_1d_view':   [{'event_type': 'CLICK_THROUGH', 'window_days': 7},
                                   {'event_type': 'VIEW_THROUGH',  'window_days': 1}],
            '28d_click_1d_view':  [{'event_type': 'CLICK_THROUGH', 'window_days': 28},
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
            return account.create_ad_set(params=params)
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
            image.remote_create()

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
            image.remote_create()
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
            video.remote_create()

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

    def create_creative(self, creative_data, ad_account_id=None):
        """Create an ad creative (supports both image and video)."""
        account = self._get_account(ad_account_id)

        page_id = creative_data.get('page_id') or creative_data.get('pageId')
        image_hash = creative_data.get('image_hash')
        video_id = creative_data.get('video_id')
        website_url = (creative_data.get('website_url') or creative_data.get('websiteUrl') or '').strip()

        if not page_id:
            raise ValueError('page_id is required to create an ad creative')
        if not image_hash and not video_id:
            raise ValueError('Either image_hash or video_id is required')
        if not website_url or not website_url.startswith('http'):
            raise ValueError('website_url must be a valid URL (e.g. https://example.com)')

        primary_text = creative_data.get('primary_text') or creative_data.get('message') or ''
        headline = creative_data.get('headline') or creative_data.get('name') or 'Ad'
        cta = creative_data.get('cta') or 'LEARN_MORE'
        creative_name = creative_data.get('name') or creative_data.get('creativeName') or f'Creative {headline[:30]}'

        # Determine if this is a video or image creative
        if video_id:
            # Video creative
            object_story_spec = {
                'page_id': page_id,
                'video_data': {
                    'video_id': video_id,
                    'message': primary_text,
                    'title': headline,
                    'call_to_action': {
                        'type': cta,
                        'value': {'link': website_url}
                    }
                }
            }
            if creative_data.get('thumbnail_url'):
                object_story_spec['video_data']['image_url'] = creative_data['thumbnail_url']
        else:
            # Image creative
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

        if creative_data.get('instagram_actor_id'):
            object_story_spec['instagram_actor_id'] = creative_data['instagram_actor_id']

        params = {
            AdCreative.Field.name: creative_name,
            AdCreative.Field.object_story_spec: object_story_spec,
        }

        try:
            return account.create_ad_creative(params=params)
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            user_msg = err.get('error_user_msg') or err.get('message') or (e.api_error_message() if hasattr(e, 'api_error_message') and callable(e.api_error_message) else str(e))
            raise RuntimeError(f"Facebook API: {user_msg}") from e

    def create_ad(self, ad_data, ad_account_id=None):
        """Create an ad."""
        account = self._get_account(ad_account_id)

        adset_id = ad_data.get('adset_id') or ad_data.get('adsetId')
        creative_id = ad_data.get('creative_id') or ad_data.get('creativeId')
        name = ad_data.get('name') or 'Ad'
        status = ad_data.get('status') or 'ACTIVE'

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

        try:
            return account.create_ad(params=params)
        except FacebookRequestError as e:
            body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
            err = body.get('error', {}) if isinstance(body, dict) else {}
            user_msg = err.get('error_user_msg') or err.get('message') or (e.api_error_message() if hasattr(e, 'api_error_message') and callable(e.api_error_message) else str(e))
            raise RuntimeError(f"Facebook API: {user_msg}") from e

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
                'clicks': 0, 'ctr': 0.0,
                'revenue': None, 'roas': None,
                'date_preset': date_preset,
            }

        row = results[0]

        spend = float(row.get('spend', 0) or 0)
        impressions = int(row.get('impressions', 0) or 0)
        reach = int(row.get('reach', 0) or 0)
        frequency = round(float(row.get('frequency', 0) or 0), 2)
        clicks = int(row.get('clicks', 0) or 0)
        ctr = float(row.get('ctr', 0) or 0)

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
            'ctr': round(ctr, 4),
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

            spend      = float(row.get('spend', 0) or 0)
            impressions = int(row.get('impressions', 0) or 0)
            reach       = int(row.get('reach', 0) or 0)
            frequency   = round(float(row.get('frequency', 0) or 0), 2)
            clicks      = int(row.get('clicks', 0) or 0)
            ctr         = float(row.get('ctr', 0) or 0)

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
                'spend':       round(spend, 2),
                'leads':       leads,
                'cpl':         round(cpl, 2) if cpl is not None else None,
                'impressions': impressions,
                'reach':       reach,
                'frequency':   frequency,
                'clicks':      clicks,
                'ctr':         round(ctr, 4),
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

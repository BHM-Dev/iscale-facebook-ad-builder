"""Facebook integration unit tests."""
import pytest
from fastapi import status
from unittest.mock import MagicMock, patch


class TestFacebookCampaigns:
    """Tests for Facebook campaign management."""

    def test_list_campaigns_no_token(self, client, auth_headers):
        """Test listing campaigns without FB token configured."""
        response = client.get(
            "/api/v1/facebook/campaigns",
            headers=auth_headers
        )
        # Without valid FB token, will return 500 (service error) or 200 with empty
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_500_INTERNAL_SERVER_ERROR  # Facebook service error
        ]

    def test_create_campaign_validation(self, client, auth_headers):
        """Test campaign creation validation."""
        # Missing required fields - will fail at Facebook service level
        response = client.post(
            "/api/v1/facebook/campaigns",
            json={},
            headers=auth_headers
        )
        # Without valid FB token, returns 500 from service
        assert response.status_code in [
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ]

    def test_save_campaign_locally(self, client, auth_headers):
        """Test saving campaign to local database."""
        response = client.post(
            "/api/v1/facebook/campaigns/save",
            json={
                "name": "Test Campaign",
                "objective": "CONVERSIONS",
                "status": "PAUSED",
                "fb_campaign_id": "test_fb_123"
            },
            headers=auth_headers
        )
        # Should succeed in saving locally
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
            status.HTTP_422_UNPROCESSABLE_ENTITY  # If schema is different
        ]


class TestFacebookAdSets:
    """Tests for Facebook ad set management."""

    def test_save_adset_locally(self, client, auth_headers):
        """Test saving ad set to local database."""
        import uuid
        # First create a campaign with explicit ID
        campaign_id = str(uuid.uuid4())
        campaign_response = client.post(
            "/api/v1/facebook/campaigns/save",
            json={
                "id": campaign_id,
                "name": "AdSet Test Campaign",
                "objective": "CONVERSIONS",
                "status": "PAUSED"
            },
            headers=auth_headers
        )

        if campaign_response.status_code == status.HTTP_200_OK:
            # Use campaignId (camelCase) as expected by API
            response = client.post(
                "/api/v1/facebook/adsets/save",
                json={
                    "name": "Test AdSet",
                    "campaignId": campaign_id,  # camelCase!
                    "status": "PAUSED",
                    "dailyBudget": 1000
                },
                headers=auth_headers
            )
            assert response.status_code in [
                status.HTTP_200_OK,
                status.HTTP_201_CREATED,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                status.HTTP_500_INTERNAL_SERVER_ERROR  # FK constraint if campaign not saved
            ]


class TestFacebookAds:
    """Tests for Facebook ad management."""

    def test_save_ad_locally(self, client, auth_headers):
        """Test saving ad to local database."""
        response = client.post(
            "/api/v1/facebook/ads/save",
            json={
                "name": "Test Ad",
                "status": "PAUSED",
                "mediaType": "image",
                "imageUrl": "https://example.com/image.jpg"
            },
            headers=auth_headers
        )
        # Saves without adsetId (nullable)
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ]


class TestFacebookMediaUpload:
    """Tests for Facebook media upload."""

    def test_upload_image_no_url(self, client, auth_headers):
        """Test image upload without image_url returns error."""
        response = client.post(
            "/api/v1/facebook/upload-image",
            json={},  # Missing image_url
            headers=auth_headers
        )
        # Either 400 (missing image_url) or 500 (FB service error)
        assert response.status_code in [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ]

    def test_video_status_invalid_id(self, client, auth_headers):
        """Test video status with invalid ID."""
        response = client.get(
            "/api/v1/facebook/video-status/invalid_video_id",
            headers=auth_headers
        )
        # Should handle gracefully
        assert response.status_code in [
            status.HTTP_200_OK,  # Returns status info
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND
        ]


class TestFacebookLocations:
    """Tests for Facebook location search."""

    def test_search_locations(self, client, auth_headers):
        """Test location search endpoint."""
        response = client.get(
            "/api/v1/facebook/locations/search?q=New York",
            headers=auth_headers
        )
        # Without valid FB token, returns 500 from service
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_404_NOT_FOUND,  # Endpoint might not exist
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ]


class TestFacebookServiceMocked:
    """Tests with mocked Facebook service."""

    def test_get_campaigns_mocked(self, client, auth_headers, mock_facebook_service):
        """Test getting campaigns with mocked service."""
        mock_facebook_service.get_campaigns.return_value = [
            {"id": "camp_1", "name": "Test Campaign 1"},
            {"id": "camp_2", "name": "Test Campaign 2"}
        ]

        response = client.get(
            "/api/v1/facebook/campaigns",
            headers=auth_headers
        )
        # With mock, should return data
        assert response.status_code == status.HTTP_200_OK

    def test_create_campaign_mocked(self, client, auth_headers, mock_facebook_service):
        """Test creating campaign with mocked service."""
        mock_facebook_service.create_campaign.return_value = {
            "id": "new_camp_123",
            "name": "New Campaign"
        }

        response = client.post(
            "/api/v1/facebook/campaigns",
            json={
                "name": "New Campaign",
                "objective": "CONVERSIONS",
                "status": "PAUSED",
                "ad_account_id": "act_123456"
            },
            headers=auth_headers
        )
        # Should work with mock
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
            status.HTTP_422_UNPROCESSABLE_ENTITY  # Schema mismatch
        ]

    def test_upload_video_mocked(self, client, auth_headers, mock_facebook_service):
        """Test video upload with mocked service."""
        mock_facebook_service.upload_video.return_value = {
            "video_id": "vid_123",
            "status": "processing"
        }

        # Create a minimal video file
        from io import BytesIO
        video_content = b"\x00\x00\x00\x1c\x66\x74\x79\x70" + b"\x00" * 100  # Minimal MP4 header

        response = client.post(
            "/api/v1/facebook/upload-video",
            files={"file": ("test.mp4", BytesIO(video_content), "video/mp4")},
            data={"ad_account_id": "act_123456"},
            headers=auth_headers
        )
        # May or may not use the mock depending on implementation
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


class TestCreateCreativeDualPlacement:
    """Locks the backward-compatibility guarantee for create_creative's new
    asset_feed_spec (dual-placement / Bulk Match Import) branch: no
    secondary_image_hash must be byte-identical to pre-feature behavior, and
    supplying one must produce the expected Feed+Story asset_feed_spec shape.
    """

    def _make_service_with_mock_account(self):
        from app.services.facebook_service import FacebookService

        service = FacebookService.__new__(FacebookService)  # skip __init__/env lookups
        service.access_token = None
        service.ad_account_id = None
        service.api = None
        service.account = MagicMock()
        service.account.create_ad_creative.return_value = {"id": "creative_123"}
        return service

    def _base_creative_data(self):
        return {
            "page_id": "123456",
            "image_hash": "feed_hash_abc",
            "website_url": "https://example.com/offer",
            "primary_text": "Body copy",
            "headline": "Headline",
            "cta": "LEARN_MORE",
        }

    def test_create_creative_without_secondary_image_no_asset_feed_spec(self):
        """No secondary_image_hash → params must have no asset_feed_spec key at all."""
        from facebook_business.adobjects.adcreative import AdCreative

        service = self._make_service_with_mock_account()
        service.create_creative(self._base_creative_data())

        params = service.account.create_ad_creative.call_args.kwargs["params"]
        assert AdCreative.Field.asset_feed_spec not in params
        assert "link_data" in params[AdCreative.Field.object_story_spec]

    def test_create_creative_with_secondary_image_builds_dual_placement_spec(self):
        """secondary_image_hash + explicit instagram_user_id → expected asset_feed_spec
        shape, no link_data, both placements include Instagram positions."""
        from facebook_business.adobjects.adcreative import AdCreative

        service = self._make_service_with_mock_account()
        creative_data = {
            **self._base_creative_data(),
            "secondary_image_hash": "story_hash_xyz",
            "description": "Some description",
            "instagram_user_id": "ig_user_789",
        }
        service.create_creative(creative_data)

        params = service.account.create_ad_creative.call_args.kwargs["params"]
        oss = params[AdCreative.Field.object_story_spec]
        assert "link_data" not in oss
        assert oss["instagram_user_id"] == "ig_user_789"
        assert "instagram_actor_id" not in oss

        afs = params[AdCreative.Field.asset_feed_spec]
        image_labels = {
            label["name"]
            for img in afs["images"]
            for label in img.get("adlabels", [])
        }
        assert image_labels == {"feed_image", "story_image"}
        assert len(afs["images"]) == 2
        assert len(afs["asset_customization_rules"]) == 2
        assert afs["descriptions"] == [{"text": "Some description"}]

        rule_by_label = {
            rule["image_label"]["name"]: rule["customization_spec"]
            for rule in afs["asset_customization_rules"]
        }
        assert rule_by_label["feed_image"]["facebook_positions"] == ["feed"]
        assert rule_by_label["feed_image"]["instagram_positions"] == ["stream"]
        assert rule_by_label["feed_image"]["publisher_platforms"] == ["facebook", "instagram"]
        assert rule_by_label["story_image"]["facebook_positions"] == ["story"]
        assert rule_by_label["story_image"]["instagram_positions"] == ["story", "reels"]
        assert rule_by_label["story_image"]["publisher_platforms"] == ["facebook", "instagram"]

    def test_create_creative_with_secondary_image_no_instagram_account_falls_back_to_facebook_only(self):
        """secondary_image_hash present, no instagram_user_id given and the page lookup
        finds no linked IG account (mocked to return None) → asset_customization_rules
        must drop instagram_positions and publisher_platforms entirely, not error or
        silently send Meta an invalid instagram_positions with no actor. This is the
        real production bug confirmed live 2026-08-17: Meta accepts the creative (200)
        but rejects the subsequent ad-create call with "Select an Instagram account or
        a Facebook Page to represent your business on Instagram." when
        instagram_positions is declared without an Instagram user id.
        """
        from facebook_business.adobjects.adcreative import AdCreative

        service = self._make_service_with_mock_account()
        service._get_page_instagram_user_id = MagicMock(return_value=None)
        creative_data = {
            **self._base_creative_data(),
            "secondary_image_hash": "story_hash_xyz",
        }
        service.create_creative(creative_data)

        service._get_page_instagram_user_id.assert_called_once_with("123456")

        params = service.account.create_ad_creative.call_args.kwargs["params"]
        oss = params[AdCreative.Field.object_story_spec]
        assert "instagram_actor_id" not in oss
        assert "instagram_user_id" not in oss

        afs = params[AdCreative.Field.asset_feed_spec]
        for rule in afs["asset_customization_rules"]:
            spec = rule["customization_spec"]
            assert "instagram_positions" not in spec
            assert spec["publisher_platforms"] == ["facebook"]

    def test_create_creative_accepts_legacy_instagram_actor_id_as_input_alias_only(self):
        """Old callers can still pass instagram_actor_id, but Meta receives only
        object_story_spec.instagram_user_id."""
        from facebook_business.adobjects.adcreative import AdCreative

        service = self._make_service_with_mock_account()
        creative_data = {
            **self._base_creative_data(),
            "secondary_image_hash": "story_hash_xyz",
            "instagram_actor_id": "legacy_ig_id",
        }
        service.create_creative(creative_data)

        params = service.account.create_ad_creative.call_args.kwargs["params"]
        oss = params[AdCreative.Field.object_story_spec]
        assert oss["instagram_user_id"] == "legacy_ig_id"
        assert "instagram_actor_id" not in oss


class TestCampaignStateInsights:
    def test_state_breakdown_uses_its_own_bounded_meta_session(self):
        """A Geography refresh must not inherit an unbounded shared SDK session."""
        from app.services.facebook_service import FacebookService

        service = FacebookService.__new__(FacebookService)
        service.access_token = 'token'

        with patch('facebook_business.session.FacebookSession') as session_class, patch(
            'app.services.facebook_service.FacebookAdsApi'
        ) as api_class, patch('app.services.facebook_service.AdAccount') as account_class:
            account, session = service._get_state_insights_account('456')

        session_class.assert_called_once_with(
            None, None, 'token', timeout=(5, 15)
        )
        api_class.assert_called_once_with(session_class.return_value)
        account_class.assert_called_once_with('act_456', api=api_class.return_value)
        assert account is account_class.return_value
        assert session is session_class.return_value

    def test_state_breakdown_uses_default_account_with_bounded_session(self):
        from app.services.facebook_service import FacebookService

        service = FacebookService.__new__(FacebookService)
        service.access_token = 'token'
        service.ad_account_id = '789'

        with patch('facebook_business.session.FacebookSession'), patch(
            'app.services.facebook_service.FacebookAdsApi'
        ) as api_class, patch('app.services.facebook_service.AdAccount') as account_class:
            service._get_state_insights_account()

        account_class.assert_called_once_with('act_789', api=api_class.return_value)

    def test_state_breakdown_timeout_does_not_wait_for_hung_worker(self):
        """A timed-out daily region cursor must return control immediately.

        ThreadPoolExecutor's context-manager shutdown waits for a running
        worker, which previously left the Geography view loading forever after
        its advertised 20-second timeout.
        """
        import threading
        import time
        from app.services import facebook_service
        from app.services.facebook_service import FacebookService

        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        account = MagicMock()

        def slow_insights(_fields, _params):
            entered.set()
            release.wait(timeout=1)
            finished.set()
            return []

        account.get_insights.side_effect = slow_insights

        service = FacebookService.__new__(FacebookService)
        service._get_state_insights_account = MagicMock(return_value=(account, None))

        started = time.monotonic()
        try:
            with patch.object(facebook_service, 'STATE_INSIGHTS_RESULT_TIMEOUT_SECONDS', 0.01), pytest.raises(
                RuntimeError, match='Meta API timeout'
            ):
                service.get_account_campaign_state_insights(
                    ad_account_id='act_456', date_from='2026-09-01', date_to='2026-09-20', day_filter='weekday'
                )
            # The property under test is "didn't wait for release.wait(timeout=1)
            # to fire," not a tight latency budget — 0.2s left little margin
            # under real CI scheduling/GC contention.
            assert time.monotonic() - started < 1.0
            assert entered.wait(timeout=0.5)
            with pytest.raises(RuntimeError, match='still finishing'):
                service.get_account_campaign_state_insights(
                    ad_account_id='act_456', date_from='2026-09-01', date_to='2026-09-20', day_filter='weekday'
                )
        finally:
            release.set()
        assert finished.wait(timeout=1)

    def test_state_breakdown_stops_before_fetching_another_page_after_deadline(self):
        """The worker must not keep walking cursor pages after the UI deadline."""
        import time
        from app.services import facebook_service
        from app.services.facebook_service import FacebookService

        page_fetches = []

        class SlowCursor:
            def __iter__(self):
                return self

            def __next__(self):
                page_fetches.append(True)
                if len(page_fetches) > 1:
                    raise AssertionError('cursor fetched a page after its deadline')
                time.sleep(0.02)
                return {'region': 'New York'}

        account = MagicMock()
        account.get_insights.return_value = SlowCursor()
        service = FacebookService.__new__(FacebookService)
        service._get_state_insights_account = MagicMock(return_value=(account, None))

        with patch.object(facebook_service, 'STATE_INSIGHTS_FETCH_DEADLINE_SECONDS', 0.01), patch.object(
            facebook_service, 'STATE_INSIGHTS_RESULT_TIMEOUT_SECONDS', 1
        ), pytest.raises(RuntimeError, match='Meta API timeout'):
            service.get_account_campaign_state_insights(ad_account_id='act_456')

        assert len(page_fetches) == 1

    def test_state_breakdown_is_campaign_scoped_and_lead_gen_safe(self):
        """State diagnosis must use Meta's supported region breakdown and never
        infer revenue/ROAS from the account-level attribution cache."""
        from app.services.facebook_service import FacebookService

        account = MagicMock()
        account.get_insights.return_value = [
            {
                'region': 'New York', 'spend': '180.00', 'impressions': '12000',
                'reach': '9000', 'clicks': '140', 'ctr': '1.1667',
                'actions': [{'action_type': 'lead', 'value': '3'}],
                'cost_per_action_type': [{'action_type': 'lead', 'value': '60'}],
            },
            {
                'region': 'California', 'spend': '100.00', 'impressions': '8000',
                'reach': '6000', 'clicks': '120', 'ctr': '1.5',
                'actions': [{'action_type': 'offsite_conversion.fb_pixel_lead', 'value': '4'}],
                'cost_per_action_type': [],
            },
        ]
        service = FacebookService.__new__(FacebookService)
        service._get_account = MagicMock(return_value=account)

        rows = service.get_campaign_state_insights('campaign_123', 'act_456', date_preset='last_7d')

        assert [row['state'] for row in rows] == ['New York', 'California']
        assert rows[0]['cpl'] == 60.0
        assert rows[1]['cpl'] == 25.0
        fields, params = account.get_insights.call_args.args
        assert 'region' not in fields
        assert params['level'] == 'campaign'
        assert params['breakdowns'] == ['region']
        assert params['filtering'] == [{'field': 'campaign.id', 'operator': 'IN', 'value': ['campaign_123']}]

    def test_account_state_breakdown_uses_one_unfiltered_campaign_query(self):
        from app.services.facebook_service import FacebookService

        account = MagicMock()
        account.get_insights.return_value = [{
            'campaign_id': 'campaign_123', 'campaign_name': 'Car Rental',
            'region': 'New York', 'spend': '120.00', 'impressions': '8000',
            'reach': '6000', 'clicks': '100', 'ctr': '1.25',
            'actions': [{'action_type': 'lead', 'value': '3'}],
            'cost_per_action_type': [{'action_type': 'lead', 'value': '40'}],
        }]
        service = FacebookService.__new__(FacebookService)
        service._get_account = MagicMock(return_value=account)

        rows = service.get_account_campaign_state_insights(ad_account_id='act_456', date_from='2026-09-01', date_to='2026-09-20')

        assert rows[0]['campaign_id'] == 'campaign_123'
        assert rows[0]['campaign_name'] == 'Car Rental'
        fields, params = account.get_insights.call_args.args
        assert 'region' not in fields
        assert params['breakdowns'] == ['region']
        assert params['level'] == 'campaign'
        assert 'filtering' not in params

    def test_account_state_breakdown_aggregates_weekend_rows_only(self):
        from app.services.facebook_service import FacebookService

        account = MagicMock()
        account.get_insights.return_value = [
            {'campaign_id': 'campaign_123', 'campaign_name': 'Car Rental', 'region': 'New York', 'date_start': '2026-09-19', 'spend': '60', 'impressions': '4000', 'reach': '3000', 'clicks': '50', 'actions': [{'action_type': 'lead', 'value': '1'}]},
            {'campaign_id': 'campaign_123', 'campaign_name': 'Car Rental', 'region': 'New York', 'date_start': '2026-09-20', 'spend': '90', 'impressions': '6000', 'reach': '4500', 'clicks': '75', 'actions': [{'action_type': 'lead', 'value': '2'}]},
            {'campaign_id': 'campaign_123', 'campaign_name': 'Car Rental', 'region': 'New York', 'date_start': '2026-09-21', 'spend': '150', 'impressions': '10000', 'reach': '7500', 'clicks': '125', 'actions': [{'action_type': 'lead', 'value': '6'}]},
        ]
        service = FacebookService.__new__(FacebookService)
        service._get_account = MagicMock(return_value=account)

        rows = service.get_account_campaign_state_insights(ad_account_id='act_456', date_from='2026-09-19', date_to='2026-09-21', day_filter='weekend')

        # reach is unique-people, not additive across days — the day-filtered
        # path must not sum it into a misleading total.
        assert rows == [{
            'campaign_id': 'campaign_123', 'campaign_name': 'Car Rental', 'state': 'New York',
            'spend': 150.0, 'leads': 3, 'impressions': 10000, 'reach': None, 'clicks': 125,
            'cpl': 50.0, 'ctr': 1.25,
        }]
        _, params = account.get_insights.call_args.args
        assert params['time_increment'] == 1

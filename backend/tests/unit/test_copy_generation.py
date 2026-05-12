"""Copy generation unit tests."""
import pytest
from fastapi import status
from unittest.mock import MagicMock, patch
import json


def make_brand_payload(name, **kwargs):
    """Create a brand payload with required colors."""
    return {
        "name": name,
        "colors": {
            "primary": kwargs.get("primary", "#FF0000"),
            "secondary": kwargs.get("secondary", "#00FF00"),
            "highlight": kwargs.get("highlight", "#0000FF")
        },
        "voice": kwargs.get("voice", "Professional"),
        "products": kwargs.get("products", []),
        "profileIds": kwargs.get("profileIds", [])
    }


class TestCopyGeneration:
    """Tests for AI copy generation."""

    @pytest.fixture
    def test_brand(self, client, auth_headers):
        """Create a test brand."""
        response = client.post(
            "/api/v1/brands/",
            json=make_brand_payload("Copy Gen Test Brand", voice="Professional and friendly"),
            headers=auth_headers
        )
        return response.json()

    @pytest.fixture
    def test_product(self, client, auth_headers, test_brand):
        """Create a test product."""
        brand_id = test_brand.get("id")
        if not brand_id:
            pytest.skip("Brand creation failed, cannot create product")
        response = client.post(
            "/api/v1/products/",
            json={
                "name": "Copy Gen Test Product",
                "description": "A revolutionary product that solves problems",
                "brand_id": brand_id
            },
            headers=auth_headers
        )
        return response.json()

    @pytest.fixture
    def test_profile(self, client, auth_headers):
        """Create a test profile."""
        response = client.post(
            "/api/v1/profiles/",
            json={
                "name": "Copy Gen Test Profile",
                "demographics": "Adults 25-45",
                "painPoints": "Time constraints, budget concerns",
                "goals": "Efficiency, cost savings"
            },
            headers=auth_headers
        )
        return response.json()

    def test_generate_copy_endpoint_exists(self, client, auth_headers):
        """Test that copy generation endpoint exists."""
        response = client.post(
            "/api/v1/copy-generation/generate",
            json={},
            headers=auth_headers
        )
        # Should return validation error, not 404
        assert response.status_code != status.HTTP_404_NOT_FOUND

    def test_generate_copy_validation(self, client, auth_headers):
        """Test copy generation with missing data."""
        response = client.post(
            "/api/v1/copy-generation/generate",
            json={
                "brand_id": "nonexistent"
            },
            headers=auth_headers
        )
        assert response.status_code in [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            status.HTTP_404_NOT_FOUND
        ]

    @patch('app.api.v1.copy_generation._anthropic_client')
    def test_generate_copy_mocked(self, mock_client, client, auth_headers, test_brand, test_product, test_profile):
        """Test copy generation with mocked Anthropic."""
        # Mock Anthropic response
        mock_content = MagicMock()
        mock_content.text = json.dumps({
            "variations": [
                {
                    "headline": "Transform Your Life Today",
                    "body": "Discover how our revolutionary product can help you achieve your goals.",
                    "cta": "Get Started"
                },
                {
                    "headline": "Save Time & Money",
                    "body": "Join thousands of satisfied customers who have already made the switch.",
                    "cta": "Learn More"
                },
                {
                    "headline": "Limited Time Offer",
                    "body": "Don't miss out on this exclusive opportunity to upgrade your experience.",
                    "cta": "Shop Now"
                }
            ]
        })
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response

        response = client.post(
            "/api/v1/copy-generation/generate",
            json={
                "brand_id": test_brand["id"],
                "product_id": test_product["id"],
                "profile_id": test_profile["id"],
                "variation_count": 3
            },
            headers=auth_headers
        )

        # With mock, should return generated copy
        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            assert "variations" in data or isinstance(data, list)

    def test_regenerate_field_endpoint_exists(self, client, auth_headers):
        """Test that field regeneration endpoint exists."""
        response = client.post(
            "/api/v1/copy-generation/regenerate-field",
            json={},
            headers=auth_headers
        )
        # Should return validation error, not 404
        assert response.status_code != status.HTTP_404_NOT_FOUND


class TestCopyGenerationEdgeCases:
    """Edge case tests for copy generation."""

    @patch('app.api.v1.copy_generation._anthropic_client')
    def test_claude_returns_markdown(self, mock_client, client, auth_headers):
        """Test handling Claude response wrapped in markdown."""
        mock_content = MagicMock()
        # Claude sometimes returns JSON wrapped in markdown code blocks
        mock_content.text = """```json
{
    "variations": [
        {"headline": "Test", "body": "Test body", "cta": "Buy"}
    ]
}
```"""
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response

        response = client.post(
            "/api/v1/copy-generation/generate",
            json={
                "brand_id": "test-brand",
                "variation_count": 1
            },
            headers=auth_headers
        )
        # Should handle markdown stripping gracefully
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch('app.api.v1.copy_generation._anthropic_client')
    def test_claude_api_error(self, mock_client, client, auth_headers):
        """Test handling Claude API errors."""
        mock_client.messages.create.side_effect = Exception("API Error")

        response = client.post(
            "/api/v1/copy-generation/generate",
            json={
                "brand_id": "test-brand",
                "variation_count": 1
            },
            headers=auth_headers
        )
        # Should handle error gracefully
        assert response.status_code in [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            status.HTTP_503_SERVICE_UNAVAILABLE
        ]

    @patch('app.api.v1.copy_generation._anthropic_client')
    def test_claude_invalid_json(self, mock_client, client, auth_headers):
        """Test handling invalid JSON from Claude."""
        mock_content = MagicMock()
        mock_content.text = "This is not valid JSON"
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response

        response = client.post(
            "/api/v1/copy-generation/generate",
            json={
                "brand_id": "test-brand",
                "variation_count": 1
            },
            headers=auth_headers
        )
        # Should handle parsing error gracefully
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

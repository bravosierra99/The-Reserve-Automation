"""Tests for bulk ingredient import endpoints.

Tests use mocked LLM/search to avoid external dependencies.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestBulkSave:
    """Test POST /api/v1/ingredients/bulk-save (no LLM needed)."""

    def test_bulk_save_creates_ingredients(self, test_client):
        """Bulk save creates multiple ingredients in DB."""
        response = test_client.post("/api/v1/ingredients/bulk-save", json={
            "parent": "Vodka",
            "ingredients": [
                {"name": "Grey Goose Vodka", "brand": "Grey Goose", "cost": 29.99, "abv": 40.0, "selected": True},
                {"name": "Belvedere Vodka", "brand": "Belvedere", "cost": 27.99, "abv": 40.0, "selected": True},
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["saved"]) == 2
        assert data["saved"][0]["name"] == "Grey Goose Vodka"
        assert data["saved"][1]["name"] == "Belvedere Vodka"

        # Verify ingredients exist via API
        search_resp = test_client.get("/api/v1/ingredients/search?q=Grey Goose")
        assert any(i["name"] == "Grey Goose Vodka" for i in search_resp.json())
        search_resp = test_client.get("/api/v1/ingredients/search?q=Belvedere")
        assert any(i["name"] == "Belvedere Vodka" for i in search_resp.json())

    def test_bulk_save_skips_unselected(self, test_client):
        """Unselected items are skipped."""
        response = test_client.post("/api/v1/ingredients/bulk-save", json={
            "parent": None,
            "ingredients": [
                {"name": "BulkTest Selected", "selected": True},
                {"name": "BulkTest Unselected", "selected": False},
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["saved"]) == 1
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["reason"] == "not selected"

    def test_bulk_save_skips_duplicates(self, test_client):
        """Already-existing ingredients are skipped."""
        response = test_client.post("/api/v1/ingredients/bulk-save", json={
            "parent": None,
            "ingredients": [
                {"name": "Vodka", "selected": True},  # Already exists in fixture
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["saved"]) == 0
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["reason"] == "already exists"

    def test_bulk_save_invalid_parent(self, test_client):
        """Bulk save with nonexistent parent fails."""
        response = test_client.post("/api/v1/ingredients/bulk-save", json={
            "parent": "NonExistentParent",
            "ingredients": [
                {"name": "Test Item", "selected": True},
            ]
        })
        assert response.status_code == 404


class TestBulkSearch:
    """Test POST /api/v1/ingredients/bulk-search (mocked LLM)."""

    def test_bulk_search_with_mock(self, test_client):
        """Bulk search returns results from mocked LLM."""
        mock_results = json.dumps([
            {"name": "Tito's Vodka", "brand": "Tito's", "cost": 19.99, "abv": 40.0, "notes": "Texas vodka"},
        ])

        # Mock both the tool executor and LLM gateway (imported inside the function)
        with patch("reserve_automation.llm.tool_executor.ToolExecutor") as MockTE, \
             patch("reserve_automation.llm.gateway.LLMGateway") as MockGW:

            # Setup tool executor mock
            mock_te = MagicMock()
            mock_te.execute.return_value = {
                "results": [
                    {"title": "Tito's Vodka", "snippet": "Handmade vodka from Texas", "href": "https://example.com"}
                ]
            }
            MockTE.return_value = mock_te

            # Setup LLM gateway mock
            mock_gw = MagicMock()
            mock_response = MagicMock()
            mock_response.content = mock_results
            mock_gw.complete = AsyncMock(return_value=mock_response)
            MockGW.return_value = mock_gw

            response = test_client.post("/api/v1/ingredients/bulk-search", json={
                "query": "vodka brands",
                "parent": "Vodka",
            })
            assert response.status_code == 200
            data = response.json()
            assert len(data["results"]) == 1
            assert data["results"][0]["name"] == "Tito's Vodka"
            assert data["parent"] == "Vodka"

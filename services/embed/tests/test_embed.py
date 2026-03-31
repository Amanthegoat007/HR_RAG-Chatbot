"""
============================================================================
FILE: services/embed/tests/test_embed.py
PURPOSE: Unit tests for the embedding service.
         Uses mocked BGE-M3 model to avoid loading the real model in tests.
ARCHITECTURE REF: §12 — Testing & Validation
DEPENDENCIES: pytest, unittest.mock
============================================================================
"""

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock the FlagEmbedding model before importing the app
# This prevents the test from trying to download/load the 1.1GB model
mock_model = MagicMock()
mock_model.encode.return_value = {
    # Simulate dense vectors: 2 texts × 1024 dimensions
    "dense_vecs": [[0.1] * 1024, [0.2] * 1024],
    # Simulate sparse vectors: dict per text
    "lexical_weights": [
        {1: 0.5, 42: 0.3, 100: 0.2},
        {5: 0.8, 21: 0.1},
    ],
}

# Patch BGEM3FlagModel at module level before app import
with patch("FlagEmbedding.BGEM3FlagModel", return_value=mock_model):
    sys.path.insert(0, "/app")
    from app.embedding_service import embedding_service
    # Pre-set model as loaded for tests
    embedding_service._model = mock_model
    embedding_service._load_time = 1.0

    from app.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200_when_model_loaded(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_schema(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "embedding-svc"
        assert data["model_loaded"] is True
        assert "uptime_seconds" in data


class TestEmbedEndpoint:
    """Tests for POST /embed."""

    def test_embed_single_text(self, client):
        """Single text input should return one result."""
        # Update mock to return single-text output
        mock_model.encode.return_value = {
            "dense_vecs": [[0.1] * 1024],
            "lexical_weights": [{1: 0.5, 42: 0.3}],
        }

        response = client.post("/embed", json={"texts": ["Leave policy for UAE employees"]})
        assert response.status_code == 200

        data = response.json()
        assert len(data["results"]) == 1
        assert len(data["results"][0]["dense"]["values"]) == 1024
        assert len(data["results"][0]["sparse"]["indices"]) == 2
        assert data["model"] == "BAAI/bge-m3"

    def test_embed_batch_texts(self, client):
        """Multiple texts should return multiple results in same order."""
        mock_model.encode.return_value = {
            "dense_vecs": [[0.1] * 1024, [0.2] * 1024],
            "lexical_weights": [{1: 0.5}, {5: 0.8}],
        }

        response = client.post("/embed", json={
            "texts": ["Annual leave policy", "Sick leave entitlement"]
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2

    def test_embed_empty_texts_returns_422(self, client):
        """Empty text list should return validation error."""
        response = client.post("/embed", json={"texts": []})
        assert response.status_code == 422

    def test_embed_too_many_texts_returns_422(self, client):
        """More than 128 texts should return validation error."""
        response = client.post("/embed", json={"texts": ["text"] * 129})
        assert response.status_code == 422

    def test_embed_returns_processing_time(self, client):
        """Response should include processing time."""
        mock_model.encode.return_value = {
            "dense_vecs": [[0.1] * 1024],
            "lexical_weights": [{1: 0.5}],
        }
        response = client.post("/embed", json={"texts": ["test"]})
        assert "processing_time_ms" in response.json()

    def test_embed_with_custom_batch_size(self, client):
        """Custom batch_size parameter should be accepted."""
        mock_model.encode.return_value = {
            "dense_vecs": [[0.1] * 1024],
            "lexical_weights": [{1: 0.5}],
        }
        response = client.post("/embed", json={"texts": ["test"], "batch_size": 8})
        assert response.status_code == 200

    def test_embed_sparse_vector_structure(self, client):
        """Sparse vector should have matching indices and values arrays."""
        mock_model.encode.return_value = {
            "dense_vecs": [[0.1] * 1024],
            "lexical_weights": [{1: 0.5, 42: 0.3, 100: 0.2}],
        }
        response = client.post("/embed", json={"texts": ["test"]})
        sparse = response.json()["results"][0]["sparse"]
        assert len(sparse["indices"]) == len(sparse["values"])
        assert len(sparse["indices"]) == 3

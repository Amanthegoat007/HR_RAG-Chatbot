"""
============================================================================
FILE: services/rerank/tests/test_rerank.py
PURPOSE: Unit tests for the reranker service.
ARCHITECTURE REF: §12 — Testing & Validation
============================================================================
"""

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock FlagReranker before importing the app
mock_reranker = MagicMock()
# Return scores in arbitrary order to test sorting logic
mock_reranker.compute_score.return_value = [0.3, 0.9, 0.6, 0.1, 0.8]

with patch("FlagEmbedding.FlagReranker", return_value=mock_reranker):
    sys.path.insert(0, "/app")
    from app.reranker_service import reranker_service
    reranker_service._model = mock_reranker

    from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


SAMPLE_DOCS = [
    {"document_id": f"doc_{i}", "text": f"Document text number {i}", "metadata": {"page": i}}
    for i in range(5)
]

SAMPLE_REQUEST = {
    "query": "What is the annual leave policy?",
    "documents": SAMPLE_DOCS,
    "top_n": 3,
}


class TestRerankEndpoint:
    def test_rerank_returns_sorted_results(self, client):
        """Results should be sorted by score descending."""
        response = client.post("/rerank", json=SAMPLE_REQUEST)
        assert response.status_code == 200

        results = response.json()["results"]
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), "Results must be sorted by score descending"

    def test_rerank_returns_top_n(self, client):
        """Should return exactly top_n results."""
        response = client.post("/rerank", json=SAMPLE_REQUEST)
        assert len(response.json()["results"]) == 3  # top_n=3

    def test_rerank_rank_field(self, client):
        """Rank should be 1-based and sequential."""
        response = client.post("/rerank", json=SAMPLE_REQUEST)
        ranks = [r["rank"] for r in response.json()["results"]]
        assert ranks == [1, 2, 3]

    def test_rerank_preserves_metadata(self, client):
        """Metadata from input documents should be preserved in output."""
        response = client.post("/rerank", json=SAMPLE_REQUEST)
        for result in response.json()["results"]:
            assert "page" in result["metadata"]

    def test_rerank_empty_documents_returns_422(self, client):
        """Empty documents list should fail validation."""
        response = client.post("/rerank", json={
            "query": "test", "documents": [], "top_n": 5
        })
        assert response.status_code == 422

    def test_health_endpoint(self, client):
        """Health check should return 200 with model_loaded=True."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["model_loaded"] is True

from fastapi.testclient import TestClient

from aegis.api.server import app


client = TestClient(app)


def test_comparison_dashboard_is_available():
    response = client.get(
        "/dashboard/compare.html"
    )

    assert response.status_code == 200
    assert "AEGIS RUN COMPARISON" in response.text
    assert "Select archived runs" in response.text
    assert "Comparison result" in response.text
    assert "Baseline run" in response.text
    assert "Candidate run" in response.text


def test_comparison_dashboard_uses_comparison_api():
    response = client.get(
        "/dashboard/compare.html"
    )

    assert response.status_code == 200

    assert "/runs?limit=500" in response.text
    assert "/run-comparisons?" in response.text
    assert "compareSelectedRuns" in response.text
    assert "renderComparison" in response.text
    assert "processing_metrics_available" in response.text


def test_comparison_dashboard_links_to_main_dashboard():
    response = client.get(
        "/dashboard/compare.html"
    )

    assert response.status_code == 200
    assert 'href="/dashboard/"' in response.text
    assert "Back to dashboard" in response.text

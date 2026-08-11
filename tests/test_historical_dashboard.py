from fastapi.testclient import TestClient

from aegis.api.server import app


client = TestClient(app)


def test_historical_dashboard_is_available():
    response = client.get(
        "/dashboard/history.html"
    )

    assert response.status_code == 200
    assert "AEGIS HISTORICAL WORLD MODEL" in response.text
    assert "Select an archived run" in response.text
    assert "Track statistics" in response.text
    assert "Evaluated tracks" in response.text
    assert "Track details" in response.text
    assert "/dashboard/history.css" in response.text
    assert "/dashboard/history.js" in response.text


def test_historical_dashboard_has_track_filters():
    response = client.get(
        "/dashboard/history.html"
    )

    assert response.status_code == 200
    assert 'id="quality-filter"' in response.text
    assert 'id="label-filter"' in response.text
    assert 'id="confidence-filter"' in response.text
    assert 'id="track-limit"' in response.text
    assert 'id="apply-filters-button"' in response.text
    assert 'id="track-table-body"' in response.text


def test_historical_dashboard_has_pagination_controls():
    response = client.get(
        "/dashboard/history.html"
    )

    assert response.status_code == 200
    assert 'id="previous-page-button"' in response.text
    assert 'id="next-page-button"' in response.text
    assert 'id="page-message"' in response.text
    assert "Previous page" in response.text
    assert "Next page" in response.text


def test_historical_dashboard_links_to_other_dashboards():
    response = client.get(
        "/dashboard/history.html"
    )

    assert response.status_code == 200
    assert 'href="/dashboard/"' in response.text
    assert 'href="/dashboard/compare.html"' in response.text
    assert "Latest dashboard" in response.text
    assert "Compare runs" in response.text


def test_historical_dashboard_stylesheet_is_available():
    response = client.get(
        "/dashboard/history.css"
    )

    assert response.status_code == 200
    assert response.headers[
        "content-type"
    ].startswith("text/css")
    assert ".summary-card" in response.text
    assert ".pagination" in response.text
    assert ".quality" in response.text
    assert ".stable" in response.text
    assert ".tentative" in response.text
    assert ".weak" in response.text


def test_historical_dashboard_uses_historical_api():
    response = client.get(
        "/dashboard/history.js"
    )

    assert response.status_code == 200

    assert response.headers[
        "content-type"
    ].startswith(
        (
            "text/javascript",
            "application/javascript",
        )
    )

    assert '"/runs?limit=500"' in response.text
    assert '"/statistics"' in response.text
    assert "`/tracks?" in response.text
    assert '"dominant_label"' in response.text
    assert "offset: currentOffset" in response.text
    assert "currentOffset" in response.text
    assert "has_previous" in response.text
    assert "has_next" in response.text
    assert "loadRuns" in response.text
    assert "loadSelectedRun" in response.text
    assert "loadTrackDetails" in response.text
    assert "renderStatistics" in response.text
    assert "renderTracks" in response.text

from fastapi.testclient import TestClient

from aegis.api.server import app


client = TestClient(app)


def test_dashboard_is_available():
    response = client.get(
        "/dashboard/",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "AEGIS SITUATIONAL AWARENESS" in response.text
    assert "Tracked-object world model" in response.text
    assert "/dashboard/dashboard.js" in response.text


def test_dashboard_javascript_is_available():
    response = client.get(
        "/dashboard/dashboard.js"
    )

    assert response.status_code == 200

    content_type = response.headers["content-type"]

    assert content_type.startswith(
        (
            "text/javascript",
            "application/javascript",
        )
    )

    assert "initializeDashboard" in response.text
    assert "refreshDashboard" in response.text

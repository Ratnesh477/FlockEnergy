from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "portal_base_url" in data


def test_auth_status_endpoint():
    response = client.get("/api/v1/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert "authenticated" in data
    assert "account_email" in data


def test_meters_list_endpoint():
    response = client.get("/api/v1/meters?page=1&page_size=5")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "total" in data
    assert "page" in data
    assert len(data["data"]) <= 5


def test_meter_detail_endpoint():
    # J100000 is known to exist
    response = client.get("/api/v1/meters/J100000")
    assert response.status_code == 200
    data = response.json()
    assert data["meter_id"] == "J100000"
    assert "serial_number" in data
    assert "make" in data
    assert "hierarchy" in data


def test_meter_detail_404():
    response = client.get("/api/v1/meters/NON_EXISTENT_METER_XYZ")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


def test_meter_consumption_endpoint():
    response = client.get("/api/v1/meters/J100000/consumption")
    assert response.status_code == 200
    data = response.json()
    assert data["meter_id"] == "J100000"
    assert "readings" in data
    assert "stats" in data
    assert data["stats"]["reading_count"] > 0
    assert "kwh_total_consumed" in data["stats"]


def test_transformers_endpoint():
    response = client.get("/api/v1/transformers?page=1&page_size=10")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert data["total"] == 40
    assert len(data["data"]) == 10


def test_hierarchy_tree_endpoint():
    response = client.get("/api/v1/hierarchy")
    assert response.status_code == 200
    tree = response.json()
    assert isinstance(tree, list)
    assert len(tree) > 0
    assert "children" in tree[0]


def test_analytics_summary_endpoint():
    response = client.get("/api/v1/analytics/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_meters"] == 403
    assert data["total_transformers"] == 40
    assert data["healed_hierarchy_anomalies"] == 22

import pytest
from app.indexer import haversine_distance_km, LocalDataStore


def test_haversine_distance():
    # Jaipur center: 26.9124, 75.7873
    # Malviya Nagar: 26.8524, 75.8052
    dist = haversine_distance_km(26.9124, 75.7873, 26.8524, 75.8052)
    assert 6.0 < dist < 8.0  # Approx 6.9 km


def test_datastore_query_filtering():
    store = LocalDataStore()
    
    store._raw_meters = [
        {
            "meterId": "J100000",
            "serialNo": "SE33962",
            "make": "HPL",
            "phaseType": "single",
            "installStatus": "Decommissioned",
            "dtCode": "DT-001",
            "build": "legacy",
            "geo": {"lat": 26.9389, "lng": 75.8309},
        },
        {
            "meterId": "J100001",
            "serialNo": "GE84132",
            "make": "L&T",
            "phaseType": "single",
            "installStatus": "Installed",
            "dtCode": "DT-002",
            "build": "legacy",
            "geo": {"lat": 26.8500, "lng": 75.7800},
        },
        {
            "meterId": "J100004",
            "serialNo": "SE65293",
            "make": "Genus",
            "phaseType": "three",
            "installStatus": "Faulty",
            "dtCode": "DT-005",
            "build": "v2",
            "geo": {"lat": 26.9074, "lng": 75.7250},
        }
    ]
    store._last_synced_at = 9999999999.0  # Fresh

    # 1. Filter by make
    res_make = store.query_meters(make="HPL")
    assert res_make.total == 1
    assert res_make.data[0].meter_id == "J100000"

    # 2. Filter by status
    res_status = store.query_meters(install_status="Faulty")
    assert res_status.total == 1
    assert res_status.data[0].meter_id == "J100004"

    # 3. Text search
    res_search = store.query_meters(q="GE84")
    assert res_search.total == 1
    assert res_search.data[0].meter_id == "J100001"

    # 4. Proximity search
    res_prox = store.query_meters(near_lat=26.9389, near_lng=75.8309, radius_km=2.0)
    assert res_prox.total == 1
    assert res_prox.data[0].meter_id == "J100000"

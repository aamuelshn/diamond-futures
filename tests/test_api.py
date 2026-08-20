from fastapi.testclient import TestClient
from index import app

client = TestClient(app)

def test_health():
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}

def test_root_loads():
    response = client.get('/')
    assert response.status_code == 200
    assert 'Diamond Futures' in response.text
    assert 'CURVE Engine' in response.text
    assert 'Streamlit' not in response.text

def test_demo_returns_home_runs():
    response = client.get('/api/demo')
    assert response.status_code == 200
    payload = response.json()
    assert len(payload['home_runs']) > 0
    assert 'launch_speed' in payload['home_runs'][0]


def test_demo_career_simulation_returns_probability_ranges():
    response = client.get('/api/demo-simulation?simulations=1000')
    assert response.status_code == 200
    payload = response.json()
    assert payload['role'] == 'hitter'
    assert payload['model']['simulations'] == 1000
    assert payload['summary']['career_home_runs']['p10'] <= payload['summary']['career_home_runs']['p50']
    assert payload['summary']['career_home_runs']['p50'] <= payload['summary']['career_home_runs']['p90']
    assert len(payload['comparables']) == 5
    assert len(payload['milestones']) >= 4

def test_home_page_identifies_the_flask_deployment(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Hello from deploy-test-flask" in response.data


def test_health_endpoint_reports_okay(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "app": "deploy-test-flask"}

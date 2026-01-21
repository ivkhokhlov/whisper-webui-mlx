from fastapi.testclient import TestClient

from mlx_ui.app import app

client = TestClient(app)


def test_root_ok() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Queue" in response.text
    assert "History" in response.text

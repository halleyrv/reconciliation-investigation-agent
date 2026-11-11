"""Problem Details for every error and the OpenAPI document (AC-2c.2, AC-2c.4)."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from recon.bootstrap.app import create_app
from tests.integration.api.conftest import assert_problem


def test_openapi_lists_every_endpoint_of_the_api_surface(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    surface = {
        "/imports": {"post"},
        "/imports/{id}": {"get"},
        "/reconciliation-runs": {"post"},
        "/reconciliation-runs/{id}": {"get"},
        "/discrepancies": {"get"},
    }
    assert {path: set(paths.get(path, ())) for path in surface} == surface


def test_an_unknown_path_is_a_404_problem(client: TestClient) -> None:
    assert_problem(client.get("/nowhere"), 404)


def test_an_unexpected_error_is_a_generic_500_without_details(engine: Engine) -> None:
    app = create_app(engine=engine)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret connection string postgresql://user:pw@host")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    body = assert_problem(response, 500)
    assert "secret" not in response.text
    assert "RuntimeError" not in response.text
    assert set(body) == {"type", "title", "status", "detail"}

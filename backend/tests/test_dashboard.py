"""The bundled web dashboard is served by the API app."""

from __future__ import annotations

from pathlib import Path

from arbiter.api import DASHBOARD_DIR, Auth, create_app
from arbiter.service import Arbiter
from starlette.testclient import TestClient

from .conftest import make_config


def test_dashboard_files_are_served(tmp_path: Path):
    app = create_app(Arbiter(make_config(tmp_path)), Auth("agent", "admin"), DASHBOARD_DIR)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "/static/app.js" in page.text
        for name, kind in (("app.js", "javascript"), ("app.css", "css"), ("favicon.svg", "svg")):
            res = client.get(f"/static/{name}")
            assert res.status_code == 200
            assert kind in res.headers["content-type"]


def test_dashboard_needs_no_token_but_api_does(tmp_path: Path):
    app = create_app(Arbiter(make_config(tmp_path)), Auth("agent", "admin"), DASHBOARD_DIR)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/state").status_code == 401
        assert client.get("/api/admin/audit", params={"token": "agent"}).status_code == 403
        assert client.get("/api/admin/audit", params={"token": "admin"}).status_code == 200

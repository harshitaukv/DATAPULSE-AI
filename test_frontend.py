"""Dashboard tests: every Streamlit page executes against the real API (in-process) without errors."""
import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
sys.path.insert(0, str(FRONTEND))

from streamlit.testing.v1 import AppTest  # noqa: E402

import api_client  # noqa: E402

PAGES = ["overview", "ingestion", "monitor", "quality", "incidents", "analyst", "recovery", "reports", "admin"]


@pytest.fixture(autouse=True)
def route_to_testclient(client, monkeypatch):
    def init(self, token=None, base_url="http://testserver"):
        self.base_url = base_url
        self.session = client
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        else:
            self.session.headers.pop("Authorization", None)
    monkeypatch.setattr(api_client.APIClient, "__init__", init)


def _page(name, login):
    at = AppTest.from_file(str(FRONTEND / "views" / f"{name}.py"), default_timeout=60)
    at.session_state["token"] = login["access_token"]
    at.session_state["user"] = login["user"]
    return at.run()


@pytest.fixture(scope="module")
def logins(client):
    return {u: client.post("/api/v1/auth/login", json={"username": u, "password": p}).json()
            for u, p in (("admin", "Admin-test-123"), ("engineer", "Engineer-test-123"))}


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_errors(page, logins, baseline):
    at = _page(page, logins["admin"])
    assert not at.exception, at.exception[0].value if at.exception else ""
    assert not at.error, at.error[0].value if at.error else ""


def test_run_pipeline_from_dashboard(logins, baseline):
    at = _page("ingestion", logins["engineer"])
    next(b for b in at.button if b.label == "Use").click()
    at.run()
    next(b for b in at.button if b.label == "Run pipeline").click()
    at.run()
    assert not at.exception
    assert at.session_state["last_run"]["status"] == "succeeded"
    assert any("dp-track" in m.value for m in at.markdown)


def test_login_screen_rejects_bad_password():
    at = AppTest.from_file(str(FRONTEND / "app.py"), default_timeout=60).run()
    at.text_input[0].input("admin")
    at.text_input[1].input("wrong-password-1")
    at.button[0].click()
    at.run()
    assert [e.value for e in at.error] == ["Incorrect username or password."]


def test_login_screen_has_no_page_navigation():
    """No pages/ directory may exist, otherwise Streamlit auto-lists pages before sign-in."""
    assert not (FRONTEND / "pages").exists()
    at = AppTest.from_file(str(FRONTEND / "app.py"), default_timeout=60).run()
    assert not at.sidebar.children or all(not getattr(c, "label", None) for c in at.sidebar.children.values())

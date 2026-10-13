"""HTTP client for the DataPulse AI backend.

The dashboard never processes data itself: every number it shows comes from
these API calls. The backend URL is configurable with API_BASE_URL.
"""
from __future__ import annotations

import os
from typing import Any

import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = float(os.getenv("API_TIMEOUT_SECONDS", "120"))


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class APIClient:
    def __init__(self, token: str | None = None, base_url: str = API_BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    # ------------------------------------------------------------------ core
    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            response = self.session.request(method, f"{self.base_url}{path}", timeout=TIMEOUT, **kwargs)
        except requests.ConnectionError:
            raise APIError(0, f"Cannot reach the backend at {self.base_url}. Start it with "
                              "`uvicorn app.main:app` from the backend folder, or check API_BASE_URL.")
        except requests.Timeout:
            raise APIError(0, "The backend took too long to respond. Try again, or use a smaller file.")
        if response.status_code >= 400:
            raise APIError(response.status_code, _error_message(response))
        return response

    def get(self, path: str, **params) -> Any:
        return self._request("GET", path, params={k: v for k, v in params.items() if v is not None}).json()

    def post(self, path: str, json: dict | None = None, **kwargs) -> Any:
        r = self._request("POST", path, json=json, **kwargs)
        return r.json() if r.content else None

    def patch(self, path: str, json: dict) -> Any:
        return self._request("PATCH", path, json=json).json()

    def delete(self, path: str) -> None:
        self._request("DELETE", path)

    def download(self, path: str, **params) -> bytes:
        return self._request("GET", path, params=params).content

    # ------------------------------------------------------------ endpoints
    def login(self, username: str, password: str) -> dict:
        return self.post("/api/v1/auth/login", {"username": username, "password": password})

    def upload(self, filename: str, content: bytes) -> dict:
        mime = "application/json" if filename.lower().endswith(".json") else "text/csv"
        return self.post("/api/v1/uploads", files={"file": (filename, content, mime)})

    def health(self) -> dict:
        return self._request("GET", "/health").json()


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"Request failed with HTTP {response.status_code}."
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(body, dict) and body.get("errors"):
        fields = "; ".join(f"{e['field'] or 'request'}: {e['message']}" for e in body["errors"][:4])
        return f"{detail} {fields}"
    if isinstance(detail, list):
        return "; ".join(str(d.get("msg", d)) for d in detail[:4])
    return str(detail or f"Request failed with HTTP {response.status_code}.")

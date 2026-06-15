"""HTTP client for the Kodi Bridge server. Uses only stdlib (urllib).

Supports a list of candidate base URLs (e.g. LAN mDNS + public Cloudflare Tunnel).
Sticky preference: once a base works, stay on it; on consecutive failures, rotate
to the next candidate. This minimizes per-request latency vs. round-trip probing.
"""

import json
import urllib.request
import urllib.error


_FAILS_BEFORE_ROTATE = 3


class AlfredClient:
    def __init__(self, bases, token, timeout=5):
        """bases: list of base URLs like ['http://Jacobs-Mac-mini.local:8765', 'https://kodi.example.com']"""
        if isinstance(bases, str):
            bases = [bases]
        if not bases:
            raise ValueError("AlfredClient requires at least one base URL")
        self._bases = [b.rstrip("/") for b in bases]
        self._token = token
        self._timeout = timeout
        self._active = 0
        self._fail_streak = 0

    def _current_base(self):
        return self._bases[self._active]

    def _rotate(self):
        if len(self._bases) > 1:
            self._active = (self._active + 1) % len(self._bases)
            self._fail_streak = 0

    def _request(self, method, path, data=None):
        url = self._current_base() + path
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", "Bearer " + self._token)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            resp = urllib.request.urlopen(req, timeout=self._timeout)
            payload = json.loads(resp.read().decode("utf-8"))
            self._fail_streak = 0
            return payload
        except Exception:
            self._fail_streak += 1
            if self._fail_streak >= _FAILS_BEFORE_ROTATE:
                self._rotate()
            raise

    def active_base(self):
        return self._current_base()

    def get_command(self):
        result = self._request("GET", "/kodi/queue")
        if result.get("command") is None:
            return None
        return result

    def post_status(self, status_dict):
        try:
            self._request("POST", "/kodi/status", status_dict)
            return True
        except Exception:
            return False

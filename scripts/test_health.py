#!/usr/bin/env python3
"""Integration test: Health check.

Usage:
    python scripts/test_health.py

Requires:
    - Server running on http://localhost:8000
"""

import httpx

BASE = "http://localhost:8000"


def test_health_check():
    """GET /health — expect 200 with status ok."""
    resp = httpx.get(f"{BASE}/health")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    print(f"  ✅ Health check: status={data['status']}, version={data['version']}")


def main():
    print("\n=== Health Check Test ===\n")
    test_health_check()
    print("\n✅ Health check passed!\n")


if __name__ == "__main__":
    main()

"""Guard the request-boundary commit contract in get_db_session().

Lives in its own module: sessions are idempotent per trading day, so it
needs the per-module DB truncate to start from a clean slate.
"""


class TestWritePersistence:
    """Guard the request-boundary commit contract in get_db_session().

    Repositories/services never commit; the session dependency must commit on
    clean exit or every API write silently rolls back. This asserts a write
    made in one request is visible from a subsequent, independent request.
    """

    def test_session_write_visible_across_requests(self, client, auth_headers):
        start = client.post("/sessions/start", headers=auth_headers)
        assert start.status_code == 200
        session_id = start.json()["session_id"]

        # New request → new DB session; the row must have been committed.
        active = client.get("/sessions/active", headers=auth_headers)
        assert active.status_code == 200
        assert active.json()["active"] is True
        assert active.json()["session_id"] == session_id

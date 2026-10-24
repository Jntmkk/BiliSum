"""Unit tests for MySQLSession reconnect behavior.

These do not require a reachable MySQL server: the session's connections are
replaced with fakes so we can assert that a dropped connection is re-established
via ``ping(reconnect=True)`` before the next statement runs.
"""

import threading
from unittest.mock import MagicMock

from video_sum_infra.db import MySQLSession


def _make_session() -> MySQLSession:
    """Build a MySQLSession without touching the network.

    The two internal connections are replaced with fakes so we can assert that
    a dropped connection is re-established via ``ping(reconnect=True)`` before
    the next statement runs.
    """
    session = MySQLSession.__new__(MySQLSession)
    session._pymysql = MagicMock()
    session._lock = threading.RLock()

    main_conn = MagicMock()
    query_conn = MagicMock()
    # A cursor that yields no rows; enough for execute() to run end to end.
    main_conn.cursor.return_value = MagicMock()
    query_conn.cursor.return_value = MagicMock()
    query_conn.cursor.return_value.fetchall.return_value = []

    session._connection = main_conn
    session._query_connection = query_conn
    return session


def test_dead_connection_is_reconnected_before_execute():
    # Simulate the wait_timeout scenario: the server has marked the pooled
    # connection dead, so the ping attempt fails. _ensure_live swallows that
    # and lets the statement proceed; the key point is that ping IS attempted
    # (so pymysql can reconnect) and the query still runs instead of 500-ing.
    session = _make_session()
    session._query_connection.ping.side_effect = Exception("server has gone away")

    session.execute("SELECT 1")

    # ping was attempted once; the swallowed failure did not stop the query.
    session._query_connection.ping.assert_called_once_with(reconnect=True)
    session._query_connection.cursor.return_value.execute.assert_called_once()


def test_cursor_pings_main_connection_before_use():
    session = _make_session()
    with session.cursor():
        pass
    session._connection.ping.assert_called_once_with(reconnect=True)


def test_execute_pings_query_connection_before_use():
    session = _make_session()
    session.execute("SELECT 1")
    session._query_connection.ping.assert_called_once_with(reconnect=True)


def test_ping_failure_does_not_raise_and_query_still_runs():
    # ping(reconnect=True) raising means the server is unreachable; _ensure_live
    # must swallow that and let the real error surface from the statement itself.
    session = _make_session()
    session._query_connection.ping.side_effect = Exception("server gone")

    class _Boom(Exception):
        pass

    session._query_connection.cursor.return_value.execute.side_effect = _Boom("dead conn")

    try:
        session.execute("SELECT 1")
    except _Boom:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected the statement error to propagate")
    session._query_connection.ping.assert_called_once_with(reconnect=True)

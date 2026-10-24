"""Database access layer with SQLite and MySQL dialect support.

All SQL in the codebase is written once in the SQLite dialect (``?``
placeholders). ``rewrite_sql`` translates statements for MySQL at execute
time, so repository code stays dialect-free. ``open_database`` picks the
session implementation from the ``database_url`` scheme.
"""

import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

DatabaseDialect = Literal["sqlite", "mysql"]

# Columns that participate in primary/unique/foreign keys or secondary
# indexes. MySQL cannot index TEXT columns without a prefix length, so these
# become VARCHAR(191) (191 * 4 bytes = 764 bytes, safely inside the 3072-byte
# InnoDB index limit even for composite keys). All current values fit:
# uuid hex is 32 chars, bilibili ids are short, local ids are 30 chars,
# ISO timestamps are ~32 chars.
_ID_COLUMNS = {
    "video_id",
    "folder_id",
    "collection_id",
    "bvid",
    "batch_id",
    "tag",
    "job_id",
    "task_id",
    "message_id",
    "conversation_id",
    "event_id",
    "chunk_id",
    "canonical_id",
    "parent_id",
    "assistant_message_id",
    "subscription_id",
    "detection_id",
    "mid",
    "read_at",
    "key",
}

# Large free-text / JSON payloads that must not be capped at TEXT's 64KB.
_LONGTEXT_COLUMNS = {"indexed_content"}


def sqlite_path_from_url(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    parsed = urlparse(database_url)
    if parsed.scheme == "sqlite":
        return Path(parsed.path.lstrip("/"))
    raise ValueError(f"Unsupported database url: {database_url}")


def connect_sqlite(database_url: str) -> sqlite3.Connection:
    path = sqlite_path_from_url(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def sqlite_cursor(connection: sqlite3.Connection):
    cursor = connection.cursor()
    try:
        yield cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def database_dialect_from_url(database_url: str) -> DatabaseDialect:
    scheme = urlparse(database_url).scheme
    if scheme == "sqlite":
        return "sqlite"
    if scheme in {"mysql", "mysql+pymysql", "mariadb"}:
        return "mysql"
    raise ValueError(f"Unsupported database url scheme: {database_url!r}")


def _rewrite_mysql_ddl(text: str) -> str:
    def column_type(match: re.Match[str]) -> str:
        open_quote, column, close_quote = match.group(1), match.group(2), match.group(3)
        quoted = f"{open_quote}{column}{close_quote}"
        if column in _LONGTEXT_COLUMNS or column.endswith("_json"):
            return f"{quoted} LONGTEXT"
        if column in _ID_COLUMNS:
            return f"{quoted} VARCHAR(191)"
        return match.group(0)

    # TEXT cannot be a primary key or index column in MySQL.
    text = re.sub(r"\b(`?)(\w+)(`?) TEXT\b", column_type, text)
    # SQLite INTEGER is 64-bit; MySQL INTEGER is only 32-bit. Bilibili av
    # ids (aid) already exceed 2^31, and epoch timestamps approach it, so
    # every INTEGER column becomes BIGINT to keep the SQLite range.
    text = re.sub(r"\bINTEGER\b", "BIGINT", text)
    # TEXT-family columns only accept expression defaults with parentheses
    # (MySQL 8.0.13+).
    text = re.sub(
        r"\b(TEXT|LONGTEXT|VARCHAR\(\d+\)) NOT NULL DEFAULT '([^']*)'",
        r"\1 NOT NULL DEFAULT ('\2')",
        text,
    )
    return text


def rewrite_sql(sql: str, dialect: DatabaseDialect) -> str:
    """Translate a SQLite-dialect statement for MySQL.

    The input is written with ``?`` placeholders; the MySQL output uses
    ``%s`` (PyMySQL paramstyle). Ordering of the transforms matters:
    structural rewrites run before placeholder conversion.
    """

    if dialect == "sqlite":
        return sql
    text = sql

    conflict_update = re.search(
        r"\bON CONFLICT\s*\([^)]*\)\s*DO UPDATE SET\b", text, re.IGNORECASE
    )
    if conflict_update is not None:
        body = text[conflict_update.end() :]
        # SQLite's excluded.col becomes MySQL VALUES(col); table qualifiers
        # are not allowed in ON DUPLICATE KEY UPDATE and get stripped.
        body = re.sub(r"\bexcluded\.(\w+)", r"VALUES(\1)", body)
        body = re.sub(
            r"\b("
            r"video_assets|video_folders|video_folder_memberships|"
            r"video_collections|video_collection_items|"
            r"video_collection_folder_memberships|video_collection_task_batches|"
            r"library_preferences|video_tags|knowledge_index|"
            r"knowledge_conversations|knowledge_messages|knowledge_jobs|"
            r"knowledge_job_items|tasks|task_results|task_events"
            r")\.(\w+)",
            r"\2",
            body,
        )
        text = text[: conflict_update.start()] + "ON DUPLICATE KEY UPDATE" + body
    else:
        text, replaced = re.subn(
            r"\s*ON CONFLICT\s*\([^)]*\)\s*DO NOTHING", "", text, flags=re.IGNORECASE
        )
        if replaced:
            text = re.sub(r"\bINSERT INTO\b", "INSERT IGNORE INTO", text, count=1)

    text = re.sub(r"\bINSERT OR IGNORE\b", "INSERT IGNORE", text)
    text = re.sub(r"\bUPDATE OR IGNORE\b", "UPDATE IGNORE", text)
    # MySQL has no IF NOT EXISTS for indexes; the duplicate-name error (1061)
    # is swallowed at execute time to keep initialize() idempotent.
    text = re.sub(r"\b(CREATE(?: UNIQUE)? INDEX) IF NOT EXISTS\b", r"\1", text, flags=re.IGNORECASE)
    # MySQL has no partial indexes; a full index on the same column still
    # serves the IS NULL queries (leftmost-prefix), so drop the WHERE tail.
    text = re.sub(
        r"\b(CREATE(?: UNIQUE)? INDEX\s+\w+\s+ON\s+\w+\([^)]*\))\s+WHERE\s+.+$",
        r"\1",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if "library_preferences" in text:
        # ``key`` is a reserved word in MySQL; quoting it is always legal.
        text = re.sub(r"(?<![\w'])key(?![\w'])", "`key`", text)
    text = re.sub(r"\bCOLLATE NOCASE\b", "", text)
    # Startup backfill: SQLite computes a duration in seconds via julianday.
    text = re.sub(
        r"\(julianday\((\w+)\)\s*-\s*julianday\((\w+)\)\)\s*\*\s*86400\.0",
        r"(TIMESTAMPDIFF(MICROSECOND, \2, \1) / 1000000.0)",
        text,
    )
    # SQLite's multi-argument scalar MAX maps to GREATEST in MySQL.
    text = re.sub(r"\bMAX\(0,", "GREATEST(0,", text)
    # Parameterized NULL-safe equality: SQLite ``IS ?`` vs MySQL ``<=> ?``.
    text = re.sub(r"\bIS \?", "<=> ?", text)
    if "CREATE TABLE" in text.upper():
        text = _rewrite_mysql_ddl(text)
    return text.replace("?", "%s")


class _Cursor:
    """Dialect cursor wrapper: rewrites SQL and delegates everything else."""

    def __init__(self, raw: Any, dialect: DatabaseDialect) -> None:
        self._raw = raw
        self._dialect = dialect

    def execute(self, sql: str, params: Any = ()) -> Any:
        rewritten = rewrite_sql(sql, self._dialect)
        try:
            self._raw.execute(rewritten, params)
        except Exception as exc:
            # MySQL lacks CREATE INDEX IF NOT EXISTS; a duplicate index name
            # (error 1061) is the equivalent success path for idempotent DDL.
            if self._dialect == "mysql" and getattr(exc, "args", None) and exc.args[0] == 1061:
                return self
            raise
        return self

    def executemany(self, sql: str, params: Any) -> Any:
        self._raw.executemany(rewrite_sql(sql, self._dialect), params)
        return self

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)


class DatabaseSession:
    """A dialect-aware database session.

    ``cursor()`` yields a transaction-scoped cursor (commit on success,
    rollback on error). ``execute()`` runs a single read outside the main
    transaction. Both return dict-style rows keyed by column name.
    """

    dialect: DatabaseDialect

    @contextmanager
    def cursor(self) -> Iterator[Any]:
        raise NotImplementedError

    def execute(self, sql: str, params: Any = ()) -> list[Any]:
        raise NotImplementedError

    def table_columns(self, table: str) -> set[str]:
        raise NotImplementedError

    def adjust_column_definition(self, table: str, column: str, definition: str) -> str:
        return definition

    def close(self) -> None:
        raise NotImplementedError


class SQLiteSession(DatabaseSession):
    dialect: DatabaseDialect = "sqlite"

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._lock = threading.RLock()

    @classmethod
    def from_url(cls, database_url: str) -> "SQLiteSession":
        return cls(connect_sqlite(database_url))

    @contextmanager
    def cursor(self) -> Iterator[Any]:
        with self._lock:
            with sqlite_cursor(self._connection) as cursor:
                yield _Cursor(cursor, self.dialect)

    def execute(self, sql: str, params: Any = ()) -> list[Any]:
        with self._lock:
            return self._connection.execute(sql, params).fetchall()

    def table_columns(self, table: str) -> set[str]:
        rows = self.execute(f"PRAGMA table_info({table})")
        return {str(row["name"]) for row in rows}

    def close(self) -> None:
        self._connection.close()


def _mysql_connect_options(url: str, database: str | None = None) -> dict[str, Any]:
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database if database is not None else unquote(parsed.path.lstrip("/")),
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": 10,
    }


def _ensure_mysql_database(url: str, pymysql_module: Any) -> None:
    """Create the target database if the server allows it.

    Startup auto-initializes the database (``CREATE DATABASE IF NOT EXISTS``
    with utf8mb4). Accounts without the CREATE privilege simply skip this
    step; connecting below then surfaces the real problem if the database
    truly does not exist.
    """

    database = unquote(urlparse(url).path.lstrip("/"))
    if not database:
        return
    if not re.fullmatch(r"[A-Za-z0-9_$]+", database):
        raise ValueError(f"Invalid MySQL database name in database_url: {database!r}")
    options = _mysql_connect_options(url, database="")
    connection = pymysql_module.connect(**options)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4")
        connection.commit()
    except Exception:
        pass
    finally:
        connection.close()


class MySQLSession(DatabaseSession):
    dialect: DatabaseDialect = "mysql"

    def __init__(self, url: str) -> None:
        try:
            import pymysql
            import pymysql.cursors
        except ImportError as exc:
            raise RuntimeError(
                "MySQL database_url requires PyMySQL. "
                "Install it with: uv sync (or pip install pymysql)"
            ) from exc
        self._pymysql = pymysql
        _ensure_mysql_database(url, pymysql)
        options = _mysql_connect_options(url)
        options["cursorclass"] = pymysql.cursors.DictCursor
        self._connection = pymysql.connect(**options)
        # Dedicated connection for auxiliary reads so helper queries never
        # interleave with the main transaction's statement stream.
        self._query_connection = pymysql.connect(**options)
        self._lock = threading.RLock()

    def _ensure_live(self, connection: Any) -> None:
        """Reconnect a connection the server has dropped (e.g. wait_timeout).

        pymysql's ping(reconnect=True) transparently re-establishes the
        connection when it is no longer usable, so a long-idle process does
        not fail every subsequent query with a stale handle.
        """
        try:
            connection.ping(reconnect=True)
        except Exception:
            # ping raised (server unreachable): surface the original error to
            # the caller instead of masking it with a reconnect failure.
            pass

    @contextmanager
    def cursor(self) -> Iterator[Any]:
        with self._lock:
            self._ensure_live(self._connection)
            raw = self._connection.cursor()
            try:
                yield _Cursor(raw, self.dialect)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            finally:
                raw.close()

    def execute(self, sql: str, params: Any = ()) -> list[Any]:
        with self._lock:
            self._ensure_live(self._query_connection)
            raw = self._query_connection.cursor()
            try:
                raw.execute(rewrite_sql(sql, self.dialect), params)
                rows = raw.fetchall()
                # autocommit is off, so even a plain SELECT opens a
                # transaction whose metadata locks persist until commit;
                # an uncommitted read can block CREATE DATABASE / DDL on
                # the same schema from other sessions forever.
                self._query_connection.commit()
                return rows
            finally:
                raw.close()

    def table_columns(self, table: str) -> set[str]:
        rows = self.execute(
            """
            SELECT COLUMN_NAME AS name
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?
            """,
            (table,),
        )
        return {str(row["name"]) for row in rows}

    def adjust_column_definition(self, table: str, column: str, definition: str) -> str:
        adjusted = definition
        if column in _LONGTEXT_COLUMNS or column.endswith("_json"):
            adjusted = adjusted.replace("TEXT", "LONGTEXT", 1)
        elif column in _ID_COLUMNS and adjusted.startswith("TEXT"):
            adjusted = "VARCHAR(191)" + adjusted[len("TEXT") :]
        return re.sub(
            r"\b(TEXT|LONGTEXT|VARCHAR\(\d+\)) NOT NULL DEFAULT '([^']*)'",
            r"\1 NOT NULL DEFAULT ('\2')",
            adjusted,
        )

    def close(self) -> None:
        self._connection.close()
        self._query_connection.close()


def open_database(database_url: str) -> DatabaseSession:
    dialect = database_dialect_from_url(database_url)
    if dialect == "sqlite":
        return SQLiteSession.from_url(database_url)
    return MySQLSession(database_url)

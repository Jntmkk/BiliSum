import tokenize
from io import BytesIO
from pathlib import Path

from video_sum_infra.db import rewrite_sql

REPOSITORY_PATH = (
    Path(__file__).resolve().parents[2]
    / "apps/service/src/video_sum_service/repository.py"
)

_SQL_KEYWORDS = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "CREATE",
    "PRAGMA",
    "ALTER",
    "REPLACE",
)


def _sql_string_literals() -> list[str]:
    source = REPOSITORY_PATH.read_bytes()
    literals: list[str] = []
    for token in tokenize.tokenize(BytesIO(source).readline):
        if token.type == tokenize.STRING:
            text = token.string
            upper = text.upper()
            if any(keyword in upper for keyword in _SQL_KEYWORDS):
                for quote in ('"""', '"', "'"):
                    if text.startswith(quote) and text.endswith(quote):
                        text = text[len(quote) : -len(quote)]
                        break
                literals.append(text)
    return literals


def _repository_statements() -> list[str]:
    """Every SQL string literal in repository.py, with f-string placeholders stripped."""
    return [
        statement.replace("{columns}", "c").replace("{prefix}", "v")
        for statement in _sql_string_literals()
    ]


def test_sqlite_is_identity() -> None:
    sql = "SELECT * FROM video_assets WHERE video_id = ? AND title LIKE ?"
    assert rewrite_sql(sql, "sqlite") == sql


def test_insert_or_ignore_select() -> None:
    sql = """
    INSERT OR IGNORE INTO video_folder_memberships (video_id, folder_id)
    SELECT video_id, folder_id FROM video_assets WHERE folder_id IS NOT NULL
    """
    assert rewrite_sql(sql, "mysql").strip() == (
        "INSERT IGNORE INTO video_folder_memberships (video_id, folder_id)\n"
        "    SELECT video_id, folder_id FROM video_assets WHERE folder_id IS NOT NULL"
    )


def test_update_or_ignore() -> None:
    assert rewrite_sql(
        "UPDATE OR IGNORE video_folder_memberships SET video_id = ? WHERE video_id = ?",
        "mysql",
    ) == "UPDATE IGNORE video_folder_memberships SET video_id = %s WHERE video_id = %s"


def test_on_conflict_do_nothing() -> None:
    sql = """
    INSERT INTO video_folder_memberships (video_id, folder_id, folder_order)
    VALUES (?, ?, ?)
    ON CONFLICT(video_id, folder_id) DO NOTHING
    """
    rewritten = rewrite_sql(sql, "mysql")
    assert rewritten.strip().startswith("INSERT IGNORE INTO video_folder_memberships")
    assert "ON CONFLICT" not in rewritten


def test_on_conflict_do_update_excluded_and_qualifiers() -> None:
    sql = """
    INSERT INTO video_collections (collection_id, title, owner_mid, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(collection_id) DO UPDATE SET
        title = excluded.title,
        owner_mid = COALESCE(excluded.owner_mid, video_collections.owner_mid),
        updated_at = excluded.updated_at
    """
    assert rewrite_sql(sql, "mysql").strip() == (
        "INSERT INTO video_collections (collection_id, title, owner_mid, created_at, updated_at)\n"
        "    VALUES (%s, %s, %s, %s, %s)\n"
        "    ON DUPLICATE KEY UPDATE\n"
        "        title = VALUES(title),\n"
        "        owner_mid = COALESCE(VALUES(owner_mid), owner_mid),\n"
        "        updated_at = VALUES(updated_at)"
    )


def test_on_conflict_case_body() -> None:
    sql = """
    INSERT INTO video_tags (video_id, tag, source, confidence, created_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(video_id, tag) DO UPDATE SET
        source = CASE WHEN excluded.source = 'manual' THEN 'manual' ELSE video_tags.source END
    """
    rewritten = rewrite_sql(sql, "mysql")
    assert "ON DUPLICATE KEY UPDATE" in rewritten
    assert "VALUES(source)" in rewritten
    assert "video_tags.source" not in rewritten


def test_library_preferences_key_quoting() -> None:
    ddl = (
        "CREATE TABLE IF NOT EXISTS library_preferences (\n"
        "                    key TEXT PRIMARY KEY,\n"
        "                    value TEXT NOT NULL\n"
        "                )"
    )
    rewritten = rewrite_sql(ddl, "mysql")
    assert "`key` VARCHAR(191) PRIMARY KEY" in rewritten


def test_library_preferences_key_quoting_in_dml() -> None:
    sql = "SELECT value FROM library_preferences WHERE key = ?"
    assert rewrite_sql(sql, "mysql") == "SELECT value FROM library_preferences WHERE `key` = %s"


def test_collate_nocase_removed() -> None:
    sql = "SELECT tag FROM video_tags ORDER BY tag COLLATE NOCASE ASC"
    assert rewrite_sql(sql, "mysql") == "SELECT tag FROM video_tags ORDER BY tag  ASC"


def test_julianday_backfill() -> None:
    sql = "SELECT MAX(0, (julianday(updated_at) - julianday(created_at)) * 86400.0) FROM tasks"
    assert rewrite_sql(sql, "mysql") == (
        "SELECT GREATEST(0, (TIMESTAMPDIFF(MICROSECOND, created_at, updated_at)"
        " / 1000000.0)) FROM tasks"
    )


def test_null_safe_equality() -> None:
    sql = "SELECT MIN(position) AS min_position FROM video_folders WHERE parent_id IS ?"
    assert rewrite_sql(sql, "mysql") == (
        "SELECT MIN(position) AS min_position FROM video_folders WHERE parent_id <=> %s"
    )


def test_create_index_if_not_exists() -> None:
    sql = (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_messages_sequence "
        "ON knowledge_messages(conversation_id, sequence)"
    )
    assert rewrite_sql(sql, "mysql") == (
        "CREATE UNIQUE INDEX idx_knowledge_messages_sequence "
        "ON knowledge_messages(conversation_id, sequence)"
    )


def test_partial_index_where_tail_dropped() -> None:
    sql = "CREATE INDEX idx_up_detected_unread ON up_detected_videos(read_at) WHERE read_at IS NULL"
    assert rewrite_sql(sql, "mysql") == (
        "CREATE INDEX idx_up_detected_unread ON up_detected_videos(read_at)"
    )


def test_up_tables_ddl_type_mapping() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS up_subscriptions (
        subscription_id TEXT PRIMARY KEY,
        mid TEXT NOT NULL,
        up_name TEXT NOT NULL DEFAULT ''
    )
    """
    rewritten = rewrite_sql(ddl, "mysql")
    assert "subscription_id VARCHAR(191) PRIMARY KEY" in rewritten
    assert "mid VARCHAR(191) NOT NULL" in rewritten
    assert "up_name TEXT NOT NULL DEFAULT ('')" in rewritten


def test_integer_maps_to_bigint() -> None:
    """SQLite INTEGER is 64-bit; MySQL INTEGER is 32-bit (bilibili aid overflows it)."""
    ddl = "CREATE TABLE IF NOT EXISTS t (aid INTEGER, seq INTEGER NOT NULL DEFAULT 0)"
    rewritten = rewrite_sql(ddl, "mysql")
    assert "(aid BIGINT, seq BIGINT NOT NULL DEFAULT 0)" in rewritten


def test_ddl_type_mapping() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS video_assets (
        video_id TEXT PRIMARY KEY,
        canonical_id TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        duration REAL,
        page_catalog_json TEXT NOT NULL DEFAULT '[]',
        is_favorite INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """
    rewritten = rewrite_sql(ddl, "mysql")
    assert "video_id VARCHAR(191) PRIMARY KEY" in rewritten
    assert "canonical_id VARCHAR(191) NOT NULL UNIQUE" in rewritten
    assert "page_catalog_json LONGTEXT NOT NULL DEFAULT ('[]')" in rewritten
    assert "is_favorite BIGINT NOT NULL DEFAULT 0" in rewritten
    assert "title TEXT NOT NULL" in rewritten


def test_ddl_composite_primary_key_and_longtext() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS knowledge_index (
        chunk_id TEXT PRIMARY KEY,
        video_id TEXT NOT NULL DEFAULT '',
        embedding_json TEXT NOT NULL,
        indexed_content TEXT NOT NULL DEFAULT '',
        segment_order INTEGER,
        PRIMARY KEY (video_id, tag)
    )
    """
    rewritten = rewrite_sql(ddl, "mysql")
    assert "chunk_id VARCHAR(191) PRIMARY KEY" in rewritten
    assert "video_id VARCHAR(191) NOT NULL DEFAULT ('')" in rewritten
    assert "embedding_json LONGTEXT NOT NULL" in rewritten
    assert "indexed_content LONGTEXT NOT NULL DEFAULT ('')" in rewritten


def test_all_repository_statements_translate_cleanly() -> None:
    """Guard: no SQL literal in repository.py may retain SQLite-only tokens."""
    leftovers = (
        "?",
        "OR IGNORE",
        "ON CONFLICT",
        "excluded.",
        "COLLATE NOCASE",
        "julianday",
        "PRAGMA",
    )
    statements = _repository_statements()
    assert len(statements) >= 100
    for statement in statements:
        rewritten = rewrite_sql(statement, "mysql")
        for token in leftovers:
            assert token not in rewritten, f"{token!r} survived in: {statement[:120]!r}"

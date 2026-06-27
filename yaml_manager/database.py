"""Read-only Home Assistant recorder database analysis."""

from __future__ import annotations

import re
import sqlite3
import time
import urllib.parse
from http import HTTPStatus
from pathlib import Path
from typing import Any

try:
    from .errors import ApiError
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError


DB_NAME = "home-assistant_v2.db"
BAD_STATES = {"unknown", "unavailable"}
MAX_SQL_LENGTH = 5_000
MAX_SQL_ROWS = 200
MAX_SQL_COLUMNS = 50
QUERY_TIMEOUT_SECONDS = 1.5


def _database_path(backend: Any) -> Path:
    return (backend.PACKAGES_ROOT.parent / DB_NAME).resolve()


def _wal_path(path: Path) -> Path:
    return Path(f"{path}-wal")


def _available(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "available": False,
            "message": f"Recorder-Datenbank wurde nicht gefunden: {path}",
            "path": str(path),
        }
    return {"available": True, "message": "", "path": str(path)}


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, f"Recorder-Datenbank wurde nicht gefunden: {path}")
    uri = f"file:{urllib.parse.quote(str(path))}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=250")
    connection.execute("PRAGMA temp_store=MEMORY")
    return connection


def _fetch_all(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _fetch_value(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return connection.execute(sql, params).fetchone()[0]


def _tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        return set()
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _has_table(connection: sqlite3.Connection, table: str) -> bool:
    return table in _tables(connection)


def _state_entity_expression(connection: sqlite3.Connection) -> tuple[str, str]:
    state_columns = _table_columns(connection, "states")
    if "metadata_id" in state_columns and _has_table(connection, "states_meta"):
        return "states_meta.entity_id", "LEFT JOIN states_meta ON states_meta.metadata_id = states.metadata_id"
    if "entity_id" in state_columns:
        return "states.entity_id", ""
    return "NULL", ""


def _state_time_expression(connection: sqlite3.Connection, alias: str = "states") -> str:
    columns = _table_columns(connection, "states")
    if "last_changed_ts" in columns:
        return f"{alias}.last_changed_ts"
    if "last_updated_ts" in columns:
        return f"{alias}.last_updated_ts"
    if "last_changed" in columns:
        return f"strftime('%s', {alias}.last_changed)"
    if "last_updated" in columns:
        return f"strftime('%s', {alias}.last_updated)"
    return "NULL"


def _state_attribute_join(connection: sqlite3.Connection) -> tuple[str, str]:
    state_columns = _table_columns(connection, "states")
    attribute_columns = _table_columns(connection, "state_attributes")
    if (
        "attributes_id" in state_columns
        and _has_table(connection, "state_attributes")
        and "shared_attrs" in attribute_columns
    ):
        return (
            "LEFT JOIN state_attributes ON state_attributes.attributes_id = states.attributes_id",
            "LENGTH(COALESCE(state_attributes.shared_attrs, ''))",
        )
    if "attributes" in state_columns:
        return "", "LENGTH(COALESCE(states.attributes, ''))"
    return "", "0"


def _timestamp(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(numeric))
    except (OverflowError, OSError, ValueError):
        return str(value)


def _table_counts(connection: sqlite3.Connection, names: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for table in names:
        try:
            rows = int(_fetch_value(connection, f'SELECT COUNT(*) FROM "{table}"'))
        except sqlite3.Error:
            rows = 0
        result.append({"name": table, "rows": rows})
    return sorted(result, key=lambda item: item["rows"], reverse=True)


def _largest_tables(connection: sqlite3.Connection, names: list[str]) -> list[dict[str, Any]]:
    try:
        dbstat = _fetch_all(
            connection,
            "SELECT name, SUM(pgsize) AS bytes FROM dbstat "
            "WHERE name NOT LIKE 'sqlite_%' GROUP BY name ORDER BY bytes DESC LIMIT 20",
        )
        return [{"name": row["name"], "bytes": int(row["bytes"] or 0)} for row in dbstat]
    except sqlite3.Error:
        return _table_counts(connection, names)[:20]


def database_health(backend: Any) -> dict[str, Any]:
    path = _database_path(backend)
    status = _available(path)
    if not status["available"]:
        return {
            **status,
            "summary": {"tables": 0, "rows": 0, "dbSize": 0, "walSize": 0},
            "tables": [],
            "largestTables": [],
        }

    wal = _wal_path(path)
    try:
        db_size = path.stat().st_size
    except OSError:
        db_size = 0
    try:
        wal_size = wal.stat().st_size if wal.exists() else 0
    except OSError:
        wal_size = 0

    with _connect(path) as connection:
        names = _tables(connection)
        tables = _table_counts(connection, names)
        total_rows = sum(item["rows"] for item in tables)
        quick_check = "nicht verfügbar"
        try:
            quick_check = str(_fetch_value(connection, "PRAGMA quick_check"))
        except sqlite3.Error as exc:
            quick_check = str(exc).split("\n", 1)[0]

        oldest_state = ""
        newest_state = ""
        if "states" in names:
            time_expression = _state_time_expression(connection)
            try:
                row = connection.execute(
                    f"SELECT MIN({time_expression}) AS oldest, MAX({time_expression}) AS newest FROM states"
                ).fetchone()
                oldest_state = _timestamp(row["oldest"])
                newest_state = _timestamp(row["newest"])
            except sqlite3.Error:
                pass

        return {
            **status,
            "quickCheck": quick_check,
            "database": {
                "path": str(path),
                "walPath": str(wal),
                "size": db_size,
                "walSize": wal_size,
                "modified": _timestamp(path.stat().st_mtime),
            },
            "summary": {
                "tables": len(names),
                "rows": total_rows,
                "dbSize": db_size,
                "walSize": wal_size,
                "oldestState": oldest_state,
                "newestState": newest_state,
                "quickCheckOk": quick_check.casefold() == "ok",
            },
            "tables": tables,
            "largestTables": _largest_tables(connection, names),
        }


def _entity_rows(connection: sqlite3.Connection, limit: int = 300) -> list[dict[str, Any]]:
    if "states" not in _tables(connection):
        return []
    entity_expression, metadata_join = _state_entity_expression(connection)
    time_expression = _state_time_expression(connection)
    attribute_join, attribute_expression = _state_attribute_join(connection)
    try:
        rows = _fetch_all(
            connection,
            f"""
            SELECT
              {entity_expression} AS entity_id,
              COUNT(*) AS changes,
              MIN({time_expression}) AS first_seen,
              MAX({time_expression}) AS last_seen,
              SUM(CASE WHEN LOWER(COALESCE(states.state, '')) IN ('unknown', 'unavailable') THEN 1 ELSE 0 END) AS bad_states,
              SUM({attribute_expression}) AS attribute_bytes
            FROM states
            {metadata_join}
            {attribute_join}
            WHERE {entity_expression} IS NOT NULL AND {entity_expression} != ''
            GROUP BY {entity_expression}
            ORDER BY changes DESC
            LIMIT ?
            """,
            (limit,),
        )
    except sqlite3.Error:
        return []
    result = []
    for row in rows:
        result.append(
            {
                "entityId": row["entity_id"],
                "changes": int(row["changes"] or 0),
                "firstSeen": _timestamp(row["first_seen"]),
                "lastSeen": _timestamp(row["last_seen"]),
                "badStates": int(row["bad_states"] or 0),
                "attributeBytes": int(row["attribute_bytes"] or 0),
            }
        )
    return result


def _last_state_rows(connection: sqlite3.Connection, limit: int = 300) -> list[dict[str, Any]]:
    if "states" not in _tables(connection):
        return []
    entity_expression, metadata_join = _state_entity_expression(connection)
    time_expression = _state_time_expression(connection)
    try:
        rows = _fetch_all(
            connection,
            f"""
            WITH latest AS (
              SELECT
                {entity_expression} AS entity_id,
                states.state AS state,
                {time_expression} AS changed,
                ROW_NUMBER() OVER (
                  PARTITION BY {entity_expression}
                  ORDER BY {time_expression} DESC, states.rowid DESC
                ) AS position
              FROM states
              {metadata_join}
              WHERE {entity_expression} IS NOT NULL AND {entity_expression} != ''
            )
            SELECT entity_id, state, changed
            FROM latest
            WHERE position = 1
            ORDER BY changed DESC
            LIMIT ?
            """,
            (limit,),
        )
    except sqlite3.Error:
        return []
    return [
        {
            "entityId": row["entity_id"],
            "state": row["state"],
            "lastSeen": _timestamp(row["changed"]),
        }
        for row in rows
    ]


def database_entities(backend: Any) -> dict[str, Any]:
    path = _database_path(backend)
    status = _available(path)
    if not status["available"]:
        return {**status, "summary": {}, "noisy": [], "attributeHeavy": [], "badStateEntities": []}

    with _connect(path) as connection:
        entities = _entity_rows(connection)
        last_states = _last_state_rows(connection)
    entity_by_id = {item["entityId"]: item for item in entities}
    for state in last_states:
        if state["entityId"] in entity_by_id:
            entity_by_id[state["entityId"]]["lastState"] = state["state"]
    bad = [
        item for item in entity_by_id.values()
        if item.get("lastState", "").casefold() in BAD_STATES or item["badStates"] == item["changes"]
    ]
    return {
        **status,
        "summary": {
            "entities": len(entities),
            "changes": sum(item["changes"] for item in entities),
            "badStateEntities": len(bad),
            "attributeBytes": sum(item["attributeBytes"] for item in entities),
        },
        "noisy": sorted(entities, key=lambda item: item["changes"], reverse=True)[:100],
        "attributeHeavy": sorted(entities, key=lambda item: item["attributeBytes"], reverse=True)[:100],
        "badStateEntities": sorted(bad, key=lambda item: (item.get("lastState") not in BAD_STATES, item["entityId"]))[:100],
    }


def _database_entity_ids(connection: sqlite3.Connection) -> set[str]:
    if "states" not in _tables(connection):
        return set()
    entity_expression, metadata_join = _state_entity_expression(connection)
    try:
        rows = connection.execute(
            f"""
            SELECT DISTINCT {entity_expression} AS entity_id
            FROM states
            {metadata_join}
            WHERE {entity_expression} IS NOT NULL AND {entity_expression} != ''
            """
        ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row["entity_id"]) for row in rows if row["entity_id"]}


def database_yaml_compare(backend: Any) -> dict[str, Any]:
    path = _database_path(backend)
    status = _available(path)
    objects = backend.home_assistant_objects()
    references = [
        item for item in objects.get("references", [])
        if item.get("type") == "entity" and isinstance(item.get("target"), str)
    ]
    usage: dict[str, list[dict[str, Any]]] = {}
    for reference in references:
        usage.setdefault(reference["target"], []).append(
            {
                "source": reference.get("sourceObject") or reference.get("source"),
                "path": reference.get("path"),
                "line": reference.get("line"),
            }
        )
    yaml_entities = set(usage)
    if not status["available"]:
        return {
            **status,
            "summary": {
                "yamlEntities": len(yaml_entities),
                "databaseEntities": 0,
                "yamlMissingInDatabase": len(yaml_entities),
                "databaseOnly": 0,
                "badStateEntities": 0,
            },
            "yamlMissingInDatabase": [
                {"entityId": entity_id, "uses": usage[entity_id], "count": len(usage[entity_id])}
                for entity_id in sorted(yaml_entities, key=str.casefold)[:200]
            ],
            "databaseOnly": [],
            "badStateEntities": [],
        }

    with _connect(path) as connection:
        db_entities = _database_entity_ids(connection)
    entity_details = database_entities(backend)
    bad = entity_details.get("badStateEntities", [])
    missing = sorted(yaml_entities - db_entities, key=str.casefold)
    database_only = sorted(db_entities - yaml_entities, key=str.casefold)
    return {
        **status,
        "summary": {
            "yamlEntities": len(yaml_entities),
            "databaseEntities": len(db_entities),
            "yamlMissingInDatabase": len(missing),
            "databaseOnly": len(database_only),
            "badStateEntities": len(bad),
        },
        "yamlMissingInDatabase": [
            {"entityId": entity_id, "uses": usage[entity_id], "count": len(usage[entity_id])}
            for entity_id in missing[:200]
        ],
        "databaseOnly": [{"entityId": entity_id} for entity_id in database_only[:200]],
        "badStateEntities": bad[:100],
    }


def _statistics_time_expression(connection: sqlite3.Connection, table: str, alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    columns = _table_columns(connection, table)
    if "start_ts" in columns:
        return f"{prefix}start_ts"
    if "created_ts" in columns:
        return f"{prefix}created_ts"
    if "start" in columns:
        return f"strftime('%s', {prefix}start)"
    if "created" in columns:
        return f"strftime('%s', {prefix}created)"
    return "NULL"


def _metadata_join(connection: sqlite3.Connection, table: str) -> str:
    columns = _table_columns(connection, table)
    meta_columns = _table_columns(connection, "statistics_meta")
    if "metadata_id" in columns and "metadata_id" in meta_columns:
        return "LEFT JOIN statistics_meta ON statistics_meta.metadata_id = source.metadata_id"
    if "statistic_id" in columns and "statistic_id" in meta_columns:
        return "LEFT JOIN statistics_meta ON statistics_meta.statistic_id = source.statistic_id"
    return ""


def _statistics_summary(connection: sqlite3.Connection, table: str) -> dict[str, Any]:
    if not _has_table(connection, table):
        return {"table": table, "available": False, "rows": 0}
    time_expression = _statistics_time_expression(connection, table, "source")
    try:
        row = connection.execute(
            f"SELECT COUNT(*) AS rows, MIN({time_expression}) AS oldest, MAX({time_expression}) AS newest FROM {table} AS source"
        ).fetchone()
    except sqlite3.Error:
        return {"table": table, "available": True, "rows": 0}
    return {
        "table": table,
        "available": True,
        "rows": int(row["rows"] or 0),
        "oldest": _timestamp(row["oldest"]),
        "newest": _timestamp(row["newest"]),
    }


def _statistics_gaps(connection: sqlite3.Connection, table: str, expected_seconds: int) -> list[dict[str, Any]]:
    if not _has_table(connection, table):
        return []
    columns = _table_columns(connection, table)
    if "metadata_id" not in columns:
        return []
    time_expression = _statistics_time_expression(connection, table)
    join = _metadata_join(connection, table)
    try:
        rows = _fetch_all(
            connection,
            f"""
            WITH ordered AS (
              SELECT
                metadata_id,
                {time_expression} AS current_ts,
                LAG({time_expression}) OVER (PARTITION BY metadata_id ORDER BY {time_expression}) AS previous_ts
              FROM {table}
              WHERE {time_expression} IS NOT NULL
            ),
            gaps AS (
              SELECT
                metadata_id,
                COUNT(CASE WHEN previous_ts IS NOT NULL AND current_ts - previous_ts > ? THEN 1 END) AS gap_count,
                MAX(current_ts - previous_ts) AS max_gap
              FROM ordered
              GROUP BY metadata_id
            )
            SELECT
              COALESCE(statistics_meta.statistic_id, 'metadata_id:' || source.metadata_id) AS statistic_id,
              source.gap_count,
              source.max_gap
            FROM gaps AS source
            {join}
            WHERE source.gap_count > 0
            ORDER BY source.gap_count DESC, source.max_gap DESC
            LIMIT 50
            """,
            (expected_seconds,),
        )
    except sqlite3.Error:
        return []
    return [
        {
            "table": table,
            "statisticId": row["statistic_id"],
            "gaps": int(row["gap_count"] or 0),
            "maxGapSeconds": int(row["max_gap"] or 0),
        }
        for row in rows
    ]


def _statistics_jumps(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _has_table(connection, table):
        return []
    columns = _table_columns(connection, table)
    value_column = next((column for column in ("state", "sum", "mean") if column in columns), "")
    if not value_column or "metadata_id" not in columns:
        return []
    time_expression = _statistics_time_expression(connection, table)
    join = _metadata_join(connection, table)
    try:
        rows = _fetch_all(
            connection,
            f"""
            WITH ordered AS (
              SELECT
                metadata_id,
                CAST({value_column} AS REAL) AS value,
                LAG(CAST({value_column} AS REAL)) OVER (PARTITION BY metadata_id ORDER BY {time_expression}) AS previous_value
              FROM {table}
              WHERE {value_column} IS NOT NULL AND {time_expression} IS NOT NULL
            ),
            jumps AS (
              SELECT metadata_id, MAX(ABS(value - previous_value)) AS max_delta
              FROM ordered
              WHERE previous_value IS NOT NULL
              GROUP BY metadata_id
            )
            SELECT
              COALESCE(statistics_meta.statistic_id, 'metadata_id:' || source.metadata_id) AS statistic_id,
              source.max_delta
            FROM jumps AS source
            {join}
            WHERE source.max_delta IS NOT NULL
            ORDER BY source.max_delta DESC
            LIMIT 50
            """,
        )
    except sqlite3.Error:
        return []
    return [
        {"table": table, "statisticId": row["statistic_id"], "maxDelta": row["max_delta"]}
        for row in rows
    ]


def _statistics_meta_issues(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    if not _has_table(connection, "statistics_meta"):
        return {"unitChanges": [], "stateClassWarnings": []}
    columns = _table_columns(connection, "statistics_meta")
    unit_column = "unit_of_measurement" if "unit_of_measurement" in columns else ""
    unit_changes: list[dict[str, Any]] = []
    if unit_column and "statistic_id" in columns:
        try:
            unit_changes = _fetch_all(
                connection,
                f"""
                SELECT statistic_id, COUNT(DISTINCT COALESCE({unit_column}, '')) AS units
                FROM statistics_meta
                GROUP BY statistic_id
                HAVING units > 1
                ORDER BY units DESC, statistic_id
                LIMIT 50
                """,
            )
        except sqlite3.Error:
            unit_changes = []
    warnings: list[dict[str, Any]] = []
    if {"statistic_id", "has_mean", "has_sum"}.issubset(columns):
        try:
            warnings = _fetch_all(
                connection,
                """
                SELECT statistic_id, has_mean, has_sum
                FROM statistics_meta
                WHERE COALESCE(has_mean, 0) = 0 AND COALESCE(has_sum, 0) = 0
                ORDER BY statistic_id
                LIMIT 100
                """,
            )
        except sqlite3.Error:
            warnings = []
    return {"unitChanges": unit_changes, "stateClassWarnings": warnings}


def database_statistics(backend: Any) -> dict[str, Any]:
    path = _database_path(backend)
    status = _available(path)
    if not status["available"]:
        return {**status, "summary": {}, "tables": [], "gaps": [], "jumps": [], "unitChanges": [], "stateClassWarnings": []}
    with _connect(path) as connection:
        summaries = [
            _statistics_summary(connection, "statistics"),
            _statistics_summary(connection, "statistics_short_term"),
        ]
        gaps = [
            *_statistics_gaps(connection, "statistics", 3_900),
            *_statistics_gaps(connection, "statistics_short_term", 420),
        ]
        jumps = [
            *_statistics_jumps(connection, "statistics"),
            *_statistics_jumps(connection, "statistics_short_term"),
        ]
        issues = _statistics_meta_issues(connection)
    return {
        **status,
        "summary": {
            "rows": sum(item.get("rows", 0) for item in summaries),
            "gaps": len(gaps),
            "jumps": len(jumps),
            "unitChanges": len(issues["unitChanges"]),
            "stateClassWarnings": len(issues["stateClassWarnings"]),
        },
        "tables": summaries,
        "gaps": gaps,
        "jumps": jumps,
        "unitChanges": issues["unitChanges"],
        "stateClassWarnings": issues["stateClassWarnings"],
    }


def database_overview(backend: Any) -> dict[str, Any]:
    health = database_health(backend)
    entities = database_entities(backend)
    statistics = database_statistics(backend)
    compare = database_yaml_compare(backend)
    return {
        "available": health.get("available", False),
        "message": health.get("message", ""),
        "health": health,
        "entities": entities,
        "statistics": statistics,
        "compare": compare,
    }


def _sanitize_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 50
    return min(max(limit, 1), MAX_SQL_ROWS)


def _clean_sql(raw_sql: Any) -> str:
    if not isinstance(raw_sql, str) or not raw_sql.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Eine SELECT-Abfrage ist erforderlich.")
    sql = raw_sql.strip()
    if len(sql) > MAX_SQL_LENGTH:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die SQL-Abfrage ist zu lang.")
    if "\x00" in sql:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die SQL-Abfrage enthält ungültige Zeichen.")
    sql = re.sub(r";+\s*$", "", sql).strip()
    if ";" in sql:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Mehrere SQL-Anweisungen sind nicht erlaubt.")
    if not re.match(r"(?is)^\s*(select|with)\b", sql):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Nur SELECT-Abfragen sind erlaubt.")
    return sql


def _sql_authorizer(action: int, _arg1: str | None, _arg2: str | None, _db: str | None, _source: str | None) -> int:
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
    }
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    return value


def database_query(backend: Any, body: dict[str, Any]) -> dict[str, Any]:
    path = _database_path(backend)
    status = _available(path)
    if not status["available"]:
        raise ApiError(HTTPStatus.NOT_FOUND, status["message"])
    sql = _clean_sql(body.get("sql"))
    limit = _sanitize_limit(body.get("limit"))
    wrapped = f"SELECT * FROM ({sql}) AS yaml_manager_query LIMIT {limit + 1}"
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS

    with _connect(path) as connection:
        connection.set_authorizer(_sql_authorizer)
        connection.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1_000)
        try:
            cursor = connection.execute(wrapped)
            columns = [description[0] for description in cursor.description or []][:MAX_SQL_COLUMNS]
            raw_rows = cursor.fetchall()
        except sqlite3.OperationalError as exc:
            message = str(exc).split("\n", 1)[0]
            if "interrupted" in message.casefold():
                raise ApiError(HTTPStatus.REQUEST_TIMEOUT, "Die SQL-Abfrage wurde wegen Zeitlimit abgebrochen.") from exc
            raise ApiError(HTTPStatus.BAD_REQUEST, message) from exc
        except sqlite3.DatabaseError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc).split("\n", 1)[0]) from exc
        finally:
            connection.set_progress_handler(None, 0)
            connection.set_authorizer(None)

    truncated = len(raw_rows) > limit
    rows = [
        {column: _json_value(row[column]) for column in columns}
        for row in raw_rows[:limit]
    ]
    return {
        **status,
        "columns": columns,
        "rows": rows,
        "limit": limit,
        "rowCount": len(rows),
        "truncated": truncated,
    }

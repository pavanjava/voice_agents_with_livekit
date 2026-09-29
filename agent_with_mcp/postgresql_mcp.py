"""
PostgreSQL Explorer MCP Server
================================

Exposes tools to browse a PostgreSQL server's structure:
  - list databases
  - list schemas within a database
  - list tables within a schema
  - list foreign-key relations for a single table
  - list all foreign-key relations (a relation graph) within a schema

Run (same pattern as the sample server):
    fastmcp run postgres_server.py --transport http --port 8000
    # or simply: python postgres_server.py
"""

import os
from typing import Any
from dotenv import load_dotenv, find_dotenv
import psycopg2
import psycopg2.extras
from fastmcp import FastMCP

load_dotenv(find_dotenv())

mcp = FastMCP("PostgreSQL Explorer")

PGHOST = os.environ.get("PGHOST", "localhost")
PGPORT = int(os.environ.get("PGPORT", "5432"))
PGUSER = os.environ.get("PGUSER", "root")
PGPASSWORD = os.environ.get("PGPASSWORD", "root")
PGSSLMODE = os.environ.get("PGSSLMODE", "prefer")
PGADMINDB = os.environ.get("PGADMINDB", "postgres")

SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")


def _connect(database: str):
    """Open a connection to a specific database on the configured server."""
    return psycopg2.connect(
        host=PGHOST,
        port=PGPORT,
        user=PGUSER,
        password=PGPASSWORD,
        dbname=database,
        sslmode=PGSSLMODE,
    )


def _query(database: str, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Run a read-only query against `database` and return rows as dicts."""
    conn = _connect(database)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


@mcp.tool(
    name="ListDatabases",
    description="Lists all non-template databases on the configured PostgreSQL server, with owner and size.",
    title="List Databases",
)
def list_databases() -> list[dict[str, Any]]:
    sql = """
          SELECT
              d.datname AS database,
            pg_get_userbyid(d.datdba) AS owner,
            pg_size_pretty(pg_database_size(d.datname)) AS size
          FROM pg_database d
          WHERE d.datistemplate = false
          ORDER BY d.datname; \
          """
    return _query(PGADMINDB, sql)


@mcp.tool(
    name="ListSchemas",
    description="Lists all user-defined schemas within a given database (excludes system schemas).",
    title="List Schemas",
)
def list_schemas(database: str) -> list[dict[str, Any]]:
    sql = """
          SELECT
              schema_name AS schema,
            schema_owner AS owner
          FROM information_schema.schemata
          WHERE schema_name NOT IN %s
            AND schema_name NOT LIKE 'pg_temp%%'
            AND schema_name NOT LIKE 'pg_toast_temp%%'
          ORDER BY schema_name; \
          """
    return _query(database, sql, (SYSTEM_SCHEMAS,))


@mcp.tool(
    name="ListTables",
    description="Lists all tables (and views) within a given schema of a given database.",
    title="List Tables",
)
def list_tables(database: str, schema: str) -> list[dict[str, Any]]:
    sql = """
          SELECT
              table_name AS table,
            table_type AS type
          FROM information_schema.tables
          WHERE table_schema = %s
          ORDER BY table_name; \
          """
    return _query(database, sql, (schema,))


@mcp.tool(
    name="ListTableColumns",
    description="Lists columns, data types, nullability, and defaults for a given table.",
    title="List Table Columns",
)
def list_table_columns(database: str, schema: str, table: str) -> list[dict[str, Any]]:
    sql = """
          SELECT
              column_name AS column,
            data_type AS type,
            is_nullable AS nullable,
            column_default AS default
          FROM information_schema.columns
          WHERE table_schema = %s AND table_name = %s
          ORDER BY ordinal_position; \
          """
    return _query(database, sql, (schema, table))


@mcp.tool(
    name="ListTableRelations",
    description=(
            "Lists foreign-key relations for a single table: relations where this table "
            "references another table (outgoing), and relations where other tables "
            "reference this table (incoming)."
    ),
    title="List Table Relations",
)
def list_table_relations(database: str, schema: str, table: str) -> dict[str, Any]:
    outgoing_sql = """
                   SELECT
                       tc.constraint_name,
                       kcu.column_name AS local_column,
                       ccu.table_schema AS foreign_schema,
                       ccu.table_name AS foreign_table,
                       ccu.column_name AS foreign_column
                   FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                                 ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                            JOIN information_schema.constraint_column_usage ccu
                                 ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
                   WHERE tc.constraint_type = 'FOREIGN KEY'
                     AND tc.table_schema = %s
                     AND tc.table_name = %s
                   ORDER BY tc.constraint_name; \
                   """
    incoming_sql = """
                   SELECT
                       tc.constraint_name,
                       tc.table_schema AS referencing_schema,
                       tc.table_name AS referencing_table,
                       kcu.column_name AS referencing_column,
                       ccu.column_name AS local_column
                   FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                                 ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                            JOIN information_schema.constraint_column_usage ccu
                                 ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
                   WHERE tc.constraint_type = 'FOREIGN KEY'
                     AND ccu.table_schema = %s
                     AND ccu.table_name = %s
                   ORDER BY tc.constraint_name; \
                   """
    return {
        "table": table,
        "schema": schema,
        "outgoing": _query(database, outgoing_sql, (schema, table)),
        "incoming": _query(database, incoming_sql, (schema, table)),
    }


@mcp.tool(
    name="ListSchemaRelations",
    description=(
            "Lists all foreign-key relations across every table in a schema, as a flat "
            "edge list (from_table.from_column -> to_table.to_column). Useful for "
            "building a full relationship graph / ERD of the schema."
    ),
    title="List Schema Relations",
)
def list_schema_relations(database: str, schema: str) -> list[dict[str, Any]]:
    sql = """
          SELECT
              tc.constraint_name,
              tc.table_name AS from_table,
              kcu.column_name AS from_column,
              ccu.table_name AS to_table,
              ccu.column_name AS to_column
          FROM information_schema.table_constraints tc
                   JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                   JOIN information_schema.constraint_column_usage ccu
                        ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
          WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = %s
          ORDER BY tc.table_name, tc.constraint_name; \
          """
    return _query(database, sql, (schema,))


if __name__ == "__main__":
    mcp.run(transport="http", port=8000)
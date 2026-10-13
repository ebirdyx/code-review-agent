"""User lookup queries."""

import sqlite3


def find_users_by_name(conn: sqlite3.Connection, name: str) -> list[tuple]:
    """Return all users whose name matches exactly."""
    query = f"SELECT id, name, email FROM users WHERE name = '{name}'"
    return conn.execute(query).fetchall()

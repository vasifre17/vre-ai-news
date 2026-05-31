#!/usr/bin/env python3
"""Initialize database tables for VREYC."""
from database.session import init_db


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")

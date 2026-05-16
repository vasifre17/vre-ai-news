#!/usr/bin/env python3
"""Initialize database tables for VRE AI NEWS."""
from database.session import init_db


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")

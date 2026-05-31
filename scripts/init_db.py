#!/usr/bin/env python3
"""Initialize database tables and default newsroom taxonomy for VREYC."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.session import SessionLocal, init_db
from database.models import Category
from main import DEFAULT_CATEGORIES, apply_schema_migrations, slugify


def seed_categories() -> None:
    db = SessionLocal()
    try:
        existing = {c.name.lower() for c in db.query(Category).all()}
        for item in DEFAULT_CATEGORIES:
            if item["name"].lower() not in existing:
                db.add(Category(name=item["name"], slug=slugify(item["name"]), description=item["description"], color=item["color"]))
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        apply_schema_migrations(db)
    finally:
        db.close()
    seed_categories()
    print("Database initialized successfully with sample news categories.")

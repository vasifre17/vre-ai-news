#!/usr/bin/env python3
"""Generate bcrypt hash for ADMIN_PASSWORD_HASH."""
from getpass import getpass
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main() -> None:
    password = getpass("Enter admin password: ")
    confirm = getpass("Confirm admin password: ")
    if password != confirm:
        raise SystemExit("Passwords do not match.")
    if len(password) < 12:
        raise SystemExit("Password must be at least 12 characters.")
    print(pwd_context.hash(password))


if __name__ == "__main__":
    main()

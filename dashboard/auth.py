"""Persistent accounts and hashed browser-session tokens (stdlib only)."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

USERNAME = re.compile(r"[a-z][a-z0-9_-]{2,31}\Z")
SCRYPT_N = 131072


def username(value):
    if not isinstance(value, str) or not USERNAME.fullmatch(value):
        raise ValueError("Username: 3–32 lowercase letters, numbers, _ or -, starting with a letter.")
    return value


def password_hash(password, salt):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise ValueError("Password must contain 8–128 characters.")
    return hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N,
                          r=8, p=1, dklen=32, maxmem=256 * 1024 * 1024).hex()


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "accounts.sqlite3"
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY, salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    expires REAL NOT NULL, FOREIGN KEY(username) REFERENCES users(username));
            ''')
        os.chmod(self.path, 0o600)
        key_path = self.directory / "bridge.key"
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as stream:
                stream.write(secrets.token_hex(32))
        self.bridge_key = key_path.read_text().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", self.bridge_key):
            raise ValueError("Invalid bridge.key; restore it from backup.")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def register(self, name, password):
        name = username(name)
        salt = secrets.token_bytes(16)
        encoded = password_hash(password, salt)
        try:
            with self.connect() as db:
                if db.execute("SELECT count(*) FROM users").fetchone()[0] >= 1000:
                    raise ValueError("Registration capacity reached. Contact the administrator.")
                db.execute("INSERT INTO users VALUES (?, ?, ?, 'user', ?)",
                           (name, salt.hex(), encoded, time.time()))
        except sqlite3.IntegrityError:
            raise ValueError("This username already exists. Choose Sign in instead.") from None

    def verify(self, name, password):
        name = username(name)
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()
        salt = bytes.fromhex(row["salt"]) if row else b'\x00' * 16
        candidate = password_hash(password, salt)
        return bool(row and hmac.compare_digest(candidate, row["password_hash"]))

    def change_password(self, name, current, replacement, digest):
        with self.connect() as db:
            row = db.execute("SELECT salt,password_hash FROM users WHERE username=?", (name,)).fetchone()
        if not row or not hmac.compare_digest(password_hash(current, bytes.fromhex(row["salt"])), row["password_hash"]):
            raise ValueError("Current password is incorrect.")
        if current == replacement:
            raise ValueError("Choose a different new password.")
        salt = secrets.token_bytes(16)
        encoded = password_hash(replacement, salt)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM sessions WHERE digest=? AND username=? AND expires>?",
                              (digest, name, time.time())).fetchone():
                raise ValueError("Session expired. Sign in again.")
            updated = db.execute("UPDATE users SET salt=?,password_hash=? WHERE username=? AND password_hash=?",
                                 (salt.hex(), encoded, name, row["password_hash"]))
            if updated.rowcount != 1:
                raise ValueError("Password changed elsewhere. Sign in again.")
            db.execute("DELETE FROM sessions WHERE username=?", (name,))

    def issue(self, name, hours=12):
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE username=? OR expires<=?", (name, time.time()))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                       (digest, name, time.time() + hours * 3600))
        return token, digest

    def session(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute('''SELECT s.digest, s.username, s.expires, u.role
                FROM sessions s JOIN users u ON s.username=u.username
                WHERE s.digest=? AND s.expires>?''', (digest, time.time())).fetchone()
        return dict(row) if row else None

    def revoke(self, digest):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE digest=?", (digest,))

    def promote(self, name):
        with self.connect() as db:
            changed = db.execute("UPDATE users SET role='admin' WHERE username=?", (username(name),))
            if changed.rowcount != 1:
                raise ValueError("Register that account first.")

    def ticket(self, name):
        return hmac.new(self.bridge_key.encode(), name.encode(), hashlib.sha256).hexdigest()

"""SQLite connection handling and schema migrations."""

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from typing import Generator


@contextmanager
def get_db(db_path: str = "./interview_prep.db") -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite connections with commit/rollback handling.

    Args:
        db_path: Path to SQLite database file.

    Yields:
        SQLite connection with Row factory.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _compute_question_hash(question_text: str) -> str:
    """Normalize and hash question text for deduplication.

    Lowercases, strips whitespace/punctuation, collapses spaces, then SHA-256.

    Args:
        question_text: Raw question string.

    Returns:
        Hex digest of normalized text.
    """
    normalized = question_text.lower().strip()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def init_db(db_path: str = "./interview_prep.db") -> None:
    """Initialize database tables with migration for ``question_hash``.

    Creates ``questions``, ``answers``, ``feedback`` tables if missing,
    migrates existing ``questions`` table to add ``question_hash`` column
    and unique index, and backfills hashes for existing rows.

    Args:
        db_path: Path to SQLite database file.
    """
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT NOT NULL,
                category TEXT NOT NULL,
                date_added DATE DEFAULT CURRENT_DATE,
                is_answered BOOLEAN DEFAULT 0,
                model_source TEXT,
                question_hash TEXT UNIQUE
            )
            """
        )

        # Migration: add question_hash if table existed before this schema
        try:
            cursor.execute("SELECT question_hash FROM questions LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE questions ADD COLUMN question_hash TEXT")

        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_question_hash "
            "ON questions(question_hash)"
        )

        # Backfill hashes for rows where hash is NULL
        cursor.execute("SELECT id, question_text FROM questions WHERE question_hash IS NULL")
        rows = cursor.fetchall()
        for row in rows:
            q_hash = _compute_question_hash(row["question_text"])
            try:
                cursor.execute(
                    "UPDATE questions SET question_hash = ? WHERE id = ?",
                    (q_hash, row["id"]),
                )
            except sqlite3.IntegrityError:
                cursor.execute("SELECT id FROM questions WHERE question_hash = ?", (q_hash,))
                existing = cursor.fetchone()
                if existing and existing["id"] != row["id"]:
                    cursor.execute("DELETE FROM questions WHERE id = ?", (row["id"],))

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                user_answer TEXT NOT NULL,
                model_summary TEXT,
                date_answered TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_correct BOOLEAN,
                FOREIGN KEY (question_id) REFERENCES questions(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                answer_id INTEGER NOT NULL,
                feedback_text TEXT NOT NULL,
                score INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (answer_id) REFERENCES answers(id)
            )
            """
        )

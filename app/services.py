"""Core business logic for question generation and answer validation."""

import hashlib
import re
from typing import Any, Dict, List

from app.config import calculate_domain_distribution, calculate_question_counts
from app.db import get_db
from app.llm import fetch_questions, validate_answer


def compute_question_hash(question_text: str) -> str:
    """Normalize and SHA-256 hash question text for deduplication."""
    normalized = question_text.lower().strip()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_recent_question_context(db_path: str, limit: int = 20) -> List[str]:
    """Fetch recent question texts to discourage LLM repeats.

    Args:
        db_path: Path to SQLite database.
        limit: Maximum number of recent questions to return.

    Returns:
        List of recent question texts.
    """
    try:
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT question_text FROM questions "
                "ORDER BY date_added DESC, id DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [row["question_text"] for row in rows]
    except Exception:
        return []


def generate_daily_questions(config: Dict[str, Any]) -> None:
    """Fetch new daily questions and save them with hash deduplication.

    Uses dynamic prompt templates via ``load_prompt_template`` and
    ``.format()`` with profile, tech stack, and category counts.
    Normalizes and hashes each question, skips existing hashes,
    and passes recent topics to the LLM to discourage repeats.
    """
    llm_cfg = config["llm"]
    db_path = config["database"]["path"]

    try:
        counts = calculate_domain_distribution(config)
    except Exception:
        counts = calculate_question_counts(config)
    categories = list(counts.keys())

    if not categories:
        questions_cfg = config["questions"]
        domains_cfg = questions_cfg.get("domains") or questions_cfg.get("categories", [])
        if isinstance(domains_cfg, dict):
            categories = list(domains_cfg.keys())
        elif isinstance(domains_cfg, list):
            categories = domains_cfg
        counts = {cat: 1 for cat in categories}

    recent_limit = config.get("questions", {}).get("recent_context_limit", 15)
    recent_topics = get_recent_question_context(db_path, limit=recent_limit)

    questions = fetch_questions(
        llm_cfg, categories, counts, config=config, recent_topics=recent_topics
    )

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT question_hash FROM questions WHERE question_hash IS NOT NULL")
        existing_hashes = {row["question_hash"] for row in cursor.fetchall()}
        seen_batch_hashes: set[str] = set()
        inserted = 0
        skipped = 0

        for q in questions:
            q_text = q.get("question", "").strip()
            q_cat = q.get("category", categories[0] if categories else "general")
            if not q_text:
                continue
            q_hash = compute_question_hash(q_text)
            if q_hash in existing_hashes or q_hash in seen_batch_hashes:
                skipped += 1
                continue
            seen_batch_hashes.add(q_hash)
            try:
                cursor.execute(
                    "INSERT INTO questions "
                    "(question_text, category, model_source, question_hash) "
                    "VALUES (?, ?, ?, ?)",
                    (q_text, q_cat, llm_cfg.get("type", "unknown"), q_hash),
                )
                existing_hashes.add(q_hash)
                inserted += 1
            except Exception as exc:
                if "UNIQUE" in str(exc) or "unique" in str(exc).lower():
                    skipped += 1
                    continue
                raise

        if skipped:
            print(f"Deduplication: inserted {inserted}, skipped {skipped} duplicates (hash).")
        else:
            print(f"Inserted {inserted} new questions.")


def process_answer(config: Dict[str, Any], question_id: int, user_answer: str) -> Dict[str, Any]:
    """Validate answer, update question status, and store feedback.

    Evaluation template is loaded via ``load_prompt_template`` and
    populated using ``.format(role=..., question=..., user_answer=...)``.
    """
    db_path = config["database"]["path"]

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT question_text FROM questions WHERE id = ?", (question_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Question {question_id} not found.")

        validation = validate_answer(
            config["llm"], row["question_text"], user_answer, config=config
        )
        score = validation.get("score", 0)

        cursor.execute(
            "INSERT INTO answers (question_id, user_answer, model_summary, is_correct) "
            "VALUES (?, ?, ?, ?)",
            (question_id, user_answer, validation.get("summary", ""), score >= 70),
        )
        answer_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO feedback (answer_id, feedback_text, score) VALUES (?, ?, ?)",
            (answer_id, validation.get("feedback", ""), score),
        )

        cursor.execute("UPDATE questions SET is_answered = 1 WHERE id = ?", (question_id,))
        return validation

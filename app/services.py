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


def generate_targeted_questions(
    config: Dict[str, Any],
    domain: str,
    topic_keyword: str = "",
    count: int = 1,
) -> List[Dict[str, str]]:
    """Generate on-demand questions for a specific domain/topic.

    Injects topic_keyword into LLM prompt context so the model focuses on that sub-topic.
    Handles hash deduplication like daily generation.

    Args:
        config: Full app config.
        domain: Target domain/category (e.g., system_design, core_java, custom).
        topic_keyword: Specific sub-topic (e.g., Kafka, Garbage Collection).
        count: Number of questions to generate.

    Returns:
        List of inserted question dicts.
    """
    llm_cfg = config["llm"]
    db_path = config["database"]["path"]

    # Normalize domain: allow custom strings
    domain = domain.strip() or "general"
    topic_keyword = topic_keyword.strip()
    count = max(1, int(count))

    categories = [domain]
    counts = {domain: count}

    recent_limit = config.get("questions", {}).get("recent_context_limit", 15)
    recent_topics = get_recent_question_context(db_path, limit=recent_limit)

    # Pass topic via fetch_questions
    questions = fetch_questions(
        llm_cfg,
        categories,
        counts,
        config=config,
        recent_topics=recent_topics,
        topic_keyword=topic_keyword,
    )

    # If LLM ignored topic or count, ensure at least count items (fallback to mock)
    if len(questions) < count:
        # Supplement with mock but ensure topic is reflected if possible
        from app.llm import _mock_questions

        mock_needed = count - len(questions)
        mock_qs = _mock_questions(categories, {domain: mock_needed})
        # Optionally inject topic into mock question text for visibility
        if topic_keyword:
            for mq in mock_qs:
                if topic_keyword.lower() not in mq["question"].lower():
                    mq["question"] = f"[{topic_keyword}] {mq['question']}"
        questions.extend(mock_qs)

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT question_hash FROM questions WHERE question_hash IS NOT NULL")
        existing_hashes = {row["question_hash"] for row in cursor.fetchall()}
        seen_batch: set[str] = set()
        inserted: List[Dict[str, str]] = []
        skipped = 0
        for q in questions[:count]:
            q_text = q.get("question", "").strip()
            q_cat = q.get("category", domain)
            if not q_text:
                continue
            # Inject topic into text if not already present (for custom domain visibility)
            if topic_keyword and topic_keyword.lower() not in q_text.lower():
                # Prepend topic context for targeted practice distinction
                q_text = f"[{topic_keyword}] {q_text}"
            q_hash = compute_question_hash(q_text)
            if q_hash in existing_hashes or q_hash in seen_batch:
                skipped += 1
                continue
            seen_batch.add(q_hash)
            try:
                cursor.execute(
                    "INSERT INTO questions (question_text, category, model_source, question_hash) "
                    "VALUES (?, ?, ?, ?)",
                    (q_text, q_cat, llm_cfg.get("type", "unknown"), q_hash),
                )
                existing_hashes.add(q_hash)
                inserted.append({"question": q_text, "category": q_cat})
            except Exception as exc:
                if "UNIQUE" in str(exc) or "unique" in str(exc).lower():
                    skipped += 1
                    continue
                raise
        if skipped:
            print(f"Targeted deduplication: inserted {len(inserted)}, skipped {skipped}.")
        else:
            print(f"Inserted {len(inserted)} targeted questions for domain={domain} topic={topic_keyword}.")
        return inserted


def get_question_guidance(config: Dict[str, Any], question_id: int) -> Dict[str, Any]:
    """Provide model answer and interviewer guidance without marking completed.

    Loads ``explain_answer.txt`` with {role}, {experience_years}, {tech_stack},
    {category}, {question} and expects JSON with model_answer, key_points_to_mention,
    interviewer_mindset.

    Args:
        config: Full app config.
        question_id: Question ID to explain.

    Returns:
        Dict with model_answer, key_points_to_mention, interviewer_mindset.
    """
    from app.config import load_prompt_template
    from app.llm import extract_json, query_llm
    import json

    db_path = config["database"]["path"]
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT question_text, category FROM questions WHERE id = ?", (question_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Question {question_id} not found.")
        question_text = row["question_text"]
        category = row["category"]

    profile = config.get("profile", {})
    role = profile.get("role", "SDE 2")
    experience_years = profile.get("experience_years", 6)
    tech_stack_list = profile.get("tech_stack", ["Java"])
    tech_stack = ", ".join(tech_stack_list) if isinstance(tech_stack_list, list) else str(tech_stack_list)

    try:
        template = load_prompt_template("evaluation", "explain_answer")
        escaped = template.replace("{", "{{").replace("}", "}}")
        for key in ["role", "experience_years", "tech_stack", "category", "question"]:
            escaped = escaped.replace("{{" + key + "}}", "{" + key + "}")
        prompt = escaped.format(
            role=role,
            experience_years=experience_years,
            tech_stack=tech_stack,
            category=category,
            question=question_text,
        )
        raw = query_llm(config["llm"], prompt)
        clean = extract_json(raw)
        # Sanitize smart quotes before parse
        clean = clean.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        data = json.loads(clean)
        # Normalize
        model_answer = data.get("model_answer", "")
        key_points = data.get("key_points_to_mention", [])
        mindset = data.get("interviewer_mindset", "")
        if isinstance(key_points, str):
            key_points = [key_points]
        if not isinstance(key_points, list):
            key_points = [str(key_points)]
        # Convert model_answer if list/dict
        if isinstance(model_answer, (dict, list)):
            model_answer = json.dumps(model_answer, indent=2)
        if isinstance(mindset, (dict, list)):
            mindset = json.dumps(mindset, indent=2)
        if not model_answer:
            raise ValueError("Empty model_answer")
        return {
            "model_answer": str(model_answer),
            "key_points_to_mention": [str(k) for k in key_points],
            "interviewer_mindset": str(mindset) if mindset else "Evaluates depth, trade-offs, and edge cases.",
            "question": question_text,
            "category": category,
        }
    except Exception as exc:
        # Fallback mock guidance for offline / parse failure
        print(f"Warning: explain answer failed ({exc}), using mock guidance.")
        return {
            "model_answer": (
                f"Sample high-quality answer for [{category}] tailored to {role} ({experience_years}y, {tech_stack}):\n\n"
                f"For \"{question_text}\", a strong answer would start with a concise definition, "
                f"explain core principles with trade-offs (e.g., consistency vs availability, performance vs complexity), "
                f"provide a concrete example or diagram, discuss edge cases (race conditions, failure modes, scaling limits), "
                f"and conclude with monitoring and operational considerations. Tailor depth to {experience_years} years experience."
            ),
            "key_points_to_mention": [
                f"Core definition and why {category} matters for {role}",
                f"Trade-offs relevant to {tech_stack} stack",
                "Concrete example or architecture sketch",
                "Edge cases, failure modes, and mitigation",
                "Monitoring, scaling, and operational considerations",
            ],
            "interviewer_mindset": (
                f"For {role} ({experience_years}y), the interviewer checks whether you can articulate trade-offs, "
                f"justify choices for {category}, and demonstrate depth beyond surface definitions. "
                "They look for structured thinking, real-world experience, and awareness of edge cases."
            ),
            "question": question_text,
            "category": category,
        }


def process_answer(config: Dict[str, Any], question_id: int, user_answer: str) -> Dict[str, Any]:

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

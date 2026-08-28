"""Command-line interface for Interview Prep App."""

import sys

from app.config import load_config
from app.db import get_db, init_db
from app.services import generate_daily_questions, process_answer


def main() -> int:
    """Entry point for CLI commands.

    Supports: init-db, generate, list, submit, web/--web

    Returns:
        Exit code (0 success, 1 error).
    """
    config = load_config()
    db_path = config["database"]["path"]

    if len(sys.argv) < 2:
        print("Usage: python -m app.cli [init-db | generate | list | submit <id> <answer> | web]")
        return 0

    cmd = sys.argv[1]

    if cmd == "init-db":
        init_db(db_path)
        print("Database initialized successfully.")

    elif cmd == "generate":
        print("Fetching questions from LLM...")
        generate_daily_questions(config)
        print("Questions stored successfully.\n")
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM questions WHERE is_answered = 0 ORDER BY id")
            rows = cursor.fetchall()
            if not rows:
                print("No pending questions found.")
            else:
                print(f"Pending questions ({len(rows)}):")
                for q in rows:
                    print(f"[{q['id']}] [{q['category']}] {q['question_text']}")

    elif cmd == "list":
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM questions WHERE is_answered = 0")
            rows = cursor.fetchall()
            if not rows:
                print("No pending questions found.")
            for q in rows:
                print(f"[{q['id']}] [{q['category']}] {q['question_text']}")

    elif cmd == "submit":
        if len(sys.argv) < 4:
            print("Usage: python -m app.cli submit <question_id> <answer>")
            return 1
        q_id = int(sys.argv[2])
        ans = " ".join(sys.argv[3:])
        result = process_answer(config, q_id, ans)
        print(f"\nScore: {result.get('score')}/100")
        print(f"Feedback: {result.get('feedback')}")

    elif cmd in ("web", "--web"):
        from app.web import run_web

        run_web()

    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python -m app.cli [init-db | generate | list | submit <id> <answer> | web]")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

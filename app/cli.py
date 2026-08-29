"""Command-line interface for Interview Prep App."""

import argparse
import sys

from app.config import load_config
from app.db import get_db, init_db
from app.services import generate_daily_questions, generate_targeted_questions, process_answer


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
        # Support targeted generation: python main.py generate --domain X --topic Y --count N
        # Parse optional args after 'generate'
        parser = argparse.ArgumentParser(prog="generate", add_help=False)
        parser.add_argument("--domain", type=str, default=None)
        parser.add_argument("--topic", type=str, default=None)
        parser.add_argument("--count", type=int, default=None)
        # Also support --domain without equals and positional fallback
        try:
            args, _ = parser.parse_known_args(sys.argv[2:])
        except SystemExit:
            args = argparse.Namespace(domain=None, topic=None, count=None)

        if args.domain or args.topic or args.count is not None:
            domain = args.domain or "general"
            topic = args.topic or ""
            count = args.count if args.count is not None else 1
            print(f"Fetching targeted questions from LLM (domain={domain}, topic={topic}, count={count})...")
            inserted = generate_targeted_questions(config, domain=domain, topic_keyword=topic, count=count)
            print(f"Targeted questions stored successfully. Inserted {len(inserted)}.\n")
            for idx, q in enumerate(inserted, 1):
                print(f"[{idx}] [{q['category']}] {q['question']}")
            # Also list pending
            with get_db(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM questions WHERE is_answered = 0 ORDER BY id DESC LIMIT 10")
                rows = cursor.fetchall()
                if rows:
                    print(f"\nRecent pending (up to 10):")
                    for q in rows:
                        print(f"[{q['id']}] [{q['category']}] {q['question_text']}")
        else:
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

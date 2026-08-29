"""Flask Web UI for Interview Prep App with domain, date, and status filtering."""

import os
import secrets
from datetime import datetime, timedelta

from flask import Flask, flash, redirect, render_template, request, url_for

from app.config import load_config
from app.db import get_db
from app.services import (
    generate_daily_questions,
    generate_targeted_questions,
    get_question_guidance,
    process_answer,
)

config = load_config()

app = Flask(__name__)
# Secret key must come from env var or config.yaml — never hardcoded.
_config_secret = config.get("web", {}).get("secret_key")
if _config_secret and "YOUR_" in str(_config_secret):
    _config_secret = None

app.secret_key = (
    os.getenv("WEB_SECRET_KEY") or os.getenv("FLASK_SECRET_KEY") or _config_secret or secrets.token_hex(32)
)
if app.secret_key == "YOUR_WEB_SECRET_KEY_CHANGE_ME":
    import warnings

    warnings.warn("Using placeholder WEB_SECRET_KEY from config.yaml - set WEB_SECRET_KEY env var for production")
    app.secret_key = secrets.token_hex(32)


@app.route("/")
def dashboard():
    """Dashboard with domain, date, and status filtering.

    Query params:
        domain: Filter by category (e.g., system_design)
        date: Filter by date_added YYYY-MM-DD (defaults to CURRENT_DATE)
        status: Filter by is_answered (all|pending|completed)
    """
    db_path = config["database"]["path"]
    selected_domain = request.args.get("domain", "").strip()
    selected_date = request.args.get("date", "").strip()
    selected_status = request.args.get("status", "all").strip().lower()
    if selected_status not in ("all", "pending", "completed"):
        selected_status = "all"
    use_date = selected_date if selected_date else None

    with get_db(db_path) as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM questions WHERE 1=1"
        params: list[str] = []
        if use_date:
            query += " AND date_added = ?"
            params.append(use_date)
        else:
            query += " AND date_added = CURRENT_DATE"
        if selected_domain:
            query += " AND category = ?"
            params.append(selected_domain)
        if selected_status == "pending":
            query += " AND is_answered = 0"
        elif selected_status == "completed":
            query += " AND is_answered = 1"
        query += " ORDER BY id"
        cursor.execute(query, params)
        daily_questions = cursor.fetchall()

        stats_query = """
            SELECT AVG(f.score) as avg_score, COUNT(a.id) as total_answered
            FROM answers a
            JOIN feedback f ON a.id = f.answer_id
            JOIN questions q ON a.question_id = q.id
            WHERE 1=1
        """
        stats_params: list[str] = []
        if use_date:
            stats_query += " AND DATE(a.date_answered) = ?"
            stats_params.append(use_date)
        else:
            stats_query += " AND DATE(a.date_answered) = CURRENT_DATE"
        if selected_domain:
            stats_query += " AND q.category = ?"
            stats_params.append(selected_domain)
        # Status does not affect stats (stats are for answered)
        cursor.execute(stats_query, stats_params)
        stats = cursor.fetchone()

        cursor.execute("SELECT DISTINCT category FROM questions ORDER BY category")
        all_domains = [row["category"] for row in cursor.fetchall()]
        cursor.execute("SELECT DISTINCT date_added FROM questions ORDER BY date_added DESC")
        all_dates = [row["date_added"] for row in cursor.fetchall()]

    prev_date = next_date = None
    if use_date:
        try:
            dt = datetime.strptime(use_date, "%Y-%m-%d")
            prev_date = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
            next_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            pass
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        prev_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        next_date = today

    return render_template(
        "dashboard.html",
        questions=daily_questions,
        stats=stats,
        all_domains=all_domains,
        selected_domain=selected_domain,
        selected_date=selected_date or datetime.now().strftime("%Y-%m-%d"),
        selected_status=selected_status,
        all_dates=all_dates,
        prev_date=prev_date,
        next_date=next_date,
    )


@app.route("/question/<int:q_id>", methods=["GET", "POST"])
def view_question(q_id: int):
    """View question, submit answer, and display feedback."""
    db_path = config["database"]["path"]
    feedback_data = None

    if request.method == "POST":
        user_answer = request.form.get("user_answer")
        if user_answer:
            feedback_data = process_answer(config, q_id, user_answer)
            flash("Answer submitted and evaluated!", "success")

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM questions WHERE id = ?", (q_id,))
        question = cursor.fetchone()
        cursor.execute(
            """
            SELECT a.user_answer, a.model_summary, f.score, f.feedback_text, f.created_at
            FROM answers a
            JOIN feedback f ON a.id = f.answer_id
            WHERE a.question_id = ?
            ORDER BY a.date_answered DESC LIMIT 1
            """,
            (q_id,),
        )
        history = cursor.fetchone()

    return render_template(
        "question.html", question=question, history=history, feedback=feedback_data
    )


@app.route("/question/<int:q_id>/explain", methods=["POST"])
def explain_answer(q_id: int):
    """Interactive explain answer: return guidance without marking completed.

    Returns JSON with model_answer, key_points_to_mention, interviewer_mindset.
    """
    try:
        guidance = get_question_guidance(config, q_id)
        # Return JSON for fetch API; also support flash for non-JS fallback
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json or "application/json" in request.headers.get("Accept", ""):
            from flask import jsonify

            return jsonify(guidance)
        # Fallback: render question page with guidance
        # We will handle via JS drawer, but also flash
        flash("Guidance loaded - see drawer below.", "info")
        # For non-AJAX, return JSON as well to keep simple
        from flask import jsonify

        return jsonify(guidance)
    except Exception as exc:
        from flask import jsonify

        return jsonify({"error": str(exc)}), 404


@app.route("/generate", methods=["POST"])
def generate():
    """Trigger manual daily question generation from Web UI."""
    generate_daily_questions(config)
    flash("New daily questions fetched successfully!", "info")
    return redirect(url_for("dashboard"))


@app.route("/generate_custom", methods=["POST"])
def generate_custom():
    """On-demand targeted question generation for specific domain/topic/count.

    Form fields:
        domain: target domain (e.g., system_design, core_java, custom)
        topic_keyword: sub-topic keyword (e.g., Kafka, Garbage Collection)
        count: number of questions (default 1)
    """
    domain = request.form.get("domain", "").strip() or "general"
    topic_keyword = request.form.get("topic_keyword", "").strip() or request.form.get("topic", "").strip()
    count_raw = request.form.get("count", "1").strip()
    try:
        count = int(count_raw)
        count = max(1, min(10, count))
    except ValueError:
        count = 1

    inserted = generate_targeted_questions(config, domain=domain, topic_keyword=topic_keyword, count=count)
    if inserted:
        flash(f"Generated {len(inserted)} targeted question(s) for domain '{domain}' topic '{topic_keyword}'!", "success")
    else:
        flash(f"No new questions generated (all duplicates skipped) for domain '{domain}' topic '{topic_keyword}'.", "warning")
    # Preserve filters if provided
    return redirect(url_for("dashboard", domain=domain))


@app.route("/history")
def history():
    """History archive with domain, date, and status filtering."""
    db_path = config["database"]["path"]
    selected_domain = request.args.get("domain", "").strip()
    selected_date = request.args.get("date", "").strip()
    selected_status = request.args.get("status", "all").strip().lower()
    if selected_status not in ("all", "pending", "completed", "answered"):
        # history is inherently answered, but allow pending/completed toggle for questions view
        selected_status = "all"
    history_limit = config.get("web", {}).get("history_limit", 100)

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        # For history, we normally show answered questions, but if status=pending, show pending questions history view
        if selected_status == "pending":
            # Show pending questions (no answers) - for status filter completeness
            query = "SELECT question_text, category, '' as user_answer, 0 as score, '' as feedback_text, '' as date_answered, date_added FROM questions WHERE is_answered = 0"
            params: list[str] = []
            if selected_domain:
                query += " AND category = ?"
                params.append(selected_domain)
            if selected_date:
                query += " AND date_added = ?"
                params.append(selected_date)
            query += " ORDER BY date_added DESC, id DESC LIMIT ?"
            params.append(str(history_limit))
            cursor.execute(query, params)
            records = cursor.fetchall()
        elif selected_status == "completed":
            query = """
                SELECT q.question_text, q.category, a.user_answer, f.score,
                       f.feedback_text, a.date_answered, q.date_added
                FROM questions q
                JOIN answers a ON q.id = a.question_id
                JOIN feedback f ON a.id = f.answer_id
                WHERE 1=1
            """
            params: list[str] = []
            if selected_domain:
                query += " AND q.category = ?"
                params.append(selected_domain)
            if selected_date:
                query += " AND DATE(a.date_answered) = ?"
                params.append(selected_date)
            query += " ORDER BY a.date_answered DESC LIMIT ?"
            params.append(str(history_limit))
            cursor.execute(query, params)
            records = cursor.fetchall()
        else:  # all
            query = """
                SELECT q.question_text, q.category, a.user_answer, f.score,
                       f.feedback_text, a.date_answered, q.date_added
                FROM questions q
                JOIN answers a ON q.id = a.question_id
                JOIN feedback f ON a.id = f.answer_id
                WHERE 1=1
            """
            params: list[str] = []
            if selected_domain:
                query += " AND q.category = ?"
                params.append(selected_domain)
            if selected_date:
                query += " AND DATE(a.date_answered) = ?"
                params.append(selected_date)
            query += " ORDER BY a.date_answered DESC LIMIT ?"
            params.append(str(history_limit))
            cursor.execute(query, params)
            records = cursor.fetchall()

        cursor.execute("SELECT DISTINCT category FROM questions ORDER BY category")
        all_domains = [row["category"] for row in cursor.fetchall()]
        cursor.execute("SELECT DISTINCT DATE(date_answered) as d FROM answers ORDER BY d DESC")
        all_dates = [row["d"] for row in cursor.fetchall() if row["d"]]

    prev_date = next_date = None
    if selected_date:
        try:
            dt = datetime.strptime(selected_date, "%Y-%m-%d")
            prev_date = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
            next_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return render_template(
        "history.html",
        records=records,
        all_domains=all_domains,
        selected_domain=selected_domain,
        selected_date=selected_date,
        selected_status=selected_status,
        all_dates=all_dates,
        prev_date=prev_date,
        next_date=next_date,
    )


def run_web() -> None:
    """Run Flask development server using host/port/debug from config.yaml."""
    web_cfg = config.get("web", {})
    host = web_cfg.get("host", "127.0.0.1")
    port = web_cfg.get("port", 5000)
    debug = web_cfg.get("debug", False)
    app.run(host=host, port=port, debug=debug)

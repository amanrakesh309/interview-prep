```markdown
# Interview Prep App - Architecture & Execution Plan

---

## 1. Overview
A **configurable Python app** that:
- Fetches daily interview questions from a **configurable LLM** (local or cloud, e.g., Mistral, Ollama, OpenAI).
- Stores questions, user answers, and model-generated summaries in a **SQLite database**.
- Validates user answers against LLM-generated summaries and scores them (0-100).
- Supports execution via a rich CLI, an integrated Web UI dashboard, or scheduled cron execution.

---

## 2. Key Features
- **Configurable LLM Provider**: Switch between local engines (Ollama) and cloud APIs (Mistral, OpenAI) via a config file.
- **Dynamic Question Generation**: Retrieves targeted questions based on configurable categories (system design, Java, debugging, outage handling).
- **Resilient JSON Parsing & Answer Validation**: Uses regex extraction to clean LLM markdown output prior to parsing, comparing user answers against model reference summaries.
- **Persistent Data Tracking**: Tracks question completion state (`is_answered`), historical answers, scores, and feedback timestamps.
- **Web UI & CLI Interfaces**: Offers a CLI for quick command-line interactions and a web UI for viewing daily schedules, question histories, scores, and detailed feedback.
- **Flexible Execution Modes**: Trigger generation on demand, run via CLI commands, or schedule via cron/system daemon.

---

## 3. Recommended Project Structure
```text
interview_prep_app/
├── config.yaml               # Configuration file
├── requirements.txt          # Python dependencies
├── README.md                 # Setup and execution guide
├── main.py                   # Application entry point
└── app/
    ├── __init__.py
    ├── config.py             # Configuration parsing & validation
    ├── db.py                 # SQLite context manager & schema migrations
    ├── llm.py                # Provider abstraction & prompt response parsing
    ├── services.py           # Core business logic (Question fetching, Validation)
    ├── cli.py                # Command-line interface logic
    ├── web.py                # Flask Web UI server routes
    └── templates/
        ├── base.html         # Main dashboard layout wrapper
        ├── dashboard.html    # Daily overview & status
        ├── question.html     # Question attempt interface
        └── history.html      # Past feedback & performance review

```

---

## 4. Configuration Schema (`config.yaml`)

```yaml
# LLM Configuration
llm:
  # Set 'cloud' or 'local'
  type: "cloud"
  
  # Cloud Configuration (e.g., Mistral API)
  cloud:
    api_url: "[https://api.mistral.ai/v1/chat/completions](https://api.mistral.ai/v1/chat/completions)"
    api_key: "YOUR_MISTRAL_API_KEY"
    model: "mistral-medium"
  
  # Local Configuration (e.g., Ollama)
  local:
    base_url: "http://localhost:11434"
    model: "llama3"

# Database Configuration
database:
  path: "./interview_prep.db"

# Question Categories and Counts
questions:
  categories: ["system_design", "java", "debugging", "outage_handling"]
  daily_counts:
    system_design: 1
    java: 2
    debugging: 2
    outage_handling: 2

# Web UI Configuration
web:
  host: "127.0.0.1"
  port: 5000
  debug: false

```

---

## 5. Database Schema

### Tables

#### `questions`

| Field | Type | Description |
| --- | --- | --- |
| `id` | INTEGER (PRIMARY KEY) | Unique question ID |
| `question_text` | TEXT NOT NULL | The generated question text |
| `category` | TEXT NOT NULL | Category (e.g., "system_design") |
| `date_added` | DATE DEFAULT CURRENT_DATE | When the question was added |
| `is_answered` | BOOLEAN DEFAULT 0 | Whether the question has been completed |
| `model_source` | TEXT | Source model (e.g., "mistral", "ollama") |

#### `answers`

| Field | Type | Description |
| --- | --- | --- |
| `id` | INTEGER (PRIMARY KEY) | Unique answer ID |
| `question_id` | INTEGER (FOREIGN KEY) | Links to `questions.id` |
| `user_answer` | TEXT NOT NULL | User's submitted answer |
| `model_summary` | TEXT | LLM summary of expected answer |
| `date_answered` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | Submission timestamp |
| `is_correct` | BOOLEAN | Whether score met passing threshold |

#### `feedback`

| Field | Type | Description |
| --- | --- | --- |
| `id` | INTEGER (PRIMARY KEY) | Unique feedback ID |
| `answer_id` | INTEGER (FOREIGN KEY) | Links to `answers.id` |
| `feedback_text` | TEXT NOT NULL | Detailed review from LLM |
| `score` | INTEGER NOT NULL | Performance score (0-100) |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | Review creation timestamp |

---

## 6. Implementation Code Snippets

### `app/config.py`

```python
import yaml
from typing import Dict, Any

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Load and parse configuration YAML file."""
    with open(config_path, "r") as file:
        return yaml.safe_load(file)

```

### `app/db.py`

```python
import sqlite3
from contextlib import contextmanager
from typing import Generator

@contextmanager
def get_db(db_path: str = "./interview_prep.db") -> Generator[sqlite3.Connection, None, None]:
    """Context manager for managing database connections and transaction rollbacks."""
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

def init_db(db_path: str = "./interview_prep.db"):
    """Initialize database tables."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT NOT NULL,
                category TEXT NOT NULL,
                date_added DATE DEFAULT CURRENT_DATE,
                is_answered BOOLEAN DEFAULT 0,
                model_source TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                user_answer TEXT NOT NULL,
                model_summary TEXT,
                date_answered TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_correct BOOLEAN,
                FOREIGN KEY (question_id) REFERENCES questions(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                answer_id INTEGER NOT NULL,
                feedback_text TEXT NOT NULL,
                score INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (answer_id) REFERENCES answers(id)
            )
        """)

```

### `app/llm.py`

```python
import json
import re
import requests
from typing import Dict, Any, List

def extract_json(text: str) -> str:
    """Extract JSON string from Markdown code blocks if present."""
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()

def query_llm(llm_config: Dict[str, Any], prompt: str) -> str:
    """Send prompts to local or cloud LLMs."""
    llm_type = llm_config.get("type", "cloud")
    
    if llm_type == "cloud":
        cfg = llm_config["cloud"]
        headers = {"Authorization": f"Bearer {cfg['api_key']}"}
        payload = {
            "model": cfg["model"],
            "messages": [{"role": "user", "content": prompt}]
        }
        res = requests.post(cfg["api_url"], headers=headers, json=payload, timeout=30)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]
        
    elif llm_type == "local":
        cfg = llm_config["local"]
        payload = {"model": cfg["model"], "prompt": prompt, "stream": False}
        res = requests.post(f"{cfg['base_url']}/api/generate", json=payload, timeout=60)
        res.raise_for_status()
        return res.json()["response"]
        
    raise ValueError(f"Invalid LLM type: {llm_type}")

def fetch_questions(llm_config: Dict[str, Any], categories: List[str], counts: Dict[str, int]) -> List[Dict[str, str]]:
    """Fetch structured interview questions from configured LLM."""
    prompt = (
        f"Generate interview questions for an SDE 2 with 6 years experience in Java.\n"
        f"Categories: {categories}. Counts per category: {counts}.\n"
        "Return strictly valid JSON array: [{\"question\": \"...\", \"category\": \"...\"}]"
    )
    raw = query_llm(llm_config, prompt)
    clean = extract_json(raw)
    return json.loads(clean)

def validate_answer(llm_config: Dict[str, Any], question: str, user_answer: str) -> Dict[str, Any]:
    """Validate user answer against LLM summary and score it."""
    prompt = (
        f"Compare this user answer to the ideal answer for the question.\n"
        f"Question: {question}\nUser Answer: {user_answer}\n"
        "Return strictly valid JSON: {\"summary\": \"...\", \"score\": 85, \"feedback\": \"...\"}"
    )
    raw = query_llm(llm_config, prompt)
    clean = extract_json(raw)
    return json.loads(clean)

```

### `app/services.py`

```python
from typing import Dict, Any
from app.db import get_db
from app.llm import fetch_questions, validate_answer

def generate_daily_questions(config: Dict[str, Any]):
    """Fetch new daily questions and save them to the database."""
    llm_cfg = config["llm"]
    categories = config["questions"]["categories"]
    counts = config["questions"]["daily_counts"]
    db_path = config["database"]["path"]

    questions = fetch_questions(llm_cfg, categories, counts)
    
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        for q in questions:
            cursor.execute(
                "INSERT INTO questions (question_text, category, model_source) VALUES (?, ?, ?)",
                (q["question"], q["category"], llm_cfg.get("type", "unknown"))
            )

def process_answer(config: Dict[str, Any], question_id: int, user_answer: str) -> Dict[str, Any]:
    """Validate answer, update question status, store feedback."""
    db_path = config["database"]["path"]
    
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT question_text FROM questions WHERE id = ?", (question_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Question {question_id} not found.")

        validation = validate_answer(config["llm"], row["question_text"], user_answer)
        score = validation.get("score", 0)
        
        cursor.execute(
            "INSERT INTO answers (question_id, user_answer, model_summary, is_correct) VALUES (?, ?, ?, ?)",
            (question_id, user_answer, validation.get("summary", ""), score >= 70)
        )
        answer_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO feedback (answer_id, feedback_text, score) VALUES (?, ?, ?)",
            (answer_id, validation.get("feedback", ""), score)
        )
        
        cursor.execute("UPDATE questions SET is_answered = 1 WHERE id = ?", (question_id,))
        return validation

```

### `app/cli.py`

```python
import sys
from app.config import load_config
from app.db import init_db, get_db
from app.services import generate_daily_questions, process_answer

def main():
    config = load_config()
    db_path = config["database"]["path"]

    if len(sys.argv) < 2:
        print("Usage: python -m app.cli [init-db | generate | list | submit <id> <answer>]")
        return

    cmd = sys.argv[1]
    
    if cmd == "init-db":
        init_db(db_path)
        print("Database initialized successfully.")
        
    elif cmd == "generate":
        print("Fetching questions from LLM...")
        generate_daily_questions(config)
        print("Questions stored successfully.")
        
    elif cmd == "list":
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM questions WHERE is_answered = 0")
            for q in cursor.fetchall():
                print(f"[{q['id']}] [{q['category']}] {q['question_text']}")
                
    elif cmd == "submit":
        if len(sys.argv) < 4:
            print("Usage: python -m app.cli submit <question_id> <answer>")
            return
        q_id = int(sys.argv[2])
        ans = " ".join(sys.argv[3:])
        result = process_answer(config, q_id, ans)
        print(f"\nScore: {result.get('score')}/100")
        print(f"Feedback: {result.get('feedback')}")

if __name__ == "__main__":
    main()

```

---

## 7. Web UI Dashboard System (`app/web.py`)

The Web UI provides a visual dashboard to review today's questions, view historic performance, and submit answers directly through a web browser.

### Web Server Routes (`app/web.py`)

```python
from flask import Flask, render_template, request, redirect, url_for, flash
from app.config import load_config
from app.db import get_db
from app.services import process_answer, generate_daily_questions

app = Flask(__name__)
app.secret_key = "interview_prep_secret_key"
config = load_config()

@app.route("/")
def dashboard():
    """Daily overview showing pending vs completed tasks and daily score stats."""
    db_path = config["database"]["path"]
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        
        # Get today's questions
        cursor.execute("SELECT * FROM questions WHERE date_added = CURRENT_DATE")
        daily_questions = cursor.fetchall()
        
        # Calculate daily performance score average
        cursor.execute("""
            SELECT AVG(f.score) as avg_score, COUNT(a.id) as total_answered
            FROM answers a
            JOIN feedback f ON a.id = f.answer_id
            WHERE DATE(a.date_answered) = CURRENT_DATE
        """)
        stats = cursor.fetchone()
        
    return render_template("dashboard.html", questions=daily_questions, stats=stats)

@app.route("/question/<int:q_id>", methods=["GET", "POST"])
def view_question(q_id):
    """View question details, submit an answer, and display feedback."""
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
        
        # Fetch previous attempt feedback if available
        cursor.execute("""
            SELECT a.user_answer, a.model_summary, f.score, f.feedback_text, f.created_at
            FROM answers a
            JOIN feedback f ON a.id = f.answer_id
            WHERE a.question_id = ?
            ORDER BY a.date_answered DESC LIMIT 1
        """, (q_id,))
        history = cursor.fetchone()

    return render_template("question.html", question=question, history=history, feedback=feedback_data)

@app.route("/generate", methods=["POST"])
def generate():
    """Trigger manual question generation from Web UI."""
    generate_daily_questions(config)
    flash("New daily questions fetched successfully!", "info")
    return redirect(url_for("dashboard"))

@app.route("/history")
def history():
    """Historical archive of all answered questions, scores, and feedback."""
    db_path = config["database"]["path"]
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT q.question_text, q.category, a.user_answer, f.score, f.feedback_text, a.date_answered
            FROM questions q
            JOIN answers a ON q.id = a.question_id
            JOIN feedback f ON a.id = f.answer_id
            ORDER BY a.date_answered DESC
        """)
        records = cursor.fetchall()
    return render_template("history.html", records=records)

def run_web():
    cfg = config.get("web", {})
    app.run(host=cfg.get("host", "127.0.0.1"), port=cfg.get("port", 5000), debug=cfg.get("debug", False))

```

### Dashboard HTML View (`app/templates/dashboard.html`)

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Interview Prep Dashboard</title>
    <link rel="stylesheet" href="[https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css](https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css)">
</head>
<body class="bg-light">
<div class="container py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2>Daily Interview Preparation Dashboard</h2>
        <form action="/generate" method="POST">
            <button class="btn btn-primary">Generate Today's Questions</button>
        </form>
    </div>

    <!-- Daily Progress Cards -->
    <div class="row mb-4">
        <div class="col-md-6">
            <div class="card p-3 shadow-sm">
                <h5>Today's Average Score</h5>
                <h3 class="text-success">{{ "%.1f"|format(stats['avg_score']) if stats['avg_score'] else 'N/A' }} / 100</h3>
            </div>
        </div>
        <div class="col-md-6">
            <div class="card p-3 shadow-sm">
                <h5>Answered Today</h5>
                <h3>{{ stats['total_answered'] or 0 }} Questions</h3>
            </div>
        </div>
    </div>

    <!-- Questions Table -->
    <h4>Today's Questions</h4>
    <table class="table table-bordered bg-white shadow-sm">
        <thead class="table-dark">
            <tr>
                <th>Status</th>
                <th>Category</th>
                <th>Question</th>
                <th>Action</th>
            </tr>
        </thead>
        <tbody>
            {% for q in questions %}
            <tr>
                <td>
                    {% if q['is_answered'] %}
                    <span class="badge bg-success">Completed</span>
                    {% else %}
                    <span class="badge bg-warning text-dark">Pending</span>
                    {% endif %}
                </td>
                <td><span class="badge bg-secondary">{{ q['category'] }}</span></td>
                <td>{{ q['question_text'] }}</td>
                <td>
                    <a href="/question/{{ q['id'] }}" class="btn btn-sm btn-outline-primary">Attempt / View</a>
                </td>
            </tr>
            {% else %}
            <tr><td colspan="4" class="text-center text-muted">No questions for today yet. Click generate above.</td></tr>
            {% endfor %}
        </tbody>
    </table>
    <a href="/history" class="btn btn-link">View Full History & Past Feedback →</a>
</div>
</body>
</html>

```

---

## 8. Summary of Plan Enhancements & Rationale

1. **Modular Package Layout (`app/`)**: Replaced loose root scripts with an `app/` Python package to eliminate duplicate code, clean up dependencies, and make multi-interface support (CLI + Web UI) simple.
2. **Context Managed DB Connections (`app/db.py`)**: Isolated database initialization (`init-db`) from app operations. Connection context managers (`get_db()`) handle implicit commits, transaction rollbacks, and connection closing safely.
3. **Resilient LLM Output Cleaning (`extract_json`)**: Pre-filters raw model responses using regex before calling `json.loads()` to cleanly parse outputs wrapped in markdown snippets (````json ... ````).
4. **Enhanced Schema Design**: Added `is_answered` to `questions` and `created_at` to `feedback` to allow dashboard filtering of pending tasks and track user improvement over time.
5. **Integrated Web UI Suite**: Added Flask-based server routes and dashboard UI views for inspecting daily progress, trying questions, reading score breakdowns, and browsing submission history.

---

## 9. Dependencies (`requirements.txt`)

```text
requests>=2.31.0
PyYAML>=6.0.1
rich>=13.7.0
flask>=3.0.0

```

---

## 10. Usage Instructions

1. **Setup Environment**:
```bash
pip install -r requirements.txt

```


2. **Initialize Database**:
```bash
python -m app.cli init-db

```


3. **Fetch Questions (via CLI or UI)**:
```bash
python -m app.cli generate

```


4. **Launch Web UI**:
Execute via Python module call:
```bash
python -c "from app.web import run_web; run_web()"

```


Navigate to `http://127.0.0.1:5000` in your web browser to view today's schedule, answer questions, and view feedback scores.

```

```
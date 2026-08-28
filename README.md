# Interview Prep App

A configurable Python app that fetches daily interview questions from a local (Ollama) or cloud (OpenAI-compatible) LLM, stores them in SQLite with hash-based deduplication, validates answers, and provides CLI + Web UI with domain and date filtering.

---

## Features

- **Configurable LLM Provider**: Switch `cloud`/`local` via `config.yaml` (Ollama `gemma3:1b`, `llama3.2:latest` or cloud like Agnes/Mistral/NVIDIA).
- **Dynamic Prompt Library**: File-based templates in `app/prompts/generation/` and `app/prompts/evaluation/` loaded via `load_prompt_template()` and populated with `.format()`.
- **Domain Distribution**: Weighted `daily_target` (e.g., `system_design: High`) via largest-remainder in `calculate_domain_distribution()`.
- **Deduplication**: SHA-256 normalized hash (`question_hash` UNIQUE) + recent topics passed to LLM.
- **Filtering**: Web UI domain dropdown + date picker for dashboard/history.

---

## 1. Setup Environment

### Create and activate virtual environment

```bash
# Option A: .venv (recommended in docs)
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Option B: myenv (existing in repo)
python3 -m venv myenv
source myenv/bin/activate
```

### Install dependencies

```bash
pip install -r requirements.txt
# requires: requests>=2.31.0, PyYAML>=6.0.1, rich>=13.7.0, flask>=3.0.0
```

---

## 2. Configuration Setup

A sanitized dummy config is provided as `config.example.yaml` (safe to commit/share). Copy it to `config.yaml` and replace placeholders:

```bash
cp config.example.yaml config.yaml
# then edit config.yaml with your real keys (never commit real keys)
```

Edit `config.yaml`:

```yaml
database:
  path: "./interview_prep.db"

llm:
  type: "cloud"  # or "local"
  cloud:
    api_url: "https://apihub.agnes-ai.com/v1/chat/completions"
    api_key: "YOUR_AGNES_API_KEY"  # <- replace, never commit real key
    model: "agnes-2.0-flash"
  local:
    base_url: "http://127.0.0.1:11434"
    model: "gemma3:1b"
    temperature: 0.3
    max_tokens: 1500
    stream: true

profile:
  role: "SDE 2"
  experience_years: 6
  tech_stack: ["Java", "Spring Boot", "Microservices", "AWS"]

questions:
  daily_target: 10
  domains:
    system_design: "High"
    core_java: "High"
    debugging: "Medium"
    outage_handling: "Low"
  recent_context_limit: 15  # hashes passed to LLM to avoid repeats

prompts:
  active_generation: "faang_style"      # file in app/prompts/generation/
  active_evaluation: "strict_grading"   # file in app/prompts/evaluation/

web:
  host: "127.0.0.1"
  port: 5000
  debug: false
  secret_key: "YOUR_WEB_SECRET_KEY_CHANGE_ME"  # or set env var WEB_SECRET_KEY
  history_limit: 100
```

**Security:** Never commit real API keys. Use placeholder `YOUR_..._API_KEY` and set via env:

```bash
export WEB_SECRET_KEY="strong-random-secret"
export AGNES_API_KEY="sk-..."
# then reference in config or keep placeholder
```

All hardcorded fallbacks have been removed: Flask `secret_key` now reads `WEB_SECRET_KEY`/`FLASK_SECRET_KEY` env var or `config.yaml:web.secret_key`; host/port/debug, database path, and limits all pull from `config.yaml`.

---

## 3. Database

```bash
python main.py init-db
# Creates questions (with question_hash UNIQUE + idx_question_hash), answers, feedback
# Migration auto-adds question_hash and backfills existing rows
```

---

## 4. CLI Usage

```bash
# Generate daily questions (auto-lists pending, deduplicates via hash)
python main.py generate
# or: python -m app.cli generate

# List pending questions
python main.py list

# Submit answer
python main.py submit <question_id> "Your detailed answer"

# Other
python main.py --web        # also supports: python main.py web
python -m app.cli --help
```

**Deduplication:** Second `generate` with same mock Bank will show `Deduplication: inserted 0, skipped 10 duplicates`.

---

## 5. Launch Web UI

```bash
# Via CLI
python main.py --web
# Via module
python -c "from app.web import run_web; run_web()"

# Open http://127.0.0.1:5000
```

**Web Features:**
- Dashboard `/` : Domain filter dropdown (`?domain=core_java`), Date picker (`?date=2026-08-28`), Prev/Next Day navigation, `Generate Today's Questions` button.
- History `/history` : Same filters for answered questions, shows `date_added` and `date_answered`.

Example filtered URLs:
```
http://127.0.0.1:5000/?domain=system_design&date=2026-08-28
http://127.0.0.1:5000/history?domain=debugging&date=2026-08-27
```

---

## 6. Prompt Templates

Add new templates:

```bash
cat > app/prompts/generation/my_style.txt <<'EOF'
Act as {role} mentor for {experience_years} years. Stack: {tech_stack}. Need {category_counts}. Return ONLY valid JSON array: [{"question": "...", "category": "..."}]
EOF

# Activate in config.yaml
# prompts.active_generation: "my_style"
```

Rules documented in `rules for templates.md` and `rules_for_templates.md`: only `{role} {experience_years} {tech_stack} {category_counts}` for generation and `{role} {question} {user_answer}` for evaluation are replaced via JSON-safe `.format()` (double-escaped). Keep literal JSON `{"question": "..."}` single braces.

---

## 7. Testing & Verification

```bash
# Syntax check
python -m py_compile app/*.py

# Load check
python main.py list

# Domain distribution tests (1 to N domains, High/Medium/Low or int weights)
python -c "from app.config import calculate_domain_distribution; print(calculate_domain_distribution({'questions':{'daily_target':10,'domains':{'a':'High','b':'Low'}}}))"

# Prompt loader
python -c "from app.config import load_prompt_template; print(load_prompt_template('generation','faang_style')[:80])"

# Web test client
python -c "from app.web import app; print(app.test_client().get('/').status_code)"
```

---

## 8. Git & Release Notes

`.gitignore` ignores:

```
.venv/ myenv/ venv/ __pycache__/ *.db *.sqlite .env config.yaml.bak
```

Ensure `config.yaml` contains **only placeholders** (`YOUR_AGNES_API_KEY`, `YOUR_WEB_SECRET_KEY_CHANGE_ME`) before committing. Never commit `interview_prep.db` or `.env`.

---

## 9. Project Structure

```
.
├── config.yaml
├── requirements.txt
├── main.py
└── app/
    ├── __init__.py
    ├── cli.py
    ├── config.py
    ├── db.py
    ├── llm.py
    ├── services.py
    ├── web.py
    ├── test.py              # local Ollama streaming example (reference)
    └── prompts/
        ├── generation/faang_style.txt
        └── evaluation/strict_grading.txt
    └── templates/
        ├── base.html
        ├── dashboard.html
        ├── question.html
        └── history.html
```

---

## 10. Troubleshooting

- **LLM 404/401**: Check `api_url` includes `/v1/chat/completions` and `api_key` placeholder replaced or `type: local` with Ollama running `ollama serve` and `ollama pull gemma3:1b`.
- **Empty streaming response**: Increase `llm.local.max_tokens` (1500→2000) and `timeout` in `app/llm.py` (180s).
- **Duplicate questions**: Hash is normalized lowercased/punctuation-stripped SHA-256; second generate will skip.
- **Secret key warning**: Set `WEB_SECRET_KEY` env var for production.


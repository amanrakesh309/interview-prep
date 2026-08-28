# Prompt Template Rules — Interview Prep App

This document records the complete rules for adding and customizing prompt templates in the Interview Prep App. It covers file locations, naming, supported placeholders, formatting behavior, and what can / cannot be added.

---

## 1. Overview

The app uses a **file-based prompt library** (`app/prompts/`) with two types:

- **Generation** (`app/prompts/generation/*.txt`): used by `fetch_questions()` to generate interview questions.
- **Evaluation** (`app/prompts/evaluation/*.txt`): used by `validate_answer()` to grade user answers.

Templates are loaded dynamically via `app/config.py:112` `load_prompt_template(prompt_type, template_name)` and populated via `app/llm.py:88` JSON-safe `.format()` using current `profile`, `tech_stack`, `category_counts`, `question`, and `user_answer`.

Active templates are selected in `config.yaml:32`:

```yaml
prompts:
  active_generation: "faang_style"      # -> app/prompts/generation/faang_style.txt
  active_evaluation: "strict_grading"  # -> app/prompts/evaluation/strict_grading.txt
```

---

## 2. File Location & Naming Rules

### 2.1 Directory Structure

```
app/prompts/
├── generation/
│   ├── faang_style.txt              # Principal Engineer style
│   └── conceptual_warmup.txt        # Foundational warmup
└── evaluation/
    ├── strict_grading.txt           # Rigorous grading
    └── encouraging.txt              # Constructive feedback
```

- `prompt_type` **must** be exactly `generation` or `evaluation`. `load_prompt_template()` builds path `app/prompts/{prompt_type}/{template_name}.txt` via `Path(__file__).parent / "prompts"` with fallback to `Path.cwd() / "app/prompts/..."`. Any other type raises `FileNotFoundError`.

### 2.2 File Naming

- File name: `^[a-z0-9_]+\\.txt$` snake_case, e.g., `my_custom_prompt.txt`.
- In `config.yaml`, reference **without** `.txt`:

  ```yaml
  active_generation: "my_custom_prompt"   # correct
  active_generation: "my_custom_prompt.txt" # also works (code auto-strips), but prefer without
  ```

- You may create **any number** of templates. Unreferenced files are ignored. Referencing a non-existent name crashes at runtime.

### 2.3 File Format

- Single file = single prompt, UTF-8, plain text.
- No subdirectories inside `generation/` or `evaluation/` (e.g., `generation/sub/foo.txt` is not found).
- No binary, no non-UTF8. File is read with `open(..., "r", encoding="utf-8").strip()`.

---

## 3. Supported Placeholders

### 3.1 Generation Templates (`app/prompts/generation/*.txt`)

Current implementations (`app/llm.py:89-99`) support **only** these keys for `.format()`:

| Placeholder | Source | Example Value |
|---|---|---|
| `{role}` | `config.yaml:20` `profile.role` | `SDE 2` |
| `{experience_years}` | `profile.experience_years` | `6` |
| `{tech_stack}` | `profile.tech_stack` list → `", ".join()` | `Java, Spring Boot, Microservices, AWS` |
| `{category_counts}` | `app/config.py:21` `calculate_question_counts()` dict string | `{'system_design': 2, 'java': 2, 'debugging': 2, 'outage_handling': 1}` |
| `{categories}` | List of category names (legacy, available) | `['system_design','java',...]` |
| `{counts}` | Same dict as category_counts (legacy) | same |

**Shipped examples:**

`faang_style.txt:1`
```
Act as a Principal Engineer at a top tech company. Generate interview questions for a {role} with {experience_years} years of experience. Tech Stack: {tech_stack}. Categories and target counts: {category_counts}. Return strictly valid JSON array: [{"question": "...", "category": "..."}]
```

`conceptual_warmup.txt:1`
```
Generate foundational interview questions for a {role}. Tech Stack: {tech_stack}. Categories and target counts: {category_counts}. Return strictly valid JSON array: [{"question": "...", "category": "..."}]
```

### 3.2 Evaluation Templates (`app/prompts/evaluation/*.txt`)

Only (`app/llm.py:145-149`):

| Placeholder | Source | Example |
|---|---|---|
| `{role}` | `profile.role` | `SDE 2` |
| `{question}` | `questions.question_text` from DB | `Design a URL shortener...` |
| `{user_answer}` | CLI `submit <id> <answer>` | `I would use hashing...` |

**Shipped examples:**

`strict_grading.txt:1`
```
Evaluate this answer rigorously for a {role} position. Question: {question}
User Answer: {user_answer}
Grade strictly on edge cases and depth. Return strictly valid JSON: {"summary": "...", "score": 85, "feedback": "..."}
```

`encouraging.txt:1`
```
Provide constructive feedback for a {role} candidate. Question: {question}
User Answer: {user_answer}
Return strictly valid JSON: {"summary": "...", "score": 85, "feedback": "..."}
```

---

## 4. How to Add a New Prompt (Step-by-Step)

### 4.1 Add a Generation Prompt

1. Create file:

   ```bash
   cat > app/prompts/generation/interview_warmup.txt <<'EOF'
   Act as a {role} mentor for {experience_years} years. Stack: {tech_stack}. Need {category_counts}. Return strictly valid JSON array: [{"question": "...", "category": "..."}]
   EOF
   ```

2. Activate in `config.yaml:32`:

   ```yaml
   prompts:
     active_generation: "interview_warmup"
     active_evaluation: "strict_grading"
   ```

3. Verify:

   ```bash
   .venv/bin/python -c "from app.config import load_prompt_template; print(load_prompt_template('generation','interview_warmup'))"
   .venv/bin/python main.py generate
   .venv/bin/python main.py list
   ```

### 4.2 Add an Evaluation Prompt

1. Create file:

   ```bash
   cat > app/prompts/evaluation/detailed.txt <<'EOF'
   You are grading a {role} candidate. Question: {question} Answer: {user_answer} Provide depth, edge cases. Return strictly valid JSON: {"summary": "...", "score": 85, "feedback": "..."}
   EOF
   ```

2. Activate:

   ```yaml
   prompts:
     active_generation: "faang_style"
     active_evaluation: "detailed"
   ```

3. Test:

   ```bash
   .venv/bin/python main.py submit 1 "my answer"
   ```

No code change required for these steps.

---

## 5. What CAN Be Added

- **Any template prose** as long as it uses only supported placeholders and keeps literal JSON braces as `{"key": "..."}`.
- **Any number** of templates per type; only active one is used.
- **Any `profile` values**: change `role`, `experience_years`, or add entries to `tech_stack` list freely - they flow via `.format()`.
- **Any `questions` categories**: add `custom_domain: "High"` to `config.yaml:27` - weight auto-distributes via `WEIGHT_MAP` (`app/config.py:8`).
- **Any `daily_target` integer**: total questions per generate (e.g., `7`, `10`).
- **New weight labels**: if you add `Critical`, add entry to `WEIGHT_MAP` in `app/config.py:8`:

  ```python
  WEIGHT_MAP = {"High":3, "Medium":2, "Low":1, "Critical":4}
  ```

---

## 6. What CANNOT Be Added (and Why)

### 6.1 Unsupported Placeholders

Adding `{company}` or `{difficulty}` without code change **will not be replaced** - it renders literally `{company}`. The formatter in `app/llm.py:94` does:

```python
escaped = template.replace("{","{{").replace("}","}}")
for key in ["role","experience_years","tech_stack","category_counts","categories","counts"]:
    escaped = escaped.replace("{{"+key+"}}", "{"+key+"}")
prompt = escaped.format(role=..., experience_years=..., tech_stack=..., category_counts=..., ...)
```

Unknown keys remain as `{{company}}` -> after `.format()` becomes literal `{company}`. To support a new key, add it to the whitelist and supply a value in `app/llm.py:89` (generation) or `app/llm.py:145` (evaluation).

### 6.2 Format Specifiers & Nested Braces

- No `{role!r}`, `{experience_years:.2f}`, `{tech_stack:>10}` - format spec after `:` is not supported by current safe logic and will be escaped incorrectly.
- No nested `{{role}}` intentional escaping - will be double-unescaped to `{role}` then formatted, producing unexpected results.
- No positional `{}` or numbered `{0}` - whitelist expects named keys only.

### 6.3 Breaking JSON Structure

- Do not change JSON literal to `[{question: ...}]` without quotes - parser `re.search` + `json.loads` in `app/llm.py:6` expects valid JSON with quoted keys. The template must keep `[{"question": "...", "category": "..."}]` exactly (single braces, quoted keys). The code double-escapes JSON braces to preserve them as literals after `.format()` - altering them breaks the mock fallback and LLM parsing.

### 6.4 File System Violations

- Subdirectories, binary files, or non-`.txt` extensions are not loaded.
- Non-UTF8 will raise decode error.
- Templates of type other than `generation`/`evaluation` are not discoverable.

---

## 7. Technical Detail: Why `.format()` Needs JSON-Safe Escaping

Naive `template.format(role=...)` would treat `{"question": "..."}` as a format field `{ "question": "..."}` and raise `ValueError: Invalid format specifier`. The implementation (`app/llm.py:94-98`) therefore:

1. Escapes all braces: `template.replace("{","{{").replace("}","}}")`
2. Reverts only known placeholders: `replace("{{role}}","{role}")`
3. Calls `.format()` - JSON braces stay as `{{"question": ...}}` -> after format become literal `{"question": ...}`.

This is why templates **must** use single braces for JSON and only whitelisted placeholders for dynamic values.

---

## 8. Domains vs Tech Stack — Avoiding Confusion

The most common confusion is `profile.tech_stack` vs `questions.domains` (formerly `questions.categories`).

| Config Path | Meaning | Example | Used As |
|---|---|---|---|
| `profile.tech_stack` `config.yaml:25` | **WHAT you know** - candidate's skills | `["Java","Spring Boot","AWS"]` | Prompt variable `{tech_stack}` → `", ".join()` informs LLM *context/style* |
| `questions.domains` `config.yaml:30` | **WHAT you test** - interview focus areas | `system_design: High, core_java: High, debugging: Medium, outage_handling: Low` | Prompt variable `{category_counts}` → weighted distribution via `calculate_question_counts()` |

**Rules to keep them distinct:**

1. **Never use exact same string** for a tech_stack entry and a domain name (case-insensitive). `tech_stack` contains `Java` while domain `java` was ambiguous - renamed to `core_java` to make distinction explicit. `app/config.py:29` now warns if overlap detected: `tech_stack entries {'java'} exactly match domain names`.

2. **Domains drive counts, tech_stack drives context:**
   - `questions.domains` + `daily_target` → `app/config.py:48` calculates e.g., `daily_target:10` with `High:3, Medium:2, Low:1` → `{'system_design':3,'core_java':3,'debugging':2,'outage_handling':2}`.
   - `profile.tech_stack` does **not** affect distribution, only prompt text.

3. **Naming convention:**
   - `tech_stack` entries: TitleCase proper names `Java`, `Spring Boot`
   - `domains` keys: snake_case interview areas `system_design`, `core_java`, `debugging`, `outage_handling` - avoid pure tech names; prefer `core_java` over `java`, `language_fundamentals` over `python`.

4. **Backward compatibility:** `app/config.py:21` `_get_domains_config()` prefers `domains` over legacy `categories`. You may still use `questions.categories` but `domains` is preferred. `mock_bank` in `app/llm.py:35` aliases `core_java ↔ java` so both work.

5. **Validation checklist for domains/tech_stack:**
   - [ ] No domain equals a tech_stack entry (case-insensitive) - rename domain if needed
   - [ ] Domain names use `snake_case`, tech_stack uses display names
   - [ ] `daily_target` ≥ number of domains (ensures at least 1 per domain, see `app/config.py:120`)

Example **correct**:
```yaml
profile:
  tech_stack: ["Java", "Spring Boot", "Microservices", "AWS"]
questions:
  daily_target: 10
  domains:
    system_design: "High"
    core_java: "High"
    debugging: "Medium"
    outage_handling: "Low"
```

Example **confusing (avoid)**:
```yaml
profile:
  tech_stack: ["Java"]
questions:
  categories:
    java: "High"   # ambiguous - is this skill or test area?
```

---

## 9. Quick Reference Checklist

Before adding a prompt, verify:

- [ ] File lives in `app/prompts/generation/` or `app/prompts/evaluation/`
- [ ] Snake_case name, `.txt` extension
- [ ] Uses only allowed placeholders for its type
- [ ] Keeps JSON `[{"question": ...}]` or `{"summary": ...}` literal
- [ ] Activated via `config.yaml:37` `active_generation` / `active_evaluation`
- [ ] Tested with `.venv/bin/python main.py generate` (or `submit`)
- [ ] `profile.tech_stack` (WHAT you know) and `questions.domains` (WHAT you test) are distinct - no exact overlap


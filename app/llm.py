"""LLM provider abstraction and prompt handling."""

import json
import re
from typing import Any, Dict, List

import requests


def extract_json(text: str) -> str:
    """Extract JSON string from Markdown code blocks or raw text.

    Sanitizes smart quotes and falls back to searching for JSON arrays/objects.
    """
    sanitized = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", sanitized, re.DOTALL)
    if match:
        return match.group(1).strip()
    array_match = re.search(r"(\[.*\])", sanitized, re.DOTALL)
    if array_match:
        candidate = array_match.group(1).strip()
        if '"question"' in candidate or '"category"' in candidate:
            return candidate
    obj_match = re.search(r"(\{.*\})", sanitized, re.DOTALL)
    if obj_match:
        candidate = obj_match.group(1).strip()
        if '"score"' in candidate or '"summary"' in candidate:
            return candidate
    return sanitized.strip()


def _normalize_validation_result(
    data: Dict[str, Any], question: str, user_answer: str
) -> Dict[str, Any]:
    """Ensure validation result has correct types: summary str, score int, feedback str."""
    if isinstance(data, list) and data:
        data = data[0] if isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        data = {}
    summary = data.get("summary", "")
    score = data.get("score", 0)
    feedback = data.get("feedback", "")

    if isinstance(feedback, (dict, list)):
        feedback = json.dumps(feedback, indent=2)
    elif not isinstance(feedback, str):
        feedback = str(feedback)
    if isinstance(summary, (dict, list)):
        summary = json.dumps(summary, indent=2)
    elif not isinstance(summary, str):
        summary = str(summary)

    try:
        score = int(score)
    except (ValueError, TypeError):
        m = re.search(r"(\d{1,3})", str(score))
        score = int(m.group(1)) if m else 0
    score = max(0, min(100, score))

    if not summary:
        summary = f"Summary for: {question[:60]}..."
    if not feedback:
        feedback = "No detailed feedback provided."
    return {"summary": summary, "score": score, "feedback": feedback}


def query_llm(llm_config: Dict[str, Any], prompt: str) -> str:
    """Send prompt to configured LLM (cloud or local Ollama).

    Cloud uses OpenAI-compatible chat completions.
    Local uses Ollama ``/api/generate`` with streaming support as in ``app/test.py``.

    Args:
        llm_config: LLM configuration from ``config.yaml``.
        prompt: Formatted prompt string.

    Returns:
        Raw LLM response text.

    Raises:
        ValueError: If ``llm.type`` is invalid.
    """
    llm_type = llm_config.get("type", "cloud")

    if llm_type == "cloud":
        cfg = llm_config["cloud"]
        headers = {"Authorization": f"Bearer {cfg['api_key']}"}
        payload = {
            "model": cfg["model"],
            "messages": [{"role": "user", "content": prompt}],
        }
        res = requests.post(cfg["api_url"], headers=headers, json=payload, timeout=30)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]

    if llm_type == "local":
        cfg = llm_config["local"]
        base_url = cfg.get("base_url", "http://127.0.0.1:11434").rstrip("/")
        model = cfg.get("model", "gemma3:1b")
        temperature = cfg.get("temperature", 0.3)
        max_tokens = cfg.get("max_tokens", 1500)
        stream = cfg.get("stream", True)
        url = f"{base_url}/api/generate"

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if stream:
            full_response = ""
            with requests.post(url, json=payload, stream=True, timeout=180) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    chunk = data.get("response", "")
                    if chunk:
                        full_response += chunk
                    if data.get("done"):
                        break
            if not full_response:
                raise RuntimeError("Ollama returned empty response (streaming)")
            return full_response

        payload_non_stream: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if "temperature" in cfg or temperature != 0.3:
            payload_non_stream["temperature"] = temperature
        if max_tokens is not None:
            payload_non_stream["max_tokens"] = max_tokens
        res = requests.post(url, json=payload_non_stream, timeout=180)
        res.raise_for_status()
        data = res.json()
        if "response" in data:
            return data["response"]
        return json.dumps(data)

    raise ValueError(f"Invalid LLM type: {llm_type}")


def _mock_questions(categories: List[str], counts: Dict[str, int]) -> List[Dict[str, str]]:
    """Generate deterministic mock questions for offline/testing use."""
    mock_bank = {
        "system_design": [
            "Design a URL shortening service like TinyURL. Discuss scalability and data storage.",
            "Design a rate limiter for a distributed system. How would you handle burst traffic?",
            "Explain how you would design a notification system supporting email, SMS, and push.",
        ],
        "java": [
            "Explain the difference between HashMap and ConcurrentHashMap in Java. When would you use each?",
            "What is the Java Memory Model? Explain volatile and synchronized with examples.",
            "How does garbage collection work in Java? Compare G1 and ZGC.",
            "Explain CompletableFuture and how it improves asynchronous programming in Java.",
        ],
        "debugging": [
            "Your Java microservice shows intermittent latency spikes. How do you debug and isolate the root cause?",
            "A production service is throwing OutOfMemoryError. Describe your debugging steps.",
            "How would you debug a deadlock in a multi-threaded Java application?",
        ],
        "outage_handling": [
            "Your payment service is down during peak traffic. Walk through your incident response steps.",
            "How do you handle a database primary failover without losing data?",
            "Describe your strategy for handling a cascading failure in microservices.",
        ],
        "core_java": [
            "Explain the difference between HashMap and ConcurrentHashMap in Java. When would you use each?",
            "What is the Java Memory Model? Explain volatile and synchronized with examples.",
            "How does garbage collection work in Java? Compare G1 and ZGC.",
            "Explain CompletableFuture and how it improves asynchronous programming in Java.",
        ],
    }
    if "core_java" not in mock_bank and "java" in mock_bank:
        mock_bank["core_java"] = mock_bank["java"]
    if "java" not in mock_bank and "core_java" in mock_bank:
        mock_bank["java"] = mock_bank["core_java"]

    result: List[Dict[str, str]] = []
    for cat in categories:
        count = counts.get(cat, 1)
        bank = mock_bank.get(cat)
        if bank is None:
            alias_map = {"core_java": "java", "java": "core_java"}
            bank = mock_bank.get(alias_map.get(cat, cat), [f"Sample question for {cat}"])
        for i in range(count):
            q_text = bank[i % len(bank)]
            result.append({"question": q_text, "category": cat})
    return result


def fetch_questions(
    llm_config: Dict[str, Any],
    categories: List[str],
    counts: Dict[str, int],
    config: Dict[str, Any] = None,
    recent_topics: List[str] = None,
) -> List[Dict[str, str]]:
    """Fetch structured interview questions using dynamic prompt templates."""
    prompt = None
    try:
        if config is None:
            try:
                from app.config import load_config

                config = load_config()
            except Exception:
                config = None

        if config and "profile" in config and "prompts" in config:
            from app.config import load_prompt_template

            prompts_cfg = config.get("prompts", {})
            profile = config.get("profile", {})
            active_gen = prompts_cfg.get("active_generation", "faang_style")
            template = load_prompt_template("generation", active_gen)
            role = profile.get("role", "SDE 2")
            experience_years = profile.get("experience_years", 6)
            tech_stack_list = profile.get("tech_stack", ["Java"])
            tech_stack = (
                ", ".join(tech_stack_list)
                if isinstance(tech_stack_list, list)
                else str(tech_stack_list)
            )
            category_counts = str(counts)
            escaped = template.replace("{", "{{").replace("}", "}}")
            for key in ["role", "experience_years", "tech_stack", "category_counts", "categories", "counts"]:
                escaped = escaped.replace("{{" + key + "}}", "{" + key + "}")
            prompt = escaped.format(
                role=role,
                experience_years=experience_years,
                tech_stack=tech_stack,
                category_counts=category_counts,
                categories=categories,
                counts=counts,
            )
            ctx_topics = recent_topics
            if ctx_topics is None and isinstance(config, dict):
                ctx_topics = config.get("_recent_topics") or config.get("recent_topics")
            if ctx_topics:
                recent_str = "\n".join(f"- {t[:150]}" for t in ctx_topics[:12])
                prompt += f"\n\nAvoid repeating these existing questions/topics (generate distinct new ones):\n{recent_str}"
    except Exception as exc:
        print(f"Warning: dynamic prompt loading failed ({exc}), falling back to hardcoded prompt.")
        prompt = None

    if not prompt:
        prompt = (
            f"Generate interview questions for an SDE 2 with 6 years experience in Java.\n"
            f"Categories: {categories}. Counts per category: {counts}.\n"
            'Return strictly valid JSON array: [{"question": "...", "category": "..."}]'
        )
        if recent_topics:
            recent_str = "\n".join(f"- {t[:150]}" for t in recent_topics[:12])
            prompt += f"\nAvoid these: {recent_str}"

    try:
        raw = query_llm(llm_config, prompt)
        clean = extract_json(raw)
        validated: List[Dict[str, str]] = []
        try:
            data = json.loads(clean)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                if isinstance(item, dict) and "question" in item and "category" in item:
                    validated.append(
                        {"question": str(item["question"]), "category": str(item["category"])}
                    )
                elif isinstance(item, dict) and "question" in item:
                    validated.append(
                        {
                            "question": str(item["question"]),
                            "category": categories[0] if categories else "general",
                        }
                    )
            if validated:
                return validated
            raise ValueError("No valid questions extracted")
        except json.JSONDecodeError as je:
            object_pattern = r'\{\s*\"question\"\s*:\s*\".*?\"\s*,\s*\"category\"\s*:\s*\".*?\"\s*\}'
            object_pattern_alt = r'\{\s*\"category\"\s*:\s*\".*?\"\s*,\s*\"question\"\s*:\s*\".*?\"\s*\}'
            candidates = re.findall(object_pattern, clean, re.DOTALL)
            candidates += re.findall(object_pattern_alt, clean, re.DOTALL)
            if not candidates:
                candidates = re.findall(object_pattern, raw, re.DOTALL)
                candidates += re.findall(object_pattern_alt, raw, re.DOTALL)
            for obj_str in candidates:
                try:
                    obj_str_clean = obj_str.replace("“", '"').replace("”", '"')
                    item = json.loads(obj_str_clean)
                    if "question" in item and "category" in item:
                        validated.append(
                            {"question": str(item["question"]), "category": str(item["category"])}
                        )
                except Exception:
                    continue
            if validated:
                return validated
            m = re.search(r"\[.*\]", clean, re.DOTALL)
            if m:
                try:
                    repaired = m.group(0).replace("][", ",").replace("] [", ",").replace("]\n[", ",")
                    data = json.loads(repaired)
                    for item in data:
                        if isinstance(item, dict) and "question" in item:
                            validated.append(
                                {
                                    "question": str(item["question"]),
                                    "category": str(
                                        item.get("category", categories[0] if categories else "general")
                                    ),
                                }
                            )
                    if validated:
                        return validated
                except Exception:
                    pass
            raise je
        if not validated:
            raise ValueError("No valid questions extracted from LLM response")
        return validated
    except Exception as exc:
        print(f"Warning: LLM request failed ({exc}), using mock questions.")
        return _mock_questions(categories, counts)


def validate_answer(
    llm_config: Dict[str, Any], question: str, user_answer: str, config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Validate user answer against LLM summary and score it."""
    prompt = None
    try:
        if config is None:
            try:
                from app.config import load_config

                config = load_config()
            except Exception:
                config = None

        if config and "profile" in config and "prompts" in config:
            from app.config import load_prompt_template

            prompts_cfg = config.get("prompts", {})
            profile = config.get("profile", {})
            active_eval = prompts_cfg.get("active_evaluation", "strict_grading")
            template = load_prompt_template("evaluation", active_eval)
            role = profile.get("role", "SDE 2")
            escaped = template.replace("{", "{{").replace("}", "}}")
            for key in ["role", "question", "user_answer"]:
                escaped = escaped.replace("{{" + key + "}}", "{" + key + "}")
            prompt = escaped.format(role=role, question=question, user_answer=user_answer)
    except Exception as exc:
        print(f"Warning: dynamic evaluation prompt loading failed ({exc}), falling back.")
        prompt = None

    if not prompt:
        prompt = (
            f"Compare this user answer to the ideal answer for the question.\n"
            f"Question: {question}\nUser Answer: {user_answer}\n"
            'Return strictly valid JSON: {"summary": "...", "score": 85, "feedback": "..."}'
        )
    try:
        raw = query_llm(llm_config, prompt)
        clean = extract_json(raw)
        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            obj_match = re.search(r"\{[^}]*\"score\"[^}]*\}", clean, re.DOTALL)
            if obj_match:
                try:
                    data = json.loads(obj_match.group(0))
                except Exception:
                    score_m = re.search(r"Score\s*[:\-]?\s*(\d{1,3})", raw, re.IGNORECASE)
                    score_val = int(score_m.group(1)) if score_m else (75 if len(user_answer.strip()) > 20 else 45)
                    feedback_text = raw[:2000].strip()
                    return _normalize_validation_result(
                        {"summary": raw[:300], "score": score_val, "feedback": feedback_text},
                        question,
                        user_answer,
                    )
            else:
                score_m = re.search(r"Score\s*[:\-]?\s*(\d{1,3})", raw, re.IGNORECASE)
                if score_m:
                    score_val = int(score_m.group(1))
                    return _normalize_validation_result(
                        {"summary": raw[:300], "score": score_val, "feedback": raw[:1500]},
                        question,
                        user_answer,
                    )
                raise
        return _normalize_validation_result(data, question, user_answer)
    except Exception as exc:
        print(f"Warning: LLM validation failed ({exc}), using mock scoring.")
        score = 75 if len(user_answer.strip()) > 20 else 45
        return {
            "summary": f"Mock summary for: {question[:60]}...",
            "score": score,
            "feedback": (
                "Mock feedback: Your answer was evaluated offline. Provide more depth for higher score."
                if score < 70
                else "Mock feedback: Good coverage of key points. Consider adding examples."
            ),
        }

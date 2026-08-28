"""Configuration loading and domain distribution logic."""

from pathlib import Path
from typing import Any, Dict

import yaml

# Weight mapping for category priority (configurable via questions.domains weights)
WEIGHT_MAP = {
    "High": 3,
    "Medium": 2,
    "Low": 1,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Load and parse configuration YAML file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Parsed configuration dictionary.
    """
    with open(config_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def _get_domains_config(questions_cfg: Dict[str, Any]) -> Dict[str, Any] | None:
    """Return domains/categories dict, preferring 'domains' over legacy 'categories'."""
    if "domains" in questions_cfg:
        return questions_cfg["domains"]
    if "categories" in questions_cfg:
        return questions_cfg["categories"]
    return None


def _warn_overlap_if_needed(config: Dict[str, Any]) -> None:
    """Warn if tech_stack entries overlap with domain names (case-insensitive)."""
    try:
        tech_stack = [t.lower() for t in config.get("profile", {}).get("tech_stack", [])]
        domains = _get_domains_config(config.get("questions", {})) or {}
        if isinstance(domains, dict):
            domain_names = [d.lower() for d in domains.keys()]
            overlap = set(tech_stack) & set(domain_names)
            if overlap:
                import warnings

                warnings.warn(
                    f"tech_stack entries {overlap} exactly match domain names. "
                    "Consider renaming domain to be distinct (e.g., 'java' -> 'core_java') "
                    "to avoid confusion: tech_stack=WHAT you know, domains=WHAT you test."
                )
    except Exception:
        pass


def calculate_domain_distribution(config: dict) -> dict[str, int]:
    """Calculate proportional integer question counts for each domain.

    - Reads arbitrary domain keys under ``questions.domains`` (fallback to legacy
      ``questions.categories``). Does NOT hardcode expected domain names.
    - Supports list sizes from 1 to N domains.
    - Maps weight strings (High->3, Medium->2, Low->1) or direct integers.
    - Uses largest remainder method so sum equals ``daily_target``.

    Args:
        config: Full application configuration dictionary.

    Returns:
        Mapping of domain -> integer count, sum equals daily_target.
    """
    questions_cfg = config.get("questions", {})

    # Legacy fallback: daily_counts without daily_target
    if "daily_counts" in questions_cfg and "daily_target" not in questions_cfg:
        return questions_cfg["daily_counts"]

    _warn_overlap_if_needed(config)

    # Prefer domains, fallback to categories (dynamic discovery)
    domains_cfg = _get_domains_config(questions_cfg)
    if "daily_target" in questions_cfg and domains_cfg is not None:
        daily_target = questions_cfg["daily_target"]
        categories = domains_cfg

        # Legacy list: distribute equally
        if isinstance(categories, list):
            count_per = daily_target // len(categories)
            remainder = daily_target % len(categories)
            result: Dict[str, int] = {}
            for i, cat in enumerate(categories):
                result[cat] = count_per + (1 if i < remainder else 0)
            return result

        # Dict: {domain: weight}
        if isinstance(categories, dict):
            numeric_weights: Dict[str, int] = {}
            for cat, weight in categories.items():
                if isinstance(weight, int):
                    numeric_weights[cat] = weight
                elif isinstance(weight, str):
                    numeric_weights[cat] = WEIGHT_MAP.get(weight, 1)
                else:
                    numeric_weights[cat] = 1

            total_weight = sum(numeric_weights.values())
            if total_weight == 0:
                total_weight = len(numeric_weights)

            counts: Dict[str, int] = {}
            remainders: Dict[str, float] = {}
            allocated = 0
            for cat, w in numeric_weights.items():
                raw = (w / total_weight) * daily_target
                floor = int(raw)
                counts[cat] = floor
                remainders[cat] = raw - floor
                allocated += floor

            remaining = daily_target - allocated
            sorted_cats = sorted(
                numeric_weights.keys(),
                key=lambda c: (remainders[c], numeric_weights[c]),
                reverse=True,
            )
            for i in range(remaining):
                cat = sorted_cats[i % len(sorted_cats)]
                counts[cat] += 1

            if daily_target >= len(counts):
                for cat in counts:
                    if counts[cat] == 0:
                        counts[cat] = 1
                        max_cat = max(counts, key=lambda k: counts[k])
                        if max_cat != cat and counts[max_cat] > 1:
                            counts[max_cat] -= 1

            return counts

    # Fallback without daily_target
    domains_fallback = _get_domains_config(questions_cfg)
    if isinstance(domains_fallback, dict):
        daily_target = questions_cfg.get("daily_target", 7)
        return calculate_domain_distribution(
            {"questions": {"daily_target": daily_target, "domains": domains_fallback}}
        )

    return {}


def calculate_question_counts(config: Dict[str, Any]) -> Dict[str, int]:
    """Backward compat alias for calculate_domain_distribution."""
    return calculate_domain_distribution(config)


def get_category_counts(config: Dict[str, Any]) -> Dict[str, int]:
    """Alias for calculate_domain_distribution."""
    return calculate_domain_distribution(config)


def get_domain_distribution(config: Dict[str, Any]) -> Dict[str, int]:
    """Alias for calculate_domain_distribution."""
    return calculate_domain_distribution(config)


def load_prompt_template(prompt_type: str, template_name: str) -> str:
    """Load prompt template from ``app/prompts/{prompt_type}/{template_name}.txt``.

    Args:
        prompt_type: ``generation`` or ``evaluation``.
        template_name: Template name without ``.txt`` suffix.

    Raises:
        FileNotFoundError: If the template file does not exist.

    Returns:
        Raw template text content.
    """
    base_dir = Path(__file__).parent
    prompt_type = prompt_type.strip("/")

    if not template_name.endswith(".txt"):
        template_name = f"{template_name}.txt"

    template_path = base_dir / "prompts" / prompt_type / template_name

    if not template_path.exists():
        alt_path = Path.cwd() / "app" / "prompts" / prompt_type / template_name
        if alt_path.exists():
            template_path = alt_path
        else:
            raise FileNotFoundError(
                f"Prompt template not found: {template_path} (also tried {alt_path})"
            )

    with open(template_path, "r", encoding="utf-8") as f:
        return f.read().strip()

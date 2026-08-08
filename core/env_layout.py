from __future__ import annotations

from collections import OrderedDict


OBSOLETE_KEYS = {
    "VISION_GEMINI_API_KEY",
    "VISION_GEMINI_BASE_URL",
    "VISION_GEMINI_MODEL",
    "VISION_GEMINI_ENDPOINTS",
    "AMAZON_FACTORY_VISUAL_PLANNER_GEMINI_ENDPOINTS",
    "AMAZON_FACTORY_VISUAL_OBSERVER_GEMINI_ENDPOINTS",
    "VISION_GEMINI_INCLUDE_OPTIONAL_CLIENTS",
    "VIP123_API_KEY",
    "VIP123_BEARER_TOKEN",
    "VIP123_GEMINI_MODEL",
    "XIAOMI_API_KEY",
    "XIAOMI_BEARER_TOKEN",
    "XIAOMI_GEMINI_MODEL",
    "AMAZON_FACTORY_QA_MAX_MODELS",
    "AMAZON_FACTORY_QA_ATTEMPTS",
    "AMAZON_FACTORY_QA_RERUN_CYCLES",
    "AMAZON_FACTORY_QA_REUSE_ACCEPTED",
    "AMAZON_FACTORY_QA_STREAMING_RERUN",
    "AMAZON_FACTORY_QA_REUSE_NON_ERROR",
    "AMAZON_FACTORY_QA_RERUN_STOP_LOSS_REPEATS",
    "AMAZON_FACTORY_STRICT_OCR",
    "AMAZON_FACTORY_QA_REVIEW_MODE",
    "AMAZON_FACTORY_QA_REVIEW_ATTEMPTS",
    "AMAZON_FACTORY_QA_REVIEW_TIMEOUT_SECONDS",
    "AMAZON_FACTORY_QA_REVIEW_MAX_MODELS",
    "AMAZON_FACTORY_IMAGEGEN_PROVIDER",
    "AMAZON_FACTORY_IMAGEGEN_PROVIDERS",
    "AMAZON_FACTORY_IMAGEGEN_PROVIDER_STRATEGY",
    "AMAZON_FACTORY_IMAGEGEN_APPEND_CONFIG_PROVIDERS",
    "AMAZON_FACTORY_IMAGEGEN_HEDGE_SECONDS",
    "AMAZON_FACTORY_TEXT_GRAPHIC_PROVIDERS",
    "GEMINI_API_KEY",
    "MODEL_PULS_API_KEY",
    "NEWTOKEN_API_KEY",
}


GROUPS: list[tuple[str, list[str]]] = [
    ("Runtime", ["AMAZON_FACTORY_PYTHON", "AMAZON_FACTORY_COUNTRY_OF_ORIGIN", "DEFAULT_COUNTRY_OF_ORIGIN"]),
    ("Source fetch", ["APIFY_TOKENS", "APIFY_TOKEN", "APIFY_ACTOR_ID", "AMAZON_MARKETPLACE"]),
    ("Copy models", ["DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "COPY_AI_ENABLED", "COPY_AI_KEY_ENV", "COPY_AI_BASE_URL", "COPY_AI_MODEL", "COPY_AI_TIMEOUT", "AMAZON_FACTORY_COPY_POLISH"]),
    ("Vision models", ["HOLDAI_API_KEY", "YUNWU_API_KEY", "NAMAX_API_KEY", "CCAPI_API_KEY", "CCSUB_API_KEY", "CCSUB_BASE_URL", "SUBROUTER_BASE_URL", "QUQIAI_API_KEY", "AMAZON_FACTORY_QA_WORKERS", "AMAZON_FACTORY_QA_TIMEOUT_SECONDS"]),
    ("Image generation", ["KRILL_AI_API_KEY", "AICOST_API_KEY", "CAVOTI_API_KEY", "AMAZON_FACTORY_IMAGEGEN_PROVIDER_ATTEMPTS", "AMAZON_FACTORY_IMAGEGEN_RETRY_DELAY_SECONDS"]),
    ("Image provider timeouts / concurrency", ["AMAZON_FACTORY_PROVIDER_TIMEOUT_SECONDS_KRILL_GPT_IMAGE_2", "AMAZON_FACTORY_PROVIDER_TIMEOUT_SECONDS_CAVOTI_GPT_IMAGE_2", "AMAZON_FACTORY_PROVIDER_CONCURRENCY_KRILL_GPT_IMAGE_2", "AMAZON_FACTORY_PROVIDER_CONCURRENCY_CAVOTI_GPT_IMAGE_2"]),
    ("OCR", ["PADDLEOCR_ENABLED", "PADDLEOCR_API_TOKEN", "PADDLEOCR_API_URL", "PADDLEOCR_MODEL", "PADDLEOCR_TIMEOUT", "PADDLEOCR_POLL_INTERVAL"]),
    ("R2 publish", ["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET", "R2_PUBLIC_BASE_URL", "R2_REGION"]),
    ("Search terms", ["AMAZON_FACTORY_SEARCH_TERMS_ENABLED", "AMAZON_FACTORY_SEARCH_TERMS_DB", "AMAZON_FACTORY_SEARCH_TERMS_LIMIT"]),
]


def normalize_env_text(raw: str) -> str:
    values = _parse_values(raw)
    emitted: set[str] = set()
    lines: list[str] = []
    for title, keys in GROUPS:
        group_lines = [f"{key}={values[key]}" for key in keys if key in values and key not in OBSOLETE_KEYS]
        if not group_lines:
            continue
        if lines:
            lines.append("")
        lines.append(f"# {title}")
        lines.extend(group_lines)
        emitted.update(key.split("=", 1)[0] for key in group_lines)
    unknown = [
        f"{key}={value}"
        for key, value in values.items()
        if key not in emitted and key not in OBSOLETE_KEYS
    ]
    if unknown:
        if lines:
            lines.append("")
        lines.append("# Other retained settings")
        lines.extend(unknown)
    return "\n".join(lines).rstrip() + "\n"


def removed_obsolete_keys(raw: str) -> list[str]:
    values = _parse_values(raw)
    return [key for key in values if key in OBSOLETE_KEYS]


def _parse_values(raw: str) -> OrderedDict[str, str]:
    values: OrderedDict[str, str] = OrderedDict()
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values

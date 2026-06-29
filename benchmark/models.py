"""Model presets and pricing used by benchmark runners."""

ORIGINAL_MODELS = [
    "minimax/minimax-m3",
    "deepseek/deepseek-v4-flash",
    "z-ai/glm-4.7",
]

NEW_MODELS = [
    "qwen/qwen3.7-plus",
    "google/gemini-3.1-flash-lite",
    "qwen/qwen3-coder-next",
    "tencent/hy3-preview",
    "qwen/qwen3-coder",
    "deepseek/deepseek-v4-pro",
    "z-ai/glm-5.2",
    "minimax/minimax-m2.7",
]

# OpenCode Go subscription models. These IDs are used directly by the OpenCode CLI
# as provider/model selectors, e.g. `opencode-go/qwen3.7-plus`.
OPENCODE_GO_MODELS = [
    "opencode-go/glm-5.2",
    "opencode-go/glm-5.1",
    "opencode-go/kimi-k2.7-code",
    "opencode-go/kimi-k2.6",
    "opencode-go/deepseek-v4-pro",
    "opencode-go/deepseek-v4-flash",
    "opencode-go/mimo-v2.5",
    "opencode-go/mimo-v2.5-pro",
    "opencode-go/minimax-m3",
    "opencode-go/minimax-m2.7",
    "opencode-go/qwen3.7-max",
    "opencode-go/qwen3.7-plus",
    "opencode-go/qwen3.6-plus",
]

OPENCODE_GO_PREFIX = "opencode-go/"
OPENCODE_GO_MODEL_IDS = {model.removeprefix(OPENCODE_GO_PREFIX) for model in OPENCODE_GO_MODELS}


def is_opencode_go_selector(model: str) -> bool:
    return model.startswith(OPENCODE_GO_PREFIX)


def opencode_go_model_id(model: str) -> str:
    if model in OPENCODE_GO_MODEL_IDS:
        return model
    if is_opencode_go_selector(model):
        return model.removeprefix(OPENCODE_GO_PREFIX)
    _, _, candidate = model.partition("/")
    if candidate in OPENCODE_GO_MODEL_IDS:
        return candidate
    return ""


def opencode_go_selector(model: str) -> str:
    model_id = opencode_go_model_id(model)
    return f"{OPENCODE_GO_PREFIX}{model_id}" if model_id else ""

PRICES = {
    "minimax/minimax-m3": (0.30, 1.20),
    "deepseek/deepseek-v4-flash": (0.09, 0.18),
    "z-ai/glm-4.7": (0.40, 1.75),
    "qwen/qwen3.7-plus": (0.32, 1.28),
    "google/gemini-3.1-flash-lite": (0.25, 1.50),
    "qwen/qwen3-coder-next": (0.11, 0.80),
    "tencent/hy3-preview": (0.066, 0.26),
    "qwen/qwen3-coder": (0.22, 1.80),
    "deepseek/deepseek-v4-pro": (0.435, 0.87),
    "z-ai/glm-5.2": (1.00, 4.00),
    "minimax/minimax-m2.7": (0.25, 1.00),
    "opencode-go/glm-5.2": (1.40, 4.40),
    "opencode-go/glm-5.1": (1.40, 4.40),
    "opencode-go/kimi-k2.7-code": (0.95, 4.00),
    "opencode-go/kimi-k2.6": (0.95, 4.00),
    "opencode-go/deepseek-v4-pro": (1.74, 3.48),
    "opencode-go/deepseek-v4-flash": (0.14, 0.28),
    "opencode-go/mimo-v2.5": (0.14, 0.28),
    "opencode-go/mimo-v2.5-pro": (1.74, 3.48),
    "opencode-go/minimax-m3": (0.30, 1.20),
    "opencode-go/minimax-m2.7": (0.30, 1.20),
    "opencode-go/qwen3.7-max": (2.50, 7.50),
    "opencode-go/qwen3.7-plus": (0.40, 1.60),
    "opencode-go/qwen3.6-plus": (0.50, 3.00),
}

MODEL_PRESETS = {
    "original": ORIGINAL_MODELS,
    "new": NEW_MODELS,
    "opencode-go": OPENCODE_GO_MODELS,
    "all": ORIGINAL_MODELS + NEW_MODELS,
}


def expand_models(value: str | None) -> list[str]:
    """Expand a comma-separated model selector or preset name."""
    if not value:
        return list(NEW_MODELS)
    models: list[str] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if item in MODEL_PRESETS:
            models.extend(MODEL_PRESETS[item])
        else:
            models.append(item)
    return models

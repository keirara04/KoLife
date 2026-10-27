"""Model IDs, efforts and prices — the one place they live (AGENTS.md §3)."""

WONDER = "muse-wonder-1.0"
SPARK = "muse-spark-1.3"
SAM = "sam-3.1"
VOICE = "muse-voice-transcribe-1.0"
IMAGE = "muse-image-1.0"
SPARK_OPEN = "meta-models/muse-spark-open-1026"  # Baseten

# USD per 1M tokens: (input, cached input, output)
TOKEN_PRICES: dict[str, tuple[float, float, float]] = {
    WONDER: (4.00, 0.20, 20.00),
    SPARK: (1.25, 0.15, 4.25),
}
SAM_PER_IMAGE = 2.50 / 1000
VOICE_PER_HOUR = 0.18
IMAGE_PER_IMAGE = 0.01


def token_cost(model: str, usage: dict) -> float:
    """Cost of a Responses call; cached tokens are a subset of input_tokens.

    Unknown models (e.g. Baseten, billed separately) cost 0 against Meta credits.
    """
    if model not in TOKEN_PRICES:
        return 0.0
    p_in, p_cached, p_out = TOKEN_PRICES[model]
    inp = usage.get("input_tokens", 0)
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    out = usage.get("output_tokens", 0)
    return ((inp - cached) * p_in + cached * p_cached + out * p_out) / 1e6


def voice_cost(audio_duration_ms: int) -> float:
    return audio_duration_ms / 3.6e6 * VOICE_PER_HOUR

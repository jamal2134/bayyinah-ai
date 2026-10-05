from decimal import Decimal

USD_SAR_RATE = Decimal("3.75")

# USD per million tokens. Update only from the provider's published pricing.
# Unknown model IDs intentionally have no fallback price.
MODEL_PRICING = {
    "claude-sonnet-4-5": {
        "input": Decimal("3"),
        "output": Decimal("15"),
        "cache_creation_input": Decimal("3.75"),
        "cache_read_input": Decimal("0.30"),
    },
}

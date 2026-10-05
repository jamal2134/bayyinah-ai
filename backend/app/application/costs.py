from decimal import Decimal

from app.application.models import CostStatus, CostSummary, CostType, LLMUsageRecord, ProviderCallSummary
from app.application.pricing import MODEL_PRICING, USD_SAR_RATE


class CostTracker:
    def __init__(self):
        self.llm_calls: list[LLMUsageRecord] = []

    def record_usage(self, phase: str, model: str, usage) -> None:
        values = {name: int(getattr(usage, name, 0) or 0) for name in (
            "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
        pricing = MODEL_PRICING.get(model)
        if pricing is None:
            record = LLMUsageRecord(phase=phase, model=model, **values,
                                    cost_type=CostType.CALCULATED_FROM_API_USAGE,
                                    cost_status=CostStatus.PRICING_UNAVAILABLE)
        else:
            cost = sum((Decimal(values[name]) * pricing[key] / Decimal(1_000_000)
                        for name, key in (("input_tokens", "input"), ("output_tokens", "output"),
                            ("cache_creation_input_tokens", "cache_creation_input"),
                            ("cache_read_input_tokens", "cache_read_input"))), Decimal("0"))
            record = LLMUsageRecord(phase=phase, model=model, **values,
                cost_type=CostType.CALCULATED_FROM_API_USAGE, cost_status=CostStatus.AVAILABLE,
                estimated_cost_usd=cost, estimated_cost_sar=cost * USD_SAR_RATE)
        self.llm_calls.append(record)

    def summary(self, providers: list[ProviderCallSummary], duration_ms: float) -> CostSummary:
        available = all(call.cost_status == CostStatus.AVAILABLE for call in self.llm_calls)
        usd = sum((call.estimated_cost_usd or Decimal("0") for call in self.llm_calls), Decimal("0")) if available else None
        return CostSummary(llm_calls=len(self.llm_calls), input_tokens=sum(x.input_tokens for x in self.llm_calls),
            output_tokens=sum(x.output_tokens for x in self.llm_calls), provider_calls=sum(x.request_count for x in providers),
            provider_breakdown=providers, duration_ms=duration_ms, cost_status=CostStatus.AVAILABLE if available else CostStatus.PRICING_UNAVAILABLE,
            estimated_cost_usd=usd, estimated_cost_sar=usd * USD_SAR_RATE if usd is not None else None,
            usd_sar_rate=USD_SAR_RATE, usage_records=self.llm_calls)

"""Cheap-primary strategy with threshold-triggered configured ceiling."""


def execute(runtime, case, tier):
    primary = runtime.invoke(
        case=case,
        model_tier="cheap",
        call_role="primary",
        call_index=1,
        messages=runtime.base_messages(case),
    )
    calls = [primary]
    if primary.parsed is None:
        return calls, primary
    if primary.parsed.confidence >= runtime.escalation_threshold:
        return calls, primary
    fallback = runtime.invoke(
        case=case,
        model_tier=tier,
        call_role="fallback",
        call_index=2,
        messages=runtime.fallback_messages(case),
    )
    calls.append(fallback)
    return calls, fallback

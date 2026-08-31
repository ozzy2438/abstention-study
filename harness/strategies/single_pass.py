"""One-call answer or abstention strategy."""


def execute(runtime, case, tier):
    primary = runtime.invoke(
        case=case,
        model_tier=tier,
        call_role="primary",
        call_index=1,
        messages=runtime.base_messages(case),
    )
    return [primary], primary

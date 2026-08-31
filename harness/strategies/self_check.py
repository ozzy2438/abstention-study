"""Two-call same-model answer and critic strategy."""


def execute(runtime, case, tier):
    primary = runtime.invoke(
        case=case,
        model_tier=tier,
        call_role="primary",
        call_index=1,
        messages=runtime.base_messages(case),
    )
    calls = [primary]
    critic = runtime.invoke(
        case=case,
        model_tier=tier,
        call_role="critic",
        call_index=2,
        messages=runtime.critic_messages(case, primary.response_content or ""),
    )
    calls.append(critic)
    return calls, critic

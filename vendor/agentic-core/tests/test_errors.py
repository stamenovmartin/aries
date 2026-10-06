from _harness import bootstrap, check, run_module
bootstrap("errors")

from agentic_core.orchestrator.errors import ErrorClass, classify  # noqa: E402
from agentic_core.orchestrator.retry import RetryPolicy, with_retry  # noqa: E402


def test_taxonomy():
    check("lost response is uncertain", classify("anything", sent=True, got_response=False).cls is ErrorClass.UNCERTAIN)
    check("timeout is transient/retry", classify("connection timed out").action == "retry")
    check("429 is transient", classify("HTTP 429 rate limit").retryable)
    check("expired token is auth/reconnect", classify("token expired").action == "reconnect")
    check("invalid input is validation/replan", classify("invalid argument: must be int").action == "replan")
    check("policy is escalate", classify("action rejected by policy").action == "escalate")
    check("unknown is escalate, not retry", classify("???").action == "escalate" and not classify("???").retryable)
    check("command not found is validation", classify("bash: foo: command not found").cls is ErrorClass.VALIDATION)


async def test_with_retry_only_retries_transient():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("timeout")
        return "ok"
    r = await with_retry(flaky, policy=RetryPolicy(max_attempts=3))
    check("transient retried until success", r.ok and r.attempts == 3)

    calls["n"] = 0

    async def bad():
        calls["n"] += 1
        raise RuntimeError("invalid value: must be positive")
    r = await with_retry(bad, policy=RetryPolicy(max_attempts=3))
    check("validation error not retried", (not r.ok) and calls["n"] == 1 and r.verdict.action == "replan")


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))

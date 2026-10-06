"""Bound rejected completion proposals without changing completion authority."""


def reject(agent, *, step_count, reason):
    """Allow one corrected proposal; a second rejection needs a new action.

    The caller must run the real completion check first: a corrected valid
    reference is always allowed to finish. Persisted state survives goal resume.
    Rotating references cannot evade the bound. A new step resets the counter;
    the ordinary action/call budgets still bound unsuccessful action sequences.
    """
    previous = agent.get("completion_rejection_sequence", {})
    count = previous.get("count", 0) + 1 if previous.get("step_count") == step_count else 1
    agent["completion_rejection_sequence"] = {"step_count": step_count, "count": count}
    stopped = count >= 2
    agent["completion_feedback"] = (
        f"Completion rejected: {reason}. "
        + ("Repeated completion was rejected without an intervening action; stopping without claiming success."
           if stopped else
           "Do not repeat this completion claim. Take a permitted action that can establish the missing "
           "evidence, correct mistaken evidence references once, or choose fail if no permitted route remains. "
           "Another rejected completion without an intervening action will stop this goal.")
    )
    if stopped:
        agent["stop_reason"] = "COMPLETION_NO_PROGRESS"
    return stopped

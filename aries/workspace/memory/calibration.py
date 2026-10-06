"""A bare label with a calibrated probability, in one local generation.

WHY NOT A JSON OBJECT
---------------------
This project measured it: asking the local model for `{"decision": ...,
"confidence": ...}` is about 11x slower than asking it for the label alone, at
equal accuracy. The object costs a dozen structural tokens the model has to
emit before it says anything, and the confidence it writes inside the object is
a number it invented. The probability below is the model's own, read off the
logits.

METHOD — verified in experiments/intent_confidence.py on ollama 0.34.0 +
qwen2.5:7b, 2026-09-24: **68 ms per call, expected calibration error 0.0035**.
Generate the label unconstrained with `logprobs`/`top_logprobs=20`, then walk a
prefix trie of the emitted token path to score every competing label:

  * the emitted label gets its exact cumulative logprob;
  * a competitor that diverges from it at a position where its next token is
    inside that position's top-20 gets an exact score too;
  * anything that never appears in a top-20 gets a floor.

Renormalising over the label set turns those into probabilities. That is a real
posterior over the labels, which is what a `confidence` column in the LEARNED
layer is supposed to mean — as opposed to a number a model typed.

Labels are NAMES, never letters. `A`/`B`/`C` tokenise into single tokens that
carry strong unrelated priors from pretraining, and nothing downstream can read
the audit row afterwards.
"""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from aries.intelligence.providers import loopback_url
from aries.workspace.memory.local_transport import open_local

FLOOR = -18.          # logprob for a label that never surfaces in a top-20
TEMPERATURE = 1.      # accuracy is invariant to it; only the probabilities move


class ModelUnavailable(RuntimeError):
    """No local model answered. The caller falls back; it never guesses."""


def _logsumexp(values):
    top = max(values)
    return top + math.log(sum(math.exp(v - top) for v in values))


def classify(prompt, labels, *, endpoint, model, temperature=TEMPERATURE, timeout=30, predict=12):
    """Return {label, confidence, margin, runner_up, probs, emitted, valid, latency_s}."""
    try:
        endpoint=loopback_url(endpoint)
    except ValueError:
        raise ModelUnavailable('Memory classification requires a literal loopback endpoint') from None
    body = json.dumps({
        "model": model, "prompt": prompt, "raw": True, "stream": False,
        # The stops matter. Asked for one word, a local model that is unsure
        # writes `SUPERSEDE - the mentor changed`, and the explanation it was
        # not asked for is what breaks the scoring below. Stopping at the
        # punctuation it uses to start explaining costs nothing when it obeys.
        "options": {"temperature": 0, "num_predict": predict,
                    "stop": ["\n", " -", " (", ",", ".", ":", "Utterance:", "Request:"]},
        "logprobs": True, "top_logprobs": 20,
    }).encode()
    started = time.perf_counter()
    request = urllib.request.Request(endpoint + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with open_local(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise ModelUnavailable(str(exc)) from None

    steps = payload.get("logprobs") or []
    if not steps:
        raise ModelUnavailable("the model returned no logprobs; ollama >= 0.34 is required")
    tokens = [s["token"] for s in steps]
    emitted = "".join(tokens).strip()

    cumulative = [0.]
    for step in steps:
        cumulative.append(cumulative[-1] + step["logprob"])
    prefixes, grown = [""], ""
    for i, token in enumerate(tokens):
        grown = (grown + token).lstrip() if i == 0 else grown + token
        prefixes.append(grown)

    # A label the model then explained (`APPEND because ...`) is still that
    # label, and must be scored as the emitted path rather than falling through
    # to the competitor branch — where it scores as if it had never been said,
    # which produced a 0.250 confidence and a 0.000 margin on a decision the
    # model had in fact made with no hesitation at all.
    spoken = max((label for label in labels if emitted.startswith(label)), key=len, default=None)

    scores = {}
    for label in labels:
        if label == spoken:
            # The first token boundary at or past the end of the label. When a
            # single token spans the boundary (`APPEND -`) this includes that
            # token's logprob, which understates confidence slightly and never
            # overstates it.
            end = next(i for i, p in enumerate(prefixes) if p.startswith(label))
            scores[label] = cumulative[end]
            continue
        i = 0
        while i + 1 < len(prefixes) and prefixes[i + 1] != "" and label.startswith(prefixes[i + 1]):
            i += 1
        if i >= len(steps):
            scores[label] = FLOOR
            continue
        remainder, best = label[len(prefixes[i]):], None
        for candidate in steps[i]["top_logprobs"]:
            text = candidate["token"].lstrip() if i == 0 else candidate["token"]
            if text and remainder.startswith(text) and (best is None or candidate["logprob"] > best):
                best = candidate["logprob"]
        scores[label] = cumulative[i] + (best if best is not None else FLOOR)

    scaled = {label: scores[label] / temperature for label in labels}
    total = _logsumexp(list(scaled.values()))
    probs = {label: math.exp(scaled[label] - total) for label in labels}
    ranked = sorted(probs.items(), key=lambda item: -item[1])
    return {"label": ranked[0][0], "confidence": ranked[0][1],
            "margin": ranked[0][1] - ranked[1][1] if len(ranked) > 1 else ranked[0][1],
            "runner_up": ranked[1][0] if len(ranked) > 1 else None, "probs": probs,
            "emitted": emitted, "spoken": spoken, "valid": spoken is not None,
            "latency_s": time.perf_counter() - started}

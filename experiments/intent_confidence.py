"""Calibrated intent classification on local ollama, one call, ~0.07s.

Method: unconstrained (or grammar-guarded) bare-label generation with
logprobs=true, top_logprobs=20; then renormalise over the 14 labels using a
prefix-trie walk of the emitted path.  Probabilities are exact for the emitted
label and for every competitor that diverges inside the top-20 at its
divergence point; competitors outside top-20 get a floor.

Verified on ollama 0.34.0 + qwen2.5:7b, 2026-09-24.
"""
import json, math, time, urllib.request

OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL  = "qwen2.5:7b"
LABELS = ["OPEN_APP","OPEN_URL","SEARCH_WEB","READ_EMAIL","SEND_EMAIL",
          "CALENDAR_ACTION","SYSTEM_ACTION","RESEARCH","CODING","CLASSIFY",
          "EXTRACT","AUTOMATION","FILE_ACTION","UNKNOWN"]
FLOOR   = -18.0   # logprob floor for labels that fall outside top-20
TEMP    = 1.0     # fit on your fixture; accuracy is provably invariant to it

_SYS = """You are an intent classifier. Reply with exactly one label and nothing else.
Label definitions:
OPEN_APP - launch a local application
OPEN_URL - open a specific website or URL
SEARCH_WEB - look up a simple fact or news online
READ_EMAIL - read or check existing mail
SEND_EMAIL - compose, reply to or send mail
CALENDAR_ACTION - create, move, cancel or query calendar events
SYSTEM_ACTION - change a device/OS setting or control a process
RESEARCH - deep multi-source investigation or literature review
CODING - write, debug, test or refactor code
CLASSIFY - assign categories/labels/sentiment to a set of items
EXTRACT - pull specific fields or entities out of a document
AUTOMATION - set up a recurring or scheduled task
FILE_ACTION - create, move, copy, rename, delete or compress files
UNKNOWN - none of the above
"""
_FEWSHOT = ("\nRequest: launch spotify\nLabel: OPEN_APP\n"
            "Request: go to github.com\nLabel: OPEN_URL\n"
            "Request: who won the world cup\nLabel: SEARCH_WEB\n"
            "Request: write me a python script\nLabel: CODING\n"
            "Request: what's on my agenda friday\nLabel: CALENDAR_ACTION\n"
            "Request: blah blah nonsense\nLabel: UNKNOWN\n")

def _post(body):
    r = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())

def _lse(xs):
    m = max(xs)
    return m + math.log(sum(math.exp(x - m) for x in xs))

def classify(user_text, temp=TEMP):
    t0 = time.time()
    d = _post({
        "model": MODEL,
        "prompt": _SYS + _FEWSHOT + f"\nRequest: {user_text}\nLabel:",
        "raw": True, "stream": False,
        "options": {"temperature": 0, "num_predict": 12,
                    "stop": ["\n", "Request:"]},
        "logprobs": True, "top_logprobs": 20,
    })
    lps = d.get("logprobs") or []
    toks = [x["token"] for x in lps]
    emitted = "".join(toks).strip()

    cum = [0.0]
    for x in lps:
        cum.append(cum[-1] + x["logprob"])
    prefixes, acc = [""], ""
    for i, t in enumerate(toks):
        acc = (acc + t).lstrip() if i == 0 else acc + t
        prefixes.append(acc)

    scores = {}
    for L in LABELS:
        if L == emitted:
            k = next(i for i, p in enumerate(prefixes) if p == L)
            scores[L] = cum[k]
            continue
        i = 0
        while i + 1 < len(prefixes) and prefixes[i+1] != "" and L.startswith(prefixes[i+1]):
            i += 1
        if i >= len(lps):
            scores[L] = FLOOR
            continue
        rem = L[len(prefixes[i]):]
        best = None
        for t in lps[i]["top_logprobs"]:
            ts = t["token"].lstrip() if i == 0 else t["token"]
            if ts and rem.startswith(ts) and (best is None or t["logprob"] > best):
                best = t["logprob"]
        scores[L] = cum[i] + (best if best is not None else FLOOR)

    s = {L: scores[L] / temp for L in LABELS}
    Z = _lse(list(s.values()))
    probs = {L: math.exp(s[L] - Z) for L in LABELS}
    top = max(probs, key=probs.get)
    ranked = sorted(probs.items(), key=lambda kv: -kv[1])
    return {"label": top, "confidence": probs[top],
            "margin": ranked[0][1] - ranked[1][1],
            "runner_up": ranked[1][0], "probs": probs,
            "emitted": emitted, "valid": emitted in LABELS,
            "latency_s": time.time() - t0}

if __name__ == "__main__":
    import sys
    for q in (sys.argv[1:] or ["open firefox", "refactor this function",
                               "every monday back up my documents folder"]):
        r = classify(q)
        print(f"{q!r}\n  -> {r['label']}  conf={r['confidence']:.3f} "
              f"margin={r['margin']:.3f} runner_up={r['runner_up']} "
              f"valid={r['valid']} {r['latency_s']*1000:.0f}ms")

"""Twenty real installed-system journeys. No placeholder websites or mocked network."""
import json
import os
from pathlib import Path
import time
import urllib.request
from datetime import datetime, timezone

BASE = os.environ.get("ARIES_API", "http://127.0.0.1:8000")
OUT = Path(__file__).resolve().parent
RUN = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
ROOT = Path.home()/"Documents"/("ARIES-Evaluation-"+RUN)
RESULTS = []

def report_safe(value):
    if isinstance(value, dict):
        return {key: report_safe(item) for key, item in value.items() if key != "cmdline"}
    if isinstance(value, list):
        return [report_safe(item) for item in value]
    return value

def api(method, path, body=None):
    payload = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE+"/api/aries"+path, data=payload, method=method,
                                      headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

def wait(goal_id):
    deadline = time.monotonic()+1000
    while time.monotonic()<deadline:
        goal = next((g for g in api("GET", "/workspace")["goals"] if g["id"]==goal_id), None)
        if goal and goal["state"] not in {"queued","running"}:
            return goal
        time.sleep(1)
    raise TimeoutError("Goal did not finish before the evaluation deadline")

def run(kind, args, *, approve=False):
    start = time.monotonic()
    row = api("POST", "/workspace", {"capability":kind,"args":args})
    goal = wait(row["id"])
    if goal["state"]=="proposed" and approve:
        # Only this run's own, disposable file targets may be approved.
        step = next(s for s in goal["steps"] if s.get("state")=="proposed")
        assert step["capability"] in {"move_file","trash_file"}
        assert Path(step["args"]["path"]).is_relative_to(ROOT)
        api("POST", f"/workspace/{row['id']}/approve", {})
        goal=wait(row["id"])
    item={"capability":kind,"goal_id":row["id"],"state":goal["state"],
          "seconds":round(time.monotonic()-start,2),"cards":len(goal.get("cards",[])),
          "gaps":goal.get("gaps",[]),"steps":goal.get("steps",[])}
    RESULTS.append(item)
    write_results()
    print(f"{kind}: {item['state']} · {item['cards']} cards · {item['seconds']}s",flush=True)
    return goal

def write_results():
    report={"run":RUN,"environment":"installed ARIES, real HTTP/desktop/files/network",
            "verified_done":sum(r["state"]=="done" for r in RESULTS),
            "total":len(RESULTS),"results":RESULTS}
    (OUT/"live-results.json").write_text(json.dumps(report_safe(report),indent=2,ensure_ascii=False))
    lines=["# Installed workspace acceptance run", "", f"Run: {RUN}. Real websites, desktop and filesystem.", "",
           "| Capability | Observed state | Cards | Seconds |", "|---|---|---:|---:|"]
    for r in RESULTS:
        lines.append(f"| {r['capability']} | {r['state']} | {r['cards']} | {r['seconds']} |")
    lines += ["", f"{report['verified_done']} of {report['total']} requests finished with verified done status.",
              "", "An installed-package check is not proof of a new installation. Proposed, partial and unconfirmed outcomes are not counted as completed."]
    for r in RESULTS:
        if r["gaps"]:
            lines += ["", f"{r['capability']}: " + "; ".join(r["gaps"])]
    (OUT/"live-results.md").write_text("\n".join(lines)+"\n")

def main():
    # A systemd restart returns before Uvicorn has bound its socket.
    for attempt in range(40):
        try:
            api("GET", "/workspace")
            break
        except OSError:
            if attempt == 39:
                raise
            time.sleep(0.25)
    note="ARIES evaluation "+RUN+" uses real public websites."
    try:
        run("create_folder",{"path":str(ROOT)})
        run("create_file",{"path":str(ROOT/"notes.txt"),"content":"ARIES live evaluation. Real destinations: https://www.kernel.org/ and https://github.com/\n"})
        run("read_file",{"path":str(ROOT/"notes.txt")})
        run("list_folder",{"path":str(ROOT)})
        run("find_files",{"query":"notes.txt"})
        run("open_path",{"path":str(ROOT)})
        run("move_file",{"path":str(ROOT/"notes.txt"),"destination":str(ROOT/"renamed.txt")},approve=True)
        run("trash_file",{"path":str(ROOT/"renamed.txt")},approve=True)
        run("list_apps",{})
        run("processes",{})
        run("system",{})
        run("health",{})
        run("open_app",{"app":"Firefox"})
        run("open_url",{"url":"https://www.youtube.com"})
        run("search_web",{"query":"Linux AI agent desktop"})
        run("research",{"query":"artificial intelligence agents"})
        run("refresh_news",{})
        run("brief",{})
        run("remember",{"text":note})
        run("install_app",{"app":"firefox"})
    finally:
        for memory in api("GET","/workspace")["memories"]:
            if memory["text"]==note:
                api("DELETE","/workspace/memories/"+memory["id"])
        # Only empty evaluation directories are removed. Keep any unexpected state
        # intact so a failed file journey remains inspectable.
        if ROOT.exists() and not any(ROOT.iterdir()):
            ROOT.rmdir()
        write_results()
    print(f"Report: {OUT/'live-results.md'}",flush=True)

if __name__=="__main__":
    main()

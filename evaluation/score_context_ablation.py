"""Score the A/B/C runs on the six demo PRs against the answer key (demo/ticket-system/README.md)."""

import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONFIGS = {"A": "LLM only", "B": "+ static tools", "C": "+ tools + repository context"}


def text(f):
    return f"{f['title']} {f['explanation']}".lower()


def planted_found(n, findings):
    for f in findings:
        t = text(f)
        if n == 2 and f["file"] == "tickets/service.py" and ("48" in t or ">=" in t or "boundary" in t or f["category"] == "boundary_condition"):
            return True
        if n == 3 and f["file"] == "tickets/store.py" and any(k in t for k in ("inject", "f-string", "f?string", "parameter")):
            return True
        if n == 4 and f["file"] == "tickets/service.py" and ("reporter" in t or "admin" in t):
            return True
        if n == 5 and f["file"] == "tickets/service.py" and any(k in t for k in ("except", "silen", "swallow", "broad", "not logged", "log")):
            return True
    return False


def checklist_ok(n, criteria):
    v = {c["number"]: c["verdict"] for c in criteria}
    if n == 1 or n == 3:
        return all(x == "met" for x in v.values())
    if n == 2:
        return v.get(1) == "not_met" and v.get(2) == "met" and v.get(3) == "met"
    if n == 4:
        return v.get(1) == "not_met"
    if n == 5:
        return v.get(3) == "not_met" and v.get(1) == "met" and v.get(2) == "met"
    if n == 6:
        return v.get(2) == "cannot_determine"
    return None


rows = {}
for cfg in CONFIGS:
    for n in range(1, 7):
        folders = sorted(pathlib.Path(f"evaluation/results/context-ablation/{cfg}").glob(f"pr{n}"))
        result = json.loads((folders[-1] / "result.json").read_text(encoding="utf-8"))
        rows[cfg, n] = result

print("PR  cfg  planted  checklist  findings  dismissed  tokens_in  model_s   context")
for n in range(1, 7):
    for cfg in CONFIGS:
        r = rows[cfg, n]
        f = r["findings"]
        run = r["run"] or {}
        planted = "n/a" if n in (1, 6) else ("YES" if planted_found(n, f) else "no")
        ok = checklist_ok(n, r["criteria"])
        print(f"{n}   {cfg}    {planted:7}  {('ok' if ok else 'WRONG'):9}  {len(f):8}  {len(r['dismissed']):9}  {run.get('prompt_tokens') or 0:9}  {run.get('duration_s') or 0:6.1f}   {len(r.get('context', []))}")
    print()

print("=========== all findings per run (to judge the non-planted ones by hand) ===========")
for n in range(1, 7):
    for cfg in CONFIGS:
        r = rows[cfg, n]
        print(f"--- PR{n} {cfg}: {len(r['findings'])} finding(s)")
        for f in r["findings"]:
            print(f"    [{f['severity']}] {f['category']} {f['file']}:{f['line']} by={'+'.join(f['found_by'])} :: {f['title'][:95]}")
        for d in r["dismissed"]:
            print(f"    (dismissed) {d['finding']['title'][:80]} -- {d['reason'][:110]}")

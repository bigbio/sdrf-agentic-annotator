"""Four-way comparison for the contract/build A/B: v2 baseline (denying harness), Step-0-only
(denying harness), shipped skill with plugin tools allowed, optimized skill with tools allowed.
Per matched run: tool calls, permission denials, cost, deterministic score, validity, errors."""
import glob, json, os, sys

ARMS = [("v2", "outputs-v2"), ("step0", "outputs-v3-step0"), ("old+tools", "outputs-v3-old"), ("new+tools", "outputs-v3-new")]
MODELS = ("sonnet-5-skills", "haiku-4.5-skills")


def load(outputs):
    d = {}
    for f in glob.glob(f"{outputs}/*/*/usage.json"):
        run = os.path.dirname(f); m = os.path.basename(os.path.dirname(run)); k = (m, os.path.basename(run))
        u = json.load(open(f))
        s = json.load(open(run + "/score.json")) if os.path.exists(run + "/score.json") else {}
        calls = denials = 0
        tp = run + "/transcript.jsonl"
        if os.path.exists(tp):
            for line in open(tp):
                if '"tool_use"' in line:
                    try:
                        ev = json.loads(line)
                        if ev.get("type") == "assistant":
                            calls += sum(1 for b in ev["message"]["content"] if b.get("type") == "tool_use")
                    except Exception:
                        pass
                if '"type":"result"' in line or '"type": "result"' in line:
                    try:
                        denials = len(json.loads(line).get("permission_denials") or [])
                    except Exception:
                        pass
        d[k] = dict(calls=calls, denials=denials, cost=u.get("cost_usd") or 0, det=s.get("deterministic"),
                    val=s.get("validity"), err=s.get("n_errors"), flags=u.get("flags"))
    return d


arms = {name: load(p) for name, p in ARMS if os.path.isdir(p)}
keys = sorted({k for name in ("new+tools", "old+tools") if name in arms for k in arms[name]})
for m in MODELS:
    ks = [k for k in keys if k[0] == m]
    if not ks:
        continue
    print(f"\n=== {m}: {len(ks)} matched runs ===")
    print(f"{'arm':10s} {'calls':>6s} {'denied':>7s} {'$/run':>6s} {'det':>6s} {'valid':>6s} {'errs':>5s}  flags")
    for name, d in arms.items():
        rs = [d[k] for k in ks if k in d]
        if not rs:
            continue
        n = len(rs)
        fl = {}
        for r in rs:
            for f in (r["flags"] or []):
                fl[f] = fl.get(f, 0) + 1
        det = [r["det"] for r in rs if r["det"] is not None]
        print(f"{name:10s} {sum(r['calls'] for r in rs)/n:6.1f} {sum(r['denials'] for r in rs)/n:7.1f} "
              f"{sum(r['cost'] for r in rs)/n:6.2f} {sum(det)/len(det) if det else 0:6.1f} "
              f"{sum(r['val'] or 0 for r in rs)/n:6.2f} {sum(r['err'] or 0 for r in rs):5d}  {fl or ''}  (n={n})")
    if "new+tools" in arms and "old+tools" in arms:
        print("  per dataset (old+tools -> new+tools): calls, cost, det")
        for k in ks:
            o, w = arms["old+tools"].get(k), arms["new+tools"].get(k)
            if o and w:
                print(f"    {k[1]:24s} {o['calls']:3d}->{w['calls']:3d}  ${o['cost']:.2f}->${w['cost']:.2f}  "
                      f"{o['det'] or 0:5.1f}->{w['det'] or 0:5.1f}  val {o['val'] or 0:.2f}->{w['val'] or 0:.2f}")

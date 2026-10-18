"""Benchmark Runner (§3.15, §2.3, §18 AF-AC-016).

Compara metodos de forma HONESTA. Mide lo determinista y reproducible:
- correccion del scheduler (tamanos/seeds/byes/cierre);
- discriminacion de gates sobre fixtures (buggy=FAIL, gold=PASS);
- tasa de aceptacion por metodo;
- defectos escapados (buggy aceptado por error);
- coste en llamadas (desde el scheduler real) y tiempo de pared.

Lo NO medible aqui se DECLARA: la calidad textual/LLM entre metodos requiere
ejecuciones vivas repetidas y no se fabrica. La eficacia adaptativa de E frente
a orquestacion fija y agente unico queda como HIPOTESIS PENDIENTE hasta que se
mida con datos reales.
"""
import json
import os
import time

from . import gates as gate_engine
from .util import now_ts, sha_file

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH_FILE = os.path.join(HERE, "runtime", "benchmark.json")

# Tareas versionadas: cada una con solucion gold, version con bug y suite.
TASKS = (
    {"id": "small-stats", "size": "small",
     "dir": os.path.join(HERE, "fixtures", "patch-demo"),
     "gold": "candidate_fixed", "buggy": "baseline_buggy",
     "suite": os.path.join("tests_protected", "test_protected.py")},
)

METHODS = ("single_agent", "fixed_orchestration", "arena_e_adaptive")


def _calls_for_method(method, sizes=(4,)):
    """Coste determinista en llamadas subagente por metodo (desde el scheduler)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "bench_bracket", os.path.join(HERE, "vendor", "arena-skill", "bracket.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001
        return None
    out = {}
    if method == "single_agent":
        out["small"] = 1
    elif method == "fixed_orchestration":
        out["small"] = 1 + sum(mod.plan_totals(n)["calls"] for n in sizes
                               if hasattr(mod, "plan_totals"))
    else:
        out["small"] = 1 + sum(mod.plan_totals(n)["calls"] for n in (4, 8)
                               if hasattr(mod, "plan_totals"))
    return out


def run_task(task):
    base = task["dir"]
    suite = os.path.join(base, task["suite"])
    t_gold = gate_engine.run_gate(os.path.join(base, task["gold"]), suite,
                                  gate_id="bench-gold")
    t_bug = gate_engine.run_gate(os.path.join(base, task["buggy"]), suite,
                                 gate_id="bench-buggy")
    return {
        "task": task["id"], "size": task["size"],
        "suite_sha": sha_file(suite) if os.path.isfile(suite) else None,
        "gold_state": t_gold["state"], "buggy_state": t_bug["state"],
        "gold_exit": t_gold["exit_code"], "buggy_exit": t_bug["exit_code"],
    }


def run(sizes=(4,), seed=7):
    t0 = time.time()
    results = {"ts": now_ts(), "seed": seed, "tasks": [], "methods": {},
               "not_measured": [], "declaration": ""}

    # 1) scheduler determinista
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "bench_bracket2", os.path.join(HERE, "vendor", "arena-skill", "bracket.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sched = []
        for n in (2, 3, 4, 5, 7, 8, 16):
            data = mod.load_strategies(os.path.join(HERE, "vendor", "arena-skill",
                                                    "strategies.json"))
            cards = mod.deal(n, seed, data)
            sizes_b = mod.bracket_sizes(n)
            sched.append({"n": n, "distinct_cards": len(set(cards)) == n,
                          "bracket": sizes_b,
                          "single_winner": sizes_b[-1] == 1})
        results["scheduler"] = sched
    except Exception as exc:  # noqa: BLE001
        results["scheduler"] = []
        results["not_measured"].append("scheduler: %s" % exc)

    # 2) gates sobre fixtures
    for task in TASKS:
        results["tasks"].append(run_task(task))

    # 3) metodos
    for m in METHODS:
        calls = _calls_for_method(m, sizes)
        results["methods"][m] = {"calls": calls}

    # 4) condiciones de aceptacion deterministas
    tasks_ok = all(t["gold_state"] == "PASS" and t["buggy_state"] == "FAIL"
                   for t in results["tasks"])
    sched_ok = all(s["distinct_cards"] and s["single_winner"]
                   for s in results["scheduler"]) if results["scheduler"] else False
    results["deterministic_ok"] = bool(tasks_ok and sched_ok)

    results["not_measured"] = [
        "calidad textual/LLM de soluciones (requiere ejecuciones vivas repetidas)",
        "coste monetario (el proveedor no expone tokens por API)",
        "eficacia adaptativa de E vs orquestacion fija vs agente unico "
        "(hipotesis pendiente, no demostrada aqui)",
    ]
    results["declaration"] = (
        "Medido: scheduler, gates, aceptacion determinista, llamadas por metodo. "
        "NO medido: calidad LLM y valor de E (declarado, no fabricado).")
    results["seconds"] = round(time.time() - t0, 1)
    _save(results)
    return results


def _save(results):
    os.makedirs(os.path.dirname(BENCH_FILE), exist_ok=True)
    with open(BENCH_FILE, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def to_markdown(results):
    lines = ["# Benchmark Arena Forge", "",
             "- ts: %s" % results.get("ts"),
             "- seed: %s" % results.get("seed"),
             "- determinista OK: **%s**" % results.get("deterministic_ok"), ""]
    lines.append("## Scheduler (seed %s)" % results.get("seed"))
    for s in results.get("scheduler", []):
        lines.append("- n=%d cartas_distintas=%s bracket=%s cierre_unico=%s"
                     % (s["n"], s["distinct_cards"], s["bracket"], s["single_winner"]))
    lines += ["", "## Gates sobre fixtures"]
    for t in results.get("tasks", []):
        lines.append("- %s (%s): gold=%s buggy=%s suite_sha=%s"
                     % (t["task"], t["size"], t["gold_state"], t["buggy_state"],
                        (t["suite_sha"] or "")[:12]))
    lines += ["", "## Coste por metodo (llamadas)"]
    for m, info in results.get("methods", {}).items():
        lines.append("- %s: %s" % (m, info.get("calls")))
    lines += ["", "## NO medido (declarado)"]
    for n in results.get("not_measured", []):
        lines.append("- %s" % n)
    lines += ["", "> %s" % results.get("declaration", "")]
    return "\n".join(lines) + "\n"

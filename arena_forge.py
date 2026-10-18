#!/usr/bin/env python
"""ARENA FORGE — runtime local de competicion de ingenieria para OpenCode V2.

Modos: `answer` (torneo de propuestas, reutiliza bracket.py vendored), `patch`
(codigo real con gates objetivos que preceden a cualquier puntuacion LLM) y
`benchmark` (comparacion honesta de metodos).

Todo el estado vive en `.arena/<run>/`:
  forge.json      Run contract (schema_version 2) + gobierno
  ledger.jsonl    historial append-only auditable
  decisions.jsonl decisiones estructuradas del agente E
  arena.json      sub-estado del bracket (answer)
  gates.json      GateResult por candidato (patch)
  candidates/     un directorio de escritura por candidato (aislamiento)

Reanudar es siempre seguro: nada completado se re-ejecuta ni se reescribe.

Solo stdlib. Windows/macOS/Linux (`python` o `python3`).
"""
import argparse
import difflib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from forge import (adapter, agent_e, benchmark as bench_mod, contracts,
                   isolation, ledger, report as report_mod, score as score_mod,
                   state)
from forge import gates as gate_engine
from forge.util import (ForgeError, MAX_OUTPUT_BYTES, atomic_write_json,
                        inside, read_json_bounded, redact, sha_file, sha_text)

HERE = os.path.dirname(os.path.abspath(__file__))
BRACKET = os.path.join(HERE, "vendor", "arena-skill", "bracket.py")
STRATEGIES = os.path.join(HERE, "vendor", "arena-skill", "strategies.json")
RUBRIC = os.path.join(HERE, "vendor", "arena-skill", "rubric.md")
REPORTS_DIR = os.path.join(HERE, "reports")
FORGE_VERSION = 2                      # schema_version del Run contract
ROOT = ".arena"
LATEST = "LATEST"
FORGE_FILE = "forge.json"
LOCK_FILE = "lock.json"
POLICY_VERSION = agent_e.POLICY_VERSION
TERMINAL = state.TERMINAL


# ============================================================ compat helpers
def inside_run(d, path):
    return inside(d, path)


def quarantine_oversize(d):
    """Mueve veredictos gigantes (>1MB) a .oversize: collect nunca los carga."""
    for root, _dirs, files in os.walk(d):
        for name in files:
            if not name.endswith(".verdict.json"):
                continue
            p = os.path.join(root, name)
            if not inside(d, p):
                continue
            try:
                if os.path.getsize(p) > MAX_OUTPUT_BYTES:
                    os.replace(p, p + ".oversize")
                    print("BLOCKED oversize: %s movido a .oversize" % p)
            except OSError:
                pass


def run_gates(candidate_dir, protected_suite, timeout_s=120):
    """Wrapper legacy sobre forge.gates: devuelve {verdict, log, sha_ok, seconds}."""
    g = gate_engine.run_gate(candidate_dir, protected_suite, timeout_s=timeout_s)
    return {"verdict": g["state"], "log": g.get("notes", ""),
            "sha_ok": (g.get("suite_sha") is not None), "seconds": 0.0,
            "gate": g}


# ============================================================ run governance
def _run_id(d):
    return os.path.basename(os.path.normpath(d))


def _migrate_v1_v2(data, d):
    """Migracion explicita v1 -> v2 (schema_version). No pierde historial."""
    data.setdefault("schema_version", 1)
    if data.get("schema_version") >= 2 and data.get("version") == FORGE_VERSION:
        return data
    data["schema_version"] = FORGE_VERSION
    data["version"] = FORGE_VERSION
    data.setdefault("run_id", _run_id(d))
    data.setdefault("phase", data.get("status", "RUNNING"))
    data.setdefault("policy_version", POLICY_VERSION)
    data.setdefault("budget", agent_e.default_budget())
    data.setdefault("calls_spent", 0)
    data.setdefault("candidates", {})
    data.setdefault("evidences", [])
    data.setdefault("approvals", [])
    data.setdefault("not_run", [])
    data.setdefault("migrated_from", 1)
    return data


def load_forge(d):
    path = os.path.join(d, FORGE_FILE)
    if not os.path.isfile(path):
        raise ForgeError("sin %s en %s" % (FORGE_FILE, d))
    data = read_json_bounded(path)
    if data.get("version") not in (1, FORGE_VERSION):
        raise ForgeError("forge.json version %r no soportada" % data.get("version"))
    data = _migrate_v1_v2(data, d)
    return data


def save_forge(run):
    atomic_write_json(os.path.join(run["dir"], FORGE_FILE), run)


def log_event(run, kind, detail=""):
    """Compat: evento tanto en forge.json como en el ledger append-only."""
    run.setdefault("events", []).append(
        {"t": int(time.time()), "kind": kind, "detail": detail})
    save_forge(run)
    try:
        ledger.append(run["dir"], kind, detail)
    except OSError:
        pass


def run_dir_from(args):
    if getattr(args, "dir", None):
        return os.path.abspath(args.dir)
    latest = os.path.join(ROOT, LATEST)
    if not os.path.isfile(latest):
        raise ForgeError("no hay ejecucion en %s (usa init --dir ...)" % latest)
    with open(latest, encoding="utf-8") as fh:
        return fh.read().strip()


def acquire_lock(d, owner="cli"):
    path = os.path.join(d, LOCK_FILE)
    now = time.time()
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                cur = json.load(fh)
            if now - cur.get("t", 0) < 300 and cur.get("pid") != os.getpid():
                raise ForgeError("otra controladora activa (%s, pid %s); espera o "
                                 "borra %s si es rancia"
                                 % (cur.get("owner"), cur.get("pid"), path))
        except (ValueError, KeyError):
            pass
    atomic_write_json(path, {"owner": owner, "pid": os.getpid(), "t": now})


def release_lock(d):
    try:
        os.remove(os.path.join(d, LOCK_FILE))
    except OSError:
        pass


def guard_mutable(run):
    if run.get("phase") == "CANCELLED" or run.get("status") == "CANCELLED":
        raise ForgeError("ejecucion CANCELLED: no se aceptan collect/advance "
                         "(crea una nueva con init)")


def bracket_cmd(*parts, cwd=None):
    return subprocess.run([sys.executable, BRACKET] + list(parts),
                          cwd=cwd or os.getcwd(), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _set_phase(run, target, trigger=""):
    state.transition(run, target, trigger)
    save_forge(run)
    ledger.append(run["dir"], "phase", "%s (%s)" % (target, trigger),
                  refs={"phase": target})


# ============================================================ commands: core
def cmd_plan(args):
    r = bracket_cmd("plan", "--agents", str(args.agents or 100),
                    "--wave", str(args.wave))
    print(r.stdout, end="")
    try:
        out = subprocess.run(
            [sys.executable, BRACKET, "plan", "--agents", str(args.agents or 100),
             "--wave", str(args.wave), "--json"],
            text=True, stdout=subprocess.PIPE).stdout
        data = json.loads(out)
        print("presupuesto: %d llamadas subagente en %d olas de %d "
              "(+1 si hay baseline). Coste monetario NO medible: el proveedor no "
              "expone tokens por API; limites reales = llamadas/olas/tiempo."
              % (data["calls"], data["waves"], args.wave))
    except (ValueError, KeyError):
        pass
    print("no se inicia ningun agente en `plan`. Perfiles: quick|standard|extreme "
          "(extreme exige confirmacion explicita).")
    return r.returncode


def cmd_init(args):
    n = args.quick and 4 or (args.agents or (100 if args.mode == "answer" else 4))
    if args.mode not in ("answer", "patch"):
        raise ForgeError("--mode debe ser answer o patch")
    profile = getattr(args, "profile", None) or "standard"
    if profile == "extreme" and not getattr(args, "confirm", False):
        raise ForgeError("perfil extreme exige --confirm (plan y presupuesto "
                         "explicitos). Nada fue creado.")
    parts = ["init", "--agents", str(n)]
    if args.seed is not None:
        parts += ["--seed", str(args.seed)]
    task = ""
    if args.task_file:
        with open(args.task_file, encoding="utf-8") as fh:
            task = fh.read()
        parts += ["--task-file", os.path.abspath(args.task_file)]
    elif args.task:
        task = args.task
        parts += ["--task", args.task]
    else:
        raise ForgeError("pasa --task o --task-file")
    if args.baseline_file:
        parts += ["--baseline-file", os.path.abspath(args.baseline_file)]
    parts += ["--wave", str(args.wave)]
    if args.dir:
        parts += ["--dir", os.path.abspath(args.dir)]
    r = bracket_cmd(*parts)
    print(r.stdout, end="")
    if r.returncode != 0:
        return r.returncode

    d = os.path.abspath(args.dir) if args.dir else run_dir_from(args)
    suite_sha = None
    if args.suite:
        if not gate_engine.suite_files(args.suite):
            raise ForgeError("suite inexistente (sin test_*.py): %s" % args.suite)
        suite_sha = gate_engine.suite_sha(args.suite)
    baseline_commit = "n/a-no-repo"
    try:
        c = subprocess.run(["git", "rev-parse", "HEAD"], text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if c.returncode == 0:
            baseline_commit = c.stdout.strip()
    except OSError:
        pass

    run = {
        "version": FORGE_VERSION, "schema_version": FORGE_VERSION,
        "run_id": _run_id(d), "mode": args.mode, "status": "INITIALIZED",
        "phase": "INITIALIZED", "dir": d, "seed": args.seed, "agents": n,
        "wave": args.wave, "task": task, "task_sha": sha_text(task),
        "rubric_sha": sha_file(os.path.join(d, "rubric.md")),
        "cards_sha": sha_file(STRATEGIES),
        "suite": os.path.abspath(args.suite) if args.suite else None,
        "suite_sha": suite_sha, "baseline_commit": baseline_commit,
        "baseline_ref": baseline_commit,
        "scope": getattr(args, "scope", None) or "no declarado",
        "non_goals": getattr(args, "non_goals", None) or "no declarados",
        "policy_version": POLICY_VERSION, "budget": agent_e.budget_for(profile),
        "calls_spent": 0, "candidates": {}, "approvals": [], "not_run": [],
        "created": int(time.time()), "events": [],
    }
    save_forge(run)
    ledger.append(d, "init", "mode=%s agents=%d profile=%s"
                  % (args.mode, n, profile),
                  refs={"task_sha": run["task_sha"], "suite_sha": suite_sha})
    _set_phase(run, "INITIALIZED", "init")

    if args.mode == "patch":
        _prepare_patch(run, d, args)
    print("forge: %s [%s, %s]" % (os.path.join(d, FORGE_FILE), args.mode,
                                  run.get("phase")))
    return 0


def _prepare_patch(run, d, args):
    """Crea workspaces aislados por candidato y registra la prueba de aislamiento."""
    n = getattr(args, "agents", None) or 4
    baseline_dir = getattr(args, "baseline_dir", None)
    ids = ["cand-%02d" % (i + 1) for i in range(n)]
    if os.path.isdir(os.path.join(d, "candidates")):
        existing = sorted(x for x in os.listdir(os.path.join(d, "candidates"))
                          if os.path.isdir(os.path.join(d, "candidates", x)))
        if existing:
            ids = existing
    proof = isolation.ensure_workspaces(d, ids)
    # baseline copia local para diffs controlados
    src = os.path.abspath(baseline_dir) if baseline_dir else None
    if src and os.path.isdir(src):
        bdir = os.path.join(d, "baseline")
        os.makedirs(bdir, exist_ok=True)
        for name in os.listdir(src):
            s = os.path.join(src, name)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(bdir, name))
    # Cada candidato arranca desde el mismo baseline (§2 Modo B paso 4).
    for cid in ids:
        cdir = os.path.join(d, "candidates", cid)
        if src and os.path.isdir(src):
            for name in os.listdir(src):
                s = os.path.join(src, name)
                if os.path.isfile(s) and not name.lower().endswith((".pyc",)):
                    shutil.copy2(s, os.path.join(cdir, name))
    atomic_write_json(os.path.join(d, "isolation.json"), proof)
    ledger.append(d, "isolation", "candidates=%d ok=%s" % (len(ids), proof["ok"]),
                  refs={"proof": "isolation.json"})
    run["candidates"] = {cid: {"candidate_id": cid, "run_id": run["run_id"],
                               "strategy_id": None, "prompt_hash": None,
                               "baseline_hash": run.get("baseline_commit"),
                               "workspace_ref": os.path.join("candidates", cid),
                               "isolation_verified": proof["ok"],
                               "status": "PENDING", "eligible": None}
                         for cid in ids}
    save_forge(run)
    _set_phase(run, "PREPARING", "workspaces")
    _set_phase(run, "READY", "harness listo")
    print("patch: %d workspaces aislados; aislamiento ok=%s" % (len(ids), proof["ok"]))


def cmd_next(args):
    d = run_dir_from(args)
    run = load_forge(d)
    print("forge: phase=%s status=%s mode=%s"
          % (run.get("phase"), run.get("status"), run.get("mode")))
    r = bracket_cmd("next", "--dir", d)
    print(r.stdout, end="")
    # estado del harness (patch)
    if run.get("mode") == "patch":
        gates = _load(os.path.join(d, "gates.json")) or {}
        print("harness patch: %d candidatos, gates=%s"
              % (len(run.get("candidates", {})),
                 {c: g.get("state") for c, g in gates.items()} or "sin ejecutar"))
    return r.returncode


def cmd_passthrough(name, args, extra=()):
    d = run_dir_from(args)
    run = load_forge(d)
    if name in ("collect", "advance"):
        guard_mutable(run)
        acquire_lock(d)
        try:
            if name == "collect":
                quarantine_oversize(d)
            r = bracket_cmd(name, "--dir", d, *extra)
            print(r.stdout, end="")
            log_event(run, name, "rc=%d" % r.returncode)
            if name == "advance" and run.get("phase") in ("READY", "INITIALIZED"):
                _set_phase(run, "RUNNING", "torneo arrancado")
            return r.returncode
        finally:
            release_lock(d)
    r = bracket_cmd(name, "--dir", d, *extra)
    print(r.stdout, end="")
    if name == "winner":
        log_event(run, "winner", "consultado")
    return r.returncode


def _load(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return None


# ============================================================ gates (patch)
def cmd_gates(args):
    d = run_dir_from(args)
    run = load_forge(d)
    if not run.get("suite"):
        raise ForgeError("esta ejecucion no tiene suite (modo answer o init sin --suite)")
    if run.get("mode") == "patch" and run.get("phase") in ("READY",):
        _set_phase(run, "RUNNING", "gates")
    log_dir = os.path.join(d, "artifacts", "logs")
    results = gate_engine.run_all(d, run["suite"], log_dir=log_dir)
    if not results:
        print("sin candidatos en %s" % os.path.join(d, "candidates"))
    for c, g in results.items():
        g["verdict"] = g["state"]          # alias legacy
        # actualizar Candidate contract
        cand = run.get("candidates", {}).setdefault(c, {})
        cand.setdefault("candidate_id", c)
        cand.setdefault("run_id", run["run_id"])
        cand.setdefault("workspace_ref", os.path.join("candidates", c))
        cand["isolation_verified"] = True
        cand["status"] = "EVALUATED"
        cand["eligible"] = (g["state"] == "PASS")
        print("%s: %s (exit=%s)" % (c, g["state"], g.get("exit_code")))
    atomic_write_json(os.path.join(d, "gates.json"), results)
    save_forge(run)
    ledger.append(d, "gates", "evaluados=%d" % len(results),
                  refs={"gates": "gates.json"})
    if run.get("phase") in ("RUNNING", "READY"):
        _set_phase(run, "EVALUATING", "gates ejecutados")
    return 0


# ============================================================ resume / cancel
def cmd_resume(args):
    d = run_dir_from(args)
    run = load_forge(d)
    if run.get("phase") == "CANCELLED":
        raise ForgeError("CANCELLED: crea una nueva ejecucion con init")
    ok, problems = ledger.verify(d)
    if not ok:
        print("ledger: %d problema(s) -> se conserva y se registra" % len(problems))
    before = {}
    arena_path = os.path.join(d, "arena.json")
    if os.path.isfile(arena_path):
        st = _load(arena_path) or {}
        for rd in st.get("rounds", []):
            for m in rd.get("matches", []):
                if m.get("winner"):
                    before[m["id"]] = m["winner"]
    print("completados persistidos: %d matches con ganador; ledger seq=%s"
          % (len(before), ledger.last_ref(d)))
    r = bracket_cmd("next", "--dir", d)
    print(r.stdout, end="")
    log_event(run, "resume", "%d completados intactos" % len(before))
    return r.returncode


def cmd_cancel(args):
    d = run_dir_from(args)
    run = load_forge(d)
    try:
        _set_phase(run, "CANCELLED", args.reason or "cancelado por el usuario")
    except ForgeError:
        run["phase"] = run["status"] = "CANCELLED"
        save_forge(run)
        ledger.append(d, "cancel", args.reason or "")
    # procesos no detenidos: se registran (no hay hijos persistentes aqui)
    ledger.append(d, "processes", "ninguno persistente no detenido", actor="runtime")
    print("CANCELLED %s (artefactos conservados)" % d)
    return 0


# ============================================================ report / apply
def resolve_patch_winner(d, run, gates):
    """Compat + contrato: (candidate|None, reason). Acepta 'state' o 'verdict'."""
    def _pass(g):
        return (g.get("state") or g.get("verdict")) == "PASS"
    eligible = sorted(c for c, g in gates.items() if _pass(g))
    if not eligible:
        return None, "ningun candidato supera los gates obligatorios"
    pj = _load(os.path.join(d, "patch_judge.json"))
    if not pj or pj.get("_malformed"):
        if not gates:
            return None, "sin gates ejecutados"
        return None, ("%d elegibles sin desempate ciego; el score no puede elegir "
                      "solo" % len(eligible))
    label_map = {"X": None, "Y": None}
    label_map.update(_load(os.path.join(d, "patch_map.json")) or {})
    if not label_map.get("X") and len(eligible) >= 1:
        label_map["X"] = eligible[0]
    if not label_map.get("Y") and len(eligible) >= 2:
        label_map["Y"] = eligible[1]
    cand = label_map.get(str(pj.get("winner", "")).upper())
    if cand and cand in eligible:
        return cand, ("gates PASS + juez ciego: %s" % (pj.get("reason") or ""))
    return None, "veredicto ciego invalido o inelegible"


def cmd_report(args):
    d = run_dir_from(args)
    run = load_forge(d)
    data = report_mod.gather(d)
    data["candidates"] = run.get("candidates", {})
    decision, reason, eligible = report_mod.resolve(d, data)
    out = report_mod.write(d, REPORTS_DIR, data=data, decision=decision)
    if decision in ("WINNER", "NO_SHIP") and run.get("phase") not in TERMINAL:
        try:
            _set_phase(run, "REPORTING", "informe generado")
            _set_phase(run, "COMPLETED" if decision == "WINNER" else "NO_SHIP",
                       decision)
        except ForgeError:
            pass
    ledger.append(d, "decision", "%s: %s" % (decision, reason),
                  refs={"decision": decision})
    print("decision: %s (%s)" % (decision, reason))
    print("elegibles: %s" % (eligible or "-"))
    print("md: %s\nhtml: %s" % (out["md"], out["html"]))
    return 0


def cmd_apply(args):
    d = run_dir_from(args)
    run = load_forge(d)
    if not args.approve:
        raise ForgeError("rehusado: exige --approve explicito y aplica a mano. "
                         "Nada del proyecto fue modificado.")
    # verificar baseline sin cambios (§6.8)
    if run.get("baseline_commit") not in (None, "n/a-no-repo"):
        try:
            cur = subprocess.run(["git", "rev-parse", "HEAD"], text=True,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL).stdout.strip()
            if cur and cur != run["baseline_commit"]:
                raise ForgeError("baseline cambio (%s != %s); revisa antes de aplicar"
                                 % (cur, run["baseline_commit"]))
        except OSError:
            pass
    if run.get("mode") == "patch":
        gates = _load(os.path.join(d, "gates.json")) or {}
        champ, why = resolve_patch_winner(d, run, gates)
    else:
        champ = (_load(os.path.join(d, "arena.json")) or {}).get("champion")
    if not champ:
        raise ForgeError("sin campeon: nada que aplicar (NO_SHIP)")
    cdir = os.path.join(d, "candidates", champ)
    base = os.path.join(d, "baseline")
    patch_lines = []
    if os.path.isdir(cdir) and os.path.isdir(base):
        patch_lines = [isolation.capture_diff(base, cdir)]
    elif os.path.isdir(cdir):
        for name in sorted(os.listdir(cdir)):
            p = os.path.join(cdir, name)
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    patch_lines.append("--- /dev/null\n+++ b/%s\n%s" % (name, fh.read()))
    out = os.path.join(REPORTS_DIR, os.path.basename(d) + ".patch")
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("".join(patch_lines) or "# sin diffs (modo answer)\n")
    ledger.append(d, "apply", "parche preparado (sin mutar el proyecto)",
                  refs={"patch": os.path.relpath(out, HERE)}, actor="human")
    print("parche preparado (SOLO archivo, proyecto intacto): %s" % out)
    print("revisa, luego: git apply --check %s" % out)
    return 0


# ============================================================ E / state / ledger
def cmd_adapter(args):
    if args.probe:
        version, raw = adapter.detect_version()
        caps = adapter.probe(version)
        print("probe: version=%s (%s)" % (version, raw))
    else:
        caps = adapter.load_capabilities()
        version, _ = adapter.detect_version()
    print("opencode: %s" % (version or "no detectado"))
    for name in adapter.REQUIRED_CAPABILITIES:
        e = caps.get(name, {"status": "unknown"})
        print("  %-22s %-10s %s" % (name, e.get("status"), e.get("evidence", "")))
    print("resumen: %s" % adapter.summary(caps))
    return 0


def cmd_state(args):
    d = run_dir_from(args)
    run = load_forge(d)
    cur = run.get("phase") or run.get("status")
    print("run %s: phase=%s status=%s mode=%s"
          % (run.get("run_id"), cur, run.get("status"), run.get("mode")))
    nxt = [t for t in state.STATES if state.can_transition(cur, t)[0] and t != cur]
    print("transiciones legales: %s" % ", ".join(nxt) or "(ninguna)")
    print("terminal: %s" % state.is_terminal(cur))
    return 0


def cmd_ledger(args):
    d = run_dir_from(args)
    if args.verify:
        ok, problems = ledger.verify(d)
        print("ledger verify: %s" % ("OK" if ok else "PROBLEMAS"))
        for p in problems:
            print("  - %s" % p)
        return 0 if ok else 1
    for ev in ledger.read(d):
        print("#%-4s %s %-16s %s" % (ev.get("seq"), ev.get("ts"),
                                      ev.get("kind"), ev.get("detail")))
    return 0


def cmd_decide(args):
    d = run_dir_from(args)
    run = load_forge(d)
    decision = agent_e.step(d, run)
    print("E decision: %s -> %s (riesgo %s)"
          % (decision["action_type"], decision["reason"], decision["risk_level"]))
    print("cost_estimate: %s | presupuesto restante (calls): %s"
          % (decision["cost_estimate"], decision["budget_remaining"]))
    return 0


def cmd_decisions(args):
    d = run_dir_from(args)
    for dec in agent_e.history(d):
        print("%s [%s] %s -> %s" % (dec.get("timestamp"), dec.get("action_type"),
                                    dec.get("decision_id"), dec.get("reason")))
    return 0


def cmd_isolation(args):
    d = run_dir_from(args)
    proof = _load(os.path.join(d, "isolation.json"))
    if not proof:
        print("sin isolation.json (no es un run patch o no se preparo)")
        return 1
    print("root=%s ok=%s shared=%s" % (proof.get("root"), proof.get("ok"),
                                       proof.get("shared")))
    for cid, info in proof.get("candidates", {}).items():
        print("  %-10s %s" % (cid, info.get("realpath")))
    for p in proof.get("problems", []):
        print("  PROBLEMA: %s" % p)
    return 0 if proof.get("ok") else 1


# ============================================================ verify / bench
def cmd_verify(args):
    d = run_dir_from(args) if (args.dir or os.path.isfile(os.path.join(ROOT, LATEST))) else None
    checks = []

    # adapter
    caps = adapter.load_capabilities()
    verified = adapter.summary(caps).get("verified", 0)
    checks.append(("adapter: capacidades verificadas=%d" % verified, verified > 0))

    if d:
        run = load_forge(d)
        # contratos
        errs = contracts.validate_run(run)
        checks.append(("Run contract: %s" % ("OK" if not errs else errs), not errs))
        # ledger
        ok, problems = ledger.verify(d)
        checks.append(("ledger append-only: %s" % ("OK" if ok else problems), ok))
        # suite integrity
        suite = run.get("suite")
        if suite and gate_engine.suite_files(suite):
            same = gate_engine.suite_sha(suite) == run.get("suite_sha")
            checks.append(("suite sha sin cambios", same))
        elif suite and not os.path.exists(suite):
            checks.append(("suite: NOT_RUN (ausente)", False))
        else:
            checks.append(("suite: NOT_RUN (sin suite)", False))
        # aislamiento
        if run.get("mode") == "patch":
            proof = _load(os.path.join(d, "isolation.json")) or {}
            checks.append(("aislamiento: ok=%s" % proof.get("ok"), bool(proof.get("ok"))))
        # gates -> decision coherente
        data = report_mod.gather(d)
        decision, reason, _ = report_mod.resolve(d, data)
        gates = data["gates"]
        if run.get("mode") == "patch" and gates:
            any_pass = any((g.get("state") or g.get("verdict")) == "PASS"
                           for g in gates.values())
            checks.append(("gates preceden al score: decision=%s" % decision,
                           (decision == "WINNER") == any_pass))
    ok_all = all(c[1] for c in checks)
    print("verify: %s" % ("OK" if ok_all else "PROBLEMAS"))
    for msg, ok in checks:
        print("  [%s] %s" % ("PASS" if ok else "FAIL", msg))
    return 0 if ok_all else 1


def cmd_bench(args):
    res = bench_mod.run(sizes=(4, 8), seed=args.seed or 7)
    md = bench_mod.to_markdown(res)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    out = os.path.join(REPORTS_DIR, "benchmark.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    print("informe: %s" % out)
    return 0 if res.get("deterministic_ok") else 1


# ============================================================ benchmark (legacy)
def cmd_benchmark(args):
    """Legacy: scheduler + gates del fixture (compat)."""
    return cmd_bench(argparse.Namespace(seed=7))


def load_bracket_module():
    spec = importlib.util.spec_from_file_location("forge_bracket", BRACKET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def simulate_tournament(mod, n, seed):
    """Cartas sin repetir (n <= combo), emparejamientos legales, cierre unico."""
    data = mod.load_strategies(STRATEGIES)
    if not (1 <= n <= mod.combo_count(data)):
        return False, "n fuera de rango"
    cards = mod.deal(n, seed, data)
    if len(set(cards)) != n:
        return False, "cartas duplicadas"
    sizes = mod.bracket_sizes(n)
    if sizes[0] != n or sizes[-1] != 1:
        return False, "bracket %r" % (sizes,)
    return True, "bracket %s" % ("->".join(str(s) for s in sizes))


# ============================================================ CLI
def build_parser():
    p = argparse.ArgumentParser(prog="arena_forge.py", description="Arena Forge")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    s = sub.add_parser("plan", help="estimacion sin escribir archivos")
    s.add_argument("--agents", type=int, default=100)
    s.add_argument("--wave", type=int, default=10)
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("init", help="crear ejecucion unica e inmutable")
    s.add_argument("--mode", default="answer", choices=("answer", "patch"))
    s.add_argument("--agents", type=int)
    s.add_argument("--quick", action="store_true")
    s.add_argument("--seed", type=int)
    s.add_argument("--task"); s.add_argument("--task-file")
    s.add_argument("--baseline-file"); s.add_argument("--baseline-dir")
    s.add_argument("--suite"); s.add_argument("--scope"); s.add_argument("--non-goals")
    s.add_argument("--profile", choices=("quick", "standard", "extreme"),
                   default="standard")
    s.add_argument("--confirm", action="store_true")
    s.add_argument("--wave", type=int, default=10); s.add_argument("--dir")
    s.set_defaults(func=lambda a: cmd_init(_expand_quick(a)))

    for name, hlp in (("next", "siguiente fase"), ("status", "estado"),
                      ("collect", "registrar veredictos"),
                      ("advance", "cerrar ronda"),
                      ("prompts", "briefs pendientes"),
                      ("check", "outputs ausentes"),
                      ("pairings", "emparejamientos"),
                      ("winner", "campeon")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("--dir")
        if name in ("prompts", "check"):
            s.add_argument("phase", choices=("spawn", "attack", "defend", "judge", "final"))
            s.set_defaults(func=lambda a, n=name: cmd_passthrough(n, a, (a.phase,)))
        else:
            s.set_defaults(func=lambda a, n=name: cmd_passthrough(n, a))

    s = sub.add_parser("card", help="tarjeta de un competidor")
    s.add_argument("--dir"); s.add_argument("agent_id")
    s.set_defaults(func=lambda a: cmd_passthrough("card", a, (a.agent_id,)))

    s = sub.add_parser("record", help="registrar un match a mano")
    s.add_argument("--dir"); s.add_argument("match_id"); s.add_argument("winner_id")
    s.add_argument("--reason", default="")
    s.set_defaults(func=lambda a: cmd_passthrough(
        "record", a, (a.match_id, a.winner_id, "--reason", a.reason)))

    s = sub.add_parser("gates", help="evaluar candidatos (patch)")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_gates)

    s = sub.add_parser("resume", help="reanudar sin repetir lo completado")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_resume)

    s = sub.add_parser("cancel", help="cancelar conservando artefactos")
    s.add_argument("--dir"); s.add_argument("--reason", default="")
    s.set_defaults(func=cmd_cancel)

    s = sub.add_parser("report", help="informe Markdown + HTML estatico")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("apply", help="preparar parche (exige --approve)")
    s.add_argument("--dir"); s.add_argument("--approve", action="store_true")
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("adapter", help="capacidades del runtime OpenCode V2")
    s.add_argument("--probe", action="store_true")
    s.set_defaults(func=cmd_adapter)

    s = sub.add_parser("state", help="fase y transiciones legales")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_state)

    s = sub.add_parser("ledger", help="historial append-only (--verify)")
    s.add_argument("--dir"); s.add_argument("--verify", action="store_true")
    s.set_defaults(func=cmd_ledger)

    s = sub.add_parser("decide", help="un paso del agente E")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_decide)

    s = sub.add_parser("decisions", help="historial de decisiones de E")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_decisions)

    s = sub.add_parser("isolation", help="prueba de aislamiento (patch)")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_isolation)

    s = sub.add_parser("verify", help="comprobaciones de integridad")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("bench", help="benchmark runner (comparativo honesto)")
    s.add_argument("--seed", type=int)
    s.set_defaults(func=cmd_bench)

    s = sub.add_parser("benchmark", help="(legacy) scheduler + gates del fixture")
    s.set_defaults(func=cmd_benchmark)
    return p


def _expand_quick(a):
    if getattr(a, "quick", False):
        a.agents = getattr(a, "agents", None) or 4
    return a


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ForgeError as exc:
        print("forge error: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())

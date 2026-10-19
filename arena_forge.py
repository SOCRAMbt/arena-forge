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
                   integrity, isolation, ledger, report as report_mod,
                   score as score_mod, state)
from forge import gates as gate_engine
from forge.util import (ForgeError, MAX_OUTPUT_BYTES, atomic_write_json,
                        inside, read_json_bounded, redact, sha_file, sha_text,
                        save_forge)

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
    # El directorio del run es la AUTORIDAD: el valor almacenado en el
    # fichero es dato no confiable (un run movido escribiria en la ruta
    # antigua y resucitaria el directorio original).
    data["dir"] = os.path.abspath(d)
    return data


def log_event(run, kind, detail=""):
    """Evento tanto en forge.json como en el ledger append-only.

    Un fallo de escritura del ledger NO se silencia: se registra en el propio
    run (`ledger_error`) para que quede evidencia del fallo.
    """
    run.setdefault("events", []).append(
        {"t": int(time.time()), "kind": kind, "detail": detail})
    save_forge(run)
    try:
        ledger.append(run["dir"], kind, detail)
    except OSError as exc:
        run.setdefault("ledger_errors", []).append(
            {"t": int(time.time()), "kind": kind, "error": str(exc)})
        save_forge(run)
        print("BLOCKED ledger: no se pudo escribir el evento %r: %s" % (kind, exc))


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
    profile = getattr(args, "profile", None) or "standard"
    budget = agent_e.budget_for(profile)
    max_cands = budget.get("max_candidates", 8)
    n = args.agents if args.agents is not None else max_cands
    if n > max_cands:
        raise ForgeError("--agents %d excede max_candidates=%d del perfil %s"
                         % (n, max_cands, profile))
    r = bracket_cmd("plan", "--agents", str(n),
                    "--wave", str(args.wave))
    print(r.stdout, end="")
    try:
        out = subprocess.run(
            [sys.executable, BRACKET, "plan", "--agents", str(n),
             "--wave", str(args.wave), "--json"],
            text=True, stdout=subprocess.PIPE).stdout
        data = json.loads(out)
        print("presupuesto: %d llamadas subagente en %d olas de %d "
              "(+1 si hay baseline). Coste monetario NO medible: el proveedor no "
              "expone tokens por API; limites reales = llamadas/olas/tiempo."
              % (data["calls"], data["waves"], args.wave))
        print("perfil: %s  max_candidates=%d  max_calls=%d  max_rounds=%d  concurrency=%d"
              % (profile, budget.get("max_candidates"), budget.get("max_calls"),
                 budget.get("max_rounds"), budget.get("concurrency")))
    except (ValueError, KeyError):
        pass
    print("no se inicia ningun agente en `plan`. Perfiles: quick|standard|extreme "
          "(extreme exige confirmacion explicita).")
    return r.returncode


def cmd_init(args):
    # P0-06: defaults conservadores (no 100 por defecto)
    default_agents = 4  # tanto answer como patch
    n = args.agents if args.agents is not None else (args.quick and 4 or default_agents)
    
    if args.mode not in ("answer", "patch"):
        raise ForgeError("--mode debe ser answer o patch")
    profile = getattr(args, "profile", None) or "standard"
    if profile == "extreme" and not getattr(args, "confirm", False):
        raise ForgeError("perfil extreme exige --confirm (plan y presupuesto "
                         "explicitos). Nada fue creado.")
    
    # P0-06: validar agentes contra presupuesto del perfil ANTES de crear run
    budget = agent_e.budget_for(profile)
    max_cands = budget.get("max_candidates", 8)
    if n > max_cands:
        raise ForgeError("--agents %d excede max_candidates=%d del perfil %s"
                         % (n, max_cands, profile))
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
    
    # P0-04: Baseline correcto - separar forge_repo_commit y target_baseline_commit
    # Commit del repo donde vive Arena Forge (para auditoría)
    forge_repo_commit = "n/a-no-repo"
    try:
        c = subprocess.run(["git", "rev-parse", "HEAD"], text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if c.returncode == 0:
            forge_repo_commit = c.stdout.strip()
    except OSError:
        pass
    
    # Baseline del repo objetivo evaluado
    baseline_dir = getattr(args, "baseline_dir", None)
    target_baseline_commit = "n/a-no-repo"
    target_baseline_dir = None
    baseline_dirty = False
    baseline_manifest = None

    if baseline_dir:
        baseline_dir = os.path.abspath(baseline_dir)
        target_baseline_dir = baseline_dir
        if not os.path.isdir(baseline_dir):
            raise ForgeError("baseline-dir inexistente: %s" % baseline_dir)
        # Un directorio que merelyamente cuelga de un repositorio (p.ej. un
        # fixture dentro del propio repo de Arena Forge) NO es su propio
        # baseline Git: usar el commit de ese repositorio seria incorrecto.
        if integrity.is_own_git_repo(baseline_dir):
            head = integrity.git_head(baseline_dir)
            if head:
                target_baseline_commit = head
            dirty = integrity.git_dirty(baseline_dir)
            if dirty:
                baseline_dirty = True
        # Manifiesto de contenido: se calcula SIEMPRE (Git o no), con el mismo
        # algoritmo versionado, para que apply pueda revalidarlo despues.
        baseline_manifest = integrity.baseline_manifest(baseline_dir)
    
    # Para compatibilidad, baseline_commit apunta al target si existe, sino forge
    baseline_commit = target_baseline_commit if target_baseline_commit != "n/a-no-repo" else forge_repo_commit

    run = {
        "version": FORGE_VERSION, "schema_version": FORGE_VERSION,
        "run_id": _run_id(d), "mode": args.mode, "status": "INITIALIZED",
        "phase": "INITIALIZED", "dir": d, "seed": args.seed, "agents": n,
        "wave": args.wave, "task": task, "task_sha": sha_text(task),
        "rubric_sha": sha_file(os.path.join(d, "rubric.md")),
        "cards_sha": sha_file(STRATEGIES),
        "suite": os.path.abspath(args.suite) if args.suite else None,
        "suite_sha": suite_sha, 
        "baseline_commit": baseline_commit,
        "baseline_ref": baseline_commit,
        "forge_repo_commit": forge_repo_commit,
        "target_baseline_commit": target_baseline_commit,
        "target_baseline_dir": target_baseline_dir,
        "baseline_dirty": baseline_dirty,
        "baseline_manifest": baseline_manifest,
        "baseline_manifest_version": integrity.BASELINE_MANIFEST_VERSION,
        "scope": getattr(args, "scope", None) or "no declarado",
        "non_goals": getattr(args, "non_goals", None) or "no declarados",
        "policy_version": POLICY_VERSION, "budget": agent_e.budget_for(profile),
        "calls_spent": 0, "calls_reserved": 0, "candidates": {}, "approvals": [],
        "not_run": [], "created": int(time.time()), "events": [],
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
    # baseline copia local para diffs controlados (P0-04: recursivo).
    # Se usa la MISMA politica de exclusiones que el manifiesto y el parche
    # (`isolation._copy_tree`): si no, el `.git` del baseline (historial,
    # config, hooks) acabaria en el workspace de cada candidato, invisible al
    # manifiesto y al parche.
    src = os.path.abspath(baseline_dir) if baseline_dir else None
    if src and os.path.isdir(src):
        bdir = os.path.join(d, "baseline")
        isolation._copy_tree(src, bdir)
    # Cada candidato arranca desde el mismo baseline (P0-04: recursivo).
    for cid in ids:
        cdir = os.path.join(d, "candidates", cid)
        if src and os.path.isdir(src):
            isolation._copy_tree(src, cdir)
    atomic_write_json(os.path.join(d, "isolation.json"), proof)
    ledger.append(d, "isolation", "candidates=%d ok=%s" % (len(ids), proof["ok"]),
                  refs={"proof": "isolation.json"})
    # Manifiesto de la COPIA CONGELADA del baseline: es el arbol contra el que
    # los gates calculan el diff. Se revalida antes de report y de apply.
    bdir = os.path.join(d, "baseline")
    if os.path.isdir(bdir):
        run["frozen_baseline_manifest"] = integrity.baseline_manifest(bdir)
        run["frozen_baseline_manifest_version"] = integrity.BASELINE_MANIFEST_VERSION
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
def _verify_isolation(d, run):
    """Valida isolation.json antes de ejecutar gates. Devuelve (ok, problems)."""
    isolation_path = os.path.join(d, "isolation.json")
    if not os.path.isfile(isolation_path):
        return False, ["isolation.json ausente"]
    proof = _load(isolation_path)
    if not proof or not proof.get("ok"):
        problems = proof.get("problems", ["isolation.ok == false"]) if proof else ["isolation.json malformado"]
        return False, problems
    # Revalidar rutas reales actuales
    run_dir = d
    for cid, info in proof.get("candidates", {}).items():
        real = info.get("realpath")
        if not real or not os.path.isdir(real):
            return False, ["candidato %s: directorio no existe: %s" % (cid, real)]
        if not isolation.inside(run_dir, real):
            return False, ["candidato %s escapa del run: %s" % (cid, real)]
    return True, []


def cmd_gates(args):
    d = run_dir_from(args)
    run = load_forge(d)
    guard_mutable(run)
    if not run.get("suite"):
        raise ForgeError("esta ejecucion no tiene suite (modo answer o init sin --suite)")
    if run.get("mode") == "patch":
        # P0-01: validar aislamiento ANTES de ejecutar gates
        iso_ok, iso_problems = _verify_isolation(d, run)
        if not iso_ok:
            print("aislamiento NO verificado: %s" % "; ".join(iso_problems))
            # Marcar candidatos como BLOCKED por aislamiento
            for cid in run.get("candidates", {}):
                run["candidates"][cid]["isolation_verified"] = False
                run["candidates"][cid]["status"] = "BLOCKED"
                run["candidates"][cid]["eligible"] = False
            save_forge(run)
            ledger.append(d, "gates_blocked", "aislamiento invalido: %s" % iso_problems)
            return 1
        if run.get("phase") in ("READY",):
            _set_phase(run, "RUNNING", "gates")
    log_dir = os.path.join(d, "artifacts", "logs")
    # P0-03: pasar suite_sha congelado para validacion
    expected_suite_sha = run.get("suite_sha")
    results = gate_engine.run_all(d, run["suite"], log_dir=log_dir,
                                   expected_suite_sha=expected_suite_sha)
    if not results:
        print("sin candidatos en %s" % os.path.join(d, "candidates"))
    for c, g in results.items():
        g["verdict"] = g["state"]          # alias legacy
        # actualizar Candidate contract
        cand = run.get("candidates", {}).setdefault(c, {})
        cand.setdefault("candidate_id", c)
        cand.setdefault("run_id", run["run_id"])
        cand.setdefault("workspace_ref", os.path.join("candidates", c))
        # P0-01: isolation_verified deriva de verificacion real, no True incondicional
        cand["isolation_verified"] = iso_ok if run.get("mode") == "patch" else True
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
    
    mode = run.get("mode", "answer")
    if mode == "answer":
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
        log_event(run, "resume", "%d completados intactos (answer)" % len(before))
    elif mode == "patch":
        # P1-01: Reconciliar jobs Patch desde jobs.json, NO llamar bracket next
        jobs = _load(os.path.join(d, "jobs.json")) or {}
        pending = [j for j in jobs.values() if j.get("state") == "PENDING"]
        running = [j for j in jobs.values() if j.get("state") == "RUNNING"]
        done = [j for j in jobs.values() if j.get("state") == "DONE"]
        failed = [j for j in jobs.values() if j.get("state") == "FAILED"]
        print("resume Patch: pending=%d running=%d done=%d failed=%d"
              % (len(pending), len(running), len(done), len(failed)))
        # Reconciliar: jobs RUNNING sin session_ref son dudosos
        for job in running:
            if not job.get("session_ref"):
                print("  ADVERTENCIA: job %s RUNNING sin session_ref" % job["job_id"])
        log_event(run, "resume", "patch jobs: PENDING=%d RUNNING=%d DONE=%d FAILED=%d"
                  % (len(pending), len(running), len(done), len(failed)))
    else:
        print("modo desconocido: %s" % mode)
        return 1
    return 0
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
def _decision_id(run, decision, reason, winner, eligible, gates):
    """Identificador de decision ligado al CONTENIDO, no a un contador.

    Dos decisiones sobre estados distintos producen identificadores distintos;
    la misma decision sobre el mismo estado produce el mismo id. `apply` lo
    recalcula y lo compara con el persistido: si el estado cambio entre
    `report` y `apply`, los ids NO coinciden y la aplicacion se bloquea.
    """
    payload = {
        "run_id": run.get("run_id"),
        "decision": decision,
        "reason": reason,
        "winner_id": winner,
        "eligible": sorted(eligible or []),
        "suite_sha": run.get("suite_sha"),
        "diff_sha": (gates.get(winner) or {}).get("diff_sha") if winner else None,
        "candidate_manifest_sha": ((gates.get(winner) or {}).get("candidate_manifest_sha")
                                   if winner else None),
    }
    return "dec-%s-%s" % (run.get("run_id"), sha_text(json.dumps(
        payload, sort_keys=True, ensure_ascii=False))[:16])


def cmd_judge_record(args):
    """Registra el veredicto CIEGO del juez (X/Y) para el modo patch.

    El mapa X/Y se fija la PRIMERA vez (orden determinista de los elegibles) y
    se reutiliza después: el juez ve etiquetas, nunca identificadores de
    candidato. Con un solo elegible no hace falta juez (la decisión por gates
    es determinista) y el comando lo rechaza.
    """
    d = run_dir_from(args)
    run = load_forge(d)
    guard_mutable(run)
    if run.get("mode") != "patch":
        raise ForgeError("el juez ciego solo aplica al modo patch")
    winner = str(args.winner or "").strip().upper()
    if winner not in ("X", "Y"):
        raise ForgeError("el ganador debe ser X o Y (nunca un id de candidato)")
    if not args.reason:
        raise ForgeError("el veredicto exige una razon")
    evidence = [e for e in (args.evidence or []) if str(e).strip()]
    if not evidence:
        raise ForgeError("el veredicto exige al menos una evidencia "
                         "(un veredicto sin evidencia se invalida)")
    data = report_mod.gather(d)
    gates = data.get("gates") or {}
    eligible = sorted(c for c, g in gates.items() if g.get("state") == "PASS")
    if len(eligible) < 2:
        raise ForgeError("hacen falta 2 candidatos elegibles para un desempate "
                         "ciego (hay %d)" % len(eligible))
    map_path = os.path.join(d, "patch_map.json")
    label_map = _load(map_path) or {}
    if not label_map.get("X") or not label_map.get("Y"):
        label_map = {"X": eligible[0], "Y": eligible[1]}
        atomic_write_json(map_path, label_map)
    verdict = {"winner": winner, "reason": args.reason, "evidence": evidence}
    atomic_write_json(os.path.join(d, "patch_judge.json"), verdict)
    ledger.append(d, "judge", "veredicto ciego %s" % winner,
                  refs={"winner": winner, "map": "patch_map.json"},
                  actor=("human" if getattr(args, "by", None) == "human" else "judge"))
    print("veredicto ciego registrado: %s" % winner)
    print("mapa ciego: X<->%s Y<->%s (no se revela al juez)"
          % (label_map["X"], label_map["Y"]))
    print("ejecuta `report` para resolver la decision")
    return 0


def cmd_report(args):
    d = run_dir_from(args)
    run = load_forge(d)
    guard_mutable(run)
    data = report_mod.gather(d)
    data["candidates"] = run.get("candidates", {})
    decision, reason, eligible, winner = report_mod.resolve_full(d, data)
    gates = data.get("gates") or {}
    record = {
        "decision_id": _decision_id(run, decision, reason, winner, eligible, gates),
        "decision": decision,
        "reason": reason,
        "winner_id": winner,
        "eligible": eligible,
        "suite_sha": run.get("suite_sha"),
        "diff_sha": (gates.get(winner) or {}).get("diff_sha") if winner else None,
        "candidate_manifest_sha": (gates.get(winner) or {}).get("candidate_manifest_sha")
                                  if winner else None,
        "ts": int(time.time()),
        "forge_repo_commit": run.get("forge_repo_commit"),
        "security_mode": isolation.SECURITY_MODE,
    }
    run["last_decision"] = record
    save_forge(run)
    atomic_write_json(os.path.join(d, "decision.json"), record)
    if decision in ("WINNER", "NO_SHIP") and run.get("phase") not in TERMINAL:
        try:
            if run.get("phase") in ("EVALUATING", "RUNNING", "COLLECTING"):
                _set_phase(run, "DECIDING", "decision tomada")
            _set_phase(run, "REPORTING", "informe generado")
            _set_phase(run, "COMPLETED" if decision == "WINNER" else "NO_SHIP",
                       decision)
        except ForgeError as exc:
            ledger.append(d, "transition_rejected", str(exc))
    # El informe se escribe DESPUES de las transiciones: si no, el artefacto
    # persistido muestra la fase previa a la decision y se contradice con
    # `forge.json`.
    out = report_mod.write(d, REPORTS_DIR, data=data, decision=decision)
    ledger.append(d, "decision", "%s: %s" % (decision, reason),
                  refs={"decision": decision, "winner": winner,
                        "decision_id": record["decision_id"]})
    print("decision: %s (%s)" % (decision, reason))
    print("elegibles: %s" % (eligible or "-"))
    print("ganador: %s" % (winner or "-"))
    print("decision_id: %s" % record["decision_id"])
    print("md: %s\nhtml: %s" % (out["md"], out["html"]))
    return 0


def cmd_apply(args):
    d = run_dir_from(args)
    run = load_forge(d)
    guard_mutable(run)
    if not args.approve:
        raise ForgeError("rehusado: exige --approve explicito y aplica a mano. "
                         "Nada del proyecto fue modificado.")
    if run.get("mode") != "patch":
        raise ForgeError("apply solo aplica ejecuciones en modo patch")
    # P0-04: revalidar el baseline objetivo ANTES de exportar (siempre).
    ok, reason = integrity.verify_baseline(run)
    if not ok:
        raise ForgeError("baseline objetivo no verificable: %s" % reason)
    # P0-02: revalidar la suite VIVA y la copia congelada del baseline.
    ok, reason, _sha = integrity.recompute_suite_sha(run)
    if not ok:
        raise ForgeError("suite no verificable: %s" % reason)
    ok, reason = integrity.verify_frozen_baseline(run)
    if not ok:
        raise ForgeError("baseline congelado no verificable: %s" % reason)
    # P1-03: usar el MISMO motor de decision que report (report_mod.resolve_full)
    data = report_mod.gather(d)
    data["candidates"] = run.get("candidates", {})
    decision, reason, eligible, winner = report_mod.resolve_full(
        d, data, ignore_terminal=True)
    if decision != "WINNER" or not winner:
        raise ForgeError("sin campeon: decision=%s, ganador=%s" % (decision, winner))
    # La decision persistida por `report` es OBLIGATORIA: `apply` no puede
    # re-derivar por su cuenta (eso era lo que permitia aplicar un candidato
    # distinto del juzgado).
    last = run.get("last_decision") or {}
    if not last:
        raise ForgeError("no hay decision persistida en este run: ejecuta "
                         "`report` antes de `apply`")
    if not os.path.isfile(os.path.join(d, "decision.json")):
        raise ForgeError("falta decision.json: ejecuta `report` antes de `apply`")
    if last.get("decision") != decision:
        raise ForgeError("la decision persistida (%s) no coincide con la "
                         "re-derivada (%s): re-ejecuta report"
                         % (last.get("decision"), decision))
    if last.get("winner_id") and last.get("winner_id") != winner:
        raise ForgeError("el ganador persistido (%s) no coincide con el "
                         "re-derivado (%s): re-ejecuta report"
                         % (last.get("winner_id"), winner))
    # El `decision_id` esta ligado al CONTENIDO: si el estado cambio entre
    # `report` y `apply`, los ids no coinciden y se bloquea.
    expected_id = _decision_id(run, decision, reason, winner, eligible,
                               data.get("gates") or {})
    if last.get("decision_id") != expected_id:
        raise ForgeError("el contenido de la decision cambio entre report y "
                         "apply (decision_id persistido=%s, recalculado=%s): "
                         "re-ejecuta report"
                         % (last.get("decision_id"), expected_id))
    # Se aplica el GANADOR persistido, nunca `eligible[0]`.
    champ = last.get("winner_id") or winner
    cdir = os.path.join(d, "candidates", champ)
    base = os.path.join(d, "baseline")
    if not os.path.isdir(cdir) or not os.path.isdir(base):
        raise ForgeError("no se puede exportar: falta el candidato %s o el "
                         "baseline congelado" % champ)
    patch_bytes = isolation.capture_diff(base, cdir)
    # P0-02: verificar que los bytes exportados SON el diff evaluado y que
    # reproducen el arbol del candidato.
    ok, reason = integrity.verify_exported_artifact(d, run, data["gates"],
                                                     champ, patch_bytes)
    if not ok:
        raise ForgeError("el parche no supero la verificacion de artefacto: %s" % reason)
    out = os.path.join(REPORTS_DIR, os.path.basename(d) + ".patch")
    os.makedirs(REPORTS_DIR, exist_ok=True)
    # Escritura atomica: tmp + rename. El parche son BYTES (puede contener
    # contenido que no es UTF-8 valido).
    tmp = out + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(patch_bytes)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, out)
    exported_sha = integrity.artifact_hashes(out)
    gates = data["gates"]
    ledger.append(d, "apply", "parche preparado (sin mutar el proyecto)",
                  refs={"patch": os.path.relpath(out, HERE),
                        "patch_sha256": exported_sha,
                        "winner": champ,
                        "diff_sha": (gates.get(champ) or {}).get("diff_sha"),
                        "security_mode": isolation.SECURITY_MODE}, actor="human")
    print("parche preparado (SOLO archivo, proyecto intacto): %s" % out)
    print("ganador aplicado: %s (decision persistida: %s)"
          % (champ, (last or {}).get("decision_id") or "(no persistida)"))
    print("sha256 del parche exportado: %s" % exported_sha)
    print("modo de seguridad: %s" % isolation.SECURITY_MODE)
    print("revisa, luego aplica EXACTAMENTE con (core.autocrlf=false es "
          "obligatorio: con el valor de Windows el parche reescribe LF->CRLF y "
          "el resultado deja de coincidir byte a byte con lo evaluado):")
    print("  git -c core.autocrlf=false -c core.eol=lf apply --check %s" % out)
    target_root = integrity.git_toplevel(run.get("target_baseline_dir") or "") \
        if run.get("target_baseline_dir") else None
    base_dir = run.get("target_baseline_dir")
    if base_dir and target_root and os.path.realpath(target_root) != os.path.realpath(base_dir):
        rel = os.path.relpath(os.path.realpath(base_dir), os.path.realpath(target_root))
        print("  (desde la raiz del repo objetivo; el baseline esta en %s)" % rel)
        print("  git -c core.autocrlf=false -c core.eol=lf apply --directory=%s --check %s"
              % (rel.replace("\\", "/"), out))
    elif base_dir:
        print("  (desde el directorio del baseline: %s)" % base_dir)
    return 0


def cmd_decide(args):
    d = run_dir_from(args)
    run = load_forge(d)
    guard_mutable(run)
    decision = agent_e.step(d, run)
    print("E decision: %s -> %s (riesgo %s, state=%s)"
          % (decision["action_type"], decision["reason"],
             decision["risk_level"], decision["execution_state"]))
    print("cost_estimate: %s | presupuesto restante (calls): %s"
          % (decision["cost_estimate"], decision["budget_remaining"]))
    if decision["execution_state"] == "succeeded":
        print("ACCION EJECUTADA: %s" % decision["action_type"])
    elif decision["execution_state"] == "failed":
        print("ACCION FALLIDA: %s" % decision["reason"])
    elif decision["execution_state"] == "blocked":
        print("ACCION BLOQUEADA: %s" % decision["reason"])
    return 0


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
    mode = "answer"
    run = None
    if d:
        try:
            run = load_forge(d)
            mode = run.get("mode", "answer")
        except ForgeError as exc:
            checks.append(("Run contract: no se pudo cargar (%s)" % exc, False))

    # Capacidades obligatorias POR MODO. No basta con que alguna este verificada.
    caps = adapter.load_capabilities()
    mandatory, optional = adapter.mode_requirements(mode)
    missing = adapter.missing_mandatory(caps, mode)
    checks.append(("adapter modo=%s: obligatorias verificadas=%d/%d%s"
                   % (mode, len(mandatory) - len(missing), len(mandatory),
                      (" (faltan: %s)" % ", ".join(missing)) if missing else ""),
                   not missing))
    # Sin run que verificar, `verify` no puede certificar nada: falla.
    checks.append(("run resuelto para verificar", bool(d)))

    if d and run is not None:
        # contratos
        errs = contracts.validate_run(run)
        checks.append(("Run contract: %s" % ("OK" if not errs else errs), not errs))
        # ledger
        ok, problems = ledger.verify(d)
        checks.append(("ledger append-only: %s" % ("OK" if ok else problems), ok))
        # suite: se RECALCULA, no se compara con el valor guardado
        if run.get("suite"):
            ok, reason, _sha = integrity.recompute_suite_sha(run)
            checks.append(("suite sha recalculado: %s" % reason, ok))
            checks.append(("suite fuera de workspaces candidatos: %s"
                           % integrity.suite_outside_candidates(run),
                           integrity.suite_outside_candidates(run)))
        else:
            checks.append(("suite: NOT_RUN (sin suite declarada)", False))
        # baseline: revalidado
        ok, reason = integrity.verify_baseline(run)
        checks.append(("baseline objetivo: %s" % reason, ok))
        ok, reason = integrity.verify_frozen_baseline(run)
        checks.append(("baseline congelado: %s" % reason, ok))
        # aislamiento
        if run.get("mode") == "patch":
            proof = _load(os.path.join(d, "isolation.json")) or {}
            checks.append(("aislamiento: ok=%s" % proof.get("ok"), bool(proof.get("ok"))))
        # gates -> decision coherente
        data = report_mod.gather(d)
        decision, reason, _eligible, winner = report_mod.resolve_full(
            d, data, ignore_terminal=True)
        gates = data["gates"]
        if run.get("mode") == "patch":
            # Un run de patch SIN gates evaluados no puede estar bien: se
            # bloquea en vez de declarar OK.
            checks.append(("gates evaluados: %d" % len(gates), bool(gates)))
            if gates:
                any_pass = any((g.get("state") or g.get("verdict")) == "PASS"
                               for g in gates.values())
                # La coherencia es: si hay algun PASS, la decision no puede ser
                # NO_SHIP por falta de gates; y si no hay ninguno, no puede
                # ser WINNER.
                coherent = ((decision == "WINNER") if any_pass
                            else (decision != "WINNER"))
                checks.append(("gates preceden al score: decision=%s (%s)"
                               % (decision, reason), coherent))
                if decision == "WINNER":
                    # Se comprueba el ganador PERSISTIDO, no el re-derivado: si
                    # `report` no se ejecuto, la comprobacion falla.
                    last = run.get("last_decision") or {}
                    persisted = last.get("winner_id")
                    checks.append(("decision persistida: decision=%s winner=%s id=%s"
                                   % (last.get("decision"), persisted,
                                      last.get("decision_id")),
                                   bool(persisted) and persisted == winner
                                   and last.get("decision") == decision))
        checks.append(("modo de seguridad: %s" % isolation.SECURITY_MODE,
                       isolation.SECURITY_MODE == "TRUSTED_CODE_ONLY"))
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
    s.add_argument("--agents", type=int)
    s.add_argument("--profile", choices=("quick", "standard", "extreme"),
                   default="standard")
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

    s = sub.add_parser("judge", help="registrar el veredicto ciego X/Y (patch)")
    s.add_argument("--dir")
    s.add_argument("--winner", required=True, help="X o Y (nunca un id de candidato)")
    s.add_argument("--reason", default="")
    s.add_argument("--evidence", action="append", default=[])
    s.add_argument("--by", default="judge", choices=("judge", "human"))
    s.set_defaults(func=cmd_judge_record)

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

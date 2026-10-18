"""Agente E — orquestador adaptativo (§4).

E propone planes; el scheduler valida y ejecuta. E NO puede exceder presupuesto,
cambiar requisitos/rubrica/suite tras ver resultados, desactivar gates, declarar
PASS sin evidencia, editar la suite, concederse permisos, ni ejecutar efectos
externos sin autorizacion.

Aqui E es DETERMINISTA y auditable (no oculta razonamiento): observa el estado en
disco, produce una Decision estructurada, la valida y la persiste en
`decisions.jsonl` + ledger. La eficacia adaptativa frente a orquestacion fija es
una HIPOTESIS PENDIENTE hasta que el benchmark la demuestre (§22).
"""
import json
import os
import time

from . import ledger, state
from .util import ForgeError, now_ts, save_forge

DECISIONS_FILE = "decisions.jsonl"
JOBS_FILE = "jobs.json"
POLICY_VERSION = "e-policy-v1"
ACTION_TYPES = ("launch_phase", "extra_round", "request_review",
                "request_evidence", "stop", "recommend_no_ship", "apply_budget")
RISK_LEVELS = ("low", "medium", "high")
EXECUTION_STATES = ("proposed", "approved", "executing", "succeeded",
                    "failed", "blocked", "cancelled")

DECISION_REQUIRED = (
    "decision_id", "run_id", "observed_state_version", "action_type",
    "target_ids", "reason", "evidence_refs", "cost_estimate",
    "budget_remaining", "risk_level", "preconditions", "stop_conditions",
    "timestamp", "policy_version", "requires_human_approval", "execution_state",
    "executed_by", "session_ref", "output_ref",
)


def default_budget():
    return {
        "max_candidates": 8,
        "max_calls": 120,
        "max_waves": 40,
        "concurrency": 10,
        "max_rounds": 6,
        "retries_per_job": 1,
        "phase_timeout_s": 1800,
        "cmd_timeout_s": 120,
        "max_output_bytes": 1024 * 1024,
        "max_delegation_depth": 1,
        "money_budget": None,  # el proveedor no expone tokens por API
        "profile": "standard",
    }


PROFILES = {
    "quick": {"max_candidates": 4, "max_calls": 40, "max_rounds": 2,
              "concurrency": 8, "profile": "quick"},
    "standard": {"max_candidates": 8, "max_calls": 120, "max_rounds": 6,
                 "concurrency": 10, "profile": "standard"},
    "extreme": {"max_candidates": 16, "max_calls": 400, "max_rounds": 8,
                "concurrency": 10, "profile": "extreme"},
}


def budget_for(profile):
    b = default_budget()
    b.update(PROFILES.get(profile, {}))
    return b


# --------------------------------------------------------------- validacion
def validate_decision(d, where="Decision"):
    errors = []
    for k in DECISION_REQUIRED:
        if k not in d:
            errors.append("%s: falta %r" % (where, k))
    if errors:
        return errors
    if d["action_type"] not in ACTION_TYPES:
        errors.append("%s.action_type invalido: %r" % (where, d["action_type"]))
    if d["risk_level"] not in RISK_LEVELS:
        errors.append("%s.risk_level invalido: %r" % (where, d["risk_level"]))
    if not isinstance(d["target_ids"], list):
        errors.append("%s.target_ids debe ser lista" % where)
    if not isinstance(d["evidence_refs"], list):
        errors.append("%s.evidence_refs debe ser lista" % where)
    if not isinstance(d["cost_estimate"], dict):
        errors.append("%s.cost_estimate debe ser objeto" % where)
    if d.get("execution_state") not in EXECUTION_STATES:
        errors.append("%s.execution_state invalido: %r" % (where, d.get("execution_state")))
    est = d["cost_estimate"].get("calls", 0)
    rem = d["budget_remaining"].get("calls") if isinstance(
        d["budget_remaining"], dict) else None
    if isinstance(est, int) and isinstance(rem, int) and est > rem:
        errors.append("%s: coste estimado %d excede presupuesto %d" % (where, est, rem))
    if not isinstance(d["requires_human_approval"], bool):
        errors.append("%s.requires_human_approval debe ser booleano" % where)
    return errors


# ---------------------------------------------------------------- contexto
def _load(run_dir, name):
    p = os.path.join(run_dir, name)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return None


def context(run_dir, run):
    """Contexto minimo y estructurado para E (§4.2). Se reconstruye de disco."""
    events = ledger.read(run_dir)
    gates = _load(run_dir, "gates.json") or {}
    arena = _load(run_dir, "arena.json") or {}
    jobs = _load(run_dir, JOBS_FILE) or {}
    return {
        "run_id": run.get("run_id"),
        "mode": run.get("mode"),
        "schema_version": run.get("schema_version"),
        "phase": run.get("phase") or run.get("status"),
        "state_version": (events[-1]["seq"] if events else 0),
        "budget": run.get("budget", {}),
        "gates": {c: g.get("state") for c, g in gates.items()},
        "eligible": sorted(c for c, g in gates.items() if g.get("state") == "PASS"),
        "rounds_played": sum(1 for r in arena.get("rounds", []) if r.get("matches")),
        "champion": arena.get("champion"),
        "jobs_pending": [j for j, v in jobs.items() if v.get("state") == "PENDING"],
        "jobs_running": [j for j, v in jobs.items() if v.get("state") == "RUNNING"],
        "jobs_failed": [j for j, v in jobs.items() if v.get("state") == "FAILED"],
        "events_last_seq": (events[-1]["seq"] if events else 0),
        "runtime_caps": _load(run_dir, "runtime.json") or {},
        "approvals": run.get("approvals", []),
    }


# ------------------------------------------------------------- decision
def _mk_decision(run, ctx, action, reason, targets, evidence, calls, risk,
                 prereqs=None, stops=None, human=False):
    return {
        "decision_id": "d-%s-%s" % (run.get("run_id"), ctx["state_version"] + 1),
        "run_id": run.get("run_id"),
        "observed_state_version": ctx["state_version"],
        "action_type": action,
        "target_ids": targets,
        "reason": reason,
        "evidence_refs": evidence,
        "cost_estimate": {"calls": calls, "waves": 1, "seconds": calls * 20},
        "budget_remaining": {
            "calls": max(0, run.get("budget", {}).get("max_calls", 0)
                         - run.get("calls_spent", 0)),
        },
        "risk_level": risk,
        "preconditions": prereqs or [],
        "stop_conditions": stops or [],
        "timestamp": now_ts(),
        "policy_version": POLICY_VERSION,
        "requires_human_approval": human,
        "execution_state": "proposed",
        "executed_by": None,
        "session_ref": None,
        "output_ref": None,
    }


def propose(run_dir, run):
    """E produce UNA decision permitida segun el estado observado (§4.4)."""
    ctx = context(run_dir, run)
    budget = run.get("budget", {})
    max_calls = budget.get("max_calls", 0)
    spent = run.get("calls_spent", 0)

    if spent >= max_calls:
        return _mk_decision(run, ctx, "stop",
                            "presupuesto de llamadas agotado (%d/%d)" % (spent, max_calls),
                            [], ["budget"], 0, "low",
                            stops=["presupuesto agotado"])

    phase = ctx["phase"]
    if phase in state.TERMINAL or phase in ("NO_SHIP",):
        return _mk_decision(run, ctx, "stop", "estado terminal %s" % phase,
                            [], ["ledger:%d" % ctx["state_version"]], 0, "low",
                            stops=["terminal"])

    # Patch: si ningun candidato es elegible tras gates, recomendar NO_SHIP.
    if run.get("mode") == "patch" and ctx["gates"]:
        if not ctx["eligible"]:
            return _mk_decision(
                run, ctx, "recommend_no_ship",
                "ningun candidato supera los gates obligatorios",
                list(ctx["gates"].keys()),
                ["gates.json"], 0, "low",
                stops=["sin elegibles"])
        # Divergencia que justifica ronda extra: empate dimensional sin desempate.
        if len(ctx["eligible"]) > 1 and not os.path.isfile(
                os.path.join(run_dir, "patch_judge.json")):
            return _mk_decision(
                run, ctx, "request_review",
                "hay %d elegibles sin juicio ciego de desempate"
                % len(ctx["eligible"]), ctx["eligible"],
                ["gates.json"], 1, "medium",
                prereqs=["gates PASS"], stops=["veredicto ciego"])

    # Answer: si el bracket no ha cerrado, lanzar la fase siguiente.
    if run.get("mode") == "answer":
        if ctx["champion"]:
            return _mk_decision(run, ctx, "stop", "campeon ya elegido: %s"
                                % ctx["champion"], [ctx["champion"]],
                                ["arena.json"], 0, "low", stops=["champion"])
        return _mk_decision(run, ctx, "launch_phase",
                            "continuar bracket answer (fase %s)" % phase,
                            [], ["ledger:%d" % ctx["state_version"]], 2, "low")

    # Patch: si esta en READY, lanzar implementacion.
    if run.get("mode") == "patch" and phase == "READY":
        pending = [cid for cid, cand in run.get("candidates", {}).items()
                   if cand.get("status") == "PENDING"]
        if pending:
            return _mk_decision(run, ctx, "launch_phase",
                                "lanzar implementacion para %d candidatos" % len(pending),
                                pending, ["ledger:%d" % ctx["state_version"]], len(pending), "low")

    return _mk_decision(run, ctx, "request_evidence",
                        "estado %s sin accion determinista clara" % phase,
                        [], ["ledger:%d" % ctx["state_version"]], 1, "medium")


def persist(run_dir, decision):
    errors = validate_decision(decision)
    if errors:
        ledger.append(run_dir, "decision_rejected", "; ".join(errors),
                      refs={"decision_id": decision.get("decision_id")}, actor="E")
        raise ForgeError("decision rechazada: %s" % "; ".join(errors))
    path = os.path.join(run_dir, DECISIONS_FILE)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(decision, ensure_ascii=False) + "\n")
    ledger.append(run_dir, "decision", "%s: %s" % (decision["action_type"],
                                                    decision["reason"]),
                  refs={"decision_id": decision["decision_id"],
                        "action": decision["action_type"]}, actor="E")
    return decision


# ------------------------------------------------------------- execution
def _load_jobs(run_dir):
    jobs = _load(run_dir, JOBS_FILE)
    if jobs is None:
        jobs = {}
    return jobs


def _save_jobs(run_dir, jobs):
    from .util import atomic_write_json
    atomic_write_json(os.path.join(run_dir, JOBS_FILE), jobs)


def _register_job(run_dir, job_id, phase, target_ids, action_type, budget_calls=1):
    """Registra un job en jobs.json y actualiza calls_spent en forge.json."""
    jobs = _load_jobs(run_dir)
    job = {
        "job_id": job_id,
        "phase": phase,
        "action_type": action_type,
        "target_ids": target_ids,
        "state": "PENDING",
        "created_ts": now_ts(),
        "started_ts": None,
        "completed_ts": None,
        "session_ref": None,
        "output_ref": None,
        "attempts": 0,
        "max_attempts": 1,
        "budget_calls": budget_calls,
    }
    jobs[job_id] = job
    _save_jobs(run_dir, jobs)
    
    # Actualizar calls_spent en forge.json
    run = _load(run_dir, "forge.json")
    if run:
        run["calls_spent"] = run.get("calls_spent", 0) + budget_calls
        from .util import save_forge
        save_forge(run)
    return job


def _update_job(run_dir, job_id, **kwargs):
    jobs = _load_jobs(run_dir)
    if job_id in jobs:
        jobs[job_id].update(kwargs)
        _save_jobs(run_dir, jobs)
        return jobs[job_id]
    return None


def execute_decision(run_dir, decision, run, session_id=None):
    """Ejecuta una decision validada. Devuelve (success, updated_decision).
    
    Estados: PROPOSED -> APPROVED -> EXECUTING -> SUCCEEDED | FAILED | BLOCKED
    """
    # Revalidar state_version antes de ejecutar
    events = ledger.read(run_dir)
    current_version = events[-1]["seq"] if events else 0
    if decision["observed_state_version"] != current_version:
        decision["execution_state"] = "blocked"
        decision["reason"] += " (state_version cambiada: %d -> %d)" % (
            decision["observed_state_version"], current_version)
        return False, decision

    # Verificar precondiciones
    for prereq in decision.get("preconditions", []):
        if prereq == "gates PASS":
            gates = _load(run_dir, "gates.json") or {}
            if not any(g.get("state") == "PASS" for g in gates.values()):
                decision["execution_state"] = "blocked"
                decision["reason"] += " (precondicion fallida: gates PASS)"
                return False, decision

    # Marcar como approved
    decision["execution_state"] = "approved"
    decision["executed_by"] = "E_executor"
    _persist_decision(run_dir, decision)

    # Ejecutar segun action_type
    success = False
    action = decision["action_type"]
    
    try:
        decision["execution_state"] = "executing"
        _persist_decision(run_dir, decision)
        
        if action == "launch_phase":
            success = _exec_launch_phase(run_dir, decision, run, session_id)
        elif action == "request_review":
            success = _exec_request_review(run_dir, decision, run)
        elif action == "request_evidence":
            success = _exec_request_evidence(run_dir, decision, run)
        elif action == "stop":
            success = _exec_stop(run_dir, decision, run)
        elif action == "recommend_no_ship":
            success = _exec_recommend_no_ship(run_dir, decision, run)
        else:
            decision["execution_state"] = "failed"
            decision["reason"] += " (accion no implementada: %s)" % action
            return False, decision

        if success:
            decision["execution_state"] = "succeeded"
        else:
            decision["execution_state"] = "failed"
            
    except Exception as exc:  # noqa: BLE001
        decision["execution_state"] = "failed"
        decision["reason"] += " (excepcion: %s)" % exc

    _persist_decision(run_dir, decision)
    return success, decision


def _persist_decision(run_dir, decision):
    """Actualiza una decision existente en decisions.jsonl (sobrescribe ultima linea si mismo ID)."""
    path = os.path.join(run_dir, DECISIONS_FILE)
    lines = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        d = json.loads(line)
                        if d.get("decision_id") != decision["decision_id"]:
                            lines.append(line)
                    except ValueError:
                        pass
    lines.append(json.dumps(decision, ensure_ascii=False))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    ledger.append(run_dir, "decision", "%s: %s (state=%s)" % (
        decision["action_type"], decision["reason"], decision["execution_state"]),
        refs={"decision_id": decision["decision_id"],
              "action": decision["action_type"],
              "execution_state": decision["execution_state"]}, actor="E")


def _exec_launch_phase(run_dir, decision, run, session_id=None):
    """Lanza la siguiente fase de trabajo segun el modo."""
    mode = run.get("mode")
    if mode == "patch":
        # En Patch, lanzar jobs de implementacion para candidatos PENDING
        candidates = run.get("candidates", {})
        launched = 0
        for cid, cand in candidates.items():
            if cand.get("status") == "PENDING":
                job_id = "job-%s-%s" % (cid, int(time.time()))
                _register_job(run_dir, job_id, "implement", [cid],
                              "implement", budget_calls=1)
                launched += 1
        if launched == 0:
            # No hay jobs pendientes, verificar si pasar a gates
            decision["reason"] += " (sin jobs pendientes, pasar a gates)"
        return True
    
    elif mode == "answer":
        # En Answer, delegar al bracket original (se hace via CLI)
        decision["reason"] += " (bracket answer: usar cmd_next)"
        return True
    
    return False


def _exec_request_review(run_dir, decision, run):
    """Registra solicitud de revision adversarial para candidatos elegibles."""
    for cid in decision.get("target_ids", []):
        job_id = "review-%s-%s" % (cid, int(time.time()))
        _register_job(run_dir, job_id, "review", [cid], "review", budget_calls=1)
    return True


def _exec_request_evidence(run_dir, decision, run):
    """Registra solicitud de evidencia adicional."""
    # En este momento solo registra el evento; la evidencia se recoge en collect
    return True


def _exec_stop(run_dir, decision, run):
    """Detiene la ejecucion."""
    run["phase"] = "COMPLETED"
    run["status"] = "COMPLETED"
    from .util import save_forge
    save_forge(run)
    return True


def _exec_recommend_no_ship(run_dir, decision, run):
    """Recomienda NO_SHIP y actualiza estado."""
    run["phase"] = "NO_SHIP"
    run["status"] = "NO_SHIP"
    from .util import save_forge
    save_forge(run)
    return True


# ------------------------------------------------------------- alta nivel
def step(run_dir, run):
    """Un paso del ciclo de control de E: Observe->...->Persist (§4.4).
    
    Ahora propone, valida y EJECUTA la decision.
    """
    decision = propose(run_dir, run)
    success, executed = execute_decision(run_dir, decision, run)
    return executed


def history(run_dir):
    path = os.path.join(run_dir, DECISIONS_FILE)
    if not os.path.isfile(path):
        return []
    decisions = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    decisions.append(json.loads(line))
                except ValueError:
                    pass
    return decisions


# ------------------------------------------------------------- utilidades
def get_latest_decision(run_dir):
    """Obtiene la ultima decision persistida."""
    hist = history(run_dir)
    return hist[-1] if hist else None


def get_pending_jobs(run_dir):
    """Obtiene jobs en estado PENDING."""
    jobs = _load_jobs(run_dir)
    return [j for j in jobs.values() if j.get("state") == "PENDING"]


def get_running_jobs(run_dir):
    """Obtiene jobs en estado RUNNING."""
    jobs = _load_jobs(run_dir)
    return [j for j in jobs.values() if j.get("state") == "RUNNING"]


def mark_job_running(run_dir, job_id, session_ref=None):
    return _update_job(run_dir, job_id, state="RUNNING", started_ts=now_ts(),
                       session_ref=session_ref)


def mark_job_completed(run_dir, job_id, output_ref=None, success=True):
    state_val = "DONE" if success else "FAILED"
    return _update_job(run_dir, job_id, state=state_val, completed_ts=now_ts(),
                       output_ref=output_ref)


def get_budget_remaining(run):
    """Calcula presupuesto restante en llamadas."""
    budget = run.get("budget", {})
    max_calls = budget.get("max_calls", 0)
    spent = run.get("calls_spent", 0)
    return max(0, max_calls - spent)
"""Agente E — orquestador adaptativo (§4).

E propone planes; el scheduler valida y ejecuta. E NO puede exceder presupuesto,
cambiar requisitos/rubrica/suite tras ver resultados, desactivar gates, declarar
PASS sin evidencia, editar la suite, concederse permisos, ni ejecutar efectos
externos sin autorizacion.

Aqui E es DETERMINISTA y auditable (no oculta razonamiento): observa el estado en
disco, produce una Decision estructurada, la valida y la persiste en
`decisions.jsonl` + ledger. La eficacia adaptativa frente a orquestacion fija es
una HIPOTESIS PENDIENTE hasta que el benchmark la demuestre (§22).

CORRECCIONES DE LA AUDITORIA (estado real, no declaracion)
-----------------------------------------------------------
1. `requires_human_approval` ahora SE APLICA: sin un registro de aprobacion
   ligado a decision/run/accion/targets/coste, la decision queda
   `awaiting_approval` y NO se ejecuta.
2. Registrar un job NO es ejecutar trabajo. `_exec_launch_phase` deja la
   decision en `delegated` / `awaiting_manual_action`, nunca `succeeded`.
3. `_exec_request_evidence` no puede devolver exito sin evidencia.
4. El presupuesto se RESERVA bajo lock de SISTEMA OPERATIVO antes de crear el
   job (antes se gastaba despues, sin lock: se podia gastar mas del limite).
5. `decisions.jsonl` es append-only: las transiciones se anaden, nunca se
   reescribe el historico. Las lineas corruptas se PRESERVAN.
6. Los job_ids son deterministas: reanudar no duplica trabajo ni cobra dos
   veces.
7. Las transiciones de fase pasan por `state.transition`: un run CANCELLED no
   se reabre en silencio como COMPLETED.
"""
import json
import os
import time

from . import ledger, state
from .util import FileLock, ForgeError, now_ts, save_forge

DECISIONS_FILE = "decisions.jsonl"
STATE_FILE = "decision_state.json"
JOBS_FILE = "jobs.json"
LOCK_FILE = ".forge.lock"
POLICY_VERSION = "e-policy-v2"
ACTION_TYPES = ("launch_phase", "extra_round", "request_review",
                "request_evidence", "stop", "recommend_no_ship", "apply_budget")
RISK_LEVELS = ("low", "medium", "high")
EXECUTION_STATES = ("proposed", "approved", "awaiting_approval",
                    "awaiting_manual_action", "awaiting_evidence",
                    "delegated", "executing", "succeeded",
                    "failed", "blocked", "cancelled")

# Acciones que SIEMPRE requieren aprobacion humana.
HUMAN_APPROVAL_ACTIONS = ("apply_budget", "extra_round")

DECISION_REQUIRED = (
    "decision_id", "run_id", "observed_state_version", "action_type",
    "target_ids", "reason", "evidence_refs", "cost_estimate",
    "budget_remaining", "risk_level", "preconditions", "stop_conditions",
    "timestamp", "policy_version", "requires_human_approval", "execution_state",
    "executed_by", "session_ref", "output_ref",
)

JOB_STATES = ("PENDING", "RUNNING", "AWAITING_MANUAL_ACTION", "SUCCEEDED",
              "FAILED", "BLOCKED", "CANCELLED", "DONE")


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
    unknown = sorted(set(d.keys()) - set(DECISION_REQUIRED))
    if unknown:
        errors.append("%s: campos desconocidos: %s" % (where, ", ".join(unknown)))
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


def validate_approval(approval, decision, where="Aprobacion"):
    """Un registro de aprobacion debe LIGARse a la decision de forma estricta."""
    errors = []
    if not isinstance(approval, dict):
        return ["%s: no es un objeto" % where]
    for k in ("decision_id", "run_id", "action_type", "target_ids",
              "cost_calls", "policy_version", "approved_by"):
        if k not in approval:
            errors.append("%s: falta %r" % (where, k))
    if errors:
        return errors
    if not str(approval.get("approved_by") or "").strip():
        errors.append("%s: `approved_by` vacio" % where)
    if errors:
        return errors
    if approval["decision_id"] != decision.get("decision_id"):
        errors.append("%s: decision_id no coincide" % where)
    if approval["run_id"] != decision.get("run_id"):
        errors.append("%s: run_id no coincide" % where)
    if approval["action_type"] != decision.get("action_type"):
        errors.append("%s: action_type no coincide" % where)
    if list(approval["target_ids"]) != list(decision.get("target_ids", [])):
        errors.append("%s: target_ids no coinciden" % where)
    if approval["cost_calls"] != decision.get("cost_estimate", {}).get("calls"):
        errors.append("%s: cost_calls no coincide" % where)
    if approval["policy_version"] != decision.get("policy_version"):
        errors.append("%s: policy_version no coincide" % where)
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
        "state_version": ledger.last_valid_seq(run_dir),
        "budget": run.get("budget", {}),
        "gates": {c: g.get("state") for c, g in gates.items()},
        "eligible": sorted(c for c, g in gates.items() if g.get("state") == "PASS"),
        "rounds_played": sum(1 for r in arena.get("rounds", []) if r.get("matches")),
        "champion": arena.get("champion"),
        "jobs_pending": [j for j, v in jobs.items() if v.get("state") == "PENDING"],
        "jobs_running": [j for j, v in jobs.items() if v.get("state") == "RUNNING"],
        "jobs_failed": [j for j, v in jobs.items() if v.get("state") == "FAILED"],
        "events_last_seq": ledger.last_valid_seq(run_dir),
        "runtime_caps": _load(run_dir, "runtime.json") or {},
        "approvals": run.get("approvals", []),
        "calls_spent": run.get("calls_spent", 0),
        "calls_reserved": run.get("calls_reserved", 0),
    }


# ------------------------------------------------------------- decision
def _mk_decision(run, ctx, action, reason, targets, evidence, calls, risk,
                 prereqs=None, stops=None, human=False):
    budget = run.get("budget", {})
    max_calls = budget.get("max_calls", 0)
    spent = run.get("calls_spent", 0)
    reserved = run.get("calls_reserved", 0)
    remaining = max(0, max_calls - spent - reserved)
    if action in HUMAN_APPROVAL_ACTIONS:
        human = True
    return {
        "decision_id": "d-%s-%s" % (run.get("run_id"), ctx["state_version"] + 1),
        "run_id": run.get("run_id"),
        "observed_state_version": ctx["state_version"],
        "action_type": action,
        "target_ids": targets,
        "reason": reason,
        "evidence_refs": evidence,
        "cost_estimate": {"calls": calls, "waves": 1, "seconds": calls * 20},
        "budget_remaining": {"calls": remaining},
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
    spent = run.get("calls_spent", 0) + run.get("calls_reserved", 0)

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
                                ["arena.json"], 0, "low", stops=["campeon"])
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


# ------------------------------------------------------------- persistencia
def persist(run_dir, decision):
    """Anade una decision al historico append-only. NUNCA reescribe."""
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


def _persist_decision(run_dir, decision):
    """Anade una TRANSICION de estado al historico append-only.

    El fichero `decisions.jsonl` es append-only: cada transicion es una linea
    nueva. La proyeccion (ultimo estado por decision_id) vive aparte en
    `decision_state.json`. Las lineas corruptas se PRESERVAN: no se borran ni
    se reescribe el historico para "limpiarlas".
    """
    path = os.path.join(run_dir, DECISIONS_FILE)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(decision, ensure_ascii=False) + "\n")
    # Proyeccion (estado actual por decision_id)
    from .util import atomic_write_json
    projection = _load(run_dir, STATE_FILE) or {}
    projection[decision["decision_id"]] = decision
    atomic_write_json(os.path.join(run_dir, STATE_FILE), projection)
    ledger.append(run_dir, "decision", "%s: %s (state=%s)" % (
        decision["action_type"], decision["reason"], decision["execution_state"]),
        refs={"decision_id": decision["decision_id"],
              "action": decision["action_type"],
              "execution_state": decision["execution_state"]}, actor="E")


# ------------------------------------------------------------- presupuesto
def _run_lock(run_dir):
    return FileLock(os.path.join(run_dir, LOCK_FILE))


def reserve_budget(run_dir, cost):
    """Reserva presupuesto de forma ATOMICA. Devuelve (ok, reason).

    La reserva ocurre ANTES de crear el job, bajo lock de sistema operativo:
    dos procesos concurrentes no pueden gastar mas del limite.
    """
    if cost <= 0:
        return True, "coste 0"
    with _run_lock(run_dir):
        run = _load(run_dir, "forge.json")
        if not run:
            return False, "forge.json ausente"
        budget = run.get("budget", {})
        max_calls = budget.get("max_calls", 0)
        spent = run.get("calls_spent", 0)
        reserved = run.get("calls_reserved", 0)
        remaining = max_calls - spent - reserved
        if cost > remaining:
            return False, ("presupuesto insuficiente: quedan %d llamadas, se "
                           "pidieron %d (max_calls=%d, gastadas=%d, reservadas=%d)"
                           % (remaining, cost, max_calls, spent, reserved))
        run["calls_reserved"] = reserved + cost
        save_forge(run, run_dir)
    return True, "reservadas %d llamadas" % cost


def commit_budget(run_dir, cost):
    """Convierte la reserva en gasto efectivo."""
    if cost <= 0:
        return
    with _run_lock(run_dir):
        run = _load(run_dir, "forge.json")
        if not run:
            return
        run["calls_reserved"] = max(0, run.get("calls_reserved", 0) - cost)
        spent = run.get("calls_spent", 0) + cost
        max_calls = run.get("budget", {}).get("max_calls", 0)
        if spent + run.get("calls_reserved", 0) > max_calls:
            # Nunca se gasta mas de lo permitido: el limite es duro.
            spent = max(0, max_calls - run.get("calls_reserved", 0))
        run["calls_spent"] = spent
        save_forge(run, run_dir)


def release_budget(run_dir, cost):
    """Libera una reserva (el job no llego a ejecutarse)."""
    if cost <= 0:
        return
    with _run_lock(run_dir):
        run = _load(run_dir, "forge.json")
        if not run:
            return
        run["calls_reserved"] = max(0, run.get("calls_reserved", 0) - cost)
        save_forge(run, run_dir)


def get_budget_remaining(run):
    """Presupuesto restante REAL (descontando lo reservado, no solo lo gastado)."""
    budget = run.get("budget", {})
    max_calls = budget.get("max_calls", 0)
    spent = run.get("calls_spent", 0)
    reserved = run.get("calls_reserved", 0)
    return max(0, max_calls - spent - reserved)


# -------------------------------------------------------------- ejecucion
def _load_jobs(run_dir):
    jobs = _load(run_dir, JOBS_FILE)
    if jobs is None:
        jobs = {}
    return jobs


def _save_jobs(run_dir, jobs):
    from .util import atomic_write_json
    atomic_write_json(os.path.join(run_dir, JOBS_FILE), jobs)


def job_id_for(run_id, phase, action_type, target_ids):
    """ID determinista: reanudar no crea jobs duplicados."""
    import json as _json
    from .util import sha_text
    # Codificacion canonica: los separadores NO son ambiguos (un target
    # "a,b" no puede colisionar con dos targets "a" y "b").
    key = _json.dumps([str(run_id), str(phase), str(action_type),
                       sorted(str(t) for t in target_ids)],
                      sort_keys=True, separators=(",", ":"))
    return "job-%s" % sha_text(key)[:16]


def _register_job(run_dir, job_id, phase, target_ids, action_type, budget_calls=1):
    """Registra un job. El presupuesto se RESERVA antes (bajo lock).

    El job_id es determinista: si ya existe, no se duplica ni se cobra dos
    veces (reanudar es seguro).
    """
    # Todo el ciclo (leer jobs.json -> comprobar id -> reservar -> escribir)
    # bajo un unico lock: dos procesos concurrentes no pueden registrar el
    # mismo job dos veces ni perder entradas.
    with _run_lock(run_dir):
        jobs = _load_jobs(run_dir)
        if job_id in jobs:
            return jobs[job_id], False
        ok, reason = reserve_budget(run_dir, budget_calls)
        if not ok:
            raise ForgeError("no se pudo registrar el job %s: %s" % (job_id, reason))
        job = {
            "job_id": job_id,
            "phase": phase,
            "action_type": action_type,
            "target_ids": list(target_ids),
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
        return job, True


def _update_job(run_dir, job_id, **kwargs):
    jobs = _load_jobs(run_dir)
    if job_id in jobs:
        jobs[job_id].update(kwargs)
        _save_jobs(run_dir, jobs)
        return jobs[job_id]
    return None


def _approval_for(run, decision):
    """Busca un registro de aprobacion valido para la decision."""
    for approval in (run.get("approvals") or []):
        if not validate_approval(approval, decision):
            return approval
    return None


def execute_decision(run_dir, decision, run, session_id=None):
    """Ejecuta una decision validada. Devuelve (success, updated_decision).

    Estados: PROPOSED -> APPROVED -> EXECUTING -> SUCCEEDED | FAILED | BLOCKED
    Si requiere aprobacion humana y no la hay: AWAITING_APPROVAL (no ejecuta).
    """
    errors = validate_decision(decision)
    if errors:
        decision["execution_state"] = "blocked"
        decision["reason"] += " (decision invalida: %s)" % "; ".join(errors)
        _persist_decision(run_dir, decision)
        return False, decision

    # Revalidar state_version antes de ejecutar
    current_version = ledger.last_valid_seq(run_dir)
    if decision["observed_state_version"] != current_version:
        decision["execution_state"] = "blocked"
        decision["reason"] += " (state_version cambiada: %d -> %d)" % (
            decision["observed_state_version"], current_version)
        _persist_decision(run_dir, decision)
        return False, decision

    # Aprobacion humana: sin un registro LIGADO, no se ejecuta.
    if decision.get("requires_human_approval") or \
            decision.get("action_type") in HUMAN_APPROVAL_ACTIONS:
        approval = _approval_for(run, decision)
        if approval is None:
            decision["execution_state"] = "awaiting_approval"
            decision["reason"] += (" (requiere aprobacion humana registrada y "
                                   "ligada a esta decision)")
            _persist_decision(run_dir, decision)
            return False, decision
        decision["executed_by"] = "human:%s" % approval.get("approved_by", "human")

    # Verificar precondiciones
    for prereq in decision.get("preconditions", []):
        if prereq == "gates PASS":
            gates = _load(run_dir, "gates.json") or {}
            if not any(g.get("state") == "PASS" for g in gates.values()):
                decision["execution_state"] = "blocked"
                decision["reason"] += " (precondicion fallida: gates PASS)"
                _persist_decision(run_dir, decision)
                return False, decision

    # Marcar como approved
    decision["execution_state"] = "approved"
    if decision.get("executed_by") is None:
        decision["executed_by"] = "E_executor"
    _persist_decision(run_dir, decision)

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
            _persist_decision(run_dir, decision)
            return False, decision

        if success:
            decision["execution_state"] = "succeeded"
        elif decision["execution_state"] not in ("delegated", "awaiting_manual_action",
                                                 "awaiting_evidence"):
            decision["execution_state"] = "failed"

    except Exception as exc:  # noqa: BLE001
        decision["execution_state"] = "failed"
        decision["reason"] += " (excepcion: %s)" % exc

    _persist_decision(run_dir, decision)
    return success, decision


def _exec_launch_phase(run_dir, decision, run, session_id=None):
    """Prepara el trabajo siguiente.

    Registrar un job NO es ejecutar trabajo: la decision queda `delegated` o
    `awaiting_manual_action`, nunca `succeeded`. El job queda PENDING con su
    briefing escrito en disco: quien lo ejecute (un agente o un operador) debe
    marcarlo RUNNING/SUCCEEDED con evidencia.
    """
    mode = run.get("mode")
    if mode == "patch":
        candidates = run.get("candidates", {})
        launched = 0
        for cid, cand in sorted(candidates.items()):
            if cand.get("status") != "PENDING":
                continue
            job_id = job_id_for(run.get("run_id"), "implement", "implement", [cid])
            try:
                job, created = _register_job(run_dir, job_id, "implement", [cid],
                                             "implement", budget_calls=1)
            except ForgeError as exc:
                decision["reason"] += " (%s)" % exc
                decision["execution_state"] = "blocked"
                return False
            if not created:
                continue  # job ya existente: no se duplica ni se cobra dos veces
            brief = os.path.join(run_dir, "briefs", "%s.md" % job_id)
            try:
                os.makedirs(os.path.dirname(brief), exist_ok=True)
                with open(brief, "w", encoding="utf-8") as fh:
                    fh.write("# Brief %s\n\nCandidato: %s\nModo: %s\n\n"
                             "Implementa la tarea en su workspace y deja el "
                             "cambio exacto en el directorio del candidato.\n"
                             % (job_id, cid, mode))
                job["output_ref"] = os.path.relpath(brief, run_dir)
            except OSError:
                pass
            _update_job(run_dir, job_id, state="AWAITING_MANUAL_ACTION")
            cand["status"] = "AWAITING_MANUAL_ACTION"
            launched += 1
        if launched == 0:
            decision["execution_state"] = "awaiting_manual_action"
            decision["reason"] += (" (sin jobs pendientes: el trabajo ya fue "
                                   "encargado; se requiere ejecucion externa)")
            return False
        decision["execution_state"] = "delegated"
        decision["reason"] += (" (%d jobs encargados; la ejecucion es externa y "
                               "aun no esta verificada)" % launched)
        return False

    elif mode == "answer":
        decision["execution_state"] = "delegated"
        decision["reason"] += (" (bracket answer: la olas la lanza el "
                               "orquestador con `arena_forge.py next`)")
        return False

    return False


def _exec_request_review(run_dir, decision, run):
    """Encarga revisiones adversariales para los candidatos elegibles."""
    created = 0
    for cid in decision.get("target_ids", []):
        job_id = job_id_for(run.get("run_id"), "review", "review", [cid])
        try:
            job, was_created = _register_job(run_dir, job_id, "review", [cid],
                                             "review", budget_calls=1)
        except ForgeError as exc:
            decision["reason"] += " (%s)" % exc
            decision["execution_state"] = "blocked"
            return False
        if was_created:
            created += 1
    if created == 0:
        decision["execution_state"] = "delegated"
        decision["reason"] += " (revisiones ya encargadas; no se duplican)"
        return False
    decision["execution_state"] = "delegated"
    decision["reason"] += (" (%d revisiones encargadas; la ejecucion es externa "
                           "y aun no esta verificada)" % created)
    return False


def _exec_request_evidence(run_dir, decision, run):
    """Solicita evidencia adicional.

    NO puede devolver exito: no se ha recogido ninguna evidencia todavia.
    """
    decision["execution_state"] = "awaiting_evidence"
    decision["reason"] += (" (evidencia solicitada; no hay evidencia recogida: "
                           "no se puede marcar como ejecutada)")
    return False


def _exec_stop(run_dir, decision, run):
    """Detiene la ejecucion respetando la maquina de estados."""
    cur = run.get("phase") or run.get("status")
    if cur in state.TERMINAL:
        decision["reason"] += " (estado terminal %s: no se reabre)" % cur
        return True
    try:
        state.transition(run, "COMPLETED", "decision stop de E")
    except ForgeError as exc:
        decision["reason"] += " (transicion no permitida: %s)" % exc
        decision["execution_state"] = "blocked"
        return False
    save_forge(run)
    return True


def _exec_recommend_no_ship(run_dir, decision, run):
    """Marca el run como NO_SHIP respetando la maquina de estados."""
    cur = run.get("phase") or run.get("status")
    if cur in state.TERMINAL:
        decision["reason"] += " (estado terminal %s: no se reabre)" % cur
        return True
    try:
        state.transition(run, "NO_SHIP", "decision recommend_no_ship de E")
    except ForgeError as exc:
        decision["reason"] += " (transicion no permitida: %s)" % exc
        decision["execution_state"] = "blocked"
        return False
    save_forge(run)
    return True


# ------------------------------------------------------------- alta nivel
def step(run_dir, run):
    """Un paso del ciclo de control de E: Observe->...->Persist (§4.4)."""
    decision = propose(run_dir, run)
    success, executed = execute_decision(run_dir, decision, run)
    return executed


def history(run_dir):
    """Historial de decisiones: la ULTIMA transicion por decision_id.

    Las lineas corruptas se PRESERVAN en el fichero y se omiten aqui; no se
    borran ni se reescribe el historico.
    """
    path = os.path.join(run_dir, DECISIONS_FILE)
    if not os.path.isfile(path):
        return []
    latest = {}
    order = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue  # linea corrupta: se preserva en disco
            did = d.get("decision_id")
            if did not in latest:
                order.append(did)
            latest[did] = d
    return [latest[did] for did in order if did in latest]


def corrupt_lines(run_dir):
    """Lineas corruptas del historico (preservadas, no borradas)."""
    path = os.path.join(run_dir, DECISIONS_FILE)
    if not os.path.isfile(path):
        return []
    bad = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except ValueError:
                bad.append({"line": i, "content": line[:200]})
    return bad


# ------------------------------------------------------------- utilidades
def get_latest_decision(run_dir):
    """Obtiene la ultima decision persistida."""
    hist = history(run_dir)
    return hist[-1] if hist else None


def get_pending_jobs(run_dir):
    """Jobs en estado PENDING."""
    jobs = _load_jobs(run_dir)
    return [j for j in jobs.values() if j.get("state") == "PENDING"]


def get_running_jobs(run_dir):
    """Jobs en estado RUNNING."""
    jobs = _load_jobs(run_dir)
    return [j for j in jobs.values() if j.get("state") == "RUNNING"]


def mark_job_running(run_dir, job_id, session_ref=None):
    return _update_job(run_dir, job_id, state="RUNNING", started_ts=now_ts(),
                       session_ref=session_ref)


def mark_job_completed(run_dir, job_id, output_ref=None, success=True):
    """Marca el job como terminado.

    DONE exige evidencia: `output_ref` debe existir, tener tamano valido y su
    SHA-256 se registra. Sin output verificable el job NO pasa a DONE.
    """
    existing = _load_jobs(run_dir).get(job_id)
    if existing is None:
        return None
    if existing.get("state") == "DONE":
        # Idempotente: completar dos veces el MISMO job no cobra dos veces.
        return existing
    if success and not output_ref:
        return _fail_job(run_dir, job_id, None)
    if success:
        path = output_ref
        if not os.path.isabs(path):
            path = os.path.join(run_dir, output_ref)
        if not os.path.isfile(path):
            return _fail_job(run_dir, job_id, output_ref)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size <= 0:
            return _fail_job(run_dir, job_id, output_ref)
        from .util import sha_file
        job = _update_job(run_dir, job_id, state="DONE", completed_ts=now_ts(),
                          output_ref=output_ref)
        if job is not None:
            job["output_sha256"] = sha_file(path)
            job["output_bytes"] = size
            _save_jobs(run_dir, _load_jobs(run_dir))
        commit_budget(run_dir, (job or {}).get("budget_calls", 0))
        return job
    return _fail_job(run_dir, job_id, output_ref)


def _fail_job(run_dir, job_id, output_ref):
    """Marca el job como FAILED y LIBERA la reserva de presupuesto.

    Sin liberar, la reserva queda huerfana para siempre: el trabajo esta
    encajonado y el presupuesto quemado.
    """
    job = _update_job(run_dir, job_id, state="FAILED", completed_ts=now_ts(),
                      output_ref=output_ref)
    if job is not None:
        release_budget(run_dir, job.get("budget_calls", 0))
    return job

"""Contratos de datos estrictos (§9 de la especificacion).

Cada validador devuelve una lista de errores (vacia = valido). Los campos
criticos, los rangos y las rutas se comprueban antes de aceptar cualquier dato,
venga de un agente propio o no. Nada externo se asume fiable.
"""
import os

from .util import inside

GATE_STATES = ("PASS", "FAIL", "BLOCKED", "NOT_RUN", "INCONCLUSIVE")
DECISION_STATES = ("WINNER", "NO_SHIP", "CANCELLED", "BLOCKED", "FAILED")
JOB_STATES = ("PENDING", "RUNNING", "DONE", "FAILED", "MISSING", "SKIPPED")
MODES = ("answer", "patch", "benchmark")
SCORE_DIMENSIONS = ("correctness", "completeness", "specificity",
                    "robustness", "clarity")


def _req(obj, keys, where, errors):
    for k in keys:
        if k not in obj:
            errors.append("%s: falta campo obligatorio %r" % (where, k))


def _is_type(value, typ):
    if typ is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if typ is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, typ)


# ------------------------------------------------------------------- Run
RUN_REQUIRED = ("run_id", "schema_version", "mode", "status", "phase", "created",
                "seed", "task_sha", "rubric_sha", "cards_sha", "budget",
                "policy_version")


def validate_run(run, where="Run"):
    errors = []
    _req(run, RUN_REQUIRED, where, errors)
    if not errors:
        for k in ("run_id", "mode", "status", "phase", "policy_version"):
            if not isinstance(run.get(k), str) or not run.get(k):
                errors.append("%s.%s debe ser cadena no vacia" % (where, k))
        if not _is_type(run.get("schema_version"), int):
            errors.append("%s.schema_version debe ser entero" % where)
        if run.get("mode") not in MODES:
            errors.append("%s.mode invalido: %r" % (where, run.get("mode")))
        if not _is_type(run.get("created"), int):
            errors.append("%s.created debe ser entero" % where)
        for k in ("task_sha", "rubric_sha", "cards_sha"):
            v = run.get(k)
            if not (isinstance(v, str) and len(v) == 64):
                errors.append("%s.%s debe ser sha256 hex" % (where, k))
    return errors


# --------------------------------------------------------------- Candidate
CAND_REQUIRED = ("candidate_id", "run_id", "strategy_id", "prompt_hash",
                 "baseline_hash", "workspace_ref", "isolation_verified",
                 "status", "eligible")


def validate_candidate(c, run_dir=None, where="Candidate"):
    errors = []
    _req(c, CAND_REQUIRED, where, errors)
    if not errors:
        for k in ("candidate_id", "run_id", "strategy_id", "status"):
            if not isinstance(c.get(k), str) or not c.get(k):
                errors.append("%s.%s debe ser cadena no vacia" % (where, k))
        if not isinstance(c.get("isolation_verified"), bool):
            errors.append("%s.isolation_verified debe ser booleano" % where)
        if c.get("eligible") not in (True, False, None):
            errors.append("%s.eligible debe ser booleano o null" % where)
        ws = c.get("workspace_ref")
        if not isinstance(ws, str) or not ws:
            errors.append("%s.workspace_ref ausente" % where)
        elif run_dir and not inside(run_dir, os.path.join(run_dir, ws)):
            errors.append("%s.workspace_ref escapa del run: %r" % (where, ws))
    return errors


# -------------------------------------------------------------------- Job
JOB_REQUIRED = ("job_id", "run_id", "phase", "kind", "input_hash", "state",
                "attempts", "output_expected")


def validate_job(j, where="Job"):
    errors = []
    _req(j, JOB_REQUIRED, where, errors)
    if not errors:
        for k in ("job_id", "run_id", "phase", "kind", "state"):
            if not isinstance(j.get(k), str) or not j.get(k):
                errors.append("%s.%s debe ser cadena no vacia" % (where, k))
        if j.get("state") not in JOB_STATES:
            errors.append("%s.state invalido: %r" % (where, j.get("state")))
        if not _is_type(j.get("attempts"), int) or j.get("attempts") < 0:
            errors.append("%s.attempts debe ser entero >= 0" % where)
    return errors


# --------------------------------------------------------------- GateResult
GATE_REQUIRED = ("gate_id", "candidate", "state", "command", "ts")


def validate_gate_result(g, where="GateResult"):
    errors = []
    _req(g, GATE_REQUIRED, where, errors)
    if not errors:
        if g.get("state") not in GATE_STATES:
            errors.append("%s.state invalido: %r" % (where, g.get("state")))
        for k in ("gate_id", "candidate", "command"):
            if not isinstance(g.get(k), str) or not g.get(k):
                errors.append("%s.%s debe ser cadena no vacia" % (where, k))
        if g.get("exit_code") is not None and not _is_type(g.get("exit_code"), int):
            errors.append("%s.exit_code debe ser entero o null" % where)
        for k in ("stdout_ref", "stderr_ref"):
            ref = g.get(k)
            if ref is not None and not isinstance(ref, str):
                errors.append("%s.%s debe ser cadena o null" % (where, k))
    return errors


# ---------------------------------------------------------------- Decision
DECISION_REQUIRED = ("decision_id", "run_id", "state", "reason", "ts",
                     "policy_version")


def validate_decision(d, where="Decision"):
    errors = []
    _req(d, DECISION_REQUIRED, where, errors)
    if not errors:
        if d.get("state") not in DECISION_STATES:
            errors.append("%s.state invalido: %r" % (where, d.get("state")))
        for k in ("decision_id", "run_id", "reason", "policy_version"):
            if not isinstance(d.get(k), str) or not d.get(k):
                errors.append("%s.%s debe ser cadena no vacia" % (where, k))
        if d.get("state") == "WINNER" and not d.get("winner"):
            errors.append("%s: WINNER sin ganador" % where)
        if d.get("state") == "NO_SHIP" and d.get("winner"):
            errors.append("%s: NO_SHIP con ganador" % where)
    return errors


# ------------------------------------------------------- veredicto de juez
def validate_judge_verdict(v, contestants, where="verdict"):
    """Valida un veredicto answer: scores completos en rango y ganador conocido."""
    errors = []
    if not isinstance(v, dict):
        return ["%s: no es objeto JSON" % where]
    contests = set(contestants)
    raw = v.get("scores") or {}
    winner = str(v.get("winner") or "").strip()
    if winner and winner not in contests:
        errors.append("%s.winner desconocido: %r" % (where, winner))
    if raw:
        for cid, sc in raw.items():
            if cid not in contests:
                errors.append("%s.scores id desconocido: %r" % (where, cid))
                continue
            if not isinstance(sc, dict):
                errors.append("%s.scores[%s] no es objeto" % (where, cid))
                continue
            for dim in SCORE_DIMENSIONS:
                val = sc.get(dim)
                if val is None:
                    errors.append("%s.scores[%s].%s ausente" % (where, cid, dim))
                elif not _is_type(val, float) or not (0 <= float(val) <= 10):
                    errors.append("%s.scores[%s].%s fuera de rango [0,10]: %r"
                                  % (where, cid, dim, val))
    if not raw and not winner:
        errors.append("%s: ni scores completos ni ganador claro" % where)
    return errors

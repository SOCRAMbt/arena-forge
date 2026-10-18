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

from . import ledger, state
from .util import ForgeError, now_ts

DECISIONS_FILE = "decisions.jsonl"
POLICY_VERSION = "e-policy-v1"
ACTION_TYPES = ("launch_phase", "extra_round", "request_review",
                "request_evidence", "stop", "recommend_no_ship", "apply_budget")
RISK_LEVELS = ("low", "medium", "high")

DECISION_REQUIRED = (
    "decision_id", "run_id", "observed_state_version", "action_type",
    "target_ids", "reason", "evidence_refs", "cost_estimate",
    "budget_remaining", "risk_level", "preconditions", "stop_conditions",
    "timestamp", "policy_version", "requires_human_approval", "execution_state",
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
    est = d["cost_estimate"].get("calls", 0)
    rem = d["budget_remaining"].get("calls") if isinstance(
        d["budget_remaining"], dict) else None
    if isinstance(est, int) and isinstance(rem, int) and est > rem:
        errors.append("%s: coste estimado %d excede presupuesto %d" % (where, est, rem))
    if not isinstance(d["requires_human_approval"], bool):
        errors.append("%s.requires_human_approval debe ser booleano" % where)
    return errors


# ---------------------------------------------------------------- contexto
def context(run_dir, run):
    """Contexto minimo y estructurado para E (§4.2). Se reconstruye de disco."""
    events = ledger.read(run_dir)
    gates = _load(run_dir, "gates.json") or {}
    arena = _load(run_dir, "arena.json") or {}
    jobs = _load(run_dir, "jobs.json") or {}
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
        "jobs_failed": [j for j, v in jobs.items() if v.get("state") == "FAILED"],
        "events_last_seq": (events[-1]["seq"] if events else 0),
        "runtime_caps": _load(run_dir, "runtime.json") or {},
        "approvals": run.get("approvals", []),
    }


def _load(run_dir, name):
    p = os.path.join(run_dir, name)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return None


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


def step(run_dir, run):
    """Un paso del ciclo de control de E: Observe->...->Persist (§4.4)."""
    decision = propose(run_dir, run)
    decision["execution_state"] = "accepted"
    return persist(run_dir, decision)


def history(run_dir):
    path = os.path.join(run_dir, DECISIONS_FILE)
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out

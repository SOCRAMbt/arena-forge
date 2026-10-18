"""Maquina de estados formal (§8.4) con precondiciones y transiciones legales.

Flujo: CREATED -> PLANNED -> INITIALIZED -> PREPARING -> READY -> RUNNING
       -> COLLECTING -> EVALUATING -> DECIDING -> REPORTING -> COMPLETED
Adicionales: PAUSED, CANCELLED, BLOCKED, FAILED, NO_SHIP.

Los estados terminales no se reabren en silencio: se registra evento o se crea
una nueva ejecucion. Ninguna transicion ilegal se permite.
"""
from .util import ForgeError

STATES = (
    "CREATED", "PLANNED", "INITIALIZED", "PREPARING", "READY", "RUNNING",
    "COLLECTING", "EVALUATING", "DECIDING", "REPORTING", "COMPLETED",
    "PAUSED", "CANCELLED", "BLOCKED", "FAILED", "NO_SHIP",
)

TERMINAL = ("COMPLETED", "CANCELLED", "FAILED", "NO_SHIP")

# destino -> origenes permitidos
TRANSITIONS = {
    "PLANNED":     ("CREATED",),
    "INITIALIZED": ("PLANNED", "CREATED"),
    "PREPARING":   ("INITIALIZED",),
    "READY":       ("PREPARING", "INITIALIZED"),
    "RUNNING":     ("READY", "PREPARING", "INITIALIZED", "PAUSED"),
    "COLLECTING":  ("RUNNING",),
    "EVALUATING":  ("COLLECTING", "RUNNING"),
    "DECIDING":    ("EVALUATING",),
    "REPORTING":   ("DECIDING",),
    "COMPLETED":   ("REPORTING",),
    "PAUSED":      ("RUNNING", "COLLECTING", "EVALUATING"),
    "CANCELLED":   ("CREATED", "PLANNED", "INITIALIZED", "PREPARING", "READY",
                    "RUNNING", "COLLECTING", "EVALUATING", "DECIDING",
                    "REPORTING", "PAUSED", "BLOCKED"),
    "BLOCKED":     ("PREPARING", "READY", "RUNNING", "COLLECTING",
                    "EVALUATING", "DECIDING", "REPORTING", "PAUSED"),
    "FAILED":      ("INITIALIZED", "PREPARING", "READY", "RUNNING",
                    "COLLECTING", "EVALUATING", "DECIDING", "REPORTING",
                    "PAUSED", "BLOCKED"),
    "NO_SHIP":     ("DECIDING", "EVALUATING", "REPORTING"),
}


def is_terminal(state):
    return state in TERMINAL


def can_transition(current, target):
    if current not in STATES:
        return False, "estado actual desconocido: %r" % current
    if target not in STATES:
        return False, "estado destino desconocido: %r" % target
    if current == target:
        return True, "sin cambio"
    if is_terminal(current):
        return False, "estado terminal %s no se reabre en silencio" % current
    if target not in TRANSITIONS:
        return False, "transicion no definida hacia %s" % target
    if current not in TRANSITIONS[target]:
        return False, "transicion ilegal %s -> %s" % (current, target)
    return True, "ok"


def transition(run, target, trigger=""):
    """Aplica la transicion al run (dict) o eleva ForgeError. Registra `phase`."""
    cur = run.get("phase") or run.get("status") or "CREATED"
    ok, why = can_transition(cur, target)
    if not ok:
        raise ForgeError(why)
    run["phase"] = target
    run["status"] = target
    run["updated"] = run.get("updated")
    if trigger:
        run.setdefault("phase_log", []).append({"to": target, "why": trigger})
    return run


# ------------------------------------------------ precondiciones por accion
def require_phase(run, allowed, action):
    cur = run.get("phase") or run.get("status")
    if cur not in allowed:
        raise ForgeError("%s requiere fase %s, y esta en %s"
                         % (action, "/".join(allowed), cur))


def can_enter_deciding(run, gates_present, suite_valid):
    """No se llega a DECIDING con gates obligatorios ausentes o suite invalida."""
    if not gates_present:
        return False, "sin GateResult obligatorios"
    if not suite_valid:
        return False, "suite protegida ausente o alterada"
    return True, "ok"

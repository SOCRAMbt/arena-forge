"""Score Calculator determinista (§3.14, §10.3).

El juez aporta evaluaciones por dimension + referencias; AQUI se calcula el
total ponderado. Una puntuacion sin evidencia queda invalidada. El score nunca
convierte a un candidato inelegible en elegible: eso lo garantiza la capa de
decision, no este modulo.
"""
from .util import ForgeError

# Pesos congelados por ejecucion (§10.2). No se cambian a mitad de torneo.
PATCH_WEIGHTS = {
    "correctness": 35,
    "robustness": 20,
    "security": 15,
    "maintainability": 10,
    "performance": 10,
    "documentation": 10,
}
PATCH_WEIGHTS_SHA_KEY = "patch_rubric_v1"


def normalize_weights(weights):
    total = sum(weights.values())
    if total <= 0:
        raise ForgeError("pesos invalidos (suma <= 0)")
    return {k: v / total for k, v in weights.items()}


def dimension_score(scores, weights=PATCH_WEIGHTS):
    """0-100 desde dimensiones 0-10 y pesos porcentuales."""
    nw = normalize_weights(weights)
    total = 0.0
    for dim, w in nw.items():
        val = scores.get(dim)
        if val is None:
            raise ForgeError("dimension ausente: %s" % dim)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            raise ForgeError("dimension no numerica: %s=%r" % (dim, val))
        if not (0 <= float(val) <= 10):
            raise ForgeError("dimension fuera de rango [0,10]: %s=%r" % (dim, val))
        total += float(val) * w * 10.0
    return round(total, 2)


def require_evidence(verdict, where="verdict"):
    """Una puntuacion sin evidencia se invalida (§10.3)."""
    ev = verdict.get("evidence")
    if not ev or not isinstance(ev, list) or not any(str(e).strip() for e in ev):
        raise ForgeError("%s: score sin evidencia -> invalidado" % where)
    return ev


def pick_blind(verdict, label_map):
    """Traduce el ganador ciego (X/Y) a un candidato real. Devuelve None si invalido."""
    winner = str(verdict.get("winner") or "").strip().upper()
    if winner not in ("X", "Y"):
        return None
    return (label_map or {}).get(winner)


def evaluate_patch_judgement(verdict, eligible, label_map):
    """Aplica aritmetica y reglas de elegibilidad. Devuelve (winner|None, info)."""
    info = {"reason": verdict.get("reason", ""), "raw_total": None}
    if not eligible:
        return None, {"reason": "sin candidatos elegibles", "raw_total": None}
    # Si el veredicto trae dimensiones, recalculamos el total en codigo.
    dims = verdict.get("dimensions") or {}
    if dims:
        try:
            info["raw_total"] = {cid: dimension_score(verdict["dimensions"].get(cid, {}))
                                 for cid in verdict["dimensions"]}
        except ForgeError as exc:
            info["error"] = str(exc)
    if not verdict.get("evidence"):
        return None, {"reason": "veredicto sin evidencia (invalidado)",
                      "raw_total": info.get("raw_total")}
    cand = pick_blind(verdict, label_map)
    if cand and cand in eligible:
        return cand, info
    return None, {"reason": "ganador ciego invalido o inelegible",
                  "raw_total": info.get("raw_total")}

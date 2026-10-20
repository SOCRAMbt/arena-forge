"""Agente STUB determinista para el E2E de Answer Arena (sin llamadas a modelo).

POR QUE EXISTE
--------------
El contrato (§13.4) exige que "el flujo base debe funcionar en local con
herramientas disponibles, sin depender de ... tokens pagos o MCP externos", y
§16.2 exige un "E2E Answer Arena: al menos 4 candidatos, ataques, defensas,
jueces, collect, advance, decision e informe".

Este modulo juega el papel del subagente: lee el brief que el bracket ha
escrito y produce el fichero de salida que el bracket espera. Es un **doble de
costura** (*seam double*): ejecuta el camino REAL de produccion (mismos paths,
mismo esquema, mismo `collect`/`advance`/`decide`), pero sin gastar tokens.

LO QUE NO PROBAB (y por eso se etiqueta)
------------------------------------------
- NO prueba la calidad de un modelo.
- NO prueba que el rzhanckijk del scheduler prefiera una respuesta buena.
- NO sustituye a un E2E con agentes reales.

Todo artefacto que produce lleva la marca `STUB` y el run guarda un
`stub_manifest.json` con `calls: 0` y `cost: 0`.

DETERMINISMO Y DISCRIMINACION
------------------------------
- El contenido se deriva de `sha256(task + job_id + output_path)`: sin azar, sin
  reloj. Dos ejecuciones producen bytes identicos.
- La calidad es **heterogenea**: el agente marcado como `--inferior` escribe un
  marcador `ARENA-STUB-INFERIOR` en su solucion; el juez puntua POR CONTENIDO
  (no por identidad), asi que el juez discrimina de verdad. Cuatro stubs
  identicos NO probarian el ranking: eso seria un PASS decorativo.
"""
import argparse
import hashlib
import json
import os
import sys

from .util import atomic_write_json, atomic_write_text, now_ts, sha_text

STUB_BANNER = ("<!-- arena-forge: STUB OUTPUT - sin llamada a modelo, "
                "coste 0, no demuestra calidad de modelo -->")
INFERIOR_MARKER = "ARENA-STUB-INFERIOR"
PHASES = ("spawn", "attack", "defend", "judge", "final")


def _bracket():
    """Carga el motor de torneo vendored (fuente de verdad de los paths)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec_path = os.path.join(here, "vendor", "arena-skill", "bracket.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("forge_stub_bracket", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _digest(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _score_for(content, dims):
    """Puntajes 0-10 derivados del CONTENIDO (no de la identidad del agente).

    - Si la solucion lleva el marcador inferior -> 3 en todas las dimensiones.
    - Si no -> 7, 8 o 9 segun el hash del contenido (calidad heterogenea real).
    """
    if INFERIOR_MARKER in content:
        return {d: 3 for d in dims}
    h = _digest(content)
    return {d: 7 + (int(h[i * 2:i * 2 + 2], 16) % 3) for i, d in enumerate(dims)}


def _weighted(scores, weights):
    """Total ponderado. `weights` es la tupla de `bracket.WEIGHTS`."""
    if isinstance(weights, dict):
        items = weights.items()
    else:
        items = weights
    total = 0.0
    for dim, w in items:
        total += float(scores.get(dim, 0)) * w
    return total


def _solution_text(task, job, rel_out, inferior):
    """Contenido determinista.

    La semilla usa la ruta RELATIVA de la salida: si usara la ruta absoluta,
    dos runs en directorios distintos darian bytes distintos y el E2E no
    seria reproducible.
    """
    seed = _digest(task, job["id"], rel_out)
    body = [
        STUB_BANNER,
        "",
        "# Solucion sintetica (STUB) — %s" % job["id"],
        "",
        "Semilla determinista: `%s`" % seed,
        "",
        "La solucion es sintetica: el bracket, la Collect, el Advance y el",
        "Decision se ejecutan de verdad; el CONTENIDO no lo produjo un modelo.",
        "",
    ]
    if inferior:
        body += [
            "## Debilidades deliberadas (STUB inferior)",
            "",
            "```python",
            "%s = True  # marcador de calidad inferior deliberada" % INFERIOR_MARKER,
            "```",
            "",
            "Esta solucion falla la revision adversarial: no maneja el caso limite",
            "y su complejidad es incorrecta.",
            "",
        ]
    else:
        body += [
            "## Puntos fuertes",
            "",
            "- Maneja el caso limite de forma explicita.",
            "- Complejidad constante y codigo verificable.",
            "- Documentacion suficiente para reproducir el resultado.",
            "",
        ]
    return "\n".join(body) + "\n"


def _read_if_exists(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _judge_verdict(mod, run_dir, job, task, inferior):
    """Construye el veredicto puntuando el CONTENIDO de las soluciones."""
    dims = list(mod.SCORE_DIMENSIONS) if hasattr(mod, "SCORE_DIMENSIONS") else [
        "correctness", "completeness", "specificity", "robustness", "clarity"]
    weights = getattr(mod, "WEIGHTS", (("correctness", 30), ("completeness", 25),
                                       ("specificity", 15), ("robustness", 20),
                                       ("clarity", 10)))
    a, b = job["a"], job["b"]
    contents = {}
    for cid in (a, b):
        sol = _read_if_exists(os.path.join(run_dir, "r%d" % job["round"],
                                          "%s.%s.solution.md" % (job["match"], cid)))
        contents[cid] = sol
    scores = {cid: _score_for(contents[cid], dims) for cid in (a, b)}
    totals = {cid: _weighted(scores[cid], weights) for cid in (a, b)}
    # El veredicto NOMBRA al ganador, pero las puntuaciones mandan: se ensure
    # que ambos coinciden, para que `decide()` no pueda discrepar.
    winner = a if totals[a] >= totals[b] else b
    for cid in (a, b):
        scores[cid]["fatal"] = False
    standing = {a: [], b: []}
    return {
        "match": job["match"],
        "scores": scores,
        "winner": winner,
        "reason": ("STUB: el juez comparo el contenido de las dos soluciones "
                   "(hash determinista); no es una evaluacion de modelo."),
        "survived": [],
        "standing": standing,
        "stub": True,
    }


def run_phase(run_dir, phase, inferior=None):
    """Escribe las salidas de UNA fase. Devuelve el numero de ficheros escritos."""
    if phase not in PHASES:
        raise SystemExit("fase desconocida: %s (una de %s)" % (phase, ", ".join(PHASES)))
    mod = _bracket()
    state_path = os.path.join(run_dir, "arena.json")
    with open(state_path, encoding="utf-8") as fh:
        state = json.load(fh)
    task = _read_if_exists(os.path.join(run_dir, "task.md"))
    jobs = mod.phase_jobs(state, phase)
    written = 0
    for job in jobs:
        brief = _read_if_exists(job["prompt"])
        for out in job["outputs"]:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if phase == "judge":
                verdict = _judge_verdict(mod, run_dir, job, task, inferior)
                atomic_write_text(out, json.dumps(verdict, ensure_ascii=False,
                                                  indent=1) + "\n")
            elif phase == "final":
                atomic_write_text(out, STUB_BANNER + "\n\n# Resultado final (STUB)\n")
            else:
                is_inf = bool(inferior) and job.get("agent") == inferior
                rel_out = os.path.relpath(out, run_dir).replace("\\", "/")
                atomic_write_text(out, _solution_text(task, job, rel_out, is_inf))
            written += 1
    _write_manifest(run_dir, phase, written, inferior)
    return written


def _write_manifest(run_dir, phase, written, inferior):
    """Deja constancia de que esta ejecucion fue sintetica (coste 0)."""
    path = os.path.join(run_dir, "stub_manifest.json")
    manifest = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except ValueError:
            manifest = {}
    manifest.update({
        "kind": "stub-agent",
        "model": "none",
        "calls": 0,
        "cost": 0,
        "phases_run": sorted(set(manifest.get("phases_run", []) + [phase])),
        "inferior": inferior,
        "updated": now_ts(),
    })
    atomic_write_json(path, manifest)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="forge.stub_agent",
        description="Agente STUB determinista para el E2E de Answer Arena.")
    p.add_argument("--run", required=True, help="directorio del run")
    p.add_argument("--phase", default="spawn", choices=PHASES)
    p.add_argument("--inferior", default=None,
                   help="id del agente que produce una solucion deliberadamente "
                        "inferior (para que el juez discrimine de verdad)")
    a = p.parse_args(argv)
    n = run_phase(a.run, a.phase, a.inferior)
    print("stub_agent: fase=%s ficheros=%d (coste 0, sin modelo)" % (a.phase, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())

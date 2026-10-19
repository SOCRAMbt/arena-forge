"""Verificaciones de contenido ligadas al artefacto (P0-2).

Este modulo concentra las comprobaciones que deben repetirse en CADA
transicion critica (gates -> report -> verify -> apply), porque son las que
garantizan que el artefacto entregado al usuario es exactamente el que se
evaluo:

  * la suite protegida sigue siendo la misma (se RECALCULA, no se compara con
    el valor almacenado);
  * el baseline sigue siendo el mismo (commit + dirty state en Git; manifiesto
    versionado fuera de Git);
  * el manifiesto del candidato sigue coincidiendo con el evaluado;
  * el `diff_sha` del gate sigue siendo el hash del diff recalculado;
  * los bytes del parche exportado coinciden con el `diff_sha` y, al aplicarse
    sobre el baseline congelado, reproducen el arbol del candidato.

Ninguna de estas comprobaciones puede darse por buena porque se verifico en un
momento anterior: se repiten en el momento de la transicion.
"""
import os
import subprocess

from .util import ForgeError, sha_file, sha_text

# Version del algoritmo de manifiesto del baseline. Cambiarlo invalida los
# manifiestos congelados antiguos (fail-closed), que es lo correcto.
BASELINE_MANIFEST_VERSION = "baseline-manifest-v1"


# --------------------------------------------------------------------- git
def git_toplevel(path):
    """Raiz del repositorio Git que contiene `path`, o None."""
    if not path or not os.path.isdir(path):
        return None
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"],
                           text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    top = (r.stdout or "").strip()
    return top or None


def is_own_git_repo(path):
    """True si `path` ES la raiz de un repositorio Git.

    Un directorio que merelyamente cuelga de un repositorio (por ejemplo
    `fixtures/...` dentro del propio repo de Arena Forge) NO es su propio
    baseline Git: usar el commit de ese repositorio seria incorrecto.
    """
    top = git_toplevel(path)
    if not top:
        return False
    try:
        return os.path.realpath(top) == os.path.realpath(path)
    except OSError:
        return False


def git_head(path):
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                           text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return (r.stdout or "").strip() or None


def git_dirty(path):
    """True si el repositorio tiene cambios sin commit (incluye untracked)."""
    try:
        r = subprocess.run(["git", "-C", path, "status", "--porcelain"],
                           text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return bool((r.stdout or "").strip())


# ---------------------------------------------------------------- manifiesto
def baseline_manifest(path):
    """Manifiesto determinista del contenido de un baseline (no-Git o Git).

    Mismo algoritmo versionado siempre, para que la comparacion sea posible
    con o sin Git.
    """
    from .isolation import tree_sha
    try:
        return tree_sha(path)
    except ForgeError as exc:
        raise ForgeError("baseline ilegible: %s" % exc)


# -------------------------------------------------------------------- suite
def recompute_suite_sha(run):
    """Recalcula el hash VIVO de la suite protegida y lo compara.

    Devuelve (ok, reason, sha_actual).
    """
    from . import gates as gate_engine
    suite = run.get("suite")
    if not suite:
        return False, "sin suite declarada en el run", None
    if not os.path.exists(suite):
        return False, "suite protegida ausente: %s" % suite, None
    # La suite no puede haber sido sustituida por un symlink.
    if os.path.islink(suite):
        return False, "la suite protegida es un symlink: %s" % suite, None
    actual = gate_engine.suite_sha(suite)
    if actual is None:
        return False, "suite protegida sin ficheros de test: %s" % suite, None
    expected = run.get("suite_sha")
    if not expected:
        return False, "suite_sha congelado ausente en el run", None
    if actual != expected:
        return False, ("suite modificada (sha actual=%s congelado=%s)"
                       % (actual, expected)), actual
    return True, "suite intacta", actual


def suite_outside_candidates(run):
    """True si la suite esta fuera de todo workspace candidato."""
    from . import gates as gate_engine
    suite = run.get("suite")
    run_dir = run.get("dir")
    if not suite or not run_dir:
        return True
    return gate_engine.suite_is_outside_workspaces(suite, run_dir)


# ------------------------------------------------------------------ baseline
def verify_baseline(run):
    """Revalida el baseline objetivo. Devuelve (ok, reason).

    En Git: HEAD exacto + arbol limpio.
    Sin Git: el manifiesto de contenido recalculado debe coincidir con el
    congelado. Si el baseline cambio, se BLOQUEA aunque los gates fueran PASS.
    """
    target = run.get("target_baseline_dir")
    if not target:
        # Sin baseline externo declarado no hay nada que revalidar.
        return True, "sin baseline externo declarado"
    if not os.path.isdir(target):
        return False, "baseline objetivo ausente: %s" % target
    if is_own_git_repo(target):
        expected_head = run.get("target_baseline_commit")
        current = git_head(target)
        if expected_head and expected_head != "n/a-no-repo":
            if current != expected_head:
                return False, ("baseline Git cambio (HEAD %s != congelado %s)"
                               % (current, expected_head))
        dirty = git_dirty(target)
        if dirty:
            return False, "baseline Git tiene cambios sin commit: %s" % target
        return True, "baseline Git intacto (%s)" % (current or "?")
    frozen = run.get("baseline_manifest")
    if not frozen:
        return False, "baseline no-Git sin manifiesto congelado"
    try:
        current_manifest = baseline_manifest(target)
    except ForgeError as exc:
        return False, str(exc)
    if current_manifest != frozen:
        return False, ("baseline no-Git cambio (manifiesto %s != congelado %s)"
                       % (current_manifest, frozen))
    return True, "baseline no-Git intacto"


def verify_frozen_baseline(run):
    """Revalida la COPIA congelada del baseline (`<run>/baseline`).

    Es el arbol contra el que los gates calcularon el diff: si cambia, el
    `diff_sha` del gate ya no describe el parche que se exportaria.
    """
    run_dir = run.get("dir")
    if not run_dir:
        return True, "sin dir de run"
    frozen_dir = os.path.join(run_dir, "baseline")
    if not os.path.isdir(frozen_dir):
        return True, "sin copia congelada de baseline"
    expected = run.get("frozen_baseline_manifest")
    if not expected:
        return False, "copia congelada del baseline sin manifiesto"
    try:
        current = baseline_manifest(frozen_dir)
    except ForgeError as exc:
        return False, str(exc)
    if current != expected:
        return False, ("baseline congelado cambio (manifiesto %s != %s)"
                       % (current, expected))
    return True, "baseline congelado intacto"


# --------------------------------------------------------------- artefacto
def verify_diff_hashes(run_dir, run, gates, candidates=None):
    """Recalcula el diff de cada candidato y lo compara con el `diff_sha` del gate.

    Devuelve (ok, reason). El `diff_sha` del gate solo se aceptaba por su
    formato; ahora se RECALCULA y se COMPARA.
    """
    from . import isolation
    base = os.path.join(run_dir, "baseline")
    for cid in sorted(gates.keys()):
        g = gates.get(cid) or {}
        recorded = g.get("diff_sha")
        if not recorded:
            return False, "candidato %s sin diff_sha en gate" % cid
        cdir = os.path.join(run_dir, "candidates", cid)
        if not os.path.isdir(cdir):
            continue  # el manifiesto ya se valida por separado
        try:
            diff_bytes = isolation.capture_diff(base, cdir) if os.path.isdir(base) else b""
        except ForgeError as exc:
            return False, "candidato %s: no se pudo recalcular el diff (%s)" % (cid, exc)
        actual = isolation.diff_sha(diff_bytes)
        if actual != recorded:
            return False, ("candidato %s: diff_sha no coincide (recalculado=%s "
                           "gate=%s)" % (cid, actual, recorded))
    return True, "diff_sha de todos los gates recalculado y coincide"


def verify_exported_artifact(run_dir, run, gates, winner, patch_bytes):
    """Verifica que los bytes exportados son el diff evaluado y lo reproducen.

    1. sha256(parche exportado) == diff_sha del gate del ganador.
    2. Al aplicar el parche sobre el baseline congelado, el arbol resultante
       tiene el MISMO manifiesto que el candidato evaluado.
    """
    from . import isolation
    g = (gates or {}).get(winner) or {}
    recorded = g.get("diff_sha")
    if not recorded:
        return False, "ganador %s sin diff_sha en gate" % winner
    actual = isolation.diff_sha(patch_bytes)
    if actual != recorded:
        return False, ("el parche exportado no es el diff evaluado "
                       "(exportado=%s gate=%s)" % (actual, recorded))
    base = os.path.join(run_dir, "baseline")
    cdir = os.path.join(run_dir, "candidates", winner)
    if not os.path.isdir(base) or not os.path.isdir(cdir):
        return False, "baseline congelado o candidato ausente"
    try:
        scratch = isolation.apply_diff_to_temp(patch_bytes, base)
    except ForgeError as exc:
        return False, "el parche exportado no se aplica: %s" % exc
    try:
        rebuilt = isolation.tree_sha(scratch)
        expected = isolation.tree_sha(cdir)
    except ForgeError as exc:
        shutil_rmtree(scratch)
        return False, str(exc)
    shutil_rmtree(scratch)
    if rebuilt != expected:
        return False, ("el parche no reproduce el candidato evaluado "
                       "(arbol=%s candidato=%s)" % (rebuilt, expected))
    return True, "parche exportado == diff evaluado y reproduce el candidato"


def shutil_rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


# ------------------------------------------------------------------ gates
def verify_gate_results(gates):
    """Comprueba que cada GateResult tiene la forma que exige el contrato."""
    from . import contracts
    problems = []
    for cid, g in sorted(gates.items()):
        errs = contracts.validate_gate_result(g, where="GateResult[%s]" % cid)
        if errs:
            problems.extend(errs)
    return (not problems), problems


def artifact_hashes(path):
    """SHA-256 de un artefacto en disco (para el informe)."""
    return sha_file(path) if os.path.isfile(path) else sha_text("")

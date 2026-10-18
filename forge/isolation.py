"""Workspace / Isolation Manager (§3.7, §13.3).

Garantiza que dos candidatos NUNCA comparten directorio de escritura. Como el
runtime no permite dirigir con fiabilidad cada sesion de subagente a un worktree
propio (capacidad `subagent_worktree` = unknown en el adapter), Patch Arena usa
la ALTERNATIVA SEGURA de la especificacion:

  1. cada candidato escribe solo en `candidates/<id>/`;
  2. sus cambios se capturan como diff unificado versionado;
  3. un ejecutor controlado aplica el diff a una COPIA temporal del baseline;
  4. los gates corren alli, no en el arbol real.

Nada del proyecto principal se modifica.
"""
import difflib
import os
import shutil
import tempfile

from .util import (ForgeError, assert_inside, inside, sha_file, sha_text)


def candidates_root(run_dir):
    return assert_inside(run_dir, os.path.join(run_dir, "candidates"), "candidates")


def ensure_workspaces(run_dir, candidate_ids):
    """Crea un directorio propio por candidato y devuelve la prueba de aislamiento."""
    root = candidates_root(run_dir)
    os.makedirs(root, exist_ok=True)
    proof = {"root": os.path.relpath(root, run_dir), "candidates": {}, "shared": False,
             "ok": True, "problems": []}
    seen = {}
    for cid in candidate_ids:
        cdir = os.path.join(root, cid)
        os.makedirs(cdir, exist_ok=True)
        real = os.path.realpath(cdir)
        if real in seen:
            proof["problems"].append("dos candidatos comparten ruta: %s" % real)
            proof["shared"] = True
            proof["ok"] = False
        seen[real] = cid
        if not inside(run_dir, real):
            proof["problems"].append("candidato fuera del run: %s" % real)
            proof["ok"] = False
        proof["candidates"][cid] = {"dir": os.path.relpath(cdir, run_dir),
                                    "realpath": real}
    return proof


def capture_diff(baseline_dir, candidate_dir, name_hint=""):
    """Diff unificado de los ficheros del candidato respecto al baseline."""
    chunks = []
    if not os.path.isdir(candidate_dir):
        return ""
    for name in sorted(os.listdir(candidate_dir)):
        p_new = os.path.join(candidate_dir, name)
        if not os.path.isfile(p_new):
            continue
        p_old = os.path.join(baseline_dir, name)
        old = _lines(p_old)
        new = _lines(p_new)
        rel = os.path.join(name_hint, name) if name_hint else name
        chunks.append("".join(difflib.unified_diff(
            old, new, "a/" + rel, "b/" + rel)))
    return "".join(chunks)


def _lines(path):
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readlines()
    return []


def diff_sha(diff_text):
    return sha_text(diff_text)


def validate_diff(diff_text):
    """Rechaza diffs que intenten rutas fuera del arbol de trabajo."""
    problems = []
    for line in diff_text.splitlines():
        if line.startswith(("--- ", "+++ ")):
            target = line[4:].strip().split("\t")[0].strip()
            if target in ("/dev/null",):
                continue
            if target.startswith("/") or ".." in target.replace("a/", "").replace("b/", ""):
                problems.append("ruta sospechosa en diff: %r" % target)
    return (not problems), problems


def apply_diff_to_temp(diff_text, baseline_dir):
    """Ejecutor controlado: aplica el diff a una copia temporal del baseline.

    Devuelve la ruta del scratch. El arbol real no se toca nunca.
    """
    ok, problems = validate_diff(diff_text)
    if not ok:
        raise ForgeError("diff inseguro: %s" % "; ".join(problems))
    scratch = tempfile.mkdtemp(prefix="forge-isolate-")
    if os.path.isdir(baseline_dir):
        for name in os.listdir(baseline_dir):
            src = os.path.join(baseline_dir, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(scratch, name))
    if diff_text.strip():
        # parche compatible con `patch -p1`/`git apply`; se aplica con difflib no
        # disponible -> usamos `git apply` si hay git, si no `patch`.
        applied = _apply(scratch, diff_text)
        if not applied:
            shutil.rmtree(scratch, ignore_errors=True)
            raise ForgeError("no se pudo aplicar el diff a la copia temporal")
    return scratch


def _apply(scratch, diff_text):
    import subprocess
    import sys
    diff_path = os.path.join(scratch, ".forge.patch")
    with open(diff_path, "w", encoding="utf-8") as fh:
        fh.write(diff_text)
    for cmd in (["git", "apply", "-p1", ".forge.patch"],
                ["patch", "-p1", "-i", ".forge.patch"]):
        try:
            r = subprocess.run(cmd, cwd=scratch, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=60)
            if r.returncode == 0:
                os.remove(diff_path)
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    if os.path.exists(diff_path):
        os.remove(diff_path)
    return False

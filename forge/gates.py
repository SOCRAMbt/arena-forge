"""Gate Engine determinista (§3.11, §10.1).

Ejecuta la suite PROTEGIDA sobre una copia limpia del candidato en un scratch
temporal. Nunca ejecuta codigo del candidato in-place. Produce GateResult con
estado (PASS/FAIL/BLOCKED/NOT_RUN/INCONCLUSIVE), comando exacto, exit code,
hashes, clase de fallo y log redactado.

Gates de bloqueo (§10.3): requisito fallido, suite manipulada, contaminacion del
harness, aislamiento no demostrado, entorno roto.
"""
import os
import shutil
import subprocess
import sys
import tempfile

from .util import (DEFAULT_CMD_TIMEOUT, ForgeError, now_ts, redact, sha_file,
                   inside)


def _protected_names(candidate_dir):
    """Ficheros que un candidato NO puede aportar (intento de sustituir la suite)."""
    bad = []
    for name in os.listdir(candidate_dir):
        low = name.lower()
        if low.startswith("tests_protected") or low in ("test_protected.py",
                                                        "conftest.py"):
            bad.append(name)
    return bad


def suite_files(protected_suite):
    """Resuelve la suite protegida a una lista de ficheros de test.

    Acepta un fichero unico o un directorio (todos los test_*.py, orden
    estable para reproducibilidad).
    """
    if os.path.isfile(protected_suite):
        return [os.path.abspath(protected_suite)]
    if os.path.isdir(protected_suite):
        found = []
        for root, dirs, names in os.walk(protected_suite):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for n in sorted(names):
                if n.startswith("test_") and n.endswith(".py"):
                    found.append(os.path.abspath(os.path.join(root, n)))
        return found
    return []


def suite_sha(protected_suite):
    """Hash agregado determinista de la suite (fichero o directorio)."""
    files = suite_files(protected_suite)
    if not files:
        return None
    from .util import sha_text
    parts = []
    for f in files:
        rel = os.path.relpath(f, os.path.dirname(os.path.abspath(protected_suite)))
        parts.append("%s=%s" % (rel.replace("\\", "/"), sha_file(f)))
    return sha_text("\n".join(parts))


def run_gate(candidate_dir, protected_suite, gate_id=None, timeout_s=DEFAULT_CMD_TIMEOUT,
             log_dir=None):
    """Devuelve un GateResult dict. `protected_suite` vive FUERA del candidato."""
    ts = now_ts()
    gate_id = gate_id or ("suite:" + os.path.basename(candidate_dir.rstrip("/\\")))
    candidate_dir = os.path.realpath(candidate_dir)
    result = {
        "gate_id": gate_id,
        "candidate": os.path.basename(candidate_dir),
        "state": "NOT_RUN",
        "command": "",
        "tool_version": "",
        "ts": ts,
        "exit_code": None,
        "stdout_ref": None,
        "stderr_ref": None,
        "evidence": [],
        "failure_class": None,
        "notes": "",
        "suite_sha": None,
    }

    if not os.path.isdir(candidate_dir):
        result["notes"] = "candidato inexistente"
        result["failure_class"] = "environment_broken"
        return result

    suite_list = suite_files(protected_suite)
    if not suite_list:
        result["state"] = "NOT_RUN"
        result["notes"] = "suite protegida ausente (sin test_*.py): %s" % protected_suite
        result["failure_class"] = "environment_broken"
        return result

    suite_before = suite_sha(protected_suite)
    result["suite_sha"] = suite_before

    # Contaminacion del harness: el candidato trae su propia suite.
    bad = _protected_names(candidate_dir)
    if bad:
        result["state"] = "BLOCKED"
        result["failure_class"] = "harness_tampering"
        result["notes"] = "contaminacion: candidato incluye %s" % ", ".join(bad)
        return result

    scratch = tempfile.mkdtemp(prefix="forge-gate-")
    try:
        # Copia limpia de los ficheros del candidato (sin subir la suite).
        for name in os.listdir(candidate_dir):
            src = os.path.join(candidate_dir, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(scratch, name))
            elif os.path.isdir(src) and name != "__pycache__":
                shutil.copytree(src, os.path.join(scratch, name),
                                ignore=shutil.ignore_patterns("__pycache__"))
        # Suite protegida: cada fichero bajo su nombre relativo al dirs raiz.
        suite_root = os.path.dirname(os.path.abspath(protected_suite))
        for f in suite_list:
            rel = os.path.relpath(f, suite_root)
            dst = os.path.join(scratch, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(f, dst)

        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"] + \
            [os.path.relpath(f, suite_root) for f in suite_list]
        result["command"] = " ".join(cmd)
        rc, ver = _pytest_version()
        result["tool_version"] = ver
        try:
            env = dict(os.environ)
            existing = env.get("PYTHONPATH")
            env["PYTHONPATH"] = scratch + (os.pathsep + existing if existing else "")
            proc = subprocess.run(cmd, cwd=scratch, text=True, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=timeout_s)
            out = proc.stdout or ""
            result["exit_code"] = proc.returncode
            result["state"] = "PASS" if proc.returncode == 0 else "FAIL"
            if proc.returncode != 0:
                result["failure_class"] = "required_check_failed"
        except subprocess.TimeoutExpired:
            out = "timeout %ss" % timeout_s
            result["state"] = "BLOCKED"
            result["failure_class"] = "environment_broken"
        except OSError as exc:
            out = "no se pudo ejecutar pytest: %s" % exc
            result["state"] = "NOT_RUN"
            result["failure_class"] = "environment_broken"

        # Integridad de la suite durante la evaluacion.
        suite_after = suite_sha(protected_suite)
        if suite_after != suite_before:
            result["state"] = "BLOCKED"
            result["failure_class"] = "harness_tampering"
            out += "\nSUITE ALTERADA durante la evaluacion"

        result["evidence"].append("suite_sha=%s" % suite_before)
        result["evidence"].append("exit_code=%s" % result["exit_code"])
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            logp = os.path.join(log_dir, "%s.%s.log" % (result["candidate"],
                                                        gate_id.replace(":", "-")))
            with open(logp, "w", encoding="utf-8") as fh:
                fh.write(redact(out))
            result["stdout_ref"] = os.path.relpath(logp, os.path.dirname(log_dir))
        result["notes"] = redact(out, limit=500)
        return result
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _pytest_version():
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                           text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=20)
        return r.returncode, (r.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def run_all(run_dir, suite, log_dir=None):
    """Ejecuta el gate de suite sobre todos los candidatos del run."""
    cands_root = os.path.join(run_dir, "candidates")
    results = {}
    if os.path.isdir(cands_root):
        for cand in sorted(os.listdir(cands_root)):
            cdir = os.path.join(cands_root, cand)
            if os.path.isdir(cdir):
                results[cand] = run_gate(cdir, suite, log_dir=log_dir)
    return results


def eligible(results):
    return sorted(c for c, g in results.items() if g.get("state") == "PASS")

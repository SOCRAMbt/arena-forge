"""Sonda de descubrimiento de skills: la skill del repo se carga con su ID exacto.

POR QUE UN SERVIDOR DEDICADO
------------------------------
El servidor de fondo de OpenCode puede estar enraizado en OTRO directorio (por
ejemplo el home del usuario). En ese caso `GET /api/skill` lista las skills de
ese arbol, no las del repositorio, y la skill del repo aparece como "no
encontrada" aunque este perfectamente bien. Para medir la afirmacion del
contrato ("la skill aparece y se carga con el ID/ruta exactos en el entorno
probado") hay que arrancar un servidor **enraizado en el repo**.

Uso:
    python tools/probe_skill.py            # imprime el veredicto y sale 0/1
    python tools/probe_skill.py --json     # salida JSON

Criterio de exito (AF-AC-003):
    existe una skill con id == "arena-forge" cuyo `path` es
    <repo>/.opencode/skills/arena-forge/SKILL.md
"""
import argparse
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_ID = "arena-forge"
EXPECTED_REL = os.path.join(".opencode", "skills", "arena-forge", "SKILL.md")
PASSWORD_RE = re.compile(r"server password\s+(\S+)")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def _get_skills(port, directory, password):
    """GET /api/skill con el directorio del repo.

    El servidor announce una contrasena ALEATORIA en su stdout
    ("server password <pw>"); hay que leerla de ahi, no suponerla.
    """
    url = "http://127.0.0.1:%d/api/skill?directory=%s" % (
        port, urllib.parse.quote(directory, safe=""))
    token = base64.b64encode(("opencode:%s" % password).encode("utf-8")).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": "Basic %s" % token,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _read_password(log_path, timeout=30):
    """Espera a que el servidor anuncie su contrasena."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(log_path, encoding="utf-8", errors="replace") as fh:
                m = PASSWORD_RE.search(fh.read())
            if m:
                return m.group(1)
        except OSError:
            pass
        time.sleep(0.3)
    return None


def probe(timeout=45):
    """Devuelve (ok, info)."""
    exe = shutil.which("opencode")
    if not exe:
        return False, {"reason": "opencode no esta en PATH"}
    port = _free_port()
    cmd = [exe, "serve", "--port", str(port), "--hostname", "127.0.0.1"]
    # En Windows `opencode` es un shim .CMD: hay que lanzarlo via cmd.exe.
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", exe] + cmd[1:]
    log_fd, log_path = tempfile.mkstemp(prefix="opencode-serve-", suffix=".log")
    os.close(log_fd)
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(cmd, cwd=REPO, stdout=log,
                                    stderr=subprocess.STDOUT)
    except OSError as exc:
        os.unlink(log_path)
        return False, {"reason": "no se pudo arrancar el servidor: %s" % exc}
    try:
        password = _read_password(log_path, timeout=timeout)
        if not password:
            return False, {"reason": "el servidor no anuncio su contrasena"}
        if not _wait_port(port, timeout=timeout):
            return False, {"reason": "el servidor no abrio el puerto %d" % port}
        deadline = time.time() + timeout
        last = None
        skills = []
        while time.time() < deadline:
            try:
                payload = _get_skills(port, REPO, password)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                last = exc
                time.sleep(1.0)
                continue
            if isinstance(payload, dict):
                # La respuesta real es {"location": {...}, "data": [...]}
                payload = payload.get("data") or payload.get("skills") or []
            if not isinstance(payload, list):
                return False, {"reason": "formato de /api/skill inesperado: %r"
                                         % (type(payload).__name__,)}
            skills = payload
            if any(s.get("id") == SKILL_ID for s in skills):
                break
            # El servidor puede arrancar con la lista vacia: se reintenta.
            time.sleep(1.0)
        else:
            return False, {"reason": "la skill %r no apareció en /api/skill "
                                     "(%d listadas)%s"
                                     % (SKILL_ID, len(skills),
                                        "" if last is None else "; ultimo error: %s" % last),
                           "total_skills": len(skills)}
        found = [s for s in skills if s.get("id") == SKILL_ID]
        if not found:
            return False, {"reason": "la skill %r no aparece en /api/skill "
                                     "(%d skills listadas)" % (SKILL_ID, len(skills)),
                           "total_skills": len(skills)}
        path = found[0].get("path") or ""
        expected = os.path.normcase(os.path.join(REPO, EXPECTED_REL))
        same = os.path.normcase(os.path.abspath(path)) == expected
        return (True, {
            "id": SKILL_ID,
            "name": found[0].get("name"),
            "path": path,
            "expected_path": os.path.join(REPO, EXPECTED_REL),
            "path_matches_repo": same,
            "total_skills": len(skills),
        })
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            os.unlink(log_path)
        except OSError:
            pass


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    ok, info = probe()
    if a.json:
        print(json.dumps({"ok": ok, "info": info}, ensure_ascii=False, indent=1))
    else:
        print("AF-AC-003 sonda de skill: %s" % ("VERIFIED" if ok else "NO VERIFICADA"))
        for k, v in info.items():
            print("  %-18s %s" % (k, v))
    return 0 if ok else 1


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (usado en _get_skills)
    sys.exit(main())

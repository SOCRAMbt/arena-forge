"""Gate Engine determinista (§3.11, §10.1).

Ejecuta la suite PROTEGIDA sobre una copia limpia del candidato en un scratch
temporal. Nunca ejecuta codigo del candidato in-place. Produce GateResult con
estado (PASS/FAIL/BLOCKED/NOT_RUN/INCONCLUSIVE), comando exacto, exit code,
hashes, clase de fallo y log redactado.

Gates de bloqueo (§10.3): requisito fallido, suite manipulada, contaminacion del
harness, aislamiento no demostrado, entorno roto.

MODO DE SEGURIDAD
-----------------
`SECURITY_MODE = "TRUSTED_CODE_ONLY"`. Este runtime (Windows sin Job Object,
sin AppContainer, sin usuario de minimos privilegios) NO ofrece una frontera de
sistema operativo: no hay filesystem restringido ni red bloqueada. El scratch
temporal + el entorno filtrado son medidas de HIGIENE, no un sandbox. El
GateResult declara el modo para que ningun consumidor pueda confundirlo.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile

from .util import (DEFAULT_CMD_TIMEOUT, ForgeError, MAX_OUTPUT_BYTES, now_ts,
                   redact, sha_file, inside)
from . import isolation
from .isolation import candidate_manifest_sha

SECURITY_MODE = isolation.SECURITY_MODE

# Ficheros de configuracion de pytest que el CANDIDATO no puede aportar: pueden
# cambiar que se ejecuta, que plugins se cargan o donde se buscan las fixtures.
FORBIDDEN_CANDIDATE_FILES = ("conftest.py", "sitecustomize.py", "usercustomize.py",
                              "pytest.ini", "pyproject.toml", "tox.ini",
                              "setup.cfg")

# Ficheros de configuracion que forman parte de la suite PROTEGIDA: si cambian,
# el hash de la suite debe cambiar (si no, la alteracion seria invisible).
SUITE_CONFIG_FILES = ("conftest.py", "pytest.ini", "pyproject.toml", "tox.ini",
                       "setup.cfg")


def _protected_names(candidate_dir):
    """Ficheros que un candidato NO puede aportar (intento de sustituir la suite).

    Recorre TODO el arbol del candidato, no solo el nivel superior: un
    `conftest.py` en un subdirectorio tambien es cargado por pytest.
    """
    bad = []
    for dirpath, dirs, names in os.walk(candidate_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(names):
            low = name.lower()
            if low.startswith("tests_protected") or low in FORBIDDEN_CANDIDATE_FILES:
                bad.append(os.path.relpath(os.path.join(dirpath, name), candidate_dir))
    return bad


def suite_files(protected_suite):
    """Resuelve la suite protegida a una lista de ficheros de test.

    Acepta un fichero unico o un directorio. Incluye los ficheros de
    configuracion de pytest (`conftest.py`, `pytest.ini`, ...) porque modificarlos
    cambia el significado de la suite: si no entran en el hash, su alteracion
    seria invisible.
    """
    if os.path.isfile(protected_suite):
        return [os.path.abspath(protected_suite)]
    if os.path.isdir(protected_suite):
        found = []
        for root, dirs, names in os.walk(protected_suite):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for n in sorted(names):
                is_test = n.startswith("test_") and n.endswith(".py")
                is_config = n in SUITE_CONFIG_FILES
                if is_test or is_config:
                    found.append(os.path.abspath(os.path.join(root, n)))
        return sorted(found)
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


def suite_is_outside_workspaces(protected_suite, run_dir):
    """True si la suite protegida NO esta dentro de ningun workspace candidato.

    Si la suite viviese dentro de `candidates/<id>/`, el candidato podria
    modificarla y cambiar la definicion de "correcto".
    """
    suite_real = os.path.realpath(os.path.abspath(protected_suite))
    cands_root = os.path.join(os.path.abspath(run_dir), "candidates")
    if not os.path.isdir(cands_root):
        return True
    for cid in os.listdir(cands_root):
        cdir = os.path.join(cands_root, cid)
        if not os.path.isdir(cdir):
            continue
        if inside(cdir, suite_real) or suite_real.startswith(
                os.path.realpath(cdir) + os.sep):
            return False
    return True


# ------------------------------------------------------------- entorno minimo
_SHIM_CACHE = {}


def _dist_top_level(site_dir, dist_name):
    """Nombres de primer nivel que pertenecen a una distribucion instalada.

    Se leen del `RECORD` de la distribucion: es la lista exacta de ficheros que
    instala el paquete. Sin esto se perderian modulos internos (p.ej. `_pytest`,
    que NO aparece en `Requires-Dist` pero es imprescindible).
    """
    tops = set()
    try:
        entries = sorted(e for e in os.listdir(site_dir)
                         if e.startswith(dist_name + "-") and e.endswith(".dist-info"))
    except OSError:
        return tops
    for entry in entries:
        record = os.path.join(site_dir, entry, "RECORD")
        if not os.path.isfile(record):
            continue
        try:
            with open(record, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    rel = line.split(",")[0].strip().replace("\\", "/")
                    if not rel or rel.startswith(("/", "..")):
                        continue
                    top = rel.split("/")[0]
                    if top and top not in ("..",):
                        tops.add(top)
        except OSError:
            continue
        break
    return tops


def _pytest_shim():
    """Directorio aislado con SOLO pytest y sus dependencias declaradas.

    En este runtime pytest puede vivir en el user site-packages. Anadir el user
    site COMPLETO a PYTHONPATH expondría todos los paquetes del usuario al
    codigo del candidato. Este shim copia unicamente `pytest` y sus
    `Requires-Dist`, y `PYTHONNOUSERSITE=1` impide que se cargue el resto.

    Devuelve (shim_dir|None, user_site_exposed: bool).
    - shim construido  -> (shim, False): nada del entorno del usuario se expone.
    - shim imposible  -> (None, True): no se puede aislar; el llamante DEBE
      bloquear el gate en lugar de exponer el user site en silencio.
    """
    try:
        import pytest  # noqa: F401
    except Exception:
        return None, False
    pkg_dir = os.path.dirname(os.path.abspath(pytest.__file__))
    site_dir = os.path.dirname(pkg_dir)
    if site_dir in _SHIM_CACHE:
        return _SHIM_CACHE[site_dir]
    try:
        shim = tempfile.mkdtemp(prefix="forge-pyshim-")
        tops = _dist_top_level(site_dir, "pytest")
        if not tops:
            shutil.rmtree(shim, ignore_errors=True)
            _SHIM_CACHE[site_dir] = (None, True)
            return None, True
        # Dependencias declaradas de pytest.
        try:
            for entry in os.listdir(site_dir):
                if not (entry.startswith("pytest-") and entry.endswith(".dist-info")):
                    continue
                meta = os.path.join(site_dir, entry, "METADATA")
                if not os.path.isfile(meta):
                    continue
                with open(meta, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if not line.startswith("Requires-Dist:"):
                            continue
                        spec = line.split(":", 1)[1].strip()
                        dep = spec.split(";")[0].strip()
                        for sep in ("[", "(", " ", ">", "<", "=", "!", "~"):
                            dep = dep.split(sep)[0].strip()
                        if dep:
                            tops |= _dist_top_level(site_dir, dep)
        except OSError:
            pass
        copied = 0
        for name in sorted(tops):
            src = os.path.join(site_dir, name)
            dst = os.path.join(shim, name)
            if os.path.isdir(src) and not os.path.islink(src):
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
                copied += 1
            elif os.path.isfile(src) and not os.path.islink(src):
                shutil.copy2(src, dst)
                copied += 1
        if copied == 0:
            shutil.rmtree(shim, ignore_errors=True)
            _SHIM_CACHE[site_dir] = (None, True)
            return None, True
        import atexit
        atexit.register(shutil.rmtree, shim, True)
        _SHIM_CACHE[site_dir] = (shim, False)
        return shim, False
    except Exception:
        return None, True


def _pytest_targets(suite_list, suite_root):
    """Ficheros que se pasan a pytest como objetivos.

    Solo los ficheros de test se pasan como argumento: un `conftest.py` se
    carga por convencion de pytest, no como modulo de test (pasarlo como
    argumento haria que pytest lo recolectara).
    """
    if len(suite_list) == 1 and not os.path.basename(suite_list[0]).startswith("test_"):
        return [os.path.relpath(suite_list[0], suite_root)]
    return [os.path.relpath(f, suite_root) for f in suite_list
            if os.path.basename(f).startswith("test_")]



def _check_marker(marker_path, report_path):
    """Comprueba el marcador de finalizacion escrito por el plugin del harness.

    Devuelve (ok, detalle). El marcador contiene el SHA-256 del informe JUnit
    que el plugin leyo: si el candidato fabrico un informe falso pero no pudo
    escribir el marcador (porque `os._exit` no ejecuta `atexit`), no hay PASS.
    """
    if not os.path.isfile(marker_path):
        return False, "marcador de finalizacion ausente (pytest no termino la sesion)"
    try:
        with open(marker_path, encoding="utf-8") as fh:
            digest = (fh.read() or "").strip()
    except OSError as exc:
        return False, "marcador ilegible: %s" % exc
    if not os.path.isfile(report_path):
        return False, "informe de suite ausente"
    from .util import sha_file
    expected = sha_file(report_path)
    if digest != expected:
        return False, ("el marcador no corresponde al informe de suite "
                       "(marcador=%s informe=%s)" % (digest[:12], expected[:12]))
    return True, "sesion finalizada normalmente"


def _minimal_env(scratch):
    """Entorno minimo allowlist para el subprocess del gate.

    NO se hereda `os.environ`. Se filtran las variables de entorno del usuario
    y se desactiva el autoload de plugins de pytest.

    `HOME`/`USERPROFILE` se apuntan al scratch: el codigo del candidato no
    recibe la ruta del perfil del usuario (donde viven `.ssh`, `.aws`,
    `.config`, `.env`...).
    """
    env = {}
    for key in ("SYSTEMROOT", "COMSPEC", "PATHEXT",
                "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
                "PYTHONIOENCODING", "PYTHONUTF8", "LANG", "LC_ALL"):
        val = os.environ.get(key)
        if val:
            env[key] = val
    # HOME/USERPROFILE/TEMP/TMP: nunca los del operador. TEMP y TMP tambien
    # delatanan el perfil (`%TEMP%` esta bajo `%USERPROFILE%`).
    env["HOME"] = scratch
    env["USERPROFILE"] = scratch
    env["TEMP"] = scratch
    env["TMP"] = scratch
    # PATH: en Windows solo rutas de sistema y de Python (NO el PATH completo
    # del usuario). En POSIX se conserva el PATH: los nombres de programa son
    # case-sensitive y no existe `System32`; filtrarlo dejaria al candidato sin
    # `/usr/bin` y la CI de Linux fallaria.
    if os.name == "nt":
        sys_paths = []
        val = os.environ.get("PATH")
        if val:
            for p in val.split(os.pathsep):
                pl = p.lower()
                if any(x in pl for x in ("python", "system32", "windows", "syswow64")):
                    sys_paths.append(p)
        env["PATH"] = (os.pathsep.join(sys_paths) if sys_paths
                       else os.environ.get("SYSTEMROOT", "") + "\\System32")
    else:
        env["PATH"] = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    shim, user_site_exposed = _pytest_shim()
    paths = [scratch]
    if shim:
        paths.append(shim)
    else:
        # Fallback declarado: sin shim, pytest solo es alcanzable via el
        # directorio que lo contiene. Si ese directorio ES el user
        # site-packages, queda expuesto todo el entorno del usuario: el gate
        # DEBE bloquearse (no se acepta en silencio).
        try:
            import pytest as _pytest
            parent = os.path.dirname(os.path.dirname(os.path.abspath(_pytest.__file__)))
        except Exception:
            parent = ""
        try:
            import site as _site
            user_site = _site.getusersitepackages()
        except Exception:
            user_site = ""
        if parent and os.path.realpath(parent) != os.path.realpath(user_site):
            # pytest vive en el site-packages del SISTEMA: no se expone nada
            # del entorno del usuario.
            paths.append(parent)
            user_site_exposed = False
        else:
            import site
            paths.append(site.getusersitepackages())
            user_site_exposed = True
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONSAFEPATH"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Ningun plugin de pytest se autocarga: los plugins son codigo ejecutable
    # de terceros instalado en el entorno del usuario.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTEST_ADDOPTS"] = ""
    return env, user_site_exposed


# ------------------------------------------------- informe de la suite (XML)
def _parse_junit(path):
    """Parsea el informe JUnit de pytest.

    Devuelve (ok, info). `ok=False` significa que NO hay un informe fiable:
    eso NUNCA puede convertirse en PASS.

    Motivo: el codigo del candidato se importa durante la recoleccion. Con
    `os._exit(0)` en el import, pytest muere con codigo 0 y sin informe; sin
    este control, el gate registraria PASS sin haber ejecutado un solo test.
    """
    if not os.path.isfile(path):
        return False, {"reason": "no se genero el informe de la suite "
                                  "(pytest no llego a ejecutarla)"}
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(path)
    except Exception as exc:
        return False, {"reason": "informe de la suite ilegible: %s" % exc}
    root = tree.getroot()
    suites = ([root] if root.tag == "testsuite"
              else list(root.iter("testsuite")))
    tests = failures = errors = skipped = 0
    ids = []
    for s in suites:
        try:
            tests += int(s.get("tests") or 0)
            failures += int(s.get("failures") or 0)
            errors += int(s.get("errors") or 0)
            skipped += int(s.get("skipped") or 0)
        except (TypeError, ValueError):
            pass
        for tc in s.iter("testcase"):
            ids.append("%s::%s" % (tc.get("classname") or "", tc.get("name") or ""))
    return True, {"tests": tests, "failures": failures, "errors": errors,
                  "skipped": skipped, "ids": ids}


def _expected_min_tests(suite_list):
    """Numero MINIMO de tests que la suite deberia ejecutar (funciones test_*)."""
    import re as _re
    total = 0
    for f in suite_list:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        total += len(_re.findall(r"(?m)^\s*def\s+test_\w+", text))
    return total


# Plugin de pytest del harness: escribe un MARCADOR DE FINALIZACION al
# terminar la sesion. `os._exit()` NO ejecuta los hooks `atexit`, asi que un
# candidato que mate al interprete durante el import deja el marcador ausente.
#
# LIMITACION HONESTA: el codigo del candidato se importa DENTRO del proceso de
# pytest, asi que puede leer `sys.modules` y el sistema de ficheros. Un
# candidato suficientemente adversarial PODRIA fabricar tambien el marcador.
# Este control sube la barra (ataja `os._exit`/`sys.exit` y los errores de
# sintaxis) pero NO sustituye a una frontera de sistema operativo. Cerrar del
# todo este ataque requiere el sandbox de OS (BLQ-1), no disponible aqui.
_GATE_PLUGIN = '''"""Plugin de harness: marca la finalizacion real de la sesion pytest."""
import atexit
import hashlib
import os


def _finish():
    report = os.environ.pop("FORGE_JUNIT_REPORT", None)
    marker = os.environ.pop("FORGE_GATE_MARKER", None)
    if not marker:
        return
    try:
        digest = ""
        if report and os.path.isfile(report):
            h = hashlib.sha256()
            with open(report, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            digest = h.hexdigest()
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(digest)
    except Exception:
        pass


atexit.register(_finish)
'''


def _looks_like_environment_break(out):
    """True si la salida indica un fallo del ENTORNO, no del candidato."""
    low = (out or "").lower()
    markers = ("no module named", "modulenotfounderror", "internalerror",
               "import error while importing conftest", "command not found",
               "is not recognized as an internal or external command",
               "error: unrecognized arguments", "no module named pytest")
    return any(m in low for m in markers)


def _kill_process_tree(proc):
    """Termina el proceso Y sus hijos. Sin esto, un timeout deja nietos vivos."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=30)
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (OSError, AttributeError):
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def _run_bounded(cmd, cwd, env, timeout_s, out_path, max_bytes=MAX_OUTPUT_BYTES,
                 hard_limit=16 * 1024 * 1024):
    """Ejecuta el comando con la salida ACOTADA en RAM y en disco.

    `stdout=PIPE` sin limite permite agotar la RAM del host con un test que
    imprime mucho; escribir a un fichero sin limite permite agotar el disco.
    Aqui se lee con contrapresion: al superar `hard_limit` se deja de leer, el
    pipe se llena, el hijo se bloquea y se mata. Al leer solo se guardan los
    primeros `max_bytes`.
    """
    import threading
    collected = []
    state = {"total": 0, "overflow": False}

    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                                            if os.name == "nt" else 0),
                            start_new_session=(os.name != "nt"))
    try:
        def _reader():
            while True:
                block = proc.stdout.read(65536)
                if not block:
                    break
                if state["total"] + len(block) > hard_limit:
                    state["overflow"] = True
                    break
                state["total"] += len(block)
                collected.append(block)
        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            raise
        finally:
            t.join(timeout=5)
            if state["overflow"]:
                # Inundacion de salida: se mata INMEDIATAMENTE al superar el
                # tope (no se espera al timeout) y el fallo se atribuye al
                # candidato, no al entorno.
                _kill_process_tree(proc)
                state["overflow_killed"] = True
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except OSError:
            pass
    data = b"".join(collected)
    with open(out_path, "wb") as fh:
        fh.write(data)
    truncated = state["overflow"] or len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    if truncated:
        text += "\n[TRUNCADO: la salida supero el limite de %d bytes]" % max_bytes
    return text, proc.returncode


def run_gate(candidate_dir, protected_suite, gate_id=None, timeout_s=DEFAULT_CMD_TIMEOUT,
             log_dir=None, expected_suite_sha=None):
    """Devuelve un GateResult dict. `protected_suite` vive FUERA del candidato.
    
    Si se proporciona expected_suite_sha, valida que la suite actual coincida
    con el hash congelado al inicializar el run (P0-03).
    """
    ts = now_ts()
    gate_id = gate_id or ("suite:" + os.path.basename(candidate_dir.rstrip("/\\")))
    candidate_dir = os.path.realpath(candidate_dir)
    # P0-05: calcular manifest hash del candidato antes de ejecutar
    try:
        candidate_manifest = candidate_manifest_sha(candidate_dir)
    except ForgeError as exc:
        return {
            "gate_id": gate_id,
            "candidate": os.path.basename(candidate_dir),
            "state": "BLOCKED",
            "command": "",
            "tool_version": "",
            "ts": ts,
            "exit_code": None,
            "stdout_ref": None,
            "stderr_ref": None,
            "evidence": [],
            "failure_class": "unsafe_candidate",
            "notes": str(exc),
            "suite_sha": None,
            "candidate_manifest_sha": None,
            "diff_sha": None,
            "security_mode": SECURITY_MODE,
            "user_site_exposed": None,
        }

    # El baseline congelado vive en `<run>/baseline` (un nivel por encima de
    # `candidates/`). Se resuelve de forma canonica, no por concatenacion fragile.
    baseline_dir = os.path.realpath(os.path.join(os.path.dirname(candidate_dir),
                                                  os.pardir, "baseline"))
    try:
        diff_bytes = (isolation.capture_diff(baseline_dir, candidate_dir)
                      if os.path.isdir(baseline_dir) else b"")
    except ForgeError as exc:
        return {
            "gate_id": gate_id,
            "candidate": os.path.basename(candidate_dir),
            "state": "BLOCKED",
            "command": "",
            "tool_version": "",
            "ts": ts,
            "exit_code": None,
            "stdout_ref": None,
            "stderr_ref": None,
            "evidence": [],
            "failure_class": "unsafe_candidate",
            "notes": str(exc),
            "suite_sha": None,
            "candidate_manifest_sha": candidate_manifest,
            "diff_sha": None,
            "security_mode": SECURITY_MODE,
            "user_site_exposed": None,
        }
    # El hash se calcula SIEMPRE, incluso para parche vacio.
    diff_hash = isolation.diff_sha(diff_bytes)

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
        "candidate_manifest_sha": candidate_manifest,
        "diff_sha": diff_hash,
        "security_mode": SECURITY_MODE,
        "user_site_exposed": None,
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

    # P0-03: validar suite hash ANTES de ejecutar contra el hash congelado del run
    suite_before = suite_sha(protected_suite)
    result["suite_sha"] = suite_before
    if expected_suite_sha is not None and suite_before != expected_suite_sha:
        result["state"] = "BLOCKED"
        result["failure_class"] = "suite_hash_mismatch"
        result["notes"] = ("suite hash no coincide con el congelado en init: "
                           "actual=%s esperado=%s" % (suite_before, expected_suite_sha))
        return result

    # Contaminacion del harness: el candidato trae su propia suite.
    # `_protected_names` recorre todo el arbol (conftest.py en un subdirectorio
    # tambien lo carga pytest), por lo que la comprobacion de nivel superior
    # que existia antes queda cubierta.
    bad = _protected_names(candidate_dir)
    if bad:
        result["state"] = "BLOCKED"
        result["failure_class"] = "harness_tampering"
        result["notes"] = "contaminacion: candidato incluye %s" % ", ".join(bad)
        return result

    scratch = tempfile.mkdtemp(prefix="forge-gate-")
    try:
        # Copia limpia del CANDIDATO usando la MISMA politica de exclusiones
        # que el manifiesto y el parche. Antes se usaba `os.listdir`, que
        # dejaba entrar `.pyc` (importables sin fuente) y caches: codigo que
        # se ejecutaba pero que no estaba en NINGUN hash ni en el parche
        # exportado.
        for rel, src_file in isolation.walk_files_checked(candidate_dir)[0]:
            dst = os.path.join(scratch, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src_file, dst)
        # Suite protegida: cada fichero bajo su nombre relativo al dirs raiz.
        suite_root = os.path.dirname(os.path.abspath(protected_suite))
        for f in suite_list:
            rel = os.path.relpath(f, suite_root)
            dst = os.path.join(scratch, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(f, dst)

        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"] + \
            _pytest_targets(suite_list, suite_root)
        report_dir = tempfile.mkdtemp(prefix="forge-gate-report-")
        report_path = os.path.join(report_dir, "report.xml")
        marker_path = os.path.join(report_dir, "completion.marker")
        plugin_dir = tempfile.mkdtemp(prefix="forge-gate-plugin-")
        plugin_path = os.path.join(plugin_dir, "forge_gate_plugin.py")
        with open(plugin_path, "w", encoding="utf-8") as fh:
            fh.write(_GATE_PLUGIN)
        cmd += ["--junitxml", report_path, "-p", "forge_gate_plugin"]
        result["command"] = " ".join(cmd)
        try:
            env, user_site_exposed = _minimal_env(scratch)
            env["FORGE_JUNIT_REPORT"] = report_path
            env["FORGE_GATE_MARKER"] = marker_path
            env["PYTHONPATH"] = os.pathsep.join(
                [plugin_dir] + env["PYTHONPATH"].split(os.pathsep))
            result["user_site_exposed"] = user_site_exposed
            if user_site_exposed:
                # Sin shim, TODO el user site-packages queda importable por el
                # codigo del candidato: no se permite que eso pase inadvertido.
                result["state"] = "BLOCKED"
                result["failure_class"] = "unsafe_candidate"
                result["notes"] = ("el user site-packages completo quedaria "
                                   "expuesto al codigo del candidato y no se pudo "
                                   "construir el shim aislado de pytest")
                result["evidence"].append("user_site_exposed=True")
                return result
            rc, ver = _pytest_version(env)
            result["tool_version"] = ver
            out_path = os.path.join(scratch, ".forge-gate-output.log")
            out, exit_code = _run_bounded(cmd, scratch, env, timeout_s, out_path)
            result["exit_code"] = exit_code
            # El veredicto NO se basa solo en el codigo de salida: se exige el
            # INFORME de la suite (Junit XML). Un candidato que mata al
            # interprete durante el import (`os._exit(0)`) deja el codigo 0 y
            # NO deja informe: sin informe no hay PASS.
            ok_xml, info = _parse_junit(report_path)
            marker_ok, marker_detail = _check_marker(marker_path, report_path)
            result["tests_executed"] = info.get("tests")
            result["tests_expected_min"] = _expected_min_tests(suite_list)
            result["suite_report_ok"] = ok_xml
            result["session_completed"] = marker_ok
            expected_min = max(1, result["tests_expected_min"])
            if not marker_ok:
                # pytest no llego a terminar la sesion (p.ej. `os._exit(0)` en
                # el import del candidato): no puede haber un PASS.
                result["state"] = "FAIL"
                result["failure_class"] = "gate_session_incomplete"
                result["notes"] = ("pytest no finalizo la sesion de forma normal "
                                   "(marcador ausente): %s" % marker_detail)
                result["evidence"].append("marcador de finalizacion ausente")
            elif not ok_xml:
                result["state"] = "BLOCKED" if _looks_like_environment_break(out) else "FAIL"
                result["failure_class"] = ("environment_broken"
                                           if result["state"] == "BLOCKED"
                                           else "gate_report_missing")
                result["notes"] = info.get("reason", "")
                result["evidence"].append("sin informe de suite: %s"
                                           % info.get("reason", ""))
            elif info.get("tests", 0) < expected_min:
                result["state"] = "FAIL"
                result["failure_class"] = "insufficient_tests_executed"
                result["notes"] = ("la suite ejecuto %d tests de los %d minimos "
                                   "esperados" % (info.get("tests", 0), expected_min))
            elif info.get("tests", 0) <= 0:
                result["state"] = "FAIL"
                result["failure_class"] = "no_tests_executed"
                result["notes"] = "la suite no ejecuto ningun test"
            elif info.get("failures", 0) or info.get("errors", 0):
                result["state"] = "FAIL"
                result["failure_class"] = "required_check_failed"
            elif exit_code != 0:
                # Informe limpio pero codigo distinto de 0: no es de fiar.
                result["state"] = "FAIL"
                result["failure_class"] = "required_check_failed"
                result["notes"] = "pytest devolvio %d pese al informe limpio" % exit_code
            else:
                result["state"] = "PASS"
            result["evidence"].append("tests=%s failures=%s errors=%s"
                                       % (info.get("tests"), info.get("failures"),
                                          info.get("errors")))
        except subprocess.TimeoutExpired:
            out = "timeout %ss" % timeout_s
            result["exit_code"] = None
            result["state"] = "BLOCKED"
            result["failure_class"] = "environment_broken"
        except OSError as exc:
            out = "no se pudo ejecutar pytest: %s" % exc
            result["exit_code"] = None
            result["state"] = "NOT_RUN"
            result["failure_class"] = "environment_broken"
        finally:
            shutil.rmtree(report_dir, ignore_errors=True)
            shutil.rmtree(plugin_dir, ignore_errors=True)

        # P0-03: validar integridad contra hash congelado del run, no solo antes/despues
        suite_after = suite_sha(protected_suite)
        if expected_suite_sha is not None and suite_after != expected_suite_sha:
            result["state"] = "BLOCKED"
            result["failure_class"] = "suite_hash_mismatch"
            result["notes"] = ("suite hash cambiado durante evaluacion: "
                               "actual=%s esperado=%s" % (suite_after, expected_suite_sha))
        elif suite_after != suite_before:
            # Fallback: detectar cambio durante evaluacion si no hay expected_suite_sha
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


def _pytest_version(env=None):
    """Version de pytest. Usa el entorno minimo si se le pasa."""
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                           text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=20,
                           env=env, errors="replace")
        return r.returncode, (r.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def run_all(run_dir, suite, log_dir=None, expected_suite_sha=None):
    """Ejecuta el gate de suite sobre todos los candidatos del run."""
    cands_root = os.path.join(run_dir, "candidates")
    results = {}
    if os.path.isdir(cands_root):
        for cand in sorted(os.listdir(cands_root)):
            cdir = os.path.join(cands_root, cand)
            if os.path.isdir(cdir):
                results[cand] = run_gate(cdir, suite, log_dir=log_dir,
                                         expected_suite_sha=expected_suite_sha)
    return results


def eligible(results):
    return sorted(c for c, g in results.items() if g.get("state") == "PASS")

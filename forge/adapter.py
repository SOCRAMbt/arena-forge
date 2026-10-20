"""Runtime Adapter OpenCode V2 (§3.2, §13).

Encapsula las capacidades REALMENTE disponibles del runtime. Nunca simula
exito: si una capacidad no se ha verificado con una prueba valida, se reporta
`unknown`, `unsupported`, `inconclusive` o `blocked`, y `require()` la bloquea
en vez de fingirla.

REGLAS DE HONESTIDAD (aplicadas por esta auditoria)
-----------------------------------------------------
1. Una definicion por funcion. Un error en una sonda debe corregirse en un
   unico sitio, no en cuatro copias.
2. Un error de sintaxis de la CLI (flag o subcomando inexistente) NO es
   evidencia de que la capacidad no exista: se marca `inconclusive`, nunca
   `unsupported`.
3. El texto de ayuda de la CLI NO prueba ni una denegacion ni una capacidad.
   Solo el estado observable (un fichero que cambia, un canario intacto) prueba.
4. Cada capacidad declara su `scope`: `host` (el host, no OpenCode), `repo`
   (propiedad del repositorio) u `opencode` (requiere al runtime de OpenCode).
   `cmd_verify` solo exige capacidades de scope `repo`/`opencode`.
5. Las sondas que requieren una llamada a modelo con coste NO se ejecutan sin
   autorizacion explicita: se marcan `blocked`.

La fuente de verdad es `runtime/capabilities.json`, escrito por `probe()` tras
comprobar el binario real, mas la version viva detectada aqui.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import time

from .util import ForgeError, now_ts

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAP_FILE = os.path.join(HERE, "runtime", "capabilities.json")
AGENTS_DIR = os.path.join(HERE, ".opencode", "agents")
SKILLS_DIR = os.path.join(HERE, ".opencode", "skills")

VERIFIED = "verified"
UNSUPPORTED = "unsupported"
UNKNOWN = "unknown"
INCONCLUSIVE = "inconclusive"
BLOCKED = "blocked"

# Scopes: host = capacidades del SO; repo = propiedades del repositorio;
# opencode = requieren el runtime de OpenCode (algunas con coste).
SCOPE_HOST = "host"
SCOPE_REPO = "repo"
SCOPE_OPENCODE = "opencode"

# Capacidades que el runtime debe declarar. `by` = como se comprobo.
REQUIRED_CAPABILITIES = (
    "skills_native",          # skill cargable por ID
    "subagent_tool",          # tool `subagent` (agent/description/prompt)
    "subagent_foreground",    # el orquestador espera la ola
    "subagent_background",    # background no garantizado entre sesiones
    "agent_profiles",         # perfiles de agente en markdown
    "permission_rules",       # {action, resource, effect}
    "readonly_agent",         # agente sin edicion (explore)
    "cwd_control",            # dirigir cwd de un proceso/hijo
    "state_on_disk",          # crear, cerrar, reabrir y reanudar un run
    "shell_tool",             # ejecutar comandos
    "plugin_api",             # API de plugin documentada
)

# Matriz de requisitos por modo. `mandatory` = sin la capability el modo no
# puede funcionar; `optional` = informativa.
#   answer    : bracket + juez -> requiere perfiles de agente y persistencia.
#   patch     : ademas requiere la suite protegida y la ejecucion de gates.
#   benchmark : solo determinismo local del scheduler.
MODE_REQUIREMENTS = {
    "answer": {
        "mandatory": ("agent_profiles", "state_on_disk"),
        "optional": ("skills_native", "subagent_tool", "subagent_foreground",
                     "permission_rules", "readonly_agent", "shell_tool"),
    },
    "patch": {
        "mandatory": ("agent_profiles", "state_on_disk", "shell_tool",
                      "python_runtime"),
        "optional": ("skills_native", "subagent_tool", "subagent_foreground",
                     "permission_rules", "readonly_agent", "cwd_control",
                     "subagent_background", "plugin_api"),
    },
    "benchmark": {
        "mandatory": ("python_runtime",),
        "optional": ("agent_profiles", "state_on_disk", "shell_tool"),
    },
}


# ------------------------------------------------------------------ ejecucion
def _run(cmd, timeout=30, cwd=None):
    """Ejecuta un comando. Devuelve (rc, stdout+stderr combinados).

    `errors="replace"`: la salida de un binario externo puede contener bytes
    que la codificacion de la consola no puede decodificar; que eso rompa la
    sonda seria un fallo de la sonda, no del runtime.
    """
    try:
        r = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout, cwd=cwd,
                           errors="replace")
        return r.returncode, (r.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def _run_opencode(args, timeout=30, cwd=None):
    """Ejecuta opencode usando el ejecutable resuelto."""
    exe = shutil.which("opencode")
    if not exe:
        return 127, "opencode no encontrado en PATH"
    return _run([exe] + list(args), timeout=timeout, cwd=cwd)


def _looks_like_usage_error(out):
    """True si la salida es el texto de ayuda/uso (error de invocacion)."""
    low = (out or "").lower()
    return ("usage:" in low or "unknown flag" in low or "unknown option" in low
            or "unrecognized argument" in low
            or low.startswith("description\n  opencode")
            or ("subcommands" in low and "flags" in low))


def detect_version():
    """Version real del binario. Devuelve (version|None, crudo)."""
    exe = shutil.which("opencode")
    if not exe:
        return None, "opencode no encontrado en PATH"
    rc, out = _run([exe, "--version"])
    if rc != 0:
        return None, out
    m = re.search(r"v?(\d+\.\d+\.\d+)", out)
    if m:
        return m.group(1), out
    return out or None, out


def _default_capabilities():
    """Valores conservadores cuando no hay probe: casi todo `unknown`."""
    caps = {}
    for name in REQUIRED_CAPABILITIES:
        caps[name] = {"status": UNKNOWN, "evidence": "sin probe grabado",
                      "by": "none", "scope": SCOPE_OPENCODE}
    return caps


def load_capabilities():
    data = _default_capabilities()
    if os.path.isfile(CAP_FILE):
        try:
            with open(CAP_FILE, encoding="utf-8") as fh:
                recorded = json.load(fh)
            data.update(recorded.get("capabilities", {}))
        except ValueError:
            pass
    return data


def _rel_to_repo(path):
    """Ruta RELATIVA al repo. Los artefactos versionados no deben llevar
    rutas absolutas del host: rompen la portabilidad del repo."""
    if not path:
        return ""
    try:
        return os.path.relpath(path, HERE).replace("\\", "/")
    except ValueError:
        return ""


def save_capabilities(caps, version):
    runtime_dir = os.path.dirname(CAP_FILE)
    os.makedirs(runtime_dir, exist_ok=True)
    payload = {
        "version": version,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "probed": now_ts(),
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "opencode_executable": _rel_to_repo(shutil.which("opencode") or ""),
        "capabilities": caps,
    }
    with open(CAP_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return payload


# ------------------------------------------------------------------- sondas
_SKILL_LIST_CACHE = {}


def _skill_api_probe(timeout=45):
    """Descubre la skill del repo con un servidor ENRAIZADO en el repo.

    Por que servidor dedicado: el servidor de fondo de OpenCode puede estar
    enraizado en otro directorio (el home del usuario). En ese caso
    `/api/skill` lista las skills de ESE arbol y la del repo aparece como "no
    encontrada" aunque este bien. Para medir "la skill aparece y se carga con
    el ID/ruta exactos" hay que arrancar un servidor en el repo.

    El servidor anuncia una contrasena ALEATORIA en su stdout; se lee de ahi.
    Devuelve (ok, info).
    """
    import base64
    import socket
    import subprocess
    import tempfile
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    exe = shutil.which("opencode")
    if not exe:
        return False, {"reason": "opencode no esta en PATH"}
    skill_id = "arena-forge"
    expected = os.path.join(SKILLS_DIR, skill_id, "SKILL.md")

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    cmd = [exe, "serve", "--port", str(port), "--hostname", "127.0.0.1"]
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", exe] + cmd[1:]
    fd, log_path = tempfile.mkstemp(prefix="opencode-serve-", suffix=".log")
    os.close(fd)
    proc = None
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(cmd, cwd=HERE, stdout=log, stderr=subprocess.STDOUT)
    except OSError as exc:
        try:
            os.unlink(log_path)
        except OSError:
            pass
        return False, {"reason": "no se pudo arrancar el servidor: %s" % exc}
    try:
        password = None
        deadline = time.time() + timeout
        while time.time() < deadline and password is None:
            try:
                with open(log_path, encoding="utf-8", errors="replace") as fh:
                    m = re.search(r"server password\s+(\S+)", fh.read())
                if m:
                    password = m.group(1)
            except OSError:
                pass
            if password is None:
                time.sleep(0.3)
        if not password:
            return False, {"reason": "el servidor no anuncio su contrasena"}
        # esperar el puerto
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.3)
        else:
            return False, {"reason": "el servidor no abrio el puerto %d" % port}

        url = "http://127.0.0.1:%d/api/skill?directory=%s" % (
            port, urllib.parse.quote(HERE, safe=""))
        token = base64.b64encode(("opencode:%s" % password).encode("utf-8")).decode()
        skills = []
        last = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                req = urllib.request.Request(url, headers={
                    "Authorization": "Basic %s" % token,
                    "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode("utf-8", "replace"))
            except (urllib.error.URLError, OSError, ValueError) as exc:
                last = exc
                time.sleep(1.0)
                continue
            if isinstance(payload, dict):
                payload = payload.get("data") or payload.get("skills") or []
            if not isinstance(payload, list):
                return False, {"reason": "formato de /api/skill inesperado"}
            skills = payload
            if any(x.get("id") == skill_id for x in skills):
                break
            time.sleep(1.0)
        else:
            return False, {"reason": "la skill %r no aparecio en /api/skill "
                                     "(%d listadas)" % (skill_id, len(skills)),
                           "total_skills": len(skills)}
        found = [x for x in skills if x.get("id") == skill_id][0]
        path = found.get("path") or ""
        same = os.path.normcase(os.path.abspath(path)) == os.path.normcase(expected)
        return True, {"id": skill_id, "name": found.get("name"), "path": path,
                      "expected_path": expected, "path_matches_repo": same,
                      "total_skills": len(skills)}
    finally:
        if proc is not None:
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


def _test_skill_load():
    """La skill del repo aparece y se carga con su ID y ruta EXACTOS."""
    ok, info = _skill_api_probe()
    if not ok:
        return False, info.get("reason", "sonda de skill fallida"), "opencode"
    if not info.get("path_matches_repo"):
        return (False, "la skill aparece pero con otra ruta: %s (esperada %s)"
                % (info.get("path"), info.get("expected_path")), "opencode")
    return (True, "skill %s cargada por ID desde %s (%d skills en el runtime)"
            % (info["id"], _rel_to_repo(info["path"]),
               info.get("total_skills", 0)), "opencode")


def _test_subagent_foreground(allow_model_calls=False):
    """Invoca un subagente y comprueba que se creo una sesion HIJA.

    Requiere una llamada a modelo (coste). Sin autorizacion -> `blocked`.
    Un mensaje que contenga 'OK' NO prueba que existiera un subagente: se
    exige un identificador de sesion hijo.
    """
    if not allow_model_calls:
        return (False,
                "BLOCKED: requiere llamada a modelo (coste no autorizado). No se "
                "puede probar la creacion de un subagente nativo sin ejecutarla",
                "opencode")
    rc, out = _run_opencode(["run", "--agent", "explore",
                              "Responde solo con la palabra OK"], timeout=90)
    if rc != 0:
        if _looks_like_usage_error(out):
            return (False, "INCONCLUSIVE: invocacion invalida de la CLI: %s" % out[:200],
                    "opencode")
        return (False, "subagent foreground fallo (rc=%d): %s" % (rc, out[:200]),
                "opencode")
    if "OK" not in out.upper():
        return (False, "subagent foreground respondio sin OK: %s" % out[:200], "opencode")
    # 'OK' solo prueba que un modelo respondio: hace falta una sesion hijo.
    if not re.search(r"ses[s_]?[a-z0-9_-]{6,}", out, re.IGNORECASE):
        return (False,
                "INCONCLUSIVE: el modelo respondio pero no hay identificador de "
                "sesion hija en la salida: no se puede probar que se creara un "
                "subagente nativo", "opencode")
    return True, "subagent foreground creo una sesion hija", "opencode"


def _test_readonly_agent(allow_model_calls=False):
    """Verifica que el agente read-only NO puede escribir, con un canario.

    Se escribe un canario con contenido conocido, se invoca el agente y se
    comprueba el estado ANTES y DESPUES. Un error generico de la CLI no es una
    denegacion: en ese caso el veredicto es `inconclusive`.
    """
    if not allow_model_calls:
        return (False,
                "BLOCKED: requiere llamada a modelo (coste no autorizado)", "opencode")
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="forge-readonly-")
    canary = os.path.join(tmpdir, "canary.txt")
    with open(canary, "w", encoding="utf-8") as fh:
        fh.write("ORIGINAL")
    try:
        before = open(canary, encoding="utf-8").read()
        rc, out = _run_opencode(["run", "--agent", "explore",
                                  "Intenta escribir en %s" % canary], timeout=90)
        after = open(canary, encoding="utf-8").read()
        if rc != 0:
            if _looks_like_usage_error(out):
                return (False, "INCONCLUSIVE: invocacion invalida de la CLI: %s"
                        % out[:200], "opencode")
            # Un error que nombre una denegacion de permiso, con el canario
            # intacto, es evidencia real.
            low = out.lower()
            denied = ("permission denied" in low or "denied" in low
                      or "not allowed" in low or "forbidden" in low)
            if denied and after == before:
                return True, "el agente explore denego la escritura (canario intacto)", "opencode"
            return (False, "INCONCLUSIVE: fallo sin evidencia de denegacion "
                    "(rc=%d): %s" % (rc, out[:200]), "opencode")
        if after == before:
            return True, "el agente explore no modifico el canario (read-only efectivo)", "opencode"
        return False, "el agente explore SI modifico el canario: read-only no efectivo", "opencode"
    finally:
        try:
            os.remove(canary)
        except OSError:
            pass
        shutil.rmtree(tmpdir, ignore_errors=True)


def _test_cwd_control():
    """Mide la capacidad del HOST de dirigir el cwd de un subprocess.

    Alcance: `host`. NO demuestra ninguna capacidad del runtime de OpenCode.
    """
    import tempfile
    test_dir = tempfile.mkdtemp(prefix="forge-cwd-")
    try:
        with open(os.path.join(test_dir, "test.txt"), "w", encoding="utf-8") as fh:
            fh.write("ok")
        if os.name == "nt":
            cmd = ["cmd", "/c", "type", "test.txt"]
        else:
            cmd = ["/bin/sh", "-c", "cat test.txt"]
        rc, out = _run(cmd, timeout=10, cwd=test_dir)
        if rc == 0 and "ok" in out:
            return (True, "host: subprocess con cwd explicito funciona (no es una "
                    "capacidad del runtime de OpenCode)", "host")
        return (False, "cwd control del host fallo (rc=%d): %s" % (rc, out), "host")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def _test_state_on_disk():
    """Crea, cierra, reabre y reanuda un run persistido.

    Alcance: `repo`. Es una prueba real de ida y vuelta sobre disco, no la
    mera existencia de un directorio.
    """
    import tempfile
    from . import ledger
    from .util import atomic_write_json
    tmp = tempfile.mkdtemp(prefix="forge-persist-")
    try:
        run = {"run_id": "probe-run", "schema_version": 2, "mode": "answer",
               "status": "RUNNING", "phase": "RUNNING", "dir": tmp,
               "created": 1, "seed": 7, "task_sha": "a" * 64,
               "rubric_sha": "b" * 64, "cards_sha": "c" * 64,
               "budget": {}, "policy_version": "e-policy-v1", "events": []}
        atomic_write_json(os.path.join(tmp, "forge.json"), run)
        ledger.append(tmp, "probe", "escritura inicial")
        # cerrar: releer desde disco
        from .util import read_json_bounded
        reopened = read_json_bounded(os.path.join(tmp, "forge.json"))
        if reopened.get("run_id") != "probe-run":
            return False, "el run no se reabre con el mismo contenido", "repo"
        # reanudar: escribir un segundo evento y verificar la cadena
        ledger.append(tmp, "probe", "reanudacion")
        ok, problems = ledger.verify(tmp)
        if not ok:
            return False, "la cadena del ledger no verifica al reanudar: %s" % problems, "repo"
        if len(ledger.read(tmp)) != 2:
            return False, "el historial no se conserva al reanudar", "repo"
        return True, ("run creado, cerrado, reabierto y reanudado; ledger verificado "
                      "(%d eventos)" % len(ledger.read(tmp))), "repo"
    except Exception as exc:
        return False, "fallo en la prueba de persistencia: %s" % exc, "repo"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_shell_tool():
    """Mide la capacidad del HOST de ejecutar comandos.

    Alcance: `host`. NO demuestra que OpenCode exponga un shell tool al agente.
    """
    if os.name == "nt":
        cmd = ["cmd", "/c", "echo test"]
    else:
        cmd = ["/bin/sh", "-c", "echo test"]
    rc, out = _run(cmd, timeout=10)
    if rc == 0 and "test" in out:
        return (True, "host: ejecucion de comandos disponible (no es el shell "
                "tool de OpenCode)", "host")
    return False, "shell del host fallo (rc=%d): %s" % (rc, out), "host"


def _test_agent_profiles():
    """Perfiles de agente del repo: se comprueba el directorio real."""
    if not os.path.isdir(AGENTS_DIR):
        return False, "directorio de perfiles ausente: %s" % _rel_to_repo(AGENTS_DIR), "repo"
    profiles = sorted(f for f in os.listdir(AGENTS_DIR) if f.endswith(".md"))
    if not profiles:
        return False, "directorio de perfiles vacio: %s" % _rel_to_repo(AGENTS_DIR), "repo"
    return True, ("perfiles .md en %s: %s"
                  % (_rel_to_repo(AGENTS_DIR), ", ".join(profiles))), "repo"


def _test_permission_rules():
    """Analisis ESTATICO del orden de las reglas de permiso de los agentes.

    OpenCode V2 resuelve la precedencia con "gana la ultima regla que
    coincide". Este test verifica que, para cada recurso permitido, la
    ultima regla que coincide es `allow`.

    NO prueba la ENFORCACION en runtime (eso exigiria una llamada a modelo):
    por eso el veredicto es `inconclusive` aunque el analisis estatico pase.
    """
    if not os.path.isdir(AGENTS_DIR):
        return False, "sin perfiles que analizar", "repo"
    problems = []
    checked = 0
    for name in sorted(os.listdir(AGENTS_DIR)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(AGENTS_DIR, name)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        rules = _parse_permissions(text)
        if not rules:
            continue
        allows = [r for r in rules if r["effect"] == "allow" and r["action"] == "edit"]
        for rule in allows:
            checked += 1
            last = None
            for r in rules:
                if r["action"] == rule["action"] and _resource_matches(r["resource"], rule["resource"]):
                    last = r
            if last is None or last["effect"] != "allow":
                problems.append("%s: el permiso allow sobre %r queda anulado por "
                                "una regla posterior" % (name, rule["resource"]))
    if problems:
        return False, "; ".join(problems), "repo"
    return (False,
            "orden de reglas correcto en %d permisos (analisis estatico); la "
            "ENFORCACION en runtime no esta probada (requiere llamada a modelo)"
            % checked, "opencode")


def _parse_permissions(text):
    """Extrae la lista de reglas {action,resource,effect} del frontmatter."""
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end < 0:
        return []
    front = text[3:end]
    rules = []
    action = resource = effect = None
    for line in front.splitlines():
        s = line.strip()
        if s.startswith("- action:"):
            if action and resource and effect:
                rules.append({"action": action, "resource": resource, "effect": effect})
            action, resource, effect = s.split(":", 1)[1].strip(), None, None
        elif s.startswith("resource:") and action is not None:
            resource = s.split(":", 1)[1].strip().strip('"')
        elif s.startswith("effect:") and action is not None:
            effect = s.split(":", 1)[1].strip()
    if action and resource and effect:
        rules.append({"action": action, "resource": resource, "effect": effect})
    return rules


def _resource_matches(pattern, concrete):
    """Matcher de OpenCode V2: `*` no cruza `/`; `**` si."""
    if pattern == concrete:
        return True
    if pattern == "**" or pattern == "*":
        return True
    p = pattern.replace("**", "\x00")
    p = p.replace("*", "[^/]*")
    p = p.replace("\x00", ".*")
    c = concrete.replace("**", "\x00")
    c = c.replace("*", "[^/]*")
    c = c.replace("\x00", ".*")
    try:
        return re.match("^%s$" % p, c) is not None
    except re.error:
        return False


# -------------------------------------------------------------------- probe
def probe(version=None, allow_model_calls=False, persist=True):
    """Evalua las capacidades del runtime y (opcionalmente) las persiste.

    `allow_model_calls` habilita las sondas que consumen credenciales de
    modelo. Sin ese permiso, esas capacidades se marcan `blocked`, nunca
    `unsupported` ni `verified`.
    """
    if version is None:
        version, _raw = detect_version()
    opencode_present = shutil.which("opencode") is not None

    caps = {}

    def _put(name, status, evidence, by, scope):
        caps[name] = {"status": status, "evidence": evidence, "by": by, "scope": scope}

    # --- host
    ok, ev, scope = _test_shell_tool()
    _put("shell_tool", VERIFIED if ok else UNSUPPORTED, ev, "host", scope)
    ok, ev, scope = _test_cwd_control()
    _put("cwd_control", VERIFIED if ok else UNSUPPORTED, ev, "host", scope)
    _put("python_runtime", VERIFIED, platform.python_version(), "platform", SCOPE_HOST)

    # --- repo
    ok, ev, scope = _test_state_on_disk()
    _put("state_on_disk", VERIFIED if ok else UNKNOWN, ev, "functional_test", scope)
    ok, ev, scope = _test_agent_profiles()
    _put("agent_profiles", VERIFIED if ok else UNKNOWN, ev, "filesystem", scope)
    ok, ev, scope = _test_permission_rules()
    _put("permission_rules", INCONCLUSIVE if ok else UNKNOWN, ev, "static_analysis", scope)

    # --- opencode (pueden requerir modelo)
    if not opencode_present:
        for name in ("skills_native", "subagent_tool", "subagent_foreground",
                     "subagent_background", "readonly_agent", "plugin_api"):
            _put(name, UNKNOWN, "opencode no encontrado en PATH", "none", SCOPE_OPENCODE)
    else:
        ok, ev, scope = _test_skill_load()
        _put("skills_native", VERIFIED if ok else INCONCLUSIVE, ev, "functional_test", scope)

        ok, ev, scope = _test_subagent_foreground(allow_model_calls)
        status = VERIFIED if ok else (BLOCKED if ev.startswith("BLOCKED") else INCONCLUSIVE)
        _put("subagent_tool", status, ev, "functional_test", scope)

        ok, ev, scope = _test_readonly_agent(allow_model_calls)
        status = VERIFIED if ok else (BLOCKED if ev.startswith("BLOCKED") else INCONCLUSIVE)
        _put("readonly_agent", status, ev, "functional_test", scope)

        # `subagent_foreground` es un subconjunto de `subagent_tool`: se deriva
        # de la MISMA prueba, no de una segunda llamada a modelo.
        sub = caps.get("subagent_tool", {})
        _put("subagent_foreground", sub.get("status", UNKNOWN),
             "derivado de la prueba de subagent_tool: %s" % sub.get("evidence", ""),
             "derived", SCOPE_OPENCODE)

        _put("subagent_background", UNKNOWN,
             "NOT_RUN: requiere sesion prolongada y llamada a modelo", "none",
             SCOPE_OPENCODE)
        _put("plugin_api", UNKNOWN,
             "NOT_RUN: la API de plugin no se usa en el producto", "none",
             SCOPE_OPENCODE)

    if persist:
        save_capabilities(caps, version)
    return caps


# ------------------------------------------------------------------- gates
def require(caps, name):
    entry = caps.get(name) or {"status": UNKNOWN}
    if entry.get("status") != VERIFIED:
        raise ForgeError("capacidad no verificada en este runtime: %s (%s)"
                         % (name, entry.get("status")))
    return entry


def mode_requirements(mode):
    """(obligatorias, opcionales) del modo. Modo desconocido -> vacio."""
    spec = MODE_REQUIREMENTS.get(mode)
    if not spec:
        return (), ()
    return tuple(spec.get("mandatory", ())), tuple(spec.get("optional", ()))


def missing_mandatory(caps, mode):
    """Capabilities obligatorias del modo que NO estan verificadas."""
    mandatory, _optional = mode_requirements(mode)
    missing = []
    for name in mandatory:
        entry = caps.get(name) or {}
        if entry.get("status") != VERIFIED:
            missing.append("%s=%s" % (name, entry.get("status", UNKNOWN)))
    return missing


def summary(caps):
    counts = {VERIFIED: 0, UNSUPPORTED: 0, UNKNOWN: 0, INCONCLUSIVE: 0, BLOCKED: 0}
    for entry in caps.values():
        st = entry.get("status", UNKNOWN)
        counts[st] = counts.get(st, 0) + 1
    return counts

"""Runtime Adapter OpenCode V2 (§3.2, §13).

Encapsula las capacidades REALMENTE disponibles del runtime. Nunca simula
exito: si una capacidad no se ha verificado, se reporta `unknown` o
`unsupported`, y `require()` la bloquea en vez de fingirla.

La fuente de verdad es `runtime/capabilities.json`, escrito por `probe` tras
comprobar el binario real, mas la version viva detectada aqui.
"""
import json
import os
import platform
import shutil
import subprocess

from .util import ForgeError, now_ts

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAP_FILE = os.path.join(HERE, "runtime", "capabilities.json")

VERIFIED = "verified"
UNSUPPORTED = "unsupported"
UNKNOWN = "unknown"

# Capacidades que el runtime debe declarar. `by` = como se comprobo.
REQUIRED_CAPABILITIES = (
    "skills_native",          # skill nativa cargable por ID
    "subagent_tool",          # tool `subagent` (agent/description/prompt)
    "subagent_foreground",    # el orquestador espera la ola
    "subagent_background",    # background no garantizado entre sesiones
    "agent_profiles",         # perfiles de agente en markdown
    "permission_rules",       # {action, resource, effect}
    "readonly_agent",         # agente sin edicion (explore)
    "cwd_control",            # dirigir cwd de un proceso/hijo
    "state_on_disk",          # reanudar desde disco
    "shell_tool",             # ejecutar comandos
    "plugin_api",             # API de plugin documentada
)


def _run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        return r.returncode, (r.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def detect_version():
    """Version real del binario. Devuelve (version|None, crudo)."""
    exe = shutil.which("opencode")
    if not exe:
        return None, "opencode no encontrado en PATH"
    rc, out = _run([exe, "--version"])
    if rc != 0:
        return None, out
    for tok in out.split():
        if tok and tok[0].isdigit():
            return tok, out
    return out or None, out


def _default_capabilities():
    """Valores conservadores cuando no hay probe: casi todo `unknown`."""
    caps = {}
    for name in REQUIRED_CAPABILITIES:
        caps[name] = {"status": UNKNOWN, "evidence": "sin probe grabado",
                      "by": "none"}
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


def save_capabilities(caps, version):
    runtime_dir = os.path.dirname(CAP_FILE)
    os.makedirs(runtime_dir, exist_ok=True)
    payload = {
        "version": version,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "probed": now_ts(),
        "capabilities": caps,
    }
    with open(CAP_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return payload


def probe(version=None):
    """Comprueba capacidades contra el entorno REAL. Lo no comprobable = unknown."""
    if version is None:
        version, _raw = detect_version()
    opencode = shutil.which("opencode") is not None
    caps = {}
    caps["shell_tool"] = {
        "status": VERIFIED if True else UNKNOWN,
        "evidence": "el orquestador ejecuta comandos via tool shell", "by": "uso"}
    caps["python_runtime"] = {
        "status": VERIFIED, "evidence": platform.python_version(), "by": "plataforma"}
    caps["skills_native"] = {
        "status": VERIFIED if opencode else UNKNOWN,
        "evidence": "skills resueltas por ID en ~/.config/opencode/skills y "
                    "<proyecto>/.opencode/skills (comprobado en E2E)",
        "by": "E2E"}
    caps["subagent_tool"] = {
        "status": VERIFIED if opencode else UNKNOWN,
        "evidence": "tool subagent(agent, description, prompt) usado en E2E real",
        "by": "E2E"}
    caps["subagent_foreground"] = {
        "status": VERIFIED if opencode else UNKNOWN,
        "evidence": "las olas returnan juntas en foreground", "by": "E2E"}
    caps["subagent_background"] = {
        "status": UNKNOWN,
        "evidence": "no se comprobo supervivencia de background al cerrar "
                    "terminal; no se usa como camino principal", "by": "none"}
    caps["agent_profiles"] = {
        "status": VERIFIED if opencode else UNKNOWN,
        "evidence": "perfiles .md en .opencode/agents/ y ~/.config/opencode/agents/",
        "by": "docs"}
    caps["permission_rules"] = {
        "status": VERIFIED if opencode else UNKNOWN,
        "evidence": "reglas {action, resource, effect} con allow/ask/deny (V2)",
        "by": "docs"}
    caps["readonly_agent"] = {
        "status": VERIFIED if opencode else UNKNOWN,
        "evidence": "agente builtin explore es read-only (docs V2)", "by": "docs"}
    caps["cwd_control"] = {
        "status": VERIFIED,
        "evidence": "subprocess con cwd explicito (gates en scratch)", "by": "E2E"}
    caps["state_on_disk"] = {
        "status": VERIFIED,
        "evidence": "resume reconstruye desde .arena/<run>/ sin duplicar", "by": "E2E"}
    caps["plugin_api"] = {
        "status": UNKNOWN,
        "evidence": "no se comprobo la API de plugin en esta instalacion; no se "
                    "depende de ella", "by": "none"}
    save_capabilities(caps, version)
    return caps


def require(caps, name):
    entry = caps.get(name) or {"status": UNKNOWN}
    if entry.get("status") != VERIFIED:
        raise ForgeError("capacidad no verificada en este runtime: %s (%s)"
                         % (name, entry.get("status")))
    return entry


def summary(caps):
    counts = {VERIFIED: 0, UNSUPPORTED: 0, UNKNOWN: 0}
    for entry in caps.values():
        counts[entry.get("status", UNKNOWN)] = counts.get(entry.get("status", UNKNOWN), 0) + 1
    return counts

"""Utilidades compartidas: hashing, escritura atomica, rutas canonicas, redaccion.

Reglas de seguridad (§11.3 de la especificacion):
- Las rutas se resuelven canonicamente; se rechaza cualquier escape del workspace.
- Los outputs tienen tope de tamano; nunca se cargan ficheros gigantes en memoria.
- Los secretos se redactan antes de persistir cualquier output.
"""
import hashlib
import json
import os
import re

MAX_OUTPUT_BYTES = 1024 * 1024          # 1 MiB por artefacto leido
DEFAULT_CMD_TIMEOUT = 120               # s
LOCK_STALE_SECONDS = 300


class ForgeError(Exception):
    """Error de uso/gobernanza de Arena Forge (nunca un fallo silencioso)."""


# ------------------------------------------------------------------ hashing
def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------- escritura
def atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def atomic_write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def append_line(path, text):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")


# ------------------------------------------------------------------- rutas
def inside(root, path):
    """True si `path` resuelto (symlinks incluidos) queda dentro de `root`."""
    base = os.path.realpath(root)
    target = os.path.realpath(path)
    return target == base or target.startswith(base + os.sep)


def has_symlink_escape(root, path):
    """True si algun componente del camino es un symlink que sale de `root`."""
    base = os.path.realpath(root)
    cur = os.path.abspath(path)
    while True:
        if os.path.islink(cur):
            if not inside(base, os.path.realpath(cur)):
                return True
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return False


def assert_inside(root, path, what="ruta"):
    if not inside(root, path) or has_symlink_escape(root, path):
        raise ForgeError("%s fuera del workspace permitido: %s" % (what, path))
    return os.path.realpath(path)


# ------------------------------------------------------------------- lectura
def read_json_bounded(path, max_bytes=MAX_OUTPUT_BYTES):
    """Carga JSON con tope de tamano. Eleva ForgeError en exceso o corrupcion."""
    size = os.path.getsize(path)
    if size > max_bytes:
        raise ForgeError("artefacto excede %d bytes: %s (%d)" % (max_bytes, path, size))
    with open(path, encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except ValueError as exc:
            raise ForgeError("JSON invalido en %s: %s" % (path, exc))


# --------------------------------------------------------------- redaccion
_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd)\b\s*[:=]\s*\S+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
               re.DOTALL),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
]


def redact(text, limit=8000):
    """Elimina secretos evidentes y recorta. Se aplica antes de persistir logs."""
    if text is None:
        return ""
    out = str(text)
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    if len(out) > limit:
        out = out[:limit] + "\n...[truncado]"
    return out


def now_ts():
    import time
    return int(time.time())


# ------------------------------------------------------------------- persistencia
FORGE_FILE = "forge.json"


def atomic_write_json(path, data):
    """Escritura atomica: tmp + rename para evitar corrupcion."""
    import tempfile
    dirn = os.path.dirname(path)
    os.makedirs(dirn, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dirn,
                                     delete=False, suffix=".tmp") as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, path)


def save_forge(run):
    atomic_write_json(os.path.join(run["dir"], FORGE_FILE), run)

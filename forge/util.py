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


def sha256_normalized(path):
    """SHA-256 del contenido **normalizado a LF**.

    Es el hash que se usa para los artefactos **versionados**: git normaliza
    los ficheros de texto a LF al commitear, asi que el hash del working tree
    (CRLF en Windows) no coincidiria con el de un checkout limpio. Normalizar
    hace que el manifiesto de evidencia sea valido en cualquier maquina.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


# --------------------------------------------------------------- escritura
def atomic_write_text(path, text):
    """Escritura atomica de texto.

    `newline=""` evita la traduccion de \\n a \\r\\n en Windows: los
    artefactos deben ser **byte-identicos en cualquier plataforma**, porque
    su SHA-256 es la evidencia que se versiona y se compara entre maquinas.
    """
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def append_line(path, text):
    """Anade una linea. `newline=""` mantiene los bytes estables (ver arriba)."""
    with open(path, "a", encoding="utf-8", newline="") as fh:
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
    re.compile(r"(?i)(api[_-]?key|access[_-]?key|secret[_-]?key|secret|token|password|passwd|pwd|credential)s?\s*[:=]\s*\S+"),
    re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*\S+"),
    re.compile(r"(?i)aws_session_token\s*[:=]\s*\S+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9\-_]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@/]+@\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
               re.DOTALL),
    re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----.*?-----END OPENSSH PRIVATE KEY-----",
               re.DOTALL),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    # Claves de proveedores LLM y cloud (el caso realista en un runtime de
    # agentes: `sk-ant-...`, `sk-proj-...`, `AIza...`).
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bsk_(live|test)_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\bya29\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\bAccountKey\s*=\s*[A-Za-z0-9+/=]{20,}"),
    re.compile(r"(?i)\bAuthorization\s*:\s*Basic\s+[A-Za-z0-9+/=]{8,}"),
    re.compile(r"(?i)https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{20,}"),
    re.compile(r"(?i)https://discord(?:app)?\.com/api/webhooks/[A-Za-z0-9/_-]{20,}"),
    re.compile(r"-----BEGIN (?:PGP|EC|DSA|RSA|OPENSSH)? ?PRIVATE KEY(?: BLOCK)?-----.*?"
               r"-----END (?:PGP|EC|DSA|RSA|OPENSSH)? ?PRIVATE KEY(?: BLOCK)?-----",
               re.DOTALL),
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


# ------------------------------------------------------------------- locks
class FileLock:
    """Lock de fichero a nivel de SISTEMA OPERATIVO.

    `arena_forge.acquire_lock` es un fichero JSON con pid/hora: dos procesos
    pueden leerlo y ambos creerse propietarios. Este lock usa `msvcrt.locking`
    (Windows) o `fcntl.flock` (POSIX), que el kernel garantiza.

    Se usa para las operaciones que deben ser atomicas: reserva de presupuesto,
    escritura del ledger y mutaciones de jobs.

    REENTRANTE dentro del mismo proceso: `msvcrt.locking` bloquea por HANDLE,
    asi que volver a tomar el mismo fichero desde el mismo proceso se
    quedaria colgado. Se lleva una cuenta de profundidad por ruta.
    """

    _held = {}

    def __init__(self, path, timeout=30.0, poll=0.02):
        self.path = path
        self.timeout = timeout
        self.poll = poll
        self._fh = None
        self._key = os.path.abspath(path)

    def acquire(self):
        import threading
        import time
        depth = FileLock._held.get(self._key, 0)
        if depth:
            # Reentrada: el mismo proceso ya tiene el lock.
            FileLock._held[self._key] = depth + 1
            return True
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._fh = open(self.path, "a+b")
        deadline = time.time() + self.timeout
        while True:
            try:
                _lock_file(self._fh)
                break
            except OSError:
                if time.time() >= deadline:
                    self._fh.close()
                    self._fh = None
                    raise ForgeError("no se pudo obtener el lock %s en %.0fs"
                                     % (self.path, self.timeout))
                time.sleep(self.poll)
        FileLock._held[self._key] = 1
        return True

    def release(self):
        if self._fh is None:
            return
        depth = FileLock._held.get(self._key, 0)
        if depth > 1:
            FileLock._held[self._key] = depth - 1
            return
        FileLock._held.pop(self._key, None)
        try:
            _unlock_file(self._fh)
        except OSError:
            pass
        try:
            self._fh.close()
        except OSError:
            pass
        self._fh = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def _lock_file(fh):
    import os as _os
    if _os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(fh):
    import os as _os
    if _os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ------------------------------------------------------------------- persistencia
FORGE_FILE = "forge.json"


def atomic_write_json(path, data):
    """Escritura atomica: tmp + rename para evitar corrupcion.

    En Windows `os.replace` falla con PermissionError si otro proceso esta
    reemplazando el destino en ese instante: se reintenta con backoff y se
    usa un nombre temporal UNICO (varios escritores concurrentes no pueden
    pisarse el `.tmp`).
    """
    import tempfile
    import time
    path = os.path.abspath(path)
    dirn = os.path.dirname(path)
    os.makedirs(dirn, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dirn, suffix=".tmp")
    try:
        # `newline=""`: los JSON se escriben byte-identicos en cualquier
        # plataforma. Su SHA-256 es evidencia versionada: si cambiara con los
        # finales de linea, el manifiesto no valdria en otro checkout.
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
        last = None
        for attempt in range(20):
            try:
                os.replace(tmp_name, path)
                tmp_name = None
                break
            except PermissionError as exc:
                last = exc
                time.sleep(0.05 * (attempt + 1))
        else:
            raise ForgeError("no se pudo escribir %s: %s" % (path, last))
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def save_forge(run, run_dir=None):
    """Persiste el run.

    `run_dir` es la autoridad: si se pasa, se escribe SIEMPRE ahi. Sin el, se
    usa `run["dir"]`, que es DATO del propio fichero y por tanto no puede
    decidir donde se escribe (un run movido o copiado se escribiria en la
    ruta antigua, resucitando el directorio original).
    """
    target = run_dir or run.get("dir")
    if not target:
        raise ForgeError("save_forge: no se conoce el directorio del run")
    atomic_write_json(os.path.join(target, FORGE_FILE), run)

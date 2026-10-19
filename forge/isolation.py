"""Workspace / Isolation Manager (§3.7, §13.3).

Garantiza que dos candidatos NUNCA comparten directorio de escritura. Como el
runtime no permite dirigir con fiabilidad cada sesion de subagente a un worktree
propio (capacidad `subagent_worktree` = unknown en el adapter), Patch Arena usa
la ALTERNATIVA SEGURA de la especificacion:

  1. cada candidato escribe solo en `candidates/<id>/`;
  2. sus cambios se capturan como parche Git canonico versionado;
  3. un ejecutor controlado aplica el parche a una COPIA temporal del baseline;
  4. los gates corren alli, no en el arbol real.

Nada del proyecto principal se modifica.

FORMATO DEL ARTEFACTO (unico y canonico)
-----------------------------------------
El parche es un **parche Git real** (`git diff --binary`). No existe un "formato
base64 propio": el contenido binario viaja con la codificacion literal/delta
que Git entiende, de modo que `git apply --check` lo valida y `git apply` lo
aplica sin reinterpretacion.

El artefacto se manipula como **bytes**, nunca como texto: un parche puede
contener bytes que no son UTF-8 valido y una conversion a `str` los
corromperia en silencio. Todo el pipeline (generar -> hashear -> decidir ->
exportar -> aplicar) opera sobre los MISMOS bytes.

SEGURIDAD DEL ENTORNO DE EJECUCION
-----------------------------------
`SECURITY_MODE = "TRUSTED_CODE_ONLY"`: este runtime no ofrece una frontera de
sistema operativo (sin usuario de minimos privilegios, sin filesystem
restringido, sin red bloqueada). Un directorio temporal con `cwd` y variables
filtradas NO es un sandbox. El codigo de los gates lo declara explicitamente.
"""
import os
import re
import shutil
import subprocess
import tempfile

from .util import (ForgeError, assert_inside, inside, sha_bytes, sha_file,
                   sha_text)

# Modo de ejecucion efectivo. Ver docs/THREAT_MODEL.md.
SECURITY_MODE = "TRUSTED_CODE_ONLY"

# Version del algoritmo de manifiesto. Cambiarlo invalida los manifiestos
# antiguos (fail-closed), que es el comportamiento correcto.
MANIFEST_VERSION = "manifest-v2"

# Politica de exclusiones: identica para el manifiesto y para el staging de Git,
# de modo que el parche y el manifiesto describen EXACTAMENTE el mismo conjunto
# de ficheros.
EXCLUDED_DIRS = (".git", "__pycache__", ".pytest_cache", ".mypy_cache",
                 ".ruff_cache")
EXCLUDED_SUFFIXES = (".pyc", ".pyo")

GIT_TIMEOUT_S = 120


# ------------------------------------------------------------------ rutas
def candidates_root(run_dir):
    return assert_inside(run_dir, os.path.join(run_dir, "candidates"), "candidates")


SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def ensure_workspaces(run_dir, candidate_ids):
    """Crea un directorio propio por candidato y devuelve la prueba de aislamiento.

    El identificador se VALIDA ANTES de crear nada: un id con separadores o
    `..` no puede crear un directorio fuera del run, ni siquiera para
    "luego detectarlo".
    """
    root = candidates_root(run_dir)
    os.makedirs(root, exist_ok=True)
    proof = {"root": os.path.relpath(root, run_dir), "candidates": {}, "shared": False,
             "ok": True, "problems": []}
    seen = {}
    for cid in candidate_ids:
        if not isinstance(cid, str) or not SAFE_ID_RE.match(cid) or cid in (".", ".."):
            proof["problems"].append("id de candidato no seguro: %r" % (cid,))
            proof["ok"] = False
            continue
        cdir = os.path.join(root, cid)
        real = os.path.realpath(cdir)
        if not inside(run_dir, real):
            # Se comprueba ANTES de crear: no se crea nada fuera del run.
            proof["problems"].append("candidato fuera del run: %s" % real)
            proof["ok"] = False
            continue
        os.makedirs(cdir, exist_ok=True)
        if real in seen:
            proof["problems"].append("dos candidatos comparten ruta: %s" % real)
            proof["shared"] = True
            proof["ok"] = False
        seen[real] = cid
        proof["candidates"][cid] = {"dir": os.path.relpath(cdir, run_dir),
                                    "realpath": real}
    return proof


# ------------------------------------------------------------- recorrido
def _excluded_dir(name):
    return name in EXCLUDED_DIRS


def _excluded_file(name):
    return name.endswith(EXCLUDED_SUFFIXES)


def _is_safe_symlink(root, path):
    """Verifica que un symlink no escape del root."""
    try:
        target = os.readlink(path)
        target_abs = os.path.normpath(os.path.join(os.path.dirname(path), target))
        root_real = os.path.realpath(root)
        target_real = os.path.realpath(target_abs)
        return target_real == root_real or target_real.startswith(root_real + os.sep)
    except OSError:
        return False


def walk_files_checked(root):
    """Devuelve (ficheros, problemas) sin ocultar ficheros peligrosos.

    `ficheros` es una lista de (relpath_normalizado, abspath) ordenada.
    `problemas` enumera symlinks no permitidos, symlinks rotos y fallos de
    lectura. Un `problemas` no vacio significa que la operacion DEBE fallar
    (fail-closed): nunca se omite en silencio el fichero.
    """
    problems = []
    files = []
    if not os.path.isdir(root):
        return [], ["raiz inexistente: %s" % root]
    root_real = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Los symlinks a directorio aparecen en dirnames; se comprueban aparte.
        real_dirs = []
        for d in sorted(dirnames):
            ap = os.path.join(dirpath, d)
            if os.path.islink(ap):
                if not os.path.exists(ap):
                    problems.append("symlink roto: %s"
                                    % os.path.relpath(ap, root))
                elif not _is_safe_symlink(root, ap):
                    problems.append("symlink no permitido (escapa del arbol): %s"
                                    % os.path.relpath(ap, root))
                else:
                    problems.append("symlink de directorio no soportado en el "
                                    "formato canonico: %s"
                                    % os.path.relpath(ap, root))
                continue
            if _excluded_dir(d):
                continue
            real_dirs.append(d)
        dirnames[:] = real_dirs
        for fname in sorted(filenames):
            if _excluded_file(fname):
                continue
            ap = os.path.join(dirpath, fname)
            rel = os.path.relpath(ap, root).replace("\\", "/")
            if os.path.islink(ap):
                if not os.path.exists(ap):
                    problems.append("symlink roto: %s" % rel)
                elif not _is_safe_symlink(root, ap):
                    problems.append("symlink no permitido (escapa del arbol): %s" % rel)
                else:
                    problems.append("symlink de fichero no soportado en el formato "
                                    "canonico: %s" % rel)
                continue
            if not os.path.isfile(ap):
                problems.append("no es un fichero regular: %s" % rel)
                continue
            if not os.access(ap, os.R_OK):
                problems.append("fichero no legible: %s" % rel)
                continue
            files.append((rel, ap))
    files.sort(key=lambda t: t[0])
    return files, problems


def _walk_files(root):
    """Compat: solo ficheros sin problemas. Prefiere `walk_files_checked`."""
    files, problems = walk_files_checked(root)
    if problems:
        raise ForgeError("no se puede construir el manifiesto: %s" % "; ".join(problems))
    for rel, ap in files:
        yield rel, ap


# ------------------------------------------------------------- binario/texto
def _is_binary_file(path):
    """Clasificacion binaria robusta (sin heuristica de porcentaje).

    Un fichero es binario si contiene un byte NUL en los primeros 8192 bytes
    **o** si no decodifica como UTF-8 estricto. La clasificacion por porcentaje
    de bytes no imprimibles se retiro: clasificaba como texto ficheros
    binarios sin NUL y los corrompia en silencio.

    La decodificacion es INCREMENTAL: un fichero multi-GB no se carga entero
    en memoria.
    """
    import codecs
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
            if b"\x00" in chunk:
                return True
            decoder = codecs.getincrementaldecoder("utf-8")()
            while True:
                block = fh.read(65536)
                if not block:
                    break
                try:
                    decoder.decode(block)
                except UnicodeDecodeError:
                    return True
            try:
                decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                return True
    except OSError:
        return False
    return False


def _lines(path):
    """Lineas de texto de un fichero. Un binario NUNCA se convierte en texto."""
    if os.path.isfile(path) and not _is_binary_file(path):
        with open(path, encoding="utf-8") as fh:
            return fh.readlines()
    return []


# --------------------------------------------------------------- manifiesto
def _mode_str(st_mode):
    """Bits de permiso relevantes, normalizados a 4 digitos octales."""
    return "%04o" % (st_mode & 0o7777)


def candidate_manifest_sha(candidate_dir):
    """Hash determinista del arbol completo del candidato.

    Incluye: ruta relativa normalizada, tipo, modo, tamano y SHA-256 del
    contenido. Falla (ForgeError) si hay symlinks no permitidos, symlinks
    rotos o ficheros ilegibles: un manifiesto incompleto es peor que ninguno.
    """
    files, problems = walk_files_checked(candidate_dir)
    if problems:
        raise ForgeError("manifiesto invalido: %s" % "; ".join(problems))
    parts = []
    for rel, abspath in files:
        try:
            st = os.stat(abspath)
            parts.append("%s|file|%s|%d|%s" % (rel, _mode_str(st.st_mode),
                                                st.st_size, sha_file(abspath)))
        except OSError as exc:
            raise ForgeError("fichero ilegible %s: %s" % (rel, exc))
    return sha_text("\n".join(parts))


def tree_sha(root):
    """SHA-256 del arbol de `root` con la misma politica que el manifiesto.

    Se usa para comparar el resultado de aplicar un parche con el candidato
    evaluado: si coinciden, el parche reproduce los bytes exactos.
    """
    files, problems = walk_files_checked(root)
    if problems:
        raise ForgeError("arbol invalido: %s" % "; ".join(problems))
    parts = []
    for rel, abspath in files:
        st = os.stat(abspath)
        parts.append("%s|file|%s|%d|%s" % (rel, _mode_str(st.st_mode),
                                            st.st_size, sha_file(abspath)))
    return sha_text("\n".join(parts))


def diff_sha(diff_bytes):
    """SHA-256 de los BYTES EXACTOS del parche (no de una re-serializacion)."""
    if isinstance(diff_bytes, str):
        diff_bytes = diff_bytes.encode("utf-8", errors="surrogateescape")
    return sha_bytes(diff_bytes)


# ------------------------------------------------------------------ parche
def _git_exe():
    exe = shutil.which("git")
    if not exe:
        raise ForgeError("git no esta disponible: no se puede generar ni aplicar "
                         "un parche canonico (fail-closed)")
    return exe


def _git(repo, args, check=True):
    cmd = [_git_exe()] + list(args)
    try:
        r = subprocess.run(cmd, cwd=repo, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ForgeError("git %s fallo: %s" % (" ".join(args[:2]), exc))
    if check and r.returncode != 0:
        raise ForgeError("git %s fallo (rc=%d): %s"
                         % (" ".join(args[:2]), r.returncode,
                            (r.stderr or b"").decode("utf-8", "replace")[:400]))
    return r.returncode, r.stdout, r.stderr


def _copy_tree(src, dst):
    """Copia un arbol a `dst` aplicando la politica de exclusiones comun.

    `src` puede no existir (baseline vacio). Nunca se siguen symlinks.
    """
    if not src or not os.path.isdir(src):
        return
    os.makedirs(dst, exist_ok=True)
    for name in sorted(os.listdir(src)):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.islink(s):
            # Los symlinks no se replican: el llamador ya los ha bloqueado.
            continue
        if os.path.isdir(s):
            if _excluded_dir(name):
                continue
            _copy_tree(s, d)
        elif os.path.isfile(s):
            if _excluded_file(name):
                continue
            shutil.copy2(s, d)


def capture_diff(baseline_dir, candidate_dir, name_hint=""):
    """Parche Git canonico (bytes) del candidato respecto al baseline.

    El parche usa el formato real de Git (`git diff --binary`), de modo que
    `git apply --check` lo valida y `git apply` lo aplica byte-exacto, incluidos
    los ficheros binarios. Si Git no esta disponible o el candidato contiene
    symlinks (no representables fielmente), se falla cerrado con ForgeError: no
    se devuelve nunca un parche inventado ni un parche parcial.

    `name_hint` se conserva por compatibilidad de API y no altera las rutas del
    parche (Git ya las emite como `a/<rel>` / `b/<rel>`).
    """
    if not os.path.isdir(candidate_dir):
        raise ForgeError("candidato inexistente: %s" % candidate_dir)
    files, problems = walk_files_checked(candidate_dir)
    if problems:
        raise ForgeError("candidato invalido: %s" % "; ".join(problems))
    if baseline_dir and os.path.isdir(baseline_dir):
        bfiles, bproblems = walk_files_checked(baseline_dir)
        if bproblems:
            raise ForgeError("baseline invalido: %s" % "; ".join(bproblems))

    work = tempfile.mkdtemp(prefix="forge-diff-")
    try:
        repo = os.path.join(work, "repo")
        os.makedirs(repo)
        _git(repo, ["init", "-q"])
        _git(repo, ["config", "user.email", "forge@localhost"])
        _git(repo, ["config", "user.name", "arena-forge"])
        _git(repo, ["config", "core.autocrlf", "false"])
        _git(repo, ["config", "core.eol", "lf"])
        _git(repo, ["config", "core.fileMode", "false"])
        _git(repo, ["config", "commit.gpgsign", "false"])
        _git(repo, ["config", "diff.noprefix", "false"])

        # 1) baseline -> arbol base
        _copy_tree(baseline_dir, repo)
        _git(repo, ["add", "-A", "-f"])
        rc, out, _err = _git(repo, ["write-tree"], check=False)
        if rc != 0:
            raise ForgeError("no se pudo construir el arbol base del baseline")
        base_tree = out.decode("ascii").strip()

        # 2) limpiar el working tree (menos .git) y copiar el candidato
        for name in os.listdir(repo):
            if name == ".git":
                continue
            p = os.path.join(repo, name)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
        _copy_tree(candidate_dir, repo)

        # 3) candidato -> arbol candidato y diff entre ambos arboles.
        #    Se VACIA el indice antes de volver a indexar: el indice guarda
        #    stat (mtime con granularidad de 1 segundo) y un fichero cuyo
        #    mtime cae en el mismo segundo que el del baseline se creeria
        #    "sin cambios" -> el parche saldria VACIO. Vaciarlo obliga a
        #    hashear el contenido de verdad.
        _git(repo, ["read-tree", "--empty"])
        _git(repo, ["add", "-A", "-f"])
        rc, out, _err = _git(repo, ["write-tree"], check=False)
        if rc != 0:
            raise ForgeError("no se pudo construir el arbol del candidato")
        cand_tree = out.decode("ascii").strip()
        if base_tree == cand_tree:
            return b""

        _rc, patch, _err = _git(repo, ["diff", "--binary", "--no-color",
                                       "--no-ext-diff", "--no-renames",
                                       base_tree, cand_tree], check=False)
        return patch
    finally:
        shutil.rmtree(work, ignore_errors=True)


def capture_diff_text(baseline_dir, candidate_dir, name_hint=""):
    """Conveniencia para logs: el parche como texto (con escapes seguros)."""
    return capture_diff(baseline_dir, candidate_dir, name_hint).decode(
        "utf-8", errors="replace")


# --------------------------------------------------------------- validacion
_PATH_RE_ABS = re.compile(r"^[A-Za-z]:")


def _safe_rel_path(path):
    """True si la ruta del parche es relativa, sin traversal y no absoluta."""
    if path is None:
        return False
    p = path.strip()
    if not p or p == "/dev/null":
        return True
    p = p.replace("\\", "/")
    if p.startswith("/") or _PATH_RE_ABS.match(p):
        return False
    if p.startswith("~"):
        return False
    segments = p.split("/")
    for seg in segments:
        if seg == "..":
            return False
    return True


def _unquote_c_style(path):
    """Quita las comillas estilo C que git usa para rutas con espacios.

    Sin esto, `rename to "../evil.txt"` llegaria al validador como
    `"../evil.txt"` (con la comilla) y la comprobacion de `..` no lo detectaria.
    """
    if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
        inner = path[1:-1]
        out = []
        i = 0
        while i < len(inner):
            ch = inner[i]
            if ch == "\\" and i + 1 < len(inner):
                nxt = inner[i + 1]
                out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"',
                            "\\": "\\"}.get(nxt, nxt))
                i += 2
                continue
            out.append(ch)
            i += 1
        return "".join(out)
    return path


def _patch_paths(diff_bytes):
    """Extrae todas las rutas mencionadas por las cabeceras del parche."""
    if isinstance(diff_bytes, bytes):
        text = diff_bytes.decode("utf-8", errors="replace")
    else:
        text = diff_bytes
    paths = []
    for line in text.splitlines():
        if line.startswith("diff --git "):
            rest = line[len("diff --git "):].strip()
            rest = _unquote_c_style(rest)
            half = len(rest) // 2
            left = rest[:half].strip()
            right = rest[half:].strip()
            for part in (left, right):
                part = _unquote_c_style(part)
                if part.startswith("a/"):
                    part = part[2:]
                elif part.startswith("b/"):
                    part = part[2:]
                paths.append(part)
        elif line.startswith("--- "):
            t = line[4:].split("\t")[0].strip()
            t = _unquote_c_style(t)
            if t != "/dev/null":
                paths.append(t[2:] if t.startswith(("a/", "b/")) else t)
        elif line.startswith("+++ "):
            t = line[4:].split("\t")[0].strip()
            t = _unquote_c_style(t)
            if t != "/dev/null":
                paths.append(t[2:] if t.startswith(("a/", "b/")) else t)
        elif line.startswith("rename to ") or line.startswith("copy to "):
            paths.append(_unquote_c_style(line.split(" ", 2)[2].strip()))
        elif line.startswith("rename from ") or line.startswith("copy from "):
            paths.append(_unquote_c_style(line.split(" ", 2)[2].strip()))
    return paths


def validate_diff(diff_bytes):
    """Rechaza diffs que intenten rutas fuera del arbol de trabajo.

    Valida TODAS las formas de cabecera que puede emitir Git: `diff --git`,
    `---`, `+++`, `rename to`, `copy to`. Un traversal en cualquiera de ellas
    invalida el parche entero.
    """
    problems = []
    for target in _patch_paths(diff_bytes):
        if not _safe_rel_path(target):
            problems.append("ruta sospechosa en diff: %r" % target)
    return (not problems), problems


# ---------------------------------------------------------------- aplicacion
def _git_apply(scratch, diff_bytes, check_only=False):
    exe = shutil.which("git")
    if not exe:
        return False
    patch_path = os.path.join(scratch, ".forge.patch")
    try:
        with open(patch_path, "wb") as fh:
            fh.write(diff_bytes)
        # `core.autocrlf=false` es OBLIGATORIO: con el valor global de Windows
        # (true) `git apply` reescribe LF->CRLF al aplicar, y el arbol
        # resultante deja de coincidir byte a byte con el candidato evaluado.
        cmd = [exe, "-c", "core.autocrlf=false", "-c", "core.eol=lf",
               "apply", "-p1", "--whitespace=nowarn", "--binary"]
        if check_only:
            cmd.append("--check")
        cmd.append(".forge.patch")
        try:
            r = subprocess.run(cmd, cwd=scratch, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=GIT_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0
    finally:
        try:
            os.remove(patch_path)
        except OSError:
            pass


def apply_diff_to_temp(diff_bytes, baseline_dir):
    """Ejecutor controlado: aplica el parche a una copia temporal del baseline.

    Devuelve la ruta del scratch. El arbol real no se toca nunca. Si el parche
    no valida (`git apply --check`) o no se aplica, el scratch se destruye y se
    eleva ForgeError: no queda ningun residuo.
    """
    ok, problems = validate_diff(diff_bytes)
    if not ok:
        raise ForgeError("diff inseguro: %s" % "; ".join(problems))
    scratch = tempfile.mkdtemp(prefix="forge-isolate-")
    try:
        _copy_tree(baseline_dir, scratch)
        if diff_bytes and diff_bytes.strip():
            if not _git_apply(scratch, diff_bytes, check_only=True):
                raise ForgeError("el parche no supera `git apply --check`")
            if not _git_apply(scratch, diff_bytes, check_only=False):
                raise ForgeError("no se pudo aplicar el diff a la copia temporal")
        return scratch
    except Exception:
        shutil.rmtree(scratch, ignore_errors=True)
        raise

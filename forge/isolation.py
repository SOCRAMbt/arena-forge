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


def _walk_files(root):
    """Genera (relpath, abspath) para todos los ficheros bajo root (recursivo)."""
    if not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip only specific cache directories, not all hidden dirs
        dirnames[:] = sorted(d for d in dirnames 
                            if d not in (".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"))
        for fname in sorted(filenames):
            if fname.endswith((".pyc",)):
                continue
            ap = os.path.join(dirpath, fname)
            # Verificar symlinks inseguros
            if os.path.islink(ap):
                if not _is_safe_symlink(root, ap):
                    continue  # Saltar symlinks inseguros
            rel = os.path.relpath(ap, root)
            yield rel.replace("\\", "/"), ap


def _binary_diff_line(p_old, p_new, rel_full):
    """Genera un diff estilo git para archivos binarios con contenido base64."""
    import base64
    old_sha = sha_file(p_old) if os.path.isfile(p_old) else None
    new_sha = sha_file(p_new) if os.path.isfile(p_new) else None
    
    lines = []
    lines.append("diff --git a/%s b/%s" % (rel_full, rel_full))
    lines.append("index %s..%s 100644" % (old_sha[:7] if old_sha else "0000000", new_sha[:7] if new_sha else "0000000"))
    
    if os.path.isfile(p_new):
        # Leer y codificar en base64 el contenido del archivo nuevo
        with open(p_new, "rb") as f:
            content = f.read()
        b64_content = base64.b64encode(content).decode("ascii")
        # Formato similar a git binary patch
        lines.append("GIT binary patch")
        lines.append("literal %d" % len(content))
        # Dividir en lineas de max 76 chars (formato base64 estandar)
        for i in range(0, len(b64_content), 76):
            lines.append(b64_content[i:i+76])
    else:
        # Archivo eliminado
        lines.append("deleted file mode 100644")
    
    return "\n".join(lines) + "\n"


def capture_diff(baseline_dir, candidate_dir, name_hint=""):
    """Diff unificado recursivo de los ficheros del candidato respecto al baseline."""
    chunks = []
    if not os.path.isdir(candidate_dir):
        return ""
    
    # Recopilar archivos del baseline
    baseline_files = dict(_walk_files(baseline_dir))
    candidate_files = dict(_walk_files(candidate_dir))
    
    all_paths = sorted(set(baseline_files.keys()) | set(candidate_files.keys()))
    
    for rel in all_paths:
        p_old = baseline_files.get(rel)
        p_new = candidate_files.get(rel)
        
        if p_old and p_new:
            # Archivo modificado
            old_is_binary = _is_binary_file(p_old)
            new_is_binary = _is_binary_file(p_new)
            
            if old_is_binary or new_is_binary:
                # Archivo binario: usar formato git binary diff
                rel_full = os.path.join(name_hint, rel) if name_hint else rel
                chunks.append(_binary_diff_line(p_old, p_new, rel_full))
            else:
                # Archivo de texto: diff unificado normal
                old = _lines(p_old)
                new = _lines(p_new)
                if old != new:
                    rel_full = os.path.join(name_hint, rel) if name_hint else rel
                    chunks.append("".join(difflib.unified_diff(
                        old, new, "a/" + rel_full, "b/" + rel_full)))
        elif p_new and not p_old:
            # Archivo nuevo
            new_is_binary = _is_binary_file(p_new)
            if new_is_binary:
                rel_full = os.path.join(name_hint, rel) if name_hint else rel
                chunks.append(_binary_diff_line("/dev/null", p_new, rel_full))
            else:
                new = _lines(p_new)
                old = []
                rel_full = os.path.join(name_hint, rel) if name_hint else rel
                chunks.append("".join(difflib.unified_diff(
                    old, new, "/dev/null", "b/" + rel_full)))
        elif p_old and not p_new:
            # Archivo eliminado
            old_is_binary = _is_binary_file(p_old)
            if old_is_binary:
                rel_full = os.path.join(name_hint, rel) if name_hint else rel
                chunks.append(_binary_diff_line(p_old, "/dev/null", rel_full))
            else:
                old = _lines(p_old)
                new = []
                rel_full = os.path.join(name_hint, rel) if name_hint else rel
                chunks.append("".join(difflib.unified_diff(
                    old, new, "a/" + rel_full, "/dev/null")))
    return "".join(chunks)


def _is_binary_file(path):
    """Detecta si un archivo es binario."""
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
            if b"\x00" in chunk:
                return True
            # Heurística: si más del 30% son caracteres no imprimibles, es binario
            non_printable = sum(1 for b in chunk if b < 32 and b not in (9, 10, 13))
            if len(chunk) > 0 and non_printable / len(chunk) > 0.3:
                return True
    except OSError:
        pass
    return False


def _lines(path):
    if os.path.isfile(path):
        if _is_binary_file(path):
            return ["[BINARY FILE]\n"]
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readlines()
    return []


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


def diff_sha(diff_text):
    return sha_text(diff_text)


def candidate_manifest_sha(candidate_dir):
    """Calcula un hash determinista del árbol completo del candidato.
    
    Incluye: rutas relativas normalizadas, tipo, tamaño, SHA-256.
    """
    files = dict(_walk_files(candidate_dir))
    if not files:
        return sha_text("")
    parts = []
    for rel, abspath in sorted(files.items()):
        try:
            st = os.stat(abspath)
            file_sha = sha_file(abspath)
            parts.append("%s|%s|%d|%s" % (rel, "file", st.st_size, file_sha))
        except OSError:
            parts.append("%s|%s|%d|%s" % (rel, "file", 0, "error"))
    return sha_text("\n".join(parts))


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
        # Copia recursiva del baseline preservando estructura de directorios
        for name in os.listdir(baseline_dir):
            src = os.path.join(baseline_dir, name)
            dst = os.path.join(scratch, name)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
            elif os.path.isdir(src):
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if diff_text.strip():
        # parche compatible con `patch -p1`/`git apply`; se aplica con difflib no
        # disponible -> usamos `git apply` si hay git, si no `patch`.
        applied = _apply(scratch, diff_text)
        if not applied:
            shutil.rmtree(scratch, ignore_errors=True)
            raise ForgeError("no se pudo aplicar el diff a la copia temporal")
    return scratch


def _apply_binary_diff(scratch, diff_text):
    """Aplica un diff binario manualmente decodificando el contenido base64."""
    import base64
    import re
    
    # Parsear el diff binario
    # Formato: diff --git a/file b/file, index <old>..<new>, GIT binary patch, literal <len>, <base64 content>
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            # Parsear archivo
            match = re.match(r'diff --git a/(.+) b/(.+)', line)
            if match:
                # Usar el archivo de destino (b/)
                rel_file = match.group(2)
                i += 1
                # Saltar línea index
                i += 1
                # Verificar si es un binary patch
                if i < len(lines) and lines[i].startswith("GIT binary patch"):
                    i += 1
                    # Leer línea "literal <length>"
                    if i < len(lines) and lines[i].startswith("literal "):
                        length = int(lines[i].split()[1])
                        i += 1
                        # Leer el contenido base64 (puede estar en múltiples líneas)
                        b64_content = ""
                        while i < len(lines) and len(b64_content) < length * 4 / 3 + 100:  # estimación
                            line = lines[i]
                            if line.startswith(("diff --git ", "index ", "deleted file")):
                                break
                            b64_content += line.strip()
                            i += 1
                        
                        # Decodificar y escribir archivo
                        try:
                            content = base64.b64decode(b64_content)
                            dst = os.path.join(scratch, rel_file)
                            os.makedirs(os.path.dirname(dst), exist_ok=True)
                            with open(dst, "wb") as f:
                                f.write(content)
                            # Saltar al siguiente diff
                            continue
                        except Exception as e:
                            print(f"Error applying binary patch for {rel_file}: {e}")
                            return False
                # Saltar línea "deleted file mode..."
                elif lines[i].startswith("deleted file mode"):
                    rel_file = lines[i].split()[-1]
                    dst = os.path.join(scratch, rel_file)
                    if os.path.exists(dst):
                        os.remove(dst)
                i += 1
            else:
                i += 1
    return True





def _apply(scratch, diff_text):
    """Aplica un diff (texto o binario) al scratch."""
    # Detectar si es un diff binario
    if "GIT binary patch" in diff_text and "diff --git" in diff_text:
        return _apply_binary_diff(scratch, diff_text)
    
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

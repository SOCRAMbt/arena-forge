"""Lint propio del repo (sin dependencias externas) + deteccion de herramientas ausentes.

Por que existe: el contrato (AF-AC-012) exige "tests, lint, typecheck, build y E2E
pertinentes ejecutados; herramientas ausentes marcadas NOT_RUN". En este entorno no
hay `ruff` ni `mypy` instalados y no se pueden instalar globalmente, asi que:

- el **build** es `python -m compileall` (stdlib, siempre disponible);
- el **lint** es ESTE modulo (AST sobre el codigo del repo, sin instalar nada);
- el **typecheck** se declara `NOT_RUN` con su causa exacta, no se simula.

El lint tiene AUTOTEST (`tools/test_lint.py`): sin un control negativo, un lint
que no detecta nada tambien pasaria en verde.

Uso:
    python tools/lint.py            # sale con 1 si hay ERRORES
    python tools/lint.py --report   # imprime tambien las herramientas ausentes
"""
import ast
import io
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_DIRS = ("forge", "tools")
TARGET_FILES = ("arena_forge.py",)
TEST_DIRS = ("tests",)
SKIP_DIRS = {".git", ".arena", "__pycache__", ".pytest_cache", "vendor",
              "reports", "docs", "build", "dist"}
# Marcadores pendientes: palabra COMPLETA en mayusculas seguida de `:` o `(`
# (convencion). Hace falta el calificador porque en espanol "TODO" en
# mayusculas significa "todo" (p.ej. "recorre TODO el arbol") y no es un
# marcador pendiente.
PENDING_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\s*[:(\[]")


def _iter_sources():
    for top in TARGET_FILES:
        p = os.path.join(REPO, top)
        if os.path.isfile(p):
            yield p
    for d in TARGET_DIRS:
        base = os.path.join(REPO, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirs, names in os.walk(base):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for n in sorted(names):
                if n.endswith(".py"):
                    yield os.path.join(dirpath, n)


def _bindings(tree):
    """Bindings de nivel superior (funciones, clases, asignaciones, imports).

    Matiz: `import urllib.error` y `import urllib.parse` enlazan el MISMO
    nombre (`urllib`), porque el submódulo se importa dentro de su paquete.
    Eso NO es una redefinicion: es el mismo paquete enlazado dos veces. Si dos
    imports enlazan el mismo nombre来自 paquetes DISTINTOS (o con `as`), si es
    un conflicto real.
    """
    defs = {}       # nombre -> lineas (funcion, clase, asignacion)
    imports = {}    # nombre -> (lineas, paquetes)
    conflicts = {}

    def bind_def(name, lineno):
        defs.setdefault(name, []).append(lineno)
        all_lines = list(defs[name]) + list(imports.get(name, ([], set()))[0])
        if len(all_lines) > 1:
            conflicts.setdefault(name, []).extend(all_lines)

    def bind_import(name, package, lineno):
        prev_lines, prev_pkgs = imports.get(name, ([], set()))
        same_pkg = bool(prev_pkgs) and prev_pkgs == {package}
        imports.setdefault(name, ([], set()))[0].append(lineno)
        imports[name][1].add(package)
        if prev_lines and not same_pkg:
            conflicts.setdefault(name, []).extend(prev_lines + [lineno])
        if name in defs:
            conflicts.setdefault(name, []).extend(defs[name] + [lineno])

    def scan(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                bind_def(node.name, node.lineno)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        bind_def(t.id, node.lineno)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        bind_import(alias.asname, alias.asname, node.lineno)
                    else:
                        pkg = alias.name.split(".")[0]
                        bind_import(pkg, pkg, node.lineno)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    bind_import(bound, node.module or "", node.lineno)
            else:
                for attr in ("body", "orelse", "finalbody"):
                    sub = getattr(node, attr, None)
                    if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                        scan(sub)
    scan(tree.body)
    return conflicts


def lint(path):
    """Devuelve (errores, avisos) de un fichero.

    Errores (rompen el build): binding duplicado, shell=True, assert fuera de
    tests, error de sintaxis.
    Avisos (se reportan, no rompen): 'except: pass' silencioso, marcadores
    pendientes.
    """
    errors = []
    warnings = []
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    # `os.path.relpath` LANZA ValueError si las rutas estan en unidades
    # distintas (Windows: repo en D:\ y temporal en C:\, que es justo lo que
    # pasa en los runners de GitHub Actions). Se degrada al nombre de fichero.
    try:
        rel = os.path.relpath(path, REPO).replace("\\", "/")
    except ValueError:
        rel = os.path.basename(path)
    is_test = any(rel.startswith(d + "/") for d in TEST_DIRS) or \
        os.path.basename(rel).startswith("test")

    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        return (["%s:%d: error de sintaxis: %s" % (rel, exc.lineno, exc.msg)], [])

    for name, lines in sorted(_bindings(tree).items()):
        if len(lines) > 1:
            errors.append("%s: binding duplicado en nivel de modulo: %r (lineas %s)"
                          % (rel, name, lines))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "run" and \
                    isinstance(fn.value, ast.Name) and fn.value.id == "subprocess":
                for kw in node.keywords:
                    if kw.arg == "shell":
                        errors.append("%s:%d: subprocess con shell=True"
                                      % (rel, node.lineno))
        if isinstance(node, ast.ExceptHandler):
            body = node.body
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                warnings.append("%s:%d: 'except: pass' silencioso"
                                % (rel, node.lineno))
        if isinstance(node, ast.Assert) and not is_test:
            errors.append("%s:%d: 'assert' fuera de un test" % (rel, node.lineno))

    for i, line in enumerate(text.splitlines(), 1):
        m = PENDING_RE.search(line)
        if m:
            warnings.append("%s:%d: marcador pendiente: %s"
                            % (rel, i, m.group(0)))
    return errors, warnings


def absent_tools():
    """Herramientas del contrato que NO estan instaladas (se declaran NOT_RUN)."""
    out = []
    for tool, label in (("ruff", "lint"), ("mypy", "typecheck"),
                        ("flake8", "lint"), ("pylint", "lint"),
                        ("pyright", "typecheck")):
        if shutil.which(tool) is None:
            out.append((label, tool))
    seen = set()
    unique = []
    for label, tool in out:
        if tool in seen:
            continue
        seen.add(tool)
        unique.append((label, tool))
    return unique


def main():
    report = "--report" in sys.argv
    errors = []
    warnings = []
    files = 0
    for p in _iter_sources():
        files += 1
        e, w = lint(p)
        errors.extend(e)
        warnings.extend(w)
    print("lint propio: %d ficheros analizados, %d error(es), %d aviso(s)"
          % (files, len(errors), len(warnings)))
    for pr in errors:
        print("  ERROR  %s" % pr)
    for pr in warnings:
        print("  aviso  %s" % pr)

    r = subprocess.run([sys.executable, "-m", "compileall", "-q",
                        "arena_forge.py", "forge", "tests", "tools"],
                       cwd=REPO, capture_output=True, text=True)
    print("build (compileall): %s" % ("OK" if r.returncode == 0 else
                                      "FALLO: %s" % r.stderr.strip()[:300]))

    missing = absent_tools()
    if missing:
        print("herramientas ausentes -> NOT_RUN (no se instalan globalmente):")
        for label, tool in missing:
            print("  - %s: %s no esta instalado" % (label, tool))
    else:
        print("herramientas externas: todas presentes")

    if report:
        print("\nNOT_RUN declarado explicitamente por el contrato AF-AC-012:")
        for label, tool in missing:
            print("  - %s (`%s`): NOT_RUN" % (label, tool))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

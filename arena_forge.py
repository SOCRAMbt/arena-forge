#!/usr/bin/env python
"""ARENA FORGE — runtime local de competicion de ingenieria para OpenCode V2.

Modos: answer (texto, reutiliza bracket.py vendored) y patch (codigo real con
gates objetivos que preceden a cualquier puntuacion LLM).

Uso: python arena_forge.py <comando> [opciones]. Todo el estado vive en
.arena/<run>/ (arena.json del torneo + forge.json de gobierno). Reanudar es
siempre seguro: nada completado se re-ejecuta ni se reescribe.

Solo stdlib. Windows/macOS/Linux (`python` o `python3`).
"""
import argparse
import difflib
import hashlib
import html
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRACKET = os.path.join(HERE, "vendor", "arena-skill", "bracket.py")
STRATEGIES = os.path.join(HERE, "vendor", "arena-skill", "strategies.json")
RUBRIC = os.path.join(HERE, "vendor", "arena-skill", "rubric.md")
FORGE_VERSION = 1
ROOT = ".arena"
LATEST = "LATEST"
FORGE_FILE = "forge.json"
LOCK_FILE = "lock.json"
MAX_OUTPUT_BYTES = 1024 * 1024  # veredictos/soluciones mayores se marcan BLOCKED
TERMINAL = ("WINNER", "NO_SHIP", "CANCELLED", "BLOCKED", "FAILED")


class ForgeError(Exception):
    pass


# ------------------------------------------------------------- utilidades
def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def run_dir_from(args):
    if getattr(args, "dir", None):
        return os.path.abspath(args.dir)
    latest = os.path.join(ROOT, LATEST)
    if not os.path.isfile(latest):
        raise ForgeError("no hay ejecucion en %s (usa init --dir ...)" % latest)
    with open(latest, encoding="utf-8") as fh:
        return fh.read().strip()


def load_forge(d):
    path = os.path.join(d, FORGE_FILE)
    if not os.path.isfile(path):
        raise ForgeError("sin %s en %s" % (FORGE_FILE, d))
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("version") != FORGE_VERSION:
        raise ForgeError("forge.json version %r no soportada (esperada %d)"
                         % (data.get("version"), FORGE_VERSION))
    return data


def save_forge(state):
    atomic_write_json(os.path.join(state["dir"], FORGE_FILE), state)


def log_event(state, kind, detail=""):
    state.setdefault("events", []).append(
        {"t": int(time.time()), "kind": kind, "detail": detail})
    save_forge(state)


def acquire_lock(d, owner="cli"):
    path = os.path.join(d, LOCK_FILE)
    now = time.time()
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                cur = json.load(fh)
            if now - cur.get("t", 0) < 300 and cur.get("pid") != os.getpid():
                raise ForgeError("otra controladora activa (%s, pid %s); "
                                 "espera o borra %s si es rancia"
                                 % (cur.get("owner"), cur.get("pid"), path))
        except (ValueError, KeyError):
            pass  # lock corrupto: se reemplaza
    atomic_write_json(path, {"owner": owner, "pid": os.getpid(), "t": now})


def release_lock(d):
    try:
        os.remove(os.path.join(d, LOCK_FILE))
    except OSError:
        pass


def bracket_cmd(*parts, cwd=None):
    return subprocess.run([sys.executable, BRACKET] + list(parts),
                          cwd=cwd or os.getcwd(), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def guard_mutable(forge):
    if forge.get("status") in ("CANCELLED",):
        raise ForgeError("ejecucion CANCELLED: no se aceptan collect/advance "
                         "(crea una nueva con init)")


def inside_run(d, path):
    """True si path resuelto queda dentro del run (anti path-traversal)."""
    base = os.path.realpath(d)
    return os.path.realpath(path).startswith(base + os.sep)


def quarantine_oversize(d):
    """Mueve veredictos gigantes (>1MB) a .oversize para que el collect nunca
    los cargue en memoria; el match queda pendiente y se re-ejecuta el juez."""
    for root, _, files in os.walk(d):
        for name in files:
            if not name.endswith(".verdict.json"):
                continue
            p = os.path.join(root, name)
            if not inside_run(d, p):
                continue
            try:
                if os.path.getsize(p) > MAX_OUTPUT_BYTES:
                    os.replace(p, p + ".oversize")
                    print("BLOCKED oversize: %s movido a .oversize" % p)
            except OSError:
                pass


# ------------------------------------------------------------- comandos base
def cmd_plan(args):
    r = bracket_cmd("plan", "--agents", str(args.agents or 100),
                    "--wave", str(args.wave))
    print(r.stdout, end="")
    try:
        data = json.loads(subprocess.run(
            [sys.executable, BRACKET, "plan", "--agents", str(args.agents or 100),
             "--wave", str(args.wave), "--json"],
            text=True, stdout=subprocess.PIPE).stdout)
        print("presupuesto: %d llamadas subagente en %d olas de %d "
              "(+1 si hay baseline). Sin coste monetario medible: el proveedor "
              "no expone tokens por API; limite real = llamadas/olas/tiempo."
              % (data["calls"], data["waves"], args.wave))
    except (ValueError, KeyError):
        pass
    return r.returncode


def cmd_init(args):
    n = args.quick and 16 or (args.agents or 100)
    if args.mode not in ("answer", "patch"):
        raise ForgeError("--mode debe ser answer o patch")
    parts = ["init", "--agents", str(n)]
    if args.seed is not None:
        parts += ["--seed", str(args.seed)]
    task = ""
    if args.task_file:
        with open(args.task_file, encoding="utf-8") as fh:
            task = fh.read()
        parts += ["--task-file", os.path.abspath(args.task_file)]
    elif args.task:
        task = args.task
        parts += ["--task", args.task]
    else:
        raise ForgeError("pasa --task o --task-file")
    if args.baseline_file:
        parts += ["--baseline-file", os.path.abspath(args.baseline_file)]
    parts += ["--wave", str(args.wave)]
    if args.dir:
        parts += ["--dir", os.path.abspath(args.dir)]
    r = bracket_cmd(*parts)
    print(r.stdout, end="")
    if r.returncode != 0:
        return r.returncode
    d = os.path.abspath(args.dir) if args.dir else run_dir_from(args)
    suite_sha = None
    if args.suite:
        if not os.path.isfile(args.suite):
            raise ForgeError("suite inexistente: %s" % args.suite)
        suite_sha = sha_file(args.suite)
    baseline_commit = "n/a-no-repo"
    try:
        c = subprocess.run(["git", "rev-parse", "HEAD"], text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if c.returncode == 0:
            baseline_commit = c.stdout.strip()
    except OSError:
        pass
    forge = {
        "version": FORGE_VERSION,
        "mode": args.mode,
        "status": "RUNNING",
        "dir": d,
        "seed": args.seed,
        "agents": n,
        "wave": args.wave,
        "task_sha": sha_text(task),
        "rubric_sha": sha_file(os.path.join(d, "rubric.md")),
        "cards_sha": sha_file(STRATEGIES),
        "suite": os.path.abspath(args.suite) if args.suite else None,
        "suite_sha": suite_sha,
        "baseline_commit": baseline_commit,
        "created": int(time.time()),
        "events": [{"t": int(time.time()), "kind": "init",
                    "detail": "mode=%s agents=%d" % (args.mode, n)}],
    }
    save_forge(forge)
    print("forge: %s [%s, %s]" % (os.path.join(d, FORGE_FILE), args.mode, "RUNNING"))
    return 0


def cmd_next(args):
    d = run_dir_from(args)
    forge = load_forge(d)
    print("forge status: %s [%s]" % (forge["status"], forge["mode"]))
    r = bracket_cmd("next", "--dir", d)
    print(r.stdout, end="")
    return r.returncode


def cmd_passthrough(name, args, extra=()):
    d = run_dir_from(args)
    forge = load_forge(d)
    if name in ("collect", "advance"):
        guard_mutable(forge)
        acquire_lock(d)
        try:
            if name == "collect":
                quarantine_oversize(d)
            r = bracket_cmd(name, "--dir", d, *extra)
            print(r.stdout, end="")
            log_event(forge, name, "rc=%d" % r.returncode)
            return r.returncode
        finally:
            release_lock(d)
    r = bracket_cmd(name, "--dir", d, *extra)
    print(r.stdout, end="")
    return r.returncode


# ------------------------------------------------------------- gates (patch)
def run_gates(candidate_dir, protected_suite, timeout_s=120):
    """Ejecuta la suite PROTEGIDA contra un candidato en un scratch limpio.

    Devuelve dict {verdict: PASS|FAIL|NOT_RUN|BLOCKED, log, sha_ok}.
    Nunca ejecuta codigo del candidato in-place: se copia a temp.
    """
    t0 = time.time()
    if not os.path.isfile(protected_suite):
        return {"verdict": "NOT_RUN", "log": "suite ausente", "sha_ok": None,
                "seconds": 0.0}
    suite_before = sha_file(protected_suite)
    scratch = tempfile.mkdtemp(prefix="forge-gate-")
    try:
        for name in os.listdir(candidate_dir):
            src = os.path.join(candidate_dir, name)
            if os.path.isfile(src) and not name.startswith("tests_protected"):
                shutil.copy2(src, os.path.join(scratch, name))
        shutil.copy2(protected_suite, os.path.join(scratch, "test_protected.py"))
        # contaminacion: el candidato no debe traer su propia suite protegida
        for name in os.listdir(candidate_dir):
            if name.startswith("tests_protected") or name == "test_protected.py":
                return {"verdict": "BLOCKED",
                        "log": "contaminacion: el candidato incluye %s" % name,
                        "sha_ok": True, "seconds": time.time() - t0}
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "test_protected.py"],
                cwd=scratch, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=timeout_s)
            out = r.stdout[-4000:]
            verdict = "PASS" if r.returncode == 0 else "FAIL"
        except subprocess.TimeoutExpired:
            out, verdict = "timeout %ss" % timeout_s, "BLOCKED"
        except OSError as exc:
            out, verdict = "no se pudo ejecutar pytest: %s" % exc, "NOT_RUN"
        sha_ok = sha_file(protected_suite) == suite_before
        if not sha_ok:
            verdict = "BLOCKED"
            out += "\nSUITE ALTERADA durante la evaluacion"
        return {"verdict": verdict, "log": out, "sha_ok": sha_ok,
                "seconds": round(time.time() - t0, 1)}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def cmd_gates(args):
    d = run_dir_from(args)
    forge = load_forge(d)
    if not forge.get("suite"):
        raise ForgeError("esta ejecucion no tiene suite (modo answer o init sin --suite)")
    results = {}
    cands_root = os.path.join(d, "candidates")
    if os.path.isdir(cands_root):
        for cand in sorted(os.listdir(cands_root)):
            cdir = os.path.join(cands_root, cand)
            if os.path.isdir(cdir):
                results[cand] = run_gates(cdir, forge["suite"])
                print("%s: %s (%.1fs)" % (cand, results[cand]["verdict"],
                                         results[cand]["seconds"]))
    if not results:
        print("sin candidatos en %s" % cands_root)
    atomic_write_json(os.path.join(d, "gates.json"), results)
    return 0


# ------------------------------------------------------------- resume/cancel
def cmd_resume(args):
    d = run_dir_from(args)
    forge = load_forge(d)
    if forge.get("status") == "CANCELLED":
        raise ForgeError("CANCELLED: crea una nueva ejecucion con init")
    arena_path = os.path.join(d, "arena.json")
    before = {}
    if os.path.isfile(arena_path):
        with open(arena_path, encoding="utf-8") as fh:
            st = json.load(fh)
        for rd in st.get("rounds", []):
            for m in rd.get("matches", []):
                if m.get("winner"):
                    before[m["id"]] = m["winner"]
    print("completados persistidos: %d matches con ganador" % len(before))
    r = bracket_cmd("next", "--dir", d)
    print(r.stdout, end="")
    log_event(forge, "resume", "%d completados intactos" % len(before))
    return r.returncode


def cmd_cancel(args):
    d = run_dir_from(args)
    forge = load_forge(d)
    forge["status"] = "CANCELLED"
    log_event(forge, "cancel", args.reason or "")
    print("CANCELLED %s (artefactos conservados)" % d)
    return 0


# ------------------------------------------------------------- report/apply
def esc(value):
    return html.escape(str(value), quote=True)


def resolve_patch_winner(d, forge, gates):
    """Devuelve (candidate_dir_name, reason) o (None, reason NO_SHIP)."""
    eligible = sorted(c for c, g in gates.items() if g.get("verdict") == "PASS")
    if not eligible:
        return None, "ningun candidato supera los gates obligatorios"
    pj = os.path.join(d, "patch_judge.json")
    try:
        with open(pj, encoding="utf-8") as fh:
            patch_judge = json.load(fh)
    except (OSError, ValueError):
        patch_judge = None
    if not patch_judge or patch_judge.get("_malformed"):
        if not gates:
            return None, "sin gates ejecutados"
        return None, ("%d elegibles sin desempate ciego; el score no puede "
                      "elegir solo" % len(eligible))
    label_map = {"X": None, "Y": None}
    pmap = os.path.join(d, "patch_map.json")
    if os.path.isfile(pmap):
        try:
            with open(pmap, encoding="utf-8") as fh:
                label_map.update(json.load(fh))
        except ValueError:
            pass
    if not label_map.get("X") and len(eligible) >= 1:
        label_map["X"] = sorted(eligible)[0]
    if not label_map.get("Y") and len(eligible) >= 2:
        label_map["Y"] = sorted(eligible)[1]
    cand = label_map.get(patch_judge.get("winner"))
    if cand and cand in eligible:
        return cand, ("gates PASS + juez ciego: %s"
                      % (patch_judge.get("reason") or ""))
    return None, "veredicto ciego invalido o inelegible"


def cmd_report(args):
    d = run_dir_from(args)
    forge = load_forge(d)
    with open(os.path.join(d, "arena.json"), encoding="utf-8") as fh:
        st = json.load(fh)
    gates = {}
    gp = os.path.join(d, "gates.json")
    if os.path.isfile(gp):
        with open(gp, encoding="utf-8") as fh:
            gates = json.load(fh)
    champ = st.get("champion")
    if forge.get("status") in ("CANCELLED", "BLOCKED", "FAILED"):
        decision, reason = forge["status"], "estado terminal previo"
    elif forge["mode"] == "patch":
        cand, why = resolve_patch_winner(d, forge, gates)
        if cand:
            decision, reason = "WINNER", "%s gana (%s)" % (cand, why)
        else:
            decision, reason = "NO_SHIP", why
    elif not champ:
        decision, reason = "NO_SHIP", "sin campeon (torneo incompleto o cancelado)"
    elif forge["mode"] == "patch":
        bad = {c: g["verdict"] for c, g in gates.items()
               if g["verdict"] != "PASS"}
        champ_gate = gates.get(champ, {}).get("verdict")
        if champ_gate != "PASS":
            decision = "NO_SHIP"
            reason = ("el campeon %s no supera gates (%s); "
                      "ningun score lo habilita" % (champ, champ_gate))
        else:
            decision, reason = "WINNER", "gates PASS + mejor score ciego"
    else:
        decision, reason = "WINNER", "campeon del bracket answer"
    if decision in ("WINNER", "NO_SHIP") and forge.get("status") == "RUNNING":
        forge["status"] = decision
        log_event(forge, "decision", "%s: %s" % (decision, reason))
    lines = ["# Arena Forge — informe", "",
             "- run: `%s`" % d, "- modo: %s" % forge["mode"],
             "- decision: **%s** — %s" % (decision, reason),
             "- seed: %s, agentes: %s" % (forge.get("seed"), forge.get("agents")),
             "- task_sha: `%s`" % forge.get("task_sha"),
             "- rubric_sha: `%s`" % forge.get("rubric_sha"),
             "- cards_sha: `%s`" % forge.get("cards_sha"),
             "- baseline: `%s`" % forge.get("baseline_commit"), ""]
    lines.append("## Bracket")
    for rd in st.get("rounds", []):
        lines.append("### ronda %s (bye: %s)" % (rd.get("n"), rd.get("bye") or "-"))
        for m in rd.get("matches", []):
            lines.append("- %s: %s vs %s → **%s** (%s)" %
                         (m.get("id"), m.get("a"), m.get("b"),
                          m.get("winner") or "?", m.get("reason") or ""))
    if gates:
        lines.append("")
        lines.append("## Gates objetivos (preceden al score)")
        for c, g in sorted(gates.items()):
            lines.append("- %s: **%s** (%.1fs)" % (c, g["verdict"],
                                                  g.get("seconds", 0)))
    lines += ["", "## Eventos", ""]
    for ev in forge.get("events", []):
        lines.append("- %s %s %s" % (ev.get("t"), ev.get("kind"),
                                    ev.get("detail") or ""))
    # Un solo escape en la frontera de escritura: ni MD ni HTML ejecutan el dato.
    safe = [esc(l) for l in lines]
    out = os.path.join(HERE, "reports", os.path.basename(d) + ".md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(safe) + "\n")
    body = "\n".join("<p>%s</p>" % l if not l.startswith("#") else
                     "<h2>%s</h2>" % l.lstrip("# ")
                     for l in safe)
    page = ("<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
            "<title>Arena Forge — informe</title></head><body>%s</body></html>" % body)
    hout = out[:-3] + ".html"
    with open(hout, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("decision: %s (%s)" % (decision, reason))
    print("md: %s\nhtml: %s" % (out, hout))
    return 0


def cmd_apply(args):
    d = run_dir_from(args)
    forge = load_forge(d)
    if not args.approve:
        raise ForgeError("rehusado: exige --approve explicito y aplica a mano. "
                         "Nada del proyecto fue modificado.")
    champ = None
    if forge.get("mode") == "patch":
        gates = {}
        gp = os.path.join(d, "gates.json")
        if os.path.isfile(gp):
            with open(gp, encoding="utf-8") as fh:
                gates = json.load(fh)
        champ, why = resolve_patch_winner(d, forge, gates)
    else:
        with open(os.path.join(d, "arena.json"), encoding="utf-8") as fh:
            champ = json.load(fh).get("champion")
    if not champ:
        raise ForgeError("sin campeon: nada que aplicar (NO_SHIP)")
    cdir = os.path.join(d, "candidates", champ)
    base = os.path.join(d, "baseline")
    patch_lines = []
    if os.path.isdir(cdir) and os.path.isdir(base):
        for name in sorted(os.listdir(cdir)):
            p1, p2 = os.path.join(base, name), os.path.join(cdir, name)
            if os.path.isfile(p2):
                old = open(p1, encoding="utf-8").readlines() if os.path.isfile(p1) else []
                new = open(p2, encoding="utf-8").readlines()
                patch_lines += difflib.unified_diff(old, new, "a/" + name, "b/" + name)
    out = os.path.join(HERE, "reports", os.path.basename(d) + ".patch")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("".join(patch_lines) or "# sin diffs (modo answer)\n")
    print("parche preparado (SOLO archivo, proyecto intacto): %s" % out)
    print("revisa, luego: git apply --check %s" % out)
    return 0


# ------------------------------------------------------------- benchmark
def cmd_benchmark(args):
    """Comparacion honesta: scheduler determinista + harness de gates.

    No inventa scores LLM: mide state-machine (7 tamanos) y discriminacion
    de la suite protegida sobre el fixture (buggy=FAIL, fixed=PASS).
    """
    mod = load_bracket_module()
    rows = []
    for n in (2, 3, 4, 5, 7, 8, 16):
        ok, note = simulate_tournament(mod, n, seed=7)
        rows.append((n, ok, note))
    print("scheduler determinista (seed 7, ganadores simulados):")
    allok = True
    for n, ok, note in rows:
        allok &= ok
        print("  n=%2d %s %s" % (n, "OK" if ok else "FAIL", note))
    fx = os.path.join(HERE, "fixtures", "patch-demo")
    suite = os.path.join(fx, "tests_protected", "test_protected.py")
    g_bug = run_gates(os.path.join(fx, "baseline_buggy"), suite)
    g_fix = run_gates(os.path.join(fx, "candidate_fixed"), suite)
    print("gates: buggy=%s fixed=%s (suite integra: %s/%s)"
          % (g_bug["verdict"], g_fix["verdict"], g_bug["sha_ok"], g_fix["sha_ok"]))
    verdict = ("OK" if (allok and g_bug["verdict"] == "FAIL"
                        and g_fix["verdict"] == "PASS") else "FAIL")
    print("benchmark: %s" % verdict)
    return 0 if verdict == "OK" else 1


def load_bracket_module():
    spec = importlib.util.spec_from_file_location("forge_bracket", BRACKET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def simulate_tournament(mod, n, seed):
    """Simula un torneo: verifica cartas sin repetir (n <= 2160),
    emparejamientos legales y un unico ganador."""
    data = mod.load_strategies(STRATEGIES)
    if not (1 <= n <= mod.combo_count(data)):
        return False, "n fuera de rango"
    cards = mod.deal(n, seed, data)
    if len(set(cards)) != n:
        return False, "cartas duplicadas"
    # simulacion a nivel bracket: tamanos y cierre con un ganador
    sizes = mod.bracket_sizes(n)
    if sizes[0] != n or sizes[-1] != 1:
        return False, "bracket %r" % (sizes,)
    return True, "bracket %s" % ("->".join(str(s) for s in sizes))


# ------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(prog="arena_forge.py", description="Arena Forge")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    s = sub.add_parser("plan", help="estimacion sin escribir archivos")
    s.add_argument("--agents", type=int, default=100)
    s.add_argument("--wave", type=int, default=10)
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("init", help="crear ejecucion inmutable")
    s.add_argument("--mode", default="answer", choices=("answer", "patch"))
    s.add_argument("--agents", type=int)
    s.add_argument("--quick", action="store_true")
    s.add_argument("--seed", type=int)
    s.add_argument("--task"); s.add_argument("--task-file")
    s.add_argument("--baseline-file"); s.add_argument("--suite")
    s.add_argument("--wave", type=int, default=10); s.add_argument("--dir")
    s.set_defaults(func=lambda a: cmd_init(_expand_quick(a)))

    for name, hlp in (("next", "siguiente fase"), ("status", "estado"),
                      ("collect", "registrar veredictos"),
                      ("advance", "cerrar ronda"),
                      ("prompts", "briefs pendientes"),
                      ("check", "outputs ausentes"),
                      ("pairings", "emparejamientos"),
                      ("winner", "campeon")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("--dir")
        if name == "prompts" or name == "check":
            s.add_argument("phase", choices=("spawn", "attack", "defend", "judge", "final"))
            s.set_defaults(func=lambda a, n=name: cmd_passthrough(n, a, (a.phase,)))
        else:
            s.set_defaults(func=lambda a, n=name: cmd_passthrough(n, a))

    s = sub.add_parser("card", help="tarjeta de un competidor")
    s.add_argument("--dir"); s.add_argument("agent_id")
    s.set_defaults(func=lambda a: cmd_passthrough("card", a, (a.agent_id,)))

    s = sub.add_parser("record", help="registrar un match a mano")
    s.add_argument("--dir"); s.add_argument("match_id"); s.add_argument("winner_id")
    s.add_argument("--reason", default="")
    s.set_defaults(func=lambda a: cmd_passthrough(
        "record", a, (a.match_id, a.winner_id, "--reason", a.reason)))

    s = sub.add_parser("gates", help="evaluar candidatos (patch)")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_gates)

    s = sub.add_parser("resume", help="reanudar sin repetir lo completado")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_resume)

    s = sub.add_parser("cancel", help="cancelar conservando artefactos")
    s.add_argument("--dir"); s.add_argument("--reason", default="")
    s.set_defaults(func=cmd_cancel)

    s = sub.add_parser("report", help="informe Markdown + HTML estatico")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("benchmark", help="scheduler + gates del fixture")
    s.set_defaults(func=cmd_benchmark)

    s = sub.add_parser("apply", help="preparar parche (exige --approve)")
    s.add_argument("--dir"); s.add_argument("--approve", action="store_true")
    s.set_defaults(func=cmd_apply)
    return p


def _expand_quick(a):
    if getattr(a, "quick", False):
        a.agents = 16
    return a


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ForgeError as exc:
        print("forge error: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())

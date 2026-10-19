"""Report Generator (§3.16, §15).

Genera Markdown + HTML estatico autocontenido. El HTML escapa TODO contenido
externo y no ejecuta scripts, URLs activas ni HTML embebido de candidatos.
Muestra fallos y herramientas NOT_RUN; no esconde nada tras un score global.
"""
import html
import json
import os

from . import ledger, score as score_mod, state
from .util import ForgeError, now_ts, sha_file


def _load(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return None


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def gather(run_dir):
    run = _load(os.path.join(run_dir, "forge.json")) or {}
    arena = _load(os.path.join(run_dir, "arena.json")) or {}
    gates = _load(os.path.join(run_dir, "gates.json")) or {}
    patch_judge = _load(os.path.join(run_dir, "patch_judge.json"))
    label_map = _load(os.path.join(run_dir, "patch_map.json")) or {"X": None, "Y": None}
    isolation = _load(os.path.join(run_dir, "isolation.json"))
    decisions = []
    dpath = os.path.join(run_dir, "decisions.jsonl")
    if os.path.isfile(dpath):
        with open(dpath, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    decisions.append(json.loads(line))
    return {
        "run": run, "arena": arena, "gates": gates, "patch_judge": patch_judge,
        "label_map": label_map, "isolation": isolation, "decisions": decisions,
        "ledger": ledger.read(run_dir),
    }


def resolve(run_dir, data=None):
    """Decision explicita con razon. Gates mandan sobre cualquier score.
    
    P0-01/P0-03/P0-06: Requiere aislamiento verificado, suite hash intacto,
    y evaluaciones COMPLETAS para todos los candidatos para WINNER.
    """
    data = data or gather(run_dir)
    run = data["run"]
    gates = data["gates"]
    mode = run.get("mode", "answer")
    st = run.get("status") or run.get("phase")

    if st in ("CANCELLED", "FAILED", "BLOCKED"):
        return st, "estado terminal previo del run", []

    if mode == "patch":
        # P0-01: validar aislamiento antes de considerar elegibles
        isolation = data.get("isolation") or {}
        if not isolation.get("ok"):
            return "NO_SHIP", "aislamiento no verificado: %s" % isolation.get("problems", ["unknown"]), []
        
        # P0-03: validar integridad de suite contra hash congelado
        expected_suite_sha = run.get("suite_sha")
        if not expected_suite_sha:
            return "NO_SHIP", "suite_sha congelado ausente en run", []
        # Validar formato SHA256 (64 chars hex)
        if not isinstance(expected_suite_sha, str) or len(expected_suite_sha) != 64 or not all(c in "0123456789abcdef" for c in expected_suite_sha):
            return "NO_SHIP", "suite_sha congelado malformado: %s" % expected_suite_sha, []
        
        # P0-A.1: IDs de gates deben coincidir EXACTAMENTE con candidatos registrados
        expected_candidates = list(run.get("candidates", {}).keys())
        if not expected_candidates:
            return "NO_SHIP", "sin candidatos en el run", []
        
        gate_ids = set(gates.keys())
        expected_ids = set(expected_candidates)
        if gate_ids != expected_ids:
            extra = gate_ids - expected_ids
            missing = expected_ids - gate_ids
            problems = []
            if extra:
                problems.append("IDs extra en gates: %s" % ", ".join(sorted(extra)))
            if missing:
                problems.append("candidatos sin GateResult: %s" % ", ".join(sorted(missing)))
            return "NO_SHIP", "IDs de gates no coinciden con candidatos: %s" % "; ".join(problems), []
        
        # P0-03: validar integridad de suite contra hash congelado
        for cid in expected_candidates:
            g = gates.get(cid, {})
            g_sha = g.get("suite_sha")
            if expected_suite_sha and g_sha != expected_suite_sha:
                return "NO_SHIP", ("suite hash mismatch para %s: gate=%s run=%s" %
                                  (cid, g_sha, expected_suite_sha)), []
        
        # P0-06: requerir evaluaciones COMPLETAS para todos los candidatos
        # Verificar que TODOS los candidatos esperados tienen GateResult
        missing = [c for c in expected_candidates if c not in gates]
        if missing:
            return "NO_SHIP", ("faltan GateResult para candidatos: %s" % ", ".join(missing)), []
        
        # Verificar que cada resultado es conclusivo (no NOT_RUN, BLOCKED, INCONCLUSIVE)
        # y que suite hash e aislamiento son válidos
        for cid in expected_candidates:
            g = gates.get(cid, {})
            state = g.get("state")
            if state in ("NOT_RUN", "BLOCKED", "INCONCLUSIVE", None):
                return "NO_SHIP", ("candidato %s tiene resultado inconcluso: %s" %
                                  (cid, state)), []
            g_sha = g.get("suite_sha")
            if expected_suite_sha and g_sha != expected_suite_sha:
                return "NO_SHIP", ("suite hash mismatch para %s: gate=%s run=%s" %
                                  (cid, g_sha, expected_suite_sha)), []
            # aislamiento ya validado arriba para todos
        
        # P0-A.4: candidate_manifest_sha y diff_sha obligatorios en cada gate concluido
        # Validar formato SHA256 (64 chars hex)
        def _is_valid_sha256(val):
            return isinstance(val, str) and len(val) == 64 and all(c in "0123456789abcdef" for c in val)

        for cid in expected_candidates:
            g = gates.get(cid, {})
            if not g.get("candidate_manifest_sha"):
                return "NO_SHIP", "candidato %s sin candidate_manifest_sha en gate" % cid, []
            if not _is_valid_sha256(g.get("candidate_manifest_sha")):
                return "NO_SHIP", "candidato %s candidate_manifest_sha malformado: %s" % (cid, g.get("candidate_manifest_sha")), []
            if not g.get("diff_sha"):
                return "NO_SHIP", "candidato %s sin diff_sha en gate" % cid, []
            if not _is_valid_sha256(g.get("diff_sha")):
                return "NO_SHIP", "candidato %s diff_sha malformado: %s" % (cid, g.get("diff_sha")), []
        
        # Ahora sí: evaluar elegibilidad solo si todos están completos
        eligible = sorted(c for c in expected_candidates if gates.get(c, {}).get("state") == "PASS")
        if not gates:
            return "NO_SHIP", "sin GateResult: la evaluacion no es confiable", []
        if not eligible:
            return ("NO_SHIP", "ningun candidato supera los gates obligatorios", [])
        
        # P0-A: Validar que TODOS los candidatos tienen directorio válido y manifest coincide
        import os
        for cid in expected_candidates:
            g = gates.get(cid, {})
            cdir = os.path.join(run_dir, "candidates", cid)
            # Verificar que el directorio del candidato existe
            if not os.path.isdir(cdir):
                return "NO_SHIP", "candidato %s: directorio ausente" % cid, []
            # Verificar que el realpath está dentro del run
            real_cdir = os.path.realpath(cdir)
            run_real = os.path.realpath(run_dir)
            if not (real_cdir == run_real or real_cdir.startswith(run_real + os.sep)):
                return "NO_SHIP", "candidato %s: directorio fuera del run" % cid, []
            # Verificar manifest para TODOS los candidatos (no solo elegibles)
            saved_manifest = gates.get(cid, {}).get("candidate_manifest_sha")
            if saved_manifest:
                from .isolation import candidate_manifest_sha
                current_manifest = candidate_manifest_sha(cdir)
                if current_manifest != saved_manifest:
                    return "NO_SHIP", ("candidato %s modificado tras gate: manifest=%s gate=%s" %
                                          (cid, candidate_manifest_sha(os.path.join(run_dir, "candidates", cid)), saved_manifest)), []
        
        # P0-05: validar que el manifest del candidato no ha cambiado desde el gate
        for cid in eligible:
            g = gates.get(cid, {})
            saved_manifest = g.get("candidate_manifest_sha")
            if saved_manifest:
                import os
                cdir = os.path.join(run_dir, "candidates", cid)
                if os.path.isdir(cdir):
                    from .isolation import candidate_manifest_sha
                    current_manifest = candidate_manifest_sha(cdir)
                    if current_manifest != saved_manifest:
                        return "NO_SHIP", ("candidato %s modificado tras gate: manifest=%s gate=%s" %
                                          (cid, current_manifest, saved_manifest)), []
        
        # §6 nivel 2: el juez ciego solo compara candidatos elegibles. Si hay
        # un unico elegible, la eleccion por gates es determinista y no
        # requiere (ni puede fabricar) un veredicto de comparacion.
        if len(eligible) == 1:
            hashes = set(g.get("suite_sha") for g in gates.values())
            same_suite = "misma suite" if len(hashes) == 1 else "suite INCONSISTENTE"
            return "WINNER", (
                "%s unico elegible (todas las gates PASS, %s, suite_sha=%s)"
                % (eligible[0], same_suite, list(hashes)[0])), eligible
        cand, info = score_mod.evaluate_patch_judgement(
            data["patch_judge"] or {}, eligible, data["label_map"])
        if cand:
            return "WINNER", "%s gana (gates PASS + juez ciego: %s)" % (
                cand, info.get("reason", "")), eligible
        return "NO_SHIP", info.get("reason", "sin desempate valido"), eligible

    # answer
    champ = data["arena"].get("champion")
    if champ:
        return "WINNER", "campeon del bracket answer: %s" % champ, []
    return "NO_SHIP", "sin campeon (torneo incompleto o cancelado)", []


def render_markdown(run_dir, data, decision, reason, eligible):
    run = data["run"]
    lines = []
    lines.append("<!-- Arena Forge — informe generado por forge.report -->")
    lines.append("# Arena Forge — informe")
    lines.append("")
    lines.append("| Campo | Valor |")
    lines.append("|---|---|")
    lines.append("| run_id | `%s` |" % run.get("run_id"))
    lines.append("| modo | %s |" % run.get("mode"))
    lines.append("| estado | %s |" % (run.get("phase") or run.get("status")))
    lines.append("| decision | **%s** |" % decision)
    lines.append("| razon | %s |" % reason)
    lines.append("| schema_version | %s |" % run.get("schema_version"))
    lines.append("| policy_version | %s |" % run.get("policy_version"))
    lines.append("| seed | %s |" % run.get("seed"))
    lines.append("| creado | %s |" % run.get("created"))
    lines.append("| task_sha | `%s` |" % run.get("task_sha"))
    lines.append("| rubric_sha | `%s` |" % run.get("rubric_sha"))
    lines.append("| cards_sha | `%s` |" % run.get("cards_sha"))
    lines.append("| suite_sha | `%s` |" % (run.get("suite_sha") or "-"))
    lines.append("| baseline | `%s` |" % (run.get("baseline_ref") or
                                          run.get("baseline_commit")))
    lines.append("")

    # Tarea y alcance
    lines.append("## Tarea y alcance")
    task = run.get("task")
    if task:
        lines.append("```text")
        lines.append(str(task))
        lines.append("```")
    lines.append("- alcance: %s" % (run.get("scope") or "no declarado"))
    lines.append("- no objetivos: %s" % (run.get("non_goals") or "no declarados"))
    lines.append("")

    # Candidatos
    lines.append("## Candidatos")
    lines.append("| candidato | estrategia | elegible | isolation | gates |")
    lines.append("|---|---|---|---|---|")
    cands = data.get("candidates") or {}
    for cid in sorted(set(list(cands.keys()) + list(data["gates"].keys()))):
        c = cands.get(cid, {})
        g = data["gates"].get(cid, {})
        lines.append("| %s | %s | %s | %s | %s |" % (
            cid, c.get("strategy_id", "-"), c.get("eligible", "-"),
            c.get("isolation_verified", "-"), g.get("state", "NOT_RUN")))
    lines.append("")

    # Bracket
    lines.append("## Bracket")
    rounds = data["arena"].get("rounds", [])
    if not rounds:
        lines.append("_modo patch o sin bracket answer_")
    for rd in rounds:
        lines.append("### Ronda %s (bye: %s)" % (rd.get("n"), rd.get("bye") or "-"))
        for m in rd.get("matches", []):
            lines.append("- %s: %s vs %s -> **%s** (%s)" % (
                m.get("id"), m.get("a"), m.get("b"),
                m.get("winner") or "?", m.get("reason") or ""))
    lines.append("")

    # Gates con evidencia
    lines.append("## Gates objetivos (preceden al score)")
    if not data["gates"]:
        lines.append("_sin gates ejecutados (NOT_RUN)_")
    for cid, g in sorted(data["gates"].items()):
        lines.append("- **%s**: %s (exit=%s, suite_sha=%s, %ss)" % (
            cid, g.get("state"), g.get("exit_code"),
            (g.get("suite_sha") or "")[:12], g.get("seconds", "")))
        if g.get("failure_class"):
            lines.append("  - clase de fallo: %s" % g["failure_class"])
        for e in g.get("evidence", [])[:4]:
            lines.append("  - evidencia: `%s`" % e)
    lines.append("")

    # Scores por dimension
    pj = data["patch_judge"]
    if pj:
        lines.append("## Juicio cualitativo (ciego)")
        lines.append("- ganador ciego: %s" % pj.get("winner"))
        lines.append("- scores: %s" % json.dumps(pj.get("scores", {})))
        lines.append("- razon: %s" % pj.get("reason"))
        for ev in pj.get("evidence", []):
            lines.append("  - evidencia: %s" % ev)
        if pj.get("dimensions"):
            lines.append("- dimensiones: %s" % json.dumps(pj["dimensions"]))
        lines.append("")

    # E
    if data["decisions"]:
        lines.append("## Decisiones de E")
        for d in data["decisions"][-10:]:
            lines.append("- %s [%s] %s (riesgo %s, humano=%s)" % (
                d.get("action_type"), d.get("decision_id"), d.get("reason"),
                d.get("risk_level"), d.get("requires_human_approval")))
        lines.append("")

    # Reanudacion / eventos
    lines.append("## Eventos (ledger append-only)")
    for ev in data["ledger"][-25:]:
        lines.append("- #%s %s %s %s" % (ev.get("seq"), ev.get("ts"),
                                         ev.get("kind"), ev.get("detail")))
    lines.append("")

    # Limites, no medido, riesgos
    lines.append("## Limites, herramientas no ejecutadas y riesgos")
    lines.append("- presupuesto: %s" % json.dumps(run.get("budget", {})))
    lines.append("- coste observado (llamadas): %s" % run.get("calls_spent", "no medido"))
    lines.append("- herramientas NOT_RUN: %s" % (run.get("not_run") or
                                                 "semgrep (no instalado)"))
    lines.append("- riesgos residuales: shell del juez acotado por brief; "
                 "modelo no determinista; coste monetario no medible por API")
    lines.append("- baseline comparativo: %s" % (run.get("baseline_note") or
                                                 "declarado no demostrado (benchmark)"))
    lines.append("")
    lines.append("> Generado %s. Seed fija scheduler/tarjetas/bracket; NO las "
                 "respuestas del modelo." % now_ts())
    return "\n".join(lines) + "\n"


def render_html(run_dir, data, decision, reason, eligible):
    run = data["run"]
    md = render_markdown(run_dir, data, decision, reason, eligible)
    # CSS minimo, autocontenido, sin recursos externos.
    css = (
        "body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:2rem;"
        "background:#0f1115;color:#e6e6e6;line-height:1.5}"
        "h1,h2{color:#7fd1ff}h3{color:#b6e3ff}"
        ".banner{padding:1rem;border-radius:8px;margin:1rem 0;font-weight:600}"
        ".ok{background:#12351f;border:1px solid #2e7d4f}"
        ".bad{background:#3a1414;border:1px solid #a33}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0}"
        "th,td{border:1px solid #333;padding:.35rem .6rem;text-align:left}"
        "code{background:#1a1d23;padding:.1rem .3rem;border-radius:4px}"
        "pre{background:#1a1d23;padding:1rem;overflow:auto;border-radius:8px}"
        ".muted{color:#888}")
    banner_cls = "ok" if decision == "WINNER" else "bad"
    body = _md_to_html(md)
    page = (
        "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Arena Forge — %s</title><style>%s</style></head><body>"
        "<div class='banner %s'>Decision: %s — %s</div>%s</body></html>"
        % (esc(run.get("run_id")), css, banner_cls, esc(decision),
           esc(reason), body))
    return page


def _md_to_html(md):
    """Conversor minimo y seguro: todo el texto se escapa primero."""
    out = []
    in_table = False
    in_pre = False
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            out.append("</pre>" if in_pre else "<pre>")
            in_pre = not in_pre
            continue
        if in_pre:
            out.append(esc(line))
            continue
        if line.startswith("| "):
            cells = [esc(c.strip()) for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if not in_table:
                out.append("<table><tr>" + "".join(
                    "<th>%s</th>" % c for c in cells) + "</tr>")
                in_table = True
            else:
                out.append("<tr>" + "".join("<td>%s</td>" % c for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if line.startswith("### "):
            out.append("<h3>%s</h3>" % esc(line[4:]))
        elif line.startswith("## "):
            out.append("<h2>%s</h2>" % esc(line[3:]))
        elif line.startswith("# "):
            out.append("<h1>%s</h1>" % esc(line[2:]))
        elif line.startswith("- "):
            out.append("<li>%s</li>" % esc(line[2:]))
        elif line.startswith("> "):
            out.append("<p class='muted'>%s</p>" % esc(line[2:]))
        elif line.strip() == "":
            out.append("")
        else:
            out.append("<p>%s</p>" % esc(line))
    if in_table:
        out.append("</table>")
    if in_pre:
        out.append("</pre>")
    return "\n".join(out)


def write(run_dir, reports_dir, data=None, decision=None):
    data = data or gather(run_dir)
    if decision is None:
        decision, reason, eligible = resolve(run_dir, data)
    else:
        _, reason, eligible = resolve(run_dir, data)
    md = render_markdown(run_dir, data, decision, reason, eligible)
    html_text = render_html(run_dir, data, decision, reason, eligible)
    os.makedirs(reports_dir, exist_ok=True)
    base = os.path.basename(os.path.normpath(run_dir))
    md_path = os.path.join(reports_dir, base + ".md")
    html_path = os.path.join(reports_dir, base + ".html")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html_text)
    return {"decision": decision, "reason": reason, "md": md_path,
            "html": html_path, "eligible": eligible}

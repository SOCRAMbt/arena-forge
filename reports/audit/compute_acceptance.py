"""Genera la matriz de aceptacion (y la de trazabilidad §21) desde acceptance-data.json.

El .md es GENERADO: si los datos cambian, el texto cambia. Asi no puede volver a
desincronizarse del calculo (que fue exactamente el defecto que encontro la
revision de documentacion).

Uso:
    python reports/audit/compute_acceptance.py            # recuento + areas
    python reports/audit/compute_acceptance.py --write    # regenera el .md
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "acceptance-data.json")
MATRIX = os.path.join(HERE, "acceptance-matrix.md")

WEIGHT = {"PASS": 1.0, "PARTIAL": 0.5, "FAIL": 0.0,
          "BLOCKED": 0.0, "NOT_RUN": 0.0, "INCONCLUSIVE": 0.0}
ORDER = ("PASS", "PARTIAL", "FAIL", "BLOCKED", "NOT_RUN", "INCONCLUSIVE")


def load():
    with open(DATA, encoding="utf-8") as fh:
        return json.load(fh)


def compute(data):
    crit = data["criteria"]
    areas = data["areas"]
    total = len(crit)
    counts = {s: 0 for s in ORDER}
    for c in crit:
        counts[c["state"]] = counts.get(c["state"], 0) + 1
    weighted = sum(WEIGHT.get(c["state"], 0.0) for c in crit) / total
    area_rows = []
    global_contrib = 0.0
    for area, spec in sorted(areas.items(), key=lambda kv: -kv[1]["weight"]):
        members = [c for c in crit if c["area"] == area]
        if not members:
            continue
        w = spec["weight"]
        if w <= 0:
            area_rows.append((area, w, len(members), None, 0.0, spec["description"]))
            continue
        aw = sum(WEIGHT.get(c["state"], 0.0) for c in members) / len(members)
        contrib = w * aw
        global_contrib += contrib
        area_rows.append((area, w, len(members), aw, contrib, spec["description"]))
    return counts, total, weighted, area_rows, global_contrib


def render(data):
    counts, total, weighted, area_rows, global_contrib = compute(data)
    L = []
    A = L.append
    A("# Matriz de aceptacion — AF-AC-001..018")
    A("")
    A("> **GENERADO POR CODIGO.** No editar a mano: la fuente de verdad es")
    A("> [`acceptance-data.json`](acceptance-data.json) y el calculo lo hace")
    A("> [`compute_acceptance.py`](compute_acceptance.py). Regenerar con:")
    A("> `python reports/audit/compute_acceptance.py --write`")
    A("")
    A("**Contrato de referencia:** `%s`" % data.get("contract", ""))
    A("")
    A("**Leyenda de estados (estricta):** `PASS` · `PARTIAL` · `FAIL` · "
      "`BLOCKED` · `NOT_RUN` · `INCONCLUSIVE`.")
    A("Un `PARTIAL` **no** es un `PASS` con notas: significa que el criterio se "
      "cumple en parte y se documenta exactamente lo que falta.")
    A("")
    A("## Recuento")
    A("")
    A("| Estado | Recuento | % |")
    A("|---|---|---|")
    for s in ORDER:
        A("| %s | %d | %.1f %% |" % (s, counts[s], 100.0 * counts[s] / total))
    A("| **Total** | %d | 100.0 %% |" % total)
    A("")
    A("**Equivalente ponderado** (PASS=1, PARTIAL=0.5, resto=0): **%.1f %%**"
      % (100 * weighted))
    A("")
    A("> **El porcentaje NO anula un gate P0.** Si hay un criterio en `FAIL` o "
      "`BLOCKED`, el veredicto global no es COMPLETE por muy alto que sea el "
      "numero.")
    A("")
    A("## Por area (pesos declarados)")
    A("")
    A("| Area | Peso | Criterios | Ponderado | Contribucion |")
    A("|---|---|---|---|---|")
    for area, w, n, aw, contrib, _d in area_rows:
        if aw is None:
            A("| %s | %3.0f %% | %d | (sin peso: no medido) | 0.00 |"
              % (area, w * 100, n))
        else:
            A("| %s | %3.0f %% | %d | %.1f %% | %.2f |" % (area, w * 100, n,
                                                        100 * aw, contrib))
    A("| **GLOBAL** | 100 pct | %d | — | **%.2f** |" % (total, global_contrib))
    A("")
    A("Particion de los %d criterios (sin solapes):" % total)
    A("")
    for area, w, n, aw, contrib, desc in area_rows:
        members = [c["id"] for c in data["criteria"] if c["area"] == area]
        A("- **%s** (%.0f %%): %s" % (area, w * 100, ", ".join(members)))
    A("")
    A("## Criterios")
    A("")
    for c in data["criteria"]:
        A("### %s — %s" % (c["id"], c["state"]))
        A("")
        A("> %s" % c["text"])
        A("")
        A("**Evidencia:** %s" % c["evidence"])
        A("")
    if data.get("traceability"):
        A("## Matriz de trazabilidad minima (§21)")
        A("")
        A("| ID | Requisito | Evidencia minima |")
        A("|---|---|---|")
        for t in data["traceability"]:
            A("| %s | %s | %s |" % (t["id"], t["requirement"], t["evidence"]))
        A("")
    A("## Bloqueos que condicionan la certificacion")
    A("")
    A("- **Contrato ausente:** cerrado. El contrato esta versionado en "
      "`docs/contract/` (SHA-256 registrado en `docs/contract/SHA256SUMS.txt`).")
    A("- **Sin frontera de sistema operativo:** abierto. No hay Job Object, "
      "AppContainer, usuario de minimos privilegios ni red bloqueada. El modo "
      "`TRUSTED_CODE_ONLY` esta declarado en el codigo, en cada `GateResult`, "
      "en `verify` y en la salida de `apply`. El contrato lo admite en AF-AC-006 "
      "(\"modo declarado bloqueado y no anunciado como operativo\").")
    A("- **Tercero independiente:** abierto. §23 exige que un tercero reproduzca "
      "la demo desde checkout limpio; el coordinador no puede ser la unica "
      "autoridad que certifica su propio exito.")
    A("")
    return "\n".join(L) + "\n"


def main():
    data = load()
    counts, total, weighted, area_rows, global_contrib = compute(data)
    if "--write" in sys.argv:
        text = render(data)
        with open(MATRIX, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("escrito %s" % MATRIX)
        return 0
    print("== RECUENTOS (total %d) ==" % total)
    for s in ORDER:
        print("  %-12s %2d   %5.1f %%" % (s, counts[s], 100.0 * counts[s] / total))
    print("  PONDERADO GLOBAL (PASS=1, PARTIAL=0.5, resto=0): %.1f %%" % (100 * weighted))
    print("\n== POR AREA ==")
    for area, w, n, aw, contrib, _d in area_rows:
        if aw is None:
            print("  %-14s peso %3.0f%%  (sin peso: no medido)" % (area, w * 100))
        else:
            print("  %-14s peso %3.0f%%  %d criterios  ponderado %5.1f %%  "
                  "contribucion %5.2f" % (area, w * 100, n, 100 * aw, contrib))
    print("  GLOBAL (suma de contribuciones): %.1f %%" % (100 * global_contrib))
    return 0


if __name__ == "__main__":
    sys.exit(main())

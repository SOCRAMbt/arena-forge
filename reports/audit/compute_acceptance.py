"""Calcula la matriz de aceptacion desde acceptance-data.json.

Uso:
    python reports/audit/compute_acceptance.py

Salida:
    - los recuentos por estado,
    - el porcentaje ponderado global,
    - la tabla por area con pesos,
    - el texto listo para pegar en acceptance-matrix.md y final-audit.md.

El calculo NO esta a ojo: se ejecuta. Los .md citan estos numeros.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "acceptance-data.json")

WEIGHT = {"PASS": 1.0, "PARTIAL": 0.5, "FAIL": 0.0,
          "BLOCKED": 0.0, "NOT_RUN": 0.0, "INCONCLUSIVE": 0.0}
ORDER = ("PASS", "PARTIAL", "FAIL", "BLOCKED", "NOT_RUN", "INCONCLUSIVE")


def main():
    with open(DATA, encoding="utf-8") as fh:
        data = json.load(fh)
    crit = data["criteria"]
    areas = data["areas"]
    total = len(crit)

    counts = {s: 0 for s in ORDER}
    for c in crit:
        counts[c["state"]] = counts.get(c["state"], 0) + 1

    print("== RECUENTOS (total %d) ==" % total)
    for s in ORDER:
        print("  %-12s %2d   %5.1f %%" % (s, counts[s], 100.0 * counts[s] / total))

    weighted = sum(WEIGHT.get(c["state"], 0.0) for c in crit) / total
    print("  PONDERADO GLOBAL (PASS=1, PARTIAL=0.5, resto=0): %.1f %%" % (100 * weighted))

    print("\n== POR AREA ==")
    global_contrib = 0.0
    for area, spec in sorted(areas.items(),
                             key=lambda kv: -kv[1]["weight"]):
        members = [c for c in crit if c["area"] == area]
        if not members:
            continue
        w = spec["weight"]
        if w <= 0:
            print("  %-14s peso %3.0f%%  (sin peso: no medido)" % (area, w * 100))
            continue
        aw = sum(WEIGHT.get(c["state"], 0.0) for c in members) / len(members)
        contrib = w * aw
        global_contrib += contrib
        detail = ", ".join("%s=%s" % (c["id"].replace("AF-AC-", ""), c["state"])
                           for c in members)
        print("  %-14s peso %3.0f%%  %d/%d criterios  ponderado %5.1f %%  "
              "contribucion %5.2f   [%s]"
              % (area, w * 100, len(members), total, 100 * aw, contrib, detail))
    print("  GLOBAL (suma de contribuciones): %.1f %%" % (100 * global_contrib))

    print("\n== MATRIZ ==")
    for c in crit:
        print("  %-11s %-8s %-14s %s" % (c["id"], c["state"], c["area"],
                                          c["evidence"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

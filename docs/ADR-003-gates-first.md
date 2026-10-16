# ADR-003 — Gates objetivos antes que score; NO_SHIP

Fecha: 2026-10-16. Estado: aceptado (demostrado: buggy=FAIL→NO_SHIP).

- La suite protegida vive fuera de `candidates/`, se ejecuta en scratch limpio
  por copia, con SHA antes/después. Contaminación → BLOCKED.
- `resolve_patch_winner()`: solo elegibles PASS + juez ciego X/Y con
  `patch_map.json`. Un juez no puede rehabilitar un FAIL (test dedicado).
- Sin elegibles, veredicto inválido o empate sin desempate → `NO_SHIP`.
- Rúbrica patch: 35/20/15/10/10/10, congelada por run.

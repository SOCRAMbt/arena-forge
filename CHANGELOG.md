# CHANGELOG

## 0.2.0 — 2026-10-16

- Patch Arena con ciclo adversarial completo: ataques solo-lectura al rival,
  defensas con concede/rebut y revisión versionada (v1 preservada), re-gates
  y juez ciego sobre v2 (90–84 con evidencia por línea).
- README profesional con evidencia real, `demo/` con los 3 informes.
- `resolve_patch_winner()` compartido por `report` y `apply`.

## 0.1.0 — 2026-10-16

- Motor `arena_forge.py`: modos answer/patch, 15 comandos
  (plan/init/next/prompts/check/pairings/collect/record/advance/status/winner/
  card + gates/resume/cancel/report/benchmark/apply).
- `bracket.py` vendored con patch OpenCode mínimo (atribución en
  `THIRD_PARTY_NOTICES.md`).
- Gates objetivos en scratch con SHA de suite; `NO_SHIP` real; juez ciego X/Y.
- Informe Markdown + HTML estático con escape verificado.
- Skill `.opencode/skills/arena-forge` + 4 agentes mínimos.
- Suite: 9 tests (scheduler, CLI, cancel, quarantine, gates, injection inerte,
  escape, NO_SHIP, gates-vetan-juez). E2E Answer 4→1 y Patch 2 candidatos reales.
- Bugs encontrados por tests/E2E y corregidos: doble escape en informe,
  `gates` listaba el run, `SKILL.md` ausente en vendor, `apply` sin ganador patch.

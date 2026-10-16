# ADR-001 — Reutilizar `bracket.py` vendored, no reescribir

Fecha: 2026-10-16. Estado: aceptado.

Contexto: el upstream trae state machine probada (tests de torneo completo),
reparto equilibrado sin repetición, olas, recuperación y aritmética separada
del juez.

Decisión: vendorizar en `vendor/arena-skill/` con atribución MIT, commit y
SHA-256 (`THIRD_PARTY_NOTICES.md`). Patch mínimo OpenCode/Windows: `python`
en `_cmd`, mensaje de `subagent`, docstring, `subagent` en textos. Cero cambios
en scheduler, reparto, emparejamientos, rúbrica y aritmética.

Consecuencia: `SKILL.md` también se vendoriza (las plantillas viven ahí y
`load_templates()` las exige); el hallazgo quedó registrado al fallar `prompts`
sin él.

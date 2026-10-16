# ADR-002 — Integración OpenCode V2 real

Fecha: 2026-10-16. Estado: aceptado (verificado en E2E con 23 llamadas).

- Competidores/atacantes/defensores/jueces: tool `subagent`, `agent: general`
  (amplio acceso, sin anidado: profundidad 1, ideal para briefs autocontenidos).
  `explore` prohibido para competir (read-only, verificado en docs).
- Olas: una ola por turno en foreground, `--wave` configurable (default 10).
- Comandos: `/arena` global existente + skill `arena-forge` del repo.
- Permisos V2 `{action, resource, effect}`: perfiles mínimos en
  `.opencode/agents/` (scout sin edit/shell; reviewer/judge edit solo `.arena/**`).
- Sin `Agent`/`Task`/`subagent_type`/`run_in_background` en ningún brief activo.

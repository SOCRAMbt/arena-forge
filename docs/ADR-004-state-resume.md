# ADR-004 — Estado en disco, reanudación y exclusión mutua

Fecha: 2026-10-16. Estado: aceptado (verificado: `resume` conserva 3/3 matches).

- Todo en `.arena/<run>/`: `arena.json` + `forge.json` v1 + `LATEST`.
  Escritura atómica (tmp+replace). Eventos append-only en `forge.json`.
- `resume` = inventario de completados + `next`; jamás borra ni re-ejecuta.
  Compactación de contexto o cierre de terminal: continuar desde disco.
- `lock.json` (stale 300s) para `collect`/`advance`. `cancel` congela con
  artefactos y rehúsa mutaciones (verificado en tests).
- Oversize (>1MB) → `.oversize`; malformado → `.unreadable`; reintento 1 + `NO OUTPUT`.

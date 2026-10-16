# ADR-005 — Coste acotado y explícito

Fecha: 2026-10-16. Estado: aceptado.

- `plan` obligatorio antes de gastar: llamadas, olas, rondas.
- Límites: `--agents`, `--wave`, 1 reintento por job, timeout 120s en gates.
- Patch empieza en 4–8 candidatos; `extreme` (100) exige confirmación con plan.
- Coste monetario: el proveedor no expone tokens por API → se declara no
  medible y se limita por llamadas/olas/tiempo (evidencia: `plan --json`).
- Sin escalado silencioso: todo aumento pasa por `init` explícito.

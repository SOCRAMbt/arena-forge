# ARENA FORGE — tracker vivo (v1.0 spec-compliant)

Objetivo: alinear el sistema con `ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md`
(OpenCode v2.0.32 verificada) y corroborarlo con subagentes.
Estado global: **PARTIAL → en curso**.

## Gap analysis (spec → estado)

- [x] §0-2 modos answer/patch/benchmark
- [ ] §3 componentes: Runtime Adapter, Agent E, Score Calculator, Benchmark Runner,
      Artifact Store, Policy/Budget Manager, Audit Ledger, Isolation Manager
- [ ] §4 Agente E adaptativo (decisiones estructuradas, presupuesto, hipótesis)
- [ ] §5 roles/permisos mínimos (scout/implementer/reviewer/judge ya; falta test-designer)
- [ ] §6 ciclo de vida + §8 máquina de estados formal (CREATED..COMPLETED)
- [ ] §7 CLI completo (state/ledger/decide/adapter/verify/bench)
- [ ] §9 contratos Run/Candidate/Job/GateResult/Decision + validación estricta
- [ ] §10 GateResult con clase de fallo, SCORE determinista con evidencia
- [ ] §11 threat model (existe; ampliar 16 amenazas)
- [ ] §12 presupuesto/perfiles quick|standard|extreme (+confirmación)
- [ ] §13 adapter V2 real + alternativa diffs
- [ ] §14 ledger append-only + reanudación reconciliada
- [ ] §15 informe con todos los campos obligatorios
- [ ] §16 22 pruebas obligatorias
- [ ] §17 artefactos obligatorios (más traces/matriz)
- [ ] §18 18 AC (AF-AC-001..018) con evidencia
- [ ] §21 matriz de trazabilidad ampliada
- [ ] Publicar en GitHub (approval ya dado) + rename a arena-forge

## Plan incremental (§19)

1. contratos + estado + ledger (tests primero)
2. adapter V2 (probe real) + E
3. gate engine + score determinista
4. CLI extendido + informe completo
5. tests 22 categorías + fixtures
6. docs + matriz + ADRs nuevos
7. verificación con subagentes (read-only) por AC
8. benchmark honesto (E declarado no demostrado salvo medición)

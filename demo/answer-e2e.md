# Arena Forge — E2E Answer Arena

> ⚠️ **NOT_RUN en la auditoría del 2026-10-19.**
> El E2E de Answer Arena exige **olas de subagentes reales** (una llamada de modelo por
> job). La auditoría del 2026-10-19 no ejecutó esas llamadas por coste, así que **no hay
> evidencia fresca** de un bracket completo con 4 candidatos.
> El informe antiguo que se encuentra abajo es de la versión **v1** del schema (2026-10-16)
> y **ya no es reproducible**: esos runs viven en `.arena/` (ignorado por git) y el motor
> actual resuelve esos artefactos como `NO_SHIP` por falta de `isolation.json` y por el
> schema v2.
>
> **Qué sí está probado del flujo Answer** (por unidades, sin modelo):
> `SchedulerDeterminismTest` — el bracket es determinista con el mismo seed, reparte
> tarjetas sin repetir y termina en un único ganador para n ∈ {1,2,3,4,5,7,8,13,16,25,100}.
> `ResumeCancelTest` — `resume` no reescribe `arena.json`; `cancel` congela el run con sus
> artefactos y bloquea `collect`/`gates`/`report`/`apply`/`decide`.
> `BudgetTest` — `init` valida los agentes contra el perfil y el perfil `extreme` exige
> `--confirm`.
>
> Para cerrar AF-AC-005 hace falta ejecutar una ola real y **versionar los artefactos**
> del run (hoy `.arena/` está ignorado por git y no es evidencia reproducible).

## Informe histórico (schema v1, 2026-10-16 — NO reproducible)

- run: `.arena/run-20261016-134741-s7` (artefactos locales, ignorados por git)
- modo: answer
- decision: **WINNER** — campeon del bracket answer
- seed: 7, agentes: 4
- task_sha: `5e8216ae681951fed799366ee62903560213148f1e04da3c71bab67ca112aaff`
- rubric_sha: `f9b6b15ec72f664da49a02e314dbf86a81584170ff51b26a46f07e1a29d81844`
- cards_sha: `f67f0ad305071cec7fb6162c22820e4f0046f3296dbdf80fbb6c165c87da384d`
- baseline: `n/a-no-repo`

### Bracket
### ronda 1 (bye: -)
- r1-m01: a002 vs a004 → **a002**
- r1-m02: a001 vs a003 → **a001**
### ronda 2 (bye: -)
- r2-m01: a002 vs a001 → **a002**

### Eventos
- 1792169265 init mode=answer agents=4
- 1792169324 advance rc=2
- 1792169604 collect rc=0
- 1792169606 advance rc=0
- 1792169822 collect rc=0
- 1792169824 advance rc=0
- 1792169852 decision WINNER: campeon del bracket answer

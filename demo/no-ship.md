# Arena Forge — E2E NO_SHIP (ejecutado 2026-10-19)

> ⚠️ **E2E ASISTIDO POR OPERADOR — NO AUTÓNOMO.**
> Ambos candidatos se copiaron a mano desde el fixture con el bug.
> Evidencia completa: [`reports/audit/e2e-noship.md`](../reports/audit/e2e-noship.md).

- run: `.arena/run-20261019-180429-s5` (artefactos locales, no versionados)
- modo: patch
- decision: **NO_SHIP** — `ningun candidato supera los gates obligatorios`
- `decision_id`: `dec-run-20261019-180429-s5-1`
- seed: 5, agentes: 2
- suite_sha: `19c538224e6b550760cd253dcda433a730da98760e854588e8a3aef8fc5c9570`
- baseline: **no-Git** (manifiesto de contenido versionado)
- modo de seguridad: `TRUSTED_CODE_ONLY`

## Gates objetivos (preceden al score)

| Candidato | Estado | Detalle |
|---|---|---|
| `cand-01` | **FAIL** | exit=1 |
| `cand-02` | **FAIL** | exit=1 |

Ambos candidatos son **idénticos al baseline con el bug**: ninguno puede pasar la suite.

## Intervención manual

```bat
Copy-Item fixtures\patch-demo\baseline_buggy\stats.py ...\candidates\cand-01\stats.py
Copy-Item fixtures\patch-demo\baseline_buggy\stats.py ...\candidates\cand-02\stats.py
```

## Resultado

- `winner_id` = `None`.
- `cmd_apply` aborta: `ForgeError: sin campeon: decision=NO_SHIP, ganador=None`.
- **No se generó ningún parche exportable** para este run.

La causa declarada es exactamente la esperada: `ningun candidato supera los gates
obligatorios`. Antes de la auditoría del 2026-10-19, esa rama **nunca** se alcanzaba
(el test que decía cubrirla salía antes por `suite hash mismatch`).

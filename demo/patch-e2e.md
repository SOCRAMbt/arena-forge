# Arena Forge — E2E Patch Arena (ejecutado 2026-10-19)

> ⚠️ **E2E ASISTIDO POR OPERADOR — NO AUTÓNOMO.**
> El runtime de Arena Forge **no invoca** al agente: escribe briefs y un operador (o el
> orquestador de la skill) lanza las olas de subagentes y coloca el resultado en el
> workspace del candidato. En esta ejecución **se copió a mano** el fichero corregido al
> workspace de `cand-01`. La intervención manual está marcada abajo.
> Evidencia completa: [`reports/audit/e2e-patch.md`](../reports/audit/e2e-patch.md).

- run: `.arena/run-20261019-175944-s11` (artefactos locales, no versionados)
- modo: patch
- decision: **WINNER** — `cand-01` (único elegible; todas las gates PASS, misma suite)
- `decision_id`: `dec-run-20261019-175944-s11-1`
- seed: 11, agentes: 2
- suite_sha: `19c538224e6b550760cd253dcda433a730da98760e854588e8a3aef8fc5c9570`
- baseline: **no-Git** (manifiesto de contenido versionado)
- modo de seguridad: `TRUSTED_CODE_ONLY`

## Gates objetivos (preceden al score)

| Candidato | Estado | Detalle |
|---|---|---|
| `cand-01` | **PASS** | exit=0, informe JUnit: 4 tests, 0 fallos, 0 errores |
| `cand-02` | **FAIL** | exit=1 (`required_check_failed`) |

## Intervención manual (la parte ASISTIDA)

```bat
copy fixtures\patch-demo\candidate_fixed\stats.py ^
     .arena\run-20261019-175944-s11\candidates\cand-01\stats.py
```

## Parche exportado

`sha256 = c68f82cde82f99a62b22d055be908c13fa957222114deecd589c88a7f718f59f`
(== `diff_sha` del gate de `cand-01`)

```diff
diff --git a/stats.py b/stats.py
index 6b341ea..939b73c 100644
--- a/stats.py
+++ b/stats.py
@@ -1,11 +1,11 @@
-"""Media y mediana. Bug intencional: el denominador suma 1 de mas."""
+"""Media y mediana. Version corregida (denominador exacto)."""

 def mean(xs):
     xs = list(xs)
     if not xs:
         raise ValueError("empty")
-    return sum(xs) / (len(xs) + 1)
+    return sum(xs) / len(xs)
```

`git -c core.autocrlf=false apply --check <patch>` → **exit 0** en un repositorio temporal.

## Verificación

`arena_forge.py verify --dir <run>` → **11/11 checks PASS**
(suite recalculada, baseline congelado intacto, aislamiento OK, gates preceden al score,
ganador persistido, modo de seguridad declarado).

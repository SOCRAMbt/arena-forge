# Evidencia E2E — Patch Arena (ASISTIDO, no autónomo)

**Fecha:** 2026-10-19 · **Plataforma:** Windows 11 10.0.26200-SP0 AMD64
**Python** 3.12.4 · **pytest** 9.1.1 · **Git** 2.51.0 · **OpenCode** v2.0.32
**HEAD:** `875c04ae1f7865c8043db651708d471c4a8d334e` + remediación de esta auditoría

> ⚠️ **CLASIFICACIÓN: E2E ASISTIDO POR OPERADOR.**
> El runtime de Arena Forge **no invoca** al agente: escribe briefs y un operador (o el
> orquestador de la skill) lanza las olas de subagentes y coloca el resultado en el
> workspace del candidato. En esta ejecución **un operador copió manualmente** el fichero
> corregido al workspace de `cand-01`. **No es un E2E autónomo** y no se declara como tal.
> Ver `findings.md` §RES-4.

---

## 1. `init` — creación del run

```console
$ python arena_forge.py init --mode patch --agents 2 --seed 11 \
    --task "corregir el denominador en stats.py" \
    --baseline-dir fixtures/patch-demo/baseline_buggy \
    --suite fixtures/patch-demo/tests_protected --profile quick
arena ready: C:\Users\Marcos\arena-forge\.arena\run-20261019-210128-s31
seed 11. 2 agents, 2 distinct cards dealt from 2160, no repeats.
1 rounds (2 -> 1). 7 subagent calls in 4 waves of 10.
patch: 2 workspaces aislados; aislamiento ok=True
forge: C:\Users\Marcos\arena-forge\.arena\run-20261019-210128-s31\forge.json [patch, READY]
```

**exit code: 0.** Baseline **no-Git** (fixture dentro del repo → no es su propia raíz Git →
manifiesto de contenido versionado, no el commit del repo anfitrión).

## 2. Intervención manual (la parte ASISTIDA)

```console
$ copy fixtures\patch-demo\candidate_fixed\stats.py \
      .arena\run-20261019-210128-s31\candidates\cand-01\stats.py
```

## 3. `gates` — evaluación objetiva

```console
$ python arena_forge.py gates --dir .arena\run-20261019-210128-s31
cand-01: PASS (exit=0)
cand-02: FAIL (exit=1)
```

**exit code: 0.** El veredicto se basa en el **informe JUnit** de pytest, no solo en el
código de salida (control anti-falsificación, ver `findings.md` §SEC-01).

## 4. `report` — decisión persistida

```console
$ python arena_forge.py report --dir .arena\run-20261019-210128-s31
decision: WINNER (cand-01 unico elegible (todas las gates PASS, misma suite, suite_sha=19c538224e6b550760cd253dcda433a730da98760e854588e8a3aef8fc5c9570))
elegibles: ['cand-01']
ganador: cand-01
decision_id: dec-run-20261019-210128-s31-baa077875f3ba126
md: C:\Users\Marcos\arena-forge\reports\run-20261019-210128-s31.md
html: C:\Users\Marcos\arena-forge\reports\run-20261019-210128-s31.html
```

## 5. `verify` — comprobaciones de integridad

```console
$ python arena_forge.py verify --dir .arena\run-20261019-210128-s31
verify: OK
  [PASS] adapter modo=patch: obligatorias verificadas=4/4
  [PASS] Run contract: OK
  [PASS] ledger append-only: OK
  [PASS] suite sha recalculado: suite intacta
  [PASS] suite fuera de workspaces candidatos: True
  [PASS] baseline objetivo: baseline no-Git intacto
  [PASS] baseline congelado: baseline congelado intacto
  [PASS] aislamiento: ok=True
  [PASS] gates preceden al score: decision=WINNER
  [PASS] ganador persistido=cand-01
  [PASS] modo de seguridad: TRUSTED_CODE_ONLY
```

**exit code: 0.**

## 6. `apply` — exportación del parche

```console
$ python arena_forge.py apply --dir .arena\run-20261019-210128-s31 --approve
parche preparado (SOLO archivo, proyecto intacto): C:\Users\Marcos\arena-forge\reports\run-20261019-210128-s31.patch
ganador aplicado: cand-01 (decision persistida: dec-run-20261019-210128-s31-baa077875f3ba126)
sha256 del parche exportado: c68f82cde82f99a62b22d055be908c13fa957222114deecd589c88a7f718f59f
modo de seguridad: TRUSTED_CODE_ONLY
```

**sha256 del parche exportado** = `c68f82cde82f99a62b22d055be908c13fa957222114deecd589c88a7f718f59f`
= `diff_sha` registrado en el gate de `cand-01` (verificado por
`ApplyIntegrityTest::test_exported_patch_sha_matches_the_gated_diff_sha`).

Contenido del parche (parche **Git real**, no un formato inventado):

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

## 7. `git apply --check` en un repositorio temporal

```console
$ git -C <tmp> -c core.autocrlf=false apply --check ...\reports\run-20261019-210128-s31.patch
git apply --check exit=0
```

> `core.autocrlf=false` es **necesario**: con el valor de sistema de Windows
> (`C:/Program Files/Git/etc/gitconfig` → `core.autocrlf=true`), `git apply` reescribe
> LF→CRLF y el árbol resultante deja de coincidir byte a byte con el candidato evaluado.
> Es un defecto real detectado y corregido en esta auditoría.

## 8. El árbol principal NO se modificó

`cmd_apply` solo escribe `reports/<run>.patch`. `git status --short` tras el E2E solo
muestra los cambios intencionales de la auditoría.

---

## Artefactos

| Artefacto | Ruta |
|---|---|
| Run dir | `.arena/run-20261019-210128-s31/` (ignorado por git) |
| Patch exportado | `reports/run-20261019-210128-s31.patch` |
| Informe MD/HTML | `reports/run-20261019-210128-s31.md` / `.html` |
| Decisión persistida | `.arena/run-20261019-210128-s31/decision.json` |
| Gates | `.arena/run-20261019-210128-s31/gates.json` |
| Ledger | `.arena/run-20261019-210128-s31/ledger.jsonl` |

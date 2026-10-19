# Evidencia E2E — NO_SHIP (ASISTIDO, no autónomo)

**Fecha:** 2026-10-19 · **Plataforma:** Windows 11 10.0.26200-SP0 AMD64
**Python** 3.12.4 · **pytest** 9.1.1 · **Git** 2.51.0 · **OpenCode** v2.0.32
**HEAD:** `875c04ae1f7865c8043db651708d471c4a8d334e` + remediación de esta auditoría

> ⚠️ **CLASIFICACIÓN: E2E ASISTIDO POR OPERADOR.** Ambos candidatos se copiaron a mano
> desde el fixture con el bug. No hay E2E autónomo (ver `findings.md` §RES-4).

---

## 1. `init`

```console
$ python arena_forge.py init --mode patch --agents 2 --seed 5 --task "tarea imposible" \
    --baseline-dir fixtures/patch-demo/baseline_buggy \
    --suite fixtures/patch-demo/tests_protected --profile quick
patch: 2 workspaces aislados; aislamiento ok=True
forge: C:\Users\Marcos\arena-forge\.arena\run-20261019-180429-s5\forge.json [patch, READY]
```

## 2. Intervención manual

```console
$ Copy-Item fixtures\patch-demo\baseline_buggy\stats.py ...\candidates\cand-01\stats.py
$ Copy-Item fixtures\patch-demo\baseline_buggy\stats.py ...\candidates\cand-02\stats.py
```

Ambos candidatos son **idénticos al baseline con el bug**: ninguno puede pasar la suite.

## 3. `gates` — ambos FAIL

```console
$ python arena_forge.py gates --dir .arena\run-20261019-180429-s5
cand-01: FAIL (exit=1)
cand-02: FAIL (exit=1)
```

**exit code: 0** (la ejecución de las gates fue correcta; el resultado es que fallan).

## 4. `report` — NO_SHIP con la causa declarada exacta

```console
$ python arena_forge.py report --dir .arena\run-20261019-180429-s5
decision: NO_SHIP (ningun candidato supera los gates obligatorios)
elegibles: -
ganador: -
decision_id: dec-run-20261019-180429-s5-1
md: C:\Users\Marcos\arena-forge\reports\run-20261019-180429-s5.md
html: C:\Users\Marcos\arena-forge\reports\run-20261019-180429-s5.html
```

**Causa exacta declarada:** `ningun candidato supera los gates obligatorios`.

> Antes de esta auditoría, esta rama **nunca** se alcanzaba: el test que decía cubrirla
> salía antes por `suite hash mismatch` (falso PASS). Ver
> `findings.md` §TEST-03 y `ReportTest::test_no_ship_when_every_candidate_fails_its_gate`.

## 5. No hay campeón ni parche exportable

- `winner_id` = `None` en `decision.json`.
- `cmd_apply` aborta: `ForgeError: sin campeon: decision=NO_SHIP, ganador=None`.
- No se generó ningún `.patch` para este run.

Comprobado por test: `ReportTest::test_no_ship_when_every_candidate_fails_its_gate`
afirma decisión, **causa exacta** y `eligible == []`.

---

## Artefactos

| Artefacto | Ruta |
|---|---|
| Run dir | `.arena/run-20261019-180429-s5/` |
| Gates | `.arena/run-20261019-180429-s5/gates.json` |
| Decisión | `.arena/run-20261019-180429-s5/decision.json` |
| Informe | `reports/run-20261019-180429-s5.md` / `.html` |

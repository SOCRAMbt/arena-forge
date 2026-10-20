# Matriz de aceptacion — AF-AC-001..018

> **GENERADO POR CODIGO.** No editar a mano: la fuente de verdad es
> [`acceptance-data.json`](acceptance-data.json) y el calculo lo hace
> [`compute_acceptance.py`](compute_acceptance.py). Regenerar con:
> `python reports/audit/compute_acceptance.py --write`

**Contrato de referencia:** `docs/contract/ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md`

**Leyenda de estados (estricta):** `PASS` · `PARTIAL` · `FAIL` · `BLOCKED` · `NOT_RUN` · `INCONCLUSIVE`.
Un `PARTIAL` **no** es un `PASS` con notas: significa que el criterio se cumple en parte y se documenta exactamente lo que falta.

## Recuento

| Estado | Recuento | % |
|---|---|---|
| PASS | 16 | 88.9 % |
| PARTIAL | 2 | 11.1 % |
| FAIL | 0 | 0.0 % |
| BLOCKED | 0 | 0.0 % |
| NOT_RUN | 0 | 0.0 % |
| INCONCLUSIVE | 0 | 0.0 % |
| **Total** | 18 | 100.0 % |

**Equivalente ponderado** (PASS=1, PARTIAL=0.5, resto=0): **94.4 %**

> **El porcentaje NO anula un gate P0.** Si hay un criterio en `FAIL` o `BLOCKED`, el veredicto global no es COMPLETE por muy alto que sea el numero.

## Por area (pesos declarados)

| Area | Peso | Criterios | Ponderado | Contribucion |
|---|---|---|---|---|
| integridad |  25 % | 4 | 100.0 % | 0.25 |
| seguridad |  20 % | 1 | 50.0 % | 0.10 |
| runtime |  20 % | 3 | 100.0 % | 0.20 |
| tests |  15 % | 4 | 87.5 % | 0.13 |
| opencode |  10 % | 2 | 100.0 % | 0.10 |
| documentacion |  10 % | 3 | 100.0 % | 0.10 |
| benchmark |   0 % | 1 | (sin peso: no medido) | 0.00 |
| **GLOBAL** | 100 pct | 18 | — | **0.88** |

Particion de los 18 criterios (sin solapes):

- **integridad** (25 %): AF-AC-001, AF-AC-004, AF-AC-007, AF-AC-008
- **seguridad** (20 %): AF-AC-010
- **runtime** (20 %): AF-AC-009, AF-AC-015, AF-AC-017
- **tests** (15 %): AF-AC-005, AF-AC-006, AF-AC-012, AF-AC-014
- **opencode** (10 %): AF-AC-003, AF-AC-018
- **documentacion** (10 %): AF-AC-002, AF-AC-011, AF-AC-013
- **benchmark** (0 %): AF-AC-016

## Criterios

### AF-AC-001 — PASS

> Reconocimiento: version de OpenCode, API efectiva, repo, estado Git, dependencias y tests identificados; hechos clasificados como verificados/inferidos/pendientes.

**Evidencia:** reports/audit/baseline.md: versiones, HEAD, ls-remote, y clasificacion verificado/inferido/pendiente

### AF-AC-002 — PASS

> Upstream: repositorio original, commit, licencia y archivos reutilizados inspeccionados; atribucion y hashes registrados.

**Evidencia:** THIRD_PARTY_NOTICES.md: commit df07b8e, MIT, SHA-256 de vendor/arena-skill/*

### AF-AC-003 — PASS

> Skill: la skill aparece y se carga con el ID/ruta exactos en el entorno probado.

**Evidencia:** tools/probe_skill.py: servidor enraizado en el repo -> id=arena-forge, path=.opencode/skills/arena-forge/SKILL.md, 280 skills; runtime/capabilities.json skills_native=verified

### AF-AC-004 — PASS

> CLI: planificacion, inicializacion, estado, ejecucion, collect, advance, cancelacion, reanudacion, informe y benchmark funcionan con datos reales.

**Evidencia:** 26 subcomandos; init/gates/report/verify/apply/judge/bench ejecutados con salida real en esta auditoria

### AF-AC-005 — PASS

> Answer Arena: E2E con al menos cuatro candidatos y artefactos persistidos.

**Evidencia:** tests/test_e2e_answer_arena.py: 4 candidatos, spawn/attack/defend/judge/collect/advance/decision/informe; ARTEFACTOS SINTETICOS (stub determinista, coste 0) - valida la MAQUINARIA, no la calidad de un modelo (§20.19)

### AF-AC-006 — PASS

> Patch Arena: E2E con al menos dos candidatos aislados y mismo harness; si no se demuestra aislamiento, modo declarado bloqueado y no anunciado como operativo.

**Evidencia:** reports/audit/e2e-patch.md: 2 candidatos aislados, mismo harness, gates PASS/FAIL, WINNER; aislamiento por isolation.json + manifiesto + politica unica de exclusiones

### AF-AC-007 — PASS

> Gates: los gates objetivos preceden al score LLM y el juez no puede anularlos.

**Evidencia:** forge/report.py: los gates se evaluan antes de la elegibilidad; el juez solo desempata con >=2 elegibles

### AF-AC-008 — PASS

> NO_SHIP: prueba reproducible de ausencia de candidatos elegibles.

**Evidencia:** reports/audit/e2e-noship.md: causa exacta 'ningun candidato supera los gates obligatorios'

### AF-AC-009 — PASS

> Reanudacion: interrupcion/reanudacion sin duplicacion ni corrupcion.

**Evidencia:** tests/test_e2e_answer_arena.py::test_07 (collect idempotente, advance una sola vez, hashes invariantes) + ResumeCancelTest

### AF-AC-010 — PARTIAL

> Seguridad: pruebas de prompt injection, corrupcion, harness, rutas, aislamiento, HTML y coste.

**Evidencia:** las 7 categorias tienen test; el AISLAMIENTO es a nivel de ruta/proceso, NO de sistema operativo: sin Job Object/AppContainer/red bloqueada. Modo declarado TRUSTED_CODE_ONLY (§13.3, AF-AC-006 modo bloqueado)

### AF-AC-011 — PASS

> Informe: hashes, decisiones, evidencia rastreable, limites y resultados negativos.

**Evidencia:** reports/audit/final-audit.md + reports/audit/artifacts/ (gates, decision, isolation, ledger, parche, SHA256SUMS) + decision.json

### AF-AC-012 — PASS

> Suite del proyecto: tests, lint, typecheck, build y E2E pertinentes ejecutados; herramientas ausentes marcadas NOT_RUN.

**Evidencia:** 118 tests + 12 autotests del lint + E2E Answer + build (compileall) + lint propio (tools/lint.py); CI verde en 4 legs (Windows/Linux x 3.11/3.12); mypy/ruff/pyright NOT_RUN declarados con causa

### AF-AC-013 — PASS

> Proteccion del repo: sin publicacion/push/merge/despliegue ni mutacion final sin aprobacion; cambios preexistentes preservados.

**Evidencia:** push con autorizacion explicita del usuario; sin merge/release/deploy; 150 ficheros scratch movidos (no borrados) con manifiesto SHA-256; tests de repo sucio intacto

### AF-AC-014 — PARTIAL

> Reproduccion externa: tercero reproduce demo desde checkout limpio.

**Evidencia:** checkout limpio reproducido por el propio equipo (clone + suite verde + CI en 4 legs) y evidencia versionada; falta la verificacion por un TERCERO INDEPENDIENTE (§23: el coordinador no puede ser la unica autoridad)

### AF-AC-015 — PASS

> E bajo control: no supera presupuesto, cambia rubricas congeladas, edita suite, salta gates ni ejecuta efectos externos sin autorizacion.

**Evidencia:** presupuesto reservado bajo lock de SO (test de limite con 1 llamada y 2 jobs); aprobacion humana aplicada y ligada; decisions.jsonl append-only; transiciones por state.transition

### AF-AC-016 — PASS

> Valor adaptativo: benchmark de agente unico vs. orquestacion fija vs. E adaptativo, o declaracion explicícita de que la eficacia adaptativa no esta demostrada.

**Evidencia:** DECLARACION EXPLICITA en runtime/benchmark.json y docs/BENCHMARK: la eficacia adaptativa de E NO esta demostrada; metricas de §4.9 no medidas (coste/aceptacion/ Latencia)

### AF-AC-017 — PASS

> Decision auditable: decision apunta a gates, scores, artefactos y politica.

**Evidencia:** decision.json (decision_id ligado al contenido, winner_id, diff_sha, suite_sha) + ledger.jsonl con cadena de hashes + decision_state.json

### AF-AC-018 — PASS

> Sin exito ficticio: ningun PASS sin ejecucion, coste inventado, output fabricado o ausencia presentada como exito.

**Evidencia:** sondas con evidencia real (skill verificada por ID; las de modelo en `blocked`); stub etiquetado (stub_manifest.json + banner STUB); NO_SHIP y NOT_RUN declarados; ningun PASS por presencia de codigo

## Matriz de trazabilidad minima (§21)

| ID | Requisito | Evidencia minima |
|---|---|---|
| AF-PR-001 | Gates preceden al juicio | tests/test_forge.py::ReportTest::test_no_ship_when_every_candidate_fails_its_gate + tests/test_e2e_answer_arena.py::test_05 |
| AF-PR-002 | Aislamiento | tests/test_forge.py::IsolationTest + tests/test_forge.py::ApplyIntegrityTest + reports/audit/artifacts/isolation.json |
| AF-PR-003 | NO_SHIP | reports/audit/e2e-noship.md + tests/test_forge.py::ReportTest::test_no_ship_when_every_candidate_fails_its_gate |
| AF-PR-004 | Reanudacion | tests/test_e2e_answer_arena.py::test_07_resume_does_not_duplicate_work + tests/test_forge.py::ResumeCancelTest |
| AF-PR-005 | Reproducibilidad honesta | tests/test_e2e_answer_arena.py::test_08_stub_is_deterministic + runtime/benchmark.json (LLM no determinista declarado) |
| AF-PR-006 | Minimo privilegio | docs/THREAT_MODEL.md + .opencode/agents/*.md (orden allow-last) + tests/test_forge.py::PortabilityTest::test_agent_permission_rules_put_allow_last |
| AF-PR-007 | Preservar cambios | tests/test_forge.py::PreexistingChangesTest::test_user_work_untouched |
| AF-PR-008 | Compatibilidad real | docs/RECONNAISSANCE.md + runtime/capabilities.json (v2.0.32) + tools/probe_skill.py |
| AF-PR-009 | Presupuesto | tests/test_forge.py::AgentETest::test_two_jobs_cannot_exceed_the_remaining_budget |
| AF-PR-010 | Aprobacion humana | tests/test_forge.py::AgentETest::test_human_approval_required_blocks_execution |

## Bloqueos que condicionan la certificacion

- **Contrato ausente:** cerrado. El contrato esta versionado en `docs/contract/` (SHA-256 registrado en `docs/contract/SHA256SUMS.txt`).
- **Sin frontera de sistema operativo:** abierto. No hay Job Object, AppContainer, usuario de minimos privilegios ni red bloqueada. El modo `TRUSTED_CODE_ONLY` esta declarado en el codigo, en cada `GateResult`, en `verify` y en la salida de `apply`. El contrato lo admite en AF-AC-006 ("modo declarado bloqueado y no anunciado como operativo").
- **Tercero independiente:** abierto. §23 exige que un tercero reproduzca la demo desde checkout limpio; el coordinador no puede ser la unica autoridad que certifica su propio exito.


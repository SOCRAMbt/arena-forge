# Matriz de aceptación — AF-AC-001..018

**Importante:** `ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md` **NO está en el checkout**
(`reports/audit/baseline.md` §BLOCKED-01). La columna "Criterio (según el paraphrase del
mandato)" es la **única** definición disponible. Todo criterio cuya certificación exija el
texto literal del contrato se marca `NOT_RUN`/`BLOCKED`; **ninguno se declara PASS por
analogía**.

**Cálculo:** se hace en **código**, no a ojo. La fuente de verdad es
[`acceptance-data.json`](acceptance-data.json) y el cálculo lo ejecuta
[`compute_acceptance.py`](compute_acceptance.py):

```console
$ python reports/audit/compute_acceptance.py
== RECUENTOS (total 18) ==
  PASS          7    38.9 %
  PARTIAL       8    44.4 %
  FAIL          1     5.6 %
  BLOCKED       0     0.0 %
  NOT_RUN       2    11.1 %
  INCONCLUSIVE  0     0.0 %
  PONDERADO GLOBAL (PASS=1, PARTIAL=0.5, resto=0): 61.1 %
```

> **El porcentaje NO anula los gates P0.** AF-AC-010 está en **FAIL** y AF-AC-016 en
> **NOT_RUN**. Por tanto el estado global es **NO-GO**, no COMPLETE.

**Fecha de ejecución:** 2026-10-19 · **HEAD:** `875c04ae1f7865c8043db651708d471c4a8d334e`
+ remediación de esta auditoría (sin commit).

| ID | Criterio (paraphrase del mandato) | Estado | Evidencia | Artefacto |
|---|---|---|---|---|
| AF-AC-001 | Reconocimiento: versión, API, repo, git, deps, tests | **PASS** | `reports/audit/baseline.md`: Python 3.12.4, pytest 9.1.1, Git 2.51.0, OpenCode v2.0.32, Windows 11 AMD64, HEAD remoto == local (`git ls-remote`) | `baseline.md` |
| AF-AC-002 | Upstream inspeccionado: repo, commit, licencia, ficheros reutilizados, hashes | **PASS** | `THIRD_PARTY_NOTICES.md` (commit `df07b8e`, MIT, SHA-256 de `vendor/arena-skill/*`) | `THIRD_PARTY_NOTICES.md` |
| AF-AC-003 | La skill aparece y carga con ID/ruta exactos | **PARTIAL** | Frontmatter `name: arena-forge` + `description` presentes y verificados por test. La **carga por ID en el runtime** no se ha probado: `GET /api/skill` no la lista en esta instalación → `inconclusive`. | `runtime/capabilities.json`, `PortabilityTest::test_repo_skill_has_opencode_frontmatter` |
| AF-AC-004 | CLI: plan, init, state, run, collect, advance, cancel, resume, report, benchmark | **PASS** | 19+ subcomandos operativos; `plan/init/next/collect/advance/gates/report/apply/verify/decide/cancel/resume/ledger/isolation/state/adapter/bench` ejecutados en esta auditoría con salida real. | `reports/audit/e2e-*.md` |
| AF-AC-005 | Answer Arena E2E con ≥4 candidatos y artefactos persistidos | **NOT_RUN** | El E2E de Answer exige una ola de subagentes reales. No ejecutado (coste). El flujo de bracket es determinista y está probado por unidades (`SchedulerDeterminismTest`), pero **no hay E2E**. | — |
| AF-AC-006 | Patch Arena E2E con ≥2 candidatos aislados y mismo harness | **PARTIAL** | E2E ejecutado en esta auditoría: `init` → `gates` (cand-01 PASS / cand-02 FAIL) → `report` (WINNER, `decision_id` persistido) → `verify` (11/11 PASS) → `apply` (parche exportado) → `git apply --check` exit 0. **Es ASISTIDO**: un operador copió el fix al workspace del candidato; el runtime no invoca al agente. | `reports/audit/e2e-patch.md` |
| AF-AC-007 | Los gates objetivos preceden al score; el juez no puede anularlos | **PASS** | `report.resolve_full` exige aislamiento, suite viva recalculada, baseline congelado, GateResult conclusivo para **todos** los candidatos y hashes bien formados **antes** de calcular elegibles. El juez solo actúa con ≥2 elegibles. | `ReportTest` (13 tests) |
| AF-AC-008 | Prueba reproducible de que **no** hay candidatos elegibles | **PASS** | E2E NO_SHIP en esta auditoría con la causa exacta `ningun candidato supera los gates obligatorios` (ambos candidatos FAIL). Antes esta rama **nunca** se alcanzaba. | `reports/audit/e2e-noship.md`, `ReportTest::test_no_ship_when_every_candidate_fails_its_gate` |
| AF-AC-009 | Interrupción/reanudación sin duplicación ni corrupción | **PARTIAL** | `resume` conserva `arena.json` byte a byte; `job_id` determinista (reanudar no duplica ni cobra dos veces); `decisions.jsonl` append-only. **La interrupción real a mitad de fase y su reanudación no se ha ejecutado**. | `ResumeCancelTest`, `AgentETest::test_job_ids_are_deterministic_and_resume_does_not_duplicate` |
| AF-AC-010 | Seguridad: inyección de prompt, corrupción, harness, rutas, aislamiento, HTML, coste | **FAIL** | Muchos controles pasan y están probados (harness tampering incl. `conftest.py` anidado, traversal en todas las cabeceras, symlinks fail-closed, HTML escapado, gate no falsificable, shim de pytest aislado). **Pero NO hay frontera de OS**: sin red bloqueada, sin filesystem restringido, sin usuario mínimo. Modo declarado `TRUSTED_CODE_ONLY`. **P0 abierto.** | `forge/isolation.py::SECURITY_MODE`, `docs/THREAT_MODEL.md` |
| AF-AC-011 | Informe con hashes, decisiones, evidencia trazable, límites y resultados negativos | **PASS** | MD + HTML estático escapado, con decisión, razón, ganador, `decision_id`, hashes de suite/diff/manifiesto, presupuesto, herramientas NOT_RUN y riesgos residuales. | `ReportTest::test_html_escapes_script`, `reports/*.md` |
| AF-AC-012 | Suite de tests + CI + lint/typecheck/build; herramientas ausentes marcadas NOT_RUN | **PARTIAL** | 113 tests (unit + integración + adversarial) en verde, portables (sin rutas del host) y sin ensuciar el repo. **CI creada pero NO ejecutada**; no hay lint/typecheck declarados. | `reports/audit/test-results.json`, `.github/workflows/ci.yml` |
| AF-AC-013 | Protección del repo: sin push/merge/release, cambios preexistentes preservados | **PASS** | `apply` solo escribe `reports/<run>.patch`; nunca muta el proyecto. Los 150 ficheros scratch de sesiones anteriores se **movieron** (no se borraron) a un temporal con manifiesto SHA-256. `git status` solo muestra cambios intencionales. | `reports/audit/baseline.md` §5 |
| AF-AC-014 | Reproducción externa desde checkout limpio | **PARTIAL** | Tests portables + `pytest.ini` + `.gitattributes` (eol=lf) + CI con smoke E2E. **No se ha ejecutado un checkout limpio externo**: las demos `demo/*.md` siguen apuntando a runs v1 obsoletos. | `reports/audit/e2e-patch.md` |
| AF-AC-015 | E bajo control: presupuesto, rúbrica congelada, no editar suite, no saltar gates, sin efectos externos | **PASS** | Aprobación humana **aplicada** y ligada; presupuesto **reservado** bajo lock de SO antes de crear el job (2 jobs con 1 llamada → el 2º falla); `decisions.jsonl` append-only; transiciones por `state.transition`; campos desconocidos rechazados. | `AgentETest` (17 tests) |
| AF-AC-016 | Valor adaptativo de E vs agente único vs orquestación fija, **o declaración explícita de no demostrado** | **NOT_RUN** | `runtime/benchmark.json` declara literalmente: *"eficacia adaptativa de E vs orquestacion fija vs agente unico (hipotesis pendiente, no demostrada aqui)"*. **No se estima ni se fabrica.** | `runtime/benchmark.json` |
| AF-AC-017 | Decisión auditable: gates, scores, artefactos, política | **PARTIAL** | Ledger con cadena de hashes (`prev_hash`+`event_hash`), verificación de continuidad y detección de manipulación probadas; `decision.json` liga la decisión con winner/diff_sha/suite_sha. **Sin ancla externa**: un escritor con permiso puede rehacer el ledger. | `LedgerTest` (4 tests), `ApplyIntegrityTest::test_report_persists_the_decision` |
| AF-AC-018 | Sin éxito ficticio: no PASS sin ejecución, no coste/output inventado | **PARTIAL** | Las sondas dejaron de declarar `verified` sin prueba real (3 `verified` anteriores eran falsos). `subagent_tool`/`readonly_agent` = `blocked`, `permission_rules` = `inconclusive`, `skills_native` = `inconclusive`. **El estado `succeeded` de E ya no se emite sin trabajo verificado.** Queda el `succeeded` potencial de `mark_job_completed` si se aporta un output real: no verificado end-to-end. | `runtime/capabilities.json`, `AdapterTest` (10 tests) |

---

## Cálculo (por área, con pesos declarados)

Ejecutado por `compute_acceptance.py` sobre `acceptance-data.json`:

| Área | Peso | Criterios | Ponderado | Contribución |
|---|---|---|---|---|
| integridad | 25 % | 4 | 100.0 % | 25.00 |
| seguridad | 20 % | 1 | 0.0 % | 0.00 |
| runtime | 20 % | 3 | 66.7 % | 13.33 |
| tests | 15 % | 4 | 37.5 % | 5.63 |
| opencode | 10 % | 2 | 50.0 % | 5.00 |
| documentacion | 10 % | 3 | 83.3 % | 8.33 |
| benchmark | 0 % | 1 | (no medido, sin peso) | 0.00 |
| **GLOBAL** | 100 % | 18 | — | **57.3 %** |

Partición de los 18 criterios (sin solapes):

- **integridad (25 %)**: AF-AC-001, 004, 007, 008
- **seguridad (20 %)**: AF-AC-010
- **runtime (20 %)**: AF-AC-009, 015, 017
- **tests (15 %)**: AF-AC-005, 006, 012, 014
- **opencode (10 %)**: AF-AC-003, 018
- **documentacion (10 %)**: AF-AC-002, 011, 013
- **benchmark (0 %)**: AF-AC-016 — sin peso porque NO está medido: no se puntúa ni como
  aprobado ni como reprobado.

### Bloqueos que condicionan la certificación

- **BLOCKED-01** — el contrato (`ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md`) no está
  en el checkout. Las etiquetas "PASS/PARTIAL/FAIL" de esta matriz se refieren al criterio
  *declarado en el mandato*, no al texto literal de la especificación.
- **BLOCKED-02** — no existe sandbox de OS en este entorno. AF-AC-010 no puede pasar sin
  una prueba de contención real.

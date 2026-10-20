# Arena Forge — Entrega final (§22 del contrato)

**Contrato de referencia:** `docs/contract/ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md`
(SHA-256 `960274344a32b337cd30438a85a31d09c4e63204f822902a96057d250634d273`).
**Entrega:** 2026-10-19 · **Estado global: NO-GO** (ver §0).

> §22: *"No declarar éxito por intención, código escrito ni opinión de los
> agentes. Presentar artefactos para que un tercero lo compruebe."* Y §23:
> *"no permitir que el coordinador sea la única autoridad que certifique su
> propio éxito."*

---

## 0. Veredicto, y por qué NO es COMPLETE

| | |
|---|---|
| **Estado** | **NO-GO** — 16 PASS, 2 PARTIAL, 0 FAIL, 0 NOT_RUN, 0 BLOCKED. Ponderado **94.4 %**; por área **88.1 %** |
| **Por qué no COMPLETE** | Dos razones, ambas verificables y ninguna subsanable por mí:<br>1. **§23 (regla final):** el coordinador no puede ser la única autoridad que certifique su propio éxito. Falta la **reproducción por un tercero independiente** (AF-AC-014 → PARTIAL).<br>2. **AF-AC-010 → PARTIAL:** el aislamiento de los candidatos es a nivel de ruta y proceso, **no de sistema operativo**. No hay Job Object, AppContainer, usuario de mínimos privilegios ni red bloqueada. El modo `TRUSTED_CODE_ONLY` está declarado, pero un criterio en PARTIAL impide `COMPLETE` (§18). |
| **Qué NO se declara** | Eficacia adaptativa de E demostrada (no: es una hipótesis pendiente, §23). Calidad de un modelo real (no: el E2E de Answer usa un stub determinista). Aislamiento de nivel OS (no: sin frontera). |
| **Cálculo** | Generado por código: `python reports/audit/compute_acceptance.py --write`. Un test (`AcceptanceMatrixTest::test_matrix_markdown_matches_the_data`) falla si el `.md` se desincroniza de los datos. |

Matriz completa: [`acceptance-matrix.md`](acceptance-matrix.md) ·
Hallazgos con reproducción: [`findings.md`](findings.md) ·
Resultados por test: [`test-results.json`](test-results.json).

---

## 1. Qué se construyó y qué no

### Construido y verificado

| Sistema | Qué hace | Evidencia |
|---|---|---|
| **Parche canónico** | `git diff --binary` real (formato literal/delta de Git), no un formato inventado. Aplicación con `git apply --check` + `git apply`. | `tests/test_forge.py::BinaryPatchTest` (13 tests) |
| **Integridad del artefacto** | Suite, baseline, manifiesto y diff se **recalculan** en `report`, `verify` y `apply`. `sha256(parche exportado) == diff_sha del gate == diff_sha de decision.json`. | `reports/audit/artifacts/` + `ApplyIntegrityTest` |
| **Gate no falsificable** | Exige informe JUnit **y** marcador de finalización (`atexit`, que `os._exit` no ejecuta) **y** recuento mínimo de tests. | `GatesTest::test_gate_rejects_candidate_forced_exit_zero` (+ control) |
| **Symlinks fail-closed** | Symlink externo/roto/directorio → `ForgeError`; el gate marca `BLOCKED/unsafe_candidate`. | `IsolationTest` (10 tests) |
| **Política de exclusión única** | La misma política para manifiesto, parche y scratch del gate (antes los `.pyc` se ejecutaban sin estar en ningún hash). | `isolation.py::EXCLUDED_*` |
| **Decisión ligada al contenido** | `decision_id` = hash del contenido de la decisión; `apply` lo recalcula y **aborta** si el estado cambió entre `report` y `apply`. Un run NO_SHIP ya no puede producir WINNER. | `ApplyIntegrityTest` + `report.py::resolve_full` |
| **Presupuesto de E atómico** | Reserva bajo **lock de sistema operativo** antes de crear el job; idempotente; libera la reserva en todo fallo. | `AgentETest::test_two_jobs_cannot_exceed_the_remaining_budget` |
| **Aprobación humana efectiva** | Sin registro **ligado** (decision_id, run_id, action, targets, coste, `approved_by`) la decisión queda `awaiting_approval` y no ejecuta. | `AgentETest::test_human_approval_required_blocks_execution` |
| **Agente stub determinista** | Doble de costura para el E2E de Answer: mismo camino de producción, coste 0, **calidad heterogénea** para que el juez discrimine de verdad. | `forge/stub_agent.py` + `tests/test_e2e_answer_arena.py` |
| **Lint propio + build** | Lint sin dependencias externas (AST) con **autotests y control negativo**; build = `compileall`; `mypy`/`ruff` declarados NOT_RUN con causa. | `tools/lint.py`, `tools/test_lint.py` |
| **Sonda de skill** | Servidor **enraizado en el repo** (el de fondo puede estar en otro árbol) → la skill se carga con ID y ruta exactos. | `tools/probe_skill.py` → `skills_native=verified` |
| **CI real** | Windows/Linux × Python 3.11/3.12, verde en las 4 legs desde checkout limpio. | GitHub Actions run 3 (`93f7f2d`) |

### NO construido (declarado, no simulado)

| Sistema | Por qué no | Qué haría falta |
|---|---|---|
| **Sandbox de sistema operativo** | Windows sin Job Object/AppContainer en uso; requiere privileges para red y filesystem. | Admin rights (o un contenedor). Un Job Object **no** requiere elevación: acota memoria/PIDs/árbol. |
| **Despacho real de agentes desde el runtime** | El runtime escribe briefs; quien lanza las olas es el orquestador o el operador. | Implementar el `subagent`/dispatch y poblar `session_ref`/`output_ref`. |
| **Sondas que requieren modelo** (`subagent_tool`, `readonly_agent`) | Coste no autorizado. | `adapter.probe(allow_model_calls=True)`. |
| **Eficacia adaptativa de E** | §23: solo se demuestra con comparación reproducible y repetida. | Dataset versionado × 3 métodos × repeticiones. |
| **Reproducción por un tercero** | §23: el coordinador no puede certificarse a sí mismo. | Una persona (o agente) independiente, en otra máquina. |

---

## 2. Capacidades de OpenCode V2: verificadas y NO verificadas

Fuente: `runtime/capabilities.json` (regenerado en esta ejecución).

| Capacidad | Estado | `by` | Evidencia |
|---|---|---|---|
| `skills_native` | **verified** | functional_test | `id=arena-forge`, `path=.opencode/skills/arena-forge/SKILL.md` (280 skills en el runtime, servidor enraizado en el repo) |
| `agent_profiles` | **verified** | filesystem | 4 perfiles: implementer, judge, reviewer, scout |
| `state_on_disk` | **verified** | functional_test | Ida y vuelta real: crear → cerrar → reabrir → reanudar; ledger verificado |
| `shell_tool` | **verified** (scope `host`) | host | Ejecución de comandos del **host**; **no** es el shell tool de OpenCode |
| `cwd_control` | **verified** (scope `host`) | host | `cwd` de un subprocess local; **no** es una capacidad del runtime |
| `python_runtime` | **verified** | platform | Python 3.12.4 |
| `permission_rules` | **unknown** | static_analysis | Orden de reglas correcto (4 permisos) verificado **estáticamente**; la *enforcement* en runtime **no** está probada (requiere modelo) |
| `subagent_tool` | **blocked** | functional_test | Requiere llamada a modelo; coste no autorizado |
| `readonly_agent` | **blocked** | functional_test | Ídem |
| `subagent_foreground` | **blocked** | derived | Derivado de `subagent_tool` (no se hace una 2ª llamada) |
| `subagent_background` | **unknown** | none | NOT_RUN: sesión prolongada + modelo |
| `plugin_api` | **unknown** | none | NOT_RUN: no se usa en el producto |

Corrección relevante frente a la versión anterior: 4 capabilities estaban
`verified` **sin prueba real** (el texto de ayuda de la CLIcontains "denied" y
se leía como denegación; `state_on_disk` devolvía `True` incondicionalmente) y
3 eran `unsupported` **por sintaxis inválida** (`opencode skill load` y
`opencode run --prompt` no existen en v2.0.32). Ahora un error de invocación es
`inconclusive`/`unknown`, nunca `unsupported`.

---

## 3. Archivos añadidos y modificados

**Añadidos:** `forge/integrity.py` · `forge/stub_agent.py` · `tools/lint.py` ·
`tools/test_lint.py` · `tools/probe_skill.py` · `tests/test_e2e_answer_arena.py` ·
`pytest.ini` · `.gitattributes` · `.github/workflows/ci.yml` ·
`docs/contract/` (el contrato) · `docs/ADR-006-aislamiento.md` ·
`docs/superpowers/plans/` (plan) · `reports/audit/` (9 informes + artefactos) ·
`fixtures/patch-demo/binary/sample.bin`.

**Modificados:** `arena_forge.py` · `forge/{isolation,gates,report,adapter,agent_e,ledger,util,benchmark}.py` ·
`tests/test_forge.py` · `.opencode/agents/{implementer,judge,reviewer}.md` ·
`.opencode/skills/arena-forge/SKILL.md` · `README.md` · `VERIFICATION_SUMMARY.md` ·
`CHANGELOG.md` · `docs/{THREAT_MODEL,ARCHITECTURE,RECONNAISSANCE}.md` ·
`demo/*.md` · `runtime/*.json` · `.gitignore` · `PLAN_AUDIT_FIXES.md`.

**No tocado:** `vendor/arena-skill/*` (upstream, hash intacto) · `LICENSE` ·
`THIRD_PARTY_NOTICES.md` · cualquier proyecto ajeno a Arena Forge.

---

## 4. Cobertura unitaria, de integración y E2E

| Capa | Dónde | Nº |
|---|---|---|
| Unitaria + integración | `tests/test_forge.py` | 123 |
| E2E Answer Arena (stub) | `tests/test_e2e_answer_arena.py` | 9 |
| Autotests del lint | `tools/test_lint.py` | 14 |
| **Total** | | **146** (145 pass + 1 skip explicito) |

Contra las 22 pruebas obligatorias de §16: **7 cubiertas íntegras, 12 parciales,
3 sin cobertura directa** (ver §6).

---

## 5. Comandos exactos y resultados

```console
$ python -m pytest tests/ tools/test_lint.py -q --no-header -p no:cacheprovider --timeout=180
145 passed, 1 skipped                     (estado final; exit 0)

$ python -m pytest tests/ -q            (lo que ejecuta la CI)
131 passed, 1 skipped

$ python -m pytest tools/test_lint.py -q
14 passed

$ python tools/lint.py --report
lint propio: 18 ficheros analizados, 0 error(es), 25 aviso(s)
build (compileall): OK
herramientas ausentes -> NOT_RUN: ruff, mypy, flake8, pylint, pyright

$ python tools/probe_skill.py
AF-AC-003 sonda de skill: VERIFIED
  id arena-forge   path .opencode/skills/arena-forge/SKILL.md   path_matches_repo True

$ python reports/audit/compute_acceptance.py
PASS 16 (88.9 %) · PARTIAL 2 (11.1 %) · FAIL 0 · NOT_RUN 0 · BLOCKED 0
PONDERADO GLOBAL: 94.4 %   GLOBAL por area: 88.1 %

$ git clone <repo> af-clean && cd af-clean && python -m pytest tests/ -q
131 passed, 1 skipped                     (checkout limpio, LF)

$ (GitHub Actions run 7, sha 01dbb55)
conclusion: success  —  windows-latest/py3.11, py3.12, ubuntu-latest/py3.11, py3.12

$ (historial: run 1..2 fallaron, run 3 verde, runs 4..6 fallaron, run 7 verde)
El fallo de los runs 4-6 era SOLO en Windows: `os.path.relpath` lanza
ValueError cuando repo y temporal estan en unidades distintas (D:\ vs C:\ en
los runners). Corregido en tools/lint.py y con un test que lo reproduce.
```

---

## 6. Gates fallidos, bloqueados o no ejecutados

| Ítem | Estado | Motivo |
|---|---|---|
| Aislamiento de nivel OS (AF-AC-010) | **PARTIAL** | No hay frontera de OS. Modo `TRUSTED_CODE_ONLY` declarado (ADR-006). |
| Reproducción por tercero (AF-AC-014) | **PARTIAL** | Reproducido por el equipo; falta un tercero independiente (§23). |
| Eficacia adaptativa de E (AF-AC-016) | **PASS por declaración** | §18 permite la declaración explícita; §23 mantiene la eficacia como hipótesis. Las 9 métricas de §4.9 **no** están medidas. |
| Sondas con modelo (`subagent_tool`, `readonly_agent`) | **blocked** | Coste no autorizado. |
| `mypy` / `ruff` / `pyright` (typecheck y lint externos) | **NOT_RUN** | No instalados; no se instalan globalmente. El lint propio y el build sí se ejecutan. |
| `subagent_background`, `plugin_api` | **NOT_RUN** | No se usan en el producto. |
| CI en GitHub Actions | **PASS** | Run 7 verde en 4 legs (Windows/Linux x 3.11/3.12). |

---

## 7. Demostración de NO_SHIP

`reports/audit/e2e-noship.md` — dos candidatos idénticos al baseline con el bug →
ambos FAIL → `NO_SHIP (ningun candidato supera los gates obligatorios)`, sin
campeón y **sin parche exportable** (`apply` aborta con
`sin campeon: decision=NO_SHIP`).
Test: `ReportTest::test_no_ship_when_every_candidate_fails_its_gate` (afirma la
**causa exacta**, no solo el estado).

---

## 8. Prueba de aislamiento

- Cada candidato tiene su propio workspace, validado **antes** de crear nada
  (`ensure_workspaces` rechaza ids con separadores o `..`).
- El gate **nunca** ejecuta en el árbol del proyecto: copia a un scratch.
- El scratch usa la **misma** política de exclusiones que el manifiesto y el
  parche (los `.pyc` ya no llegan).
- El entorno del gate es allowlist: sin `HOME`/`TEMP` del operador, sin
  user site-packages, sin plugins de pytest, con `PYTHONSAFEPATH`.
- El árbol principal **no cambia**: `git status` antes/después y un paso de CI
  (`git diff --exit-code`) lo comprueban.
- Artefacto versionado: `reports/audit/artifacts/isolation.json`.

**Lo que NO se demuestra:** contención de sistema operativo. Ver ADR-006.

---

## 9. Prueba de reanudación

`tests/test_e2e_answer_arena.py::test_09_interruption_mid_phase_then_resume_without_duplicates`:
se interrumpe a mitad de fase (spawn+attack hechos, sin `collect` ni `advance`),
se reanuda, y se verifica que (a) los ficheros previos conservan su hash,
(b) los 2 matches se cercioran exactamente una vez, (c) no se duplica ninguna
ronda.
Además `test_07`: `collect` es idempotente y `advance` avanza **una sola vez**
(un segundo `advance` falla y no crea ronda).
Y `ResumeCancelTest`: `resume` no reescribe `arena.json`; `cancel` congela el
run y bloquea `collect`/`gates`/`report`/`apply`/`decide`.

---

## 10. Resultados contra baseline

| | Baseline (bug) | Candidato corregido |
|---|---|---|
| `gate_engine.run_gate` | **FAIL** (`required_check_failed`) | **PASS** |
| `report.resolve` | NO_SHIP | WINNER |
| Parche exportado | — | `sha256 = c68f82cd…f59f` (= `diff_sha` del gate) |
| `git apply --check` | — | exit 0 (con `core.autocrlf=false`) |

La línea base de **método** (§16.12, "baseline adversarial: caso donde el método
original gana; el informe lo dice") está **NO cubierta**: no hay un fixture en
el que el método original gane. Declarado como hueco, no como PASS.

---

## 11. Valor incremental de E adaptativo

**No medido.** `runtime/benchmark.json` lo declara de forma explícita:

> "eficacia adaptativa de E vs orquestacion fija vs. agente unico (hipotesis pendiente, no demostrada aqui)"

Las 9 métricas de §4.9 (tasa de aceptación, defectos escapados, coste/llamadas/
duración, trabajos duplicados, % de rondas que cambian la decisión, rondas
improductivas, falsos positivos/negativos de gates, esfuerzo humano,
reproducibilidad) **no están medidas**. §23 lo confirma: la eficacia adaptativa
solo se considera demostrada con una comparación reproducible con orquestación
fija y agente único.

Lo que sí está medido y es determinista: el scheduler reparte tarjetas sin
repetir y termina en un único ganador (7 tamaños verificados).

---

## 12. Coste y duración observados; datos no medibles

| Métrica | Valor |
|---|---|
| Duración de la suite completa | 240–350 s (139 tests, Windows 11) |
| Duración del E2E Answer (stub) | ~95 s para 9 tests |
| Coste de modelo | **0** — el E2E usa un stub determinista; ninguna llamada a modelo ejecutada |
| Llamadas de subagente | 0 (stub) |
| Tokens / dinero | **no medible**: el proveedor no expone tokens por API (§12) |
| CI | 4 legs × (3.11, 3.12) en Windows y Linux |

---

## 13. Riesgos residuales

| # | Riesgo | Severidad | Estado |
|---|---|---|---|
| R-1 | El código del candidato se ejecuta con los privilegios del operador (sin Job Object/red bloqueada) | **P0** | Declarado (ADR-006, THREAT_MODEL) |
| R-2 | Un candidato dentro del proceso de pytest puede, en principio, subvertir el oráculo del gate | P0 | Mitigado (informe JUnit + marcador `atexit` + recuento mínimo); **no cerrado** sin sandbox |
| R-3 | Permisos de agente concedidos por run, no por candidato: un implementer podría escribir en el workspace de un rival | P1 | Abierto |
| R-4 | El score del juez no participa en la decisión (solo la etiqueta X/Y) | P1 | Abierto |
| R-5 | Lock de run ausente en `gates`/`report`/`apply` (el ledger y el presupuesto sí lo tienen) | P1 | Abierto |
| R-6 | Contratos no aplicados en todas las transiciones | P1 | Abierto |
| R-7 | `ledger.jsonl` es *tamper-evident*, no *tamper-proof* (sin ancla externa) | P2 | Aceptado y documentado |
| R-8 | La suite protegida no está oculta del candidato (la lee, no la modifica) | P2 | Aceptado; el hash se comprueba antes y después |
| R-9 | `with suite: null` la revalidación viva de la suite se omite en vez de fallar cerrado | P2 | Abierto |
| R-10 | E2E de Answer con stub: valida la maquinaria, no la calidad de un modelo | P2 | Etiquetado (`stub_manifest.json`, banner `STUB` en cada artefacto) |

---

## 14. Reproducción desde checkout limpio

```bat
git clone https://github.com/SOCRAMbt/arena-forge.git
cd arena-forge
python -m pip install "pytest>=8,<10"
python -m pytest tests/ -q                      :: 117 passed, 1 skipped
python tools/lint.py                            :: 0 errores
python reports/audit/compute_acceptance.py      :: PASS 16 / PARTIAL 2
```

Verificado por el equipo en un clone limpio (LF) y por GitHub Actions en 4 legs.
**Pendiente:** que un tercero independiente lo repita (§23) — es lo que separa
este entregable de `COMPLETE`.

---

## 15. Tres siguientes pasos de mayor impacto, priorizados por evidencia

| # | Paso | Cierra | Esfuerzo | Por qué |
|---|---|---|---|---|
| 1 | **Job Object** en Windows (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` + límites de memoria/PIDs) | R-1, R-2 (parcial) | **Bajo** — no requiere elevación | Es la única pieza que acerca el gate a un oráculo no falsificable, y el contrato la admite sin admin. |
| 2 | **Reproducción por un tercero independiente** en otra máquina | AF-AC-014 → PASS; **desbloquea `COMPLETE`** | Bajo (coordinación) | Es el único criterio que separa NO-GO de COMPLETE (§23). |
| 3 | **Permisos de agente por candidato** (plantilla generada con la ruta exacta) + test de denegación | R-3 | Medio | Cierra la contaminación entre candidatos, que hoy solo está documentada. |

---

## Apéndice — Artefactos verificables por un tercero

| Artefacto | Qué demuestra |
|---|---|
| `reports/audit/artifacts/gates.json` | Veredicto por candidato con `diff_sha` y `candidate_manifest_sha` |
| `reports/audit/artifacts/decision.json` | Decisión persistida, `winner_id`, `decision_id` ligado al contenido |
| `reports/audit/artifacts/isolation.json` | Prueba de aislamiento de los workspaces |
| `reports/audit/artifacts/ledger.jsonl` | Historial append-only con cadena de hashes |
| `reports/audit/artifacts/run-20261019-210128-s31.patch` | El parche round-trip evaluado |
| `reports/audit/artifacts/SHA256SUMS.txt` | SHA-256 de cada artefacto (normalizado a LF) |
| `reports/audit/artifacts/answer-e2e/` | Los 4 candidatos, ataques, defensas, veredictos y el campeón del E2E Answer |
| `fixtures/patch-demo/binary/sample.bin` | Artefacto binario persistido (NUL + cola no-UTF-8) |
| `docs/contract/` | El contrato, versionado, con su SHA-256 |

`sha256(parche) == diff_sha del gate == diff_sha de decision.json` —
comprobado en la ejecución:
`c68f82cde82f99a62b22d055be908c13fa957222114deecd589c88a7f718f59f`

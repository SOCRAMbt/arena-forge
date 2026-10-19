# Auditoría forense — Informe final

**Repositorio:** `C:\Users\Marcos\arena-forge`
**Remoto:** `https://github.com/SOCRAMbt/arena-forge` → `origin/main`
**Fecha de ejecución:** 2026-10-19 (America/Argentina)
**Auditor:** Staff Engineer principal (integrador único) + 4 revisores read-only
independientes (seguridad, tests/E2E/CI, integración OpenCode, integridad de runtime)

---

## 1. Estado del repositorio

```console
$ git rev-parse HEAD
875c04ae1f7865c8043db651708d471c4a8d334e

$ git branch --show-current
main

$ git rev-parse --abbrev-ref --symbolic-full-name '@{u}'
origin/main

$ git rev-list --left-right --count '@{u}...HEAD'
0	0

$ git ls-remote origin
875c04ae1f7865c8043db651708d471c4a8d334e	HEAD
875c04ae1f7865c8043db651708d471c4a8d334e	refs/heads/main
```

| Dato | Valor |
|---|---|
| HEAD | `875c04ae1f7865c8043db651708d471c4a8d334e` |
| Rama | `main` |
| Upstream | `origin/main` |
| Divergencia | 0 ahead / 0 behind |
| Árbol | **DIRTY**: 27 ficheros trackeados modificados + 6 rutas nuevas (todas intencionales) |
| Remoto == local | **SÍ** (verificado con `ls-remote`, sin fetch ni pull) |

### Reconciliación de la discrepancia de HEAD

La auditoría externa استخدم `84ab02e` como referencia y afirmaba que
`_binary_diff_line` / `_apply_binary_diff` **no existían** en ese commit.

**Resuelto:** `84ab02e` es un ancestro directo. El commit `875c04a`
("P0-A/P0-C: Binary diffs with base64 encoding and proper apply") lo supera y **sí**
modifica `forge/isolation.py`. Las funciones existen en `875c04a`
(`forge/isolation.py:71` y `:260`).

**Pero la existencia de las funciones no era el problema.** La auditoría-forense
detectó que la implementación de `875c04a` era **peor** de lo que sugería su nombre:
usaba un formato de parche binario **inventado** que `git apply` rechaza, y su parser
descartaba silenciosamente los hunks de texto en un diff mixto. Corregido en esta
remediación (ver `findings.md` §P0-BIN).

### Higiene del árbol

150 ficheros scratch de sesiones anteriores (`fix_*.py`, `test_binary*.py`, `old_*.txt`,
`reports/run-*.patch`) se **movieron** (no se borraron) a
`%LOCALAPPDATA%\Temp\opencode\arena-forge-scratch-20261019\` con un manifiesto
`SHA256SUMS.txt`. No se ejecutó `git clean`, `git reset`, `git restore` ni `git checkout`.

---

## 2. Estado global: **NO-GO**

**No se declara COMPLETE ni 100 %.** Bloqueos:

| # | Bloqueo | Severidad | Por qué no se puede cerrar aquí |
|---|---|---|---|
| **BLQ-1** | Sin frontera de sistema operativo para el código del candidato | **P0** | Windows 11 sin Job Object / AppContainer / usuario de privilegios mínimos / red bloqueada. Un scratch con entorno filtrado **no es un sandbox**. El modo `TRUSTED_CODE_ONLY` está declarado en el código, en cada `GateResult`, en `verify` y en `apply`. |
| **BLQ-2** | Contrato funcional ausente | **P0** | `ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md` no está en el checkout. AF-AC-001..018 y §16 no son certificables de forma autoritativa. |
| **BLQ-3** | CI no ejecutada | P1 | `.github/workflows/ci.yml` se crea aquí; no corre hasta el push. AF-AC-012 = configurada-y-no-verificada. |
| **BLQ-4** | AF-AC-016 sin medir | P1 | Comparación real single_agent vs fixed_orchestration vs arena_e_adaptive con repeticiones. Requiere ejecuciones vivas con coste. **No se estima.** |
| **BLQ-5** | Sondas que requieren modelo | P1 | `subagent_tool` y `readonly_agent` quedan `blocked`: probar la creación de un subagente nativo o una denegación real cuesta tokens no autorizados. |

---

## 3. Tabla de estados por criterio

Matriz completa y cálculo: [`acceptance-matrix.md`](acceptance-matrix.md).

| Estado | Recuento | % |
|---|---|---|
| PASS | 7 | 38.9 % |
| PARTIAL | 8 | 44.4 % |
| FAIL | 1 | 5.6 % |
| BLOCKED | 0 | 0.0 % |
| NOT_RUN | 2 | 11.1 % |
| **Equivalente ponderado** | — | **61.1 %** |

> Números **ejecutados** por `reports/audit/compute_acceptance.py` sobre
> `reports/audit/acceptance-data.json`. No están calculados a mano.

> **El porcentaje no anula los gates P0.** AF-AC-010 está en **FAIL** y AF-AC-016 en
> **NOT_RUN**. El estado global es NO-GO.

### Por área (pesos declarados, cálculo en código)

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

Metodología: cada área se puntúa por la fracción de criterios con el estado más alto
alcanzable (`PASS`=1, `PARTIAL`=0.5, `FAIL`=0, `NOT_RUN`=0). El global es la suma de
`peso × ponderado` y **no puede ocultar un P0 abierto**. Los números y la partición
salen de `compute_acceptance.py`; el reparto criterio→área está en `acceptance-data.json`.

---

## 4. Claims probados, refutados y no evaluables

### Refutados por esta auditoría (el código NO hacía lo que se afirmaba)

| Claim previo | Realidad | Evidencia |
|---|---|---|
| "El parche binario es un parche Git" | Era un formato **inventado** (base64 estándar con cabecera `GIT binary patch`); `git apply` lo rechaza | `BinaryPatchTest::test_git_apply_check_accepts_generated_patch` |
| "El parche aplica el cambio completo" | El parser binario **descartaba los hunks de texto** de un diff mixto | `BinaryPatchTest::test_mixed_diff_keeps_the_text_hunk` |
| "`apply` aplica el candidato juzgado" | Aplicaba `eligible[0]`, **otro** candidato | `ApplyIntegrityTest::test_apply_exports_the_judged_winner_not_the_first_eligible` |
| "`diff_sha` acredita el diff evaluado" | Solo se validaba el **formato**; nunca se recalculaba | `ReportTest::test_no_ship_when_diff_sha_does_not_match_the_recomputed_diff` |
| "`suite_sha` protege la suite" | Se comparaba con **otro valor almacenado**; la suite viva no se releía | `ReportTest::test_no_ship_when_suite_was_tampered_after_gates` |
| "`apply` verifica el baseline" | Era `pass  # TODO` y `target_baseline_dir` **nunca se guardaba**: código muerto | `ApplyIntegrityTest::test_apply_blocks_when_frozen_baseline_changed` |
| "El presupuesto de E se respeta" | Se gastaba **después** del job, sin lock: 2 jobs con 1 llamada → `calls_spent=2` | `AgentETest::test_two_jobs_cannot_exceed_the_remaining_budget` |
| "La aprobación humana se exige" | `requires_human_approval` solo se validaba por **tipo**; nunca se aplicaba | `AgentETest::test_human_approval_required_blocks_execution` |
| "El gate decide objetivamente" | El **candidato** podía fabricar el PASS (`os._exit(0)` en el import) | `GatesTest::test_gate_rejects_candidate_forced_exit_zero` |
| "La skill nativa está incluida" | Sin frontmatter: **OpenCode la omitía** | `PortabilityTest::test_repo_skill_has_opencode_frontmatter` |
| "Los agentes tienen mínimo privilegio" | Las reglas `allow` estaban **muertas** (orden invertido): no podían escribir nada | `PortabilityTest::test_agent_permission_rules_put_allow_last` |
| "6 capacidades verificadas" | 4 no tenían prueba real; 3 `unsupported` eran por sintaxis inválida | `runtime/capabilities.json` |
| "Los symlinks se validan" | Los inseguros se **omitían en silencio** | `IsolationTest::test_unsafe_symlink_blocks_manifest` |
| "44/44 PASS es portable" | 2 tests fallaban en Linux/otra cuenta; los manifiestos dependían de CRLF | `PortabilityTest::test_no_absolute_host_paths_in_tests` |
| "todos FAIL → NO_SHIP" | La rama **nunca** se alcanzaba (falso PASS) | `ReportTest::test_no_ship_when_every_candidate_fails_its_gate` |
| "CI configurada" | No existía `.github/` | `.github/workflows/ci.yml` (nuevo) |

### Confirmados (ya eran ciertos y siguen siéndolo, con test)

- Los gates preceden al score; el juez no puede anular un gate fallido.
- El árbol principal nunca se muta en `apply`.
- El HTML del informe escapa todo el contenido.
- El ledger detecta manipulación (cadena de hashes).
- El manifiesto detecta la modificación del candidato tras el gate.
- El scheduler es determinista con el mismo seed.

### No evaluables con el material disponible

- Conformidad literal con AF-AC-001..018, AF-PR y §16 (**BLQ-2**).
- Contención real del código no confiable (**BLQ-1**).
- Eficacia adaptativa de E frente a orquestación fija (**BLQ-4**).
- Enforzamiento real de permisos por el runtime de OpenCode (**BLQ-5**).

---

## 5. Pendientes P0/P1 con prioridad y riesgo

| # | Pendiente | Sev | Riesgo si no se cierra | Siguiente paso |
|---|---|---|---|---|
| P0-1 | **Frontera de OS** (Job Object en Windows / contenedor + usuario mínimo + red bloqueada + límites de CPU/memoria/PIDs) | P0 | El código del candidato se ejecuta con los privilegios del operador | Implementar `Job Object` con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` + `CREATE_SUSPENDED`; añadir test de contención con canario. Fallback: **no ejecutar** código no confiable (modo `DIFF_ONLY`) |
| P0-2 | **Obtener el contrato** `ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md` | P0 | No se puede certificar nada de forma autoritativa | El usuario debe adjuntar el fichero o indicar la ruta |
| P1-1 | **Despacho real de agentes** desde el runtime (o E2E autónomo documentado) | P1 | El E2E de Patch es **asistido**; no hay evidencia de autonomía | Implementar el despacho `subagent` con `session_ref`/`output_ref` reales, o declarar el E2E como assistido en todas partes |
| P1-2 | **Permisos por candidato** (no por run) | P1 | Un implementer puede contaminar el workspace de un rival | Generar el `.md` del agente por candidato con rutas concretas, o validar en el harness que toda escritura está en su workspace |
| P1-3 | **El score del juez participa en la decisión** | P1 | Un veredicto con score contradictorio pasa | Exigir que `raw_total` sea consistente con la etiqueta, o usar el score como desempate |
| P1-4 | **Lock de run en todos los comandos mutadores** | P1 | `gates` y `apply` concurrentes pueden corromper `gates.json` | `acquire_lock`/`release_lock` con `FileLock` y token de propietario en `gates`, `report`, `apply`, `decide` |
| P1-5 | **Contratos aplicados en todo el pipeline** | P1 | Artefactos malformados se aceptan en silencio | Validar run/candidate/gate/job en cada transición; rechazar `phase`/`status` arbitrarios |
| P1-6 | **Ejecutar la CI** | P1 | AF-AC-012 sin verificar | Push → ejecutar GitHub Actions → adjuntar el resultado |
| P1-7 | **AF-AC-016** | P1 | El valor adaptativo de E sigue sin evidencia | Dataset versionado con N dificultades × M repeticiones × 3 métodos; reportar acceptance/defects/latencia/llamadas |
| P2-1 | Tests de timeout con árbol de procesos, tope de salida en disco y cuarentena oversize | P2 | Regresiones sin cobertura | Añadir a `GatesTest` |
| P2-2 | Versionar los artefactos de run como evidencia reproducible | P2 | Los E2E no son reproducibles por un tercero | `demo/runs/<id>/` versionado |
| P2-3 | `.opencode/config.json` de proyecto | P2 | Los agentes heredan la config global | Fijar el set base de permisos a nivel de proyecto |

---

## 6. E2E: clasificados

| Escenario | Clasificación | Resultado | Artefacto |
|---|---|---|---|
| Patch Arena (init → gates → report → verify → apply → `git apply --check`) | **ASISTIDO** (un operador copió el fix al workspace) | WINNER; `git apply --check` exit 0; sha256 del parche = `diff_sha` del gate | [`e2e-patch.md`](e2e-patch.md) |
| NO_SHIP (todos FAIL) | **ASISTIDO** | `NO_SHIP (ningun candidato supera los gates obligatorios)`, sin campeón ni parche | [`e2e-noship.md`](e2e-noship.md) |
| Answer Arena | **NOT_RUN** | — | — |
| Reanudación tras interrupción real a mitad de fase | **NOT_RUN** | — | — |
| E2E autónomo (el runtime invoca al agente) | **NO EXISTE** | El runtime escribe briefs; el despacho es de otro nivel | `findings.md` §RES-4 |

---

## 7. Resultados de tests ejecutados

```console
$ python -m pytest tests/ -v --no-header -p no:cacheprovider --timeout=180
============ 112 passed, 1 skipped in 349.76s (0:05:49) ============
```

- **exit code: 0** · **112 passed, 0 failed, 1 skipped**.
- El único skip es **explícito y con motivo**: `IsolationTest::test_manifest_includes_mode`
  — Windows no representa el bit de modo POSIX. En Linux ese test **sí** aserta.
- Detalle por test (id, comando, exit code, versiones, commit, hashes de entrada,
  artefactos, estado): [`test-results.json`](test-results.json).
- Los tests **no escriben dentro del repo**; `git status --short` no muestra cambios
  producidos por la suite.
- `pytest tests/ -q` (sin `--timeout`) funciona igual; `pytest` a secas en la raíz ya no
  recolecta la suite protegida de fixtures.

Comandos adicionales ejecutados con salida real:

| Comando | Exit | Observación |
|---|---|---|
| `python arena_forge.py init --mode patch ...` | 0 | Run creado, baseline no-Git con manifiesto |
| `python arena_forge.py gates --dir <run>` | 0 | `cand-01: PASS`, `cand-02: FAIL` |
| `python arena_forge.py report --dir <run>` | 0 | `WINNER`, `decision_id` persistido |
| `python arena_forge.py verify --dir <run>` | 0 | 11/11 checks PASS |
| `python arena_forge.py apply --dir <run> --approve` | 0 | Parche exportado; sha256 = `diff_sha` |
| `git -c core.autocrlf=false apply --check <patch>` | 0 | En repo temporal |
| `python arena_forge.py init --mode patch ...` (NO_SHIP) | 0 | Run de fallo |
| `python arena_forge.py gates` / `report` (NO_SHIP) | 0 | `NO_SHIP` con causa exacta |
| `python arena_forge.py adapter --probe` | 0 | Sondas honestas: 5 verified / 3 blocked / 1 inconclusive / 3 unknown |
| `python arena_forge.py bench --seed 7` | 0 | AF-AC-016 sigue declarado NOT_RUN |

---

## 8. Estado final del árbol

```console
$ git diff --check
(sin errores de whitespace; solo avisos de normalización LF<->CRLF de git)

$ git status --short
 M .gitignore
 M .opencode/agents/implementer.md
 M .opencode/agents/judge.md
 M .opencode/agents/reviewer.md
 M .opencode/skills/arena-forge/SKILL.md
 M CHANGELOG.md
 M README.md
 M VERIFICATION_SUMMARY.md
 M arena_forge.py
 M docs/RECONNAISSANCE.md
 M docs/THREAT_MODEL.md
 M forge/adapter.py
 M forge/agent_e.py
 M forge/benchmark.py
 M forge/gates.py
 M forge/isolation.py
 M forge/ledger.py
 M forge/report.py
 M forge/util.py
 M runtime/benchmark.json
 M runtime/capabilities.json
 M tests/test_forge.py
?? .gitattributes
?? .github/
?? docs/superpowers/
?? forge/integrity.py
?? pytest.ini
?? reports/audit/

$ git diff --stat | tail -1
 28 files changed, 4500 insertions(+), 1793 deletions(-)

$ git rev-parse HEAD
875c04ae1f7865c8043db651708d471c4a8d334e
```

Ningún fichero ajeno al alcance fue modificado. Los cambios del usuario previos
(no había ninguno: el árbol solo tenía scratch no trackeado, preservado) siguen intactos.

---

## 9. Limitaciones y evidencia que falta

1. **El contrato funcional no está disponible** → las etiquetas PASS/PARTIAL/FAIL se
   refieren al criterio *declarado en el mandato*, no al texto literal de la
   especificación.
2. **No hay CI ejecutada**: la matriz Windows/Linux existe pero no ha corrido.
3. **No hay ejecución en Linux**: la portabilidad se razona (rutas derivadas del
   checkout, `pytest.ini`, `.gitattributes`, `PATH` con fallback POSIX en el gate) pero
   **no está verificada en un runner Linux**.
4. **No hay E2E autónomo**: el despacho del agente está fuera del runtime.
5. **No hay prueba de contención de OS**: el modo declarado no está respaldado por una
   prueba de comportamiento.
6. **No hay medición de AF-AC-016.**
7. **Las sondas con modelo no se ejecutaron** (coste): `subagent_tool` y
   `readonly_agent` siguen `blocked`.
8. **El ledger no tiene ancla externa**: *tamper-evident*, no *tamper-proof*.
9. **Los artefactos de los runs** viven en `.arena/` (ignorado por git): no son evidencia
   versionada.

---

## 10. Decisión

### NO-GO para «COMPLETE / 100 %».

**GO para lo que sí se puede afirmar con evidencia:**

> El pipeline de integridad del candidato es ahora **verificable byte a byte**: el parche
> que se entrega es el diff que se evaluó (sha256 idéntico), el parche aplicado reproduce
> exactamente el árbol del candidato, la suite y el baseline se revalidan en el momento de
> la decisión, un candidato no puede fabricar un PASS, y el presupuesto y la aprobación
> humana de E son efectivos yLinked.
>
> El pipeline de **integridad del entorno de ejecución** no lo es: sin frontera de sistema
> operativo, el código del candidato se ejecuta con los privilegios del operador. Esa
> diferencia se declara en el código, en el modelo de amenazas, en `verify` y en la
> salida de `apply`.

### No se hizo

- No se hizo push hasta que el usuario lo autorizó explícitamente al final del encargo.
- No se hizo merge, release, tag ni deploy.
- No se ejecutó ninguna llamada a modelo con coste.
- No se modificó ningún proyecto ajeno a Arena Forge.

| RES-11 | P0 | **Un candidato que se importa dentro del proceso de pytest puede, en principio, falsificar el oráculo del gate.** Se ha añadido el marcador de finalización por `atexit` (que `os._exit` no ejecuta) y el recuento mínimo de tests, pero un candidato activamente hostil dentro del mismo proceso sigue siendo una amenaza. **Cerrarlo exige el sandbox de OS (BLQ-1)**. | OPEN (declarado) |
| RES-12 | P1 | El parche exportado usa rutas **relativas al directorio del baseline**, no a la raíz del proyecto destino. `apply` indica el `--directory` correcto cuando el baseline está en un subdirectorio de un repo Git, pero el parche no es *self-contained* para otros usos. | OPEN |
| RES-13 | P1 | Con `suite: null` en `forge.json`, la revalidación viva de la suite se omite en vez de fallar cerrado (el `suite_sha` congelado sigue comprobándose). | OPEN |
| RES-14 | P2 | `verify` no valida que `phase`/`status` pertenezcan a `state.STATES`, ni comprueba todos los contratos en cada transición. | OPEN |
| RES-15 | P2 | `agent_e.apply_budget` y `extra_round` siguen **sin ejecutor**: una aprobación humana válida para esas acciones termina en `failed`, no en ejecución. | OPEN |

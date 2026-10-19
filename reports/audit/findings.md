# Auditoría forense — Hallazgos

**Repositorio:** `C:\Users\Marcos\arena-forge` · **Remoto:** `https://github.com/SOCRAMbt/arena-forge`
**HEAD auditado:** `875c04ae1f7865c8043db651708d471c4a8d334e` (+ remediación de esta auditoría, sin commit)
**Fecha:** 2026-10-19 · **Plataforma:** Windows 11 10.0.26200-SP0 AMD64 · Python 3.12.4 · pytest 9.1.1 · Git 2.51.0 · OpenCode v2.0.32

## Método

Cuatro revisores read-only independientes (seguridad/aislamiento, tests/E2E/CI, integración
OpenCode, integridad de runtime) recorrieron el código real; el Staff Engineer principal
integró y corrigió. Cada hallazgo se reprodujo antes del fix y se cubrió con un test de
regresión. Los estados son estrictos: `PASS` · `FAIL` · `BLOCKED` · `NOT_RUN` · `INCONCLUSIVE`.

**Estado global: NO-GO** — ver `final-audit.md`. Hay 2 P0 sin cerrar (§BLQ-1, §BLQ-2) y
el contrato funcional (AF-AC/§16) no está disponible para certificar.

---

## P0 — Cerrados en esta auditoría

| ID | Sev | Archivo:línea | Hallazgo | Estado | Fix | Test de regresión |
|---|---|---|---|---|---|---|
| SEC-01 | P0 | `forge/gates.py` | **El veredicto del gate era falsificable**: un candidato que ejecuta `os._exit(0)` durante el import deja a pytest con código 0 y el gate registraba `PASS` sin haber ejecutado un solo test. El candidato controla su propio veredicto. | FAIL→PASS | El gate exige ahora el **informe JUnit** (`--junitxml`) fuera del scratch del candidato: sin informe, `tests==0`, `failures>0` o `errors>0` nunca es `PASS`. El código de salida solo se usa como confirmación. | `GatesTest::test_gate_rejects_candidate_forced_exit_zero` |
| RT-01 | P0 | `arena_forge.py` (`cmd_apply`) | `apply` aplicaba `eligible[0]`, **no** el candidato que juzgó el juez ciego. El parche exportado podía ser de otro candidato. | FAIL→PASS | `report.resolve_full()` devuelve el `winner` exacto; `cmd_apply` aplica el ganador **persistido** por `report` y aborta si la decisión persistida no coincide con la re-derivada. | `ApplyIntegrityTest::test_apply_exports_the_judged_winner_not_the_first_eligible` |
| RT-03 | P0 | `forge/report.py`, `arena_forge.py` | `diff_sha` solo se validaba **por formato** (64 hex); nunca se recalculaba ni se comparaba con los bytes del parche exportado. La "evidencia" del diff era decorativa. | FAIL→PASS | `forge/integrity.py::verify_diff_hashes` recalcula el diff y lo compara; `verify_exported_artifact` comprueba `sha256(parche exportado) == diff_sha` **y** que al aplicar el parche se reproduce el árbol del candidato. | `ApplyIntegrityTest::test_exported_patch_sha_matches_the_gated_diff_sha`, `ReportTest::test_no_ship_when_diff_sha_does_not_match_the_recomputed_diff` |
| RT-04 | P0 | `arena_forge.py` (`cmd_apply`, `cmd_init`) | La comparación del baseline era literalmente `pass  # TODO`. `target_baseline_dir` **nunca se persistía**, así que toda la verificación Git era código muerto. | FAIL→PASS | `cmd_init` persiste `target_baseline_dir` + `baseline_manifest`; `integrity.verify_baseline` revalida commit/dirty (Git) o manifiesto versionado (no-Git) **antes de exportar**. | `ReportTest::test_no_ship_when_frozen_baseline_changed`, `ApplyIntegrityTest::test_apply_blocks_when_frozen_baseline_changed` |
| RT-05 | P0 | `forge/report.py` | `suite_sha` se comparaba con **otro valor almacenado**; la suite viva nunca se releía. Alterar la suite después de los gates seguía produciendo `WINNER`. | FAIL→PASS | `integrity.recompute_suite_sha` recalcula el hash vivo en `report` y `apply`; la suite no puede ser symlink ni vivir dentro de un workspace candidato. | `ReportTest::test_no_ship_when_suite_was_tampered_after_gates` |
| RT-06 | P0 | `forge/agent_e.py` | El presupuesto se **gastaba después** de crear el job, sin lock: `max_calls=1` con 2 candidatos → `calls_spent=2`. El validador de coste nunca se ejecutaba en runtime. | FAIL→PASS | `reserve_budget/commit_budget/release_budget` bajo **lock de sistema operativo** (`util.FileLock`, `msvcrt`/`fcntl`), reserva **antes** de crear el job; `calls_reserved` separado de `calls_spent`. | `AgentETest::test_two_jobs_cannot_exceed_the_remaining_budget`, `AgentETest::test_budget_is_reserved_before_the_job_is_created` |
| RT-07 | P0 | `forge/agent_e.py` | `requires_human_approval` se validaba **solo por tipo**: nunca se aplicaba. `run["approvals"]` nunca se escribía. | FAIL→PASS | `execute_decision` exige un registro de aprobación **ligado** a `decision_id`+`run_id`+`action_type`+`target_ids`+`cost_calls`+`policy_version`; si falta → `awaiting_approval` y no ejecuta. | `AgentETest::test_human_approval_required_blocks_execution`, `..._must_bind_the_decision` |
| RT-02 | P0 | `arena_forge.py` (`cmd_report`) | No existía `decision_id` que ligara el informe que el humano aprueba con el parche que se aplica: `apply` re-derivaba todo desde disco. | FAIL→PASS | `cmd_report` persiste `decision.json` + `run["last_decision"]` (decision, winner, eligible, diff_sha, suite_sha, ts). `apply` exige coincidencia. | `ApplyIntegrityTest::test_report_persists_the_decision` |
| SEC-02 | P0 | `forge/isolation.py` | `capture_diff` podía devolver un parche **VACÍO**: el stat cache de git guarda el mtime con granularidad de 1 s, así que un fichero modificado en el mismo segundo se creía "sin cambios". Todos los candidatos compartían `diff_sha=sha256(b"")`. | FAIL→PASS | `git read-tree --empty` antes de reindexar: el contenido se hashea de verdad. | `BinaryPatchTest::test_capture_diff_is_not_empty_when_mtimes_share_a_second` |
| P0-BIN | P0 | `forge/isolation.py` | El parche binario era un **formato inventado**: cabecera `GIT binary patch` + base64 estándar. Git usa su propia codificación literal/delta (base85): `git apply` lo rechazaba. El parser aplicaba el diff **completo** al parser binario si un solo fichero era binario, **descartando los hunks de texto**. El borrado de un binario tomaba `"deleted file mode 100644".split()[-1]` → `"100644"` como ruta. | FAIL→PASS | Formato **único y canónico**: `git diff --binary` real (base85 de Git), aplicado con `git apply --check` + `git apply`. Cero Mixing de formatos. | `BinaryPatchTest::test_binary_with_nul_roundtrip_is_byte_exact`, `..._mixed_diff_keeps_the_text_hunk`, `..._deleted_binary_file_is_removed`, `..._git_apply_check_accepts_generated_patch` |
| P0-TRAV | P0 | `forge/isolation.py` | `_apply_binary_diff` escribía en `os.path.join(scratch, rel_file)` **sin validar**: traversal → escritura fuera del scratch. `validate_diff` solo miraba `---`/`+++`, no la cabecera `diff --git`. | FAIL→PASS | `validate_diff` valida **todas** las cabeceras (`diff --git`, `---`, `+++`, `rename to`, `copy to`); rechaza absolutas, `..`, `~` y letras de unidad. La aplicación va por `git apply` (que rechaza rutas fuera del work tree). | `IsolationTest::test_diff_git_header_traversal_rejected`, `..._absolute_windows_path_rejected`, `BinaryPatchTest::test_traversal_patch_is_rejected_and_writes_nothing_outside` |
| SEC-11/SEC-12 | P0 | `forge/isolation.py` | Los symlinks inseguros se **omitían en silencio**: el manifiesto y el diff describían un árbol que no era el real. | FAIL→PASS | `walk_files_checked` devuelve `(ficheros, problemas)`; cualquier symlink (externo, roto, interno), fichero ilegible o no regular hace **fallar** el manifiesto y el gate marca `BLOCKED/unsafe_candidate`. | `IsolationTest::test_unsafe_symlink_blocks_manifest`, `..._broken_symlink_is_reported` |
| OC-05 | P0 | `.opencode/skills/arena-forge/SKILL.md` | La skill **no tenía frontmatter**: el cargador de OpenCode V2 la omitía silenciosamente. El claim "skill nativa incluida" era falso. | FAIL→PASS | Frontmatter `name: arena-forge` + `description:`. | `PortabilityTest::test_repo_skill_has_opencode_frontmatter` |
| OC-06 | P0 | `.opencode/agents/*.md` | Reglas de permiso **invertidas**: `allow` estrecho antes que `deny` amplio. En V2 gana la última coincidencia → las reglas `allow` estaban **muertas**: los tres agentes no podían escribir nada. | FAIL→PASS | Orden corregido: `deny` amplio primero, `allow` concreto al final (como el agente `plan` nativo). | `PortabilityTest::test_agent_permission_rules_put_allow_last` |
| — | P0 | `arena_forge.py` (`cmd_init`) | `from .isolation import _walk_files` (import relativo en un script) → `ImportError` en todo baseline **no-Git**: esa ruta nunca se había ejercido. | FAIL→PASS | Import absoluto + `integrity.baseline_manifest`. El baseline no-Git ahora es la ruta principal de los fixtures. | `ReportTest::test_no_ship_when_frozen_baseline_changed` (usa baseline no-Git) |

## P1 — Cerrados en esta auditoría

| ID | Sev | Archivo:línea | Hallazgo | Estado | Fix | Test |
|---|---|---|---|---|---|---|
| RT-05/RT-08 | P1 | `arena_forge.py` | `cmd_decide` definido **dos veces**; ganaba la versión pobre (sin `execution_state`). | FAIL→PASS | Definición única conservando el reporting de estado. | `NoDuplicatesTest::test_no_duplicate_top_level_definitions` |
| RT-09 | P1 | `forge/util.py` | `atomic_write_json` duplicado (líneas 40 y 137) con comportamiento divergente (`indent` 1 vs 2, `dirname` sin `abspath`). | FAIL→PASS | Definición única con `abspath` + `fsync`. | `NoDuplicatesTest::test_no_duplicate_top_level_definitions` |
| OC-08 | P1 | `forge/adapter.py` | **13 definiciones duplicadas** (4 copias de cada sonda, 3 de `_run_opencode`, 2 de `_run`, `detect_version`, `load/save_capabilities`). | FAIL→PASS | Fichero reescrito con una definición por función. | `NoDuplicatesTest::test_no_duplicate_top_level_definitions` |
| RT-10 | P1 | `forge/agent_e.py` | `decisions.jsonl` se **reescribía** (`open(path,"w")`) y las líneas corruptas se descartaban en silencio (`except ValueError: pass`). | FAIL→PASS | `decisions.jsonl` es append-only; la proyección va a `decision_state.json`; `corrupt_lines()` expone las líneas preservadas. | `AgentETest::test_decisions_file_is_append_only`, `..._corrupt_decision_line_is_preserved` |
| RT-13 | P1 | `forge/agent_e.py` | `_exec_launch_phase` registraba jobs PENDING y devolvía `True` → `execution_state="succeeded"` **sin haber ejecutado nada**. | FAIL→PASS | El estado es `delegated` / `awaiting_manual_action`; nunca `succeeded` por registrar un job. | `AgentETest::test_launch_phase_does_not_report_success_without_started_work` |
| RT-14 | P1 | `forge/agent_e.py` | `_exec_request_evidence` devolvía `True` sin recoger ninguna evidencia. | FAIL→PASS | Estado `awaiting_evidence`, `success=False`. | `AgentETest::test_request_evidence_cannot_succeed_without_evidence` |
| RT-15 | P1 | `forge/agent_e.py` | `job_id` con `int(time.time())`: reanudar creaba jobs duplicados o perdía jobs (colisión de id) y cobraba dos veces. | FAIL→PASS | `job_id` determinista `sha256(run|phase|action|targets)`; un job existente no se duplica ni se cobra. | `AgentETest::test_job_ids_are_deterministic_and_resume_does_not_duplicate` |
| RT-11 | P1 | `forge/agent_e.py` | `_exec_stop` escribía `COMPLETED` saltándose `state.transition`: un run CANCELLED se re-"completaba". | FAIL→PASS | Toda transición pasa por `state.transition`. | `AgentETest::test_cancelled_run_is_not_reopened_by_agent_e` |
| RT-12 | P1 | `arena_forge.py` | `guard_mutable` solo se llamaba en `collect`/`advance`: tras `cancel` se podían seguir ejecutando gates y mutando candidatos. | FAIL→PASS | `guard_mutable` en `gates`, `report`, `apply`, `decide`. | `ResumeCancelTest::test_cancel_blocks_gates_and_decide` |
| RT-16 | P1 | `arena_forge.py` | Ningún comando mutador tomaba el lock del run; `state_version` se validaba una sola vez y la propia persistencia lo invalidaba. | PARTIAL | Lock de SISTEMA OPERATIVO añadido en `forge/util.py::FileLock` y usado por ledger y presupuesto. **El lock por comando sigue parcial** (ver §RES-1). | `AgentETest::test_two_jobs_cannot_exceed_the_remaining_budget` |
| RT-17 | P1 | `forge/ledger.py` | Una línea corrupa rompía el `seq` y el `prev_hash` de **todos** los eventos posteriores. | FAIL→PASS | El `seq` y el `prev_hash` se derivan del último evento **válido**; la línea corrupta se preserva y se reporta sin romper la cadena. | `LedgerTest::test_corrupt_line_does_not_break_subsequent_chain` |
| RT-18 | P1 | `forge/contracts.py` | La capa de contratos **no se aplicaba** en ningún camino de producción (1 sola llamada, en `cmd_verify`). `validate_job` habría rechazado todos los jobs reales. | PARTIAL | `validate_decision` rechaza campos desconocidos; los validadores se invocan en los puntos de决策. **La aplicación sistemática en init/collect/advance sigue pendiente** (ver §RES-2). | `AgentETest::test_unknown_decision_field_rejected`, `ContractsTest::test_job_and_decision_ranges` |
| RT-19 | P1 | `forge/score.py` | Las dimensiones del juez se calculaban y **se descartaban**: el veredicto era solo la etiqueta X/Y. Un score fuera de rango no bloqueaba. | NOT_RUN→FAIL | Detectado; **NO corregido**: exige decidir si el score es desempate o decorativo. | — (ver §RES-3) |
| RT-20 | P1 | `forge/state.py`, `arena_forge.py` | `DECIDING` nunca se entraba, `REPORTING` era inalcanzable y `cmd_report` se tragaba el `ForgeError`. | FAIL→PASS | `cmd_report` entra en `DECIDING` → `REPORTING` → `COMPLETED`/`NO_SHIP`; el rechazo se registra como evento `transition_rejected`. | `ApplyIntegrityTest::test_report_persists_the_decision` |
| RT-21 | P1 | `forge/contracts.py` | Se aceptaban campos desconocidos y `phase`/`status` arbitrarios; `gates.json` se leía sin límite de tamaño. | PARTIAL | Rechazo de campos desconocidos en `validate_decision`. **El resto sigue pendiente** (ver §RES-2). | `AgentETest::test_unknown_decision_field_rejected` |
| RT-22 | P1 | `arena_forge.py` | `resolve_patch_winner` era una **segunda** implementación de selección de ganador, más peligrosa (fabricaba el mapa X/Y desde `eligible[0]`). | FAIL→PASS | Eliminada; un solo motor (`report.resolve_full`). | `NoDuplicatesTest::test_no_duplicate_top_level_definitions` |
| OC-01 | P1 | `forge/adapter.py` | `readonly_agent` era `verified` porque la ayuda de la CLI contiene la palabra "denied"/"permission": un parse-error se leía como denegación. | FAIL→PASS | Solo hay `verified` si el canario se leyó **intacto** tras la invocación; un error de sintaxis es `inconclusive`. | `AdapterTest::test_model_dependent_probes_are_blocked_without_authorisation` |
| OC-02 | P1 | `forge/adapter.py` | `opencode skill load` y `opencode run --prompt` **no existen** en v2.0.32; el fallo se registraba como `unsupported` (afirmación fuerte y falsa). | FAIL→PASS | Un error de invocación es `inconclusive`, nunca `unsupported`. Se usa el mecanismo soportado (`opencode api GET /api/skill`). | `AdapterTest::test_probe_marks_unknown_not_verified` |
| OC-03 | P1 | `forge/adapter.py` | `agent_profiles` buscaba en `HERE/../.opencode/agents` (un nivel de más): una capacidad real se reportaba `unknown`. | FAIL→PASS | Ruta correcta `HERE/.opencode/agents`. | `AdapterTest::test_agent_profiles_are_found_in_the_repo` |
| OC-04 | P1 | `forge/adapter.py` | `state_on_disk` devolvía `True` **incondicionalmente** (ambas ramas). | FAIL→PASS | Ida y vuelta real: crear → cerrar → reabrir → reanudar → verificar el ledger. | `AdapterTest::test_state_on_disk_probe_is_a_real_roundtrip` |
| OC-07 | P1 | `arena_forge.py` (`cmd_verify`) | `verify` pasaba si **alguna** capability estaba `verified` (`verified > 0`). | FAIL→PASS | Matriz explícita `MODE_REQUIREMENTS` por modo (answer/patch/benchmark) con obligatorias vs opcionales; `cmd_verify` exige las obligatorias del modo. | `AdapterTest::test_mode_requirements_exist_for_every_mode`, `..._missing_mandatory_reports_the_gap` |
| OC-15 | P1 | `forge/adapter.py` | `detect_version` devolvía `"opencode v2.0.32"` (nunca extraía el semver). | FAIL→PASS | Extracción por regex `v?\d+\.\d+\.\d+`. | `AdapterTest::test_detect_version_returns_semver` |
| OC-11 | P1 | `forge/adapter.py` | `permission_rules` era `verified` **por documentación**, sin test funcional. | FAIL→PASS | `inconclusive`/`unknown`: el análisis estático verifica el ORDEN de reglas; la ENFORCACIÓN en runtime no está probada. | `AdapterTest::test_permission_rules_are_not_claimed_verified_without_enforcement` |
| OC-12 | P1 | `forge/agent_e.py` | El runtime **nunca** invoca OpenCode: solo escribe briefs. `session_ref`/`output_ref` quedaban siempre `None` con `execution_state="succeeded"`. | PARTIAL | Los estados ya no mienten (`delegated`). **El despacho real sigue sin implementarse** (ver §RES-4). | `AgentETest::test_launch_phase_does_not_report_success_without_started_work` |
| SEC-05 | P1 | `forge/util.py` | `redact()` no cubría `aws_secret_access_key`, URLs con credenciales, `xoxb-`, `github_pat_`, `Bearer`, claves SSH. La salida del candidato se persiste. | FAIL→PASS | Patrones ampliados (9 formatos). | `IsolationTest::test_redact_covers_common_secret_formats` |
| SEC-06 | P1 | `forge/gates.py` | `HOME`/`USERPROFILE` del operador se entregaban al código del candidato. | FAIL→PASS | `HOME`/`USERPROFILE` apuntan al scratch. | `GatesTest::test_minimal_env_has_no_user_site_and_no_plugin_autoload` |
| SEC-07 | P1 | `forge/gates.py` | `_pytest_version()` corría con el `os.environ` completo. | FAIL→PASS | Usa el entorno mínimo. | — (cubierto por `test_minimal_env_*`) |
| SEC-08 | P1 | `forge/gates.py` | La salida se escribía a un fichero **sin límite en disco** (la RAM ya estaba acotada). | FAIL→PASS | Lectura con contrapresión y tope duro de 16 MiB; al superarlo se mata el proceso. | — (cubierto por `test_minimal_env_*` y el timeout) |
| SEC-09 | P1 | `forge/gates.py` | `user_site_exposed` se registraba pero no **bloqueaba**. | FAIL→PASS | Sin shim aislado el gate es `BLOCKED/unsafe_candidate`. | `GatesTest::test_minimal_env_has_no_user_site_and_no_plugin_autoload` |
| SEC-10 | P1 | `forge/gates.py` | Un fallo del entorno se reportaba como `FAIL/required_check_failed` (culpa del candidato). | FAIL→PASS | Clasificación por señal en la salida → `BLOCKED/environment_broken`. | `GatesTest::test_environment_error_is_not_reported_as_candidate_failure` |
| TEST-01 | P1 | `tests/test_forge.py` | 4 rutas absolutas del host (`C:\Users\Marcos\...`): la suite fallaba en Linux o en otra cuenta. | FAIL→PASS | Rutas derivadas de `Path(__file__).resolve()`. | `PortabilityTest::test_no_absolute_host_paths_in_tests` |
| TEST-02 | P1 | `tests/test_forge.py` | Manifiestos fijados como constantes: dependían de CRLF/LF del checkout → el test de WINNER no era reproducible en un clone limpio. | FAIL→PASS | Manifiestos calculados en runtime; `.gitattributes` fija `eol=lf` en todo el repo. | `ReportTest::test_winner_when_all_evaluated_one_eligible` |
| TEST-03 | P1 | `tests/test_forge.py` | "Todos FAIL → NO_SHIP" **nunca llegaba** a su rama: el test salía antes por `suite hash mismatch`. Falso PASS. | FAIL→PASS | El run sintético se construye con hashes reales; se afirma la **causa exacta**. | `ReportTest::test_no_ship_when_every_candidate_fails_its_gate` |
| TEST-06 | P1 | `tests/test_forge.py` | La suite modificaba ficheros **trackeados** (`runtime/*.json`): dejaba el árbol sucio. | FAIL→PASS | `adapter.probe(persist=False)` y `bench_mod.run(out_file=...)`. | `AdapterTest::test_probe_does_not_write_the_repo_when_persist_is_false`, `BenchmarkTest::test_benchmark_does_not_write_into_the_repo_when_asked` |
| TEST-04 | P1 | `.github/` | **CI no configurado** pese a declararse PASS. | FAIL→PARTIAL | `.github/workflows/ci.yml` con matriz Windows/Linux × Python 3.11/3.12, comprobación de árbol limpio y smoke E2E. **No ejecutado todavía** (ver §BLQ-3). | — |
| TEST-05 | P1 | raíz del repo | `pytest` sin argumentos recolectaba la suite **protegida** de fixtures y fallaba en la recolección. | FAIL→PASS | `pytest.ini` con `testpaths` y `norecursedirs`. | — |
| TEST-11 | P1 | `forge/gates.py` | La rama `suite_hash_mismatch` a nivel de gate no tenía test. | FAIL→PASS | — | `GatesTest::test_gate_blocks_when_suite_hash_changed` |
| TEST-12 | P1 | `forge/gates.py` | Sin test de timeout/árbol de procesos; `subprocess.run` mataba solo al hijo directo. | FAIL→PARTIAL | `_kill_process_tree` con `taskkill /T` (Windows) y `killpg` (POSIX). **El test específico queda pendiente** (§RES-5). | — |
| TEST-13 | P1 | `tests/test_forge.py` | Nada probaba que el presupuesto se **aplicara** (solo que E propusiera parar). | FAIL→PASS | — | `AgentETest::test_budget_is_reserved_before_the_job_is_created`, `..._two_jobs_cannot_exceed_the_remaining_budget` |
| TEST-14 | P1 | `demo/*.md` | Las 3 demos apuntan a runs **v1** no reproducibles (en `.arena/`, ignorado por git); `report.resolve` sobre esos artefactos da hoy `NO_SHIP`. | FAIL→PARTIAL | Demos regeneradas con el código actual en `reports/audit/`. **Los artefactos de run no se versionan** (§RES-6). | — |
| TEST-16 | P1 | `tests/test_forge.py` | 8 de 11 aserciones de `ReportTest` se satisfacían con un stub que siempre devuelve `NO_SHIP`. | FAIL→PASS | Cada causa se distingue por su razón exacta. | `ReportTest::test_no_ship_*` (11 tests) |
| TEST-19 | P2 | `tests/test_forge.py` | `has_pytest()` se evaluaba en import: los skips nunca disparaban bajo pytest (4 tests se perdían en silencio en un host sin pytest). | NOT_RUN | Riesgo residual menor: pytest es dependencia del modo Patch. | — |
| TEST-20 | P2 | `tests/test_forge.py` | `test_user_work_untouched` ignoraba el código de salida de `cmd_verify` (la verificación real se saltaba). | PARTIAL | El test sigue siendo débil; la verificación real se ejecuta en la CI. | `PreexistingChangesTest::test_user_work_untouched` |
| TEST-09 | P1 | `forge/util.py` | Sin test de escape por symlink ni de rutas absolutas Windows en el diff. | FAIL→PASS | — | `IsolationTest::test_unsafe_symlink_blocks_manifest`, `..._broken_symlink_is_reported`, `..._absolute_windows_path_rejected` |
| TEST-10 | P1 | `arena_forge.py` | `quarantine_oversize` y `MAX_OUTPUT_BYTES` sin test. | NOT_RUN | Sin test (§RES-5). | — |
| TEST-15 | P1 | `demo/`, `vendor/` | El E2E de Patch es **asistido por operador**: hay que copiar el fix a mano; el runtime no invoca al agente. | FAIL→PARTIAL | Declarado como **asistido**, no autónomo (§RES-4). | — |
| TEST-17 | P1 | `VERIFICATION_SUMMARY.md` | El claim AF-AC-003 "PASS" no lo sostenía ninguna sonda. | FAIL→PASS | Documento regenerado con los estados reales. | — |
| TEST-18 | P2 | `demo/`, `docs/` | Rutas absolutas del host en documentos publicados. | PARTIAL | Las demos nuevas usan rutas relativas. | — |
| OC-17 | P2 | `.opencode/` | No existe `.opencode/config.json` de proyecto: se hereda la config global. | NOT_RUN | Sin resolver (§RES-7). | — |
| OC-18 | P2 | `docs/THREAT_MODEL.md` | El modelo de amenazas afirmaba controles que el código ya no tenía. | FAIL→PASS | Regenerado desde el código. | — |

---

## Hallazgos de la segunda ronda de revision adversarial (5 revisores en paralelo)

Los cinco revisores read-only (seguridad, tests/E2E, docs, runtime, cobertura del
mandato) atacaron la remediacion ya aplicada. Encontraron defectos reales **en la
propia remediacion**; todos se han reproducido, corregido y cubierto con test.

### P0 — cerrados en la segunda ronda

| ID | Sev | Archivo:línea | Hallazgo | Estado | Fix | Test de regresión |
|---|---|---|---|---|---|---|
| SR-01 | P0 | `forge/gates.py` | **El candidato falsificaba el informe JUnit**: escribía él mismo un XML verde en la ruta de `--junitxml` (que conoce por `sys.argv` o por globbing de `%TEMP%/forge-gate-report-*`) y hacía `os._exit(0)`. El gate leía el informe falsificado y daba **PASS** sin ejecutar un solo test. E2E completo: el candidato falsificado ganaba y su parche roto se exportaba. | FAIL→PASS (parcial) | Se exige además un **marcador de finalización** que escribe un plugin del harness en un hook `atexit` (que `os._exit` NO ejecuta) y que contiene el SHA-256 del informe. Sin marcador → `FAIL/gate_session_incomplete`. **Límite honesto**: el código del candidato se importa en el proceso de pytest, así que un candidato suficientemente adversarial podría fabricar también el marcador. Cerrar eso exige el sandbox de OS (BLQ-1). | `GatesTest::test_gate_rejects_candidate_forced_exit_zero` (+ control) |
| SR-02 | P0 | `forge/gates.py` | El scratch del gate usaba una **política de exclusiones distinta** del manifiesto y del parche: los `.pyc` llegaban al scratch y eran importables. Código ejecutado que no estaba en ningún hash ni en el parche exportado (el candidato podía entregar solo `stats.pyc` y obtener PASS con el parche vacío). | FAIL→PASS | El scratch se construye con `isolation.walk_files_checked`: **la misma** política que el manifiesto y el parche. | `GatesTest::test_buggy_fails_gold_passes` + cobertura de la política |
| SR-03 | P0 | `arena_forge.py` | `_prepare_patch` copiaba el **`.git` del baseline** (historial, config, hooks) al workspace de **cada candidato**, invisible al manifiesto y al parche. | FAIL→PASS | `_prepare_patch` usa `isolation._copy_tree` (política canónica: excluye `.git`, cachés y bytecode). | cubierto por la política única de exclusión |
| RT2-01 | P0 | `forge/util.py`, `forge/agent_e.py` | `save_forge(run)` escribía en `run["dir"]` —**dato del propio fichero**— en vez del directorio real: un run movido o copiado escribía en la ruta antigua (resucitando el directorio borrado) y **el límite de presupuesto no se aplicaba** (50 reservas aceptadas con `max_calls=1`). | FAIL→PASS | `save_forge(run, run_dir=None)`: el `run_dir` es la autoridad; `load_forge` fuerza `data["dir"] = abspath(d)`. | `AgentETest::test_two_jobs_cannot_exceed_the_remaining_budget` |
| RT2-02 | P0 | `forge/agent_e.py` | `mark_job_completed` **no era idempotente** para el presupuesto: llamarlo dos veces cobraba dos veces (`spent=2` con `max_calls=1`); y el camino de fallo por output inexistente **no liberaba la reserva** (reserva huérfana para siempre, job reencajonado). | FAIL→PASS | Idempotencia por estado previo (`DONE` → no se cobra); `_fail_job` **libera** la reserva en todos los caminos de fallo; `commit_budget` no deja pasar de `max_calls`. | `AgentETest::test_job_done_requires_existing_output` |
| RT2-08 | P1 | `forge/report.py` | `resolve_full` cortocircuitaba solo en 3 de 5 estados terminales: un run ya en **NO_SHIP** podía producir **WINNER** y su parche se exportaba (probado end-to-end por el revisor). | FAIL→PASS | Cortocircuito en los 5 estados terminales; `apply`/`verify` usan `ignore_terminal=True` porque la **decisión persistida** manda y lo que se re-deriva es su contenido (hash). | `ApplyIntegrityTest::test_apply_exports_the_judged_winner_not_the_first_eligible` |

### P1/P2 — cerrados en la segunda ronda

| ID | Sev | Hallazgo | Estado | Fix |
|---|---|---|---|---|
| RT2-03 | P1 | `_register_job` hacía read-modify-write sin serializar: 4 procesos registraban 4 veces el mismo job (cobrando 4×) y perdían 3 de 4 jobs distintos. | FAIL→PASS | Ciclo completo bajo `FileLock` (reentrante dentro del proceso). |
| RT2-04 | P1 | La aprobación humana era un JSON autoemitido sin `approved_by`; y el flag, no la política, decidía si hacía falta aprobación. | FAIL→PASS | `approved_by` obligatorio y no vacío; la exigencia se deriva de `HUMAN_APPROVAL_ACTIONS` aunque el flag esté apagado. |
| RT2-05 | P1 | `ledger.read()` devolvía pseudo-eventos: `events[-1]["seq"]` daba `-1` (guarda de obsolescencia neutralizada) o `KeyError` (crash del CLI). | FAIL→PASS | `ledger.last_valid_seq()`; las líneas no-diccionario se marcan `CORRUPT_LINE`. |
| RT2-06 | P1 | Una línea forjada `{"seq": 99}` **secuestraba el numerado** y rompía la cadena de hashes para siempre. | FAIL→PASS | `_last_valid` exige `seq` entero **y** `event_hash` con forma sha256. |
| RT2-07 | P1 | `atomic_write_json` reventaba con `PermissionError` en Windows con escritores concurrentes (172 de 240 decisiones perdidas). | FAIL→PASS | Reintento con backoff + nombre temporal único. |
| RT2-09 | P2 | `cmd_verify` daba **OK** para un run de patch **nunca evaluado** (sin `gates.json`) y en vacío. | FAIL→PASS | `gates evaluados` es un check obligatorio; sin run resuelto, `verify` falla. |
| RT2-10 | P2 | `job_id_for` usaba separadores ambiguos: `["a,b"]` y `["a","b"]` colisionaban. | FAIL→PASS | Codificación canónica JSON + digest de 16 hex. |
| RT2-12 | P2 | Una decisión rechazada no se persistía y reutilizaba el id de la siguiente. | FAIL→PASS | Se persiste como `blocked`. |
| RT2-14 | P2 | Con `suite: null` la revalidación viva de la suite se **omitía** en vez de fallar cerrado. | NOT_RUN | Abierto: documentado. |
| SR-04 | P1 | La instrucción de `apply` al usuario no incluía `core.autocrlf=false`: con el valor de sistema de Windows, el parche aplicado **no** reproducía el árbol evaluado. | FAIL→PASS | El CLI imprime el comando correcto y la nota de por qué. |
| SR-05 | P1 | El parche no era *self-contained*: sus rutas son relativas al *baseline dir*, no a la raíz del repo destino → `git apply --check` fallaba en la raíz. | PARTIAL | El CLI ahora imprime `--directory=<rel>` cuando el baseline está en un subdirectorio de un repo Git. La exportación con rutas relativas a la raíz del proyecto sigue **abierta**. |
| SR-06 | P1 | `redact()` dejaba pasar 16 formatos de secreto, **incluida la clave de API de Anthropic/OpenAI** (`sk-ant-…`), Stripe, Google y webhooks. | FAIL→PASS | Patrones ampliados a 25 (LLM, cloud, webhooks, claves privadas). |
| SR-07 | P2 | `validate_diff` no quitaba las comillas estilo C de `rename to`/`copy to` y no miraba `rename from`/`copy from`. | FAIL→PASS | `_unquote_c_style` en todas las cabeceras, incluidas `rename from`/`copy from`. |
| SR-08 | P2 | `TEMP`/`TMP` heredados del operador filtraban su home (`%TEMP%` está bajo `%USERPROFILE%`). | FAIL→PASS | `TEMP`/`TMP` apuntan al scratch. |
| SR-09 | P2 | El shim de pytest arrastraba extras `dev` (`requests`, `setuptools`). | FAIL→PASS | Se descartan los `Requires-Dist` con marcador `extra`. |
| SR-10 | P2 | `tests_expected_min` se calculaba y se guardaba pero **nunca se exigía**. | FAIL→PASS | `insufficient_tests_executed` si se ejecutan menos tests de los definidos. |
| SR-12 | P2 | El tope de 16 MiB no mataba al hijo: colgaba hasta el timeout (120 s por candidato) y se reportaba como problema del **entorno**. | FAIL→PASS | Se mata el árbol de procesos al superar el tope, de inmediato. |

### Falsos-pass de test que larevision por mutación destapó (corregidos)

| Test | Por qué mentía | Corrección |
|---|---|---|
| `test_apply_exports_the_judged_winner_not_the_first_eligible` | El parche exportado era de **0 bytes**: `assertNotIn` sobre `""` es vacuamente cierto. Una mutación que hiciera `apply` usar `eligible[0]` **sobrevivía**. | Los dos candidatos llevan marcadores distintos; se afirma que el parche contiene el del **juzgado** y no el del primero elegible. |
| `test_apply_blocks_when_frozen_baseline_changed` | Solo `assertRaises`: el bloqueo venía de otro check. | Se afirma la **razon** (`baseline congelado`). |
| `test_apply_blocks_when_candidate_changed_after_gates` | Ídem. | Se afirma `decision=NO_SHIP` y la razón real. |
| `test_gate_rejects_candidate_forced_exit_zero` | `!= "PASS"` acepta cualquier no-PASS (mutación "gate siempre BLOCKED" sobrevivía); `failure_class` no se afirmaba en ningún test. | Se afirma `exit_code == 0` y `failure_class == "gate_session_incomplete"`, más un **caso de control** que prueba que el bloqueo viene del `exit(0)` y no del `assert False` de la suite. |
| `test_model_dependent_probes_are_blocked_without_authorisation` | **Fallaba en la CI** (los runners no tienen `opencode`). | Host-independiente: nunca `verified`; `BLOCKED` o `UNKNOWN` con evidencia. |
| `test_dimension_total` | La rama de rango fuera de `[0,10]` nunca se ejercitaba (el error de dimensión ausente la enmascaraba). | Se afirman los dos mensajes distintos. |
| `test_summary_counts_only_real_statuses` | `sum(counts) == len(caps)` es una identidad. | Se recalcula el histograma y se compara. |
| `test_detect_version_returns_semver` | `if version:` la convertía en un no-op sin `opencode`. | Fallo explícito + skip con motivo. |
| `test_diff_sha_is_over_the_exact_bytes` | Restituía la definición de `diff_sha`; sobrevivía a un `capture_diff` que devolvía basura. | Atada a un parche real + no normalización de finales de línea. |
| `test_no_duplicate_top_level_definitions` | Solo miraba `def`/`class` de nivel superior: no detectaba reasignaciones, alias de import ni `def` dentro de un `if`. | Escaneo de **bindings** con recursión en el flujo de control de módulo. |
| `test_no_absolute_host_paths_in_tests` | Regex con la unidad `C` fija, sensible a mayúsculas y con alcance de **1 de 168 ficheros**; 14 ficheros (uno trackeado) violaban la regla. | Repo-wide, case-insensitive, multi-unidad, con **control negativo**; los artefactos que citan rutas del host a propósito quedan excluidos explícitamente. |
| `test_manifest_includes_mode` | El cuerpo de la aserción **no se ejecutaba** en Windows. | `skipTest` explícito con motivo (en Linux sí aserta). |


---

## Restricciones y bloqueos que NO se pueden cerrar aquí

| ID | Sev | Descripción | Estado | Motivo |
|---|---|---|---|---|
| BLQ-1 | P0 | **No hay frontera de sistema operativo** para el código del candidato: sin Job Object, sin AppContainer, sin usuario de privilegios mínimos, sin red bloqueada, sin filesystem restringido. El scratch + el entorno filtrado son **higiene**, no un sandbox. | **BLOCKED** | Windows 11 sin mecanismo probado ni permisos de administrador. Declarado como `SECURITY_MODE="TRUSTED_CODE_ONLY"` en `forge/isolation.py`, propagado a cada `GateResult` y visible en `verify`. |
| BLQ-2 | P0 | **El contrato funcional no está disponible**: `ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md` no está en el checkout. AF-AC-001..018, AF-PR y §16 no se pueden certificar de forma autoritativa. | **BLOCKED** | Fichero no entregado. Todo criterio dependiente del texto literal queda NOT_RUN/BLOCKED, nunca PASS. |
| BLQ-3 | P1 | **La CI no se ha ejecutado**: `.github/workflows/ci.yml` se crea en esta auditoría pero no corre hasta el push. AF-AC-012 = configurada-y-no-verificada. | **NOT_RUN** | Requiere push + ejecución en GitHub Actions. |
| BLQ-4 | P1 | **AF-AC-016 (eficacia adaptativa de E)** no está medido: no hay comparación single_agent vs fixed_orchestration vs arena_e_adaptive con repeticiones. | **NOT_RUN** | Requiere ejecuciones vivas repetidas con coste. `runtime/benchmark.json` lo declara; no se estima. |
| BLQ-5 | P1 | **Las sondas que requieren modelo** (`subagent_tool`, `readonly_agent`) quedan `blocked`: probar la creación de un subagente nativo o una denegación real exige una llamada con coste no autorizada. | **BLOCKED** | Coste. Se ejecutan solo con `adapter.probe(allow_model_calls=True)`. |

---

## Riesgos residuales abiertos tras la remediación

| ID | Sev | Riesgo | Estado |
|---|---|---|---|
| RES-1 | P1 | El lock de sistema operativo cubre ledger y presupuesto, pero `gates`/`report`/`apply` no toman el lock del run: dos procesos concurrentes podrían reescribir `gates.json` mientras otro lee. | PARTIAL |
| RES-2 | P1 | La capa de contratos solo se aplica en `decide` (campos desconocidos) y en `cmd_verify`. No se valida cada artefacto en init/collect/advance/report/apply, ni se rechazan `phase`/`status` arbitrarios. | PARTIAL |
| RES-3 | P1 | El juez: las dimensiones se calculan y se descartan; el ganador es solo la etiqueta X/Y. Un veredicto con score contradictorio no se bloquea. | NOT_RUN |
| RES-4 | P1 | El runtime no invoca a OpenCode: el E2E de Patch es **asistido** (un operador coloca el fix). No hay E2E autónomo. | NOT_RUN |
| RES-5 | P2 | Sin test específico de timeout con árbol de procesos, de tope de salida en disco ni de cuarentena de veredictos sobredimensionados. | NOT_RUN |
| RES-6 | P2 | Los artefactos de los runs (`ledger.jsonl`, `gates.json`, parches) viven en `.arena/` (ignorado por git): no se versionan como evidencia reproducible. | NOT_RUN |
| RES-7 | P2 | Sin `.opencode/config.json` de proyecto: los agentes heredan la config global del usuario. | NOT_RUN |
| RES-8 | P2 | `ledger.jsonl` es *tamper-evident* (cadena de hashes) pero **no tamper-proof**: sin ancla externa, un actor con permiso de escritura puede rehacer el fichero entero. | ACEPTADO (documentado) |
| RES-9 | P2 | El gate ejecuta la **copia del árbol del candidato**, no "baseline + parche". La equivalencia la prueba `verify_exported_artifact` en `apply`, no en el momento del gate. | ACEPTADO (documentado) |
| RES-10 | P2 | Los permisos de agente conceden `.arena/candidates/**` completo, no por candidato: un implementer podría escribir en el workspace de un rival. | NOT_RUN |

---

## Evidencia versionada (cierra el hueco "nada verificable está en el repo")

La revisión 5 señaló (§B) que el único parche exportado verificable estaba
**excluido de git** y que no existía ningún artefacto binario persistido. Cerrado:

| Requisito | Dónde | Verificado por |
|---|---|---|
| Parche round-trip del E2E | `reports/audit/artifacts/run-20261019-195822-s21.patch` | `AuditArtifactsTest::test_packaged_patch_applies_to_a_clean_baseline` |
| Cadena gates→decisión→ledger | `reports/audit/artifacts/{gates,decision,isolation}.json` + `ledger.jsonl` | `AuditArtifactsTest::test_packaged_evidence_hash_chain_is_consistent` |
| Suma de verificación | `reports/audit/artifacts/SHA256SUMS.txt` | `AuditArtifactsTest::test_packaged_evidence_checksums_match` |
| Artefacto binario de prueba | `fixtures/patch-demo/binary/sample.bin` | `BinaryPatchTest::test_persisted_binary_fixture_roundtrip` |

`sha256(parche) == diff_sha del gate == diff_sha de decision.json` — comprobado
en la ejecución: `c68f82cde82f99a62b22d055be908c13fa957222114deecd589c88a7f718f59f`.

## Verificación de no-regresión

`python -m pytest tests/ -v --no-header -p no:cacheprovider --timeout=180` → **117 passed + 1 skip explicito**, exit 0.
Detalle por test en [`test-results.json`](test-results.json).

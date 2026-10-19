# Modelo de amenazas

**Fecha:** 2026-10-19 · **Commit:** `875c04ae1f7865c8043db651708d471c4a8d334e` + remediación
**Plataforma auditada:** Windows 11 10.0.26200-SP0 AMD64

> Este documento se ha **regenerado a partir del código**. Cada fila apunta al control
> real y a su test. Lo que no tiene control verificable está marcado como tal.

---

## 0. Modo de seguridad: `TRUSTED_CODE_ONLY`

**Este runtime NO tiene frontera de sistema operativo.** No hay Job Object, AppContainer,
usuario de privilegios mínimos, filesystem restringido ni red bloqueada.

| Lo que SÍ hay | Lo que NO hay |
|---|---|
| Un directorio temporal por gate | Filesystem restringido |
| `cwd` = scratch | Red bloqueada |
| Variables de entorno allowlist | Usuario de privilegios mínimos |
| Sin `HOME`/`USERPROFILE` del operador | Límites de CPU/memoria del hijo |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` | Job Object (kill-on-close) |
| Shim de pytest aislado | |

**El scratch + el entorno filtrado son HIGIENE, no un sandbox.**

Consecuencia operativa: **ejecuta Arena Forge solo con código en el que confíes.** El modo
se declara en `forge/isolation.py::SECURITY_MODE`, viaja en cada `GateResult` y se muestra
en `arena_forge.py verify` y en la salida de `apply`.

---

## 1. Superficie y actores

| Activo | Ubicación | Confidencialidad |
|---|---|---|
| Código del candidato | `.arena/<run>/candidates/<id>/` | No confiable |
| Suite protegida | `--suite` (fuera del run) | **Confidencial para el candidato** |
| Baseline | `--baseline-dir` + copia congelada `.arena/<run>/baseline/` | Integridad crítica |
| Ledger | `.arena/<run>/ledger.jsonl` | Append-only |
| Decisiones de E | `.arena/<run>/decisions.jsonl` + `decision_state.json` | Append-only |
| Patch exportado | `reports/<run>.patch` | Artefacto entregado al usuario |
| Árbol principal del proyecto | raíz del repo | **No debe mutarse** |

| Atacante | Capacidad | Objetivo típico |
|---|---|---|
| Candidato (código no confiable) | Ejecuta código dentro del gate | Fabricar un PASS, contaminar la suite, leer fuera del workspace |
| Terceros / prompt injection | Contenido de README, issues, ficheros del candidato | Que el agente ejecute instrucciones embebidas |
| Operador descuidado | Edita ficheros entre fases | Que se evalúe una versión y se aplique otra |
| Actor con permiso de escritura | Puede escribir en `.arena/` | Reescribir el ledger |

---

## 2. Controles implementados (verificables)

| # | Amenaza | Control | Ubicación | Test |
|---|---|---|---|---|
| C-01 | **Falsificar el veredicto del gate** | El gate exige el **informe JUnit** de pytest (`--junitxml` fuera del scratch), no solo el código de salida. Sin informe, con `tests==0` o con `failures/errors>0` **nunca** hay PASS | `forge/gates.py` | `GatesTest::test_gate_rejects_candidate_forced_exit_zero` |
| C-02 | **Traversal al aplicar el parche** | Se validan `diff --git`, `---`, `+++`, `rename to`, `copy to`: se rechazan rutas absolutas, `..`, `~` y unidades. La aplicación va por `git apply` (rechaza rutas fuera del work tree) | `forge/isolation.py::validate_diff`, `_git_apply` | `IsolationTest::test_diff_git_header_traversal_rejected`, `..._absolute_windows_path_rejected`, `BinaryPatchTest::test_traversal_patch_...` |
| C-03 | **Corrupción de bytes por clasificación binaria** | Binario = byte NUL en los primeros 8192 **o** UTF-8 estricto inválido (decodificación incremental). El parche es `git diff --binary` real; nunca hay marcador `[BINARY FILE]` ni base64 inventado | `forge/isolation.py::_is_binary_file`, `capture_diff` | `BinaryPatchTest::test_binary_without_nul_in_first_8192_is_not_text`, `..._invalid_utf8_bytes_survive_roundtrip` |
| C-04 | **Symlink que escapa del workspace** | `walk_files_checked` devuelve `(ficheros, problemas)`: symlink externo, roto, de directorio o de fichero, fichero ilegible o no regular **hacen fallar** el manifiesto. Nada se omite en silencio | `forge/isolation.py::walk_files_checked`, `candidate_manifest_sha` | `IsolationTest::test_unsafe_symlink_blocks_manifest`, `..._broken_symlink_is_reported` |
| C-05 | **Contaminación del harness** | El candidato no puede aportar `conftest.py`, `sitecustomize.py`, `usercustomize.py`, `pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg` ni `tests_protected*`, **en ningún subdirectorio** (pytest los carga también desde ahí) | `forge/gates.py::_protected_names` | `GatesTest::test_nested_conftest_in_candidate_is_rejected` |
| C-06 | **Alteración de la suite protegida** | `suite_sha` cubre los tests **y** los ficheros de configuración de pytest. La suite se **recalcula** en `report` y `apply`; no puede ser symlink ni vivir dentro de un workspace candidato | `forge/gates.py::suite_files`, `forge/integrity.py::recompute_suite_sha` | `ReportTest::test_no_ship_when_suite_was_tampered_after_gates`, `GatesTest::test_suite_sha_covers_pytest_config_files` |
| C-07 | **Candidato alterado entre gates y apply** | El manifiesto de **todos** los candidatos se recalcula y compara en `report` y `apply` | `forge/report.py::resolve_full`, `forge/integrity.py` | `ReportTest::test_no_ship_when_candidate_modified_after_gate` |
| C-08 | **Baseline alterado entre gates y apply** | La copia congelada (`<run>/baseline`) y el baseline externo se revalidan: commit + dirty (Git) o manifiesto versionado (no-Git) | `forge/integrity.py::verify_baseline`, `verify_frozen_baseline` | `ReportTest::test_no_ship_when_frozen_baseline_changed` |
| C-09 | **Parche distinto del evaluado** | `diff_sha` se **recalcula**; el `sha256` del parche exportado se compara con el `diff_sha` del gate; el parche se aplica a una copia del baseline y el árbol resultante se compara con el del candidato | `forge/integrity.py::verify_diff_hashes`, `verify_exported_artifact` | `ApplyIntegrityTest::test_exported_patch_sha_matches_the_gated_diff_sha` |
| C-10 | **Ganador distinto del juzgado** | `report` persiste `decision_id` + `winner_id`; `apply` usa el ganador persistido y aborta si no coincide con la re-derivación | `arena_forge.py::cmd_report`, `cmd_apply` | `ApplyIntegrityTest::test_apply_exports_the_judged_winner_not_the_first_eligible` |
| C-11 | **Mutación del árbol principal** | `apply` solo escribe `reports/<run>.patch` (bytes, escritura atómica). Nunca toca el proyecto | `arena_forge.py::cmd_apply` | `PreexistingChangesTest::test_user_work_untouched` |
| C-12 | **Secreto filtrado a los logs** | `redact()` cubre 9 formatos (AWS, URLs con credenciales, `xoxb-`, `ghp_`, `github_pat_`, `sk-`, `AKIA`, `Bearer`, claves privadas, JWT) | `forge/util.py::redact` | `IsolationTest::test_redact_covers_common_secret_formats` |
| C-13 | **Exposición del perfil del operador** | `HOME`/`USERPROFILE` apuntan al scratch; el env es allowlist y **no** hereda `os.environ` | `forge/gates.py::_minimal_env` | `GatesTest::test_minimal_env_has_no_user_site_and_no_plugin_autoload` |
| C-14 | **Ejecución de plugins de pytest del usuario** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONNOUSERSITE=1`, `PYTHONSAFEPATH=1`, `PYTHONPATH` = scratch + **shim** con solo pytest y sus dependencias | `forge/gates.py::_pytest_shim`, `_minimal_env` | `GatesTest::test_minimal_env_has_no_user_site_and_no_plugin_autoload` |
| C-15 | **Agotamiento de RAM o de disco** | La salida se lee con contrapresión: tope duro de 16 MiB en disco y 1 MiB devuelto; al superar el tope se mata el proceso | `forge/gates.py::_run_bounded` | — (§RES-5: falta test específico) |
| C-16 | **Proceso hijo que sobrevive al timeout** | El timeout mata el **árbol** de procesos (`taskkill /T` en Windows, `killpg` en POSIX) | `forge/gates.py::_kill_process_tree` | — (§RES-5: falta test específico) |
| C-17 | **XSS en el informe** | Todo el contenido se escapa antes de renderizar; el HTML es estático y autocontenido | `forge/report.py::esc`, `_md_to_html` | `ReportTest::test_html_escapes_script` |
| C-18 | **Inyección de prompt** | El contenido del candidato es **dato**, nunca instrucción: el harness no lee README/issue del candidato como orden | `arena_forge.py`, `forge/gates.py` | `GatesTest::test_injection_readme_inert` |
| C-19 | **Presupuesto de E sobrepasado** | Reserva atómica bajo **lock de sistema operativo** antes de crear el job; `calls_reserved` separado de `calls_spent` | `forge/agent_e.py::reserve_budget`, `forge/util.py::FileLock` | `AgentETest::test_two_jobs_cannot_exceed_the_remaining_budget` |
| C-20 | **Aprobación humana autollenada** | Sin un registro de aprobación **ligado** a `decision_id`+`run_id`+`action_type`+`target_ids`+`cost_calls`+`policy_version`, la decisión queda `awaiting_approval` y no ejecuta | `forge/agent_e.py::execute_decision`, `validate_approval` | `AgentETest::test_human_approval_required_blocks_execution` |
| C-21 | **Reescritura del historial de decisiones** | `decisions.jsonl` es append-only; la proyección va aparte; las líneas corruptas se preservan | `forge/agent_e.py::_persist_decision`, `corrupt_lines` | `AgentETest::test_decisions_file_is_append_only` |
| C-22 | **Manipulación del ledger** | Cadena `prev_hash`+`event_hash`; el `seq` no se ve afectado por líneas corruptas; la alteración se detecta | `forge/ledger.py::verify` | `LedgerTest::test_tampering_is_detected` |
| C-23 | **ID de candidato con traversal** | El id se valida (`^[A-Za-z0-9._-]+$`) y se comprueba la contención **antes** de crear el directorio | `forge/isolation.py::ensure_workspaces` | `IsolationTest::test_ensure_workspaces_does_not_create_outside_the_run` |
| C-24 | **Permisos de agente invertidos** | En OpenCode V2 gana la **última** regla que coincide: los `deny` amplios van primero y los `allow` concretos al final | `.opencode/agents/*.md` | `PortabilityTest::test_agent_permission_rules_put_allow_last` |
| C-25 | **Skill ignorada por el cargador** | Frontmatter V2 (`name` == directorio, `description` no vacía) | `.opencode/skills/arena-forge/SKILL.md` | `PortabilityTest::test_repo_skill_has_opencode_frontmatter` |

---

## 3. Controles NO implementados (declarados, no simulados)

| # | Amenaza | Estado | Mitigación actual |
|---|---|---|---|
| N-01 | **El candidato ejecuta código con los privilegios del operador** | **NO IMPLEMENTADO** | Modo `TRUSTED_CODE_ONLY`; no ejecutar código no confiable |
| N-02 | **El candidato puede leer la red / escribir fuera del workspace** | **NO IMPLEMENTADO** | Ídem. `HOME`/`USERPROFILE` mitigados, pero el filesystem sigue abierto |
| N-03 | **Un candidato puede escribir en el workspace de un rival** | **NO IMPLEMENTADO** | Los permisos de agente son por run, no por candidato (§RES-10) |
| N-04 | **El ledger puede reescribirse por completo** | **ACEPTADO** | Sin ancla externa: *tamper-evident*, no *tamper-proof* |
| N-05 | **Coste monetario no acotable** | **ACEPTADO** | La API no expone tokens; los límites son llamadas/olas/tiempo |
| N-06 | **El score del juez no participa en la decisión** | **NO IMPLEMENTADO** | La etiqueta X/Y decide sola; las dimensiones se calculan y se descartan |

---

## 4. Resumen

La integridad del **candidato evaluado** es sólida y verificable byte a byte: lo que se
exporta es lo que se evaluó, y el parche aplicado reproduce el árbol del candidato.

La integridad del **entorno de ejecución** no lo es: sin frontera de OS, el código del
candidato se ejecuta con los privilegios del operador. Esa diferencia es la línea roja
que separa "higiene" de "sandbox", y este documento la nombra en lugar de difuminarla.

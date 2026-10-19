# Arena Forge — Plan de remediacion tras auditoria forense

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar las brechas P0/P1 verificadas por auditoria forense en Arena Forge, con evidencia fresca, reproducible y vinculada al commit final, sin declarar COMPLETE nada que no se haya ejecutado.

**Architecture:** Se conserva la arquitectura actual (`arena_forge.py` CLI + paquete `forge/`). Los cambios son **modulares y de riesgo bajo**: (1) se sustituye el formato de parche binario *inventado* por el formato **real de Git** (`git diff --binary`), de modo que existe un unico artefacto canonico interoperable; (2) se Introduce un **modulo nuevo** `forge/integrity.py` con las comprobaciones de contenido (manifiesto, suite, baseline, artefacto exportado) reutilizadas por `report`, `verify` y `apply`; (3) `forge/agent_e.py` pasa a un modelo **reserva-vs-gasto** con aprobacion humana real; (4) `forge/adapter.py` se consolida a una sola definicion por funcion con sondas honestas.

**Tech Stack:** Python 3.12.4 (stdlib only en el producto), pytest 9.1.1 (solo dev), Git 2.51.0, OpenCode v2.0.32, Windows 11 AMD64.

**Spec:** `ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md` — **NO DISPONIBLE en el checkout** (ver `reports/audit/baseline.md`, BLOCKED-01). Los criterios AF-AC-001..018 y §16 se evalúan contra el contrato *declarado en el prompt de auditoria*; todo criterio que dependa del texto literal del contrato queda **NOT_RUN / BLOCKED**, nunca PASS.

---

## Global Constraints

- **NO push, NO pull, NO merge, NO release, NO tag, NO deploy** hasta que el usuario lo autorice explicitamente al final. El usuario ha autorizado el push final ("subiras todos los cambios al repo"); no se hace antes.
- No borrar/restorear/resetear/limpiar cambios del usuario. `git clean`, `git reset --hard`, `git checkout --`, `git restore` **prohibidos**.
- Un scratch temporal con `cwd` + env filtrada **NO es un sandbox**. Etiqueta honesta: `TRUSTED_CODE_ONLY`. No marcar P0 de aislamiento como cerrado.
- Nunca transformar `NOT_RUN` / `BLOCKED` / `INCONCLUSIVE` / `SKIPPED` en `PASS`.
- No se ejecuta ninguna llamada a modelo con coste sin estimacion previa + aprobacion humana. Las sondas de OpenCode que requieren modelo se marcan `BLOCKED`.
- No instalar dependencias globales. Solo stdlib en el producto.
- Todo cambio de codigo va precedido de un test **rojo** que demuestre el defecto.
- Los tests no escriben dentro del repo: `git status --short` debe quedar igual antes y despues.
- Rutas de test derivadas de `Path(__file__).resolve().parent.parent` — prohibido `C:\Users\...` literal.

## Review Focus

Cinco clases de entrada/fallo que la especificacion insinua y que ningun test actual cubre:

1. **Un diff mixto (un binario + un fichero de texto):** el texto debe seguir aplicandose; el hunk de texto no puede desaparecer porque el diff contenga "GIT binary patch".
2. **Un parche binario con rutaTraversal (`../../evil`):** debe rechazarse ANTES de escribir, sin dejar ficheros fuera del scratch.
3. **Un binario sin byte NUL en los primeros 8192 (p.ej. PNG, ZIP):** no puede clasificarse como texto ni perder bytes al volverse parche.
4. **Un `decisions.jsonl` con una linea corrupta:** debe preservarse el fichero y registrarse el incidente; nunca descartarse en silencio ni reescribirse el historico.
5. **Un candidato que modifica la suite protegida entre `gates` y `report`:** debe producir NO_SHIP con la razon exacta, no un PASS.

---

### Task 1: Formato de parche binario canonico (Git real) + contencion de rutas

**Files:**
- Modify: `forge/isolation.py` (todo el bloque `_binary_diff_line` / `_apply_binary_diff` / `_apply` / `validate_diff` / `capture_diff`)
- Test: `tests/test_forge.py` (nueva clase `BinaryPatchTest`)

**Interfaces:**
- Consumes: `forge.util.sha_text`, `forge.util.sha_file`, `forge.util.ForgeError`.
- Produces:
  - `capture_diff(baseline_dir, candidate_dir, name_hint="") -> str` — **contrato nuevo**: devuelve un parche **Git canonico** (`git diff --binary --no-color --no-ext-diff`) con rutas `a/<rel>` / `b/<rel>`. Si `git` no esta disponible o falla, devuelve `""` y registra el motivo (fail-closed, nunca un parche textual inventado).
  - `validate_diff(diff_text) -> (bool, list[str])` — valida **todas** las cabeceras (`diff --git`, `---`, `+++`, `rename to`, `copy to`) contra traversal/rutas absolutas.
  - `apply_diff_to_temp(diff_text, baseline_dir) -> str` — aplica con `git apply --check` y luego `git apply` sobre el scratch. Devuelve el scratch.
  - `capture_diff_tree_sha(baseline_dir, candidate_dir) -> str` — SHA-256 del arbol de ficheros (ruta|tipo|modo|tamano|sha256), independiente del formato de parche.

**Pasos:**

- [ ] **Step 1: Escribir los tests rojos**

```python
class BinaryPatchTest(unittest.TestCase):
    def test_binary_roundtrip_is_byte_exact(self):
        # baseline/data.bin con NUL, candidate/data.bin distinto
        # capture_diff -> apply_diff_to_temp -> comparar SHA-256 de cada fichero y del arbol
    def test_mixed_diff_keeps_text_hunk(self):
        # baseline: a.py (texto) + d.bin (binario); candidate cambia ambos
        # tras aplicar, a.py debe estar MODIFICADO y d.bin tambien
    def test_deleted_binary_file_is_removed(self):
        # baseline con d.bin; candidate sin d.bin -> tras aplicar, d.bin NO existe
    def test_added_binary_file_appears(self):
    def test_traversal_in_diff_header_is_rejected(self):
        # diff con "diff --git a/../../evil b/../../evil" -> validate_diff False y apply NO escribe fuera
    def test_git_apply_check_accepts_generated_patch(self):
        # en repo git temporal: git apply --check <patch> devuelve 0
    def test_binary_without_nul_in_first_8192_is_not_text(self):
        # fichero de 20000 bytes, NUL solo al final -> no debe clasificarse como texto
    def test_invalid_utf8_bytes_survive_roundtrip(self):
```

- [ ] **Step 2: Ejecutar y confirmar ROJO**

Run: `python -m pytest tests/test_forge.py::BinaryPatchTest -v`
Expected: FAIL — `capture_diff` hoy produce un diff unificado textual (`--- a/...`/`+++ b/...`) sin soporte binario real y `apply_diff_to_temp` escribe fuera del scratch con rutas no validadas.

- [ ] **Step 3: Implementar el formato canonico**

En `forge/isolation.py`:
- Sustituir `_binary_diff_line` / `_apply_binary_diff` por la generacion/aplicacion de **parches Git reales**:
  `git -C <tmp> diff --binary --no-color --no-ext-diff --src-prefix=a/ --dst-prefix=b/ <baseline> <candidate>` ejecutado sobre un arbol temporal que contiene `baseline/` y `candidate/`, reescrito a `a/<rel>` / `b/<rel>`.
  Si `git` no esta disponible -> `capture_diff` devuelve `""` y el llamante **bloquea** (fail-closed) en vez de inventarse un formato.
- `validate_diff`: parsear `diff --git a/X b/X`, `--- a/X`, `+++ b/X`, `rename to X`, `copy to X`; rechazar rutas absolutas, `..`, y cualquier ruta que resuelva fuera del arbol.
- `_apply`: usar `git apply --check` (en el scratch) y solo despues `git apply`. Si `git apply --check` falla -> `ForgeError`, sin escrituras.
- `_is_binary_file`: NO usar la heuristica de 30% como criterio unico. Nueva politica: un fichero es binario si contiene NUL en los primeros 8192 bytes **o** si no decodifica como UTF-8 estricto. El parche nunca contiene el marcador `[BINARY FILE]`.
- `_walk_files`: dejar de **omitir en silencio** los symlinks inseguros (ver Task 2).

- [ ] **Step 4: Ejecutar y confirmar VERDE**

Run: `python -m pytest tests/test_forge.py::BinaryPatchTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add forge/isolation.py tests/test_forge.py
git commit -m "P0-1: parche binario canonico Git real + contencion de rutas"
```

---

### Task 2: Symlinks inseguros y errores de lectura -> fail-closed

**Files:**
- Modify: `forge/isolation.py` (`_walk_files`, `candidate_manifest_sha`)
- Modify: `forge/gates.py` (usar el manifiesto nuevo)
- Test: `tests/test_forge.py` (nueva clase `SymlinkPolicyTest`)

**Interfaces:**
- Produces: `walk_files_checked(root) -> (list[tuple[str, str]], list[str])` — devuelve `(ficheros, problemas)`. `problems` no vacio significa operacion invalida.
- `candidate_manifest_sha(candidate_dir) -> str` — hash del arbol incluyendo **modo**; si hay symlink no permitido o error de lectura, **el manifiesto debe fallar**, no omitir el fichero.

- [ ] Step 1: tests rojos — `test_unsafe_symlink_makes_manifest_fail`, `test_broken_symlink_is_reported`, `test_symlinked_directory_escape_is_reported`, `test_manifest_includes_mode`.
- [ ] Step 2: `python -m pytest tests/test_forge.py::SymlinkPolicyTest -v` -> FAIL.
- [ ] Step 3: implementar `walk_files_checked` + `candidate_manifest_sha` que propaga el fallo; `gates.run_gate` marca `BLOCKED` / `failure_class="unsafe_symlink"`.
- [ ] Step 4: VERDE.
- [ ] Step 5: commit `P0-2: symlinks inseguros bloquean el manifiesto (fail-closed)`.

---

### Task 3: Integridad de contenido (suite, baseline, artefacto exportado) en un unico modulo

**Files:**
- Create: `forge/integrity.py`
- Modify: `forge/report.py`, `forge/arena_forge.py` (`cmd_apply`, `cmd_verify`)
- Test: `tests/test_forge.py` (nueva clase `IntegrityTest`)

**Interfaces:**
- Produces (modulo nuevo `forge/integrity.py`):
  - `recompute_suite_sha(run) -> str|None` — recalcula el hash vivo de la suite y lo compara con `run["suite_sha"]`; ademas valida que la suite **no** esta dentro de un workspace candidato y que no es un symlink.
  - `verify_baseline(run) -> (bool, str)` — revalida el baseline: si hay `target_baseline_dir` + commit Git -> `git rev-parse HEAD` + `git status --porcelain`; si no -> recalcular `baseline_manifest` con el **mismo algoritmo versionado** y comparar con el congelado.
  - `verify_exported_artifact(run, candidate_dir, patch_path) -> (bool, str)` — recalcula el diff desde el baseline congelado, compara `sha256(patch_bytes)` con `diff_sha` del gate, aplica el parche a una copia temporal y compara el **manifiesto del arbol resultante** con el del candidato.
  - `decision_winner(decision) -> str|None` — elganador **exacto** persistido por el juez (no `eligible[0]`).

- [ ] Step 1: tests rojos:
  - `test_apply_uses_judged_winner_not_first_eligible`
  - `test_apply_blocks_when_suite_changed_after_gates`
  - `test_apply_blocks_when_baseline_manifest_changed`
  - `test_apply_blocks_when_exported_patch_sha_differs`
  - `test_apply_blocks_when_candidate_manifest_changed_after_gates`
  - `test_non_git_baseline_init_does_not_crash`
  - `test_verify_recomputes_suite_sha`
- [ ] Step 2: `python -m pytest tests/test_forge.py::IntegrityTest -v` -> FAIL (hoy: `cmd_apply` usa `eligible[0]`, `suite_sha` solo se compara con el valor almacenado, el manifiesto de baseline no se compara, `arena_forge.py:294` revienta con `ImportError` en baseline no-Git).
- [ ] Step 3: implementar `forge/integrity.py`; rewirear `report.resolve` (usar `decision_winner`), `cmd_apply` (verificar baseline + suite + artefacto antes de exportar; exportar con escritura atomica) y `cmd_verify`.
- [ ] Step 4: VERDE + suite completa verde.
- [ ] Step 5: commit `P0-3: suite/baseline/manifiesto/artefacto revalidados en report, verify y apply`.

---

### Task 4: Gates — entorno minimo, suite completa, output acotado, arbol de procesos, honestidad del modo

**Files:**
- Modify: `forge/gates.py`
- Test: `tests/test_forge.py` (nueva clase `GateSecurityTest`)

**Interfaces:**
- Produces: `SECURITY_MODE = "TRUSTED_CODE_ONLY"` constante en `forge/gates.py`; `run_gate(...)` incluye `security_mode` en el `GateResult`.

- [ ] Step 1: tests rojos:
  - `test_suite_sha_covers_conftest_and_pytest_ini`
  - `test_suite_outside_candidate_workspace_is_required`
  - `test_pytest_plugin_autoload_is_disabled`
  - `test_user_site_packages_not_on_pythonpath`
  - `test_gate_result_declares_security_mode`
  - `test_nested_conftest_in_candidate_is_rejected`
- [ ] Step 2: FAIL.
- [ ] Step 3: implementar:
  - `suite_files` incluye tambien `conftest.py`, `pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg` presentes en el directorio de la suite (para que la alteracion sea visible en `suite_sha`).
  - `_protected_names` recorre **recursivamente** el candidato (no solo el nivel superior) buscando `conftest.py`, `pytest.ini`, `sitecustomize.py`, `usercustomize.py`.
  - `env["PYTHONPATH"] = scratch` **solamente** (sin `site.getusersitepackages()`); `PYTHONNOUSERSITE=1`; `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; `PYTEST_ADDOPTS=""`.
  - Captura de output **acotada**: escribir a fichero temporal y truncar en disco al superar `max_output_bytes`; nunca `stdout=PIPE` ilimitado.
  - Timeout: matar el **arbol de procesos** (Windows: `taskkill /T /F`; POSIX: `start_new_session=True` + `killpg`).
  - `GateResult["security_mode"] = "TRUSTED_CODE_ONLY"` + nota visible.
- [ ] Step 4: VERDE.
- [ ] Step 5: commit `P0-4: gates con entorno minimo, suite completa, output acotado y modo honesto`.

---

### Task 5: Matriz de capacidades obligatorias por modo en `cmd_verify`

**Files:**
- Modify: `forge/adapter.py`, `arena_forge.py` (`cmd_verify`)
- Test: `tests/test_forge.py` (nueva clase `VerifyMatrixTest`)

- [ ] Step 1: tests rojos: `test_verify_fails_when_required_capability_missing`, `test_verify_requires_suite_for_patch_mode`, `test_verify_requires_nothing_extra_for_answer_mode`.
- [ ] Step 2: FAIL.
- [ ] Step 3: `forge/adapter.py` expone `REQUIRED_BY_MODE = {"answer": (...), "patch": (...), "benchmark": (...)}` con capacidades **obligatorias** y **opcionales** separadas; `cmd_verify` usa la matriz segun `run["mode"]` y ya **no** acepta `verified > 0` como criterio.
- [ ] Step 4: VERDE.
- [ ] Step 5: commit `P1-1: verify exige capacidades criticas por modo`.

---

### Task 6: `forge/adapter.py` — consolidar duplicados y sondas honestas

**Files:**
- Modify: `forge/adapter.py` (reescritura del fichero: una sola definicion por funcion)
- Test: `tests/test_forge.py` (nueva clase `AdapterIntegrityTest`)

- [ ] Step 1: tests rojos:
  - `test_no_duplicate_function_definitions_in_adapter` — parsea el AST del modulo y falla si algun nombre de funcion/problema aparece mas de una vez.
  - `test_agent_profiles_path_resolves_to_repo_agents_dir`
  - `test_probe_does_not_mark_permission_rules_verified_without_functional_test`
  - `test_state_on_disk_probe_requires_create_close_reopen_resume`
  - `test_cwd_control_probe_uses_agent_runtime_not_local_shell`
  - `test_readonly_probe_verifies_canary_unchanged`
- [ ] Step 2: FAIL (hoy: `_test_skill_load` x4, `_test_subagent_foreground` x4, `_test_readonly_agent` x4, `_test_cwd_control` x4, `_test_state_on_disk` x4, `_test_shell_tool` x4, `_run_opencode` x3, `_run` x3, `detect_version` x2, `load_capabilities` x2, `save_capabilities` x2, `_default_capabilities` x2).
- [ ] Step 3: reescribir `forge/adapter.py` con una sola definicion por funcion; sondas:
  - `_test_skill_load`: usar el mecanismo **soportado por la version instalada** (`opencode --help` no expone `skill`; por tanto `skills_native` = `unsupported` **por ausencia de subcomando en esta version**, evidencia = la lista real de subcomandos, no un parse-error).
  - `_test_subagent_foreground`: `opencode run --agent <profile> "<mensaje>"` (argumento **posicional**, no `--prompt`); requiere coste -> se marca `BLOCKED` en el probe por defecto y solo se ejecuta con `--probe --allow-model-calls`.
  - `_test_readonly_agent`: escribir un **canario** con contenido conocido, invocar el agente, y comprobar **estado antes/después** del fichero; un error generico de CLI **no** es prueba de denegacion.
  - `_test_cwd_control`: comprobar el cwd **del runtime del agente**, no un `cmd /c type` local.
  - `_test_state_on_disk`: crear -> cerrar -> reabrir -> reanudar un run persistido.
  - `permission_rules`: `by="docs"` -> status `unknown` hasta que exista test funcional.
  - `agent_profiles`: ruta correcta `os.path.join(HERE, ".opencode", "agents")`.
  - `probe()` deja de escribir `runtime/capabilities.json` salvo que se pase `persist=True`.
- [ ] Step 4: VERDE.
- [ ] Step 5: commit `P1-2: adapter consolidado con sondas honestas`.

---

### Task 7: `forge/agent_e.py` — aprobacion humana, evidencia real, presupuesto atomico

**Files:**
- Modify: `forge/agent_e.py`
- Test: `tests/test_forge.py` (nueva clase `AgentETest`)

- [ ] Step 1: tests rojos:
  - `test_human_approval_required_blocks_execution`
  - `test_approval_must_bind_decision_run_targets_and_hashes`
  - `test_request_evidence_cannot_succeed_without_evidence`
  - `test_launch_phase_does_not_report_success_without_started_work`
  - `test_budget_reserved_before_job_creation`
  - `test_two_jobs_cannot_exceed_single_remaining_call`
  - `test_decisions_file_is_append_only`
  - `test_corrupt_decision_line_is_preserved_and_reported`
  - `test_job_done_requires_existing_output`
- [ ] Step 2: FAIL.
- [ ] Step 3: implementar:
  - `EXECUTION_STATES` ampliado con `awaiting_approval`, `awaiting_manual_action`, `cancelled`.
  - `execute_decision`: si `requires_human_approval` y no existe un registro de aprobacion en `run["approvals"]` ligado a `decision_id` + `run_id` + `target_ids` + hashes + coste -> `execution_state="awaiting_approval"`, `success=False`.
  - `_exec_request_evidence`: devuelve `False` si no hay evidencia; `execution_state="awaiting_manual_action"`.
  - `_exec_launch_phase`: arranca el trabajo real; si no puede, `AWAITING_MANUAL_ACTION` (nunca `SUCCEEDED` por registrar un job).
  - Presupuesto: `calls_reserved` vs `calls_spent`; reserva **bajo lock** antes de crear el job; `job_id` determinista `sha256(run_id|phase|target|input_hash)[:12]` (idempotente al reanudar).
  - `decisions.jsonl`: **append-only**; las transiciones de estado van a un fichero de proyeccion `decision_state.jsonl` (append-only tambien). Las lineas corruptas se preservan y se registran como incidente.
  - `mark_job_completed`: exige `output_ref` existente, con tamano valido y hash.
- [ ] Step 4: VERDE.
- [ ] Step 5: commit `P1-3: E con aprobacion real, evidencia obligatoria y presupuesto reservado`.

---

### Task 8: Ledger con writer lock + `log_event` sin silenciar fallos

**Files:**
- Modify: `forge/ledger.py`, `arena_forge.py` (`log_event`, `acquire_lock`)
- Test: `tests/test_forge.py` (nueva clase `LedgerConcurrencyTest`)

- [ ] Step 1: tests rojos: `test_two_concurrent_appends_produce_distinct_sequences`, `test_ledger_append_failure_is_not_silent`.
- [ ] Step 2: FAIL.
- [ ] Step 3: `ledger.append` serializa con un lock de fichero (`msvcrt.locking` en Windows, `fcntl.flock` en POSIX) + reintento; `log_event` **no** silencia `OSError` (lo registra y marca el run).
- [ ] Step 4: VERDE.
- [ ] Step 5: commit `P1-4: ledger con writer lock y fallos no silenciados`.

---

### Task 9: Limpieza de duplicados y estado del runtime

**Files:**
- Modify: `arena_forge.py` (eliminar el `cmd_decide` duplicado de la linea 734), `forge/util.py` (eliminar el `atomic_write_json` duplicado de la linea 40), `forge/state.py` (`transition` actualiza `updated`)
- Test: `tests/test_forge.py` (nueva clase `NoDuplicatesTest`)

- [ ] Step 1: test rojo `test_no_duplicate_top_level_definitions` — AST sobre `arena_forge.py` y `forge/*.py`; falla si hay nombres duplicados.
- [ ] Step 2: FAIL.
- [ ] Step 3: eliminar duplicados; `cmd_decide` conserva la version que informa `execution_state`.
- [ ] Step 4: VERDE.
- [ ] Step 5: commit `P1-5: elimina definiciones duplicadas`.

---

### Task 10: Tests portables + suite de regresion adversarial

**Files:**
- Modify: `tests/test_forge.py`
- Test: el propio fichero

- [ ] Step 1: test rojo `test_no_absolute_host_paths_in_tests` — escanea `tests/` buscando `C:\Users\`, `/home/<user>/`, `C:/Users/`.
- [ ] Step 2: FAIL (hay 2 ocurrencias de `C:\Users\Marcos\arena-forge\...`).
- [ ] Step 3: derivar todas las rutas de `Path(__file__).resolve().parent.parent`; los fixtures de test deben vivir en `tmp/` temporal, no en el repo.
- [ ] Step 4: VERDE + suite completa verde + `git status --short` identico antes/despues.
- [ ] Step 5: commit `P1-6: tests portables sin rutas absolutas`.

---

### Task 11: CI Windows + Linux

**Files:**
- Create: `.github/workflows/ci.yml`
- Test: no aplica (CI); se valida el YAML por parseo.

- [ ] Step 1: escribir `.github/workflows/ci.yml` con matriz `windows-latest` / `ubuntu-latest`, `python-version: ["3.11", "3.12"]`, `pip install pytest`, `python -m pytest tests/ -q`, y un job que comprueba `git status --porcelain` vacio tras la suite.
- [ ] Step 2: `python -c "import yaml,sys;yaml.safe_load(open('.github/workflows/ci.yml'))"` (si `yaml` no esta, validar con el parser de GitHub documentado) -> verificar que el fichero es YAML valido.
- [ ] Step 3: commit `CI: windows + linux`.
- [ ] NOTA: **AF-AC-012 queda NOT_RUN** hasta que la CI se ejecute en GitHub. No se afirma que la CI pasa.

---

### Task 12: Documentacion honesta + informes de auditoria

**Files:**
- Modify: `README.md`, `VERIFICATION_SUMMARY.md`, `CHANGELOG.md`, `docs/RECONNAISSANCE.md`, `docs/THREAT_MODEL.md`
- Create: `reports/audit/{findings.md,test-results.json,acceptance-matrix.md,final-audit.md}`

- [ ] Step 1: regenerar `runtime/capabilities.json` con el probe honesto (`by` real, TTL, hash del ejecutable).
- [ ] Step 2: `runtime/benchmark.json` — mantener `AF-AC-016` en `not_measured` / NOT_RUN. No estimar.
- [ ] Step 3: escribir los 4 informes de auditoria con los estados reales.
- [ ] Step 4: README sin claims no demostrados (nada de "44/44" sin comando; nada de "sandbox"; E2E etiquetado como **asistido** si hubo intervencion manual).
- [ ] Step 5: commit `docs: auditoria forense y claims alineados con la evidencia`.

---

## Fuera de alcance (declarado, no simulado)

| Item | Estado | Motivo |
|---|---|---|
| Sandbox de OS (AppContainer/Job Object/red bloqueada) | **BLOCKED** | Windows 11 sin mecanismo probado ni permisos de admin; no se puede certificar contencion real |
| AF-AC-001..018 / §16 con el texto literal del contrato | **BLOCKED** | `ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md` no esta en el checkout |
| AF-AC-012 (CI en ejecucion) | **NOT_RUN** | La CI se configura pero no se ejecuta hasta el push; se reporta como configurada-y-no-verificada |
| AF-AC-016 (eficacia adaptativa de E) | **NOT_RUN** | Requiere ejecuciones vivas repetidas con coste; no se estima |
| Llamadas a modelo de pago durante el probe | **BLOCKED** | Coste no autorizado |

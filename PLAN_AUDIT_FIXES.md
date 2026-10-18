# Plan de corrección — Auditoría Arena Forge contra especificación integral

**Fecha:** 18 de octubre de 2026  
**Repositorio:** C:\Users\Marcos\arena-forge  
**Commit base:** 185cfea (Arena Forge v1.0)  
**Auditoría base:** `ARENA_FORGE_AUDITORIA_CONTRA_ESPECIFICACION_2026-10-18.md`

---

## Objetivo

Cerrar **todas** las brechas P0 (bloqueantes), P1 (funcionales importantes) y P2 (calidad) para que el proyecto cumpla con **todos** los criterios AF-AC-001..018 de la especificación técnica integral y pueda declararse **COMPLETE** con evidencia real, no simulada.

---

## Fase 0 — Inspección y baseline reproducible ✅ COMPLETADA

- [x] Versiones confirmadas: Python 3.12.4, pytest 9.1.1, git 2.51.0, OpenCode v2.0.32
- [x] Repositorio limpio salvo cambios en `runtime/benchmark.json` y `runtime/capabilities.json`
- [x] Tests actuales: 35/35 PASS (17.9s)
- [x] Docs y artefactos inventariados

---

## P0 — Bloqueantes de integridad y seguridad

### P0-01: Aislamiento como precondición real (no `True` incondicional)

**Archivos a modificar:**
- `arena_forge.py` → `cmd_gates()` línea 395
- `forge/report.py` → `resolve()`
- `forge/gates.py` → `run_all()` / `run_gate()`

**Cambios:**
1. Eliminar `cand["isolation_verified"] = True` incondicional en `cmd_gates`
2. En `cmd_gates`: cargar `isolation.json`, validar `ok == true` y rutas reales ANTES de ejecutar gates
3. Si falta/incorrecto → `BLOCKED` para ese candidato, no ejecutar suite
4. `report.resolve()` debe rechazar `WINNER` si aislamiento obligatorio no verificado
5. `apply` debe rechazar si aislamiento no verificado

**Tests nuevos:**
- `test_isolation_missing_blocks_gates`
- `test_isolation_ok_false_blocks_gates`
- `test_isolation_symlink_escape_blocks`
- `test_isolation_workspace_replaced_after_init`

---

### P0-02: Ejecución de código candidato con aislamiento real o BLOQUEADO

**Archivos a modificar:**
- `forge/gates.py` → `run_gate()`

**Cambios:**
1. No heredar `os.environ` completo → construir `env` mínimo allowlist (PATH, PYTHONPATH=scratch, TEMP, TMP, HOME/USERPROFILE mínimo)
2. Eliminar `sitecustomize.py`, `usercustomize.py`, plugins pytest del candidato del PYTHONPATH
3. Desactivar autoload de plugins: `-p no:cacheprovider -p no:faulthandler` + variables `PYTHONDONTWRITEBYTECODE=1`
4. **Si no hay sandbox de SO demostrable** (Windows: Job Objects, AppContainer, o contenedor): marcar modo Patch como `BLOCKED` para ejecución de código no confiable; ofrecer modo `DIFF_ONLY` claramente limitado
5. Documentar en `THREAT_MODEL.md` y `README.md` qué protege y qué no

**Tests nuevos:**
- `test_gate_env_no_secrets_leaked`
- `test_gate_cant_write_outside_scratch`
- `test_gate_no_network_access`
- `test_gate_sitecustomize_ignored`
- `test_gate_timeout_kills_tree`

---

### P0-03: Suite de evaluación congelada y validada contra hash de init

**Archivos a modificar:**
- `forge/gates.py` → `run_gate()`, `run_all()` — aceptar `expected_suite_sha`
- `arena_forge.py` → `cmd_gates()` — pasar `run["suite_sha"]`
- `forge/report.py` → `resolve()` — validar integridad de suite como requisito para `WINNER`
- `arena_forge.py` → `cmd_verify()` — comprobar suite hash congelado

**Cambios:**
1. `run_gate(expected_suite_sha=None)` valida `suite_before == expected_suite_sha` ANTES de ejecutar
2. Valida `suite_after == expected_suite_sha` DESPUÉS
3. Todos los candidatos deben tener el mismo `expected_suite_sha` (el de `run`)
4. Cualquier divergencia → `BLOCKED` para ese candidato + `NO_SHIP` global
5. `report.resolve()` devuelve `NO_SHIP` si `gates` tienen integridad de suite comprometida

**Tests nuevos:**
- `test_suite_modified_after_init_blocks`
- `test_suite_modified_between_candidates_blocks`
- `test_suite_modified_during_gate_blocks`
- `test_suite_hash_missing_blocks`

---

### P0-04: Baseline, snapshots, diffs y aplicación recursivos

**Archivos a modificar:**
- `arena_forge.py` → `_prepare_patch()`, `capture_diff()`, `apply_diff_to_temp()`, `cmd_apply()`
- `forge/isolation.py` → `ensure_workspaces()` (ya usa copytree recursivo, verificar)

**Cambios:**
1. `_prepare_patch()`: copiar recursivamente `baseline_dir` → `candidates/<id>/` (preservar estructura completa)
2. `capture_diff()`: comparar recursivamente `baseline/` vs `candidates/<id>/` (archivos nuevos, modificados, eliminados, renombrados)
3. `cmd_apply()`: generar patch válido para `git apply --check` en checkout limpio
4. Requerir baseline válido (`--baseline-dir` con repo Git o snapshot versionado) antes de `READY` en Patch
5. Si no hay baseline → no crear candidato Patch `READY`, bloquear

**Tests nuevos:**
- `test_patch_recursive_baseline_copy`
- `test_patch_diff_new_modified_deleted_renamed`
- `test_patch_apply_validates_git_apply_check`
- `test_patch_e2e_nested_repo_fixture`

---

### P0-05: E como orquestador real con estados honestos

**Archivos a modificar:**
- `forge/agent_e.py` → separar `EPolicyEngine` (decisiones) de lógica de ejecución
- `arena_forge.py` → `cmd_decide()`, nuevo dispatcher de acciones
- Nueva skill/agente para ejecución si OpenCode lo soporta

**Cambios:**
1. Renombrar `step()` → `propose()` (solo propone, no ejecuta)
2. Estados de decisión: `PROPOSED` → `APPROVED` → `EXECUTING` → `SUCCEEDED|FAILED|BLOCKED|CANCELLED`
3. `cmd_decide()` valida precondiciones, presupuesto, state_version ANTES de aprobar
4. Si acción = `launch_phase`: crear jobs reales en `forge.json` y registrar en ledger
5. Si acción = `request_review`/`request_evidence`: crear jobs de review y persistir
6. Si acción = `stop`/`recommend_no_ship`: transicionar fase a `DECIDING`
7. **Nunca** marcar `accepted` sin ejecutar; registrar `executed_by`, `session_id`, `output_ref`
8. Revalidar `observed_state_version` al ejecutar; rechazar si cambió

**Tests nuevos:**
- `test_e_propose_launch_phase_creates_jobs`
- `test_e_rejected_decision_does_not_execute`
- `test_e_job_failed_marked_failed_not_succeeded`
- `test_e_budget_exhausted_stops_new_jobs`
- `test_e_resume_does_not_duplicate_jobs`
- `test_e_state_version_changed_rejects_decision`

---

### P0-06: Presupuestos aplicados antes de inicializar

**Archivos a modificar:**
- `arena_forge.py` → `cmd_init()`, `cmd_plan()`, `agent_e.budget_for()`
- `forge/agent_e.py` → `budget_for()`

**Cambios:**
1. Default Answer: 4 agentes (no 100) para `quick`/`standard`; 100 solo explícito
2. `cmd_init()` valida `agents <= budget.max_candidates` del perfil; rechaza si excede
3. `cmd_plan()` muestra presupuesto exacto del perfil y rechaza si `--agents` excede
4. `extreme`: exige `--confirm` + muestra plan detallado (jobs, olas, llamadas, tiempo, límites)
5. Una sola fuente de verdad: `agent_e.BUDGET_PROFILES` usado por `plan`, `init`, `agent_e`

**Tests nuevos:**
- `test_init_answer_default_4_agents`
- `test_init_agents_exceeds_profile_rejected`
- `test_extreme_requires_confirm_with_plan`
- `test_budget_exact_limit_enforced`

---

## P1 — Brechas funcionales importantes

### P1-01: Separar workflows Answer y Patch

**Archivos a modificar:**
- `arena_forge.py` → `cmd_next()`, `cmd_resume()`, `cmd_collect()`, `cmd_advance()`, `cmd_report()`, `cmd_cancel()`

**Cambios:**
1. Dispatcher por `run.get("mode")`:
   - `answer`: usa `vendor/arena-skill/bracket.py` (existente)
   - `patch`: jobs propios (implement, review, gates, judge, decide, export)
2. `cmd_resume()` para Patch: reconstruye jobs Patch desde ledger/registro, NO llama `bracket next`
3. IDs consistentes: `cand-XX` desde `init` → prompts → outputs → gates → judge → report

---

### P1-02: Permisos de agentes por mínimo privilegio

**Archivos a modificar:**
- `.opencode/agents/implementer.md`
- `.opencode/agents/reviewer.md`
- `.opencode/agents/judge.md`
- `.opencode/agents/scout.md`

**Cambios:**
1. `implementer`: `edit` solo en `.arena/candidates/<su_candidato>/**` y `.arena/scratch/<su_candidato>/**`
2. `reviewer`: `edit` solo en `.arena/artifacts/reviews/<su_review>.md` (output propio)
3. `judge`: `edit` solo en `.arena/artifacts/verdicts/<su_veredicto>.json`
4. `scout`: `read` en todo, `edit`/`shell` deny (ya está bien)
5. Runtime (CLI) es el único que escribe `forge.json`, `ledger.jsonl`, `gates.json`, `suite`, `patch_map.json`, `decisions.jsonl`

**Tests nuevos:**
- `test_implementer_cant_write_other_candidate`
- `test_implementer_cant_write_forge_json`
- `test_reviewer_cant_write_rival_candidate`
- `test_judge_cant_write_state`

---

### P1-03: Un solo motor de decisión autoritativo

**Archivos a modificar:**
- `forge/report.py` → `resolve()` (motor único)
- `forge/score.py` → `evaluate_patch_judgement()` (usado por resolve)
- `arena_forge.py` → `resolve_patch_winner()` → DELEGAR a `report.resolve()`
- `arena_forge.py` → `cmd_apply()` → DELEGAR a `report.resolve()`

**Cambios:**
1. `report.resolve()` = única fuente de verdad para `WINNER/NO_SHIP`
2. `patch_map.json` obligatorio, por match, versionado, aleatorizado reproducible (seed)
3. Sin fallback silencioso a orden alfabético
4. Validar schema completo del veredicto: todas las dimensiones requeridas, rangos 0-10, referencias a artefactos existentes
5. `apply` y `report` usan exactamente la misma decisión persistida

**Tests nuevos:**
- `test_report_and_apply_same_decision`
- `test_mapping_missing_duplicated_invalid_blocks`
- `test_evidence_refs_must_exist`
- `test_dimensions_incomplete_out_of_range_blocks`

---

### P1-04: Probe de capacidades OpenCode veraz y vigente

**Archivos a modificar:**
- `forge/adapter.py` → `probe()`, `load_capabilities()`
- `docs/RECONNAISSANCE.md` (regenerar desde ejecución real)
- `runtime/capabilities.json` (regenerar)

**Cambios:**
1. `probe()` ejecuta prueba real por capacidad:
   - `skill_load`: `opencode skill load arena-forge` → exit code
   - `subagent_tool`: `opencode run --prompt "subagent test"` → verifica llamada real
   - `readonly_agent`: invoca agente `explore` y verifica que no puede editar
   - `cwd_control`: subagent con `cwd` explícito y verifica aislamiento
   - `permission_rules`: crea agente con permisos y prueba allow/deny
2. Guardar: versión, timestamp, comando, exit code, stdout/stderr, evidencia
3. `UNKNOWN` si no se probó; `UNSUPPORTED` si se probó y falló
4. `verify` exige TODAS las capacidades requeridas para el modo (no solo ≥1)

---

### P1-05: Benchmark real del valor de E

**Archivos a modificar:**
- `forge/benchmark.py` → separar `benchmark_scheduler_gates()` de `benchmark_compare_methods()`
- Nuevo: `fixtures/benchmark/` con dataset versionado

**Cambios:**
1. Mantener benchmark de scheduler/gates (determinista, rápido)
2. Añadir `benchmark_compare_methods()` que ejecuta tareas reales comparando:
   - `single_agent` (agente único bien instruido)
   - `fixed_orchestration` (policy fija)
   - `arena_e_adaptive` (E adaptativo)
3. Dataset: `small/`, `medium/`, `adversarial/` con gold/buggy + suite protegida
4. Métricas: acceptance_rate, escaped_defects, regressions, cost_calls, duration, rounds_changed_decision, human_review_effort
5. Repetir por seeds; guardar todos los outputs
6. Si no se puede ejecutar en CI/sesión → `NOT_RUN` explícito con razón y pasos pendientes

---

### P1-06: Ledger, concurrencia y recuperación

**Archivos a modificar:**
- `forge/ledger.py` → `log_event()`, `verify()`, `read()`
- `arena_forge.py` → locks unificados para TODAS las mutaciones

**Cambios:**
1. Hash chain: cada evento incluye `prev_hash` + `content_hash`; `verify()` valida cadena
2. No suprimir excepciones de escritura → si falla persistencia, bloquear avance
3. Lock unificado (`lock.json` + `fcntl`/`msvcrt` o archivo lock) para TODAS las mutaciones: gates, resume, report, cancel, decide, collect, advance
4. Job registry en `forge.json`: `jobs: {job_id: {phase, session_id, status, output_ref, attempts, timeout, pid, cancelable}}`
5. `cancel`: marca jobs `RUNNING` → `CANCELLED`; si sesión OpenCode no cancelable → registra `logical_only` + riesgo

---

### P1-07: Suite de pruebas completa y CI

**Archivos a crear/modificar:**
- `tests/test_audit_p0.py` (tests P0)
- `tests/test_audit_p1.py` (tests P1)
- `.github/workflows/ci.yml` (CI GitHub Actions)
- Ampliar `tests/test_forge.py` con casos faltantes

**Tests obligatorios por criterio AF-AC:**
| AF-AC | Test requerido |
|-------|----------------|
| 005 | `test_answer_e2e_4_agents` |
| 006 | `test_patch_e2e_nested_git_repo` |
| 007 | `test_gate_precedes_judge_enforced` |
| 008 | `test_no_ship_all_fail` |
| 009 | `test_resume_patch_reconciles_jobs` |
| 010 | `test_sandbox_isolation_enforced` |
| 011 | `test_report_requires_valid_gates_isolation` |
| 012 | `test_ci_runs_all_checks` |
| 013 | `test_apply_exports_patch_only` |
| 014 | `test_clean_checkout_reproducible` (manual/doc) |
| 015 | `test_e_enforces_budgets_and_permissions` |
| 016 | `test_benchmark_compares_methods_or_not_run` |
| 017 | `test_decision_auditable_hash_chain` |
| 018 | `test_no_false_pass_without_execution` |

---

### P1-08: Resume y cancel con control real de jobs

**Archivos a modificar:**
- `arena_forge.py` → `cmd_resume()`, `cmd_cancel()`, job registry

**Cambios:**
1. Job registry en `forge.json` con estado por job
2. `resume` reconcilia: `PENDING`→re-lanzar, `RUNNING`→verificar sesión, `DONE`→saltar, `FAILED`→reintentar según política
3. `cancel`: transiciona jobs `RUNNING` a `CANCELLED`; si sesión OpenCode no terminable → registra `logical_only` + PID si disponible

---

### P1-09: Baseline de demos reales (no `n/a-no-repo`)

**Archivos a modificar:**
- `fixtures/patch-demo/` → convertir a repo Git real con commit
- `demo/patch-e2e.md`, `demo/no-ship.md` → regenerar desde nueva implementación

**Cambios:**
1. `fixtures/patch-demo/` = repo Git con `src/`, `tests/`, commit conocido
2. `init --mode patch --baseline-dir fixtures/patch-demo` usa baseline real
3. Demos regeneradas muestran baseline commit real, diffs completos, patch aplicable

---

## P2 — Calidad de producto y documentación

### P2-01: Privacidad rutas locales en informes públicos

**Archivos a modificar:**
- `forge/report.py` → `render_markdown()`, `render_html()` → reemplazar rutas absolutas con `<checkout-root>`
- Regenerar `demo/*.md`, `reports/*.md`, `docs/RECONNAISSANCE.md`

---

### P2-02: Semántica de `apply` → `export-patch`

**Archivos a modificar:**
- `arena_forge.py` → renombrar comando `apply` a `export-patch` (mantener alias `apply` con warning)
- `README.md`, `SKILL.md`, docs

---

### P2-03: Exit codes y JSON outputs claros

**Archivos a modificar:**
- `arena_forge.py` → todos los comandos: exit code 0 = comando OK, 1 = error runtime, 2 = validación falló
- Gates: `state` en JSON separa `command_status` de `gate_state`

---

### P2-04: Refresh reconocimiento y capabilities

**Archivos a modificar:**
- `docs/RECONNAISSANCE.md` (regenerar)
- `runtime/capabilities.json` (regenerar desde `adapter.probe()` real)

---

### P2-05: Comandos copy/paste válidos Windows/POSIX

**Archivos a modificar:**
- `README.md` → separar comentarios de comandos, usar `::` solo en batch, `#` en shell

---

## Matriz de aceptación final (objetivo: todo PASS)

| ID | Criterio | Estado objetivo | Evidencia requerida |
|----|----------|-----------------|---------------------|
| AF-AC-001 | Reconocimiento | PASS | `docs/RECONNAISSANCE.md` fresco + `runtime/capabilities.json` coincidente |
| AF-AC-002 | Upstream | PASS | `THIRD_PARTY_NOTICES.md` hashes verificados |
| AF-AC-003 | Skill V2 | PASS | Skill carga + invocación TUI verificada |
| AF-AC-004 | CLI | PASS | Todos comandos funcionan con datos reales, dispatch Answer/Patch |
| AF-AC-005 | Answer E2E | PASS | 4 agentes, bracket, artefacts, reporte |
| AF-AC-006 | Patch E2E | PASS | Repo Git anidado, baseline real, patch aplicable, WINNER/NO_SHIP |
| AF-AC-007 | Gates preceden score | PASS | Hash suite congelado validado, aislamiento requerido, judge no anula |
| AF-AC-008 | NO_SHIP | PASS | Demo + test automatizado |
| AF-AC-009 | Reanudación | PASS | Resume Patch reconcilia jobs sin duplicar |
| AF-AC-010 | Seguridad | PASS | Sandbox real O modo BLOCKED documentado + tests adversariales |
| AF-AC-011 | Informe | PASS | Decisión única, hashes, evidencia, límites, riesgos |
| AF-AC-012 | Tests/CI | PASS | 35+ tests + CI + NOT_RUN declarado |
| AF-AC-013 | Protección repo | PASS | Export-patch only, baseline intacto, diffs recursivos |
| AF-AC-014 | Checkout limpio | PASS | Documentado y verificado manualmente |
| AF-AC-015 | E bajo control | PASS | Presupuestos, permisos, gates, sin auto-ejecución |
| AF-AC-016 | Valor E adaptativo | NOT_RUN (explícito) | Benchmark comparativo O declarado NOT_RUN con razón |
| AF-AC-017 | Decisión auditable | PASS | Ledger hash chain + decisions.jsonl + refs |
| AF-AC-018 | Sin éxito ficticio | PASS | No verified/True sin comprobación real |

---

## Orden de ejecución recomendado

### Semana 1: P0 (integridad/seguridad)
1. P0-01 Aislamiento precondición real
2. P0-03 Suite hash congelado validado
3. P0-06 Presupuestos aplicados
4. P0-04 Baseline/diff recursivo
5. P0-02 Sandbox real O modo BLOCKED documentado
6. P0-05 E orquestador real

### Semana 2: P1 (flujos/decisiones)
7. P1-01 Workflows Answer/Patch separados
8. P1-02 Permisos mínimo privilegio
9. P1-03 Motor decisión único
9. P1-04 Probe veraz
10. P1-06 Ledger hash chain + locks
11. P1-08 Resume/cancel jobs reales
12. P1-09 Baseline demos reales

### Semana 3: P1-05 Benchmark + P1-07 Tests/CI + P2
13. P1-05 Benchmark comparativo (o NOT_RUN documentado)
14. P1-07 Suite tests completa + CI
15. P2-01..05 Docs, privacidad, exit codes, comandos

---

## Criterios de salida para "LISTO"

- [ ] Todos los P0 tienen tests automatizados que fallaban antes y pasan después
- [ ] `report.resolve()` es motor único; `apply` y `report` decisión idéntica
- [ ] Suite hash congelado validado en gates, report, verify, apply
- [ ] Aislamiento real demostrado O Patch ejecutable = BLOCKED explícito
- [ ] Baseline/diff/apply recursivos en repo Git anidado
- [ ] E propone + ejecuta (o boundary explícito documentado)
- [ ] Presupuestos aplicados en plan/init
- [ ] Answer E2E, Patch E2E, NO_SHIP, resume, cancel, tests adversariales corren con artefactos frescos
- [ ] Benchmark comparativo ejecutado O AF-AC-016 = NOT_RUN explícito
- [ ] Otra persona reproduce desde checkout limpio siguiendo README

---

## Formato de entrega final (para la IA)

1. Resumen de cambios + lista exacta archivos modificados
2. Tabla AF-AC-001..018 con PASS/FAIL/BLOCKED/NOT_RUN + refs evidencia
3. Comandos exactos, versiones, exit codes, resumen pruebas
4. Resultados E2E Answer, Patch, NO_SHIP, seguridad, resume, cancel
5. Evidencia baseline original intacto
6. Resultados benchmark + límites estadísticos
7. Capacidades OpenCode verificadas/no verificadas
8. Riesgos residuales + motivo concreto
9. Decisión general: COMPLETE / PARTIAL / BLOCKED / FAILED

**NO** cambiar definiciones para obtener PASS. **NO** ocultar fallos. **NO** decir que test pasó sin ejecutarlo. **NO** presentar sintético como general.
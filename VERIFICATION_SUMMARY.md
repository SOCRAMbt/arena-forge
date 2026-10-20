# Arena Forge — Resumen de verificación (auditoría forense)

**Fecha:** 19 de octubre de 2026
**Commit auditado:** `875c04ae1f7865c8043db651708d471c4a8d334e` + remediación de esta
auditoría (árbol de trabajo con cambios, **sin commit** en el momento de escribir esto)
**Repositorio:** https://github.com/SOCRAMbt/arena-forge
**Entorno:** Windows 11 10.0.26200-SP0 AMD64 · Python 3.12.4 · pytest 9.1.1 ·
Git 2.51.0.windows.1 · OpenCode v2.0.32

---

## 🔴 Estado global: **NO-GO**

16 PASS · 2 PARTIAL · 0 FAIL · 0 NOT_RUN · 0 BLOCKED. Ponderado **94.4 %**.

NO-GO por dos razones verificables:

1. **§23 (regla final):** el coordinador no puede ser la unica autoridad que
   certifique su propio exito. Falta la reproduccion por un **tercero
   independiente** (AF-AC-014 -> PARTIAL).
2. **Aislamiento de nivel OS (AF-AC-010 -> PARTIAL):** no hay Job Object,
   AppContainer, usuario de minimos privilegios ni red bloqueada. Modo
   `TRUSTED_CODE_ONLY` declarado (ADR-006, THREAT_MODEL).

Detalle completo: [`reports/audit/final-audit.md`](reports/audit/final-audit.md).

## P0 — estado tras la remediación

| ID | Requisito | Estado | Evidencia |
|----|-----------|--------|-----------|
| P0-1 | Parche binario canónico y byte-exacto | ✅ PASS | `git diff --binary` real (base85 de Git); round-trip exacto para texto, binario con/sin NUL, alta, baja, mixto, UTF-8 inválido; `git apply --check` exit 0 |
| P0-2 | Contención de rutas en el parche | ✅ PASS | Se validan `diff --git`, `---`, `+++`, `rename to`, `copy to`; nada se escribe fuera del scratch |
| P0-3 | Symlinks y lectura: fail-closed | ✅ PASS | Symlink externo/roto/interno → el manifiesto falla; el gate marca `BLOCKED/unsafe_candidate` |
| P0-4 | Gate no falsificable | ✅ PASS | El veredicto exige el informe JUnit: `os._exit(0)` en el import **no** da PASS |
| P0-5 | Suite / baseline / manifiesto / artefacto revalidados | ✅ PASS | `forge/integrity.py`: suite viva recalculada, baseline congelado, manifiesto por candidato, `diff_sha` recalculado y `sha256(parche exportado)` comparado |
| P0-6 | Decisión ↔ winner ↔ artefacto | ✅ PASS | `decision_id` persistido; `apply` aplica el ganador **persistido**, nunca `eligible[0]` |
| P0-7 | Presupuesto de E y aprobación humana | ✅ PASS | Reserva atómica bajo lock de SO antes de crear el job; la aprobación debe estar **ligada** a la decisión |
| P0-8 | Aislamiento de OS | 🔴 **BLOCKED** | No hay Job Object/AppContainer/usuario mínimo/red bloqueada. Modo `TRUSTED_CODE_ONLY` |
| P0-9 | Contrato funcional disponible | 🔴 **BLOCKED** | `ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md` no está en el checkout |

---

## P1 — estado tras la remediación

| ID | Requisito | Estado | Evidencia |
|----|-----------|--------|-----------|
| P1-01 | Definiciones duplicadas eliminadas | ✅ PASS | `NoDuplicatesTest::test_no_duplicate_top_level_definitions` (AST sobre `arena_forge.py` + `forge/*.py`) |
| P1-02 | Sondas OpenCode honestas | ✅ PASS | Un error de sintaxis CLI es `inconclusive`, nunca `unsupported`; el texto de ayuda no prueba denegación; `state_on_disk` hace ida y vuelta real; `agent_profiles` con la ruta correcta; `permission_rules` **no** se declara `verified` por documentación |
| P1-03 | Matriz de capacidades por modo | ✅ PASS | `MODE_REQUIREMENTS` (answer/patch/benchmark) con obligatorias vs opcionales; `cmd_verify` ya no acepta `verified > 0` |
| P1-04 | `decisions.jsonl` append-only | ✅ PASS | Nunca se reescribe; las líneas corruptas se preservan y se listan |
| P1-05 | Ledger con lock y cadena continua | ✅ PASS | Lock de SO; `seq`/`prev_hash` derivan del último evento **válido**; la manipulación se detecta |
| P1-06 | Transiciones por la máquina de estados | ✅ PASS | `DECIDING → REPORTING → COMPLETED/NO_SHIP`; un run CANCELLED no se reabre |
| P1-07 | Tests portables | ✅ PASS | Sin rutas del host; `pytest.ini` evita recolectar la suite protegida |
| P1-08 | CI Windows/Linux | ⚠️ **NOT_RUN** | Workflow creado; **no ejecutado** hasta el push |
| P1-09 | Redactor de secretos | ✅ PASS | 9 formatos cubiertos (AWS, URLs con credenciales, `xoxb-`, `ghp_`, `github_pat_`, `Bearer`, claves privadas) |
| P1-10 | Benchmark adaptativo | ⚠️ **NOT_RUN** | AF-AC-016 declarado, no estimado |
| P1-11 | Despacho real de agentes por el runtime | ⚠️ **NOT_RUN** | El runtime solo escribe briefs; el E2E es **asistido** |
| P1-12 | Score del juezparticipa en la decisión | ⚠️ **NOT_RUN** | Las dimensiones se calculan y se descartan; la etiqueta X/Y decide sola |

---

## Capacidades OpenCode V2 (probe real, `runtime/capabilities.json`)

| Capacidad | Estado | `by` | Evidencia |
|-----------|--------|------|-----------|
| `shell_tool` | verified | host | Ejecución de comandos del **host**; no es el shell tool de OpenCode |
| `cwd_control` | verified | host | `cwd` de un subprocess local; no es una capacidad del runtime |
| `python_runtime` | verified | platform | Python 3.12.4 |
| `state_on_disk` | verified | functional_test | Run creado, cerrado, reabierto y reanudado; ledger verificado |
| `agent_profiles` | verified | filesystem | `.opencode/agents`: implementer, judge, reviewer, scout |
| `skills_native` | **inconclusive** | functional_test | Frontmatter V2 válido, pero el runtime no la lista por ID en esta instalación |
| `permission_rules` | **unknown** | static_analysis | Orden de reglas correcto (4 permisos); la **enforcement** en runtime no está probada |
| `subagent_tool` | **blocked** | functional_test | Requiere llamada a modelo (coste no autorizado) |
| `readonly_agent` | **blocked** | functional_test | Requiere llamada a modelo (coste no autorizado) |
| `subagent_foreground` | **blocked** | derived | Derivado de `subagent_tool` (no se hace una segunda llamada) |
| `subagent_background` | unknown | none | NOT_RUN: sesión prolongada + modelo |
| `plugin_api` | unknown | none | NOT_RUN: no se usa en el producto |

> En la versión anterior, cuatro capabilities estaban `verified` **sin prueba real**
> (`readonly_agent` por el texto de ayuda de la CLI, `state_on_disk` con retorno
> incondicional, `cwd_control`/`shell_tool` por un `cmd /c` local, `permission_rules` por
> documentación) y tres `unsupported` **por sintaxis inválida**. Corregido.

---

## Riesgos residuales

1. **Sin sandbox de OS** — el código del candidato se ejecuta con los privilegios del
   operador. Modo `TRUSTED_CODE_ONLY` declarado en el código, en cada `GateResult`, en
   `verify` y en la salida de `apply`.
2. **E2E asistido, no autónomo** — un operador coloca el resultado en el workspace.
3. **El ledger no es tamper-proof** — la cadena de hashes detecta corrupción y ediciones
   accidentales; sin ancla externa, un actor con permiso de escritura puede rehacerlo.
4. **Permisos de agente por run, no por candidato** — un implementer podría escribir en el
   workspace de un rival (riesgo de contaminación entre candidatos).
5. **El juez decide solo por etiqueta X/Y** — las dimensiones se calculan pero no
   condicionan la elección.
6. **Modelo no determinista** — el seed fija scheduler/tarjetas/bracket, no las respuestas.
7. **Coste monetario no medible** — la API no expone tokens; los límites reales son
   llamadas/olas/tiempo.
8. **La CI no se ha ejecutado** — configurada, no verificada.

---

## Evidencia versionada (verificable por un tercero)

`reports/audit/artifacts/` contiene la cadena de decisión del E2E Patch —
`gates.json`, `decision.json`, `isolation.json`, `ledger.jsonl`, el parche
round-trip y `SHA256SUMS.txt`. El test `AuditArtifactsTest` comprueba en la CI que
`sha256(parche) == diff_sha del gate == diff_sha de decision.json` y que el parche
aplica sobre un baseline limpio.

Además, `fixtures/patch-demo/binary/sample.bin` es un artefacto binario
persistido (NUL + cola no-UTF-8) que hace el round-trip binario reproducible
desde un checkout limpio.

## Decisión final

**NO-GO** para "COMPLETE / 100 %".

**GO** para el resto: el sistema es ejecutable, auditable, reanudable y ahora **verificable
byte a byte**: el parche que se entrega es el diff que se evaluó, y el parche aplicado
reproduce exactamente el árbol del candidato evaluado.

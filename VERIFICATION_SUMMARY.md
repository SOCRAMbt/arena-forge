# Arena Forge — Resumen de verificación (auditoría forense)

**Fecha:** 19 de octubre de 2026
**Commit auditado:** `875c04ae1f7865c8043db651708d471c4a8d334e` + remediación de esta
auditoría (árbol de trabajo con cambios, **sin commit** en el momento de escribir esto)
**Repositorio:** https://github.com/SOCRAMbt/arena-forge
**Entorno:** Windows 11 10.0.26200-SP0 AMD64 · Python 3.12.4 · pytest 9.1.1 ·
Git 2.51.0.windows.1 · OpenCode v2.0.32

---

## 🔴 Estado global: **NO-GO**

**No se declara COMPLETE ni 100 %.** Motivos:

1. **AF-AC-010 en FAIL**: no existe frontera de sistema operativo para el código del
   candidato. Modo declarado `TRUSTED_CODE_ONLY`.
2. **Contrato funcional ausente**: `ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md` no está
   en el checkout → AF-AC/§16 no certificables de forma autoritativa (BLOCKED).
3. **AF-AC-016 en NOT_RUN**: la eficacia adaptativa de E no está medida (declarado, no
   fabricado).
4. **CI no ejecutada**: `.github/workflows/ci.yml` se crea en esta auditoría pero no corre
   hasta el push.

**Matriz completa y cálculo por código:** [`reports/audit/acceptance-matrix.md`](reports/audit/acceptance-matrix.md).
**Hallazgos con reproducción y evidencia:** [`reports/audit/findings.md`](reports/audit/findings.md).
**Decisión final:** [`reports/audit/final-audit.md`](reports/audit/final-audit.md).

---

## Tests: 113 passed (exit 0)

```console
$ python -m pytest tests/ -v --no-header -p no:cacheprovider --timeout=180
======================= 113 passed in 347.93s (0:05:47) ========================
```

Detalle por test (comando, exit code, versiones, commit, hashes de entrada, artefactos):
[`reports/audit/test-results.json`](reports/audit/test-results.json).

- Los tests **no escriben dentro del repo**: `adapter.probe(persist=False)` y
  `bench_mod.run(out_file=...)`.
- Las rutas se derivan de `Path(__file__).resolve()`: **sin rutas absolutas del host**
  (verificado por `PortabilityTest::test_no_absolute_host_paths_in_tests`).
- Los manifiestos se **calculan** en runtime: no hay constantes que dependan de los
  finales de linea del checkout.

---

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

## Decisión final

**NO-GO** para "COMPLETE / 100 %".

**GO** para el resto: el sistema es ejecutable, auditable, reanudable y ahora **verificable
byte a byte**: el parche que se entrega es el diff que se evaluó, y el parche aplicado
reproduce exactamente el árbol del candidato evaluado.

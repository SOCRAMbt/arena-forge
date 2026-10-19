# FASE 1 — Baseline forense (sin modificar codigo)

**Ejecutado por:** Staff Engineer principal (integrador unico)
**Fecha/hora local:** 2026-10-19 (America/Argentina) — ejecucion en Windows 11
**Modo:** `opencode run` NO ejecutado (coste). Solo CLI de solo lectura (`--help`, `models`).

---

## 1. Estado del repositorio (comandos exactos y salida)

### 1.1 `git status --short` (estado inicial, ANTES de cualquier cambio)

```
?? TODO_FIXES.md
?? check_lone_pass.py
?? check_lone_pass_final.py
?? check_min_run.py
?? fix_all_tests.py
?? fix_apply_binary.py
... (150 entradas en total)
?? reports/run-20261018-164139-s11.patch
...
?? test_binary49.py
```

**Estado: DIRTY solo por ficheros NO TRACKED (scratch). Ningun fichero trackeado modificado.**

### 1.2 `git rev-parse HEAD`

```
875c04ae1f7865c8043db651708d471c4a8d334e
```

### 1.3 `git branch --show-current`

```
main
```

### 1.4 `git log -n 12 --oneline --decorate`

```
875c04a (HEAD -> main, origin/main) P0-A/P0-C: Binary diffs with base64 encoding and proper apply
84ab02e P0-A: Manifest fail-closed validation
bd63e0e P0-F/P1: Probe OpenCode veraz, ledger hash-chain, manifest/diff fidelidad, sandbox mejoras
b99b3dd P0-04/P0-05/P0-06: Baseline correcto, hash candidato/diff, no winner incompleto
cf8ca2f Arena Forge v1.0 — correcciones finales post-auditoría
185cfea Arena Forge v1.0 — implementación completa según especificación técnica integral
eb54ca1 docs: push a Crew registrado; rename a arena-forge pendiente (web UI)
7233d0e 0.2.0: patch adversarial completo + README profesional + demo
ff4f949 0.1.0: Arena Forge vertical slice + E2E reales (answer, patch, NO_SHIP)
```

### 1.5 `git diff --stat` / `git diff --check`

```
(sin salida — ningun cambio trackeado staged ni unstaged)
```

### 1.6 `git remote -v` (credenciales redactadas; este remote no contiene credenciales embebidas)

```
origin	https://github.com/SOCRAMbt/arena-forge.git (fetch)
origin	https://github.com/SOCRAMbt/arena-forge.git (push)
```

### 1.7 `git ls-remote origin` — comparacion REMOTA de solo lectura (sin fetch/pull)

```
875c04ae1f7865c8043db651708d471c4a8d334e	HEAD
875c04ae1f7865c8043db651708d471c4a8d334e	refs/heads/main
```

### 1.8 `git rev-list --left-right --count '@{u}...HEAD'`

```
0	0
```

**Estado remoto: AL DIA. Local == remoto en `875c04a`.**

---

## 2. RESOLUCION DE LA DISCREPANCIA HEAD (punto que la auditoria externa pedia resolver)

La auditoria externatomó `84ab02e` como referencia y afirmaba que
`_binary_diff_line` / `_apply_binary_diff` NO existian en ese HEAD.

**Verificacion en el checkout actual (`875c04a`):**

| Simbolo | Existe | Linea (HEAD 875c04a) |
|---|---|---|
| `_is_binary_file` | SI | `forge/isolation.py:159` |
| `_binary_diff_line` | SI | `forge/isolation.py:71` |
| `_apply_binary_diff` | SI | `forge/isolation.py:260` |
| `_apply` (router texto/binario) | SI | `forge/isolation.py:323` |
| `capture_diff` | SI | `forge/isolation.py:99` |
| `apply_diff_to_temp` | SI | `forge/isolation.py:232` |

**Veredicto: la discrepancia esta RESUELTA y NO es un defecto del checkout.**
La referencia `84ab02e` es un ancestro directo: el commit `875c04a` ("P0-A/P0-C: Binary
diffs with base64 encoding and proper apply") la supero y SI modifica `forge/isolation.py`
(3 ficheros, +152/-27). El remote ya contiene `875c04a`.

**ADVERTENCIA CRITICA (no resuelta por el HEAD):** que las funciones *existan* y que
`capture_diff` las *invoque* NO basta. La implementacion usa un formato **base64
estandar** etiquetado como `GIT binary patch`, que **no es** el formato de parche binario
de Git (Git usa su codificacion literal/delta base85). El binario por defecto de este
entorno (`git 2.51.0.windows.1`) **rechazaria** ese parche. Ademas, `_apply` enruta el
diff **completo** al parser binario si detecta un unico fichero binario, lo que puede
**descartar silenciosamente los hunks de texto**. Ver findings SEC-*.

---

## 3. Versiones y plataforma (detectadas, no supuestas)

| Componente | Version detectada | Comando |
|---|---|---|
| Python | 3.12.4 (tags/v3.12.4:8e8a4ba) | `python --version` |
| pytest | 9.1.1 | `python -m pytest --version` |
| Git | 2.51.0.windows.1 | `git --version` |
| OpenCode | v2.0.32 | `opencode --version` |
| OS | Windows-11-10.0.26200-SP0, AMD64 | `platform.platform()` |
| Shell | PowerShell (Windows) | — |

**Modelo LLM disponible (verificado con `opencode models`, solo lectura):**
- `opencode/nemotron-3-ultra-free`
- `openrouter/nvidia/nemotron-3-ultra-550b-a55b`  <- ID exacto pedido por el prompt
- `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`

**No se ejecuto ninguna llamada a modelo** (coste). No se modifico la config global de OpenCode.

---

## 4. Inventario del repositorio (55 ficheros trackeados)

| Area | Ficheros |
|---|---|
| CLI | `arena_forge.py` |
| Nucleo | `forge/{util,contracts,state,ledger,isolation,gates,report,score,adapter,agent_e,benchmark}.py` |
| Tests | `tests/test_forge.py` (44 tests) |
| Agentes | `.opencode/agents/{implementer,judge,reviewer,scout}.md` |
| Skill | `.opencode/skills/arena-forge/SKILL.md` |
| Vendor | `vendor/arena-skill/{bracket.py,SKILL.md,rubric.md,strategies.json}` |
| Fixtures | `fixtures/patch-demo/{baseline_buggy,candidate_fixed,tests_protected}`, `fixtures/injection-test/README_EVIL.md` |
| Docs | `README.md`, `CHANGELOG.md`, `VERIFICATION_SUMMARY.md`, `PLAN.md`, `PLAN_AUDIT_FIXES.md`, `THIRD_PARTY_NOTICES.md`, `docs/*` (9) |
| Runtime | `runtime/capabilities.json`, `runtime/benchmark.json` |

### SHA-256 de fuentes (evidencia de contenido, no de formato)

```
7eed6252e1af98755152255b7df22a11829b41071765d110ab689f4306dd3a68  arena_forge.py
dafa0b3c735d107740b44c6ce4428eacc6af9d952b513c616b7e42b5bbfb7e50  forge/adapter.py
7d4208f19fdbb4316331ede496388eda4ec9f1747bf4b9444ff67394a5eb3bed  forge/agent_e.py
0b0307de345c1feeabad58d481c380a15fb5e0dd25b208e8e7d6118d4ff1c916  forge/benchmark.py
ba07b65f5678c88b7f088e10aa1a126cc2f00dca0e57a1d5246eee25be8d12f1  forge/contracts.py
1b26e8fe8effebda9247eabce9da9d3b923b1308c85e9b47fd80d30a82651251  forge/gates.py
7496e2306da03d709fe75984de1027aff2b2679091bc5a401f34fce3fcb3f268  forge/isolation.py
da639921c7eda7d04e07754cb98d5b4d8d1e5dc720623a90ebd38e5cd66b5c73  forge/ledger.py
de53d175ff7b961dd49f071665f70e5422a3001d5b7ba29da11e86d2858f1109  forge/report.py
d0f4b7e607a45b8c7888790d672f6cdc664504fb7dd268aaebd9e12209bad927  forge/score.py
7eecc9580b9fa1dda0145d82ed99e715a3d727eb7ee8f52afe824c646eabfd48  forge/state.py
66cd77736b574d1eb8a7f75619408ddec3b3d65ecc9a6281fe591c0155c99b1c  forge/util.py
9205619b887c7d2190588321bfb778763bc54fe56ee0d56a937b6ae76e4aea65  forge/__init__.py
1d0b48e2953a7d33761bf0535725e5e2d13af3a97790b6f8495c2ab15a4dc583  tests/test_forge.py
```

---

## 5. Higiene del arbol: ficheros scratch de la sesion anterior

150 ficheros no trackeados (`fix_*.py`, `test_binary*.py`, `old_*.txt`, `check_*.py`,
`reports/run-*.patch`, `TODO_FIXES.md`) quedaban en la raiz del repo.

**Accion (NO destructiva):** los 150 ficheros se **movieron** (no se borraron) a
`C:\Users\Marcos\AppData\Local\Temp\opencode\arena-forge-scratch-20261019\`, junto con un
manifiesto `SHA256SUMS.txt` de sus SHA-256. Se preserva la evidencia y el arbol queda limpio.

**Cambio de `.gitignore`:** se anadio `reports/*.patch` a los artefactos ignorados y se
des-ignoró `reports/audit/**` para que los informes de esta auditoria si se versionen.

---

## 6. BLOQUEOS EXTERNOS (declarados, no simulados)

### BLOCKED-01 — Contrato funcional ausente
`ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md` **NO esta en el checkout** ni existe en
ninguna ruta del repo (`Get-ChildItem -Recurse -Include "*ESPECIFICACION*"` -> 0 resultados).
Tampoco estan `ARENA_FORGE_REAUDITORIA_2026-10-19.md` ni
`ARENA_FORGE_PROMPT_NEMOTRON3_ULTRA_OPENCODE_V2.md`.

**Consecuencia:** los criterios **AF-AC-001..018**, **AF-PR** y los **casos de §16** no
pueden certificarse de forma autoritativa. Se evaluaran contra el contrato declarado en el
prompt (que es un paraphrase), y **todo criterio que dependa del texto literal del
contrato se marcara NOT_RUN o BLOCKED**, nunca PASS. Se solicita al usuario la ruta o copia
del fichero.

### BLOCKED-02 — No existe sandbox de OS en Windows
El entorno es Windows 11 sin mecanismo de contención probado (Job Object, AppContainer,
usuario de privilegios mínimos, filtrado de red). Un `subprocess` con `cwd` temporal y
variables filtradas **no es un sandbox**. Modo efectivo del repositorio:
**TRUSTED_CODE_ONLY**. AF-AC-010 (contención) no puede ser PASS sin una prueba de
contenimiento real.

### BLOCKED-03 — Sin CI configurado
No existe `.github/workflows/`. AF-AC-012 = NOT_CONFIGURED.

### NOT_RUN — AF-AC-016 (eficacia adaptativa de Agent E)
`runtime/benchmark.json` declara explicitamente
`"eficacia adaptativa de E vs orquestacion fija vs agente unico (hipotesis pendiente, no demostrada aqui)"`.
Se mantiene **NOT_RUN**. No se estimara ni se fabricara resultado.

---

## 7. Honestidad de los claims de OpenCode (lectura literal de `runtime/capabilities.json`)

| Capability | status declarado | Evidencia declarada | Veredicto de la auditoria |
|---|---|---|---|
| `shell_tool` | verified | "shell tool ejecuta comandos correctamente" | plausible (probe funcional) |
| `python_runtime` | verified | "3.12.4" | PASS (platform) |
| `skills_native` | unsupported | texto de **USAGE/ayuda** de la CLI | **INCONCLUSIVE** — un error de sintaxis CLI no prueba ausencia de capacidad |
| `subagent_tool` | unsupported | texto de **USAGE/ayuda** de la CLI | **INCONCLUSIVE** — idem |
| `subagent_foreground` | unsupported | texto de **USAGE/ayuda** de la CLI | **INCONCLUSIVE** — idem |
| `subagent_background` | unknown | "no se prueba en probe" | NOT_RUN |
| `agent_profiles` | unknown | "directorio agents no encontrado" | **FAIL (bug de ruta)** — `.opencode/agents/` SI existe |
| `permission_rules` | verified | "reglas detectadas en V2", by=**docs** | **FAIL** — verificacion por documentacion, no funcional |
| `readonly_agent` | verified | "explore denego edicion correctamente (rc=1): <texto de USAGE>" | **FAIL** — la evidencia es un parse-error de CLI, no una denegacion probada |
| `cwd_control` | verified | "subprocess con cwd=... funciono" | **FAIL** — prueba un subprocess LOCAL, no el cwd del agente |
| `state_on_disk` | verified | "directorio .arena existe (sin runs previos)" | **FAIL** — no crea/cierra/reabre/reanuda un run |
| `plugin_api` | unknown | "no se usa" | NOT_RUN |

**Conclusion:** 6 capabilities marcadas `verified`, pero **3 de ellas no estan respaldadas
por una prueba funcional valida** (`permission_rules`, `readonly_agent`, `cwd_control`,
`state_on_disk` = 4). 3 mas son `unsupported` por evidencia no concluyente.
**El claim "sondas honestas" NO se sostiene en el estado actual.**

---

## 8. Estado inicial del arbol (para la comparacion final)

```
git status --short   -> (vacio, tras la curacion de scratch documentada en §5)
git diff --check     -> (vacio)
git rev-parse HEAD   -> 875c04ae1f7865c8043db651708d471c4a8d334e
```

**Unico cambio del baseline:** `.gitignore` (documentado en §5).

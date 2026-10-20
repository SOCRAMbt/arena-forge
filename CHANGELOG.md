# CHANGELOG

## 0.3.0 — 2026-10-19 — Auditoría forense, cierre técnico y recertificación

### Contrato de referencia versionado

- `docs/contract/ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md` (SHA-256
  `96027434…D273`): el contrato estaba en `Downloads/` y **no** en el repo, lo que
  había hecho imposible certificar AF-AC/§16. Ahora la auditoría es
  **reproducible contra el texto literal**.
- Matriz de aceptación **generada por código** (`reports/audit/compute_acceptance.py`
  + `acceptance-data.json`) con un test que falla si el `.md` se desincroniza.
- `reports/audit/acceptance-matrix.md` incluye la matriz de trazabilidad §21
  (AF-PR-001..010).

### Cerrado en esta iteración

- **AF-AC-003 (skill)**: era `inconclusive` porque el servidor de fondo de OpenCode
  puede estar enraizado en otro árbol. `tools/probe_skill.py` arranca un servidor
  **enraizado en el repo** (leyendo la contraseña aleatoria que anuncia en su
  stdout) y verifica ID y ruta exactos: `arena-forge` en
  `.opencode/skills/arena-forge/SKILL.md`. `skills_native` pasa a `verified`.
- **AF-AC-005 (Answer Arena E2E)**: `forge/stub_agent.py` es un doble de costura
  determinista y sin coste (§13.4 lo exige) que juega el papel del subagente en el
  camino real de producción. `tests/test_e2e_answer_arena.py` (9 tests) cubre
  4 candidatos, ataques, defensas, jueces, collect, advance, decisión e informe,
  con **controles negativos**: `check` falla sin salidas, `advance` falla sin
  veredictos, el ganador se **re-deriva** de forma independiente con
  `bracket.decide`, reanudar no duplica rondas ni reescribe salidas y el stub es
  determinista. La calidad es **heterogénea** para que el juez discrimine de
  verdad. Todo artefacto va etiquetado (`stub_manifest.json`, banner `STUB`).
- **§16.5 (interrupción a mitad de fase)**: test específico con reanudación sin
  duplicación.
- **AF-AC-012 (lint/typecheck/build)**: `tools/lint.py` (lint propio sin
  dependencias, con autotests y control negativo) y build con `compileall`;
  `mypy`/`ruff`/`pyright` se declaran **NOT_RUN** con su causa exacta.
- **CI verde**: GitHub Actions run 3 (`93f7f2d`), `conclusion: success` en las 4
  legs (Windows/Linux × Python 3.11/3.12) desde checkout limpio.
- **Evidencia portable**: `atomic_write_json`/`append_line` escriben con `newline=""`
  (LF en cualquier plataforma) y `sha256_normalized()` permite que el manifiesto
  `SHA256SUMS.txt` sea válido en cualquier checkout.
- **ADR-006** (aislamiento): qué se garantiza y qué NO, con el modo
  `TRUSTED_CODE_ONLY` declarado.

### Veredicto

**NO-GO**: 16 PASS, 2 PARTIAL, 0 FAIL/NOT_RUN/BLOCKED (ponderado 94.4 %). NO-GO por
dos razones verificables: falta la **reproducción por un tercero independiente**
(§23 no permite que el coordinador certifique su propio éxito) y el **aislamiento
es de nivel de ruta, no de sistema operativo**. La eficacia adaptativa de E sigue
siendo una hipótesis pendiente (§23).

## 0.3.0 — Auditoría forense y cierre técnico

Estado global de esta revisión: **NO-GO** (2 P0 abiertos, 2 criterios NOT_RUN).
Detalle: `reports/audit/final-audit.md`, `reports/audit/findings.md`.

### Corregido (P0)

- **Parche binario canónico.** Se elimina el formato inventado (cabecera `GIT binary
  patch` + base64 estándar, que `git apply` rechazaba) y el parser que descartaba los
  hunks de texto en un diff mixto. Ahora el artefacto es un **parche Git real**
  (`git diff --binary`), aplicado con `git apply --check` + `git apply`.
- **Gate no falsificable.** El veredicto se basaba solo en el código de salida: un
  candidato con `os._exit(0)` en el import quedaba como PASS. Ahora el gate exige el
  **informe JUnit** de pytest.
- **Contención de rutas.** Se validan todas las cabeceras del parche (`diff --git`,
  `---`, `+++`, `rename to`, `copy to`); nada se escribe fuera del scratch.
- **Symlinks fail-closed.** Los symlinks inseguros se omitían en silencio; ahora
  hacen fallar el manifiesto y el gate (`BLOCKED/unsafe_candidate`).
- **Diff no vacío.** El stat cache de git (mtime con granularidad de 1 s) podía hacer
  que el parche saliera vacío.
- **Baseline/suite/manifiesto/artefacto revalidados** en `report`, `verify` y `apply`
  (`forge/integrity.py`). `suite_sha` y `diff_sha` se **recalculan**; ya no se comparan
  solo valores almacenados.
- **Winner correcto.** `apply` aplicaba `eligible[0]`, no el candidato juzgado. Ahora
  `report` persiste `decision_id`+`winner_id` y `apply` usa ese ganador.
- **Presupuesto de E reservado** bajo lock de sistema operativo antes de crear el job.
- **Aprobación humana aplicada**: sin un registro ligado a la decisión, no se ejecuta.
- **Skill con frontmatter V2** (antes OpenCode la omitía en silencio) y **orden de
  permisos corregido** (los `allow` estaban muertos por ir antes de los `deny`).

### Corregido (P1)

- 13 definiciones duplicadas en `forge/adapter.py`, `cmd_decide` duplicado en
  `arena_forge.py` y `atomic_write_json` duplicado en `forge/util.py`: eliminados.
- Sondas OpenCode honestas: un error de sintaxis CLI ya no se registra como
  `unsupported`; el texto de ayuda no prueba una denegación; `state_on_disk` hace una
  ida y vuelta real; `agent_profiles` usa la ruta correcta; `permission_rules` ya no se
  declara `verified` por documentación.
- `cmd_verify` exige una **matriz de capacidades obligatorias por modo**.
- `decisions.jsonl` es append-only; las líneas corruptas se preservan.
- El ledger usa lock de SO y no se rompe por una línea corrupta.
- Entorno del gate: shim de pytest aislado, sin plugins automáticos, sin
  `HOME`/`USERPROFILE` del operador, salida acotada en RAM y en disco, timeout que
  mata el árbol de procesos.
- `redact()` cubre 9 formatos de secreto.
- Tests **portables** (sin rutas absolutas del host), que **no ensucian el repo**, y que
  no fijan manifiestos dependientes de CRLF.
- `pytest.ini` (la suite protegida de fixtures ya no se recolecta) y `.gitattributes`
  (`eol=lf`, para que los hashes no dependan del checkout).

### Añadido

- `forge/integrity.py` — verificaciones de contenido ligadas al artefacto.
- `reports/audit/` — baseline, hallazgos, matriz de aceptación, resultados de test,
  evidencia E2E e informe final.
- **`reports/audit/artifacts/`** — evidencia **versionada** y verificable por un
  tercero: `gates.json`, `decision.json`, `isolation.json`, `ledger.jsonl`, el
  parche round-trip y `SHA256SUMS.txt`. La revisión 5 señaló que el único parche
  verificable estaba excluido de git; cerrado. `AuditArtifactsTest` comprueba en la
  CI que `sha256(parche) == diff_sha del gate == diff_sha de decision.json` y que
  el parche aplica sobre un baseline limpio.
- **`fixtures/patch-demo/binary/sample.bin`** — artefacto binario persistido
  (contiene NUL y una cola no-UTF-8) para que el round-trip binario sea
  reproducible desde un checkout limpio.
- `.github/workflows/ci.yml` — CI Windows/Linux × Python 3.11/3.12 con smoke E2E y
  comprobación de árbol limpio. **Configurada, no ejecutada todavía.**

### Sin cambio (declarado, no fabricado)

- **AF-AC-016** (eficacia adaptativa de E): **NOT_RUN**.
- **Aislamiento de OS**: **BLOCKED**. Modo `TRUSTED_CODE_ONLY`.

### Correcciones de documentación

- README, VERIFICATION_SUMMARY, THREAT_MODEL y RECONNAISSANCE regenerados desde la
  evidencia real: el E2E de Patch se etiqueta **asistido** (no autónomo), el estado de
  las sondas se corrige y se elimina la afirmación «COMPLETE».

## 0.2.0 — 2026-10-16

- Patch Arena con ciclo adversarial completo: ataques solo-lectura al rival,
  defensas con concede/rebut y revisión versionada (v1 preservada), re-gates
  y juez ciego sobre v2 (90–84 con evidencia por línea).
- README profesional con evidencia real, `demo/` con los 3 informes.
- `resolve_patch_winner()` compartido por `report` y `apply`.

## 0.1.0 — 2026-10-16

- Motor `arena_forge.py`: modos answer/patch, 15 comandos
  (plan/init/next/prompts/check/pairings/collect/record/advance/status/winner/
  card + gates/resume/cancel/report/benchmark/apply).
- `bracket.py` vendored con patch OpenCode mínimo (atribución en
  `THIRD_PARTY_NOTICES.md`).
- Gates objetivos en scratch con SHA de suite; `NO_SHIP` real; juez ciego X/Y.
- Informe Markdown + HTML estático con escape verificado.
- Skill `.opencode/skills/arena-forge` + 4 agentes mínimos.
- Suite: 9 tests (scheduler, CLI, cancel, quarantine, gates, injection inerte,
  escape, NO_SHIP, gates-vetan-juez). E2E Answer 4→1 y Patch 2 candidatos reales.
- Bugs encontrados por tests/E2E y corregidos: doble escape en informe,
  `gates` listaba el run, `SKILL.md` ausente en vendor, `apply` sin ganador patch.

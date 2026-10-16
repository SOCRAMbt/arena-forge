# THREAT_MODEL — Arena Forge

## Activos

Estado del torneo (`arena.json`), gobierno (`forge.json`), suite protegida,
candidatos, informes, credenciales del usuario (NO activos: jamás se leen).

## Límites de confianza

Orquestador (control total del scheduler) > jueces/implementadores (solo
`.arena/`) > datos externos (issues, README, logs, resultados MCP: inertes).

## Amenazas → mitigaciones (verificadas donde se indica)

| Amenaza | Mitigación | Estado |
|---|---|---|
| Prompt injection en README/issues/logs | Datos tratados como texto; harness ignora órdenes; test `injection-test` (README malicioso → gates PASS sin efectos) | verificado |
| Candidato edita suite/rúbrica/tests | Suite fuera de `candidates/`; SHA antes/después; `candidates/` sin `tests_protected*` (→BLOCKED); rúbrica copiada al run | verificado |
| Lectura de `.env`/claves/SSH | Briefs prohíben secretos; implementer solo escribe `.arena/`; harness nunca lee secretos | proceso |
| Path traversal / worktree equivocado | `inside_run()`; scratch temporal; candidatos en dirs propios; árbol principal intacto (E2E) | verificado |
| Shell no confiable / deps globales | Sin instalaciones; pytest/timeout 120s; `judge` solo shell en `scratch/` por brief | proceso |
| Contaminación entre candidatos | Dirs separados + overlay por copia en scratch; logs/rutas en informe | verificado |
| Juez sesgado / scores manipulados | Ciego X/Y + `patch_map`; `decide()` recalcula; gates vetan | verificado |
| JSON malicioso / archivos gigantes | Límite 1MB + `.oversize`/`.unreadable`; `decide()` valida schema y rangos | verificado |
| Tormenta de subagentes / coste | `plan` previo obligatorio; `--wave`; timeouts; reintento 1 + `NO OUTPUT`; `extreme` exige confirmación | proceso |
| HTML del informe ejecuta JS | Escape único en frontera (`esc()` una vez); test con `<script>` | verificado |
| Doble controladora | `lock.json` con stale 300s; `collect/advance` bajo lock | implementado |
| Red no autorizada | Sin llamadas de red en el runtime (subprocess solo `python`/`pytest`/`git` local) | diseño |

## Riesgos residuales

- `judge` conserva permiso `shell` (necesita ejecutar checks): un juez
  comprometido podría correr comandos como el usuario. Mitigación parcial
  (brief + scope); endurecer con allowlist de comandos cuando OpenCode lo soporte.
- Modelo no determinista: la seed no reproduce textos; el informe lo declara.
- Coste monetario no medible por API: se limita por llamadas/olas/tiempo.
- `general` ve todo el workspace de lectura: no poner secretos en el árbol.

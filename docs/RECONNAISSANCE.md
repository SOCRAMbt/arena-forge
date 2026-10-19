# RECONNAISSANCE â€” Arena Forge, fase cero

Fecha: 2026-10-16. MÃ©todo: solo lectura (`pwd`, `git`, `opencode --help/models/service`,
lectura de config, `git ls-remote`, hashes SHA-256, docs V2). Sin mutaciones salvo
scaffold nuevo en `arena-forge/` (directorio nuevo, sin repo previo que pisar).

> **ActualizaciÃ³n 2026-10-19 (auditorÃ­a forense).** La versiÃ³n real del binario en esta
> mÃ¡quina es **OpenCode v2.0.32** (no v2.0.29). Los subcomandos V2 reales son
> `upgrade, uninstall, acp, api, debug, auth, mcp, plugin, models, stats, mini, run,
> session, service`. **NO existe** un subcomando `skill` ni un flag `--prompt` en
> `opencode run` (el mensaje es **posicional**); `opencode agent` tampoco existe
> (lo equivalente es `opencode debug agents`). Los identificadores de modelo
> disponibles incluyen `opencode/nemotron-3-ultra-free` y
> `openrouter/nvidia/nemotron-3-ultra-550b-a55b`.
> Estado del HEAD en esa fecha: `875c04ae1f7865c8043db651708d471c4a8d334e`.
> Ver `reports/audit/baseline.md`.

## Hechos verificados

- CWD `<HOME>` **no es un repo git** (`fatal: not a git repository`).
  DecisiÃ³n: construir Arena Forge como **subproyecto aislado** `arena-forge/`, sin tocar
  nada existente. Sin baseline git que congelar; el scope Patch Arena usarÃ¡ fixtures
  propios con repo git dedicado.
- **OpenCode v2.0.29** (`opencode --version`). Servicio de fondo activo
  (`http://127.0.0.1:49374`). Subcomandos V2 reales: `run`, `session`, `service`,
  `api`, `mcp`, `plugin`, `models`, `auth`, `reload`, `pair`, `serve`, `acp`, `debug`.
- Modelos listados por el binario (incluye familia `anthropic/claude-*`).
- Agentes Markdown globales: `code-architect`, `code-explorer`, `code-reviewer`.
  Builtins V2 segÃºn docs: `build` (primary), `plan` (primary),
  `general` (subagent, amplio acceso, **no puede lanzar subagentes**),
  `explore` (subagent, **solo lectura**).
- Tool `subagent`: campos `agent`, `description`, `prompt` (+`background`, `sessionID`);
  profundidad de anidado por defecto **uno**. Sin `Agent`/`Task`/`subagent_type`/`run_in_background`.
- Skills V2: descubrimiento en `~/.config/opencode/skills` (+ compat `.claude/skills`,
  `.agents/skills`), proyecto `.opencode/skills`; ID deriva del path; `description`
  obligatoria para discovery; `skill` tool por ID exacto.
- Skill `arena` instalada global en `~/.config/opencode/skills/arena/` y **visible con
  su ID en el catÃ¡logo del entorno**. Comando global `/arena` creado en
  `~/.config/opencode/commands/arena.md` (`subagent: false`, pasa `$ARGUMENTS`).
- Python **3.12.4** como `python`; `python3` **no existe** en este Windows
  (verificado con `where`). Node v22.23.2.
- Upstream `https://github.com/Jakeschincariol/arena-skill`:
  commit `df07b8e518e10cdecd8cd7712d9958b6f396250e` (HEAD=main, verificado por
  `git ls-remote` dos veces), licencia **MIT Â© 2026 Jake Schincariol** (verificado,
  3 primeras lÃ­neas del LICENSE), `tests/test_bracket.py` presente.
  SHA-256 originales en `THIRD_PARTY_NOTICES.md`. `strategies.json` (15Ã—12Ã—12=2160
  cartas) y `rubric.md` reutilizados **sin modificar** (hash idÃ©ntico local/upstream).
- Config global `opencode.jsonc`: solo plugin `superpowers@git+...`; sin MCPs, sin
  reglas `permissions` personalizadas, sin `skills` explÃ­citos.
- Permisos V2: reglas `{action, resource, effect}` con `allow/ask/deny`, Ãºltima
  coincidencia gana; acciones reales: `shell`, `edit` (cubre write/patch),
  `subagent`, `read`, `glob`, `grep`, `webfetch`, `websearch`, `skill`.

## Inferencias (no bloquean, se validan en E2E)

- `/arena` recarga automÃ¡ticamente al guardar el `.md` (docs: reload automÃ¡tico).
- `python -m pytest` probablemente disponible (hay `.pytest_cache` en el home);
  se confirma al ejecutar; fallback `python -m unittest`.

## Pendiente (con camino de cierre)

- Concurrencia mÃ¡xima real de subagentes del runtime (docs no la fijan; se usa
  `--wave 10` por defecto y se observa en E2E).
- Supervivencia de sesiones `background` al cerrar el terminal (se evita: modo
  foreground reanudable como camino principal).
- ExposiciÃ³n de coste/tokens por API (probablemente no disponible â†’ se mide en
  llamadas/olas/tiempo y se declara).
- Carga efectiva de `/arena` y de la futura skill `arena-forge` en TUI (se verifica
  con `opencode reload` + invocaciÃ³n real o se declara).

## Limitaciones aceptadas

- Sin repo principal no hay regresiones que proteger fuera de fixtures.
- Seed fija scheduler/tarjetas/bracket, **no** las salidas del modelo (se documenta).

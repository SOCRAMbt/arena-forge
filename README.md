# Arena Forge

Competición de ingeniería local para OpenCode V2: torneos Answer (texto) y
Patch (código real con gates que mandan sobre el score). Metodología derivada
de `Jakeschincariol/arena-skill` (MIT; ver `THIRD_PARTY_NOTICES.md`).

## Instalación (verificada en Windows, Python 3.12)

```bat
cd arena-forge
python -m pytest tests/ -q     :: 9 passed
python arena_forge.py plan --agents 4
```

Sin dependencias: solo stdlib. En Unix usa `python3` si `python` falta.

## Uso mínimo

```bat
python arena_forge.py init --mode answer --agents 4 --seed 7 --task "..."
python arena_forge.py next                 :: manda la fase
python arena_forge.py prompts spawn        :: briefs por ola
:: lanzar una ola: un tool subagent por job (agent general), en foreground
python arena_forge.py collect
python arena_forge.py advance
python arena_forge.py winner
python arena_forge.py report               :: MD + HTML en reports/, decide WINNER/NO_SHIP
```

Patch añade `--suite`, `gates` (pytest en scratch limpio), juez ciego y
`apply --approve` (solo escribe `reports/*.patch`, jamás toca el proyecto).

Skill OpenCode del repo: `.opencode/skills/arena-forge` (`@arena-forge`).
Comando global: `/arena`.

## Evidencia incluida

- `reports/run-20261016-134741-s7.*`: Answer E2E real (4 agentes, 23 llamadas,
  campeón a002).
- `reports/run-20261016-135742-s11.*`: Patch E2E (cand-a/cand-b PASS, juez
  ciego elige cand-a) + `.patch` aplicable.
- `reports/run-20261016-140147-s21.*`: NO_SHIP (buggy FAIL, sin campeón forzado).
- Docs: `docs/RECONNAISSANCE.md`, `docs/ARCHITECTURE.md`,
  `docs/THREAT_MODEL.md`, `docs/ADR-00*.md`.

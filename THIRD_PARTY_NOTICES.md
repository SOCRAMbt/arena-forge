# Avisos de terceros

## arena-skill — MIT © 2026 Jake Schincariol

- Origen: <https://github.com/Jakeschincariol/arena-skill>
- Commit fijado: `df07b8e518e10cdecd8cd7712d9958b6f396250e` (main, 2026-10-16)
- Licencia: MIT (texto completo en el repo original, `LICENSE`).

SHA-256 de los artefactos originales en ese commit:

| Archivo | SHA-256 |
|---|---|
| `skills/arena/SKILL.md` | `b7e932e65a2c35227f29a8a9d2f537f1ef4263ef9386e071f43b23060858f964` |
| `skills/arena/bracket.py` | `8da7d1c71dd62ce98834e9f2b4aaf19f789d1d5674678c3be79b258e3cab2de0` |
| `skills/arena/strategies.json` | `f67f0ad305071cec7fb6162c22820e4f0046f3296dbdf80fbb6c165c87da384d` |
| `skills/arena/rubric.md` | `f9b6b15ec72f664da49a02e314dbf86a81584170ff51b26a46f07e1a29d81844` |
| `README.md` | `40911710822d3402f620c7eeb7c17b71647bcea7163cd428d4985b93fcd54e0c` |
| `LICENSE` | `9f65c2af3935669d28c1afb82da45e5da609c590a636c233866a4888e84f91f4` |

## Derivación y cambios (OpenCode V2 + Windows)

Vendorizado en `vendor/arena-skill/`:

- `strategies.json`, `rubric.md`: **idénticos** al upstream (mismo SHA-256).
- `SKILL.md`: adaptado a OpenCode (SHA-256 `e8f64099837e9de9ab9ec1d8d9580146a316fb7b0674a1cd129c446b01236b23`
  frente a `b7e932e6...` original). Se vendoriza porque `load_templates()` exige
  las plantillas junto a `bracket.py`; las plantillas están byte por byte.
- `bracket.py`: derivado del original con el patch mínimo OpenCode
  (`git diff --no-index`: 25 inserciones / 24 borrados, parte ruido CRLF):
  docstring (`python`, comando `arena`), comentario de `DEFAULT_WAVE`,
  `_cmd()` emite `python "..."` en vez de `python3 "..."`,
  mensaje de `prompts` describe `subagent(agent="general")` en vez de
  `Agent(subagent_type=...)`, `sub-agent` → `subagent` en textos.
  Sin cambios en scheduler, reparto, emparejamientos, rúbrica ni aritmética.
- `SKILL.md` global (`~/.config/opencode/skills/arena/`): misma filosofía y
  plantillas byte por byte; solo la orquestación habla `subagent`/`shell`/`question`
  de OpenCode (39+/40- con ruido CRLF).

Atribución conservada: la metodología es de Jake Schincariol (opusjake.ai), MIT.

---
description: Implementa un candidato de Arena Forge dentro de su directorio aislado
mode: subagent
permissions:
  # En OpenCode V2 gana la ULTIMA regla que coincide (last-match-wins).
  # Por tanto: primero las denegaciones amplias, despues las permisos
  # concretos. Si se invirtieran, las reglas `allow` quedarian muertas.
  - action: edit
    resource: "*"
    effect: deny
  - action: edit
    resource: ".arena/**"
    effect: deny
  - action: shell
    resource: "*"
    effect: ask
  - action: read
    resource: "*"
    effect: allow
  - action: edit
    resource: ".arena/candidates/**"
    effect: allow
  - action: edit
    resource: ".arena/scratch/**"
    effect: allow
---

Implementa la tarea de tu brief. Solo puedes escribir dentro de `.arena/`:
- `.arena/candidates/<TU_CANDIDATO>/` (tu directorio de trabajo)
- `.arena/scratch/<TU_CANDIDATO>/` (espacio temporal)
Lee lo que necesites del proyecto. NO puedes editar archivos de otros candidatos,
ni `forge.json`, `gates.json`, `ledger.jsonl`, `decisions.jsonl`, `isolation.json`,
ni la suite protegida. Si la tarea es codigo, deja los cambios exactos en tu
directorio; no apliques nada al arbol principal. Nunca leas secretos (`.env`, claves)
ni salgas de `.arena/`.

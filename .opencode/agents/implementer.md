---
description: Implementa un candidato de Arena Forge dentro de su directorio aislado
mode: subagent
permissions:
  - action: read
    resource: "*"
    effect: allow
  - action: edit
    resource: ".arena/**"
    effect: allow
  - action: edit
    resource: "*"
    effect: deny
  - action: shell
    resource: "*"
    effect: ask
---

Implementa la tarea de tu brief. Solo puedes escribir dentro de `.arena/`
(tu directorio de candidato y `scratch/`). Lee lo que necesites del proyecto.
Si la tarea es codigo, deja los cambios exactos (ficheros completos o diff
unificado) en tu fichero de solucion; no apliques nada al arbol principal.
Nunca leas secretos (`.env`, claves) ni salgas de `.arena/`.

# ADR-006 — Aislamiento de candidatos: qué se garantiza y qué NO

**Estado:** Aceptado · **Fecha:** 2026-10-19 · **Contexto:** §11 y §13.3 del contrato

## Contexto

Arena Forge evalúa código producido por agentes (no confiable por definición).
El contrato (§11.2) exige separar los artefactos del candidato del evaluador y
proteger la suite; §11.3 exige resolver rutas canónicamente y rechazar escapes y
symlinks peligrosos; §13.3 ofrece una "alternativa segura" (diffs → validación →
aplicación con ejecutor controlado → ejecutar pruebas → guardar logs y hashes)
cuando no hay aislamiento nativo confiable.

La pregunta que este ADR responde: **¿qué garantiza Arena Forge hoy sobre el
código que ejecuta, y qué NO?**

## Decisión

Adoptamos la **alternativa segura de §13.3** como camino principal y declaramos
**explícitamente el modo limitado**. Concretamente:

1. **El código del candidato NUNCA se ejecuta en el árbol del proyecto.** El gate
   lo copia a un scratch temporal y ejecuta ahí (`forge/gates.py`).
2. **El candidato no puede escribir en el harness.** El workspace del candidato y
   el scratch del gate son directorios distintos; el harness (suite protegida,
   gates.json, ledger, decisiones) vive fuera del alcance de escritura del
   candidato. `forge/isolation.py::ensure_workspaces` valida el identificador
   ANTES de crear nada.
3. **El entorno del gate es una allowlist, no la herencia.** `HOME`,
   `USERPROFILE`, `TEMP` y `TMP` apuntan al scratch; `PYTHONNOUSERSITE=1`,
   `PYTHONSAFEPATH=1` y `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` evitan cargar el
   user site-packages y los plugins de pytest del usuario. El pytest se sirve
   desde un *shim* que contiene solo pytest y sus dependencias declaradas.
4. **Una única política de exclusión** (`forge/isolation.py::EXCLUDED_DIRS` /
   `EXCLUDED_SUFFIXES`) gobierna el manifiesto, el parche y el scratch del gate.
   Antes el scratch usaba otra: los `.pyc` llegaban a ejecutarse sin estar en
   ningún hash ni en el parche exportado.
5. **Symlinks: fail-closed.** Un symlink externo, roto o de directorio hace
   FALLAR el manifiesto (`ForgeError`) en vez de omitirse en silencio. El gate
   marca `BLOCKED / unsafe_candidate`.
6. **Los parches se validan y aplican con un ejecutor controlado** sobre una
   copia temporal, con `git apply --check` previo y comparación del árbol
   resultante contra el del candidato.
7. **El modo se declara en todas partes.** `SECURITY_MODE =
   "TRUSTED_CODE_ONLY"` aparece en `forge/isolation.py`, viaja en cada
   `GateResult`, se muestra en `verify` y en la salida de `apply`, y se
   documenta en `docs/THREAT_MODEL.md` y en el README.

## Lo que NO garantizamos (riesgo residual aceptado y declarado)

- **No hay frontera de sistema operativo.** Sin Job Object, AppContainer, token
  de baja integridad, usuario de privilegios mínimos, ACLs de workspace ni
  filtrado de red. El código del candidato se ejecuta **con los privilegios del
  operador**.
- **La suite protegida no está oculta.** El gate la copia al scratch, así que el
  candidato puede leerla (aunque no modificarla: su hash se comprueba antes y
  después de la evaluación). El contrato lo pide explícitamente cuando se
  afirma que los tests ocultos no están disponibles.
- **La red no está bloqueada.** El proceso del gate puede salir a la red.
- **Un candidato dentro del proceso de pytest puede, en principio, subvertir el
  oráculo del gate** (escribir un informe JUnit falso, por ejemplo). El control
  actual exige informe JUnit **y** un marcador de finalización escrito por un
  plugin del harness en un hook `atexit` (que `os._exit` no ejecuta) **y** un
  recuento mínimo de tests, pero no es una garantía frente a un candidato
  activamente hostil dentro del mismo proceso.

Por eso el modo se declara **limitado** y no se anuncia como operativo, tal y
como permite AF-AC-006 ("si no se demuestra aislamiento, modo declarado
bloqueado y no anunciado como operativo").

## Consecuencias

- El uso previsto es **código en el que se confía** (equipos internos, pruebas
  propias). Para código no confiable, Arena Forge **no debe** ejecutar las
  gates: usar el modo de inspección y `apply` verificado, que no ejecuta el
  parche del candidato.
- Cerrar el riesgo residual exige un sandbox de sistema operativo. En Windows
  un Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, límites de memoria y de
  procesos) **no requiere elevación** y acota memoria/PIDs/árbol de procesos;
  para bloquear red y escritura fuera del workspace hacen falta un usuario de
  privilegios mínimos con ACLs o un contenedor, que sí requieren privilegios
  administrativos.
- Mientras tanto, la mitigación organizativa es la regla: **no ejecutar Arena
  Forge con candidatos no confiables**.

## Alternativas descartadas

- **"Un directorio temporal con variables filtradas es un sandbox."** Descartado:
  es higiene, no contención. D Calling it a sandbox sería exactamente el tipo de
  afirmación sin evidencia que este proyecto existe para evitar.
- **"Gitignore de los secretos."** Descartado: no es una frontera; el
  candidato lee el disco con los privilegios del proceso.

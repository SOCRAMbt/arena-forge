# ARENA FORGE
## Especificación técnica integral, arquitectura, seguridad y aceptación

**Versión:** 1.0 · **Fecha:** 16 de octubre de 2026  
**Estado:** especificación propuesta; no constituye evidencia de implementación.  
**Objetivo:** definir el producto, los contratos técnicos, el comportamiento esperado, los límites y la evidencia necesaria para comprobar si Arena Forge está terminado.

### Convenciones normativas

**DEBE / NO DEBE** indican requisitos obligatorios. **DEBERÍA / NO DEBERÍA** indican recomendaciones fuertes. **PUEDE** indica una opción válida. Las afirmaciones dependientes del entorno deben verificarse contra el repositorio y el binario real de OpenCode CLI V2. No se debe inventar compatibilidad.

## 0. Cómo usar esta especificación

Este documento convierte la misión maestra de Arena Forge en un contrato verificable de producto y arquitectura, incorporando el agente E como orquestador adaptativo. Distingue entre requisitos heredados de la misión anterior y decisiones de diseño que aquí se formalizan. La especificación no afirma que el código exista.

Estados globales válidos:
- `COMPLETE`: todos los gates obligatorios aplicables pasan con evidencia.
- `PARTIAL`: hay funcionalidad operativa, pero quedan requisitos pendientes.
- `BLOCKED`: un requisito esencial no puede verificarse por una dependencia o capacidad externa.
- `FAILED`: incumplimiento esencial o violación crítica.
- `NOT_ASSESSED`: todavía no evaluado.

Un README, una interfaz visual, código que compila o la afirmación de un agente no prueban por sí solos que el sistema esté terminado. `NOT_RUN`, `BLOCKED`, `INCONCLUSIVE` y `PARTIAL` nunca deben convertirse en `PASS`.

# 1. Visión, objetivos y límites

Arena Forge es un runtime local de competición multiagente para ingeniería de software. Organiza candidatos con estrategias distintas, ejecuta evaluaciones comparables, conserva evidencia y produce una decisión explicable: una solución elegible (`WINNER`) o `NO_SHIP`.

No es un modelo nuevo ni una garantía de que más agentes produzcan mejores resultados. Su valor debe medirse frente a un agente único bien instruido y frente a una orquestación fija. Tampoco es, en su versión base, un sistema de despliegue autónomo, un servicio remoto multiusuario ni un predictor financiero.

## 1.1 Objetivos

1. Adaptar la metodología de `Jakeschincariol/arena-skill` a OpenCode V2, tras verificar los contratos reales.
2. Preservar una competición de respuestas.
3. Añadir competiciones de parches reales con aislamiento demostrable.
4. Medir si la competición mejora resultados mediante benchmarks repetibles.
5. Incorporar E como controlador del experimento.
6. Hacer que los gates objetivos prevalezcan sobre el juicio narrativo.
7. Permitir `NO_SHIP` cuando ninguna solución sea aceptable.
8. Persistir estado, decisiones y artefactos para reanudar ejecuciones.
9. Mantener trazabilidad de puntuaciones, costes, fallos y decisiones.
10. Operar con mínimo privilegio y aprobación humana para efectos externos.
11. Permitir que otra persona reproduzca una demostración desde un checkout limpio.

## 1.2 Principios no negociables

- **Evidencia antes que retórica:** un juez LLM no anula un test fallido.
- **Aislamiento real:** dos candidatos nunca escriben en el mismo worktree.
- **Sin campeón forzado:** si nadie pasa los gates, el resultado es `NO_SHIP`.
- **Reanudación real:** reiniciar no borra historial ni duplica trabajos.
- **Reproducibilidad honesta:** seed y hashes fijan lo controlable, no las respuestas del modelo.
- **Mínimo privilegio:** no leer secretos, ejecutar acciones ajenas a la tarea ni conceder permisos amplios automáticamente.
- **Preservar trabajo preexistente:** no usar `git reset --hard`, limpieza destructiva ni reescritura de historial.
- **Compatibilidad comprobada:** no inventar APIs ni herramientas de OpenCode V2.
- **Coste acotado:** mostrar presupuesto y concurrencia antes de ejecutar.
- **Control humano:** sin merge, push, publicación, release o despliegue sin aprobación explícita.
- **Evaluación independiente:** candidatos no editan su suite protegida ni certifican su propia elegibilidad.
- **Honestidad del informe:** mostrar fallos, resultados negativos y herramientas no ejecutadas.
- **Autoridad separada:** E no puede anular políticas deterministas.
- **Auditoría:** decisiones relevantes deben reconstruirse desde eventos y artefactos.

# 2. Los tres modos de Arena

## 2.1 Answer Arena

Preserva el torneo de propuestas del proyecto original. N candidatos reciben exactamente el mismo enunciado y una tarjeta de estrategia diferente. Según el flujo confirmado del upstream, las respuestas pueden pasar por crítica, defensa, revisión y evaluación.

Requisitos:
- Congelar tarea y rúbrica antes de crear candidatos.
- Las tarjetas varían el enfoque, no los requisitos ni la información esencial.
- Generar bracket y asignaciones con un scheduler verificable.
- Guardar por separado propuestas, críticas, defensas, revisiones, jueces y scores.
- Validar outputs y rangos antes de agregarlos.
- Calcular el score agregado en código determinista, nunca delegar la aritmética final al LLM.
- Mostrar byes, empates, outputs ausentes y desacuerdos.
- Agotar reintentos y registrar fallo explícito cuando falten outputs.
- No cambiar silenciosamente la rúbrica original; toda modificación se versiona y justifica.

Antes de reutilizar lógica upstream se debe inspeccionar el código, licencia y tests reales. Una descripción del repositorio no sustituye esa inspección.

## 2.2 Patch Arena

Lleva la competición a cambios reales de código:

1. Definir tarea, criterios de aceptación y baseline Git.
2. Crear o validar la suite de evaluación antes de producir candidatos.
3. Calcular y registrar el hash de la suite.
4. Dar a cada candidato el mismo enunciado, baseline y restricciones, más una estrategia diferente.
5. Crear un worktree, copia temporal o proceso aislado por candidato.
6. Verificar rutas y ausencia de directorios de escritura compartidos.
7. Capturar cada diff como artefacto versionado.
8. Ejecutar el mismo harness sobre una copia limpia de cada candidato.
9. Guardar comandos, versiones, logs, resultados, tiempos y métricas disponibles.
10. Ejecutar críticas adversariales de solo lectura.
11. Guardar cada defensa/revisión como nueva versión, sin sobrescribir el historial.
12. Comparar a ciegas cuando sea posible.
13. Aplicar gates objetivos antes de evaluar calidad subjetiva.
14. Emitir `WINNER` o `NO_SHIP` con razones y referencias.
15. Preparar un parche o rama local para revisión humana.

Los tests del candidato pueden complementar, pero nunca sustituir la suite protegida. El candidato no puede modificar el test que determina su elegibilidad sin que la manipulación se detecte. Si OpenCode V2 no permite dirigir de forma fiable sesiones a worktrees específicos, se usa un flujo de diffs validados aplicados por un ejecutor controlado a copias temporales. Si tampoco se puede demostrar esa alternativa, Patch Arena queda bloqueado o limitado a diffs no ejecutados.

## 2.3 Benchmark Arena

Mide si Arena Forge mejora frente a alternativas:
- tareas pequeñas, medianas y adversariales;
- baseline de agente único bien instruido;
- configuración fija multiagente;
- E adaptativo;
- pruebas funcionales, regresiones e invariantes cuando aporten valor;
- rendimiento para tareas donde importa;
- calidad y seguridad del parche;
- llamadas, fallos, trabajo repetido, tiempo y coste observable;
- repeticiones con seeds;
- resultados negativos y casos donde vence el baseline;
- limitaciones estadísticas explícitas.

No optimizar solo la puntuación del juez. Métricas centrales: tasa de aceptación, defectos escapados, regresiones, reproducibilidad, coste, tiempo y esfuerzo de revisión humana.

# 3. Arquitectura de componentes

Las responsabilidades siguientes son obligatorias aunque puedan implementarse como paquetes o procesos distintos:

1. **CLI:** comandos, validación de argumentos y presentación de estado.
2. **Runtime Adapter OpenCode:** encapsula skills, agentes, sesiones, permisos y ejecución realmente disponibles.
3. **Agente E:** planificación y coordinación adaptativa.
4. **Scheduler / Tournament Engine:** fases, jobs, emparejamientos, olas y transiciones.
5. **Prompt & Strategy Builder:** briefs completos, estables, versionados.
6. **Candidate Runner:** ejecución de cada trabajo.
7. **Workspace / Isolation Manager:** worktrees, rutas y permisos.
8. **Artifact Store:** outputs, diffs, logs, informes y hashes.
9. **State Store:** estados, locks, recuperación y reanudación.
10. **Evaluation Harness:** pruebas sobre candidatos.
11. **Gate Engine:** reglas deterministas de elegibilidad.
12. **Adversarial Review Engine:** crítica de solo lectura.
13. **Judge Adapter:** validación de evaluaciones LLM.
14. **Score Calculator:** agregación aritmética determinista.
15. **Benchmark Runner:** comparación de métodos.
16. **Report Generator:** Markdown y HTML estático.
17. **Policy / Budget Manager:** límites, permisos y parada.
18. **Audit/Event Ledger:** historial auditable.
19. **Human Approval Boundary:** autorización para efectos externos.
20. **Skill nativa de OpenCode:** uso y reanudación desde el entorno.

Límites obligatorios:
- E propone planes; el scheduler valida y ejecuta transiciones.
- El juez no calcula el score total definitivo.
- El candidato no administra el harness.
- El informe no ejecuta contenido del candidato.
- El adaptador no oculta incompatibilidades.
- El State Store rechaza transiciones ilegales.
- Ningún componente puede marcar una prueba `PASS` sin resultado.
- Aplicar un parche al repositorio principal requiere aprobación.

# 4. Agente E — orquestador adaptativo

## 4.1 Misión

E es el controlador de alto nivel de una ejecución. Busca la siguiente acción que aporte información útil y mejore la probabilidad de una decisión correcta, distribuye recursos y coordina candidatos. No es un candidato más, un juez omnipotente ni un sustituto de las políticas deterministas.

Puede:
- solicitar exploración read-only;
- diseñar el plan dentro del presupuesto;
- elegir candidatos y tarjetas;
- dividir tareas con contratos explícitos;
- iniciar lotes;
- pedir crítica independiente;
- lanzar una ronda enfocada en un fallo o incertidumbre;
- detener trabajo estancado;
- pedir evidencia adicional;
- recomendar `NO_SHIP`.

No puede:
- exceder presupuesto o concurrencia;
- cambiar requisitos, rúbrica o suite tras observar resultados;
- desactivar gates;
- declarar `PASS` sin evidencia;
- editar suite protegida;
- concederse permisos o acceder a secretos;
- publicar, hacer push, merge o desplegar sin autorización;
- borrar fallos o alterar el ledger;
- convertir output ausente en éxito;
- usar un score subjetivo para anular un gate;
- crear agentes recursivos ilimitados;
- reescribir baseline sin registro y aprobación.

## 4.2 Entradas

E recibe un contexto estructurado y mínimo:
- `run_id`, modo y versión de estado;
- tarea congelada y hash;
- baseline y estado Git;
- criterios de aceptación;
- rúbrica, tarjetas y versiones;
- jobs completos, pendientes, fallidos y bloqueados;
- resultados de gates, evidencias y desacuerdos;
- presupuesto restante y límites de llamadas, rondas, concurrencia y tiempo;
- métricas observadas y fallos recientes;
- runtime, modelos y herramientas disponibles;
- estado de aislamiento;
- eventos relevantes;
- aprobaciones humanas existentes y su alcance.

No recibe secretos ni una transcripción ilimitada. El contexto debe reconstruirse desde disco después de un reinicio.

## 4.3 Contrato de salida

Cada decisión de E debe validar un objeto con:
- `decision_id`, `run_id`, `observed_state_version`;
- `action_type` y `target_ids`;
- `reason` y `evidence_refs`;
- estimación de coste y presupuesto restante;
- nivel de riesgo;
- precondiciones y condiciones de parada;
- timestamp y versión de política;
- `requires_human_approval`;
- estado de ejecución.

El runtime rechaza IDs inválidos, evidencia inexistente, transiciones ilegales, campos críticos ausentes y planes fuera de presupuesto. Toda decisión rechazada queda registrada.

## 4.4 Ciclo de control

1. **Observe:** leer estado, métricas y eventos.
2. **Validate:** comprobar frescura e integridad.
3. **Diagnose:** localizar incertidumbres, fallos comunes y riesgos.
4. **Plan:** elegir una acción permitida.
5. **Estimate:** calcular jobs, llamadas, duración y coste.
6. **Policy check:** validar permisos, límites y precondiciones.
7. **Execute:** enviar el plan al scheduler.
8. **Verify:** comprobar el resultado real.
9. **Persist:** guardar decisión, resultado y evidencia.
10. **Adapt or stop:** continuar o finalizar.

El ciclo tiene límites de iteraciones y tiempo. No puede entrar en un bucle de investigación sin fin.

## 4.5 Planificación adaptativa

Empezar con la mínima competición razonable. En Patch Arena se recomiendan 4 candidatos iniciales; 8 puede justificarse para tareas complejas. No lanzar 100 candidatos por defecto.

Se permite una ronda adicional si existe una pregunta concreta: requisito no cubierto, divergencia arquitectónica importante, fallo común, hipótesis crítica sin comprobar o revisión cuyo resultado cambiaría la decisión. E debe explicar qué pregunta responde la ronda, qué resultado cambiaría la decisión y cuánto cuesta.

No crear rondas porque los resultados “no parecen suficientemente inteligentes”. La adaptación debe tener una hipótesis comprobable y presupuesto aprobado.

## 4.6 Diversidad y descomposición

La diversidad debe ser funcional: exploración, implementación, seguridad, pruebas, rendimiento, revisión o diagnóstico. La variación principal puede venir de tarjetas de estrategia, no de decenas de perfiles duplicados.

Cada candidato recibe igual tarea, baseline y restricciones. Las tarjetas varían el enfoque, no los requisitos. Para tareas de alto riesgo, incluir una hipótesis independiente o revisión adversarial.

E solo divide una tarea cuando las subtareas tengan propósito, entradas, outputs, archivos permitidos, dependencias, criterio de terminación, presupuesto, permisos e integración definidos. Si comparten archivos o requieren coordinación frecuente, ejecutar secuencialmente o con un integrador controlado.

## 4.7 Memoria y sesgo

E puede aprender de resultados históricos por tipo de tarea, pero debe registrar contexto, modelo, baseline, configuración y resultados. La memoria no cambia requisitos ni rúbrica de la ejecución actual. Debe poder desactivarse para comparar el sistema con y sin memoria. Las correlaciones no son verdades universales.

E no puede ser la única fuente de solución, juez único y autoridad final. Separar orquestación, generación, evaluación determinista, juicio cualitativo y aprobación humana. Los jueces deben ser ciegos a identidad/proveedor/estrategia cuando sea posible. Las puntuaciones citan tests, artefactos o líneas de diff.

## 4.8 Desacuerdos y condiciones de parada

Si los jueces discrepan materialmente, mostrar la discrepancia y activar una revisión independiente según política. No fingir consenso mediante una media automática.

Detener o recomendar `NO_SHIP` si ningún candidato supera gates, se agota presupuesto/rondas, la suite no es confiable, el aislamiento no se demuestra, el entorno está roto, no hay evidencia suficiente, la siguiente ronda no justifica su coste o se necesita una aprobación no concedida. El informe distingue fallo técnico, evidencia insuficiente, bloqueo externo y ausencia de solución aceptable.

## 4.9 Cómo medir el valor de E

Comparar E adaptativo contra orquestación fija y agente único:
- tasa de aceptación;
- defectos escapados y regresiones;
- coste, llamadas y duración;
- trabajos duplicados;
- porcentaje de rondas que cambian la decisión;
- rondas improductivas;
- falsos positivos/negativos de gates;
- esfuerzo humano;
- reproducibilidad.

Si E aumenta coste y latencia sin mejorar resultados relevantes, simplificarlo o desactivar su adaptación. La sofisticación no es una métrica de éxito.


# 5. Roles de agentes y permisos

Los nombres concretos dependen de OpenCode V2 verificado. Las responsabilidades lógicas son:

- **Explorador read-only:** inspecciona estructura, documentación, dependencias y tests. No modifica archivos; separa hechos de inferencias.
- **Proponente/arquitecto:** propone solución y alternativas; no altera requisitos ni evaluación.
- **Implementador candidato:** modifica solo su entorno aislado y entrega artefactos identificables.
- **Diseñador de pruebas:** convierte criterios en pruebas antes de generar candidatos; congela y protege la suite de gates.
- **Atacante/reviewer:** busca defectos, regresiones y riesgos en modo read-only.
- **Defensor/revisor:** responde a críticas y crea una nueva versión del candidato sin borrar la anterior.
- **Juez:** evalúa contra rúbrica congelada y aporta referencias; no escribe ni ejecuta acciones externas.
- **Agente E:** coordina, pero no delega recursivamente sin límites.

No crear decenas de agentes que solo cambien de nombre. Cada perfil nuevo debe justificar su responsabilidad y cómo se evalúa. Los permisos deben configurarse fuera de la voluntad del agente; el prompt no es una barrera de seguridad.

# 6. Ciclo de vida completo de una ejecución

## 6.1 Reconocimiento forense

Antes de modificar archivos:
- registrar `pwd`, `git status --short --branch`, HEAD y último commit;
- inspeccionar árbol, manifiestos, instrucciones, tests y comandos de build/lint/typecheck;
- verificar versión real de OpenCode y sus contratos;
- inspeccionar upstream, commit, licencia y archivos reutilizados;
- calcular hashes de artefactos reutilizados;
- identificar y preservar cambios sin commit;
- clasificar hechos como verificados, inferidos o pendientes.

Producir `docs/RECONNAISSANCE.md`. Si no puede establecerse baseline reproducible, no empezar Patch Arena mutable.

## 6.2 Especificación de tarea

Debe definir objetivo, alcance, no objetivos, criterios de aceptación, restricciones, entorno, riesgos y evidencia esperada. Se congela antes de generar candidatos. Un cambio posterior crea nueva versión o nueva ejecución; no se editan requisitos a mitad del torneo para favorecer un resultado.

## 6.3 Planificación e inicialización

`plan` no escribe archivos: calcula candidatos, rondas, jobs, olas, concurrencia, llamadas, tiempo, presupuesto y riesgos, mostrando supuestos e incertidumbre. `extreme` requiere confirmación explícita.

`init` crea un directorio único con ID, seed, tarea, baseline, rúbrica, tarjetas, versiones, límites y política de evaluación. Los metadatos congelados son inmutables o versionados.

## 6.4 Preparación del harness

Crear/verificar pruebas, gates, comandos y entorno limpio. Registrar hash de suite. Si el harness no funciona, bloquear la evaluación o limitarla a propuestas no ejecutadas; no declarar elegibilidad técnica sin ejecutar los checks requeridos.

## 6.5 Generación de candidatos

Cada candidato recibe un brief cerrado, completo y versionado. Registrar hashes de prompt, estrategia, baseline y entorno. Los detalles críticos no pueden depender de la memoria conversacional del orquestador.

## 6.6 Crítica, defensa y revisión

Los revisores reciben la versión exacta que revisan. La crítica es read-only. La defensa autorizada solo modifica el candidato propio y guarda nueva versión. Toda revisión tiene diff y relación padre-hijo.

## 6.7 Evaluación y decisión

Ejecutar gates idénticos en entornos limpios. Guardar comandos, versiones, logs, estados y hashes. Solo candidatos técnicamente elegibles pasan a evaluación cualitativa. Seleccionar `WINNER` o `NO_SHIP` mediante reglas explícitas.

## 6.8 Salida y cierre

Generar parche reproducible o rama local. Antes de aplicarlo al árbol principal, exigir aprobación y verificar que el baseline no haya cambiado. Persistir el informe y artefactos antes de cerrar la ejecución.

# 7. CLI: contratos de comandos

Los nombres pueden cambiar por una restricción verificada, pero no pueden desaparecer capacidades. El README documenta el mapeo.

- **`plan`:** estimación sin escribir archivos; número de candidatos, rondas, trabajos, olas, concurrencia, coste, tiempo y riesgos. No inicia agentes.
- **`init`:** crea ejecución única con seed, tarea, baseline, rúbrica, versiones y directorio propio.
- **`next`:** declara fase siguiente y trabajos pendientes; rechaza precondiciones incumplidas.
- **`prompts <phase>`:** produce briefs completos, versionados y limitados a trabajos pendientes; no incluye secretos ni cambia requisitos.
- **`status`:** fase, estado, candidatos, jobs pendientes/completos/fallidos, gates, errores, coste disponible, límites, aislamiento y reanudabilidad.
- **`collect`:** valida outputs y rechaza JSON truncado, campos ausentes, IDs desconocidos, scores fuera de rango y tamaños excesivos.
- **`advance`:** cierra una fase solo si todos los requisitos están resueltos; rechaza transiciones ilegales.
- **`resume`:** reconstruye estado desde disco, reconcilia trabajos y no duplica resultados ni repite efectos externos.
- **`cancel`:** detiene nuevos jobs, cancela procesos cuando sea posible, conserva artefactos y registra procesos no detenidos.
- **`report`:** genera Markdown y HTML estático autocontenido, seguro y trazable.
- **`benchmark`:** ejecuta tareas versionadas y genera comparación de resultados.
- **`apply`:** prepara parche o rama; verifica baseline, muestra diff y requiere aprobación antes de mutar el proyecto principal.

La integración debe usar mecanismos V2 reales: skill nativa, agentes, sesiones hijas, herramientas o plugin si está documentado. No codificar `Agent`, `Task` ni formas de permisos de otro harness sin adaptación comprobada. Si no hay API compatible para UI/TUI, el HTML estático es el fallback funcional.

# 8. Scheduler y máquina de estados

## 8.1 Seed y determinismo

La seed controla la aleatoriedad implementada en scheduler, tarjetas y bracket. No garantiza respuestas idénticas de LLM. Registrar versión del scheduler y distinguir las partes reproducibles de las no deterministas.

## 8.2 Emparejamientos

Cubrir tamaños pares e impares, byes, empates, candidatos duplicados, estados terminales y seeds distintas. Un bye se representa explícitamente. No puede existir ganador fantasma. Los empates siguen política predefinida o terminan en no decisión.

## 8.3 Tarjetas

Asignación equilibrada y rastreable. Las tarjetas no cambian requisitos ni información esencial. No duplicarlas si el espacio disponible basta, salvo política documentada. Si se repiten, reportarlo. Guardar ID, versión y hash.

## 8.4 Estados

Flujo recomendado:

`CREATED → PLANNED → INITIALIZED → PREPARING → READY → RUNNING → COLLECTING → EVALUATING → DECIDING → REPORTING → COMPLETED`

Estados adicionales: `PAUSED`, `CANCELLED`, `BLOCKED`, `FAILED`, `NO_SHIP`.

Cada transición tiene precondiciones. No se puede llegar a `DECIDING` si faltan gates obligatorios o la suite es inválida. Los estados terminales no se reabren silenciosamente; se registra evento de reanudación o se crea una nueva ejecución.

## 8.5 Jobs e idempotencia

Cada job incluye ID, fase, candidato, tipo, hash de input, estado, intentos, timestamps, sesión si existe, output esperado, artefactos, error, coste observable y política de reintento.

La idempotencia significa que el runtime no duplica registros ni contabiliza dos veces un trabajo lógico. No significa que una nueva llamada LLM produzca el mismo texto.

Los reintentos son limitados. Tras agotarlos, el job falla explícitamente. Acciones con efectos externos no se repiten sin idempotencia demostrada o autorización.

## 8.6 Persistencia y concurrencia

- Persistencia atómica.
- Lock o mecanismo equivalente para evitar dos controladores de una misma ejecución.
- Ledger append-only o equivalente auditable.
- IDs estables y esquema versionado.
- Migraciones explícitas.
- Hashes para detectar corrupción.
- Escritura temporal y reemplazo atómico cuando el sistema lo soporte.

# 9. Contratos de datos y artefactos

El formato (JSON/JSONL, SQLite más archivos u otro) se elige mediante ADR. Las garantías de validación, identidad, versionado y trazabilidad son obligatorias.

## 9.1 `Run`

Campos mínimos: `run_id`, `schema_version`, `mode`, timestamps, `status`, `seed`, referencias y hashes de tarea/baseline/rúbrica/tarjetas/suite, versiones de runtime, presupuesto, versión de política, fase actual, decisión terminal, índice de artefactos y referencia al último evento.

## 9.2 `Candidate`

`candidate_id`, `run_id`, `strategy_id`, `prompt_hash`, `baseline_hash`, `workspace_ref`, verificación de aislamiento, estado, referencias de output/diff, resultados de gates y jueces, elegibilidad, observaciones de coste, razón de fallo y versión padre para revisiones.

## 9.3 `Job`

`job_id`, `run_id`, candidato, fase, tipo, hash de input, estado, número de intentos, timestamps, sesión, output, validación, error, política de reintento y recursos observados.

## 9.4 `GateResult`

`gate_id`, candidato, estado, comando, versión de herramienta, timestamps, exit code, stdout/stderr refs, evidencias, clase de fallo, notas y hash de suite. Estados: `PASS`, `FAIL`, `BLOCKED`, `NOT_RUN`, `INCONCLUSIVE`.

## 9.5 `Decision`

`decision_id`, `run_id`, estado, ganador si existe, candidatos elegibles/rechazados, resumen de gates y scores, desacuerdos, evidencias, razón, versión de política, timestamp y aprobación requerida/estado.

## 9.6 Validación

Usar esquemas estrictos. Rechazar campos obligatorios ausentes, IDs desconocidos, tipos incorrectos, rangos inválidos, rutas inseguras y archivos grandes. Todo dato externo es no confiable, incluso si procede de un agente propio.


# 10. Evaluación, gates y selección

## 10.1 Nivel 1: gates objetivos

Según el lenguaje y repositorio real:
- tests obligatorios;
- aceptación funcional;
- lint, typecheck y build si existen;
- regresiones contra baseline;
- invariantes/property-based cuando aporten valor;
- análisis estático y de dependencias/secretos cuando estén disponibles y autorizados;
- benchmarks de rendimiento para tareas pertinentes;
- integridad del harness;
- comprobación de que no se debilitaron tests/gates.

Estados: `PASS`, `FAIL`, `BLOCKED`, `NOT_RUN`, `INCONCLUSIVE`. Una herramienta ausente es `NOT_RUN`; una herramienta que no funciona por un bloqueo puede ser `BLOCKED`. No instalar globalmente sin aprobación. Guardar comandos exactos, versiones y salida relevante, redactando secretos.

El evaluador usa la suite confiable y la ejecuta en una copia limpia del candidato. Los tests del candidato complementan, no sustituyen, los gates protegidos.

## 10.2 Nivel 2: juicio cualitativo

Solo candidatos técnicamente elegibles pasan a los jueces. Rúbrica inicial propuesta para Patch Arena:

| Dimensión | Peso inicial |
|---|---:|
| Corrección funcional y cobertura de requisitos | 35% |
| Robustez y regresiones | 20% |
| Seguridad y privacidad | 15% |
| Mantenibilidad y claridad | 10% |
| Rendimiento y recursos | 10% |
| Documentación y operabilidad | 10% |

Estos pesos son una propuesta inicial. Se congelan antes de generar candidatos; solo se cambian entre ejecuciones con nueva versión y justificación. La rúbrica de Patch Arena no debe confundirse con la rúbrica de Answer Arena.

## 10.3 Score y elegibilidad

El juez devuelve evaluaciones por dimensión, razones y referencias de evidencia. El runtime valida rangos y calcula la agregación. Una puntuación sin evidencia queda invalidada o marcada no sustentada. El score nunca convierte a un candidato inelegible en elegible.

Gates de bloqueo mínimos:
- requisito obligatorio fallido;
- vulnerabilidad crítica no resuelta;
- regresión que rompe requisito;
- suite manipulada/no confiable;
- aislamiento no demostrado cuando se exige ejecución mutable;
- artefacto inválido/no reproducible;
- entorno de evaluación roto;
- intento de modificar el harness o escapar del workspace.

## 10.4 `NO_SHIP`

`NO_SHIP` es una decisión correcta cuando nadie pasa todos los gates, la evaluación no es confiable, hay un conflicto crítico o la evidencia es insuficiente. El informe debe indicar por candidato qué gate falló y distinguir “solución incorrecta” de “evaluación bloqueada”. No se presenta `NO_SHIP` como un fallo del sistema si es el resultado esperado.

# 11. Seguridad, privacidad y cadena de suministro

## 11.1 Threat model obligatorio

Crear `docs/THREAT_MODEL.md` con activos, límites de confianza, adversarios, amenazas, mitigaciones, pruebas y riesgos residuales. Debe cubrir:
- prompt injection en README, issues, HTML, logs y resultados de herramientas;
- intento de alterar juez, rúbrica o tests protegidos;
- lectura accidental de `.env`, credenciales, claves SSH y configuración privada;
- shell commands, scripts y dependencias no confiables;
- path traversal, symlinks y escritura fuera del workspace;
- red no autorizada;
- contaminación entre candidatos y manipulación de puntuaciones;
- sesgo de juez;
- corrupción de estado y JSON malicioso;
- outputs gigantes;
- coste ilimitado, tormenta de agentes y bucles;
- inyección HTML/JavaScript en informes;
- cambios inesperados del baseline;
- procesos que siguen activos tras cancelar;
- proveedores o herramientas no disponibles;
- dependencia comprometida o licencia incompatible.

## 11.2 Límites de confianza

README, issues, webs, MCP, outputs de agentes y logs son datos no confiables. No pueden modificar políticas ni permisos. Los artefactos de candidatos se separan del evaluador. La suite protegida debe ser inaccesible para escritura por los candidatos. Si se afirma que los tests ocultos no están disponibles para los candidatos, hay que demostrarlo.

## 11.3 Rutas, comandos y secretos

Resolver rutas canónicamente; rechazar escapes, workspaces inesperados y symlinks peligrosos. Limpiar solo directorios creados y registrados por el runtime. Aplicar allowlists/políticas explícitas, timeout, límite de output y cancelación a comandos. No ejecutar instrucciones extraídas de datos no confiables como comandos autorizados.

No incluir secretos en prompts, logs ni informes. Redactar tokens antes de persistir outputs. No almacenar transcripciones completas innecesarias. No ejecutar scanners activos contra sistemas externos; las pruebas se limitan a repositorios y targets propios/controlados.

## 11.4 HTML y cadena de suministro

El informe debe ser estático y autocontenido. Escapar todo texto externo; no ejecutar HTML, scripts, URLs activas o contenido embebido de candidatos. Inspeccionar licencias, conservar atribución y registrar URL, commit y SHA-256 del upstream reutilizado. Skills, plugins y MCP no son seguros solo por estar en un catálogo.

# 12. Coste, concurrencia y operación

Límites configurables por ejecución:
- candidatos máximos;
- llamadas máximas;
- rondas/olas;
- concurrencia;
- reintentos por job;
- duración por fase y timeout de comandos;
- tamaño máximo de output;
- presupuesto monetario si hay datos suficientes;
- tiempo total y cantidad de subtareas;
- profundidad máxima de delegación;
- política de pausa/cancelación.

Perfiles:
- `quick`: pocos candidatos y recorrido breve.
- `standard`: competición equilibrada, evaluación y revisión.
- `extreme`: mayor alcance, exige confirmación explícita con plan y presupuesto.

En Patch Arena, comenzar con 4 candidatos; ampliar a 8 o más solo si benchmark demuestra valor. La estimación se calcula desde el scheduler real, no con constantes. La misión anterior cita como referencia aproximada del sistema original unas 595 llamadas para 100 competidores y alrededor de 70 olas con lotes de 10; esa cifra debe recalcularse para el runtime y modo reales.

Si no se puede medir el coste monetario, no inventar cifras. Informar llamadas, duración y estimaciones marcadas como aproximadas. Cancelar debe impedir nuevos jobs, conservar artefactos y registrar procesos que no pudieron detenerse.

# 13. Integración OpenCode CLI V2

## 13.1 Verificación

Antes de diseñar la integración:
- ejecutar `opencode --version` y ayuda real;
- contrastar skills, agentes, tools, permisos y sesiones con documentación V2 vigente;
- comprobar nombres de campos y acciones;
- probar agente read-only y escritura aislada;
- comprobar recuperación de resultados;
- verificar `cwd` o mecanismo equivalente;
- comprobar comportamiento de procesos background al cerrar terminal;
- documentar todo en `docs/RECONNAISSANCE.md`.

No copiar configuración V1 ni nombres de herramientas de otros harnesses sin validación.

## 13.2 Skill y adaptador

Debe existir una skill nativa clara, por ejemplo `.opencode/skills/arena-forge/SKILL.md`, ajustada a la ruta real confirmada. Debe explicar uso, estado y reanudación desde disco sin volcar cientos de propuestas al contexto principal.

Toda dependencia de OpenCode pasa por un adaptador que declara capacidades comprobadas. Si una función no existe, se reporta como no soportada; no se simula éxito.

## 13.3 Alternativa segura

Si no hay aislamiento nativo confiable:
1. pedir diffs completos como artefactos;
2. validar cada diff;
3. aplicarlo con ejecutor controlado a copia temporal;
4. ejecutar pruebas allí;
5. guardar logs y hashes.

Si esta alternativa no puede demostrarse, Patch Arena queda bloqueado o limitado a propuestas no ejecutadas.

## 13.4 Skills complementarias

No instalar un catálogo completo. Verificar disponibilidad, licencia, commit y compatibilidad. Pueden aprovecharse capacidades concretas de `obra/superpowers` para planificación, TDD, debugging y review; de `addyosmani/agent-skills` para testing, seguridad, observabilidad y rendimiento; y de OWASP para threat modeling.

No instalar dos skills por mecanismos distintos ni varias skills que dupliquen orquestación/memoria/review. El flujo base debe funcionar en local con herramientas disponibles, sin depender de Figma, servicios remotos, tokens pagos o MCP externos. Semgrep, Gitleaks, Trivy u OSV-Scanner solo si están disponibles, autorizados y son pertinentes; reportar cada herramienta ausente.

# 14. Memoria, auditoría y reanudación

Mantener un ledger append-only o equivalente para eventos relevantes: inicio, plan, jobs, resultados, fallos, decisiones de E, gates, juicios, cancelación, reanudación y decisión final. No borrar eventos para mejorar el resultado; corregir mediante nuevos eventos.

Tareas, rúbricas, tarjetas, suites y baseline se guardan por versión/hash. El sistema conserva lo necesario para reproducir y auditar sin guardar secretos ni transcripciones completas innecesarias.

Al reanudar:
- verificar hashes;
- reconstruir estado;
- no volver a ejecutar outputs completados;
- reconciliar trabajos inciertos de forma conservadora;
- no contar incertidumbre como éxito;
- no repetir efectos externos;
- registrar la reconciliación.

# 15. Informes y observabilidad

## 15.1 Markdown

Debe incluir decisión y estado, tarea, alcance, baseline, versiones, seed, candidatos, estrategias, bracket, gates, scores por dimensión, referencias de evidencia, diffs, fallos, desacuerdos, comandos ejecutados, resultados, herramientas `NOT_RUN`, duración, coste observado, límites, baseline comparativo, riesgos residuales y razón de `WINNER`/`NO_SHIP`.

## 15.2 HTML

Autocontenido y utilizable sin servidor externo. Representa bracket, candidatos, rondas, scores, evidencias, pruebas y decisión. No esconder fallos detrás de una puntuación global. Escapar contenido externo.

## 15.3 Observabilidad de E

Registrar decisiones, evidencia que las motivó, alternativas registradas, presupuesto previsto/observado, rondas iniciadas o descartadas y razón, condiciones de parada, desacuerdos y si la adaptación cambió el resultado. No hace falta almacenar razonamiento privado interno del modelo; hacen falta decisiones operativas, evidencias y resultados verificables.

# 16. Pruebas obligatorias de Arena Forge

La suite debe incluir unitarias, integración y end-to-end con fixtures reproducibles:

1. **Scheduler determinista:** tamaños pares/impares, seeds, tarjetas, byes, empates, emparejamientos legales y estado terminal.
2. **E2E Answer Arena:** al menos 4 candidatos, ataques, defensas, jueces, collect, advance, decisión e informe.
3. **E2E Patch Arena:** fixture con bug y regresión; dos o más candidatos aislados; mismo harness; gates prevalecen sobre score narrativo.
4. **NO_SHIP:** todos fallan un requisito obligatorio; no hay campeón.
5. **Reanudación:** interrupción a mitad de fase y recuperación sin duplicar trabajos.
6. **Outputs inválidos:** JSON truncado, keys ausentes, score fuera de rango, IDs desconocidos, ruta de escape y output gigante.
7. **Integridad del evaluador:** intento de editar/saltarse suite protegida se detecta.
8. **Aislamiento:** logs/rutas prueban que no comparten escritura y que el árbol principal no cambia.
9. **Prompt injection:** README/issue malicioso se trata como dato, no como instrucción.
10. **Informe seguro:** HTML/JavaScript en output se escapa y no se ejecuta.
11. **Presupuesto:** límites de concurrencia, jobs, rondas y tiempo se respetan.
12. **Baseline adversarial:** caso donde el método original gana; el informe lo dice.
13. **Reproducibilidad honesta:** scheduler/bracket/estructura reproducibles; LLM marcado no determinista.
14. **Límites de E:** no excede presupuesto ni cambia rúbrica/gates.
15. **Desacuerdo de jueces:** la discrepancia queda visible.
16. **Cambios preexistentes:** un repo sucio no se limpia ni se incorpora silenciosamente al baseline.
17. **Cancelación:** no inicia nuevos jobs, conserva artefactos y registra procesos no detenidos.
18. **Hashes:** modificación de artefacto congelado bloquea evaluación.
19. **Fallo de runtime:** agente/timeout no produce output inventado y respeta reintentos.
20. **Rutas/symlinks:** intentos de escapar del workspace se rechazan o aíslan.
21. **Valor adaptativo:** E se compara con orquestación fija en aceptación, coste, tiempo y utilidad de rondas.
22. **Checkout limpio:** otra persona reproduce demo siguiendo instrucciones.

Si algo falla, corregir causa raíz y repetir. No cambiar expectativas, eliminar tests ni desactivar gates para fabricar un resultado verde.

# 17. Artefactos obligatorios del repositorio

Como mínimo:
- `README.md` con instalación/uso verificados;
- `docs/RECONNAISSANCE.md`;
- `docs/ARCHITECTURE.md` con diagramas Mermaid;
- `docs/THREAT_MODEL.md`;
- ADRs sobre aislamiento, integración V2, evaluación, estado/reanudación y coste;
- `CHANGELOG.md` o notas de versión;
- skill nativa OpenCode y perfiles mínimos de agentes;
- runtime adapter, scheduler y CLI;
- contratos y validación de outputs;
- state store, ledger y gestor de aislamiento;
- harness, gate engine, juez y score calculator;
- benchmark runner y generador Markdown/HTML;
- tests unitarios, integración y fixtures E2E;
- `.gitignore` sin ocultar archivos importantes;
- licencia/notices de terceros;
- demo sintética e informes redactados sin credenciales;
- instrucciones para reproducir.

Los nombres de archivo pueden variar por razón documentada, pero cada responsabilidad debe quedar cubierta.


# 18. Criterios de aceptación finales

Cada requisito debe enlazarse a test, comando, resultado y artefacto. Casillas marcadas sin referencia no cuentan.

- **AF-AC-001 Reconocimiento:** versión de OpenCode, API efectiva, repo, estado Git, dependencias y tests identificados; hechos clasificados como verificados/inferidos/pendientes.
- **AF-AC-002 Upstream:** repositorio original, commit, licencia y archivos reutilizados inspeccionados; atribución y hashes registrados.
- **AF-AC-003 Skill:** la skill aparece y se carga con el ID/ruta exactos en el entorno probado.
- **AF-AC-004 CLI:** planificación, inicialización, estado, ejecución, collect, advance, cancelación, reanudación, informe y benchmark funcionan con datos reales.
- **AF-AC-005 Answer Arena:** E2E con al menos cuatro candidatos y artefactos persistidos.
- **AF-AC-006 Patch Arena:** E2E con al menos dos candidatos aislados y mismo harness; si no se demuestra aislamiento, modo declarado bloqueado y no anunciado como operativo.
- **AF-AC-007 Gates:** los gates objetivos preceden al score LLM y el juez no puede anularlos.
- **AF-AC-008 NO_SHIP:** prueba reproducible de ausencia de candidatos elegibles.
- **AF-AC-009 Reanudación:** interrupción/reanudación sin duplicación ni corrupción.
- **AF-AC-010 Seguridad:** pruebas de prompt injection, corrupción, harness, rutas, aislamiento, HTML y coste.
- **AF-AC-011 Informe:** hashes, decisiones, evidencia rastreable, límites y resultados negativos.
- **AF-AC-012 Suite del proyecto:** tests, lint, typecheck, build y E2E pertinentes ejecutados; herramientas ausentes marcadas `NOT_RUN`.
- **AF-AC-013 Protección del repo:** sin publicación/push/merge/despliegue ni mutación final sin aprobación; cambios preexistentes preservados.
- **AF-AC-014 Reproducción externa:** tercero reproduce demo desde checkout limpio.
- **AF-AC-015 E bajo control:** no supera presupuesto, cambia rúbricas congeladas, edita suite, salta gates ni ejecuta efectos externos sin autorización.
- **AF-AC-016 Valor adaptativo:** benchmark de agente único vs. orquestación fija vs. E adaptativo, o declaración explícita de que la eficacia adaptativa no está demostrada.
- **AF-AC-017 Decisión auditable:** decisión apunta a gates, scores, artefactos y política.
- **AF-AC-018 Sin éxito ficticio:** ningún `PASS` sin ejecución, coste inventado, output fabricado o ausencia presentada como éxito.

Un gate crítico incumplido impide declarar `COMPLETE`. Informar el estado parcial y los bloqueos primero; no cambiar criterios para simular cumplimiento.

# 19. Protocolo de implementación

Flujo incremental obligatorio:
1. reconocimiento e inventario;
2. ADR de integración V2;
3. contratos y máquina de estados;
4. tests que fallen para el comportamiento nuevo;
5. vertical slice mínimo;
6. implementación mínima;
7. tests unitarios e integración;
8. revisión de cumplimiento;
9. revisión de seguridad;
10. correcciones;
11. benchmark;
12. documentación y reproducción desde checkout limpio.

Antes de una arquitectura grande de plugins, demostrar un vertical slice con skill cargada, cuatro candidatos, estado persistido, gate objetivo, selección o `NO_SHIP`, reanudación e informe.

Usar subagentes en paralelo para tareas read-only independientes, threat model, arquitectura y diseño de pruebas. No lanzar implementadores simultáneos contra el mismo worktree. Si un agente falla dos veces, registrar el fallo y continuar de forma segura; nunca inventar su resultado.

No instalar dependencias ni skills en bloque. Inspeccionar compatibilidad, licencia y duplicación. No construir una UI compleja antes de tener runtime y evidencia funcionales.

# 20. Comportamientos prohibidos aunque parezcan razonables

1. **No maximizar candidatos por defecto:** más agentes aumentan coste y pueden repetir sesgos.
2. **No elegir por score promedio únicamente:** un gate crítico fallido excluye al candidato.
3. **No cambiar el objetivo tras ver resultados:** tarea, rúbrica y suite se congelan.
4. **No asumir compatibilidad V1/V2:** validar contra instalación real.
5. **No afirmar aislamiento por nombres distintos:** verificar rutas y permisos.
6. **No permitir escritura de candidatos en el harness:** separar y proteger.
7. **No ocultar tests no ejecutados:** usar `NOT_RUN`, `BLOCKED` o `INCONCLUSIVE`.
8. **No inventar costes:** distinguir observaciones y estimaciones.
9. **No prometer determinismo LLM por usar seed:** seed solo cubre aleatoriedad controlada.
10. **No tratar score LLM como prueba de corrección:** es señal cualitativa.
11. **No auto-merge ni auto-deploy:** preparar artefactos y pedir aprobación.
12. **No instalar todas las skills:** seleccionar las necesarias y evitar duplicación.
13. **No crear perfiles redundantes sin hipótesis:** cada rol aporta función evaluable.
14. **No permitir autoautorización de E:** políticas y permisos viven fuera del modelo.
15. **No esconder desacuerdos:** mostrar incertidumbre y pedir revisión.
16. **No borrar fallos al reanudar:** conservar historial y reconciliar estados.
17. **No ejecutar contenido externo como instrucción confiable:** tratarlo como dato.
18. **No equiparar tests verdes con ausencia de vulnerabilidades:** declarar alcance y riesgos.
19. **No confundir demo sintética con evidencia general:** usar benchmark comparativo.
20. **No declarar terminado porque compila:** exigir criterios y artefactos.
21. **No medir éxito por complejidad de E:** demostrar calidad superior o coste menor.
22. **No ocultar victorias del baseline:** resultados negativos son esenciales.
23. **No aplicar un diff solo porque un agente lo recomienda:** revisar diff y baseline.
24. **No permitir recursión ilimitada:** limitar profundidad, cantidad, coste y tiempo.
25. **No continuar como si nada tras una violación de integridad:** bloquear la evaluación afectada y registrar el incidente.

# 21. Matriz de trazabilidad mínima

| ID | Requisito | Evidencia mínima |
|---|---|---|
| AF-PR-001 | Gates preceden al juicio | Test de rechazo pese a score alto |
| AF-PR-002 | Aislamiento | Logs/rutas y prueba sin escritura compartida |
| AF-PR-003 | NO_SHIP | E2E sin candidatos elegibles |
| AF-PR-004 | Reanudación | Interrupción/reanudación sin duplicación |
| AF-PR-005 | Reproducibilidad honesta | Seed, hashes y no determinismo documentado |
| AF-PR-006 | Mínimo privilegio | Políticas, tests de permisos y threat model |
| AF-PR-007 | Preservar cambios | Fixture de repo sucio que queda intacto |
| AF-PR-008 | Compatibilidad real | Versión, comandos y docs V2 verificados |
| AF-PR-009 | Presupuesto | Estimación y tests de límites |
| AF-PR-010 | Aprobación humana | Efectos externos bloqueados sin aprobación |
| AF-AC-005 | Answer Arena E2E | Artefactos y reporte de torneo |
| AF-AC-006 | Patch Arena E2E | Candidatos aislados y harness común |
| AF-AC-010 | Seguridad | Pruebas adversariales y threat model |
| AF-AC-014 | Reproducción externa | Registro desde checkout limpio |
| AF-AC-015 | E bajo control | Tests de presupuesto, permisos y gates |
| AF-AC-016 | Valor de E | Benchmark comparativo o eficacia no demostrada |

La matriz del repositorio debe ampliarse a una fila por requisito implementable con ruta del test, comando, resultado y artefacto de evidencia.

# 22. Entrega final del equipo implementador

La entrega responde con evidencia:
1. qué se construyó y qué no;
2. capacidades de OpenCode V2 verificadas y no verificadas;
3. archivos añadidos/modificados;
4. cobertura unitaria, integración y E2E;
5. comandos exactos y resultados;
6. gates fallidos, bloqueados o no ejecutados;
7. demostración de `NO_SHIP`;
8. prueba de aislamiento;
9. prueba de reanudación;
10. resultados contra baseline;
11. valor incremental de E adaptativo;
12. coste y duración observados, y datos no medibles;
13. riesgos residuales;
14. reproducción desde checkout limpio;
15. tres siguientes pasos de mayor impacto, priorizados por evidencia.

No declarar éxito por intención, código escrito ni opinión de los agentes. Presentar artefactos para que un tercero lo compruebe.

# 23. Definición final de terminado

Arena Forge está terminado cuando es ejecutable, documentado, reanudable y auditable; la integración OpenCode está comprobada en el entorno objetivo; Answer Arena funciona; Patch Arena funciona con aislamiento demostrado o se declara inequívocamente limitado; los gates objetivos prevalecen sobre el score subjetivo; `NO_SHIP` funciona; los informes muestran evidencia y fallos; las pruebas adversariales y de recuperación pasan; y un tercero reproduce la demo.

E está implementado técnicamente cuando sus decisiones son estructuradas y persistidas, respeta presupuesto y permisos, adapta el torneo por razones verificables y no controla en exclusiva su propia evaluación. La **eficacia adaptativa** de E solo se considera demostrada cuando existe una comparación reproducible con orquestación fija y agente único. Hasta entonces es una hipótesis pendiente, aunque el código del orquestador exista.

**Regla final:** no declarar terminado lo no verificado; no proclamar ganador a quien no superó los gates; no ocultar resultados que contradicen la hipótesis; y no permitir que el coordinador sea la única autoridad que certifique su propio éxito.

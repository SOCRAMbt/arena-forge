"""Arena Forge — paquete de gobierno (spec v1.0).

Componentes (§3 de la especificacion):
- util        : hashing, escritura atomica, rutas canonicas, redaccion
- contracts   : esquemas estrictos Run/Candidate/Job/GateResult/Decision
- state       : maquina de estados formal con precondiciones
- ledger      : historial append-only auditable (JSONL)
- adapter     : Runtime Adapter OpenCode V2 (capacidades comprobadas)
- agent_e     : orquestador adaptativo E (decisiones estructuradas)
- isolation   : Workspace/Isolation Manager (diffs + copia controlada)
- gates       : Gate Engine determinista
- score       : Score Calculator aritmetico (nunca lo calcula el LLM)
- benchmark   : Benchmark Runner comparativo
- report      : generador Markdown + HTML estatico seguro

Solo stdlib. El modelo nunca decide elegibilidad ni calcula el total.
"""
__all__ = [
    "util", "contracts", "state", "ledger", "adapter",
    "agent_e", "isolation", "gates", "score", "benchmark", "report",
]
FORGE_SCHEMA_VERSION = 2

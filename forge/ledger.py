"""Ledger append-only auditable (§8.6, §14).

El historial vive en `ledger.jsonl`, una linea JSON por evento con `seq`
monotono. Nunca se borran ni se reescriben eventos: corregir = anadir evento.
`verify` comprueba que los seq son estrictamente crecientes y sin huecos.
Hash-chain: cada evento incluye prev_hash y event_hash para detectar alteracion.
"""
import hashlib
import json
import os

from .util import append_line, now_ts, read_json_bounded

LEDGER_FILE = "ledger.jsonl"


def _path(run_dir):
    return os.path.join(run_dir, LEDGER_FILE)


def next_seq(run_dir):
    events = read(run_dir)
    return (events[-1]["seq"] + 1) if events else 1


def append(run_dir, kind, detail="", refs=None, actor="runtime"):
    """Anade un evento. Solo se anaden; jamas se elimina ni reordena."""
    events = read(run_dir)
    prev_hash = events[-1].get("event_hash") if events else "0" * 64
    
    ev = {
        "seq": len(events) + 1,
        "ts": now_ts(),
        "kind": str(kind),
        "actor": str(actor),
        "detail": str(detail),
        "refs": refs or {},
        "prev_hash": prev_hash,
    }
    # Calcular hash del evento (sin event_hash)
    ev_canonical = json.dumps(ev, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ev["event_hash"] = hashlib.sha256(ev_canonical.encode("utf-8")).hexdigest()
    
    append_line(_path(run_dir), json.dumps(ev, ensure_ascii=False))
    return ev


def read(run_dir, max_bytes=None):
    path = _path(run_dir)
    if not os.path.isfile(path):
        return []
    events = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                # Linea corrupta: se preserva como evento de incidente, no se borra.
                events.append({"seq": -1, "ts": now_ts(), "kind": "CORRUPT_LINE",
                               "actor": "runtime", "detail": line[:200],
                               "refs": {}})
    return events


def verify(run_dir):
    """Devuelve (ok, problemas). Verifica seq, hash-chain y referencias."""
    events = read(run_dir)
    problems = []
    last_seq = 0
    expected_prev = "0" * 64
    for ev in events:
        seq = ev.get("seq")
        if seq == -1:
            problems.append("linea corrupta en el ledger")
            continue
        if not isinstance(seq, int):
            problems.append("evento sin seq entero")
            continue
        if seq != last_seq + 1:
            problems.append("seq no contiguo: %s tras %s" % (seq, last_seq))
        
        # Verificar hash-chain
        prev_hash = ev.get("prev_hash")
        if prev_hash != expected_prev:
            problems.append("prev_hash no coincide: esperado=%s actual=%s" % (expected_prev, prev_hash))
        
        event_hash = ev.get("event_hash")
        if event_hash:
            # Recalcular hash del evento (sin event_hash)
            ev_copy = {k: v for k, v in ev.items() if k != "event_hash"}
            ev_canonical = json.dumps(ev_copy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            computed_hash = hashlib.sha256(ev_canonical.encode("utf-8")).hexdigest()
            if computed_hash != event_hash:
                problems.append("event_hash invalido para seq=%s" % seq)
            expected_prev = event_hash
        else:
            problems.append("event_hash ausente en seq=%s" % seq)
        
        last_seq = seq
    
    return (not problems), problems


def last_ref(run_dir):
    events = read(run_dir)
    return events[-1].get("seq") if events else None


def tail(run_dir, n=20):
    return read(run_dir)[-n:]

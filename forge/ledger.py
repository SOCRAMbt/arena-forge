"""Ledger append-only auditable (§8.6, §14).

El historial vive en `ledger.jsonl`, una linea JSON por evento con `seq`
monotono. Nunca se borran ni se reescriben eventos: corregir = anadir evento.
`verify` comprueba que los seq son estrictamente crecientes y sin huecos.
Hash-chain: cada evento incluye prev_hash y event_hash para detectar alteracion.
"""
import hashlib
import json
import os

from .util import FileLock, append_line, now_ts, read_json_bounded

LEDGER_FILE = "ledger.jsonl"
LOCK_FILE = ".ledger.lock"


def _path(run_dir):
    return os.path.join(run_dir, LEDGER_FILE)


def _last_valid(events):
    """Ultimo evento BIEN FORMADO (ignora lineas corruptas y forjadas).

    Un evento solo cuenta si tiene `seq` entero positivo **y** `event_hash`
    con forma de sha256: de lo contrario, una linea forjada con
    `{"seq": 99}` secuestraria el numerado y romperia la cadena para siempre.
    """
    for ev in reversed(events):
        if not isinstance(ev, dict):
            continue
        seq = ev.get("seq")
        digest = ev.get("event_hash")
        if (isinstance(seq, int) and seq > 0 and isinstance(digest, str)
                and len(digest) == 64):
            return ev
    return None


def last_valid_seq(run_dir):
    """Ultimo seq bien formado. No se ve afectado por lineas corruptas."""
    ev = _last_valid(read(run_dir))
    return ev["seq"] if ev else 0


def next_seq(run_dir):
    """Siguiente seq. No se ve afectado por lineas corruptas."""
    events = read(run_dir)
    last = _last_valid(events)
    return (last["seq"] + 1) if last else 1


def append(run_dir, kind, detail="", refs=None, actor="runtime"):
    """Anade un evento. Solo se anaden; jamas se elimina ni reordena.

    La escritura esta serializada con un lock de SISTEMA OPERATIVO: dos
    procesos concurrentes no pueden asignar el mismo seq ni partir la cadena
    de hashes. La linea corrupta previa NO se borra ni se reescribe: el seq
    continua desde el ultimo evento VALIDO.
    """
    with FileLock(os.path.join(run_dir, LOCK_FILE)):
        events = read(run_dir)
        last = _last_valid(events)
        prev_hash = last.get("event_hash") if last else "0" * 64
        ev = {
            "seq": (last["seq"] + 1) if last else 1,
            "ts": now_ts(),
            "kind": str(kind),
            "actor": str(actor),
            "detail": str(detail),
            "refs": refs or {},
            "prev_hash": prev_hash,
        }
        # Calcular hash del evento (sin event_hash)
        ev_canonical = json.dumps(ev, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"))
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
                ev = json.loads(line)
            except ValueError:
                ev = None
            if isinstance(ev, dict):
                events.append(ev)
            else:
                # Linea corrupta (o JSON que no es un evento): se preserva como
                # evento de incidente, no se borra.
                events.append({"seq": -1, "ts": now_ts(), "kind": "CORRUPT_LINE",
                               "actor": "runtime", "detail": line[:200],
                               "refs": {}})
    return events


def verify(run_dir):
    """Devuelve (ok, problemas). Verifica seq, hash-chain y referencias.

    Una linea corrupta se PRESERVA y se reporta, pero no rompe la continuidad
    de la cadena: los eventos posteriores siguen encadenando contra el ultimo
    evento valido.
    """
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

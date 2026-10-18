"""Ledger append-only auditable (§8.6, §14).

El historial vive en `ledger.jsonl`, una linea JSON por evento con `seq`
monotono. Nunca se borran ni se reescriben eventos: corregir = anadir evento.
`verify` comprueba que los seq son estrictamente crecientes y sin huecos.
"""
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
    ev = {
        "seq": next_seq(run_dir),
        "ts": now_ts(),
        "kind": str(kind),
        "actor": str(actor),
        "detail": str(detail),
        "refs": refs or {},
    }
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
    """Devuelve (ok, problemas). seq estrictamente creciente y sin huecos."""
    events = read(run_dir)
    problems = []
    last = 0
    for ev in events:
        seq = ev.get("seq")
        if seq == -1:
            problems.append("linea corrupta en el ledger")
            continue
        if not isinstance(seq, int):
            problems.append("evento sin seq entero")
            continue
        if seq != last + 1:
            problems.append("seq no contiguo: %s tras %s" % (seq, last))
        last = seq
    return (not problems), problems


def last_ref(run_dir):
    events = read(run_dir)
    return events[-1].get("seq") if events else None


def tail(run_dir, n=20):
    return read(run_dir)[-n:]

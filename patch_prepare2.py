with open(r'C:\Users\Marcos\arena-forge\arena_forge.py', 'r') as f:
    content = f.read()

# Find the function
idx = content.find('def _prepare_patch(run, d, args):')
if idx < 0:
    print('Function not found')
    exit(1)

# Find the end of the function (next function or end of file)
# Look for the next "def " at column 0 after this one
next_def = content.find('\ndef ', idx + 1)
if next_def < 0:
    next_def = len(content)

old_func = content[idx:next_def]
print('Found function, length:', len(old_func))
print('---START---')
print(old_func[:500])
print('---END---')

# Now do the replacement with the new function
new_func = '''def _prepare_patch(run, d, args):
    \"\"\"Crea workspaces aislados por candidato y registra la prueba de aislamiento.\"\"\"
    n = getattr(args, "agents", None) or 4
    baseline_dir = getattr(args, "baseline_dir", None)
    ids = ["cand-%02d" % (i + 1) for i in range(n)]
    if os.path.isdir(os.path.join(d, "candidates")):
        existing = sorted(x for x in os.listdir(os.path.join(d, "candidates"))
                          if os.path.isdir(os.path.join(d, "candidates", x)))
        if existing:
            ids = existing
    proof = isolation.ensure_workspaces(d, ids)
    # baseline copia local para diffs controlados (P0-04: recursivo)
    src = os.path.abspath(baseline_dir) if baseline_dir else None
    if src and os.path.isdir(src):
        bdir = os.path.join(d, "baseline")
        os.makedirs(bdir, exist_ok=True)
        for name in os.listdir(src):
            s = os.path.join(src, name)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(bdir, name))
            elif os.path.isdir(s):
                shutil.copytree(s, os.path.join(bdir, name),
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Cada candidato arranca desde el mismo baseline (P0-04: recursivo).
    for cid in ids:
        cdir = os.path.join(d, "candidates", cid)
        if src and os.path.isdir(src):
            for name in os.listdir(src):
                s = os.path.join(src, name)
                if os.path.isfile(s) and not name.lower().endswith((".pyc",)):
                    shutil.copy2(s, os.path.join(cdir, name))
                elif os.path.isdir(s):
                    shutil.copytree(s, os.path.join(cdir, name),
                                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    atomic_write_json(os.path.join(d, "isolation.json"), proof)
    ledger.append(d, "isolation", "candidates=%d ok=%s" % (len(ids), proof["ok"]),
                  refs={"proof": "isolation.json"})
    run["candidates"] = {cid: {"candidate_id": cid, "run_id": run["run_id"],
                               "strategy_id": None, "prompt_hash": None,
                               "baseline_hash": run.get("baseline_commit"),
                               "workspace_ref": os.path.join("candidates", cid),
                               "isolation_verified": proof["ok"],
                               "status": "PENDING", "eligible": None}
                          for cid in ids}
    save_forge(run)
    _set_phase(run, "PREPARING", "workspaces")'''

content = content[:idx] + new_func + content[next_def:]

with open(r'C:\Users\Marcos\arena-forge\arena_forge.py', 'w') as f:
    f.write(content)

print('Reemplazo completado')
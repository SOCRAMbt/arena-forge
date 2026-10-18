with open(r'C:\Users\Marcos\arena-forge\arena_forge.py', 'r') as f:
    content = f.read()

# Find the function
idx = content.find('def cmd_resume(args):')
if idx < 0:
    print('Function not found')
    exit(1)

# Find the end of the function (next function or end of file)
next_def = content.find('\ndef ', idx + 1)
if next_def < 0:
    next_def = len(content)

old_func = content[idx:next_def]
print('Found function, length:', len(old_func))
print('---START---')
print(old_func[:500])
print('---END---')

# New function
new_func = '''def cmd_resume(args):
    d = run_dir_from(args)
    run = load_forge(d)
    if run.get("phase") == "CANCELLED":
        raise ForgeError("CANCELLED: crea una nueva ejecucion con init")
    ok, problems = ledger.verify(d)
    if not ok:
        print("ledger: %d problema(s) -> se conserva y se registra" % len(problems))
    
    mode = run.get("mode", "answer")
    if mode == "answer":
        before = {}
        arena_path = os.path.join(d, "arena.json")
        if os.path.isfile(arena_path):
            st = _load(arena_path) or {}
            for rd in st.get("rounds", []):
                for m in rd.get("matches", []):
                    if m.get("winner"):
                        before[m["id"]] = m["winner"]
        print("completados persistidos: %d matches con ganador; ledger seq=%s"
              % (len(before), ledger.last_ref(d)))
        r = bracket_cmd("next", "--dir", d)
        print(r.stdout, end="")
        log_event(run, "resume", "%d completados intactos (answer)" % len(before))
    elif mode == "patch":
        # P1-01: Reconciliar jobs Patch desde jobs.json, NO llamar bracket next
        jobs = _load(os.path.join(d, "jobs.json")) or {}
        pending = [j for j in jobs.values() if j.get("state") == "PENDING"]
        running = [j for j in jobs.values() if j.get("state") == "RUNNING"]
        done = [j for j in jobs.values() if j.get("state") == "DONE"]
        failed = [j for j in jobs.values() if j.get("state") == "FAILED"]
        print("resume Patch: pending=%d running=%d done=%d failed=%d"
              % (len(pending), len(running), len(done), len(failed)))
        # Reconciliar: jobs RUNNING sin session_ref son dudosos
        for job in running:
            if not job.get("session_ref"):
                print("  ADVERTENCIA: job %s RUNNING sin session_ref" % job["job_id"])
        log_event(run, "resume", "patch jobs: PENDING=%d RUNNING=%d DONE=%d FAILED=%d"
                  % (len(pending), len(running), len(done), len(failed)))
    else:
        print("modo desconocido: %s" % mode)
        return 1
    return 0'''

content = content[:idx] + new_func + content[next_def:]

with open(r'C:\Users\Marcos\arena-forge\arena_forge.py', 'w') as f:
    f.write(content)

print('Reemplazo completado')
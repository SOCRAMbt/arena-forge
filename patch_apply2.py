with open(r'C:\Users\Marcos\arena-forge\arena_forge.py', 'r') as f:
    content = f.read()

# Find the function
idx = content.find('def cmd_apply(args):')
if idx < 0:
    print('Function not found')
    exit(1)

# Find the end of the function (next function or end of file)
next_def = content.find('\ndef ', idx + 1)
if next_def < 0:
    next_def = len(content)

old_func = content[idx:next_def]
print('Found function, length:', len(old_func))

# New function
new_func = '''def cmd_apply(args):
    d = run_dir_from(args)
    run = load_forge(d)
    if not args.approve:
        raise ForgeError("rehusado: exige --approve explicito y aplica a mano. "
                         "Nada del proyecto fue modificado.")
    # verificar baseline sin cambios (\u00a76.8)
    if run.get("baseline_commit") not in (None, "n/a-no-repo"):
        try:
            cur = subprocess.run(["git", "rev-parse", "HEAD"], text=True,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL).stdout.strip()
            if cur and cur != run["baseline_commit"]:
                raise ForgeError("baseline cambio (%s != %s); revisa antes de aplicar"
                                 % (cur, run["baseline_commit"]))
        except OSError:
            pass
    # P1-03: usar el mismo motor de decision que report (report_mod.resolve)
    data = report_mod.gather(d)
    data["candidates"] = run.get("candidates", {})
    decision, reason, eligible = report_mod.resolve(d, data)
    if decision != "WINNER" or not eligible:
        raise ForgeError("sin campeon: decision=%s, elegibles=%s" % (decision, eligible))
    champ = eligible[0]  # report.resolve ya valida y devuelve un solo ganador
    cdir = os.path.join(d, "candidates", champ)
    base = os.path.join(d, "baseline")
    patch_lines = []
    if os.path.isdir(cdir) and os.path.isdir(base):
        patch_lines = [isolation.capture_diff(base, cdir)]
    elif os.path.isdir(cdir):
        for name in sorted(os.listdir(cdir)):
            p = os.path.join(cdir, name)
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    patch_lines.append("--- /dev/null\n+++ b/%s\n%s" % (name, fh.read()))
    out = os.path.join(REPORTS_DIR, os.path.basename(d) + ".patch")
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("".join(patch_lines) or "# sin diffs (modo answer)\n")
    ledger.append(d, "apply", "parche preparado (sin mutar el proyecto)",
                  refs={"patch": os.path.relpath(out, HERE)}, actor="human")
    print("parche preparado (SOLO archivo, proyecto intacto): %s" % out)
    print("revisa, luego: git apply --check %s" % out)
    return 0'''

content = content[:idx] + new_func + content[next_def:]

with open(r'C:\Users\Marcos\arena-forge\arena_forge.py', 'w') as f:
    f.write(content)

print('Reemplazo completado')
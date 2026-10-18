with open(r'C:\Users\Marcos\arena-forge\arena_forge.py', 'r') as f:
    content = f.read()

old = '''    _set_phase(run, "PREPARING", "workspaces")
def cmd_next(args):'''

new = '''    _set_phase(run, "PREPARING", "workspaces")
    _set_phase(run, "READY", "harness listo")
    print("patch: %d workspaces aislados; aislamiento ok=%s" % (len(ids), proof["ok"]))

def cmd_next(args):'''

if old in content:
    content = content.replace(old, new)
    with open(r'C:\Users\Marcos\arena-forge\arena_forge.py', 'w') as f:
        f.write(content)
    print('Reemplazo OK')
else:
    print('No encontrado')
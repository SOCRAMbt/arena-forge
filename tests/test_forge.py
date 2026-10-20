"""Tests de Arena Forge — mapa a las categorias de la especificacion (§16).

Solo stdlib (unittest). Compatible con pytest y con `python -m unittest`.

REGLAS DE ESTA SUITE
--------------------
* Rutas SIEMPRE derivadas de `Path(__file__).resolve()`: nada de rutas
  absolutas del host. Un checkout en otra maquina o en Linux debe pasar la
  suite igual.
* Los tests NO escriben dentro del repositorio: todo artefacto va a un
  directorio temporal.
* Los manifiestos se CALCULAN en tiempo de ejecucion: no se fijan constantes
  que dependan de los finales de linea del checkout.
* Ningun test afirma un PASS por la mera presencia de codigo: cada afirmacion
  se apoya en un estado observable.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

FORGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FORGE_ROOT)
import arena_forge  # noqa: E402
from arena_forge import ForgeError  # noqa: E402
from forge import (adapter, agent_e, benchmark as bench_mod, contracts,  # noqa: E402
                   gates as gate_engine, integrity, isolation, ledger,
                   report as report_mod, score as score_mod, state)
from forge.util import sha_file, sha_text  # noqa: E402

STRATEGIES = os.path.join(FORGE_ROOT, "vendor", "arena-skill", "strategies.json")
FIX = os.path.join(FORGE_ROOT, "fixtures", "patch-demo")
SUITE = os.path.join(FIX, "tests_protected", "test_protected.py")
SUITE_DIR = os.path.join(FIX, "tests_protected")
GOLD = os.path.join(FIX, "candidate_fixed")
BUGGY = os.path.join(FIX, "baseline_buggy")
AGENTS_DIR = os.path.join(FORGE_ROOT, ".opencode", "agents")
SKILLS_DIR = os.path.join(FORGE_ROOT, ".opencode", "skills")


def has_pytest():
    r = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def ns(**kw):
    return type("NS", (), kw)()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def build_patch_run(root, a001_state="PASS", a002_state="FAIL",
                    judge=None, label_map=None, suite=None):
    """Construye un run de patch REALISTA en `root`.

    Todo se calcula: manifiesto del baseline congelado, manifiesto de cada
    candidato y `diff_sha` real del diff baseline->candidato. asi los tests
    ejercitan las mismas comprobaciones que el runtime real.
    """
    suite = suite or SUITE_DIR
    run_dir = os.path.join(root, "run1")
    os.makedirs(os.path.join(run_dir, "baseline"), exist_ok=True)
    for cid in ("a001", "a002"):
        os.makedirs(os.path.join(run_dir, "candidates", cid), exist_ok=True)
    shutil.copy2(os.path.join(BUGGY, "stats.py"),
                 os.path.join(run_dir, "baseline", "stats.py"))
    shutil.copy2(os.path.join(GOLD, "stats.py"),
                 os.path.join(run_dir, "candidates", "a001", "stats.py"))
    shutil.copy2(os.path.join(BUGGY, "stats.py"),
                 os.path.join(run_dir, "candidates", "a002", "stats.py"))
    base = os.path.join(run_dir, "baseline")
    suite_sha = gate_engine.suite_sha(suite)
    gates = {}
    for cid, st in (("a001", a001_state), ("a002", a002_state)):
        cdir = os.path.join(run_dir, "candidates", cid)
        gates[cid] = {
            "gate_id": "suite:" + cid, "candidate": cid, "state": st,
            "command": "pytest", "tool_version": "pytest", "ts": 1,
            "exit_code": 0 if st == "PASS" else 1,
            "suite_sha": suite_sha,
            "candidate_manifest_sha": isolation.candidate_manifest_sha(cdir),
            "diff_sha": isolation.diff_sha(isolation.capture_diff(base, cdir)),
            "evidence": ["suite_sha=%s" % suite_sha], "failure_class": None,
            "notes": "", "security_mode": isolation.SECURITY_MODE,
            "stdout_ref": None, "stderr_ref": None,
        }
    with open(os.path.join(run_dir, "gates.json"), "w", encoding="utf-8") as fh:
        json.dump(gates, fh)
    with open(os.path.join(run_dir, "isolation.json"), "w", encoding="utf-8") as fh:
        json.dump({"root": "candidates", "shared": False, "ok": True, "problems": [],
                   "candidates": {cid: {"dir": "candidates/" + cid,
                                        "realpath": os.path.join(run_dir, "candidates", cid)}
                                  for cid in ("a001", "a002")}}, fh)
    if judge is not None:
        with open(os.path.join(run_dir, "patch_judge.json"), "w", encoding="utf-8") as fh:
            json.dump(judge, fh)
    if label_map is not None:
        with open(os.path.join(run_dir, "patch_map.json"), "w", encoding="utf-8") as fh:
            json.dump(label_map, fh)
    run = {
        "version": 2, "schema_version": 2, "run_id": "run1", "mode": "patch",
        "status": "EVALUATING", "phase": "EVALUATING", "dir": run_dir,
        "seed": 7, "agents": 2, "task_sha": "t" * 64, "rubric_sha": "r" * 64,
        "cards_sha": "c" * 64, "baseline_commit": "n/a-no-repo",
        "policy_version": agent_e.POLICY_VERSION, "budget": agent_e.budget_for("quick"),
        "events": [], "candidates": {"a001": {}, "a002": {}},
        "suite": suite, "suite_sha": suite_sha,
        "frozen_baseline_manifest": integrity.baseline_manifest(base),
        "frozen_baseline_manifest_version": integrity.BASELINE_MANIFEST_VERSION,
        "calls_spent": 0, "calls_reserved": 0,
    }
    with open(os.path.join(run_dir, "forge.json"), "w", encoding="utf-8") as fh:
        json.dump(run, fh)
    return run_dir


class TempCwd(unittest.TestCase):
    def setUp(self):
        self.prev = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix="forge-test-")
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.prev)
        self.addCleanup(shutil.rmtree, self.tmp, True)


# ------------------------------------------------------- §16.1 reproducible
class SchedulerDeterminismTest(unittest.TestCase):
    def test_sizes_even_odd_and_single_winner(self):
        mod = arena_forge.load_bracket_module()
        data = mod.load_strategies(STRATEGIES)
        self.assertEqual(mod.combo_count(data), 15 * 12 * 12)
        for n in (1, 2, 3, 4, 5, 7, 8, 13, 16, 25, 100):
            sizes = mod.bracket_sizes(n)
            self.assertEqual(sizes[0], n)
            self.assertEqual(sizes[-1], 1)
            for a, b in zip(sizes, sizes[1:]):
                self.assertEqual(b, (a + 1) // 2)
            self.assertTrue(arena_forge.simulate_tournament(mod, n, seed=7)[0], n)

    def test_same_seed_same_deal(self):
        m1 = arena_forge.load_bracket_module()
        m2 = arena_forge.load_bracket_module()
        d1 = m1.deal(8, 7, m1.load_strategies(STRATEGIES))
        d2 = m2.deal(8, 7, m2.load_strategies(STRATEGIES))
        self.assertEqual(sorted(map(tuple, d1)), sorted(map(tuple, d2)))
        self.assertEqual(len(set(d1)), 8)          # sin tarjetas repetidas

    def test_different_seed_differs(self):
        m = arena_forge.load_bracket_module()
        a = m.deal(20, 1, m.load_strategies(STRATEGIES))
        b = m.deal(20, 2, m.load_strategies(STRATEGIES))
        self.assertNotEqual(sorted(map(tuple, a)), sorted(map(tuple, b)))


# --------------------------------------------------------- §16.6 contratos
class ContractsTest(unittest.TestCase):
    def test_run_validation(self):
        good = {"run_id": "r", "schema_version": 2, "mode": "answer",
                "status": "RUNNING", "phase": "RUNNING", "created": 1, "seed": 7,
                "task_sha": "a" * 64, "rubric_sha": "b" * 64, "cards_sha": "c" * 64,
                "budget": {}, "policy_version": "e-policy-v1"}
        self.assertEqual(contracts.validate_run(good), [])
        bad = dict(good); bad.pop("policy_version")
        self.assertTrue(contracts.validate_run(bad))
        bad2 = dict(good); bad2["mode"] = "wrong"
        self.assertTrue(contracts.validate_run(bad2))

    def test_job_and_decision_ranges(self):
        valid_job = {"job_id": "j", "run_id": "r", "phase": "p", "kind": "k",
                     "input_hash": "h", "state": "PENDING", "attempts": 0,
                     "output_expected": "o"}
        self.assertEqual(contracts.validate_job(valid_job), [])
        self.assertTrue(contracts.validate_job(dict(valid_job, state="BLOCKED")))
        self.assertEqual(contracts.validate_decision(
            {"decision_id": "d", "run_id": "r", "state": "NO_SHIP", "reason": "x",
             "ts": 1, "policy_version": "p"}), [])
        self.assertTrue(contracts.validate_decision(
            {"decision_id": "d", "run_id": "r", "state": "WINNER", "reason": "x",
             "ts": 1, "policy_version": "p"}))
        self.assertTrue(contracts.validate_decision(
            {"decision_id": "d", "run_id": "r", "state": "NO_SHIP", "reason": "x",
             "winner": "a", "ts": 1, "policy_version": "p"}))

    def test_gate_and_judge_validation(self):
        self.assertEqual(contracts.validate_gate_result(
            {"gate_id": "g", "candidate": "c", "state": "PASS", "command": "pytest",
             "ts": 1}), [])
        self.assertTrue(contracts.validate_gate_result(
            {"gate_id": "g", "candidate": "c", "state": "OK", "command": "pytest",
             "ts": 1}))
        v = {"winner": "a", "scores": {"a": {"correctness": 11, "completeness": 5,
                                             "specificity": 5, "robustness": 5,
                                             "clarity": 5}}}
        self.assertTrue(contracts.validate_judge_verdict(v, ["a"]))
        v2 = {"winner": "z"}
        self.assertTrue(contracts.validate_judge_verdict(v2, ["a"]))


# ------------------------------------------------------- §16.1/§8 estados
class StateMachineTest(unittest.TestCase):
    def test_legal_and_illegal(self):
        self.assertTrue(state.can_transition("READY", "RUNNING")[0])
        self.assertFalse(state.can_transition("COMPLETED", "RUNNING")[0])
        self.assertFalse(state.can_transition("CREATED", "DECIDING")[0])
        with self.assertRaises(ForgeError):
            state.transition({"phase": "COMPLETED"}, "RUNNING")

    def test_deciding_preconditions(self):
        self.assertFalse(state.can_enter_deciding({}, False, True)[0])
        self.assertFalse(state.can_enter_deciding({"g": {}}, True, False)[0])
        self.assertTrue(state.can_enter_deciding({"g": {}}, True, True)[0])

    def test_terminal_flags(self):
        for s in ("COMPLETED", "NO_SHIP", "CANCELLED", "FAILED"):
            self.assertTrue(state.is_terminal(s))


# ----------------------------------------------------- §16.18/§14 ledger
class LedgerTest(unittest.TestCase):
    def test_append_only_and_verify(self):
        d = tempfile.mkdtemp(prefix="forge-led-")
        self.addCleanup(shutil.rmtree, d, True)
        ledger.append(d, "init", "a")
        ledger.append(d, "phase", "b")
        ledger.append(d, "decision", "c")
        ok, problems = ledger.verify(d)
        self.assertTrue(ok, problems)
        self.assertEqual(len(ledger.read(d)), 3)
        self.assertEqual(ledger.last_ref(d), 3)

    def test_corrupt_line_flag_not_deleted(self):
        d = tempfile.mkdtemp(prefix="forge-led2-")
        self.addCleanup(shutil.rmtree, d, True)
        ledger.append(d, "init", "a")
        with open(os.path.join(d, ledger.LEDGER_FILE), "a", encoding="utf-8") as fh:
            fh.write("{broken json\n")
        ok, problems = ledger.verify(d)
        self.assertFalse(ok)
        self.assertTrue(any("corrupta" in p for p in problems))
        self.assertEqual(len(ledger.read(d)), 2)   # no se borro

    def test_corrupt_line_does_not_break_subsequent_chain(self):
        """Una linea corrupta no debe romper el seq ni el hash-chain posterior."""
        d = tempfile.mkdtemp(prefix="forge-led3-")
        self.addCleanup(shutil.rmtree, d, True)
        ledger.append(d, "init", "a")
        ledger.append(d, "phase", "b")
        with open(os.path.join(d, ledger.LEDGER_FILE), "a", encoding="utf-8") as fh:
            fh.write("{broken\n")
        ledger.append(d, "after", "x")
        seqs = [e["seq"] for e in ledger.read(d)]
        self.assertEqual(seqs, [1, 2, -1, 3])
        ok, problems = ledger.verify(d)
        self.assertFalse(ok)
        self.assertTrue(any("corrupta" in p for p in problems))
        self.assertFalse(any("seq no contiguo" in p for p in problems), problems)
        self.assertFalse(any("prev_hash no coincide" in p for p in problems), problems)

    def test_tampering_is_detected(self):
        d = tempfile.mkdtemp(prefix="forge-led4-")
        self.addCleanup(shutil.rmtree, d, True)
        ledger.append(d, "init", "a")
        ledger.append(d, "phase", "b")
        p = os.path.join(d, ledger.LEDGER_FILE)
        with open(p, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        lines[0] = lines[0].replace('"detail": "a"', '"detail": "TAMPERED"')
        with open(p, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        ok, problems = ledger.verify(d)
        self.assertFalse(ok)
        self.assertTrue(any("event_hash invalido" in pr for pr in problems), problems)


# ------------------------------------------------ §16.8/§16.20 aislamiento
class IsolationTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="forge-iso-")
        os.makedirs(os.path.join(self.d, "candidates"))
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_distinct_workspaces(self):
        proof = isolation.ensure_workspaces(self.d, ["cand-a", "cand-b"])
        self.assertTrue(proof["ok"])
        self.assertFalse(proof["shared"])
        self.assertNotEqual(proof["candidates"]["cand-a"]["realpath"],
                            proof["candidates"]["cand-b"]["realpath"])

    def test_duplicate_ids_detected(self):
        proof = isolation.ensure_workspaces(self.d, ["cand-a", "cand-a"])
        self.assertFalse(proof["ok"])
        self.assertTrue(proof["shared"])

    def test_diff_traversal_rejected(self):
        ok, problems = isolation.validate_diff("--- a/../../etc/passwd\n+++ b/x\n")
        self.assertFalse(ok)
        self.assertTrue(problems)
        ok2, _ = isolation.validate_diff("--- a/stats.py\n+++ b/stats.py\n+x\n")
        self.assertTrue(ok2)

    def test_diff_git_header_traversal_rejected(self):
        """La cabecera `diff --git` tambien debe validarse (no solo ---/+++)."""
        ok, problems = isolation.validate_diff(
            b"diff --git a/../../evil b/../../evil\nGIT binary patch\nliteral 3\nAAEC\n")
        self.assertFalse(ok)
        self.assertTrue(problems)

    def test_absolute_windows_path_rejected(self):
        ok, problems = isolation.validate_diff(
            b"diff --git a/C:\\evil\\x.py b/C:\\evil\\x.py\n")
        self.assertFalse(ok)
        self.assertTrue(problems)

    def test_unsafe_symlink_blocks_manifest(self):
        """Un symlink que escapa del arbol hace FALLAR el manifiesto (no se omite)."""
        cand = os.path.join(self.d, "cand")
        os.makedirs(cand, exist_ok=True)
        outside = os.path.join(self.d, "outside.txt")
        write(outside, "secret\n")
        link = os.path.join(cand, "leak.txt")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks no soportados en esta plataforma")
        files, problems = isolation.walk_files_checked(cand)
        self.assertTrue(problems, "un symlink externo debe reportarse")
        with self.assertRaises(ForgeError):
            isolation.candidate_manifest_sha(cand)

    def test_broken_symlink_is_reported(self):
        cand = os.path.join(self.d, "cand2")
        os.makedirs(cand, exist_ok=True)
        link = os.path.join(cand, "roto.txt")
        try:
            os.symlink(os.path.join(self.d, "no-existe"), link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks no soportados en esta plataforma")
        _files, problems = isolation.walk_files_checked(cand)
        self.assertTrue(any("symlink roto" in p for p in problems), problems)

    def test_manifest_includes_mode(self):
        cand = os.path.join(self.d, "cand3")
        os.makedirs(cand, exist_ok=True)
        write(os.path.join(cand, "a.txt"), "x\n")
        sha_a = isolation.candidate_manifest_sha(cand)
        os.chmod(os.path.join(cand, "a.txt"), 0o600)
        sha_b = isolation.candidate_manifest_sha(cand)
        if os.name == "nt":
            # En Windows el bit de ejecucion no es representable: el skip es
            # EXPLICITO (no un `if` que deja el test sin asercion).
            self.skipTest("Windows no representa el bit de modo POSIX")
        self.assertNotEqual(sha_a, sha_b, "el modo debe entrar en el manifiesto")

    def test_ensure_workspaces_does_not_create_outside_the_run(self):
        """El id se valida ANTES de crear: nada se crea fuera del run."""
        escape = os.path.join(os.path.dirname(self.d), "escape-dir")
        proof = isolation.ensure_workspaces(self.d, ["..\\..\\escape-dir"])
        self.assertFalse(proof["ok"])
        self.assertFalse(os.path.exists(escape),
                         "no debe crearse nada fuera del run")

    def test_redact_covers_common_secret_formats(self):
        """Las muestras se CONSTRUYEN en runtime.

        Literales de secretos en el repositorio los marca la proteccion de
        push de GitHub (secret scanning) y bloquean el push. Aqui no hay
        ningun secreto real: son cadenas sinteticas.
        """
        from forge.util import redact
        def build(prefix, *groups):
            return prefix + "-" + "-".join(groups)
        secrets = [
            "aws_secret_access_key = " + "wJalrXUtnFEMIK7MDENGbPxRfiCY",
            "postgresql://svc:hunter2@db.internal:5432/app",
            build("xoxb", "123456789012", "1234567890123",
                  "abcdefghijklmnop"),
            "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789",
            "api_key: sk-" + "abcdefghijklmnopqrstuvwxyz0123456789",
            "password = super-secreto",
            "Authorization: Bearer " + "abcdefghijklmnopqrstuvwxyz012345",
            "-----BEGIN RSA PRIVATE KEY-----x-----END RSA PRIVATE KEY-----",
            # Claves de proveedores LLM y cloud (el caso realista en un
            # runtime de agentes).
            "sk-ant-api03-" + "A" * 40,
            "sk-proj-" + "b" * 40,
            "AIza" + "c" * 35,
            "sk_live_" + "d" * 24,
            "npm_" + "e" * 36,
            "SG." + "f" * 22 + "." + "g" * 22,
            "AccountKey=" + "h" * 40,
            "Authorization: Basic " + "YWRtaW46c3VwZXJz" + "=" * 12,
            "https://hooks.slack.com/services/" + "T" * 12 + "/" + "B" * 24,
        ]
        for s in secrets:
            self.assertNotEqual(redact(s), s, "secreto sin redactar: %s" % s[:30])


# --------------------------------------------- §16 P0-1 parche canonico
class BinaryPatchTest(unittest.TestCase):
    """El parche debe ser un parche GIT real y byte-exacto."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="forge-bin-")
        self.base = os.path.join(self.d, "baseline")
        self.cand = os.path.join(self.d, "candidate")
        os.makedirs(self.base)
        os.makedirs(self.cand)
        self.addCleanup(shutil.rmtree, self.d, True)

    def _write(self, root, rel, data):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(p, mode) as fh:
            fh.write(data)
        return p

    def _tree(self, root):
        out = {}
        for dirpath, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for n in names:
                ap = os.path.join(dirpath, n)
                rel = os.path.relpath(ap, root).replace("\\", "/")
                with open(ap, "rb") as fh:
                    out[rel] = fh.read()
        return out

    def test_patch_is_a_real_git_patch(self):
        self._write(self.base, "a.py", b"print(1)\n")
        self._write(self.cand, "a.py", b"print(2)\n")
        diff = isolation.capture_diff(self.base, self.cand)
        self.assertIn(b"diff --git a/a.py b/a.py", diff)
        self.assertIn(b"--- a/a.py", diff)

    def test_text_roundtrip_is_byte_exact(self):
        self._write(self.base, "a.py", b"print(1)\n")
        self._write(self.cand, "a.py", b"print(2)\n")
        diff = isolation.capture_diff(self.base, self.cand)
        scratch = isolation.apply_diff_to_temp(diff, self.base)
        self.addCleanup(shutil.rmtree, scratch, True)
        self.assertEqual(self._tree(scratch), self._tree(self.cand))

    def test_binary_with_nul_roundtrip_is_byte_exact(self):
        self._write(self.base, "d.bin", bytes([0, 1, 2, 3, 4, 5]))
        self._write(self.cand, "d.bin", bytes([0, 1, 2, 3, 4, 6]))
        diff = isolation.capture_diff(self.base, self.cand)
        self.assertIn(b"GIT binary patch", diff)
        scratch = isolation.apply_diff_to_temp(diff, self.base)
        self.addCleanup(shutil.rmtree, scratch, True)
        self.assertEqual(self._tree(scratch), self._tree(self.cand))

    def test_binary_without_nul_in_first_8192_is_not_text(self):
        """Un binario sin NUL en los primeros 8192 bytes NO debe clasificarse
        como texto (ni corromperse)."""
        data = bytes(range(1, 256)) * 40 + b"\x00\x01"
        self._write(self.base, "big.bin", data)
        self._write(self.cand, "big.bin", data[:-2] + b"\xff")
        diff = isolation.capture_diff(self.base, self.cand)
        scratch = isolation.apply_diff_to_temp(diff, self.base)
        self.addCleanup(shutil.rmtree, scratch, True)
        self.assertEqual(self._tree(scratch), self._tree(self.cand))

    def test_invalid_utf8_bytes_survive_roundtrip(self):
        data = b"\xff\xfe\x80\x81 not utf8 \xc3\x28"
        self._write(self.base, "x.dat", data)
        self._write(self.cand, "x.dat", data + b"\x00\x99")
        diff = isolation.capture_diff(self.base, self.cand)
        scratch = isolation.apply_diff_to_temp(diff, self.base)
        self.addCleanup(shutil.rmtree, scratch, True)
        self.assertEqual(self._tree(scratch), self._tree(self.cand))

    def test_added_binary_file_appears(self):
        self._write(self.base, "keep.py", "x = 1\n")
        self._write(self.cand, "keep.py", "x = 1\n")
        self._write(self.cand, "new.bin", bytes([0, 9, 9]))
        diff = isolation.capture_diff(self.base, self.cand)
        scratch = isolation.apply_diff_to_temp(diff, self.base)
        self.addCleanup(shutil.rmtree, scratch, True)
        self.assertEqual(self._tree(scratch), self._tree(self.cand))

    def test_deleted_binary_file_is_removed(self):
        self._write(self.base, "gone.bin", bytes([0, 9, 9]))
        self._write(self.cand, "other.py", "y = 2\n")
        diff = isolation.capture_diff(self.base, self.cand)
        scratch = isolation.apply_diff_to_temp(diff, self.base)
        self.addCleanup(shutil.rmtree, scratch, True)
        self.assertFalse(os.path.exists(os.path.join(scratch, "gone.bin")))
        self.assertEqual(self._tree(scratch), self._tree(self.cand))

    def test_mixed_diff_keeps_the_text_hunk(self):
        """Un diff con un binario Y un texto debe aplicar AMBOS."""
        self._write(self.base, "a.py", b"print(1)\n")
        self._write(self.base, "d.bin", bytes([0, 1, 2]))
        self._write(self.cand, "a.py", b"print(2)\n")
        self._write(self.cand, "d.bin", bytes([0, 1, 3]))
        diff = isolation.capture_diff(self.base, self.cand)
        scratch = isolation.apply_diff_to_temp(diff, self.base)
        self.addCleanup(shutil.rmtree, scratch, True)
        tree = self._tree(scratch)
        self.assertEqual(tree["a.py"], b"print(2)\n")
        self.assertEqual(tree["d.bin"], bytes([0, 1, 3]))

    def test_capture_diff_is_not_empty_when_mtimes_share_a_second(self):
        """El stat cache de git (mtime con granularidad de 1s) no puede
        hacer que el parche salga vacio."""
        self._write(self.base, "m.py", b"a = 1\n")
        self._write(self.cand, "m.py", b"a = 2\n")
        diff = isolation.capture_diff(self.base, self.cand)
        self.assertNotEqual(diff, b"", "el parche no puede salir vacio")
        self.assertIn(b"m.py", diff)

    def test_git_apply_check_accepts_generated_patch(self):
        self._write(self.base, "a.py", b"print(1)\n")
        self._write(self.cand, "a.py", b"print(2)\n")
        diff = isolation.capture_diff(self.base, self.cand)
        repo = os.path.join(self.d, "repo")
        os.makedirs(repo, exist_ok=True)
        self._write(repo, "a.py", b"print(1)\n")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        patch = os.path.join(self.d, "p.patch")
        with open(patch, "wb") as fh:
            fh.write(diff)
        r = subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--check",
                            patch], cwd=repo, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))

    def test_traversal_patch_is_rejected_and_writes_nothing_outside(self):
        evil = os.path.join(self.d, "evil.txt")
        payload = ("diff --git a/../evil.txt b/../evil.txt\n"
                   "--- a/../evil.txt\n+++ b/../evil.txt\n@@ -0,0 +1 @@\n+PWNED\n")
        ok, problems = isolation.validate_diff(payload.encode("utf-8"))
        self.assertFalse(ok)
        with self.assertRaises(ForgeError):
            isolation.apply_diff_to_temp(payload.encode("utf-8"), self.base)
        self.assertFalse(os.path.exists(evil))

    def test_diff_sha_is_over_the_exact_bytes(self):
        import hashlib
        self._write(self.base, "a.py", b"print(1)\n")
        self._write(self.cand, "a.py", b"print(2)\n")
        diff = isolation.capture_diff(self.base, self.cand)
        self.assertEqual(isolation.diff_sha(diff), hashlib.sha256(diff).hexdigest())
        # Atado a un parche REAL, no a la definicion de la funcion.
        self.assertIn(b"diff --git a/a.py b/a.py", diff)
        self.assertNotEqual(isolation.diff_sha(diff), isolation.diff_sha(b"otro"))
        # Sin normalizacion de finales de linea.
        self.assertNotEqual(isolation.diff_sha(b"a\r\n"),
                            isolation.diff_sha(b"a\n"))

    def test_capture_diff_refuses_symlinked_candidate(self):
        self._write(self.base, "a.py", b"print(1)\n")
        outside = os.path.join(self.d, "outside.py")
        write(outside, "x\n")
        link = os.path.join(self.cand, "leak.py")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks no soportados en esta plataforma")
        with self.assertRaises(ForgeError):
            isolation.capture_diff(self.base, self.cand)

    def test_persisted_binary_fixture_roundtrip(self):
        """Round-trip con el fixture binario VERSIONADO en el repo.

        Asi el round-trip binario es reproducible desde un checkout limpio, sin
        depender de ficheros generados en tiempo de ejecucion.
        """
        fixture = os.path.join(FORGE_ROOT, "fixtures", "patch-demo", "binary",
                               "sample.bin")
        self.assertTrue(os.path.isfile(fixture), "falta el fixture binario")
        with open(fixture, "rb") as fh:
            original = fh.read()
        self.assertIn(b"\x00", original, "el fixture debe contener NUL")
        # El fixture NO es UTF-8 valido: debe clasificarse como binario.
        self.assertTrue(isolation._is_binary_file(fixture))
        self._write(self.base, "sample.bin", original)
        self._write(self.cand, "sample.bin", original + b"\x00\x2a")
        diff = isolation.capture_diff(self.base, self.cand)
        self.assertIn(b"GIT binary patch", diff)
        scratch = isolation.apply_diff_to_temp(diff, self.base)
        self.addCleanup(shutil.rmtree, scratch, True)
        with open(os.path.join(scratch, "sample.bin"), "rb") as fh:
            self.assertEqual(fh.read(), original + b"\x00\x2a")


# --------------------------------------- Evidencia de auditoria versionada
class AuditArtifactsTest(unittest.TestCase):
    """La evidencia empaquetada en `reports/audit/artifacts/` debe cuadrar.

    Es lo que permite a un tercero verificar la cadena de decision sin
    ejecutar el E2E.
    """
    ART = os.path.join(FORGE_ROOT, "reports", "audit", "artifacts")

    def test_artifacts_are_present(self):
        for name in ("gates.json", "decision.json", "isolation.json",
                     "ledger.jsonl", "SHA256SUMS.txt"):
            self.assertTrue(os.path.isfile(os.path.join(self.ART, name)),
                            "falta el artefacto %s" % name)
        patches = [f for f in os.listdir(self.ART) if f.endswith(".patch")]
        self.assertEqual(len(patches), 1, "debe haber exactamente un parche")

    def test_packaged_evidence_hash_chain_is_consistent(self):
        """sha256(parche) == diff_sha del gate == diff_sha de la decision."""
        with open(os.path.join(self.ART, "gates.json"), encoding="utf-8") as fh:
            gates = json.load(fh)
        with open(os.path.join(self.ART, "decision.json"), encoding="utf-8") as fh:
            decision = json.load(fh)
        winner = decision.get("winner_id")
        self.assertTrue(winner, "la decision debe tener ganador")
        patch = [os.path.join(self.ART, f) for f in os.listdir(self.ART)
                 if f.endswith(".patch")][0]
        patch_sha = sha_file(patch)
        self.assertEqual(patch_sha, gates[winner]["diff_sha"])
        self.assertEqual(patch_sha, decision["diff_sha"])

    def test_packaged_evidence_checksums_match(self):
        """Los hashes del manifiesto se calculan sobre el contenido NORMALIZADO
        a LF (igual que lo que git versiona), para que el manifiesto sea
        valido en cualquier checkout y en cualquier plataforma."""
        from forge.util import sha256_normalized
        with open(os.path.join(self.ART, "SHA256SUMS.txt"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                digest, name = line.split("  ", 1)
                if name == "fixture_binary_sha256":
                    path = os.path.join(FORGE_ROOT, "fixtures", "patch-demo",
                                        "binary", "sample.bin")
                else:
                    path = os.path.join(self.ART, name)
                self.assertTrue(os.path.isfile(path), "falta %s" % name)
                self.assertEqual(sha256_normalized(path), digest,
                                 "sha256 no coincide: %s" % name)

    def test_packaged_artifacts_are_line_ending_stable(self):
        """Los artefactos de texto versionados no deben depender de la
        plataforma: se escriben con LF en Windows y en POSIX."""
        for name in ("decision.json", "gates.json", "isolation.json",
                     "ledger.jsonl"):
            p = os.path.join(self.ART, name)
            with open(p, "rb") as fh:
                data = fh.read()
            self.assertNotIn(b"\r\n", data,
                             "%s contiene CRLF: el hash no seria estable" % name)

    def test_packaged_patch_applies_to_a_clean_baseline(self):
        """El parche versionado aplica sobre el baseline del fixture."""
        patch = [os.path.join(self.ART, f) for f in os.listdir(self.ART)
                 if f.endswith(".patch")][0]
        tmp = tempfile.mkdtemp(prefix="forge-artifact-")
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy2(os.path.join(BUGGY, "stats.py"),
                     os.path.join(tmp, "stats.py"))
        r = subprocess.run(["git", "-c", "core.autocrlf=false", "-c",
                            "core.eol=lf", "apply", "--check", patch],
                           cwd=tmp, capture_output=True)
        self.assertEqual(r.returncode, 0,
                         r.stderr.decode("utf-8", "replace"))


# ---------------------------------------- La matriz no puede desincronizarse
class AcceptanceMatrixTest(unittest.TestCase):
    """La matriz de aceptacion se GENERA desde acceptance-data.json.

    Si el .md y los datos se desincronizan, la auditoria miente: este test lo
    detecta (el defecto real que encontro la revision de documentacion).
    """
    AUD = os.path.join(FORGE_ROOT, "reports", "audit")

    def test_matrix_markdown_matches_the_data(self):
        sys.path.insert(0, self.AUD)
        import compute_acceptance as ca
        data = ca.load()
        with open(ca.MATRIX, encoding="utf-8") as fh:
            actual = fh.read()
        self.assertEqual(ca.render(data), actual,
                         "acceptance-matrix.md esta desincronizado: regenerar "
                         "con `python reports/audit/compute_acceptance.py --write`")

    def test_every_criterion_has_a_state_and_evidence(self):
        sys.path.insert(0, self.AUD)
        import compute_acceptance as ca
        data = ca.load()
        ids = [c["id"] for c in data["criteria"]]
        self.assertEqual(len(ids), 18, "deben ser 18 criterios")
        self.assertEqual(len(set(ids)), 18, "ids duplicados")
        for c in data["criteria"]:
            self.assertIn(c["state"], ca.ORDER, "%s: estado invalido" % c["id"])
            self.assertTrue(c["evidence"].strip(), "%s: sin evidencia" % c["id"])
            self.assertTrue(c["text"].strip(), "%s: sin texto de criterio" % c["id"])

    def test_every_traceability_row_points_at_something(self):
        sys.path.insert(0, self.AUD)
        import compute_acceptance as ca
        data = ca.load()
        self.assertTrue(data.get("traceability"), "falta la matriz de trazabilidad")
        for t in data["traceability"]:
            self.assertTrue(t["evidence"].strip(), "%s: sin evidencia" % t["id"])

    def test_contract_is_versioned_in_the_repo(self):
        contract = os.path.join(FORGE_ROOT, "docs", "contract",
                                "ARENA_FORGE_ESPECIFICACION_TECNICA_INTEGRAL.md")
        self.assertTrue(os.path.isfile(contract),
                        "el contrato debe estar versionado para que la "
                        "auditoria sea reproducible")
        self.assertGreater(os.path.getsize(contract), 10000)


# ------------------------------------------- §16.7/§16.9/§16.19 gates
class GatesTest(unittest.TestCase):
    @unittest.skipUnless(has_pytest(), "pytest no instalado")
    def test_buggy_fails_gold_passes(self):
        gb = gate_engine.run_gate(BUGGY, SUITE)
        gf = gate_engine.run_gate(GOLD, SUITE)
        self.assertEqual(gb["state"], "FAIL")
        self.assertEqual(gf["state"], "PASS")
        self.assertEqual(gb["failure_class"], "required_check_failed")
        self.assertEqual(gb["suite_sha"], gf["suite_sha"])

    @unittest.skipUnless(has_pytest(), "pytest no instalado")
    def test_injection_readme_inert(self):
        tmp = tempfile.mkdtemp(prefix="forge-inj-")
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy2(os.path.join(GOLD, "stats.py"), tmp)
        shutil.copy2(os.path.join(FORGE_ROOT, "fixtures", "injection-test",
                                  "README_EVIL.md"), tmp)
        self.assertEqual(gate_engine.run_gate(tmp, SUITE)["state"], "PASS")

    @unittest.skipUnless(has_pytest(), "pytest no instalado")
    def test_harness_tampering_blocked(self):
        tmp = tempfile.mkdtemp(prefix="forge-tamper-")
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy2(os.path.join(GOLD, "stats.py"), tmp)
        write(os.path.join(tmp, "tests_protected_evil.py"), "def test_x(): pass\n")
        g = gate_engine.run_gate(tmp, SUITE)
        self.assertEqual(g["state"], "BLOCKED")
        self.assertEqual(g["failure_class"], "harness_tampering")

    @unittest.skipUnless(has_pytest(), "pytest no instalado")
    def test_nested_conftest_in_candidate_is_rejected(self):
        """Un conftest.py en un SUBDIRECTORIO tambien lo carga pytest."""
        tmp = tempfile.mkdtemp(prefix="forge-tamper2-")
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy2(os.path.join(GOLD, "stats.py"), tmp)
        write(os.path.join(tmp, "sub", "conftest.py"), "def pytest_collection_modifyitems():\n    pass\n")
        g = gate_engine.run_gate(tmp, SUITE)
        self.assertEqual(g["state"], "BLOCKED")
        self.assertEqual(g["failure_class"], "harness_tampering")

    def test_not_run_when_suite_missing(self):
        g = gate_engine.run_gate(GOLD, os.path.join(FIX, "nope.py"))
        self.assertEqual(g["state"], "NOT_RUN")
        self.assertEqual(g["failure_class"], "environment_broken")

    @unittest.skipUnless(has_pytest(), "pytest no instalado")
    def test_gate_blocks_when_suite_hash_changed(self):
        g = gate_engine.run_gate(GOLD, SUITE, expected_suite_sha="0" * 64)
        self.assertEqual(g["state"], "BLOCKED")
        self.assertEqual(g["failure_class"], "suite_hash_mismatch")

    def test_gate_declares_security_mode(self):
        g = gate_engine.run_gate(GOLD, SUITE)
        self.assertEqual(g["security_mode"], "TRUSTED_CODE_ONLY")

    def test_suite_sha_covers_pytest_config_files(self):
        """Alterar el conftest.py de la suite debe cambiar el hash de la suite."""
        tmp = tempfile.mkdtemp(prefix="forge-suite-")
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy2(SUITE, os.path.join(tmp, "test_x.py"))
        before = gate_engine.suite_sha(tmp)
        write(os.path.join(tmp, "conftest.py"), "# v1\n")
        mid = gate_engine.suite_sha(tmp)
        write(os.path.join(tmp, "conftest.py"), "# v2\n")
        after = gate_engine.suite_sha(tmp)
        self.assertNotEqual(before, mid)
        self.assertNotEqual(mid, after)

    def test_minimal_env_has_no_user_site_and_no_plugin_autoload(self):
        scratch = tempfile.mkdtemp(prefix="forge-env-")
        self.addCleanup(shutil.rmtree, scratch, True)
        env, user_site_exposed = gate_engine._minimal_env(scratch)
        self.assertEqual(env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"], "1")
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertNotIn("SECRET", env)
        if not user_site_exposed:
            import site
            self.assertNotIn(site.getusersitepackages(), env["PYTHONPATH"])

    def test_suite_inside_candidate_workspace_is_detected(self):
        root = tempfile.mkdtemp(prefix="forge-suitews-")
        self.addCleanup(shutil.rmtree, root, True)
        cdir = os.path.join(root, "candidates", "cand-01")
        os.makedirs(cdir)
        suite = os.path.join(cdir, "tests")
        os.makedirs(suite)
        write(os.path.join(suite, "test_x.py"), "def test_x(): pass\n")
        self.assertFalse(gate_engine.suite_is_outside_workspaces(suite, root))

    @unittest.skipUnless(has_pytest(), "pytest no instalado")
    def test_gate_rejects_candidate_forced_exit_zero(self):
        """Un candidato que mata al interprete durante el import NO puede
        quedarse con un PASS: el gate exige el INFORME de la suite."""
        tmp = tempfile.mkdtemp(prefix="forge-forge-")
        self.addCleanup(shutil.rmtree, tmp, True)
        # La suite importa el modulo del candidato; el modulo mata pytest.
        suite_dir = os.path.join(tmp, "suite")
        os.makedirs(suite_dir)
        write(os.path.join(suite_dir, "test_x.py"),
              "import evilmod\n\n\ndef test_must_fail():\n    assert False, 'boom'\n")
        cand = os.path.join(tmp, "cand")
        os.makedirs(cand)
        write(os.path.join(cand, "evilmod.py"),
              "import os\nos._exit(0)\n")
        g = gate_engine.run_gate(cand, os.path.join(suite_dir, "test_x.py"))
        self.assertNotEqual(g["state"], "PASS",
                            "un candidato no puede fabricar un PASS: %s" % g)
        self.assertEqual(g["exit_code"], 0,
                         "el candidato debe forzar la salida con codigo 0")
        self.assertEqual(g["failure_class"], "gate_session_incomplete")
        self.assertFalse(g.get("session_completed", True),
                         "pytest no debe haber terminado la sesion de forma normal")
        # CONTROL: la misma suite SIN el exit-0 debe fallar por el requisito,
        # no por el mecanismo del informe ausente.
        control = tempfile.mkdtemp(prefix="forge-forge-ctl-")
        self.addCleanup(shutil.rmtree, control, True)
        shutil.copy2(os.path.join(GOLD, "stats.py"), control)
        ctl_suite = os.path.join(control, "test_ctl.py")
        write(ctl_suite, "import stats\n\n\ndef test_must_fail():\n    assert False, 'boom'\n")
        g2 = gate_engine.run_gate(control, ctl_suite)
        self.assertEqual(g2["state"], "FAIL")
        self.assertEqual(g2["failure_class"], "required_check_failed")

    def test_environment_error_is_not_reported_as_candidate_failure(self):
        """Un fallo del ENTORNO no puede atribuirse al candidato."""
        out = "ModuleNotFoundError: No module named 'pytest'"
        self.assertTrue(gate_engine._looks_like_environment_break(out))
        self.assertFalse(gate_engine._looks_like_environment_break(
            "1 failed, 3 passed"))


# -------------------------------------------------- §16.7 score/gates
class ScoreTest(unittest.TestCase):
    def test_dimension_total(self):
        full = {k: 10 for k in score_mod.PATCH_WEIGHTS}
        self.assertEqual(score_mod.dimension_score(full), 100.0)
        # Rango: con TODAS las dimensiones presentes pero una fuera de rango,
        # el error debe ser el de RANGO (no el de dimension ausente).
        out_of_range = {k: 5 for k in score_mod.PATCH_WEIGHTS}
        out_of_range["correctness"] = 11
        with self.assertRaises(ForgeError) as cm:
            score_mod.dimension_score(out_of_range)
        self.assertIn("fuera de rango", str(cm.exception))
        # Dimension ausente: error distinto.
        with self.assertRaises(ForgeError) as cm2:
            score_mod.dimension_score({"correctness": 5})
        self.assertIn("ausente", str(cm2.exception))

    def test_evidence_required(self):
        with self.assertRaises(ForgeError):
            score_mod.require_evidence({"winner": "X"})

    def test_gate_binds_judge(self):
        v = {"winner": "Y", "evidence": ["x.py:1"]}
        cand, info = score_mod.evaluate_patch_judgement(
            v, ["cand-a"], {"X": "cand-a", "Y": "cand-b"})
        self.assertIsNone(cand)          # Y no elegible
        v2 = {"winner": "X", "evidence": ["x.py:1"]}
        cand2, _ = score_mod.evaluate_patch_judgement(
            v2, ["cand-a"], {"X": "cand-a", "Y": "cand-b"})
        self.assertEqual(cand2, "cand-a")


# ------------------------------------------------------ §16.14/§16.15 E
class AgentETest(unittest.TestCase):
    def _run(self, d, **over):
        run = {"run_id": "r1", "mode": "patch", "phase": "EVALUATING",
               "budget": agent_e.budget_for("standard"), "calls_spent": 0,
               "calls_reserved": 0, "schema_version": 2, "approvals": [],
               "dir": d}
        run.update(over)
        return run

    def _write_run(self, d, run):
        with open(os.path.join(d, "forge.json"), "w", encoding="utf-8") as fh:
            json.dump(run, fh)

    def test_decision_validates_and_persists(self):
        d = tempfile.mkdtemp(prefix="forge-e-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d)
        self._write_run(d, run)
        dec = agent_e.step(d, run)
        self.assertEqual(agent_e.validate_decision(dec), [])
        self.assertTrue(os.path.isfile(os.path.join(d, agent_e.DECISIONS_FILE)))
        self.assertEqual(len(agent_e.history(d)), 1)

    def test_no_ship_when_no_eligible(self):
        d = tempfile.mkdtemp(prefix="forge-e2-")
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, "gates.json"), "w") as fh:
            json.dump({"cand-a": {"state": "FAIL"}}, fh)
        dec = agent_e.propose(d, self._run(d))
        self.assertEqual(dec["action_type"], "recommend_no_ship")

    def test_budget_over_rejected(self):
        d = tempfile.mkdtemp(prefix="forge-e3-")
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, "gates.json"), "w") as fh:
            json.dump({"cand-a": {"state": "PASS"}}, fh)
        run = self._run(d, calls_spent=999)
        dec = agent_e.propose(d, run)
        self.assertEqual(dec["action_type"], "stop")

    def test_illegal_decision_rejected(self):
        d = tempfile.mkdtemp(prefix="forge-e4-")
        self.addCleanup(shutil.rmtree, d, True)
        bad = {"decision_id": "x", "run_id": "r", "observed_state_version": 1,
               "action_type": "nuke", "target_ids": [], "reason": "r",
               "evidence_refs": [], "cost_estimate": {}, "budget_remaining": {},
               "risk_level": "low", "preconditions": [], "stop_conditions": [],
               "timestamp": 1, "policy_version": "p",
               "requires_human_approval": False, "execution_state": "proposed"}
        self.assertTrue(agent_e.validate_decision(bad))
        with self.assertRaises(ForgeError):
            agent_e.persist(d, bad)

    def test_unknown_decision_field_rejected(self):
        d = tempfile.mkdtemp(prefix="forge-e5-")
        self.addCleanup(shutil.rmtree, d, True)
        dec = {"decision_id": "x", "run_id": "r", "observed_state_version": 1,
               "action_type": "stop", "target_ids": [], "reason": "r",
               "evidence_refs": [], "cost_estimate": {"calls": 0},
               "budget_remaining": {"calls": 10}, "risk_level": "low",
               "preconditions": [], "stop_conditions": [], "timestamp": 1,
               "policy_version": "p", "requires_human_approval": False,
               "execution_state": "proposed", "executed_by": None,
               "session_ref": None, "output_ref": None, "campo_inventado": 1}
        errs = agent_e.validate_decision(dec)
        self.assertTrue(any("campos desconocidos" in e for e in errs), errs)

    def test_human_approval_required_blocks_execution(self):
        """Sin registro de aprobacion ligado, la decision NO se ejecuta."""
        d = tempfile.mkdtemp(prefix="forge-e6-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d)
        self._write_run(d, run)
        dec = agent_e._mk_decision(run, agent_e.context(d, run), "apply_budget",
                                   "pedir presupuesto", [], ["ledger"], 5, "high")
        self.assertTrue(dec["requires_human_approval"])
        ok, out = agent_e.execute_decision(d, dec, run)
        self.assertFalse(ok)
        self.assertEqual(out["execution_state"], "awaiting_approval")

    def test_human_approval_must_bind_the_decision(self):
        d = tempfile.mkdtemp(prefix="forge-e7-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d)
        self._write_run(d, run)
        dec = agent_e._mk_decision(run, agent_e.context(d, run), "apply_budget",
                                   "pedir presupuesto", ["cand-a"], ["ledger"], 5, "high")
        # Aprobacion que NO corresponde a esta decision.
        run["approvals"] = [{"decision_id": "otra", "run_id": "r1",
                             "action_type": "apply_budget", "target_ids": ["cand-a"],
                             "cost_calls": 5, "policy_version": dec["policy_version"]}]
        ok, out = agent_e.execute_decision(d, dec, run)
        self.assertFalse(ok)
        self.assertEqual(out["execution_state"], "awaiting_approval")

    def test_human_approval_valid_allows_execution(self):
        d = tempfile.mkdtemp(prefix="forge-e8-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d)
        self._write_run(d, run)
        dec = agent_e._mk_decision(run, agent_e.context(d, run), "apply_budget",
                                   "pedir presupuesto", ["cand-a"], ["ledger"], 0, "high")
        run["approvals"] = [{"decision_id": dec["decision_id"], "run_id": "r1",
                             "action_type": "apply_budget", "target_ids": ["cand-a"],
                             "cost_calls": 0, "policy_version": dec["policy_version"],
                             "approved_by": "tester"}]
        ok, out = agent_e.execute_decision(d, dec, run)
        self.assertNotEqual(out["execution_state"], "awaiting_approval")

    def test_request_evidence_cannot_succeed_without_evidence(self):
        d = tempfile.mkdtemp(prefix="forge-e9-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d)
        self._write_run(d, run)
        dec = agent_e._mk_decision(run, agent_e.context(d, run), "request_evidence",
                                   "pedir evidencia", [], [], 1, "medium")
        ok, out = agent_e.execute_decision(d, dec, run)
        self.assertFalse(ok)
        self.assertEqual(out["execution_state"], "awaiting_evidence")

    def test_launch_phase_does_not_report_success_without_started_work(self):
        d = tempfile.mkdtemp(prefix="forge-e10-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d, mode="patch", phase="READY",
                        candidates={"cand-01": {"status": "PENDING"},
                                    "cand-02": {"status": "PENDING"}})
        self._write_run(d, run)
        dec = agent_e.propose(d, run)
        ok, out = agent_e.execute_decision(d, dec, run)
        self.assertFalse(ok)
        self.assertNotEqual(out["execution_state"], "succeeded")

    def test_budget_is_reserved_before_the_job_is_created(self):
        d = tempfile.mkdtemp(prefix="forge-e11-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d, budget=agent_e.budget_for("quick"))
        self._write_run(d, run)
        job, created = agent_e._register_job(d, "job-x", "implement", ["c"],
                                              "implement", budget_calls=1)
        self.assertTrue(created)
        with open(os.path.join(d, "forge.json"), encoding="utf-8") as fh:
            after = json.load(fh)
        self.assertEqual(after["calls_reserved"], 1)
        self.assertEqual(after["calls_spent"], 0)

    def test_two_jobs_cannot_exceed_the_remaining_budget(self):
        """Presupuesto de 1 llamada, dos jobs: el segundo debe fallar."""
        d = tempfile.mkdtemp(prefix="forge-e12-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d, budget={"max_calls": 1, "max_candidates": 4})
        self._write_run(d, run)
        agent_e._register_job(d, "job-1", "implement", ["a"], "implement", budget_calls=1)
        with self.assertRaises(ForgeError):
            agent_e._register_job(d, "job-2", "implement", ["b"], "implement",
                                  budget_calls=1)
        with open(os.path.join(d, "forge.json"), encoding="utf-8") as fh:
            after = json.load(fh)
        self.assertLessEqual(after["calls_spent"] + after["calls_reserved"], 1)

    def test_job_ids_are_deterministic_and_resume_does_not_duplicate(self):
        d = tempfile.mkdtemp(prefix="forge-e13-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d, budget={"max_calls": 10, "max_candidates": 4})
        self._write_run(d, run)
        j1 = agent_e.job_id_for("r1", "implement", "implement", ["c"])
        j2 = agent_e.job_id_for("r1", "implement", "implement", ["c"])
        self.assertEqual(j1, j2)
        _job, created1 = agent_e._register_job(d, j1, "implement", ["c"],
                                               "implement", budget_calls=1)
        _job2, created2 = agent_e._register_job(d, j1, "implement", ["c"],
                                                "implement", budget_calls=1)
        self.assertTrue(created1)
        self.assertFalse(created2, "reanudar no debe duplicar el job")
        with open(os.path.join(d, "forge.json"), encoding="utf-8") as fh:
            after = json.load(fh)
        self.assertEqual(after["calls_reserved"], 1)

    def test_decisions_file_is_append_only(self):
        d = tempfile.mkdtemp(prefix="forge-e14-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d)
        self._write_run(d, run)
        agent_e.step(d, run)
        p = os.path.join(d, agent_e.DECISIONS_FILE)
        before = open(p, encoding="utf-8").read()
        agent_e.step(d, run)
        after = open(p, encoding="utf-8").read()
        self.assertTrue(after.startswith(before),
                        "decisions.jsonl no debe reescribirse")

    def test_corrupt_decision_line_is_preserved(self):
        d = tempfile.mkdtemp(prefix="forge-e15-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d)
        self._write_run(d, run)
        agent_e.step(d, run)
        p = os.path.join(d, agent_e.DECISIONS_FILE)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("{this is not json\n")
        agent_e.step(d, run)
        self.assertIn("{this is not json", open(p, encoding="utf-8").read())
        self.assertTrue(agent_e.corrupt_lines(d))

    def test_job_done_requires_existing_output(self):
        d = tempfile.mkdtemp(prefix="forge-e16-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d, budget={"max_calls": 10, "max_candidates": 4})
        self._write_run(d, run)
        job, _ = agent_e._register_job(d, "job-o", "implement", ["c"],
                                       "implement", budget_calls=1)
        res = agent_e.mark_job_completed(d, "job-o", output_ref=None, success=True)
        self.assertEqual(res["state"], "FAILED")
        res2 = agent_e.mark_job_completed(d, "job-o", output_ref="no-existe",
                                          success=True)
        self.assertEqual(res2["state"], "FAILED")

    def test_cancelled_run_is_not_reopened_by_agent_e(self):
        d = tempfile.mkdtemp(prefix="forge-e17-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d, phase="CANCELLED", status="CANCELLED")
        self._write_run(d, run)
        dec = agent_e._mk_decision(run, agent_e.context(d, run), "stop",
                                   "parar", [], [], 0, "low")
        agent_e.execute_decision(d, dec, run)
        with open(os.path.join(d, "forge.json"), encoding="utf-8") as fh:
            after = json.load(fh)
        self.assertEqual(after["phase"], "CANCELLED")


# ------------------------------------------------- §16.10/§15 informe
class ReportTest(TempCwd):
    def test_html_escapes_script(self):
        """El HTML del informe debe escapar el contenido de los candidatos."""
        d = build_patch_run(self.tmp)
        arena = {"champion": "a001", "rounds": [
            {"n": 1, "bye": None, "matches": [
                {"id": "r1-m01", "a": "a001", "b": "a002",
                 "winner": "a001", "reason": "<script>alert(1)</script>"}]}]}
        with open(os.path.join(d, "arena.json"), "w", encoding="utf-8") as fh:
            json.dump(arena, fh)
        out = report_mod.write(d, os.path.join(self.tmp, "reports"))
        body = open(out["html"], encoding="utf-8").read()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertNotIn("<script>alert(1)</script>", body)

    def test_winner_when_all_evaluated_one_eligible(self):
        d = build_patch_run(self.tmp)
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "WINNER", reason)
        self.assertEqual(eligible, ["a001"])

    def test_no_ship_when_every_candidate_fails_its_gate(self):
        """La causa declarada debe ser exactamente 'todos fallan sus gates'."""
        d = build_patch_run(self.tmp, a001_state="FAIL", a002_state="FAIL")
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("ningun candidato supera los gates obligatorios", reason)
        self.assertEqual(eligible, [])

    def test_no_ship_when_candidate_missing_gate_result(self):
        d = build_patch_run(self.tmp)
        p = os.path.join(d, "gates.json")
        gates = json.load(open(p, encoding="utf-8"))
        del gates["a002"]
        json.dump(gates, open(p, "w", encoding="utf-8"))
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("sin GateResult", reason)

    def test_no_ship_when_candidate_gate_not_run(self):
        d = build_patch_run(self.tmp)
        p = os.path.join(d, "gates.json")
        gates = json.load(open(p, encoding="utf-8"))
        gates["a002"]["state"] = "NOT_RUN"
        json.dump(gates, open(p, "w", encoding="utf-8"))
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("inconcluso", reason)

    def test_no_ship_when_candidate_gate_blocked(self):
        d = build_patch_run(self.tmp)
        p = os.path.join(d, "gates.json")
        gates = json.load(open(p, encoding="utf-8"))
        gates["a002"]["state"] = "BLOCKED"
        json.dump(gates, open(p, "w", encoding="utf-8"))
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("inconcluso", reason)

    def test_no_ship_when_candidate_gate_inconclusive(self):
        d = build_patch_run(self.tmp)
        p = os.path.join(d, "gates.json")
        gates = json.load(open(p, encoding="utf-8"))
        gates["a002"]["state"] = "INCONCLUSIVE"
        json.dump(gates, open(p, "w", encoding="utf-8"))
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("inconcluso", reason)

    def test_no_ship_when_suite_hash_mismatch(self):
        d = build_patch_run(self.tmp)
        p = os.path.join(d, "gates.json")
        gates = json.load(open(p, encoding="utf-8"))
        gates["a002"]["suite_sha"] = "b" * 64
        json.dump(gates, open(p, "w", encoding="utf-8"))
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("suite hash mismatch", reason)

    def test_no_ship_when_isolation_invalid(self):
        d = build_patch_run(self.tmp)
        with open(os.path.join(d, "isolation.json"), "w", encoding="utf-8") as fh:
            json.dump({"ok": False, "problems": ["candidato fuera del run"]}, fh)
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("aislamiento no verificado", reason)

    def test_no_ship_when_candidate_modified_after_gate(self):
        d = build_patch_run(self.tmp)
        write(os.path.join(d, "candidates", "a001", "stats.py"),
              "def mean(x): return sum(x)/len(x) + 999\n")
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("modificado tras gate", reason)

    def test_no_ship_when_frozen_baseline_changed(self):
        d = build_patch_run(self.tmp)
        write(os.path.join(d, "baseline", "stats.py"), "# TAMPERED\n")
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("baseline congelado cambio", reason)

    def test_no_ship_when_diff_sha_does_not_match_the_recomputed_diff(self):
        d = build_patch_run(self.tmp)
        p = os.path.join(d, "gates.json")
        gates = json.load(open(p, encoding="utf-8"))
        gates["a001"]["diff_sha"] = "0" * 64
        json.dump(gates, open(p, "w", encoding="utf-8"))
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("diff_sha no coincide", reason)

    def test_no_ship_when_suite_was_tampered_after_gates(self):
        d = build_patch_run(self.tmp)
        run = json.load(open(os.path.join(d, "forge.json"), encoding="utf-8"))
        suite = run["suite"]
        tmp_suite = os.path.join(self.tmp, "suite_copy")
        shutil.copytree(suite, tmp_suite)
        run["suite"] = tmp_suite
        json.dump(run, open(os.path.join(d, "forge.json"), "w", encoding="utf-8"))
        write(os.path.join(tmp_suite, "test_protected.py"),
              open(SUITE, encoding="utf-8").read() + "\n# TAMPERED\n")
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("suite modificada", reason)

    def test_no_ship_when_baseline_frozen_is_absent(self):
        d = build_patch_run(self.tmp)
        shutil.rmtree(os.path.join(d, "baseline"))
        dec, reason, _ = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("baseline congelado ausente", reason)

    def test_resolve_full_returns_the_judged_winner(self):
        """Con dos elegibles, el ganador es el que eligio el juez, no el primero."""
        d = build_patch_run(self.tmp, a001_state="PASS", a002_state="PASS",
                            judge={"winner": "Y", "reason": "mejor",
                                   "evidence": ["a002 es mejor"]},
                            label_map={"X": "a001", "Y": "a002"})
        dec, reason, eligible, winner = report_mod.resolve_full(d)
        self.assertEqual(dec, "WINNER", reason)
        self.assertEqual(winner, "a002")
        self.assertEqual(sorted(eligible), ["a001", "a002"])


# ----------------------------------------------- §16 P0-3 artefacto/apply
class ApplyIntegrityTest(TempCwd):
    def test_apply_exports_the_judged_winner_not_the_first_eligible(self):
        """El parche exportado debe contener el contenido del candidato JUZGADO.

        a002 (el juzgado) lleva un marcador unico; a001 (el primero elegible)
        lleva otro. Si `apply` usara `eligible[0]`, el parche contendria el
        marcador de a001 y este test fallaria.
        """
        d = build_patch_run(self.tmp, a001_state="PASS", a002_state="PASS",
                            judge={"winner": "Y", "reason": "mejor",
                                   "evidence": ["a002 es mejor"]},
                            label_map={"X": "a001", "Y": "a002"})
        write(os.path.join(d, "candidates", "a001", "marcador.py"),
              "MARCADOR_PRIMER_ELEGIBLE = True\n")
        write(os.path.join(d, "candidates", "a002", "marcador.py"),
              "MARCADOR_JUDGADO = True\n")
        p = os.path.join(d, "gates.json")
        gates = json.load(open(p, encoding="utf-8"))
        for cid in ("a001", "a002"):
            cdir = os.path.join(d, "candidates", cid)
            gates[cid]["candidate_manifest_sha"] = isolation.candidate_manifest_sha(cdir)
            gates[cid]["diff_sha"] = isolation.diff_sha(
                isolation.capture_diff(os.path.join(d, "baseline"), cdir))
        json.dump(gates, open(p, "w", encoding="utf-8"))
        arena_forge.cmd_report(ns(dir=d))
        arena_forge.cmd_apply(ns(dir=d, approve=True))
        patch = os.path.join(arena_forge.REPORTS_DIR, os.path.basename(d) + ".patch")
        self.addCleanup(lambda: os.path.exists(patch) and os.remove(patch))
        text = open(patch, encoding="utf-8", errors="replace").read()
        self.assertIn("MARCADOR_JUDGADO", text)
        self.assertNotIn("MARCADOR_PRIMER_ELEGIBLE", text)
        run = json.load(open(os.path.join(d, "forge.json"), encoding="utf-8"))
        self.assertEqual(run["last_decision"]["winner_id"], "a002")

    def test_apply_requires_approve(self):
        d = build_patch_run(self.tmp)
        with self.assertRaises(ForgeError):
            arena_forge.cmd_apply(ns(dir=d, approve=False))

    def test_apply_blocks_when_candidate_changed_after_gates(self):
        d = build_patch_run(self.tmp)
        write(os.path.join(d, "candidates", "a001", "stats.py"), "# changed\n")
        with self.assertRaises(ForgeError) as cm:
            arena_forge.cmd_apply(ns(dir=d, approve=True))
        self.assertIn("decision=NO_SHIP", str(cm.exception))
        _dec, reason, _el, _w = report_mod.resolve_full(d)
        self.assertIn("modificado tras gate", reason)

    def test_apply_blocks_when_frozen_baseline_changed(self):
        d = build_patch_run(self.tmp)
        write(os.path.join(d, "baseline", "stats.py"), "# TAMPERED\n")
        with self.assertRaises(ForgeError) as cm:
            arena_forge.cmd_apply(ns(dir=d, approve=True))
        self.assertIn("baseline congelado", str(cm.exception))

    def test_exported_patch_sha_matches_the_gated_diff_sha(self):
        d = build_patch_run(self.tmp)
        arena_forge.cmd_report(ns(dir=d))
        arena_forge.cmd_apply(ns(dir=d, approve=True))
        patch = os.path.join(arena_forge.REPORTS_DIR, os.path.basename(d) + ".patch")
        self.addCleanup(lambda: os.path.exists(patch) and os.remove(patch))
        gates = json.load(open(os.path.join(d, "gates.json"), encoding="utf-8"))
        self.assertEqual(sha_file(patch), gates["a001"]["diff_sha"])

    def test_report_persists_the_decision(self):
        d = build_patch_run(self.tmp)
        arena_forge.cmd_report(ns(dir=d))
        run = json.load(open(os.path.join(d, "forge.json"), encoding="utf-8"))
        self.assertIn("last_decision", run)
        self.assertEqual(run["last_decision"]["decision"], "WINNER")
        self.assertEqual(run["last_decision"]["winner_id"], "a001")
        self.assertTrue(os.path.isfile(os.path.join(d, "decision.json")))


# ----------------------------------------------- §16.11 presupuesto/perfiles
class BudgetTest(TempCwd):
    def test_extreme_requires_confirm(self):
        base = dict(mode="answer", agents=4, quick=False, seed=7, task="x",
                    task_file=None, baseline_file=None, suite=None, wave=10,
                    dir=None, scope=None, non_goals=None, baseline_dir=None)
        with self.assertRaises(ForgeError):
            arena_forge.cmd_init(ns(profile="extreme", confirm=False, **base))

    def test_profile_limits(self):
        q = agent_e.budget_for("quick")
        e = agent_e.budget_for("extreme")
        self.assertLess(q["max_calls"], e["max_calls"])

    def test_init_rejects_agents_over_profile_max(self):
        base = dict(mode="answer", seed=7, task="x", task_file=None,
                    baseline_file=None, suite=None, wave=10, dir=None,
                    scope=None, non_goals=None, baseline_dir=None,
                    profile="quick", confirm=False, quick=False)
        with self.assertRaises(ForgeError):
            arena_forge.cmd_init(ns(agents=99, **base))


# ------------------------------------ §16.5/§16.17 reanudacion y cancelacion
class ResumeCancelTest(TempCwd):
    def _init(self):
        base = dict(mode="answer", agents=2, quick=False, seed=7, task="t",
                    task_file=None, baseline_file=None, suite=None, wave=10,
                    dir=None, scope=None, non_goals=None, baseline_dir=None,
                    profile="standard", confirm=False)
        arena_forge.cmd_init(ns(**base))
        return arena_forge.run_dir_from(ns(dir=None))

    def test_resume_keeps_completed(self):
        d = self._init()
        before = open(os.path.join(d, "arena.json"), encoding="utf-8").read()
        arena_forge.cmd_resume(ns(dir=d))
        after = open(os.path.join(d, "arena.json"), encoding="utf-8").read()
        self.assertEqual(before, after)          # nada duplicado ni reescrito
        kinds = [e["kind"] for e in ledger.read(d)]
        self.assertIn("resume", kinds)

    def test_cancel_keeps_artifacts(self):
        d = self._init()
        arena_forge.cmd_cancel(ns(dir=d, reason="stop"))
        self.assertEqual(arena_forge.load_forge(d)["phase"], "CANCELLED")
        self.assertTrue(os.path.isfile(os.path.join(d, "arena.json")))
        with self.assertRaises(ForgeError):
            arena_forge.cmd_passthrough("collect", ns(dir=d))

    def test_cancel_blocks_gates_and_decide(self):
        d = self._init()
        arena_forge.cmd_cancel(ns(dir=d, reason="stop"))
        with self.assertRaises(ForgeError):
            arena_forge.cmd_gates(ns(dir=d))
        with self.assertRaises(ForgeError):
            arena_forge.cmd_decide(ns(dir=d))


# ------------------------------------------------- §16.16 cambios preexistentes
class PreexistingChangesTest(TempCwd):
    def test_user_work_untouched(self):
        write(os.path.join(self.tmp, "user_work.txt"), "preciosa produccion del usuario\n")
        before = open(os.path.join(self.tmp, "user_work.txt"), encoding="utf-8").read()
        base = dict(mode="answer", agents=2, quick=False, seed=7, task="t",
                    task_file=None, baseline_file=None, suite=None, wave=10,
                    dir=None, scope=None, non_goals=None, baseline_dir=None,
                    profile="standard", confirm=False)
        arena_forge.cmd_init(ns(**base))
        d = arena_forge.run_dir_from(ns(dir=None))
        arena_forge.cmd_verify(ns(dir=d))
        self.assertEqual(open(os.path.join(self.tmp, "user_work.txt"),
                              encoding="utf-8").read(), before)


# ------------------------------------------------------------ §13 adapter
class AdapterTest(unittest.TestCase):
    def test_probe_marks_unknown_not_verified(self):
        caps = adapter.probe(persist=False)
        self.assertNotEqual(caps["plugin_api"]["status"], adapter.VERIFIED)
        self.assertNotEqual(caps["subagent_background"]["status"], adapter.VERIFIED)
        with self.assertRaises(ForgeError):
            adapter.require(caps, "plugin_api")

    def test_probe_does_not_write_the_repo_when_persist_is_false(self):
        caps_path = adapter.CAP_FILE
        before = os.path.getmtime(caps_path) if os.path.isfile(caps_path) else None
        adapter.probe(persist=False)
        after = os.path.getmtime(caps_path) if os.path.isfile(caps_path) else None
        self.assertEqual(before, after, "probe(persist=False) no debe escribir")

    def test_model_dependent_probes_are_blocked_without_authorisation(self):
        """Sin autorizacion de modelo, esas capacidades NUNCA pueden ser
        `verified`. El test no puede depender de que `opencode` este
        instalado (los runners de CI no lo tienen)."""
        caps = adapter.probe(persist=False, allow_model_calls=False)
        for name in ("subagent_tool", "readonly_agent"):
            self.assertIn(caps[name]["status"],
                          (adapter.BLOCKED, adapter.UNKNOWN), name)
            self.assertNotEqual(caps[name]["status"], adapter.VERIFIED, name)
            self.assertTrue(caps[name]["evidence"], name)

    def test_agent_profiles_are_found_in_the_repo(self):
        caps = adapter.probe(persist=False)
        self.assertEqual(caps["agent_profiles"]["status"], adapter.VERIFIED)
        self.assertIn("implementer", caps["agent_profiles"]["evidence"])

    def test_state_on_disk_probe_is_a_real_roundtrip(self):
        ok, evidence, _scope = adapter._test_state_on_disk()
        self.assertTrue(ok, evidence)
        self.assertIn("reanudado", evidence)

    def test_permission_rules_are_not_claimed_verified_without_enforcement(self):
        caps = adapter.probe(persist=False)
        self.assertNotEqual(caps["permission_rules"]["status"], adapter.VERIFIED)

    def test_summary_counts_only_real_statuses(self):
        caps = adapter.probe(persist=False)
        counts = adapter.summary(caps)
        self.assertEqual(sum(counts.values()), len(caps))
        recomputed = {}
        for entry in caps.values():
            recomputed[entry["status"]] = recomputed.get(entry["status"], 0) + 1
        self.assertEqual({k: v for k, v in counts.items() if v}, recomputed)
        self.assertEqual(set(counts), {adapter.VERIFIED, adapter.UNSUPPORTED,
                                       adapter.UNKNOWN, adapter.INCONCLUSIVE,
                                       adapter.BLOCKED})

    def test_detect_version_returns_semver(self):
        version, raw = adapter.detect_version()
        if version is None:
            # Sin opencode: el fallo debe ser explicito, no un vacio silencioso.
            self.assertTrue(raw)
            self.skipTest("opencode no instalado en PATH")
        self.assertRegex(version, r"^\d+\.\d+\.\d+")
        self.assertTrue(raw.strip())

    def test_mode_requirements_exist_for_every_mode(self):
        for mode in ("answer", "patch", "benchmark"):
            mandatory, optional = adapter.mode_requirements(mode)
            self.assertTrue(mandatory, mode)

    def test_missing_mandatory_reports_the_gap(self):
        caps = {"agent_profiles": {"status": adapter.UNKNOWN}}
        missing = adapter.missing_mandatory(caps, "patch")
        self.assertTrue(missing)
        self.assertTrue(any("agent_profiles" in m for m in missing))


# ------------------------------------------- Sin definiciones duplicadas
class NoDuplicatesTest(unittest.TestCase):
    def _duplicates(self, path):
        """Detecta CUALQUIER binding de nivel superior duplicado.

        No basta con `def`: una reasignacion (`f = 3`), un alias de import
        (`from x import y as f`) o un `def` dentro de un `if` de modulo son
        tambien duplicados silenciosos.
        """
        import ast
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = {}

        def scan(body):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    names.setdefault(node.name, []).append(node.lineno)
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            names.setdefault(tgt.id, []).append(node.lineno)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        bound = alias.asname or alias.name.split(".")[0]
                        names.setdefault(bound, []).append(node.lineno)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef)):
                    pass  # el cuerpo de una funcion es un ambito nuevo
                else:
                    for attr in ("body", "orelse", "finalbody"):
                        sub = getattr(node, attr, None)
                        if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                            scan(sub)
        scan(tree.body)
        return {k: v for k, v in names.items() if len(v) > 1}

    def test_no_duplicate_top_level_definitions(self):
        files = [os.path.join(FORGE_ROOT, "arena_forge.py")]
        fdir = os.path.join(FORGE_ROOT, "forge")
        for f in sorted(os.listdir(fdir)):
            if f.endswith(".py"):
                files.append(os.path.join(fdir, f))
        for path in files:
            dups = self._duplicates(path)
            self.assertFalse(dups, "%s define mas de una vez: %s"
                             % (os.path.basename(path), dups))


# ------------------------------------------------------ Portabilidad / repo
class PortabilityTest(unittest.TestCase):
    _HOST_PATH_RE = None

    def test_no_absolute_host_paths_in_the_repo(self):
        """Ninguna ruta absoluta del host en el codigo ni en la documentacion.

        El patron se construye en tiempo de ejecucion (para que el propio test
        no se auto-dispare) y cubre cualquier unidad, mayusculas/minusculas y
        separadores mixtos. Hay un CONTROL NEGATIVO: si el patron dejara de
        funcionar, el test debe fallar.
        """
        import re
        if self._HOST_PATH_RE is None:
            drive = "[" + chr(65) + "-" + chr(90) + chr(97) + "-" + chr(122) + "]"
            pat = (r"(?:" + drive + r":[\\/]{1,2}Users[\\/]{1,2})"
                   r"|(?:/home/[A-Za-z0-9._-]{1,}/)"
                   r"|(?:/Users/[A-Za-z0-9._-]{1,}/)")
            cls = PortabilityTest
            cls._HOST_PATH_RE = re.compile(pat, re.IGNORECASE)
        rx = self._HOST_PATH_RE
        # CONTROL NEGATIVO: el patron debe detectar una ruta de host.
        sample = ("C" + ":" + chr(92) + "Users" + chr(92) + "alguien" + chr(92))
        self.assertTrue(rx.search(sample),
                        "el patron de rutas absolutas no funciona")
        skip_dirs = {".git", ".arena", "__pycache__", ".pytest_cache", "tmp"}
        # Se excluyen artefactos que citan rutas del host a PROPOSITO:
        # informes de auditoria, el plan de remediacion y el fixture de
        # inyeccion (su contenido es senuelo, no codigo del producto).
        skip_prefix = ("reports/", "docs/superpowers/", "fixtures/injection-test/")
        offenders = []
        for dirpath, dirs, names in os.walk(FORGE_ROOT):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for name in names:
                if not name.endswith((".py", ".md", ".yml", ".yaml", ".json",
                                      ".ini", ".cfg", ".txt")):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, FORGE_ROOT).replace("\\", "/")
                if rel.startswith(skip_prefix):
                    continue
                try:
                    with open(full, encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError:
                    continue
                if rx.search(text):
                    offenders.append(rel)
        self.assertEqual(offenders, [],
                         "ficheros con rutas absolutas del host: %s" % offenders)

    def test_test_paths_are_derived_from_the_checkout(self):
        self.assertTrue(os.path.isdir(FORGE_ROOT))
        self.assertTrue(os.path.isfile(os.path.join(FORGE_ROOT, "arena_forge.py")))

    def test_repo_skill_has_opencode_frontmatter(self):
        """Sin frontmatter `name`+`description`, OpenCode omite la skill."""
        skill = os.path.join(SKILLS_DIR, "arena-forge", "SKILL.md")
        self.assertTrue(os.path.isfile(skill))
        text = open(skill, encoding="utf-8").read()
        self.assertTrue(text.startswith("---"), "falta el bloque frontmatter")
        front = text[3:text.find("\n---", 3)]
        self.assertRegex(front, r"(?m)^name:\s*arena-forge\s*$")
        self.assertRegex(front, r"(?m)^description:\s*\S+")

    def test_agent_permission_rules_put_allow_last(self):
        """OpenCode V2: gana la ultima regla que coincide.

        Si un `allow` de edicion aparece antes de un `deny` amplio, el allow
        queda muerto: el agente no puede escribir nada.
        """
        for name in sorted(os.listdir(AGENTS_DIR)):
            if not name.endswith(".md"):
                continue
            text = open(os.path.join(AGENTS_DIR, name), encoding="utf-8").read()
            rules = adapter._parse_permissions(text)
            if not rules:
                continue
            for i, rule in enumerate(rules):
                if rule["effect"] != "allow" or rule["action"] != "edit":
                    continue
                later = [r for r in rules[i + 1:]
                         if r["action"] == "edit"
                         and adapter._resource_matches(r["resource"], rule["resource"])]
                if later:
                    self.fail("%s: el allow de edicion sobre %r queda anulado por %r"
                              % (name, rule["resource"], later[-1]["resource"]))


# ------------------------------------------------- §16.12/§16.21 benchmark
class BenchmarkTest(unittest.TestCase):
    @unittest.skipUnless(has_pytest(), "pytest no instalado")
    def test_deterministic_ok_and_declared_gaps(self):
        out = os.path.join(tempfile.mkdtemp(prefix="forge-bench-"), "benchmark.json")
        res = bench_mod.run(sizes=(4,), seed=7, out_file=out)
        self.assertTrue(res["deterministic_ok"])
        self.assertTrue(any("E" in n or "aqui" in n or "calidad" in n
                            for n in res["not_measured"]))
        md = bench_mod.to_markdown(res)
        self.assertIn("NO medido", md)

    def test_benchmark_does_not_write_into_the_repo_when_asked(self):
        repo_file = bench_mod.BENCH_FILE
        before = os.path.getmtime(repo_file) if os.path.isfile(repo_file) else None
        out = os.path.join(tempfile.mkdtemp(prefix="forge-bench2-"), "b.json")
        bench_mod.run(sizes=(4,), seed=7, out_file=out)
        after = os.path.getmtime(repo_file) if os.path.isfile(repo_file) else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)

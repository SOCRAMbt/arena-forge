"""Tests de Arena Forge. Solo stdlib (unittest). E2E reales aparte (demo/)."""
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

BRACKET = os.path.join(FORGE_ROOT, "vendor", "arena-skill", "bracket.py")
STRATEGIES = os.path.join(FORGE_ROOT, "vendor", "arena-skill", "strategies.json")
FIX = os.path.join(FORGE_ROOT, "fixtures", "patch-demo")
SUITE = os.path.join(FIX, "tests_protected", "test_protected.py")


def has_pytest():
    r = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


class TempCwd(unittest.TestCase):
    def setUp(self):
        self.prev = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix="forge-test-")
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.prev)
        self.addCleanup(shutil.rmtree, self.tmp, True)


class SchedulerTest(unittest.TestCase):
    def test_sizes_and_deal(self):
        mod = arena_forge.load_bracket_module()
        data = mod.load_strategies(STRATEGIES)
        self.assertEqual(mod.combo_count(data), 15 * 12 * 12)
        for n in (1, 2, 3, 4, 5, 7, 8, 13, 16, 25, 100):
            sizes = mod.bracket_sizes(n)
            self.assertEqual(sizes[0], n)
            self.assertEqual(sizes[-1], 1)
            for a, b in zip(sizes, sizes[1:]):
                self.assertEqual(b, (a + 1) // 2)
        for n in (2, 3, 4, 5, 7, 8, 16, 100):
            ok, _ = arena_forge.simulate_tournament(mod, n, seed=7)
            self.assertTrue(ok, n)
        # misma seed, mismo reparto (scheduler reproducible)
        mod2 = arena_forge.load_bracket_module()
        d1 = mod.deal(8, 7, mod.load_strategies(STRATEGIES))
        d2 = mod2.deal(8, 7, mod2.load_strategies(STRATEGIES))
        self.assertEqual(sorted(map(tuple, d1)), sorted(map(tuple, d2)))


class ForgeInitTest(TempCwd):
    def test_init_writes_governance(self):
        ns = argparse_ns(mode="answer", agents=2, quick=False, seed=7,
                         task="haiku", task_file=None, baseline_file=None,
                         suite=None, wave=10, dir=None)
        self.assertEqual(arena_forge.cmd_init(ns), 0)
        d = arena_forge.run_dir_from(ns)
        fg = arena_forge.load_forge(d)
        self.assertEqual(fg["version"], 1)
        self.assertEqual(fg["mode"], "answer")
        self.assertEqual(fg["status"], "RUNNING")
        self.assertEqual(fg["task_sha"], arena_forge.sha_text("haiku"))
        self.assertTrue(os.path.isfile(os.path.join(d, "arena.json")))


class CancelGuardTest(TempCwd):
    def test_collect_refused_after_cancel(self):
        ns = argparse_ns(mode="answer", agents=2, quick=False, seed=7,
                         task="t", task_file=None, baseline_file=None,
                         suite=None, wave=10, dir=None)
        arena_forge.cmd_init(ns)
        d = arena_forge.run_dir_from(ns)
        arena_forge.cmd_cancel(argparse_ns(dir=d, reason="demo"))
        self.assertEqual(arena_forge.load_forge(d)["status"], "CANCELLED")
        with self.assertRaises(ForgeError):
            arena_forge.cmd_passthrough("collect", argparse_ns(dir=d))


class QuarantineTest(TempCwd):
    def test_oversize_and_traversal(self):
        os.makedirs("run1", exist_ok=True)
        big = os.path.join("run1", "m.verdict.json")
        with open(big, "wb") as fh:
            fh.write(b"x" * (arena_forge.MAX_OUTPUT_BYTES + 1))
        arena_forge.quarantine_oversize(os.path.abspath("run1"))
        self.assertTrue(os.path.isfile(big + ".oversize"))
        self.assertFalse(os.path.isfile(big))
        outside = os.path.abspath(os.path.join("run1", "..", "evil.json"))
        self.assertFalse(arena_forge.inside_run(os.path.abspath("run1"), outside))


class GatesTest(unittest.TestCase):
    @unittest.skipUnless(has_pytest(), "pytest no instalado")
    def test_buggy_fails_fixed_passes(self):
        gb = arena_forge.run_gates(os.path.join(FIX, "baseline_buggy"), SUITE)
        gf = arena_forge.run_gates(os.path.join(FIX, "candidate_fixed"), SUITE)
        self.assertEqual(gb["verdict"], "FAIL")
        self.assertEqual(gf["verdict"], "PASS")
        self.assertTrue(gb["sha_ok"] and gf["sha_ok"])

    @unittest.skipUnless(has_pytest(), "pytest no instalado")
    def test_injection_readme_is_inert(self):
        tmp = tempfile.mkdtemp(prefix="forge-inj-")
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy2(os.path.join(FIX, "candidate_fixed", "stats.py"), tmp)
        shutil.copy2(os.path.join(FORGE_ROOT, "fixtures", "injection-test",
                                  "README_EVIL.md"), tmp)
        g = arena_forge.run_gates(tmp, SUITE)
        self.assertEqual(g["verdict"], "PASS")


class ReportTest(TempCwd):
    def _min_run(self, mode, status, gates=None):
        os.makedirs("run1", exist_ok=True)
        arena = {"champion": "a001", "rounds": [
            {"n": 1, "bye": None, "matches": [
                {"id": "r1-m01", "a": "a001", "b": "a002", "winner": "a001",
                 "reason": "<script>alert(1)</script>"}]}]}
        with open("run1/arena.json", "w", encoding="utf-8") as fh:
            json.dump(arena, fh)
        forge = {"version": 1, "mode": mode, "status": status, "dir": "run1",
                 "seed": 7, "agents": 2, "task_sha": "t", "rubric_sha": "r",
                 "cards_sha": "c", "baseline_commit": "n/a", "events": []}
        with open("run1/forge.json", "w", encoding="utf-8") as fh:
            json.dump(forge, fh)
        if gates is not None:
            with open("run1/gates.json", "w", encoding="utf-8") as fh:
                json.dump(gates, fh)
        return os.path.abspath("run1")

    def test_escape_and_winner(self):
        d = self._min_run("answer", "RUNNING")
        arena_forge.cmd_report(argparse_ns(dir=d))
        base = os.path.basename(d)
        html_p = os.path.join(FORGE_ROOT, "reports", base + ".html")
        self.addCleanup(lambda: [os.path.exists(p) and os.remove(p)
                                 for p in (html_p, html_p[:-5] + ".md")])
        body = open(html_p, encoding="utf-8").read()
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>alert", body)

    def test_no_ship_when_champion_fails_gates(self):
        d = self._min_run("patch", "RUNNING",
                          {"a001": {"verdict": "FAIL", "seconds": 1.0}})
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            arena_forge.cmd_report(argparse_ns(dir=d))
        self.assertIn("NO_SHIP", buf.getvalue())
        base = os.path.basename(d)
        for p in (os.path.join(FORGE_ROOT, "reports", base + ".md"),
                  os.path.join(FORGE_ROOT, "reports", base + ".html")):
            if os.path.exists(p):
                os.remove(p)


class PatchWinnerTest(TempCwd):
    def test_gates_bind_judge(self):
        os.makedirs("run1", exist_ok=True)
        d = os.path.abspath("run1")
        forge = {"mode": "patch"}
        gates = {"cand-a": {"verdict": "PASS"}, "cand-b": {"verdict": "FAIL"}}
        with open("run1/patch_judge.json", "w", encoding="utf-8") as fh:
            json.dump({"winner": "Y", "reason": "x"}, fh)
        with open("run1/patch_map.json", "w", encoding="utf-8") as fh:
            json.dump({"X": "cand-a", "Y": "cand-b"}, fh)
        # Y es inelegible (FAIL): NO_SHIP aunque el juez lo elija
        cand, _ = arena_forge.resolve_patch_winner(d, forge, gates)
        self.assertIsNone(cand)
        with open("run1/patch_judge.json", "w", encoding="utf-8") as fh:
            json.dump({"winner": "X", "reason": "x"}, fh)
        cand, _ = arena_forge.resolve_patch_winner(d, forge, gates)
        self.assertEqual(cand, "cand-a")


def argparse_ns(**kw):
    return type("NS", (), kw)()


if __name__ == "__main__":
    unittest.main(verbosity=2)

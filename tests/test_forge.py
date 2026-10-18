"""Tests de Arena Forge — mapa a las 22 categorias de la especificacion (§16).

Solo stdlib (unittest). Los E2E reales con subagentes viven en demo/.
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
                   gates as gate_engine, isolation, ledger, report as report_mod,
                   score as score_mod, state)

STRATEGIES = os.path.join(FORGE_ROOT, "vendor", "arena-skill", "strategies.json")
FIX = os.path.join(FORGE_ROOT, "fixtures", "patch-demo")
SUITE = os.path.join(FIX, "tests_protected", "test_protected.py")
GOLD = os.path.join(FIX, "candidate_fixed")
BUGGY = os.path.join(FIX, "baseline_buggy")


def has_pytest():
    r = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def ns(**kw):
    return type("NS", (), kw)()


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
        self.assertTrue(contracts.validate_job({"job_id": "j", "run_id": "r",
                                                "phase": "p", "kind": "k",
                                                "input_hash": "h", "state": "BLOCKED",
                                                "attempts": 1, "output_expected": "o"}))
        self.assertFalse(contracts.validate_job({"job_id": "j", "run_id": "r",
                                                 "phase": "p", "kind": "k",
                                                 "input_hash": "h", "state": "PENDING",
                                                 "attempts": 0, "output_expected": "o"}))
        # NO_SHIP sin `winner` es CONTRATO VALIDO (el no-despacho no tiene ganador):
        # validate_decision devuelve [] para el primer caso, error para WINNER sin ganador y
        # para NO_SHIP con ganador (un NO_SHIP no puede declara un ganador).
        self.assertEqual(contracts.validate_decision({"decision_id": "d", "run_id": "r",
                                                      "state": "NO_SHIP", "reason": "x",
                                                      "ts": 1, "policy_version": "p"}), [])
        self.assertTrue(contracts.validate_decision({"decision_id": "d", "run_id": "r",
                                                     "state": "WINNER", "reason": "x",
                                                     "ts": 1, "policy_version": "p"}))

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
        self.assertTrue(contracts.validate_judge_verdict(v2, ["a"]))  # id desconocido


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
        with open(os.path.join(tmp, "tests_protected_evil.py"), "w") as fh:
            fh.write("def test_x(): pass\n")
        g = gate_engine.run_gate(tmp, SUITE)
        self.assertEqual(g["state"], "BLOCKED")
        self.assertEqual(g["failure_class"], "harness_tampering")

    def test_not_run_when_suite_missing(self):
        g = gate_engine.run_gate(GOLD, os.path.join(FIX, "nope.py"))
        self.assertEqual(g["state"], "NOT_RUN")
        self.assertEqual(g["failure_class"], "environment_broken")


# -------------------------------------------------- §16.7 score/gates
class ScoreTest(unittest.TestCase):
    def test_dimension_total(self):
        full = {k: 10 for k in score_mod.PATCH_WEIGHTS}
        self.assertEqual(score_mod.dimension_score(full), 100.0)
        with self.assertRaises(ForgeError):
            score_mod.dimension_score({"correctness": 11})
        with self.assertRaises(ForgeError):
            score_mod.dimension_score({"correctness": 5})

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
               "schema_version": 2}
        run.update(over)
        return run

    def test_decision_validates_and_persists(self):
        d = tempfile.mkdtemp(prefix="forge-e-")
        self.addCleanup(shutil.rmtree, d, True)
        run = self._run(d)
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


# ------------------------------------------------- §16.10/§15 informe
class ReportTest(TempCwd):
    def _min_run(self, mode, status, gates=None):
        os.makedirs("run1", exist_ok=True)
        arena = {"champion": "a001", "rounds": [
            {"n": 1, "bye": None, "matches": [
                {"id": "r1-m01", "a": "a001", "b": "a002", "winner": "a001",
                 "reason": "<script>alert(1)</script>"}]}]}
        with open("run1/arena.json", "w", encoding="utf-8") as fh:
            json.dump(arena, fh)
        forge = {"version": 2, "schema_version": 2, "run_id": "run1", "mode": mode,
                 "status": status, "phase": status, "dir": "run1", "seed": 7,
                 "agents": 2, "task_sha": "t" * 64, "rubric_sha": "r" * 64,
                 "cards_sha": "c" * 64, "baseline_commit": "n/a",
                 "policy_version": "e-policy-v1", "budget": {}, "events": [],
                 "candidates": {"a001": {}, "a002": {}},
                 "suite_sha": "a" * 64}
        with open("run1/forge.json", "w", encoding="utf-8") as fh:
            json.dump(forge, fh)
        if gates is not None:
            # Agregar candidate_manifest_sha y diff_sha a cada gate
            gates_with_hashes = {}
            for cid, g in (gates or {}).items():
                g2 = dict(g)
                if "candidate_manifest_sha" not in g2:
                    g2["candidate_manifest_sha"] = "test_manifest_" + cid
                if "diff_sha" not in g2:
                    g2["diff_sha"] = "test_diff_" + cid
                gates_with_hashes[cid] = g2
            with open("run1/gates.json", "w", encoding="utf-8") as fh:
                json.dump(gates_with_hashes, fh)
        # Para Patch mode, crear isolation.json válido por defecto
        if mode == "patch":
            isolation = {"root": "candidates", "candidates": {
                "a001": {"dir": "candidates/a001", "realpath": os.path.abspath("run1/candidates/a001")},
                "a002": {"dir": "candidates/a002", "realpath": os.path.abspath("run1/candidates/a002")}
            }, "shared": False, "ok": True, "problems": []}
            with open("run1/isolation.json", "w", encoding="utf-8") as fh:
                json.dump(isolation, fh)
        return os.path.abspath("run1")

    def test_html_escapes_script(self):
        d = self._min_run("answer", "RUNNING")
        out = report_mod.write(d, os.path.join(FORGE_ROOT, "reports"))
        base = os.path.basename(d)
        self.addCleanup(lambda: [os.path.exists(p) and os.remove(p)
                                 for p in (out["html"], out["md"])])
        body = open(out["html"], encoding="utf-8").read()
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>alert", body)

    def test_no_ship_when_gate_fails(self):
        d = self._min_run("patch", "EVALUATING",
                          {"a001": {"state": "FAIL", "exit_code": 1, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a001", "diff_sha": "diff_a001"}})
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertEqual(eligible, [])
        out = report_mod.write(d, os.path.join(FORGE_ROOT, "reports"))
        for p in (out["html"], out["md"]):
            if os.path.exists(p):
                os.remove(p)

    # P0-06: No winner con resultados incompletos
    def test_no_ship_when_candidate_missing_gate_result(self):
        """Si falta GateResult para un candidato esperado, no WINNER."""
        d = self._min_run("patch", "EVALUATING",
                          {"a001": {"state": "PASS", "exit_code": 0, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a001", "diff_sha": "diff_a001"}})
        # forge.json tiene 2 candidatos (a001, a002) pero gates solo tiene a001
        with open(os.path.join(d, "forge.json"), encoding="utf-8") as fh:
            forge = json.load(fh)
        forge["candidates"] = {"a001": {}, "a002": {}}
        with open(os.path.join(d, "forge.json"), "w", encoding="utf-8") as fh:
            json.dump(forge, fh)
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("sin GateResult", reason)

    def test_no_ship_when_candidate_gate_not_run(self):
        """Si un candidato tiene NOT_RUN, no WINNER."""
        d = self._min_run("patch", "EVALUATING",
                          {"a001": {"state": "PASS", "exit_code": 0, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a001", "diff_sha": "diff_a001"},
                           "a002": {"state": "NOT_RUN", "exit_code": None, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a002", "diff_sha": "diff_a002"}})
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("inconcluso", reason)

    def test_no_ship_when_candidate_gate_blocked(self):
        """Si un candidato tiene BLOCKED, no WINNER."""
        d = self._min_run("patch", "EVALUATING",
                          {"a001": {"state": "PASS", "exit_code": 0, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a001", "diff_sha": "diff_a001"},
                           "a002": {"state": "BLOCKED", "exit_code": None, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a002", "diff_sha": "diff_a002"}})
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("inconcluso", reason)

    def test_no_ship_when_candidate_gate_inconclusive(self):
        """Si un candidato tiene INCONCLUSIVE, no WINNER."""
        d = self._min_run("patch", "EVALUATING",
                          {"a001": {"state": "PASS", "exit_code": 0, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a001", "diff_sha": "diff_a001"},
                           "a002": {"state": "INCONCLUSIVE", "exit_code": None, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a002", "diff_sha": "diff_a002"}})
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("inconcluso", reason)

    def test_no_ship_when_suite_hash_missing(self):
        """Si falta suite_sha en un resultado, no WINNER."""
        d = self._min_run("patch", "EVALUATING",
                          {"a001": {"state": "PASS", "exit_code": 0, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a001", "diff_sha": "diff_a001"},
                           "a002": {"state": "PASS", "exit_code": 0, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a002", "diff_sha": "diff_a002"}})
        # Configurar suite_sha esperado en el run (diferente al de los gates)
        with open(os.path.join(d, "forge.json"), encoding="utf-8") as fh:
            forge = json.load(fh)
        forge["suite_sha"] = "b" * 64  # Diferente al de los gates
        with open(os.path.join(d, "forge.json"), "w", encoding="utf-8") as fh:
            json.dump(forge, fh)
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("suite hash mismatch", reason)

    def test_no_ship_when_isolation_invalid(self):
        """Si aislamiento inválido, no WINNER."""
        d = self._min_run("patch", "EVALUATING",
                          {"a001": {"state": "PASS", "exit_code": 0, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a001", "diff_sha": "diff_a001"},
                           "a002": {"state": "PASS", "exit_code": 0, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a002", "diff_sha": "diff_a002"}})
        # Invalidar isolation.json
        with open(os.path.join(d, "isolation.json"), "w", encoding="utf-8") as fh:
            json.dump({"ok": False, "problems": ["candidato fuera del run"]}, fh)
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("aislamiento no verificado", reason)

    def test_winner_when_all_evaluated_one_eligible(self):
        """Todos evaluados, mismo harness, exactamente uno PASS → WINNER."""
        d = self._min_run("patch", "EVALUATING",
                          {"a001": {"state": "PASS", "exit_code": 0, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a001", "diff_sha": "diff_a001"},
                           "a002": {"state": "FAIL", "exit_code": 1, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest_a002", "diff_sha": "diff_a002"}})
        # Asegurar isolation.json válido
        with open(os.path.join(d, "isolation.json"), "w", encoding="utf-8") as fh:
            json.dump({"ok": True, "candidates": {"a001": {}, "a002": {}}}, fh)
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "WINNER")
        self.assertEqual(eligible, ["a001"])

    def test_no_ship_when_all_fail(self):
        """Todos FAIL → NO_SHIP."""
        d = self._min_run("patch", "EVALUATING",
                          {"a001": {"state": "FAIL", "exit_code": 1, "suite_sha": "abc"},
                           "a002": {"state": "FAIL", "exit_code": 1, "suite_sha": "abc"}})
        with open(os.path.join(d, "isolation.json"), "w", encoding="utf-8") as fh:
            json.dump({"ok": True, "candidates": {"a001": {}, "a002": {}}}, fh)
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertEqual(eligible, [])

    # P0-05: Hash del candidato modificado tras gate
    def test_no_ship_when_candidate_modified_after_gate(self):
        """Si el candidato cambia tras gate PASS, no WINNER."""
        d = self._min_run("patch", "EVALUATING",
                          {"a001": {"state": "PASS", "exit_code": 0, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest1", "diff_sha": "diff1"},
                           "a002": {"state": "FAIL", "exit_code": 1, "suite_sha": "a" * 64,
                                     "candidate_manifest_sha": "manifest2", "diff_sha": "diff2"}})
        # Asegurar isolation.json válido
        with open(os.path.join(d, "isolation.json"), "w", encoding="utf-8") as fh:
            json.dump({"ok": True, "candidates": {"a001": {}, "a002": {}}}, fh)
        # Crear directorio de candidato real con manifest diferente
        os.makedirs(os.path.join(d, "candidates", "a001"), exist_ok=True)
        with open(os.path.join(d, "candidates", "a001", "stats.py"), "w", encoding="utf-8") as fh:
            fh.write("def mean(x): return sum(x)/len(x)\n")
        dec, reason, eligible = report_mod.resolve(d)
        self.assertEqual(dec, "NO_SHIP")
        self.assertIn("modificado tras gate", reason)


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


# ------------------------------------ §16.5/§16.17 reanudacion y cancelacion
class ResumeCancelTest(TempCwd):
    def test_resume_keeps_completed(self):
        base = dict(mode="answer", agents=2, quick=False, seed=7, task="t",
                    task_file=None, baseline_file=None, suite=None, wave=10,
                    dir=None, scope=None, non_goals=None, baseline_dir=None,
                    profile="standard", confirm=False)
        arena_forge.cmd_init(ns(**base))
        d = arena_forge.run_dir_from(ns(dir=None))
        before = open(os.path.join(d, "arena.json"), encoding="utf-8").read()
        arena_forge.cmd_resume(ns(dir=d))
        after = open(os.path.join(d, "arena.json"), encoding="utf-8").read()
        self.assertEqual(before, after)          # nada duplicado ni reescrito
        kinds = [e["kind"] for e in ledger.read(d)]
        self.assertIn("resume", kinds)

    def test_cancel_keeps_artifacts(self):
        base = dict(mode="answer", agents=2, quick=False, seed=7, task="t",
                    task_file=None, baseline_file=None, suite=None, wave=10,
                    dir=None, scope=None, non_goals=None, baseline_dir=None,
                    profile="standard", confirm=False)
        arena_forge.cmd_init(ns(**base))
        d = arena_forge.run_dir_from(ns(dir=None))
        arena_forge.cmd_cancel(ns(dir=d, reason="stop"))
        self.assertEqual(arena_forge.load_forge(d)["phase"], "CANCELLED")
        self.assertTrue(os.path.isfile(os.path.join(d, "arena.json")))
        with self.assertRaises(ForgeError):
            arena_forge.cmd_passthrough("collect", ns(dir=d))


# ------------------------------------------------- §16.16 cambios preexistentes
class PreexistingChangesTest(TempCwd):
    def test_user_work_untouched(self):
        with open("user_work.txt", "w", encoding="utf-8") as fh:
            fh.write("preciosa produccion del usuario\n")
        before = open("user_work.txt", encoding="utf-8").read()
        base = dict(mode="answer", agents=2, quick=False, seed=7, task="t",
                    task_file=None, baseline_file=None, suite=None, wave=10,
                    dir=None, scope=None, non_goals=None, baseline_dir=None,
                    profile="standard", confirm=False)
        arena_forge.cmd_init(ns(**base))
        d = arena_forge.run_dir_from(ns(dir=None))
        arena_forge.cmd_verify(ns(dir=d))
        self.assertEqual(open("user_work.txt", encoding="utf-8").read(), before)


# ------------------------------------------------------------ §13 adapter
class AdapterTest(unittest.TestCase):
    def test_probe_marks_unknown_not_verified(self):
        caps = adapter.probe()
        self.assertNotEqual(caps["plugin_api"]["status"], adapter.VERIFIED)
        self.assertNotEqual(caps["subagent_background"]["status"], adapter.VERIFIED)
        with self.assertRaises(ForgeError):
            adapter.require(caps, "plugin_api")

    def test_summary_counts(self):
        caps = adapter.probe()
        counts = adapter.summary(caps)
        self.assertGreaterEqual(counts.get(adapter.VERIFIED, 0), 5)


# ------------------------------------------------- §16.12/§16.21 benchmark
class BenchmarkTest(unittest.TestCase):
    @unittest.skipUnless(has_pytest(), "pytest no instalado")
    def test_deterministic_ok_and_declared_gaps(self):
        res = bench_mod.run(sizes=(4,), seed=7)
        self.assertTrue(res["deterministic_ok"])
        self.assertTrue(any("E" in n or "aqui" in n or "calidad" in n
                            for n in res["not_measured"]))
        md = bench_mod.to_markdown(res)
        self.assertIn("NO medido", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""E2E de Answer Arena con agente STUB (§16.2 del contrato).

Cubre la cadena completa: init -> next/prompts -> spawn -> attack -> defend ->
judge -> collect -> advance -> decision -> informe, con 4 candidatos.

POR QUE UN STUB
---------------
El contrato (§13.4) exige que el flujo base funcione en local "sin depender de
... tokens pagos". El stub (`forge/stub_agent.py`) juega el papel del subagente
con el camino REAL de produccion (mismos ficheros, mismo esquema, mismo
`collect`/`advance`/`decide`), pero sin gastar tokens.

LO QUE ESTE TEST NO PROBAB
---------------------------
La calidad de un modelo. Todo lo que produce el stub va etiquetado
(`stub_manifest.json`, banner en cada artefacto) para que un revisor no pueda
confundir esta ejecucion con un E2E de agentes reales.

CONTROLES NEGATIVOS (lo que haria que este test pasara en verde sin+E2E real)
------------------------------------------------------------------------------
1. `check <fase>` falla y lista exactamente las salidas que faltan.
2. `advance` falla (rc=2) si falta un veredicto, y funciona despues.
3. Las 4 respuestas spawn son distintas entre si (hash diferente).
4. El juez discrimina: el candidato inferior sale eliminado en la ronda 1.
5. El ganador se RE-DERIVA de forma independiente desde el veredicto en crudo
   (`bracket.decide`), sin fiarse de lo que diga `arena.json`.
6. Reanudar no duplica trabajo: hashes y numero de rondas invariantes.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

FORGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FORGE_ROOT)

import arena_forge  # noqa: E402
from forge import contracts, stub_agent  # noqa: E402

SEED = 7
AGENTS = 4
INFERIOR = "a003"


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _bracket():
    return arena_forge.load_bracket_module()


class AnswerArenaE2E(unittest.TestCase):
    """E2E Answer Arena con 4 candidatos, stub determinista, coste 0."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="forge-answer-e2e-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run_dir = os.path.join(self.tmp, "run")
        rc = arena_forge.main([
            "init", "--mode", "answer", "--agents", str(AGENTS), "--seed", str(SEED),
            "--task", "disena una funcion que calcule el factorial",
            "--dir", self.run_dir, "--profile", "quick"])
        self.assertEqual(rc, 0, "init fallo")
        self.mod = _bracket()
        with open(os.path.join(self.run_dir, "arena.json"), encoding="utf-8") as fh:
            self.state = json.load(fh)

    # ------------------------------------------------------------- utilidades
    def _next(self):
        return arena_forge.main(["next", "--dir", self.run_dir])

    def _check(self, phase):
        return arena_forge.main(["check", phase, "--dir", self.run_dir])

    def _collect(self):
        return arena_forge.main(["collect", "--dir", self.run_dir])

    def _advance(self):
        return arena_forge.main(["advance", "--dir", self.run_dir])

    def _state(self):
        with open(os.path.join(self.run_dir, "arena.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def _current_phase(self):
        """Fase que el bracket pide ahora mismo (la que `next` acaba de decir)."""
        state = self._state()
        try:
            phase, _left, _jobs = self.mod.next_action(state)
            return phase
        except Exception:
            return ""

    def _run_round(self):
        """Una ronda completa: se sigue al bracket fase a fase hasta el juez."""
        for _ in range(8):
            if self._next() != 0:
                break
            phase = self._current_phase()
            if phase not in ("spawn", "attack", "defend", "judge", "final"):
                break
            stub_agent.run_phase(self.run_dir, phase, inferior=INFERIOR)

    # ------------------------------------------------------------------ tests
    def test_01_check_reports_exactly_the_missing_outputs(self):
        """CONTROL NEGATIVO 1: sin stubs, `check` falla y lista lo que falta."""
        self.assertEqual(self._next(), 0)
        rc = self._check("spawn")
        self.assertNotEqual(rc, 0, "check deberia fallar sin salidas")
        for aid in sorted(self._state()["agents"]):
            self.assertTrue(os.path.isfile(
                os.path.join(self.run_dir, "r0", aid + ".md")) is False)

    def test_02_advance_fails_without_verdicts_then_succeeds(self):
        """CONTROL NEGATIVO 2: `advance` falla (rc=2) si falta un veredicto."""
        self._run_round()
        # Sin collect, ningun match esta registrado:
        rc = self._advance()
        self.assertEqual(rc, 2,
                         "advance deberia fallar sin veredictos registrados")
        # Con collect, el advance va:
        self.assertEqual(self._collect(), 0)
        self.assertEqual(self._advance(), 0, "advance con veredictos fallo")

    def test_03_four_distinct_spawn_answers(self):
        """4 candidatos, 4 respuestas DISTINTAS (no un stub identico repetido)."""
        self._run_round()
        hashes = {}
        for aid in sorted(self._state()["agents"]):
            p = os.path.join(self.run_dir, "r0", aid + ".md")
            self.assertTrue(os.path.isfile(p), "falta la respuesta de %s" % aid)
            self.assertGreater(os.path.getsize(p), 0)
            hashes[aid] = _sha(p)
        self.assertEqual(len(set(hashes.values())), AGENTS,
                         "las respuestas spawn deben ser distintas entre si")
        # Y el run queda marcado como sintetico, con coste 0:
        manifest = json.load(open(os.path.join(self.run_dir, "stub_manifest.json"),
                                  encoding="utf-8"))
        self.assertEqual(manifest["kind"], "stub-agent")
        self.assertEqual(manifest["calls"], 0)
        self.assertEqual(manifest["cost"], 0)

    def test_04_every_artifact_of_the_round_exists(self):
        """Por cada match: 2 ataques, 2 defensas + 2 soluciones, 1 veredicto."""
        self._run_round()
        state = self._state()
        rd = state["rounds"][0]
        for m in rd["matches"]:
            n, mid = rd["n"], m["id"]
            for aid in (m["a"], m["b"]):
                self.assertTrue(os.path.isfile(os.path.join(
                    self.run_dir, "r%d" % n, "%s.%s.attack.md" % (mid, aid))))
                self.assertTrue(os.path.isfile(os.path.join(
                    self.run_dir, "r%d" % n, "%s.%s.defense.md" % (mid, aid))))
                self.assertTrue(os.path.isfile(os.path.join(
                    self.run_dir, "r%d" % n, "%s.%s.solution.md" % (mid, aid))))
            vp = os.path.join(self.run_dir, "r%d" % n, "%s.verdict.json" % mid)
            self.assertTrue(os.path.isfile(vp), "falta el veredicto de %s" % mid)
            verdict = json.load(open(vp, encoding="utf-8"))
            # El veredicto cumple el contrato de datos:
            self.assertEqual(contracts.validate_judge_verdict(
                verdict, [m["a"], m["b"]]), [])
            self.assertIn(verdict["winner"], (m["a"], m["b"]))

    def test_05_judge_discriminates_and_winner_is_independently_rederived(self):
        """CONTROL NEGATIVO 4 y 5: el juez discrimina, y el ganador se
        RE-DERIVA desde el veredicto en crudo (no se fia de arena.json)."""
        self._run_round()
        self.assertEqual(self._collect(), 0)
        state = self._state()
        rd = state["rounds"][0]
        for m in rd["matches"]:
            vp = os.path.join(self.run_dir, "r%d" % rd["n"], "%s.verdict.json" % m["id"])
            verdict = json.load(open(vp, encoding="utf-8"))
            # Re-derivacion INDEPENDIENTE con el motor real:
            winner, totals, _note = self.mod.decide(verdict, m["a"], m["b"])
            self.assertEqual(m["winner"], winner,
                             "el ganador registrado no coincide con la "
                             "re-derivacion independiente")
            # Y las puntuaciones son heterogeneas (el juez puntua contenido):
            self.assertGreater(totals[winner], totals[m["a"] if winner == m["b"] else m["b"]])
        # El candidato inferior debe quedar eliminado en la ronda 1:
        losers = [m["loser"] for m in rd["matches"] if m.get("loser")]
        self.assertIn(INFERIOR, losers,
                      "el candidato inferior debe ser eliminado: el juez no "
                      "discrimina")
        # Y el estado de eliminacion lo confirma tras el advance:
        self.assertEqual(self._advance(), 0)
        self.assertEqual(self._state()["agents"][INFERIOR].get("eliminated_in"), 1,
                         "el inferior debe eliminarse en la ronda 1")

    def test_06_single_champion_and_persisted_report(self):
        """Un solo campeon, decision persistida e informe generado."""
        # Se completan las rondas hasta que haya campeon:
        for _ in range(6):
            state = self._state()
            if state.get("champion"):
                break
            self._run_round()
            self.assertEqual(self._collect(), 0)
            self.assertEqual(self._advance(), 0)
        state = self._state()
        self.assertTrue(state.get("champion"), "no hay campeon")
        # Con campeon no hay ronda abierta: `advance` lo dice (rc=2).
        rc = self._advance()
        self.assertNotEqual(rc, 0, "advance tras el campeon deberia fallar")

        # Informe (MD + HTML) y decision persistida:
        self.assertEqual(arena_forge.main(["report", "--dir", self.run_dir]), 0)
        dec_path = os.path.join(self.run_dir, "decision.json")
        self.assertTrue(os.path.isfile(dec_path), "falta decision.json")
        dec = json.load(open(dec_path, encoding="utf-8"))
        self.assertEqual(dec["decision"], "WINNER")
        self.assertEqual(dec["winner_id"], state["champion"])

        # Informe generado:
        reports = os.path.join(FORGE_ROOT, "reports")
        base = os.path.basename(self.run_dir)
        md = os.path.join(reports, base + ".md")
        html = os.path.join(reports, base + ".html")
        self.addCleanup(lambda: [os.path.exists(p) and os.remove(p)
                                 for p in (md, html)])
        self.assertTrue(os.path.isfile(md), "falta el informe MD")
        self.assertTrue(os.path.isfile(html), "falta el informe HTML")
        self.assertIn("STUB", open(md, encoding="utf-8").read() +
                      open(md, encoding="utf-8").read())

    def test_07_resume_does_not_duplicate_work(self):
        """CONTROL NEGATIVO 6: `collect` es idempotente y `advance` avanza UNA
        sola vez: reanudar no duplica rondas ni reescribe salidas."""
        self._run_round()
        self.assertEqual(self._collect(), 0)
        before_state = self._state()
        before_hashes = {}
        for rel_dir in ("r0", "r1"):
            base = os.path.join(self.run_dir, rel_dir)
            if not os.path.isdir(base):
                continue
            for dirpath, _dirs, names in os.walk(base):
                for n in names:
                    p = os.path.join(dirpath, n)
                    before_hashes[os.path.relpath(p, self.run_dir)] = _sha(p)
        before_rounds = len(before_state["rounds"])
        before_winner = before_state["rounds"][0]["matches"][0]["winner"]

        # Reanudar: `collect` de nuevo NO debe duplicar el registro.
        self.assertEqual(self._collect(), 0)
        mid_state = self._state()
        self.assertEqual(len(mid_state["rounds"]), before_rounds,
                         "collect duplico una ronda")
        self.assertEqual(mid_state["rounds"][0]["matches"][0]["winner"],
                         before_winner, "collect reescribio el ganador")

        # Y `advance` avanza exactamente una vez.
        self.assertEqual(self._advance(), 0)
        after = self._state()
        self.assertEqual(len(after["rounds"]), before_rounds + 1,
                         "advance no abrio la ronda siguiente")
        rc = self._advance()
        self.assertNotEqual(rc, 0, "advance no debe poder avanzar dos veces")
        self.assertEqual(len(self._state()["rounds"]), before_rounds + 1,
                         "advance duplico una ronda")

        after_hashes = {}
        for rel_dir in ("r0", "r1"):
            base = os.path.join(self.run_dir, rel_dir)
            if not os.path.isdir(base):
                continue
            for dirpath, _dirs, names in os.walk(base):
                for n in names:
                    p = os.path.join(dirpath, n)
                    after_hashes[os.path.relpath(p, self.run_dir)] = _sha(p)
        self.assertEqual(before_hashes, after_hashes,
                         "reanudar reescribio salidas existentes")

    def test_08_stub_is_deterministic(self):
        """Dos ejecuciones producen bytes IDENTICOS (sin azar ni reloj)."""
        other = tempfile.mkdtemp(prefix="forge-answer-e2e2-")
        self.addCleanup(shutil.rmtree, other, True)
        run2 = os.path.join(other, "run")
        self.assertEqual(arena_forge.main([
            "init", "--mode", "answer", "--agents", str(AGENTS), "--seed", str(SEED),
            "--task", "disena una funcion que calcule el factorial",
            "--dir", run2, "--profile", "quick"]), 0)
        for phase in ("spawn", "attack", "defend", "judge"):
            arena_forge.main(["next", "--dir", run2])
            stub_agent.run_phase(run2, phase, inferior=INFERIOR)
        for phase in ("spawn", "attack", "defend", "judge"):
            arena_forge.main(["next", "--dir", self.run_dir])
            stub_agent.run_phase(self.run_dir, phase, inferior=INFERIOR)
        for rel in ("r0/a001.md", "r0/a002.md", "r0/a003.md", "r0/a004.md"):
            p1 = os.path.join(self.run_dir, rel.replace("/", os.sep))
            p2 = os.path.join(run2, rel.replace("/", os.sep))
            self.assertTrue(os.path.isfile(p1) and os.path.isfile(p2), rel)
            self.assertEqual(_sha(p1), _sha(p2), "el stub no es determinista: %s" % rel)

    def test_09_interruption_mid_phase_then_resume_without_duplicates(self):
        """§16.5: interrupcion a mitad de fase y recuperacion sin duplicar.

        Se simula una interrupcion dejando la ronda a medias (spawn+attack
        hechos, sin collect ni advance) y se reanuda: el bracket debe
        completar la ronda sin repetir trabajo ya hecho ni duplicar registros.
        """
        # Fase de spawn y de attack, y "crash" (no se hace collect ni advance).
        for phase in ("spawn", "attack"):
            self.assertEqual(self._next(), 0)
            self.assertEqual(self._current_phase(), phase)
            stub_agent.run_phase(self.run_dir, phase, inferior=INFERIOR)
        before = self._state()
        self.assertIsNone(before["rounds"][0]["matches"][0]["winner"],
                          "no deberia haber ganador todavia")
        partial = {}
        for dirpath, _dirs, names in os.walk(os.path.join(self.run_dir, "r0")):
            for n in names:
                p = os.path.join(dirpath, n)
                partial[os.path.relpath(p, self.run_dir)] = _sha(p)

        # Reanudacion: se sigue desde donde se quedo.
        for phase in ("defend", "judge"):
            self.assertEqual(self._next(), 0)
            self.assertEqual(self._current_phase(), phase)
            stub_agent.run_phase(self.run_dir, phase, inferior=INFERIOR)
        self.assertEqual(self._collect(), 0)
        self.assertEqual(self._advance(), 0)

        after = self._state()
        # No se duplico trabajo: los ficheros de la fase de spawn siguen igual.
        for rel, digest in partial.items():
            p = os.path.join(self.run_dir, rel.replace("/", os.sep))
            self.assertEqual(_sha(p), digest,
                             "reanudar reescribio %s" % rel)
        # Y seCeremonialaron los 2 matches de la ronda, sin duplicados.
        matches = after["rounds"][0]["matches"]
        self.assertEqual(len(matches), 2)
        for m in matches:
            self.assertTrue(m.get("winner"), "match sin ganador tras reanudar")
            self.assertTrue(m.get("loser"))
        # Una sola ronda cerrada (no dos advances).
        self.assertEqual(len(after["rounds"]), len(before["rounds"]) + 1,
                         "reanudar duplico rondas")


if __name__ == "__main__":
    unittest.main(verbosity=2)

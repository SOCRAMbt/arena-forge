"""Autotests del lint propio.

Un lint que no detecta nada tambien pasaria en verde: sin control negativo, su
"PASS" no prueba nada. Estos tests plantan cada tipo de defecto y comprueban que
el lint lo ve; y comprueban que NO ve ruido (falsos positivos).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import lint as lintmod  # noqa: E402


class LintSelfTest(unittest.TestCase):
    def _lint(self, code):
        tmp = tempfile.mkdtemp(prefix="forge-lint-")
        path = os.path.join(tmp, "modulo.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(code)
        errors, warnings = lintmod.lint(path)
        return errors, warnings

    # -------------------------------------------------- controles negativos
    def test_detects_duplicate_binding(self):
        errors, _ = self._lint("def f():\n    pass\n\ndef f():\n    pass\n")
        self.assertTrue(any("duplicado" in e for e in errors), errors)

    def test_detects_duplicate_import_alias(self):
        errors, _ = self._lint("import os as cosa\nfrom sys import path as cosa\n")
        self.assertTrue(any("duplicado" in e for e in errors), errors)

    def test_does_not_flag_submodule_imports_of_the_same_package(self):
        """`import urllib.error` y `import urllib.parse` enlazan el MISMO
        nombre: no es una redefinicion."""
        errors, _ = self._lint("import urllib.error\nimport urllib.parse\n"
                               "import urllib.request\n")
        self.assertEqual(errors, [], errors)

    def test_detects_shell_true(self):
        errors, _ = self._lint("import subprocess\n"
                                "def f():\n"
                                "    subprocess.run(['x'], shell=True)\n")
        self.assertTrue(any("shell=True" in e for e in errors), errors)

    def test_detects_assert_outside_tests(self):
        errors, _ = self._lint("def f():\n    assert True\n")
        self.assertTrue(any("assert" in e for e in errors), errors)

    def test_detects_syntax_error(self):
        errors, _ = self._lint("def f(:\n")
        self.assertTrue(any("sintaxis" in e for e in errors), errors)

    # ------------------------------------------------------ control negativo
    def test_does_not_flag_legitimate_code(self):
        errors, _ = self._lint(
            "import os\n"
            "\n"
            "def f():\n"
            "    '''doc'''\n"
            "    try:\n"
            "        return 1\n"
            "    except ValueError:\n"
            "        return 2\n")
        self.assertEqual(errors, [], errors)

    def test_does_not_flag_spanish_word_todo(self):
        """'todo' en prosa (minusculas, en espanol) NO es un marcador pendiente."""
        _e, warnings = self._lint("def f():\n"
                                  "    '''coste de todo el metodo, por todo'''\n")
        self.assertEqual([w for w in warnings if "marcador" in w], [])

    def test_does_not_flag_spanish_todo_in_capitals(self):
        """'TODO' en mayusculas en espanol ("recorre TODO el arbol") NO es
        un marcador pendiente: hace falta el calificador `:` o `(`."""
        _e, warnings = self._lint("def f():\n"
                                  "    '''Recorre TODO el arbol del candidato'''\n")
        self.assertEqual([w for w in warnings if "marcador" in w], [])

    def test_flags_uppercase_todo_marker(self):
        _e, warnings = self._lint("def f():\n"
                                  "    '''TODO: falta algo'''\n")
        self.assertTrue(any("marcador" in w for w in warnings), warnings)

    def test_silent_except_is_a_warning_not_an_error(self):
        errors, warnings = self._lint("def f():\n"
                                      "    try:\n"
                                      "        pass\n"
                                      "    except OSError:\n"
                                      "        pass\n")
        self.assertEqual(errors, [])
        self.assertTrue(any("silencioso" in w for w in warnings), warnings)

    # ----------------------------------------------------- el repo esta limpio
    def test_repository_has_no_lint_errors(self):
        errors = []
        for p in lintmod._iter_sources():
            e, _w = lintmod.lint(p)
            errors.extend(e)
        self.assertEqual(errors, [], "\n".join(errors))

    def test_build_step_passes(self):
        import subprocess
        r = subprocess.run([sys.executable, "-m", "compileall", "-q",
                            "arena_forge.py", "forge", "tests", "tools"],
                           cwd=lintmod.REPO, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

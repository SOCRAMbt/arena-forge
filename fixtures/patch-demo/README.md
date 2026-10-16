# Fixture patch-demo

Tarea: `stats.py` debe exponer `mean(xs)` y `median(xs)` que fallen con
`ValueError` ante lista vacía.

Aceptación (suite protegida `tests_protected/test_protected.py`):
- `mean([2,4,6]) == 4.0`
- `median([3,1,2]) == 2`, `median([4,1,3,2]) == 2.5`
- vacío eleva `ValueError`

`baseline_buggy/` falla `test_mean` (off-by-one en el denominador).
`candidate_fixed/` pasa todo. El harness debe discriminarlas.

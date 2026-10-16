"""Suite PROTEGIDA del fixture patch-demo.

Vive fuera de los directorios de candidato. El harness la copia a un scratch
limpio junto a los ficheros del candidato y la ejecuta ahi. Ningun candidato
puede editarla ni sustituirla: su SHA se verifica antes y despues.
"""
from stats import mean, median


def test_mean():
    assert mean([2, 4, 6]) == 4.0


def test_median_odd():
    assert median([3, 1, 2]) == 2


def test_median_even():
    assert median([4, 1, 3, 2]) == 2.5


def test_empty_raises():
    for fn in (mean, median):
        try:
            fn([])
        except ValueError:
            continue
        raise AssertionError("no eleva ValueError con vacio")

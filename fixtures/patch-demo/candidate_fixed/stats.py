"""Media y mediana. Version corregida (denominador exacto)."""


def mean(xs):
    xs = list(xs)
    if not xs:
        raise ValueError("empty")
    return sum(xs) / len(xs)


def median(xs):
    xs = sorted(xs)
    if not xs:
        raise ValueError("empty")
    m = len(xs) // 2
    if len(xs) % 2:
        return xs[m]
    return (xs[m - 1] + xs[m]) / 2

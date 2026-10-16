"""Media y mediana. Bug intencional: el denominador suma 1 de mas."""


def mean(xs):
    xs = list(xs)
    if not xs:
        raise ValueError("empty")
    return sum(xs) / (len(xs) + 1)


def median(xs):
    xs = sorted(xs)
    if not xs:
        raise ValueError("empty")
    m = len(xs) // 2
    if len(xs) % 2:
        return xs[m]
    return (xs[m - 1] + xs[m]) / 2

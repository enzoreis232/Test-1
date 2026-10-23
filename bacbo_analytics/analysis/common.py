"""Convenções matemáticas compartilhadas, sem dependências da interface."""

from math import sqrt
from typing import Iterable

LABELS = ("P", "B", "T")
THEORETICAL = {"P": 575 / 1296, "B": 575 / 1296, "T": 146 / 1296}
NO_EVIDENCE = "SEM EVIDÊNCIA SUFICIENTE DE PREVISIBILIDADE."


def normalize(values: Iterable) -> list[str]:
    result = []
    for item in values:
        value = item if isinstance(item, str) else getattr(item, "result", None)
        if value not in LABELS:
            raise ValueError("Resultado inválido: use somente P, B ou T")
        result.append(value)
    return result


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float] | None:
    """IC de Wilson marginal, 95%, para frequência; não é acurácia preditiva."""
    if n == 0:
        return None
    p = successes / n
    divisor = 1 + z * z / n
    center = (p + z * z / (2 * n)) / divisor
    margin = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / divisor
    return max(0.0, center - margin), min(1.0, center + margin)


def holm(p_values: dict[str, float]) -> dict[str, float]:
    """Ajuste Holm da família explicitamente recebida."""
    previous = 0.0
    adjusted = {}
    ordered = sorted(p_values, key=p_values.get)
    for rank, name in enumerate(ordered):
        previous = max(previous, (len(ordered) - rank) * p_values[name])
        adjusted[name] = min(1.0, previous)
    return adjusted

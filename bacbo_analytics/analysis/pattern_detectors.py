"""Detectores independentes e extensíveis. Todos descrevem dados passados."""

from collections import Counter
from itertools import groupby
from statistics import mean, median, pvariance
from typing import Protocol

from .common import LABELS


class PatternDetector(Protocol):
    name: str

    def detect(self, results: list[str]) -> dict: ...


class SurfDetector:
    name = "surf"

    def __init__(self, trigger: int = 4):
        self.trigger = trigger

    def detect(self, results: list[str]) -> dict:
        runs = [(side, len(list(group))) for side, group in groupby(results)]
        side, length = runs[-1] if runs else (None, 0)
        distribution = Counter(length for side, length in runs if side != "T")
        return {"active": side in ("P", "B") and length >= self.trigger,
                "side": side, "length": length,
                "longest": max((length for side, length in runs if side != "T"), default=0),
                "distribution": dict(sorted(distribution.items())),
                "occurrences": sum(length >= self.trigger for side, length in runs if side != "T")}


class ChessDetector:
    name = "chess"

    def __init__(self, trigger: int = 4):
        self.trigger = trigger

    def detect(self, results: list[str]) -> dict:
        current, longest, total = 0, 0, 0
        episodes = []
        for previous, current_result in zip(results, results[1:]):
            if previous in ("P", "B") and current_result in ("P", "B") and previous != current_result:
                current += 1
                total += 1
                longest = max(longest, current)
            else:
                if current:
                    episodes.append(current)
                current = 0
        if current:
            episodes.append(current)
        return {"active": current >= self.trigger, "length": current, "longest": longest,
                "total": total, "frequency": total / (len(results) - 1) if len(results) > 1 else 0,
                "occurrences": sum(n >= self.trigger for n in episodes)}


class BlocksDetector:
    name = "blocks"

    def detect(self, results: list[str]) -> dict:
        occurrences = {}
        active = []
        for size in (2, 3, 4):
            count = 0
            width = size * 4
            for start in range(max(0, len(results) - width + 1)):
                part = results[start:start + width]
                expected = ([part[0]] * size + [("B" if part[0] == "P" else "P")] * size) * 2
                if part[0] in ("P", "B") and part == expected:
                    count += 1
                    if start + width == len(results):
                        active.append(size)
            occurrences[size] = count
        return {"active": bool(active), "sizes": active, "occurrences": occurrences,
                "note": "Ocorrências sobrepostas, janelas de quatro blocos do mesmo tamanho."}


class TieDetector:
    name = "ties"

    def detect(self, results: list[str]) -> dict:
        positions = [i for i, side in enumerate(results) if side == "T"]
        intervals = [b - a for a, b in zip(positions, positions[1:])]
        before_after = {before: {after: 0 for after in LABELS} for before in LABELS}
        for i in positions:
            if 0 < i < len(results) - 1:
                before_after[results[i - 1]][results[i + 1]] += 1
        return {"intervals": intervals, "mean": mean(intervals) if intervals else None,
                "median": median(intervals) if intervals else None,
                "variance": pvariance(intervals) if intervals else None,
                "distribution": dict(Counter(intervals)), "before_after": before_after,
                "current_gap": len(results) - 1 - positions[-1] if positions else len(results),
                "gap_censored": not bool(positions),
                "note": "Intervalos completos entre empates, em rodadas. Atraso não aumenta P(T)."}

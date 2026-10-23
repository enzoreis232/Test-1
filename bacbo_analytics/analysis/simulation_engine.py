"""Simulação reproduzível dos quatro dados independentes."""

import random


class SimulationEngine:
    def __init__(self, seed: int | None = None):
        self.seed = seed
        self._rng = random.Random(seed)

    def next_result(self) -> tuple[str, tuple[int, int, int, int]]:
        dice = tuple(self._rng.randint(1, 6) for _ in range(4))
        player, banker = sum(dice[:2]), sum(dice[2:])
        result = "P" if player > banker else "B" if banker > player else "T"
        return result, dice

    def generate(self, count: int) -> list[tuple[str, tuple[int, int, int, int]]]:
        if type(count) is not int or not 0 <= count <= 1_000_000:
            raise ValueError("Quantidade deve ser inteira, entre 0 e 1.000.000")
        return [self.next_result() for _ in range(count)]

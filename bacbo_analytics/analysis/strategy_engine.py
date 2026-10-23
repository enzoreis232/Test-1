"""Orquestração de detectores; adicionar plugins não altera o núcleo."""

from collections import Counter

from .common import LABELS, normalize
from .pattern_detectors import BlocksDetector, ChessDetector, SurfDetector, TieDetector


class StrategyEngine:
    def __init__(self, surf_trigger: int = 4, chess_trigger: int = 4, detectors=None):
        if min(surf_trigger, chess_trigger) < 2:
            raise ValueError("Gatilhos devem ser pelo menos 2")
        self.detectors = detectors or [SurfDetector(surf_trigger), ChessDetector(chess_trigger),
                                      BlocksDetector(), TieDetector()]

    def analyze(self, results) -> dict:
        values = normalize(results)
        patterns = {detector.name: detector.detect(values) for detector in self.detectors}
        surf, chess = patterns.get("surf", {}), patterns.get("chess", {})
        current = "Nenhum padrão configurado ativo"
        evidence, similar = "Amostra descritiva; sem indicação de entrada.", 0
        if surf.get("active"):
            current = "Surf de " + ("Player" if surf["side"] == "P" else "Banker")
            evidence = f"{surf['length']} resultados consecutivos; empates interrompem a sequência."
            similar = surf["occurrences"]
        elif chess.get("active"):
            current = "Alternância (Xadrez)"
            evidence = f"{chess['length']} alternâncias consecutivas entre P e B."
            similar = chess["occurrences"]
        elif patterns.get("blocks", {}).get("active"):
            current = "Blocos repetidos"
            evidence = f"Tamanhos ativos: {patterns['blocks']['sizes']}."
            similar = sum(patterns["blocks"]["occurrences"].values())
        transitions = {a: {b: 0 for b in LABELS} for a in LABELS}
        for a, b in zip(values, values[1:]):
            transitions[a][b] += 1
        windows = {}
        for size in (10, 25, 50, 100):
            part = values[-size:]
            counts = Counter(part)
            windows[str(size)] = {"n": len(part), "counts": {side: counts[side] for side in LABELS},
                                  "relative": {side: counts[side] / len(part) if part else 0 for side in LABELS}}
        counts = Counter(values)
        windows["all"] = {"n": len(values), "counts": {s: counts[s] for s in LABELS},
                          "relative": {s: counts[s] / len(values) if values else 0 for s in LABELS}}
        return {"current_pattern": current, "evidence": evidence, "similar_occurrences": similar,
                "current_run": {"side": surf.get("side"), "length": surf.get("length", 0)},
                "longest_run": surf.get("longest", 0), "alternations": chess,
                "repetitions": sum(a == b for a, b in zip(values, values[1:])),
                "tie_intervals": patterns.get("ties", {}), "transitions": transitions,
                "windows": windows, "patterns": patterns}

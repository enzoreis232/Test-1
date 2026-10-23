"""Estatística categórica com testes Monte Carlo e controle de comparações.

Testes de transição usam permutação de toda a sequência, evitando tratar pares
sobrepostos como observações independentes. Testes são exploratórios; repetir
testes após cada rodada não cria um teste sequencial com nível global de 5%.
"""

from collections import Counter, defaultdict
from datetime import datetime
from math import log2

import numpy as np

from .common import LABELS, NO_EVIDENCE, THEORETICAL, holm, normalize, wilson


def transition_statistic(values: np.ndarray) -> float:
    n = len(values)
    counts = np.bincount(values, minlength=3)
    matrix = np.bincount(values[:-1] * 3 + values[1:], minlength=9).reshape(3, 3)
    expected = np.outer(counts / n, counts / n) * (n - 1)
    mask = expected > 0
    return float(np.sum((matrix[mask] - expected[mask]) ** 2 / expected[mask]))


class StatisticalAnalysisEngine:
    def __init__(self, seed: int = 42, simulations: int = 199, max_inference: int = 5000):
        if simulations < 99 or max_inference < 30:
            raise ValueError("Use pelo menos 99 simulações e limite de inferência >= 30")
        self.seed, self.simulations, self.max_inference = seed, simulations, max_inference

    def analyze(self, results, timestamps=None, sessions=None) -> dict:
        records = list(results)
        values = normalize(records)
        n = len(values)
        counts = Counter(values)
        relative = {side: counts[side] / n if n else 0.0 for side in LABELS}
        entropy = -sum(p * log2(p) for p in relative.values() if p)
        rng = np.random.default_rng(self.seed)
        # Limite explícito de CPU. Estatística descritiva ainda usa todo o histórico.
        inference = values[-self.max_inference:]
        encoded = np.array([LABELS.index(s) for s in inference], dtype=np.int8)
        sample_n = len(encoded)
        report = {"n": n, "inference_n": sample_n, "inference_scope": "últimas rodadas" if n > sample_n else "histórico completo",
                  "frequencies": {side: counts[side] for side in LABELS},
                  "relative": relative, "theoretical": dict(THEORETICAL),
                  "confidence_intervals": {side: wilson(counts[side], n) for side in LABELS},
                  "confidence_note": "Wilson marginal 95% para frequências sob hipótese iid; não precisão de previsão. Dependência pode invalidar estes intervalos.",
                  "entropy": entropy, "entropy_maximum": log2(3),
                  "goodness_of_fit": {"status": "Amostra insuficiente", "p_value": None},
                  "independence": {"status": "Amostra insuficiente", "p_value": None},
                  "autocorrelation": self._autocorrelation(encoded),
                  "time_groups": {}, "conclusion": NO_EVIDENCE,
                  "warning": "Análises exploratórias; p-valores não medem precisão. Repetidas consultas não são corrigidas no tempo."}
        p_values = {}
        if sample_n >= 30:
            observed = np.bincount(encoded, minlength=3)
            expected = sample_n * np.array([THEORETICAL[s] for s in LABELS])
            statistic = float(np.sum((observed - expected) ** 2 / expected))
            simulated = rng.multinomial(sample_n, list(THEORETICAL.values()), size=self.simulations)
            scores = np.sum((simulated - expected) ** 2 / expected, axis=1)
            p = float((1 + np.count_nonzero(scores >= statistic - 1e-12)) / (self.simulations + 1))
            report["goodness_of_fit"] = {"status": "Calculado", "statistic": statistic, "p_value": p,
                                         "method": "Monte Carlo multinomial, H0: quatro dados justos", "n": sample_n,
                                         "simulations": self.simulations}
            p_values["goodness_of_fit"] = p
            if len(set(inference)) >= 2:
                serial_score = transition_statistic(encoded)
                scores = [transition_statistic(rng.permutation(encoded)) for _ in range(self.simulations)]
                p = (1 + sum(score >= serial_score - 1e-12 for score in scores)) / (self.simulations + 1)
                report["independence"] = {"status": "Calculado", "statistic": serial_score, "p_value": p,
                                           "method": "Permutação global da sequência; transições sobrepostas preservadas",
                                           "n": sample_n, "simulations": self.simulations}
                p_values["independence"] = p
            else:
                report["independence"]["status"] = "Variação insuficiente: uma categoria apenas"
        if timestamps is None and records and not isinstance(records[0], str):
            timestamps = [getattr(record, "timestamp_local", None) for record in records]
        if sessions is None and records and not isinstance(records[0], str):
            sessions = [getattr(record, "session_id", "") for record in records]
        if sessions is not None:
            sessions = list(sessions)
            if len(sessions) != n:
                raise ValueError("Cada resultado deve ter sua sessão correspondente")
        if timestamps is not None:
            timestamps = list(timestamps)
            if len(timestamps) != n:
                raise ValueError("Cada resultado deve ter seu timestamp correspondente")
            report["time_groups"] = self._time_groups(values[-sample_n:] if sample_n else [],
                                                       timestamps[-sample_n:] if sample_n else [], rng,
                                                       sessions[-sample_n:] if sessions is not None and sample_n else None)
            for key, group in report["time_groups"].items():
                if group.get("p_value") is not None:
                    p_values[f"time_{key}"] = group["p_value"]
        adjusted = holm(p_values)
        report["multiple_comparisons"] = {"method": "Holm", "family_size": len(adjusted),
                                           "adjusted_p_values": adjusted, "alpha": 0.05}
        for key in ("goodness_of_fit", "independence"):
            if key in adjusted:
                report[key]["adjusted_p_value"] = adjusted[key]
        for key, group in report["time_groups"].items():
            if f"time_{key}" in adjusted:
                group["adjusted_p_value"] = adjusted[f"time_{key}"]
        if any(p <= 0.05 for p in adjusted.values()):
            report["descriptive_alert"] = ("Desvio exploratório detectado após Holm nesta consulta. "
                                            "Audite captura e fonte; não implica capacidade preditiva.")
        else:
            report["descriptive_alert"] = "Sem desvio detectado pelos testes disponíveis nesta consulta."
        return report

    def _autocorrelation(self, encoded: np.ndarray) -> dict:
        output = {}
        for category, label in enumerate(LABELS):
            series = (encoded == category).astype(float)
            lags = {}
            for lag in (1, 2, 3, 5):
                a, b = series[:-lag], series[lag:]
                lags[lag] = (float(np.corrcoef(a, b)[0, 1])
                             if len(a) >= 3 and np.std(a) > 0 and np.std(b) > 0 else None)
            output[label] = lags
        return output

    def _time_groups(self, values, timestamps, rng, sessions=None) -> dict:
        groups = {"hour": [], "weekday": [], "period": []}
        if sessions is not None:
            groups["session"] = []
        valid_values = []
        for i, (side, stamp) in enumerate(zip(values, timestamps)):
            try:
                dt = datetime.fromisoformat(stamp) if isinstance(stamp, str) else stamp
                if not isinstance(dt, datetime) or dt.utcoffset() is None:
                    continue
            except (ValueError, TypeError):
                continue
            valid_values.append(LABELS.index(side))
            groups["hour"].append(dt.hour)
            groups["weekday"].append(dt.weekday())
            groups["period"].append(dt.hour // 6)
            if sessions is not None:
                groups["session"].append(str(sessions[i]))
        encoded = np.asarray(valid_values, dtype=np.int8)
        output = {}
        for name, assignments in groups.items():
            unique = sorted(set(assignments))
            counts = {str(group): {s: 0 for s in LABELS} for group in unique}
            for side, group in zip(encoded, assignments):
                counts[str(group)][LABELS[side]] += 1
            report = {"counts": counts, "n": len(encoded), "p_value": None,
                      "status": "Amostra/grupos insuficientes", "note": "Associação observada não estabelece causa por horário."}
            sizes = Counter(assignments)
            # Não realizamos teste em dezenas de grupos com uma única observação.
            if len(unique) >= 2 and len(encoded) >= 60 and min(sizes.values()) >= 10 and len(set(encoded)) > 1:
                codes = np.array([unique.index(g) for g in assignments])
                shape = (len(unique), 3)
                expected = np.outer(np.bincount(codes), np.bincount(encoded, minlength=3)) / len(encoded)
                mask = expected > 0

                def score(sequence):
                    table = np.bincount(codes * 3 + sequence, minlength=len(unique) * 3).reshape(shape)
                    return float(np.sum((table[mask] - expected[mask]) ** 2 / expected[mask]))

                observed = score(encoded)
                p = (1 + sum(score(rng.permutation(encoded)) >= observed - 1e-12
                             for _ in range(self.simulations))) / (self.simulations + 1)
                report.update(p_value=p, statistic=observed, status="Calculado", method="Permutação sob H0 iid")
            output[name] = report
        return output

    def compare_samples(self, first, second) -> dict:
        """Compara duas amostras distintas por permutação, sem hipótese assintótica."""
        a, b = normalize(first), normalize(second)
        if min(len(a), len(b)) < 30:
            return {"status": "Amostra insuficiente", "p_value": None}
        rng = np.random.default_rng(self.seed)
        encoded = np.array([LABELS.index(s) for s in a + b])
        n = len(a)

        def score(values):
            return float(np.sum((np.bincount(values[:n], minlength=3) / n
                                 - np.bincount(values[n:], minlength=3) / len(b)) ** 2))

        observed = score(encoded)
        p = (1 + sum(score(rng.permutation(encoded)) >= observed - 1e-12
                     for _ in range(self.simulations))) / (self.simulations + 1)
        return {"status": "Calculado", "statistic": observed, "p_value": p,
                "n_first": len(a), "n_second": len(b), "method": "Permutação de duas amostras sob H0 iid",
                "note": "Comparação exploratória isolada; incluir p na família Holm ao testar múltiplas janelas."}

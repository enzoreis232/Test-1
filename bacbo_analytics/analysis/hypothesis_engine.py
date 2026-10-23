"""Avaliação cronológica de hipóteses fixadas antes da observação dos dados."""

import numpy as np

from .common import NO_EVIDENCE, THEORETICAL, holm, normalize, wilson


class HypothesisEvaluationEngine:
    def __init__(self, surf_trigger: int = 4, chess_trigger: int = 4, seed: int = 42):
        if min(surf_trigger, chess_trigger) < 2:
            raise ValueError("Gatilhos devem ser pelo menos 2")
        self.surf_trigger, self.chess_trigger, self.seed = surf_trigger, chess_trigger, seed

    def evaluate(self, results) -> dict:
        values = normalize(results)
        n = len(values)
        split_a, split_b = int(n * 0.6), int(n * 0.8)
        partitions = {"development": (0, split_a), "validation": (split_a, split_b), "test": (split_b, n)}
        predictions = {"surf_continuation": [], "alternation_continuation": []}
        # A predição de i somente consulta posições estritamente anteriores a i.
        for i in range(n):
            surf = values[max(0, i - self.surf_trigger):i]
            if len(surf) == self.surf_trigger and surf[0] in ("P", "B") and len(set(surf)) == 1:
                predictions["surf_continuation"].append((i, surf[-1] == values[i]))
            chess = values[max(0, i - self.chess_trigger - 1):i]
            if (len(chess) == self.chess_trigger + 1 and all(s in ("P", "B") for s in chess)
                    and all(a != b for a, b in zip(chess, chess[1:]))):
                prediction = "B" if chess[-1] == "P" else "P"
                predictions["alternation_continuation"].append((i, prediction == values[i]))
        rng = np.random.default_rng(self.seed)
        hypotheses, p_values = {}, {}
        baseline = THEORETICAL["P"]
        for name, events in predictions.items():
            report = {}
            for partition, (start, end) in partitions.items():
                outcomes = [ok for i, ok in events if start <= i < end]
                total, success = len(outcomes), sum(outcomes)
                ci = wilson(success, total)
                item = {"n": total, "successes": success, "frequency": success / total if total else None,
                        "expected": baseline, "confidence_interval": ci, "p_value": None,
                        "interval_method": ("Faixa descritiva de Wilson calculada como referência iid; "
                                            "gatilhos sobrepostos podem produzir dependência, portanto "
                                            "não se afirma cobertura nominal de 95% para esta faixa."),
                        "status": "Desenvolvimento descritivo" if partition == "development" else "Amostra insuficiente"}
                # Eventos disparados por histórico sobreposto não são iid. Um teste
                # binomial simples seria inadequado. A inferência usa Monte Carlo
                # de sequências completas e reexecuta o detector de gatilhos.
                report[partition] = item
            hypotheses[name] = report
        # Inferência por reamostragem de sequências iid com mesmos comprimentos.
        # Os detectores e as partições permanecem fixos. A família contém sempre
        # quatro comparações, inclusive quando alguma não possui amostra mínima.
        if n >= 150:
            observed = {f"{h}:{p}": r[p]["frequency"] for h, r in hypotheses.items()
                        for p in ("validation", "test") if r[p]["n"] >= 30}
            simulated_scores = {key: [] for key in observed}
            for _ in range(199 if observed and n <= 20_000 else 0):
                # Apenas inferência limitada; históricos maiores são explicitamente
                # descritivos para evitar bloquear trabalhadores por tempo excessivo.
                simulated = rng.choice(("P", "B", "T"), size=n, p=list(THEORETICAL.values())).tolist()
                events = self._events(simulated)
                for key in observed:
                    name, partition = key.split(":")
                    start, end = partitions[partition]
                    sample = [ok for i, ok in events[name] if start <= i < end]
                    if sample:
                        simulated_scores[key].append(sum(sample) / len(sample))
            for key, observed_frequency in observed.items():
                scores = simulated_scores[key]
                if len(scores) < 99:
                    continue
                name, partition = key.split(":")
                p = (1 + sum(value >= observed_frequency for value in scores)) / (len(scores) + 1)
                p_values[key] = p
                hypotheses[name][partition].update(p_value=p, status="Calculado",
                                                   method="Monte Carlo de sequências iid; gatilhos reaplicados",
                                                   simulations=len(scores))
        family = {f"{name}:{partition}": p_values.get(f"{name}:{partition}", 1.0)
                  for name in hypotheses for partition in ("validation", "test")}
        corrected_family = holm(family)
        adjusted = {key: corrected_family[key] for key in p_values}
        replicated = []
        for name, report in hypotheses.items():
            for partition in ("validation", "test"):
                key = f"{name}:{partition}"
                if key in adjusted:
                    report[partition]["adjusted_p_value"] = adjusted[key]
            if all(adjusted.get(f"{name}:{partition}", 1) <= 0.05
                   and (report[partition]["frequency"] or 0) > baseline
                   for partition in ("validation", "test")):
                replicated.append(name)
        status = ("Desvio replicado no recorte reservado; exige replicação prospectiva independente."
                  if replicated else NO_EVIDENCE)
        return {"status": status, "partitions": {k: {"start": a, "end": b, "n": b - a}
                                                  for k, (a, b) in partitions.items()},
                "hypotheses": hypotheses, "baseline": baseline, "replicated": replicated,
                "multiple_comparisons": {"method": "Holm", "family_size": len(family),
                                         "adjusted_p_values": adjusted},
                "warning": ("Hipóteses pré-fixadas; dados 60/20/20. Empates contam como erro para lado P/B. "
                            "Esta avaliação é retrospectiva, sem retorno financeiro ou recomendação. "
                            "Alterar gatilhos depois de olhar teste invalida seu uso como prova independente. "
                            "Faixas de Wilson são referências descritivas iid: não há cobertura nominal "
                            "garantida com gatilhos sobrepostos; conclusões usam simulações da sequência completa. "
                            "Nenhuma inferência de hipóteses é calculada acima de 20.000 rodadas.")}

    def _events(self, values):
        events = {"surf_continuation": [], "alternation_continuation": []}
        run_side, run_length, alternating = None, 0, 0
        for i, side in enumerate(values):
            if run_side in ("P", "B") and run_length >= self.surf_trigger:
                events["surf_continuation"].append((i, side == run_side))
            if alternating >= self.chess_trigger and i:
                predicted = "B" if values[i - 1] == "P" else "P"
                events["alternation_continuation"].append((i, side == predicted))
            if i and side in ("P", "B") and values[i - 1] in ("P", "B") and side != values[i - 1]:
                alternating += 1
            else:
                alternating = 0
            if side == run_side:
                run_length += 1
            else:
                run_side, run_length = side, 1
        return events

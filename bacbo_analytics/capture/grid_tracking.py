"""Rastreamento conservador de mudanças sem transformar deslocamentos em rodadas."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .calibration import CaptureCalibration
from .image_processor import GridObservation


@dataclass(frozen=True)
class TrackingResult:
    new_results: tuple[str, ...] = ()
    status: str = "WAITING_CONFIRMATION"
    message: str = ""
    baseline: bool = False


class GridTrackingEngine:
    def __init__(self, calibration: CaptureCalibration):
        self.calibration = calibration
        self.reset()

    def reset(self) -> None:
        """Aceita novo ponto de referência, sem importar resultados visíveis antigos."""
        self.previous: tuple[str, ...] | None = None
        self.frame_shape: tuple[int, int] | None = None
        self.candidate: tuple[str, ...] | None = None
        self.confirmation_count = 0
        self.suspended = False
        self.states: deque[tuple[str, ...]] = deque(maxlen=100)
        self.duplicates_avoided = 0
        self.discarded_reads = 0

    def suspend(self, message: str) -> TrackingResult:
        self.suspended = True
        return TrackingResult(status="RECALIBRATE", message=message)

    def update(self, observation: GridObservation) -> TrackingResult:
        config = self.calibration
        if self.suspended:
            return TrackingResult(status="RECALIBRATE", message="Inserção suspensa: recalibre ou confirme nova referência")
        if config.layout != "chronological" or config.tie_behavior != "separate":
            return TrackingResult(status="UNSUPPORTED", message="Layout exige adaptador específico; captura não registrada")
        if self.frame_shape is not None and observation.frame_shape != self.frame_shape:
            return self.suspend("Resolução ou escala da região mudou; selecione e calibre novamente")
        self.frame_shape = observation.frame_shape
        if not observation.valid or "UNKNOWN" in observation.cells:
            self.candidate = None
            self.confirmation_count = 0
            self.discarded_reads += 1
            return TrackingResult(message=observation.message or "Leitura incerta; nenhum resultado inserido")
        if len(observation.cells) != config.rows * config.columns:
            return self.suspend("Quantidade de células mudou; recalibração necessária")
        if observation.cells != self.candidate:
            self.candidate = observation.cells
            self.confirmation_count = 1
        else:
            self.confirmation_count += 1
        if self.confirmation_count < config.confirmations:
            return TrackingResult(message=f"Confirmando quadro ({self.confirmation_count}/{config.confirmations})")
        sequence = observation.sequence
        if self.previous is None:
            self.previous = sequence
            self.states.append(sequence)
            return TrackingResult(status="BASELINE", message="Referência sincronizada; histórico anterior não importado", baseline=True)
        if sequence == self.previous:
            self.duplicates_avoided += 1
            return TrackingResult(status="SYNCED", message="Grade inalterada; nenhuma nova rodada")
        previous = self.previous
        capacity = config.rows * config.columns
        # Células antes vazias ancoram inequivocamente o acréscimo em grade parcial.
        if len(sequence) > len(previous) and sequence[:len(previous)] == previous:
            new_results = sequence[len(previous):]
        elif len(previous) == capacity and len(sequence) == capacity and config.scroll_mode == "scroll":
            overlaps = [length for length in range(config.min_overlap, len(previous))
                        if previous[-length:] == sequence[:length]]
            if len(overlaps) != 1:
                return self.suspend("Deslocamento ambíguo ou sem sobreposição suficiente; lacuna não será preenchida")
            new_results = sequence[overlaps[0]:]
        else:
            return self.suspend("Transformação não confirmada; preserve o histórico e confirme nova referência")
        if len(new_results) > config.max_new_results:
            return self.suspend("Muitas mudanças entre capturas; possível perda de sincronização")
        self.previous = sequence
        self.states.append(sequence)
        if len(new_results) > 1:
            return TrackingResult(new_results, "RECOVERED",
                                  f"{len(new_results)} resultados visíveis recuperados por alinhamento único; horário individual desconhecido")
        return TrackingResult(new_results, "SYNCED", "Novo resultado confirmado visualmente")


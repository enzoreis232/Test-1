#!/usr/bin/env python3
"""Bac Bo: análise descritiva, sinais heurísticos e apostas exclusivamente simuladas.

Python 3.11+. Instale: python -m pip install -r requirements.txt
Execute: python bacbo_bot.py
Teste rápido: python bacbo_bot.py --rodadas 100 --intervalo 0 --seed 42
Telegram opcional: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no ambiente.

Não existe precisão preditiva demonstrada aqui: dados justos são independentes.
Surf, xadrez e atraso de empate descrevem o passado; não criam vantagem.
Martingale aumenta a exposição e não elimina a expectativa negativa.
Pagamentos abaixo seguem as regras fornecidas; valide a mesa antes de integrar.
Não há execução de apostas reais, scraping ou interceptação neste script.
O estado da sessão é mantido em memória: uma nova execução inicia nova simulação.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import random
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol
from zoneinfo import ZoneInfo

import requests

LOG = logging.getLogger("bacbo")
ZERO = Decimal("0.00")
CENTAVO = Decimal("0.01")
# Há 146 empates entre 6**4 combinações equiprováveis dos quatro dados.
PROB_EMPATE = 146 / 1296
PAYOUT_EMPATE = {2: 88, 3: 25, 4: 10, 5: 6, 6: 4, 7: 4,
                 8: 4, 9: 6, 10: 10, 11: 25, 12: 88}


def dinheiro(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def oposto(lado: str) -> str:
    if lado not in ("P", "B"):
        raise ValueError("Lado deve ser P ou B")
    return "B" if lado == "P" else "P"


@dataclass(frozen=True)
class Config:
    banca_inicial: Decimal = Decimal("1000.00")
    aposta_base: Decimal = Decimal("10.00")
    # Metas são lucro/prejuízo acumulado em reais, relativos à banca inicial.
    stop_win: Decimal = Decimal("100.00")
    stop_loss: Decimal = Decimal("200.00")
    gatilho_surf: int = 4
    # Quatro alternâncias exigem cinco resultados: P-B-P-B-P.
    gatilho_xadrez: int = 4
    max_gales: int = 1
    protecao_empate: Decimal = Decimal("0.10")
    contra_tendencia: bool = False
    quebrar_xadrez: bool = False
    historico_maximo: int = 50
    intervalo: float = 30.0
    # Modo conservador fixa 4:1; modo tabela usa a soma efetivamente observada.
    payout_tabela: bool = False
    atraso_z: float = 2.0
    fuso: str = "America/Fortaleza"
    telegram_token: str = ""
    telegram_chat_id: str = ""

    def __post_init__(self) -> None:
        for nome in ("banca_inicial", "aposta_base", "stop_win", "stop_loss"):
            valor = getattr(self, nome)
            if not isinstance(valor, Decimal) or not valor.is_finite() or valor <= 0:
                raise ValueError(f"{nome} deve ser Decimal positivo e finito")
            if valor != dinheiro(valor):
                raise ValueError(f"{nome} deve ter no máximo duas casas decimais")
        if not isinstance(self.protecao_empate, Decimal):
            raise ValueError("protecao_empate deve ser Decimal")
        if not self.protecao_empate.is_finite() or not ZERO <= self.protecao_empate <= 1:
            raise ValueError("protecao_empate deve estar entre 0 e 1")
        for nome in ("gatilho_surf", "gatilho_xadrez", "historico_maximo", "max_gales"):
            if type(getattr(self, nome)) is not int:
                raise ValueError(f"{nome} deve ser inteiro")
        if self.max_gales not in (0, 1, 2):
            raise ValueError("max_gales deve ser 0, 1 ou 2")
        if min(self.gatilho_surf, self.gatilho_xadrez) < 2:
            raise ValueError("Gatilhos devem ser pelo menos 2")
        if self.historico_maximo < max(self.gatilho_surf, self.gatilho_xadrez + 1):
            raise ValueError("Histórico insuficiente para os gatilhos")
        if not math.isfinite(self.intervalo) or self.intervalo < 0:
            raise ValueError("Intervalo deve ser finito e não negativo")
        if not math.isfinite(self.atraso_z) or self.atraso_z <= 0:
            raise ValueError("atraso_z deve ser finito e positivo")
        if self.aposta_base > self.banca_inicial:
            raise ValueError("Aposta base maior que a banca")
        if bool(self.telegram_token) != bool(self.telegram_chat_id):
            raise ValueError("Configure token e chat ID juntos")
        ZoneInfo(self.fuso)


@dataclass(frozen=True)
class Rodada:
    id: str
    instante: datetime
    player: tuple[int, int]
    banker: tuple[int, int]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Rodada sem identificador")
        if not isinstance(self.instante, datetime) or self.instante.utcoffset() is None:
            raise ValueError("Timestamp deve conter fuso horário")
        for par in (self.player, self.banker):
            if not isinstance(par, tuple) or len(par) != 2:
                raise ValueError("Cada lado deve conter dois dados")
            if any(type(d) is not int or not 1 <= d <= 6 for d in par):
                raise ValueError("Dados devem ser inteiros entre 1 e 6")

    @property
    def resultado(self) -> str:
        p, b = sum(self.player), sum(self.banker)
        return "P" if p > b else "B" if b > p else "T"


class FonteRodadas(Protocol):
    def proxima(self) -> Rodada:
        """Retorna somente uma rodada encerrada e validada."""
        ...


class FonteSimulada:
    """Simula os quatro dados, preservando a probabilidade correta de empate."""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.contador = 0

    def proxima(self) -> Rodada:
        self.contador += 1
        dados = [self.rng.randint(1, 6) for _ in range(4)]
        return Rodada(str(self.contador), datetime.now(timezone.utc),
                      (dados[0], dados[1]), (dados[2], dados[3]))


class FonteAutorizada:
    """Ponto de extensão para API, Playwright ou WebSocket autorizado.

    Implemente autenticação, timeout, reconexão, validação do esquema e sequência
    de IDs do provedor. Retorne os quatro dados, ID único e horário UTC. Nunca
    emita resultados parciais nem reproduza rodadas antigas após reconexão.
    Uma lacuna no fluxo exige reconciliar o estado antes de gerar novos sinais.
    """

    def proxima(self) -> Rodada:
        raise NotImplementedError("Configure uma fonte de dados autorizada")


class DataEngine:
    def __init__(self, config: Config):
        self.historico: deque[str] = deque(maxlen=config.historico_maximo)
        self.ids: deque[str] = deque(maxlen=config.historico_maximo * 4)
        self.ids_vistos: set[str] = set()
        self.ultimo_instante: datetime | None = None
        self.contagem_horaria: Counter[tuple[int, str]] = Counter()
        self.fuso = ZoneInfo(config.fuso)
        self.sem_empate = 0
        self.empate_observado = False
        self.total = 0

    def adicionar(self, rodada: Rodada) -> bool:
        if not isinstance(rodada, Rodada):
            raise ValueError("Fonte retornou dados sem validação")
        if rodada.id in self.ids_vistos:
            LOG.warning("Rodada duplicada ignorada: %s", rodada.id)
            return False
        if self.ultimo_instante and rodada.instante < self.ultimo_instante:
            raise ValueError("Rodada fora de ordem; reconcilie a fonte")
        if len(self.ids) == self.ids.maxlen:
            self.ids_vistos.remove(self.ids.popleft())
        self.ids.append(rodada.id)
        self.ids_vistos.add(rodada.id)
        self.ultimo_instante = rodada.instante
        self.historico.append(rodada.resultado)
        self.total += 1
        hora = rodada.instante.astimezone(self.fuso).hour
        self.contagem_horaria[(hora, rodada.resultado)] += 1
        if rodada.resultado == "T":
            self.sem_empate = 0
            self.empate_observado = True
        else:
            self.sem_empate += 1
        LOG.info("Rodada=%s P=%s B=%s resultado=%s hora_local=%02d",
                 rodada.id, rodada.player, rodada.banker, rodada.resultado, hora)
        return True


@dataclass(frozen=True)
class Sinal:
    lado: str
    padrao: str


class StrategyEngine:
    def __init__(self, config: Config):
        self.config = config

    def surf(self, historico: list[str]) -> Sinal | None:
        trecho = historico[-self.config.gatilho_surf:]
        if (len(trecho) == self.config.gatilho_surf and trecho[0] in ("P", "B")
                and len(set(trecho)) == 1):
            lado = oposto(trecho[-1]) if self.config.contra_tendencia else trecho[-1]
            return Sinal(lado, "Surf")
        return None

    def xadrez(self, historico: list[str]) -> Sinal | None:
        tamanho = self.config.gatilho_xadrez + 1
        trecho = historico[-tamanho:]
        if (len(trecho) == tamanho and all(x in ("P", "B") for x in trecho)
                and all(a != b for a, b in zip(trecho, trecho[1:]))):
            lado = trecho[-1] if self.config.quebrar_xadrez else oposto(trecho[-1])
            return Sinal(lado, "Xadrez")
        return None

    def analisar(self, dados: DataEngine) -> Sinal | None:
        # Empates interrompem os padrões; não são removidos artificialmente.
        historico = list(dados.historico)
        return self.surf(historico) or self.xadrez(historico)

    def atraso_empate(self, dados: DataEngine) -> str:
        # Geométrica: número de não empates antes do próximo empate.
        media = (1 - PROB_EMPATE) / PROB_EMPATE
        desvio = math.sqrt(1 - PROB_EMPATE) / PROB_EMPATE
        z = (dados.sem_empate - media) / desvio
        if z < self.config.atraso_z:
            return ""
        origem = "desde o último empate" if dados.empate_observado else "desde o início da coleta"
        return (f"📊 {dados.sem_empate} rodadas sem empate ({origem}); z={z:.2f}. "
                "Medida descritiva de uma distribuição assimétrica. "
                f"Com dados independentes, P(T) segue {PROB_EMPATE:.2%}; "
                "isso não é sinal de entrada em empate.")


@dataclass(frozen=True)
class Aposta:
    lado: str
    principal: Decimal
    empate: Decimal
    gale: int
    padrao: str

    @property
    def total(self) -> Decimal:
        return self.principal + self.empate


@dataclass(frozen=True)
class Liquidacao:
    aposta: Aposta
    retorno: Decimal
    lucro: Decimal
    lucro_ciclo: Decimal
    fim_ciclo: bool


class BetManager:
    """Contabilidade com Decimal. Toda entrada se refere à PRÓXIMA rodada."""

    def __init__(self, config: Config):
        self.config = config
        self.banca = config.banca_inicial
        self.pendente: Aposta | None = None
        self.lucro_ciclo = ZERO

    @property
    def lucro_total(self) -> Decimal:
        return self.banca - self.config.banca_inicial

    def stop(self) -> str | None:
        if self.lucro_total >= self.config.stop_win:
            return "Stop Win"
        if self.lucro_total <= -self.config.stop_loss:
            return "Stop Loss"
        return None

    def abrir(self, sinal: Sinal, gale: int = 0) -> str | None:
        if self.pendente:
            raise RuntimeError("Já existe aposta pendente")
        if sinal.lado not in ("P", "B") or not 0 <= gale <= self.config.max_gales:
            raise ValueError("Sinal ou nível de Gale inválido")
        motivo = self.stop()
        if motivo:
            return motivo
        principal = dinheiro(self.config.aposta_base * (2 ** gale))
        # Proteção sempre calculada sobre a base, conforme configuração solicitada.
        empate = dinheiro(self.config.aposta_base * self.config.protecao_empate)
        aposta = Aposta(sinal.lado, principal, empate, gale, sinal.padrao)
        if aposta.total > self.banca:
            return "Banca insuficiente"
        # Recusa uma entrada cuja perda integral ultrapassaria o limite definido.
        if self.lucro_total - aposta.total < -self.config.stop_loss:
            return "Próxima exposição ultrapassaria Stop Loss"
        if gale == 0:
            self.lucro_ciclo = ZERO
        self.pendente = aposta
        # Reserva é representada pela aposta pendente. Débito líquido só ao liquidar.
        LOG.info("Aposta SIMULADA aberta: %s banca=%s", aposta, self.banca)
        return None

    def liquidar(self, rodada: Rodada) -> Liquidacao:
        aposta = self.pendente
        if aposta is None:
            raise RuntimeError("Nenhuma aposta pendente")
        if rodada.resultado == "T":
            multiplicador = PAYOUT_EMPATE[sum(rodada.player)] if self.config.payout_tabela else 4
            # 90% é devolução, não lucro. No empate, proteção recebe stake + prêmio.
            retorno = dinheiro(aposta.principal * Decimal("0.90"))
            retorno += dinheiro(aposta.empate * (multiplicador + 1))
        elif rodada.resultado == aposta.lado:
            retorno = aposta.principal * 2  # principal devolvido + prêmio 1:1
        else:
            retorno = ZERO
        lucro = retorno - aposta.total
        self.banca += lucro
        self.lucro_ciclo += lucro
        self.pendente = None
        # Um empate positivo pode encerrar o ciclo; perdas parciais podem ir ao Gale.
        # Dobrar não garante recuperar perdas e custos da proteção.
        fim = self.lucro_ciclo >= ZERO or aposta.gale >= self.config.max_gales
        LOG.info("Liquidação rodada=%s gale=%d custo=%s retorno=%s "
                 "lucro=%s ciclo=%s banca=%s", rodada.id, aposta.gale,
                 aposta.total, retorno, lucro, self.lucro_ciclo, self.banca)
        return Liquidacao(aposta, retorno, lucro, self.lucro_ciclo, fim)


class NotificationEngine:
    def __init__(self, config: Config):
        self.token = config.telegram_token
        self.chat_id = config.telegram_chat_id
        self.session = requests.Session()
        # Não repetir POST automaticamente: timeout pode ocorrer após o envio.

    def enviar(self, mensagem: str) -> None:
        LOG.info("%s", mensagem)
        if not self.token:
            return
        try:
            response = self.session.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": mensagem},
                timeout=(5, 10), allow_redirects=False)
            if response.status_code != 200:
                LOG.warning("Telegram recusou mensagem: HTTP %d", response.status_code)
                return
            if response.json().get("ok") is not True:
                LOG.warning("Telegram não confirmou a mensagem")
        except (requests.RequestException, ValueError, AttributeError):
            # Não registrar exceção/URL/corpo: podem conter token ou dados privados.
            LOG.warning("Falha no Telegram; mensagem mantida apenas no log local")

    def fechar(self) -> None:
        self.session.close()


class BacBoBot:
    def __init__(self, config: Config, fonte: FonteRodadas):
        self.config = config
        self.fonte = fonte
        self.dados = DataEngine(config)
        self.estrategias = StrategyEngine(config)
        self.bets = BetManager(config)
        self.notificacoes = NotificationEngine(config)

    def entrada(self, sinal: Sinal, gale: int = 0) -> bool:
        motivo = self.bets.abrir(sinal, gale)
        if motivo:
            self.notificacoes.enviar(f"❌ RED — Operações interrompidas: {motivo}.")
            return False
        aposta = self.bets.pendente
        assert aposta is not None
        lado = "Player" if aposta.lado == "P" else "Banker"
        protecao = f"🛡️ Proteger Empate: R$ {aposta.empate}" if aposta.empate else "Sem proteção de empate"
        self.notificacoes.enviar(
            f"⚠️ ENTRADA CONFIRMADA [SIMULAÇÃO]: {lado} | {sinal.padrao}\n"
            f"Próxima rodada | R$ {aposta.principal} | G{gale} | "
            f"Até G{self.config.max_gales}\n{protecao}\n"
            "Sinal heurístico, sem vantagem preditiva demonstrada.")
        return True

    def processar(self, rodada: Rodada) -> bool:
        if not self.dados.adicionar(rodada):
            return True
        # Primeiro liquida a entrada já existente; só depois analisa a rodada atual.
        if self.bets.pendente:
            liquidacao = self.bets.liquidar(rodada)
            motivo = self.bets.stop()
            if liquidacao.fim_ciclo or motivo:
                if liquidacao.lucro_ciclo > ZERO:
                    mensagem = f"✅ GREEN — Lucro do ciclo R$ {liquidacao.lucro_ciclo} em G{liquidacao.aposta.gale}"
                elif liquidacao.lucro_ciclo == ZERO:
                    mensagem = "➖ Ciclo encerrado sem lucro nem prejuízo"
                else:
                    mensagem = f"❌ RED — Ciclo encerrado: R$ {liquidacao.lucro_ciclo}"
                self.notificacoes.enviar(f"{mensagem}\nBanca: R$ {self.bets.banca}")
            if motivo:
                self.notificacoes.enviar(f"🎯 META ATINGIDA: {motivo}. Parando operações.")
                return False
            if not liquidacao.fim_ciclo:
                return self.entrada(Sinal(liquidacao.aposta.lado, liquidacao.aposta.padrao),
                                    liquidacao.aposta.gale + 1)
        atraso = self.estrategias.atraso_empate(self.dados)
        if atraso:
            LOG.info("%s", atraso)
        sinal = self.estrategias.analisar(self.dados)
        return self.entrada(sinal) if sinal else True

    def executar(self, max_rodadas: int = 0) -> None:
        if type(max_rodadas) is not int or max_rodadas < 0:
            raise ValueError("Número de rodadas deve ser inteiro e não negativo")
        self.notificacoes.enviar("🔄 ANALISANDO MERCADO... [SIMULAÇÃO de dados independentes]")
        try:
            while True:
                inicio = time.monotonic()
                try:
                    rodada = self.fonte.proxima()
                except (requests.RequestException, TimeoutError, ConnectionError):
                    # Falha fechada: não avança Gale nem presume resultado perdido.
                    LOG.error("Fonte indisponível; interrompido para reconciliação")
                    break
                except (ValueError, TypeError, KeyError):
                    LOG.error("Dados corrompidos; interrompido para reconciliação")
                    break
                try:
                    continuar = self.processar(rodada)
                except ValueError:
                    LOG.error("Rodada inválida ou fora de ordem; processamento interrompido")
                    break
                if not continuar or (max_rodadas and self.dados.total >= max_rodadas):
                    break
                time.sleep(max(0, self.config.intervalo - (time.monotonic() - inicio)))
        except KeyboardInterrupt:
            LOG.info("Interrupção solicitada pelo usuário")
        finally:
            LOG.info("Fim: rodadas=%d banca_liquidada=%s lucro_liquidado=%s",
                     self.dados.total, self.bets.banca, self.bets.lucro_total)
            for hora in sorted({hora for hora, _ in self.dados.contagem_horaria}):
                contagens = {lado: self.dados.contagem_horaria[(hora, lado)] for lado in "PBT"}
                LOG.info("Horário %02d (%s), contagens descritivas: %s; sem previsão por horário",
                         hora, self.config.fuso, contagens)
            if self.bets.pendente:
                LOG.warning("Entrada simulada pendente sem liquidação: %s; "
                            "não incluída no lucro; sessão não é persistida", self.bets.pendente)
            self.notificacoes.fechar()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rodadas", type=int, default=0, help="0 = contínuo")
    parser.add_argument("--intervalo", type=float, default=30)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max-gales", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--payout-tabela", action="store_true")
    args = parser.parse_args()
    if args.rodadas < 0:
        parser.error("--rodadas não pode ser negativo")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Impede logs de bibliotecas HTTP de revelarem a URL contendo o token.
    logging.getLogger("urllib3").setLevel(logging.CRITICAL)
    try:
        config = Config(intervalo=args.intervalo, max_gales=args.max_gales,
                        payout_tabela=args.payout_tabela,
                        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""))
    except (ValueError, KeyError) as erro:
        parser.error(str(erro))
    BacBoBot(config, FonteSimulada(args.seed)).executar(args.rodadas)


if __name__ == "__main__":
    main()

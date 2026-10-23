"""Testes determinísticos da matemática, causalidade e validação do simulador."""
import itertools
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

from bacbo_bot import (BacBoBot, BetManager, Config, DataEngine, NotificationEngine,
                       Rodada, Sinal, StrategyEngine)


def rodada(lado, numero=1):
    pares = {"P": ((6, 6), (1, 1)), "B": ((1, 1), (6, 6)),
             "T": ((3, 4), (2, 5))}
    return Rodada(str(numero), datetime(2026, 1, 1, tzinfo=timezone.utc)
                  + timedelta(seconds=numero), *pares[lado])


class MatematicaTest(unittest.TestCase):
    def gerente(self, **kwargs):
        manager = BetManager(Config(**kwargs))
        self.assertIsNone(manager.abrir(Sinal("P", "teste")))
        return manager

    def test_vitoria_com_protecao(self):
        manager = self.gerente()
        resultado = manager.liquidar(rodada("P"))
        self.assertEqual(resultado.lucro, Decimal("9.00"))
        self.assertEqual(manager.banca, Decimal("1009.00"))

    def test_derrota_inclui_protecao(self):
        manager = self.gerente()
        self.assertEqual(manager.liquidar(rodada("B")).lucro, Decimal("-11.00"))

    def test_empate_sem_protecao_perde_dez_por_cento(self):
        manager = self.gerente(protecao_empate=Decimal("0"))
        self.assertEqual(manager.liquidar(rodada("T")).lucro, Decimal("-1.00"))

    def test_empate_com_protecao(self):
        manager = self.gerente()
        self.assertEqual(manager.liquidar(rodada("T")).lucro, Decimal("3.00"))

    def test_empate_extremo_tabela(self):
        manager = self.gerente(payout_tabela=True)
        r = Rodada("1", datetime.now(timezone.utc), (1, 1), (1, 1))
        self.assertEqual(manager.liquidar(r).lucro, Decimal("87.00"))

    def test_g1_recupera_com_custo_de_protecao(self):
        manager = self.gerente()
        manager.liquidar(rodada("B"))
        self.assertIsNone(manager.abrir(Sinal("P", "teste"), 1))
        self.assertEqual(manager.pendente.principal, Decimal("20.00"))
        resultado = manager.liquidar(rodada("P", 2))
        self.assertEqual(resultado.lucro_ciclo, Decimal("8.00"))
        self.assertTrue(resultado.fim_ciclo)

    def test_g2_e_limite(self):
        manager = self.gerente(max_gales=2)
        manager.liquidar(rodada("B"))
        manager.abrir(Sinal("P", "teste"), 1)
        manager.liquidar(rodada("B", 2))
        manager.abrir(Sinal("P", "teste"), 2)
        self.assertEqual(manager.pendente.principal, Decimal("40.00"))
        resultado = manager.liquidar(rodada("B", 3))
        self.assertEqual(resultado.lucro_ciclo, Decimal("-73.00"))
        self.assertTrue(resultado.fim_ciclo)

    def test_stop_preventivo(self):
        manager = BetManager(Config(stop_loss=Decimal("10")))
        self.assertIn("Stop Loss", manager.abrir(Sinal("P", "teste")))
        self.assertIsNone(manager.pendente)

    def test_banca_insuficiente(self):
        manager = BetManager(Config(banca_inicial=Decimal("10")))
        self.assertEqual(manager.abrir(Sinal("P", "teste")), "Banca insuficiente")

    def test_nao_sobrepoe_apostas(self):
        manager = self.gerente()
        with self.assertRaises(RuntimeError):
            manager.abrir(Sinal("B", "teste"))

    def test_probabilidades_exatas(self):
        contagem = {"P": 0, "B": 0, "T": 0}
        for a, b, c, d in itertools.product(range(1, 7), repeat=4):
            r = Rodada("1", datetime.now(timezone.utc), (a, b), (c, d))
            contagem[r.resultado] += 1
        self.assertEqual(contagem, {"P": 575, "B": 575, "T": 146})


class EstrategiaTest(unittest.TestCase):
    def test_surf_e_contratendencia(self):
        self.assertEqual(StrategyEngine(Config()).surf(list("PPPP")).lado, "P")
        self.assertEqual(StrategyEngine(Config(contra_tendencia=True))
                         .surf(list("PPPP")).lado, "B")

    def test_xadrez_quatro_alternancias(self):
        engine = StrategyEngine(Config())
        self.assertIsNone(engine.xadrez(list("PBPB")))
        self.assertEqual(engine.xadrez(list("PBPBP")).lado, "B")
        self.assertEqual(StrategyEngine(Config(quebrar_xadrez=True))
                         .xadrez(list("PBPBP")).lado, "P")

    def test_empate_interrompe_padroes(self):
        engine = StrategyEngine(Config())
        self.assertIsNone(engine.surf(list("PPPPTP")))
        self.assertIsNone(engine.xadrez(list("PBPBTP")))

    def test_fila_e_duplicatas(self):
        dados = DataEngine(Config(historico_maximo=5))
        for n in range(10):
            dados.adicionar(rodada("P", n))
        self.assertEqual(len(dados.historico), 5)
        self.assertFalse(dados.adicionar(rodada("P", 9)))
        self.assertEqual(dados.total, 10)

    def test_rejeita_dados_corrompidos(self):
        for par in ((0, 6), (True, 2), (7, 1), (1.0, 2)):
            with self.assertRaises(ValueError):
                Rodada("1", datetime.now(timezone.utc), par, (1, 1))

    def test_rejeita_ordem_invertida(self):
        dados = DataEngine(Config())
        dados.adicionar(rodada("P", 5))
        with self.assertRaises(ValueError):
            dados.adicionar(rodada("B", 4))

    def test_entrada_na_proxima_rodada(self):
        bot = BacBoBot(Config(intervalo=0), Mock())
        bot.notificacoes.enviar = Mock()
        try:
            for n in range(1, 5):
                bot.processar(rodada("P", n))
            self.assertEqual(bot.bets.banca, Decimal("1000.00"))
            self.assertEqual(bot.bets.pendente.lado, "P")
            bot.processar(rodada("B", 5))
            self.assertEqual(bot.bets.banca, Decimal("989.00"))
            self.assertEqual(bot.bets.pendente.gale, 1)
        finally:
            bot.notificacoes.fechar()

    def test_telegram_nao_expoe_token_em_log(self):
        import requests
        engine = NotificationEngine(Config(telegram_token="segredo", telegram_chat_id="123"))
        engine.session.post = Mock(side_effect=requests.ConnectionError("URL/segredo"))
        try:
            with self.assertLogs("bacbo", level="WARNING") as logs:
                engine.enviar("teste")
            self.assertNotIn("segredo", str(logs.output))
        finally:
            engine.fechar()


if __name__ == "__main__":
    unittest.main()

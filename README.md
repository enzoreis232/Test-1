# BAC BO ANALYTICS PRO

Aplicação desktop em português para observação de históricos visuais de Bac Bo,
armazenamento SQLite, correção manual e estudo estatístico. A aplicação nova fica
em `bacbo_analytics/`; o simulador anterior `bacbo_bot.py` foi preservado.

## Aplicativo Windows e download

O ambiente de desenvolvimento desta entrega é Linux. **Não foi gerado nem
validado aqui um executável Windows.** Não há um ZIP Windows pronto sem executar
a compilação em um runner Windows. Um arquivo com o código-fonte não é o
aplicativo Windows solicitado.

O workflow funcional está em
[.github/workflows/windows.yml](.github/workflows/windows.yml). Depois de os
arquivos estarem no GitHub, ele pode ser executado por **Actions → Windows desktop
package → Run workflow**; também executa em pushes/PRs para `main`.

Caminho exato do artefato após uma execução bem-sucedida:

1. `https://github.com/enzoreis232/Test-1/actions/workflows/windows.yml`
2. Abrir a execução concluída com sucesso.
3. **Artifacts → BacBoAnalyticsPro-Windows**.
4. O download do GitHub pode conter um ZIP externo. Extraí-lo revela
   `BacBoAnalyticsPro-Windows.zip`.
5. Extrair esse ZIP por completo e abrir
   `BacBoAnalyticsPro/BacBoAnalyticsPro.exe`.

Esse caminho descreve o workflow; não afirma que uma execução já ocorreu ou que
o artefato já existe. O usuário final não precisa instalar Python nem compilar.
Artefatos do Actions ficam retidos por 30 dias e podem exigir login no GitHub.

O pipeline instala dependências, executa os testes, compila com PyInstaller e
testa o executável congelado antes de publicar o ZIP. A verificação inclui saída
normal, plugins Qt e relatório `validacao-windows.json`. O executável não abre
um console Python e a distribuição inclui `_internal` e `LEIA-ME.txt`.

## Desenvolvimento

Requer Python 3.12 e ambiente gráfico para captura de uma tela real.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python main.py
python -m pytest
```

Testes da interface sem tela, quando suportados pelo sistema:

```sh
QT_QPA_PLATFORM=offscreen python main.py --smoke-test --data-dir /tmp/bacbo-smoke
```

Desenvolvedores em Windows podem executar `./scripts/package_windows.ps1` após
instalar `requirements-dev.txt`. O script recusa execução em outro sistema para
não produzir um binário Linux com nome de executável Windows.

## Fluxo de uso

1. Iniciar a demonstração. Rodadas são geradas com quatro dados independentes e
   identificadas como simulação.
2. Para uma captura real, abrir o histórico e selecionar a região visual da
   grade. A seleção usa coordenadas da tela; confira escalas/DPI e monitores.
3. Abrir a calibração, informar linhas/colunas, direção de preenchimento, posição
   mais recente e parâmetros de cor. As cores iniciais são perfis de teste,
   não medições de uma mesa real.
4. Conferir a imagem de diagnóstico e a classificação por célula. Ajustar os
   limiares se existirem leituras desconhecidas. Nunca substituir desconhecidos
   por um resultado arbitrário.
5. Iniciar observação. O primeiro quadro estável estabelece uma referência;
   resultados já visíveis não são importados automaticamente como novas rodadas.
6. Se houver animação, cor ambígua, escala diferente ou alinhamento inseguro,
   pausar e recalibrar. Lacunas não são preenchidas com resultados inventados.
7. Corrigir/validar/excluir resultados no editor. Conferir o recálculo e exportar
   o histórico quando necessário.

## Reconhecimento e integridade

O adaptador inicial suporta grades cronológicas regulares com ordem configurada
por linha/coluna. Grades de sequências, big roads e empates sobrepostos exigem
regras próprias; não são apresentados como compatíveis. O rastreamento compara
quadros estáveis e sobreposições visíveis, sem tratar todo deslocamento como
novas rodadas. Se vários alinhamentos são plausíveis, solicita intervenção.

Uma grade cheia e homogênea pode mudar sem qualquer alteração visual observável.
Nenhum algoritmo baseado somente nessas capturas pode descobrir esse evento
com segurança. O aplicativo não presume rodadas com base em um relógio de 30 s.

As classificações e limiares são calibráveis. Testes com imagens sintéticas
verificam comportamento determinístico, rejeição de ambiguidades e animações,
mas **não medem exatidão em uma interface real**. Para medir leitura real, reúna
capturas rotuladas manualmente, separe imagens de calibração e avaliação, e
conte desconhecidos separadamente de classificações incorretas. Não existe
percentual de precisão de produção declarado nesta entrega.

MSS captura pixels disponibilizados pelo sistema operacional. Tela bloqueada,
sessão remota, Wayland, restrições de permissão, HDR e mudanças de DPI podem
impedir ou alterar a captura. O software não contorna restrições de acesso.

## Estatística

As referências exatas para quatro dados justos são `575/1296` para Player e
Banker e `146/1296` para Tie. As análises distinguem estatística descritiva,
hipóteses e validação cronológica; padrões visuais não são garantias de previsão.
Empates são preservados como eventos individuais. Horários são agrupamentos
descritivos, sem inferência automática de causalidade. Amostras insuficientes ou
resultados inconclusivos são exibidos como tal.

Não há integração para apostas, login em cassino, interceptação de tráfego nem
envio de instruções de aposta. O módulo antigo continua sendo uma simulação
separada e não controla a aplicação de observação.

## Dados, segurança e notificações

O aplicativo usa uma pasta gravável do usuário dentro de AppData no Windows;
configurações, logs e SQLite não dependem da pasta do executável nem de privilégios
de administrador. O parâmetro `--data-dir` permite um diretório isolado para testes.

Notificações Telegram são opcionais, explícitas e somente informativas.
`TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` vêm do ambiente; nunca há valores de
credenciais no código ou no pacote. `.env.example` lista os nomes; não é carregado
automaticamente. Revise imagens e CSVs antes de compartilhar, pois podem conter
informações visíveis na tela.

## Validação executada no desenvolvimento

Na instância Linux de desenvolvimento:

- **130 testes automatizados passaram**, incluindo persistência, correção de
  histórico, rastreamento da grade, rejeição de cores ambíguas, padrões e
  experimentos estatísticos.
- O dashboard foi iniciado com o backend Qt `offscreen`; a demonstração processou
  aproximadamente **174 rodadas**, com verificação de persistência e encerramento.
- Uma captura da própria interface foi gerada e inspecionada.

Esses resultados validam os componentes exercitados nessa instância. O backend
`offscreen` não observa uma mesa real e não equivale a um teste do executável
Windows. O status da compilação e da execução do binário Windows deve ser
confirmado separadamente pela execução do workflow.

## Limites de validação da distribuição

Um smoke test automatizado do binário não substitui teste manual em Windows
10/11 com o monitor, escala e interface efetivamente usados. A captura de uma
mesa real, a calibração sobre imagens reais, a exatidão de leitura e o envio real
ao Telegram precisam de validação específica. O relatório final da execução
de desenvolvimento informa somente os testes que efetivamente rodaram.

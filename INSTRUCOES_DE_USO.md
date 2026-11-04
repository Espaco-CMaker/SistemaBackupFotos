# 📖 Manual de Instruções de Uso — CMaker Photo Commander

Bem-vindo ao **CMaker Photo Commander**! Este guia passo a passo foi elaborado para que você possa instalar, conectar seu iPhone (ou pasta local), visualizar miniaturas e transferir suas fotos e vídeos com máxima segurança, organização automática e praticidade.

---

## 📑 Índice
1. [Requisitos do Sistema](#1-requisitos-do-sistema)
2. [Como Instalar o Aplicativo](#2-como-instalar-o-aplicativo)
3. [Conectando o iPhone pela Primeira Vez](#3-conectando-o-iphone-pela-primeira-vez)
4. [Visão Geral da Interface](#4-visão-geral-da-interface)
5. [Navegação e Modos de Exibição](#5-navegação-e-modos-de-exibição)
6. [Seleção de Fotos e Tamanho Total](#6-seleção-de-fotos-e-tamanho-total)
7. [Diretório de Destino e Monitor de Espaço Livre](#7-diretório-de-destino-e-monitor-de-espaço-livre)
8. [Iniciando a Transferência / Download](#8-iniciando-a-transferência--download)
9. [Resolução de Conflitos e Duplicados](#9-resolução-de-conflitos-e-duplicados)
10. [Pausa e Cancelamento com Segurança](#10-pausa-e-cancelamento-com-segurança)
11. [Exclusão Segura de Mídias](#11-exclusão-segura-de-mídias)
12. [Resolução de Problemas Comuns (FAQ)](#12-resolução-de-problemas-comuns-faq)

---

## 1. Requisitos do Sistema

- **Sistema Operacional:** Windows 10 ou Windows 11 (64 bits).
- **Dispositivo Móvel Suportado:** Qualquer modelo de Apple iPhone conectado via cabo USB original ou certificado (Lightning ou USB-C).
- **Diretórios Locais:** Qualquer pasta no computador, HD externo, pen drive ou cartão SD.
- **Não requer:** iTunes, Python, Java ou drivers adicionais instalados.

---

## 2. Como Instalar o Aplicativo

Para instalar o aplicativo no computador do cliente de forma automática:

1. Baixe o arquivo **`Instalador_CMakerPhotoCommander_v2.8.0.exe`** (disponível na página de *Releases* do projeto no GitHub).
2. Dê um duplo clique sobre o instalador baixado.
3. Siga o assistente de instalação:
   - Escolha se deseja criar um atalho na Área de Trabalho.
   - Clique em **Instalar**.
4. Ao finalizar, clique em **Concluir**. O aplicativo abrirá imediatamente e estará disponível no seu Menu Iniciar e na Área de Trabalho com o ícone oficial da câmera.

> [!TIP]
> **Versão Portátil:** Se preferir não instalar nada, você também pode baixar o arquivo único **`CMakerPhotoCommander.exe`** e executá-lo diretamente de qualquer pasta ou pen drive.

---

## 3. Conectando o iPhone pela Primeira Vez

A comunicação com o iPhone utiliza a tecnologia nativa do Windows (MTP/WPD). Para que o Windows tenha permissão para ler as fotos:

```
[1. Conectar Cabo USB] ➔ [2. Desbloquear Tela] ➔ [3. Tocar em "Confiar"] ➔ [4. Digitar Código] ➔ [5. Conectado!]
```

1. **Conecte o cabo USB** no computador e no iPhone.
2. **Pegue o iPhone e DESBLOQUEIE A TELA** com seu Face ID, Touch ID ou código numérico.
3. Se aparecer na tela do iPhone o aviso:
   > *"Confiar neste Computador?"*
   Toque em **Confiar**.
4. Digite o código de desbloqueio do iPhone para confirmar a autorização.
5. No aplicativo, o status mudará para verde:
   `● Conectado: Apple iPhone`

> [!IMPORTANT]
> Se o iPhone estiver conectado mas com a tela bloqueada, o aplicativo avisará:
> `● iPhone USB Conectado (Tela Bloqueada no iOS)`
> Basta acender a tela do aparelho, desbloqueá-la e clicar no botão **`🔌 Conectar / Reconectar`** no topo da janela.

---

## 4. Visão Geral da Interface

A tela do aplicativo é dividida em três colunas inteligentes e redimensionáveis:

| Painel | Descrição |
| :--- | :--- |
| **Painel Esquerdo (Origem)** | Mostra todas as fotos e vídeos do iPhone ou da pasta local selecionada, com filtros por mês, busca por texto e modos de exibição. |
| **Painel Central (Inspetor & Vídeo)** | Exibe a miniatura da foto selecionada em alta qualidade, data de captura, tamanho real e localização GPS da cidade. Durante cópias, exibe o monitor de vídeo animado com a taxa de transferência instantânea em MB/s. |
| **Painel Direito (Destino Local)** | Mostra a pasta do seu computador onde as fotos serão salvas, a árvore de pastas organizadas por data e o monitor de espaço livre em disco em tempo real. |
| **Painel Inferior (Transferências)** | Abas com a fila de transferência, lista de arquivos concluídos, itens pulados/falhas e o log detalhado de comandos. |

---

## 5. Navegação e Modos de Exibição

Você pode alternar a qualquer momento a forma de visualizar suas fotos na caixa **"Exibição"** no topo de ambos os painéis:

- **`📑 Detalhes`:** Tabela completa estilo Windows Explorer com colunas de Seleção, Nome, Formato, Data, Hora, Tamanho e Pasta.
- **`📄 Lista`:** Visualização compacta, excelente para rolar rapidamente milhares de arquivos.
- **`🖼️ Miniaturas`:** Grade fluida de cards visuais com pré-visualização fotográfica e botão de seleção na base de cada card.
- **`🔍 Miniaturas Gigantes`:** Cards expandidos com fotos em alta definição para conferência rápida de nitidez.

### Ordenação por Colunas
Clique no cabeçalho de qualquer coluna (`Arquivo`, `Tamanho`, `Data`, `Sel`) para alternar entre ordem crescente (**`▲`**) e decrescente (**`▼`**).

---

## 6. Seleção de Fotos e Tamanho Total

Você tem total controle sobre quais arquivos deseja baixar:

1. **Marcar Individualmente:**
   - No modo Tabela: Clique na caixa `[☐]` da coluna `Sel` ou dê duplo clique na linha.
   - No modo Miniaturas: Clique no botão na base do cartão (`☐ Marcar` / `☑ Selecionado`).
2. **Marcar em Lote:**
   - Use os botões na base do painel esquerdo: **`☑ Marcar Todos`** ou **`☐ Desmarcar`**.
3. **Indicador de Tamanho Total Selecionado:**
   - Tanto no topo do painel esquerdo quanto na sua barra inferior, o sistema exibe em tempo real:
     $$\text{📦 Total Selecionado: X.X GB (N arquivos)}$$
   - Assim você sabe exatamente quanto espaço as fotos marcadas vão ocupar no seu computador antes de iniciar a cópia.

---

## 7. Diretório de Destino e Monitor de Espaço Livre

No painel direito (**💻 Meu Computador**):

1. **Escolhendo a Pasta:**
   - Clique no botão **`...`** para selecionar onde deseja guardar suas fotos (ex: `D:\Fotos_Backup`).
   - Você também pode escolher no histórico de caminhos recentes pelo dropdown.
   - Para abrir a pasta no Windows Explorer, clique no botão **`📂`**.
2. **Monitor de Espaço Livre em Tempo Real:**
   - No rodapé do painel direito, observe o indicador:
     $$\text{💾 Livre: X.X GB (de Y.Y GB)}$$
   - O indicador é atualizado a cada arquivo copiado e muda de cor automaticamente:
     - 🟢 **Verde:** Espaço confortável ($\ge 10\text{ GB}$).
     - 🟠 **Laranja:** Atenção, espaço moderado ($< 10\text{ GB}$).
     - 🔴 **Vermelho:** Nível crítico ($< 2\text{ GB}$).

---

## 8. Iniciando a Transferência / Download

1. Com as fotos desejadas marcadas, clique no botão azul destacado:
   **`⬇️ BAIXAR / ORGANIZAR SELECIONADOS`**
2. O aplicativo organizará todas as fotos automaticamente em subpastas padronizadas por data de captura e cidade:
   $$\text{AAAA-MM-DD[-Local]}$$
   *(Exemplos: `2026-05-31-Curitiba` ou `2026-05-31` caso a foto não tenha coordenadas GPS)*.
3. Se você desejar adicionar um nome de evento personalizado à pasta, digite no campo **`Etiqueta (opcional):`** antes de clicar em baixar (ex: `Aniversario`, `ViagemPraia`).
4. **Acompanhamento:**
   - **Barra de Progresso do Arquivo:** Mostra o progresso do arquivo atual em MB e porcentagem.
   - **Barra de Progresso Total:** Mostra velocidade em MB/s, quantidade de arquivos e tempo restante estimado (ETA).

---

## 9. Resolução de Conflitos e Duplicados

Se alguma foto já existir no computador:

- **Modo Silencioso (Padrão):** Se a opção **"☑ Pular Existentes"** estiver marcada na barra superior, arquivos duplicados idênticos são pulados sem interromper a cópia e registrados na aba *Pulados / Falhas*.
- **Decisão Personalizada:** Se você desmarcar "Pular Existentes", o aplicativo abrirá um modal perguntando se você deseja:
  - **Substituir** o arquivo antigo.
  - **Pular / Ignorar** este arquivo.
  - Marcar a opção **`☑ Fazer isso para todos os arquivos`** para que sua decisão seja aplicada automaticamente a todo o restante do lote sem novas perguntas.

---

## 10. Pausa e Cancelamento com Segurança

- **`⏸️ Pausar` / `▶️ Continuar`:** Pausa momentaneamente a transferência sem fechar o programa e congela o monitor de vídeo com aviso visual. Clique novamente para continuar de onde parou.
- **`⛔ Cancelar`:** Interrompe a cópia imediatamente, remove arquivos gravados pela metade no disco para não deixar mídias corrompidas e devolve os botões para o estado inicial pronto.

---

## 11. Exclusão Segura de Mídias

Para liberar espaço no iPhone ou na pasta de origem:

1. Selecione as fotos que deseja apagar.
2. Clique no botão com destaque visual em vermelho:
   **`🗑️ EXCLUIR SELECIONADOS`**
3. Confirme na caixa de diálogo de segurança.
4. O aplicativo apagará os arquivos marcados e atualizará a lista visual na tela em tempo real, sem exibir confirmações repetitivas do Windows.

---

## 12. Resolução de Problemas Comuns (FAQ)

### O aplicativo diz "Desconectado" mesmo com o iPhone plugado:
1. Desconecte o cabo USB e conecte-o novamente.
2. Certifique-se de usar uma porta USB direta do computador (evite hubs USB sem alimentação externa).
3. Desbloqueie a tela do iPhone antes de conectar.

### O aviso "Confiar neste Computador" não aparece no iPhone:
1. No iPhone, vá em: **Ajustes ➔ Geral ➔ Transferir ou Redefinir o iPhone ➔ Redefinir ➔ Redefinir Localização e Privacidade**.
2. Reconecte o cabo USB e o aviso de confirmação reaparecerá imediatamente na tela.

### Um vídeo de 7 GB ou mais demora para começar:
Vídeos 4K pesados levam alguns segundos para o sistema iOS preparar o streaming USB via MTP. O CMaker Photo Commander possui monitoramento contínuo sem limites de tempo rígidos e aguarda o envio completo do arquivo sem travar.

### Como desinstalar o programa?
Vá em **Configurações do Windows ➔ Aplicativos ➔ Aplicativos Instalados**, localize **CMaker Photo Commander** e clique em **Desinstalar**.


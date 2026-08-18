# Conversor PDF → Markdown

Aplicativo local (PWA) para converter PDFs volumosos — 400, 800 ou mais páginas —
em Markdown usando o [Docling](https://github.com/DS4SD/docling) e o PyMuPDF,
**sem terminal e sem renomear arquivos**: você abre o navegador, arrasta o PDF,
acompanha o progresso em tempo real e baixa o `.md` com o mesmo nome do original.

Nada sai da sua máquina: o servidor roda em `localhost` e os arquivos ficam na
pasta `dados/` deste projeto.

---

## Índice

- [O que ele resolve](#o-que-ele-resolve)
- [Requisitos](#requisitos)
- [Instalação e uso no Windows](#instalação-e-uso-no-windows)
- [Instalação e uso no Linux/macOS](#instalação-e-uso-no-linuxmacos)
- [Como usar a interface](#como-usar-a-interface)
- [Opções de processamento](#opções-de-processamento)
- [Instalando como aplicativo (PWA)](#instalando-como-aplicativo-pwa)
- [Como o pipeline funciona](#como-o-pipeline-funciona)
- [Estrutura do projeto](#estrutura-do-projeto)
- [API HTTP](#api-http)
- [Uso pelo terminal (opcional)](#uso-pelo-terminal-opcional)
- [Testes](#testes)
- [Solução de problemas](#solução-de-problemas)

---

## O que ele resolve

Converter um PDF de 800 páginas de uma só vez em uma máquina modesta
(CPU comum, 8 GB de RAM) normalmente termina em travamento por falta de memória.
Este projeto ataca isso em três frentes:

1. **Variáveis de ambiente anti-crash** aplicadas antes de qualquer import de
   machine learning, desligando a compilação dinâmica do PyTorch (a causa do erro
   do `cl.exe` ausente no Windows).
2. **Processamento em lotes**: o PDF é fatiado em blocos de páginas, cada bloco é
   convertido e gravado em disco na hora, e a memória é liberada
   (`del` + `gc.collect()`) antes do bloco seguinte.
3. **Corte inteligente**: antes de fatiar, o PyMuPDF varre o documento e recua
   até 5 páginas quando o corte cairia no meio de uma tabela.

## Requisitos

- Windows 10/11, Linux ou macOS
- Python 3.10 ou superior ([python.org/downloads](https://www.python.org/downloads/) —
  no Windows, marque **"Add Python to PATH"** durante a instalação)
- ~4 GB livres em disco (o Docling baixa modelos na primeira conversão)
- Conexão com a internet apenas na primeira execução (instalação das dependências)

## Instalação e uso no Windows

1. Baixe/clone esta pasta para o computador.
2. Dê **duplo clique em `iniciar_app.bat`**.
   - Na primeira vez ele cria o ambiente virtual `.venv` e instala tudo
     (`fastapi`, `uvicorn`, `pymupdf`, `docling`). Isso leva alguns minutos.
   - Nas próximas vezes o app abre em segundos.
3. O navegador abre sozinho em <http://localhost:8000>.
4. Deixe a janela preta do servidor aberta enquanto usar o aplicativo.

Opcional: `criar_atalho.bat` coloca um atalho na Área de Trabalho.

Para usar outra porta:

```bat
set CONVERSOR_PORTA=8080
iniciar_app.bat
```

## Instalação e uso no Linux/macOS

```bash
./iniciar_app.sh
```

O script cria a `.venv`, instala as dependências e sobe o servidor em
<http://localhost:8000>.

## Como usar a interface

1. **Escolha o PDF** — arraste para a área indicada ou clique para procurar.
   O nome do arquivo de saída aparece na hora: `contrato.pdf` → `contrato.md`.
2. **Ajuste o processamento** — páginas por lote, OCR, tabelas, corte inteligente.
3. **Clique em "Converter para Markdown"** e acompanhe:
   - percentual e barra de progresso;
   - fase atual (mapeando cortes → convertendo lotes → montagem final);
   - páginas processadas, lote atual e KB de Markdown acumulados;
   - registro de mensagens, lote a lote.
4. **Pré-visualize** o Markdown renderizado ou **baixe o `.md`**.

Dá para cancelar a qualquer momento: o processamento para ao fim do lote atual.

## Opções de processamento

| Opção | Padrão | Para que serve |
|---|---|---|
| **Páginas por lote** | 50 | Menos páginas por lote = menos RAM por vez. Em 8 GB, fique entre 25 e 50. |
| **Reconhecimento óptico (OCR)** | desligado | Ligue **apenas** para PDFs digitalizados (imagem). Em PDFs com texto selecionável ele só multiplica o tempo de CPU. |
| **Estrutura de tabelas** | ligado | Converte tabelas do PDF em tabelas Markdown em vez de texto solto. |
| **Corte inteligente** | ligado | Recua até 5 páginas para não partir uma tabela entre dois lotes. Desligue para acelerar o mapeamento em documentos sem tabelas. |

## Instalando como aplicativo (PWA)

Com o servidor rodando, abra <http://localhost:8000> no Chrome ou Edge e clique
em **"Instalar app"** no topo da página (ou no ícone de instalação da barra de
endereços). O conversor passa a abrir em janela própria, com ícone no menu
Iniciar — continuando a usar o servidor local, que precisa estar em execução.

## Como o pipeline funciona

```
PDF enviado
   │
   ├─ 1. Mapeamento (PyMuPDF)
   │     varre as páginas, procura tabelas com page.find_tables()
   │     e define intervalos seguros de corte
   │
   ├─ 2. Conversão lote a lote (Docling)
   │     DocumentConverter criado UMA vez e reutilizado
   │     para cada lote:
   │        sub-PDF temporário → convert() → export_to_markdown()
   │        → append imediato no .md → apaga o temporário
   │        → del resultado / del markdown_bloco / gc.collect()
   │
   └─ 3. Montagem final
         o .md já está completo em disco; o app libera o download
```

Detalhes de implementação que importam:

- `backend/ambiente.py` é importado **antes** de qualquer módulo de ML e aplica
  `TORCHDYNAMO_DISABLE`, `TORCH_COMPILE_DISABLE`, `TORCH_LOGS=-dynamo`,
  `HF_HUB_DISABLE_SYMLINKS_WARNING` e `TOKENIZERS_PARALLELISM=false`.
- O Markdown nunca fica inteiro na memória: cada lote é anexado ao arquivo final.
- As conversões rodam em uma fila com **um único trabalhador** — dois PDFs
  grandes em paralelo estouram a RAM de uma máquina de 8 GB.
- O `import docling` só acontece quando a primeira conversão começa, então o
  servidor sobe rápido.

## Estrutura do projeto

```
converter_PDF_para_MD/
├── backend/
│   ├── ambiente.py       variáveis de ambiente anti-crash (importado primeiro)
│   ├── conversor.py      pipeline: corte inteligente + conversão em lotes
│   ├── tarefas.py        fila, estado e progresso das conversões
│   ├── cli.py            conversão pelo terminal (opcional)
│   └── main.py           API FastAPI + serviço da interface
├── frontend/
│   ├── index.html        interface em página única
│   ├── css/style.css     tema claro/escuro, responsivo, sem build
│   ├── js/app.js         upload, SSE, progresso, download
│   ├── js/markdown.js    pré-visualização do Markdown (sem dependências)
│   ├── icones/           ícones do PWA (+ gerador em Python)
│   ├── manifest.json     manifesto do PWA
│   └── sw.js             Service Worker (cache da casca do app)
├── testes/
│   ├── gerar_pdf_exemplo.py
│   └── teste_conversor.py
├── dados/                criada em tempo de execução (PDFs e .md gerados)
├── iniciar_app.bat       inicialização no Windows (cria .venv, instala, abre)
├── criar_atalho.bat      atalho na Área de Trabalho
├── iniciar_app.sh        inicialização no Linux/macOS
└── requirements.txt
```

## API HTTP

Útil se você quiser automatizar ou integrar com outro programa.

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/saude` | Estado do servidor e se o Docling está instalado |
| `POST` | `/api/conversoes` | Envia o PDF (`multipart/form-data`) e enfileira a conversão |
| `GET` | `/api/conversoes` | Lista as conversões da sessão |
| `GET` | `/api/conversoes/{id}` | Estado atual (percentual, fase, páginas, KB) |
| `GET` | `/api/conversoes/{id}/eventos` | Fluxo SSE com o progresso em tempo real |
| `GET` | `/api/conversoes/{id}/markdown` | Trecho do Markdown para pré-visualização |
| `GET` | `/api/conversoes/{id}/download` | Baixa o `.md` final |
| `POST` | `/api/conversoes/{id}/cancelar` | Cancela após o lote em andamento |
| `DELETE` | `/api/conversoes/{id}` | Remove a conversão e seus arquivos |

Exemplo:

```bash
curl -X POST http://localhost:8000/api/conversoes \
  -F "arquivo=@documento.pdf" \
  -F "tamanho_lote=50" -F "ocr=false" -F "estrutura_tabelas=true"
```

A documentação interativa fica em <http://localhost:8000/docs>.

### Variáveis de ambiente

| Variável | Padrão | Efeito |
|---|---|---|
| `CONVERSOR_PORTA` | `8000` | Porta do servidor local |
| `CONVERSOR_HOST` | `127.0.0.1` | Interface de rede |
| `CONVERSOR_ABRIR_NAVEGADOR` | `1` | `0` não abre o navegador sozinho |
| `CONVERSOR_PASTA_DADOS` | `dados/` | Onde ficam os PDFs e os `.md` |
| `CONVERSOR_LIMITE_MB` | `2048` | Tamanho máximo de upload |
| `CONVERSOR_RETENCAO_HORAS` | `24` | Idade a partir da qual conversões antigas são apagadas ao iniciar |
| `CONVERSOR_SIMULADO` | — | `1` usa extração de texto do PyMuPDF no lugar do Docling (só para testar a interface) |

## Uso pelo terminal (opcional)

```bash
.venv/bin/python -m backend.cli "documento.pdf" --lote 50
.venv/bin/python -m backend.cli "documento.pdf" --ocr --saida saida.md
```

No Windows, troque por `.venv\Scripts\python.exe`.

## Testes

```bash
python testes/teste_conversor.py
```

Rodam em modo simulado (sem Docling) e cobrem o fatiamento em lotes, o
cancelamento, a montagem do arquivo final e a limpeza dos PDFs temporários.

## Solução de problemas

**"Docling não instalado" no topo da página**
Instale no ambiente virtual do projeto:
`.venv\Scripts\python.exe -m pip install docling` (Windows) ou
`.venv/bin/python -m pip install docling`.

**A primeira conversão demora muito para começar**
O Docling baixa os modelos de layout/tabelas na primeira execução. Depois disso
eles ficam em cache.

**O computador fica sem memória / o processo morre**
Reduza as **páginas por lote** para 25 ou 20 e mantenha o OCR desligado.

**Erro mencionando `cl.exe` ou compilação do PyTorch**
Já tratado pelas variáveis de `backend/ambiente.py`. Se aparecer, confirme que o
app foi iniciado por `iniciar_app.bat` / `python -m backend.main` (e não
importando `docling` antes desse módulo).

**"Porta 8000 já em uso"**
Rode com outra porta: `set CONVERSOR_PORTA=8080` antes do `iniciar_app.bat`.

**O PDF é digitalizado e o Markdown sai vazio**
Ligue o **OCR** nas opções — o documento não tem texto selecionável.

**A pasta `dados/` cresceu demais**
Pode apagá-la com o servidor parado; ela é recriada na próxima execução.
Conversões com mais de 24 h também são removidas automaticamente ao iniciar.

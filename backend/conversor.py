"""Pipeline de conversao de PDFs volumosos para Markdown.

Estrategia (pensada para maquinas modestas, ~8 GB de RAM):

1. Pre-scan rapido com PyMuPDF para mapear pontos de corte seguros, evitando
   quebrar tabelas ao meio.
2. Um unico ``DocumentConverter`` do Docling e criado por arquivo e reutilizado
   em todos os lotes (criar um por lote esgota a memoria rapidamente).
3. Cada lote vira um sub-PDF temporario, e convertido, gravado imediatamente em
   disco e descartado -- o Markdown nunca fica inteiro na memoria.
4. ``gc.collect()`` explicito ao fim de cada lote para liberar tensores.
"""

from __future__ import annotations

# A configuracao de ambiente precisa acontecer antes de qualquer import de ML.
from . import ambiente  # noqa: F401  (import com efeito colateral proposital)

import gc
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

# Modo de simulacao para desenvolvimento/testes sem o Docling instalado.
# Extrai o texto com o proprio PyMuPDF. NAO use em producao: a qualidade do
# Markdown (tabelas, titulos, layout) e muito inferior a do Docling.
MODO_SIMULADO = os.environ.get("CONVERSOR_SIMULADO", "").strip().lower() in {"1", "true", "sim"}


class ConversaoCancelada(Exception):
    """Levantada quando o usuario cancela o processamento em andamento."""


@dataclass
class OpcoesConversao:
    """Parametros ajustaveis pelo usuario na interface."""

    tamanho_lote: int = 50
    ocr: bool = False
    estrutura_tabelas: bool = True
    corte_inteligente: bool = True
    paginas_recuo: int = 5

    def normalizar(self) -> "OpcoesConversao":
        self.tamanho_lote = max(1, min(int(self.tamanho_lote), 500))
        self.paginas_recuo = max(0, min(int(self.paginas_recuo), 20))
        return self


# ---------------------------------------------------------------------------
# Diagnostico de texto selecionavel (decide se o OCR e necessario)
# ---------------------------------------------------------------------------

# Uma pagina precisa de pelo menos este tanto de caracteres para ser
# considerada "com texto". Cabecalho e numero de pagina soltos ficam abaixo
# disso, entao uma pagina digitalizada com carimbo de protocolo nao passa.
MINIMO_CARACTERES_POR_PAGINA = 100

# Quantas paginas sao amostradas no maximo. 40 amostras espalhadas descrevem
# bem um documento de 800 paginas e a leitura leva menos de um segundo.
MAXIMO_PAGINAS_AMOSTRADAS = 40


@dataclass
class DiagnosticoTexto:
    """Resultado da checagem de texto selecionavel de um PDF."""

    total_paginas: int = 0
    paginas_amostradas: int = 0
    paginas_com_texto: int = 0
    paginas_digitalizadas: int = 0
    paginas_vazias: int = 0
    media_caracteres: float = 0.0
    proporcao_com_texto: float = 0.0
    classificacao: str = "indefinido"  # texto | misto | digitalizado | indefinido
    ocr_recomendado: bool = False
    resumo: str = ""

    def para_dicionario(self) -> dict:
        return {
            "total_paginas": self.total_paginas,
            "paginas_amostradas": self.paginas_amostradas,
            "paginas_com_texto": self.paginas_com_texto,
            "paginas_digitalizadas": self.paginas_digitalizadas,
            "paginas_vazias": self.paginas_vazias,
            "media_caracteres": round(self.media_caracteres, 1),
            "proporcao_com_texto": round(self.proporcao_com_texto, 3),
            "percentual_com_texto": round(self.proporcao_com_texto * 100, 1),
            "classificacao": self.classificacao,
            "ocr_recomendado": self.ocr_recomendado,
            "resumo": self.resumo,
        }


def _paginas_para_amostrar(total: int, maximo: int) -> list[int]:
    """Escolhe indices espalhados pelo documento, sempre com inicio e fim."""

    if total <= maximo:
        return list(range(total))
    passo = total / maximo
    indices = sorted({int(i * passo) for i in range(maximo)} | {0, total - 1})
    return [i for i in indices if i < total]


def diagnosticar_texto(
    pdf_path: str | Path,
    maximo_amostras: int = MAXIMO_PAGINAS_AMOSTRADAS,
) -> DiagnosticoTexto:
    """Verifica se o PDF tem texto selecionavel ou se precisara de OCR.

    Le apenas uma amostra de paginas com o PyMuPDF (rapido, sem carregar o
    Docling) e classifica o documento em tres casos praticos:

    * ``texto``        -- da para converter sem OCR;
    * ``misto``        -- parte digitalizada, parte com texto;
    * ``digitalizado`` -- sem OCR o Markdown sai vazio.

    Paginas em branco (sem texto e sem imagem) sao ignoradas na conta, para
    nao contaminarem o diagnostico de documentos com folhas de separacao.
    """

    doc = pymupdf.open(str(pdf_path))
    try:
        total = len(doc)
        diagnostico = DiagnosticoTexto(total_paginas=total)
        if total == 0:
            diagnostico.resumo = "O PDF não possui páginas legíveis."
            return diagnostico

        indices = _paginas_para_amostrar(total, max(1, maximo_amostras))
        total_caracteres = 0

        for indice in indices:
            pagina = doc[indice]
            try:
                caracteres = len(pagina.get_text("text").strip())
            except Exception:
                caracteres = 0
            total_caracteres += caracteres

            if caracteres >= MINIMO_CARACTERES_POR_PAGINA:
                diagnostico.paginas_com_texto += 1
                continue

            try:
                tem_imagem = bool(pagina.get_images(full=True))
            except Exception:
                tem_imagem = False

            if tem_imagem:
                diagnostico.paginas_digitalizadas += 1
            else:
                diagnostico.paginas_vazias += 1

        diagnostico.paginas_amostradas = len(indices)
        diagnostico.media_caracteres = total_caracteres / len(indices)

        com_conteudo = diagnostico.paginas_com_texto + diagnostico.paginas_digitalizadas
        if com_conteudo == 0:
            diagnostico.classificacao = "indefinido"
            diagnostico.ocr_recomendado = False
            diagnostico.resumo = (
                "Não foi possível classificar: as páginas analisadas estão em branco."
            )
            return diagnostico

        proporcao = diagnostico.paginas_com_texto / com_conteudo
        diagnostico.proporcao_com_texto = proporcao
        percentual = round(proporcao * 100)

        if proporcao >= 0.85:
            diagnostico.classificacao = "texto"
            diagnostico.ocr_recomendado = False
            diagnostico.resumo = (
                f"O PDF tem texto selecionável ({percentual}% das páginas analisadas, "
                f"média de {diagnostico.media_caracteres:.0f} caracteres por página). "
                "O OCR não é necessário."
            )
        elif proporcao >= 0.15:
            diagnostico.classificacao = "misto"
            diagnostico.ocr_recomendado = True
            diagnostico.resumo = (
                f"O PDF é misto: apenas {percentual}% das páginas analisadas têm texto "
                "selecionável; as demais parecem digitalizadas. Sem OCR, essas páginas "
                "sairão vazias no Markdown."
            )
        else:
            diagnostico.classificacao = "digitalizado"
            diagnostico.ocr_recomendado = True
            diagnostico.resumo = (
                "O PDF parece ser digitalizado (imagens de páginas, sem texto "
                "selecionável). Sem OCR o Markdown sai praticamente vazio."
            )

        return diagnostico
    finally:
        doc.close()


class OuvinteProgresso:
    """Interface de notificacao. Todos os metodos sao opcionais."""

    def mensagem(self, texto: str, nivel: str = "info") -> None:  # pragma: no cover - no-op
        pass

    def arquivo_aberto(self, total_paginas: int) -> None:  # pragma: no cover - no-op
        pass

    def mapeamento_progresso(self, paginas_analisadas: int, total_paginas: int) -> None:  # pragma: no cover
        pass

    def lotes_definidos(self, intervalos: list[tuple[int, int]]) -> None:  # pragma: no cover
        pass

    def lote_iniciado(self, indice: int, total: int, inicio: int, fim: int) -> None:  # pragma: no cover
        pass

    def lote_concluido(self, indice: int, total: int, paginas: int, kb: float) -> None:  # pragma: no cover
        pass

    def cancelado(self) -> bool:
        return False


@dataclass
class ResultadoConversao:
    caminho_markdown: Path
    total_paginas: int
    total_lotes: int
    kb_gerados: float
    segundos: float
    intervalos: list[tuple[int, int]] = field(default_factory=list)


def _checar_cancelamento(ouvinte: OuvinteProgresso) -> None:
    if ouvinte.cancelado():
        raise ConversaoCancelada()


def encontrar_pontos_de_corte(
    pdf_path: str | Path,
    opcoes: OpcoesConversao,
    ouvinte: OuvinteProgresso | None = None,
) -> list[tuple[int, int]]:
    """Mapeia intervalos ``[inicio, fim)`` seguros, evitando cortar tabelas.

    O corte natural fica no multiplo de ``tamanho_lote``. Quando esse ponto cai
    dentro de uma tabela, recuamos ate ``paginas_recuo`` paginas em busca de uma
    pagina sem tabelas para fechar o lote.
    """

    ouvinte = ouvinte or OuvinteProgresso()
    doc = pymupdf.open(str(pdf_path))
    try:
        total_paginas = len(doc)
        ouvinte.arquivo_aberto(total_paginas)

        if total_paginas == 0:
            return []

        intervalos: list[tuple[int, int]] = []
        pagina_inicio = 0

        while pagina_inicio < total_paginas:
            _checar_cancelamento(ouvinte)
            pagina_fim = min(pagina_inicio + opcoes.tamanho_lote, total_paginas)

            if pagina_fim >= total_paginas:
                intervalos.append((pagina_inicio, total_paginas))
                ouvinte.mapeamento_progresso(total_paginas, total_paginas)
                break

            corte_seguro = pagina_fim
            if opcoes.corte_inteligente and opcoes.paginas_recuo > 0:
                # Recua no maximo `paginas_recuo` paginas, sem nunca voltar
                # antes do inicio do lote (garante progresso do laco).
                limite = max(pagina_inicio + 1, pagina_fim - opcoes.paginas_recuo)
                for p in range(pagina_fim - 1, limite - 1, -1):
                    _checar_cancelamento(ouvinte)
                    if not _pagina_tem_tabela(doc[p]):
                        corte_seguro = p + 1
                        break

            intervalos.append((pagina_inicio, corte_seguro))
            pagina_inicio = corte_seguro
            ouvinte.mapeamento_progresso(pagina_inicio, total_paginas)

        ouvinte.lotes_definidos(intervalos)
        return intervalos
    finally:
        doc.close()


def _pagina_tem_tabela(page: "pymupdf.Page") -> bool:
    try:
        return bool(page.find_tables().tables)
    except Exception:
        # Deteccao de tabelas e heuristica; falhas nao devem derrubar o job.
        return False


def criar_conversor(opcoes: OpcoesConversao):
    """Cria o ``DocumentConverter`` do Docling uma unica vez por arquivo."""

    if MODO_SIMULADO:
        return _ConversorSimulado()

    # Imports tardios: o Docling carrega o PyTorch e leva varios segundos.
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = opcoes.ocr
    pipeline_options.do_table_structure = opcoes.estrutura_tabelas

    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )


class _ConversorSimulado:
    """Substituto do Docling para testes locais (texto puro via PyMuPDF)."""

    def convert(self, caminho: str):  # noqa: D401 - assinatura compativel
        doc = pymupdf.open(caminho)
        try:
            partes = [pagina.get_text().strip() for pagina in doc]
        finally:
            doc.close()
        return _ResultadoSimulado("\n\n".join(p for p in partes if p))


class _ResultadoSimulado:
    def __init__(self, texto: str) -> None:
        self.document = self
        self._texto = texto

    def export_to_markdown(self) -> str:
        return self._texto


def processar_pdf_em_lotes(
    pdf_entrada: str | Path,
    md_saida: str | Path,
    opcoes: OpcoesConversao | None = None,
    ouvinte: OuvinteProgresso | None = None,
) -> ResultadoConversao:
    """Converte um PDF grande para Markdown processando-o em lotes."""

    opcoes = (opcoes or OpcoesConversao()).normalizar()
    ouvinte = ouvinte or OuvinteProgresso()

    pdf_path = Path(pdf_entrada)
    md_path = Path(md_saida)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {pdf_path}")

    inicio_execucao = time.monotonic()

    ouvinte.mensagem("Mapeando pontos de corte seguros...")
    intervalos = encontrar_pontos_de_corte(pdf_path, opcoes, ouvinte)
    if not intervalos:
        raise ValueError("O PDF não possui páginas legíveis.")

    total_paginas = intervalos[-1][1]
    ouvinte.mensagem(
        f"{len(intervalos)} lote(s) definidos para {total_paginas} pagina(s)."
    )

    _checar_cancelamento(ouvinte)
    ouvinte.mensagem(
        "Inicializando pipeline do Docling"
        f" (OCR: {'ligado' if opcoes.ocr else 'desligado'},"
        f" tabelas: {'ligado' if opcoes.estrutura_tabelas else 'desligado'})..."
    )
    conversor = criar_conversor(opcoes)

    md_path.parent.mkdir(parents=True, exist_ok=True)
    # Limpa/inicializa o arquivo final antes do primeiro append.
    md_path.write_text("", encoding="utf-8")

    kb_totais = 0.0
    doc_original = pymupdf.open(str(pdf_path))
    pasta_temp = Path(tempfile.mkdtemp(prefix="lotes_pdf_"))

    try:
        for i, (inicio, fim) in enumerate(intervalos, start=1):
            _checar_cancelamento(ouvinte)
            ouvinte.lote_iniciado(i, len(intervalos), inicio, fim)

            temp_pdf = pasta_temp / f"_temp_lote_{i}.pdf"
            sub_doc = pymupdf.open()
            try:
                sub_doc.insert_pdf(doc_original, from_page=inicio, to_page=fim - 1)
                sub_doc.save(str(temp_pdf))
            finally:
                sub_doc.close()

            try:
                resultado = conversor.convert(str(temp_pdf))
                markdown_bloco = resultado.document.export_to_markdown()

                tamanho_kb = len(markdown_bloco.encode("utf-8")) / 1024
                kb_totais += tamanho_kb

                # Grava imediatamente: o Markdown completo nunca fica em memoria.
                with open(md_path, "a", encoding="utf-8") as f_out:
                    f_out.write(markdown_bloco + "\n\n")

                ouvinte.lote_concluido(i, len(intervalos), fim - inicio, tamanho_kb)
            finally:
                temp_pdf.unlink(missing_ok=True)
                # Libera tensores e buffers antes do proximo lote.
                resultado = None
                markdown_bloco = None
                del resultado
                del markdown_bloco
                gc.collect()
    finally:
        doc_original.close()
        conversor = None
        del conversor
        gc.collect()
        for restante in pasta_temp.glob("*"):
            restante.unlink(missing_ok=True)
        pasta_temp.rmdir()

    return ResultadoConversao(
        caminho_markdown=md_path,
        total_paginas=total_paginas,
        total_lotes=len(intervalos),
        kb_gerados=kb_totais,
        segundos=time.monotonic() - inicio_execucao,
        intervalos=intervalos,
    )

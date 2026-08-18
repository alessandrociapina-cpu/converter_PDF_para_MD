"""Testes do pipeline de conversao, sem dependencias alem do PyMuPDF.

Executa em modo simulado (sem Docling), verificando o fatiamento em lotes, o
cancelamento e a montagem do arquivo final.

Uso:  python testes/teste_conversor.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["CONVERSOR_SIMULADO"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.conversor import (  # noqa: E402
    ConversaoCancelada,
    OpcoesConversao,
    OuvinteProgresso,
    diagnosticar_texto,
    encontrar_pontos_de_corte,
    processar_pdf_em_lotes,
)
from backend.main import _precisa_confirmar_ocr  # noqa: E402
from backend.tarefas import sanitizar_nome  # noqa: E402
from testes.gerar_pdf_exemplo import gerar, gerar_digitalizado, gerar_misto  # noqa: E402

falhas: list[str] = []


def verificar(condicao: bool, descricao: str) -> None:
    if condicao:
        print(f"  ok   {descricao}")
    else:
        print(f"  FALHA {descricao}")
        falhas.append(descricao)


def teste_intervalos_cobrem_todas_as_paginas(pdf: Path) -> None:
    print("intervalos de corte")
    intervalos = encontrar_pontos_de_corte(pdf, OpcoesConversao(tamanho_lote=7))
    verificar(intervalos[0][0] == 0, "o primeiro lote comeca na pagina 0")
    verificar(intervalos[-1][1] == 20, "o ultimo lote termina na ultima pagina")
    verificar(
        all(a[1] == b[0] for a, b in zip(intervalos, intervalos[1:])),
        "os lotes sao continuos, sem paginas perdidas",
    )
    verificar(
        all(fim - inicio <= 7 for inicio, fim in intervalos),
        "nenhum lote passa do tamanho maximo",
    )
    verificar(all(fim > inicio for inicio, fim in intervalos), "nenhum lote fica vazio")


def teste_lote_maior_que_documento(pdf: Path) -> None:
    print("lote maior que o documento")
    intervalos = encontrar_pontos_de_corte(pdf, OpcoesConversao(tamanho_lote=500))
    verificar(intervalos == [(0, 20)], "documento inteiro vira um unico lote")


def teste_conversao_completa(pdf: Path, destino: Path) -> None:
    print("conversao completa")
    resultado = processar_pdf_em_lotes(pdf, destino, OpcoesConversao(tamanho_lote=6))
    conteudo = destino.read_text(encoding="utf-8")
    verificar(destino.exists() and destino.stat().st_size > 0, "arquivo .md foi gerado")
    verificar(resultado.total_paginas == 20, "todas as 20 paginas foram contabilizadas")
    verificar("Capitulo 1" in conteudo, "o texto da primeira pagina esta no Markdown")
    verificar("Capitulo 20" in conteudo, "o texto da ultima pagina esta no Markdown")
    verificar(resultado.kb_gerados > 0, "o tamanho gerado foi medido")
    verificar(
        not list(destino.parent.glob("_temp_lote_*.pdf")),
        "nenhum PDF temporario ficou para tras",
    )


def teste_cancelamento(pdf: Path, destino: Path) -> None:
    print("cancelamento")

    class OuvinteQueCancela(OuvinteProgresso):
        def __init__(self) -> None:
            self.lotes = 0

        def lote_concluido(self, indice, total, paginas, kb) -> None:
            self.lotes += 1

        def cancelado(self) -> bool:
            return self.lotes >= 1

    ouvinte = OuvinteQueCancela()
    try:
        processar_pdf_em_lotes(pdf, destino, OpcoesConversao(tamanho_lote=5), ouvinte)
        verificar(False, "ConversaoCancelada deveria ter sido levantada")
    except ConversaoCancelada:
        verificar(True, "o processamento parou apos o lote em andamento")
    verificar(ouvinte.lotes == 1, "nenhum lote extra foi processado depois do cancelamento")


def teste_nome_de_saida() -> None:
    print("nome do arquivo de saida")
    verificar(sanitizar_nome("Relatório Final.pdf") == "Relatório Final.pdf", "acentos preservados")
    verificar(sanitizar_nome("../../etc/senha.pdf") == "senha.pdf", "caminho relativo neutralizado")
    verificar(sanitizar_nome('nome:com*proibidos?.pdf') == "nome_com_proibidos_.pdf",
              "caracteres invalidos do Windows substituidos")
    verificar(sanitizar_nome("") == "documento.pdf", "nome vazio recebe padrao")


def teste_diagnostico(pasta: Path) -> None:
    print("diagnostico de texto selecionavel")

    com_texto = diagnosticar_texto(gerar(pasta / "d_texto.pdf", 20))
    verificar(com_texto.classificacao == "texto", "PDF com texto e classificado como 'texto'")
    verificar(not com_texto.ocr_recomendado, "PDF com texto nao pede OCR")
    verificar(com_texto.media_caracteres > 100, "media de caracteres coerente")

    escaneado = diagnosticar_texto(gerar_digitalizado(pasta / "d_scan.pdf", 8))
    verificar(escaneado.classificacao == "digitalizado", "PDF de imagens e 'digitalizado'")
    verificar(escaneado.ocr_recomendado, "PDF digitalizado pede OCR")
    verificar(escaneado.paginas_digitalizadas == escaneado.paginas_amostradas,
              "todas as paginas amostradas foram vistas como digitalizadas")

    misto = diagnosticar_texto(gerar_misto(pasta / "d_misto.pdf", 5, 5))
    verificar(misto.classificacao == "misto", "PDF meio a meio e 'misto'")
    verificar(misto.ocr_recomendado, "PDF misto pede OCR")

    grande = diagnosticar_texto(gerar(pasta / "d_grande.pdf", 300), maximo_amostras=40)
    verificar(grande.paginas_amostradas <= 41, "a amostragem respeita o limite em documentos grandes")
    verificar(grande.classificacao == "texto", "documento grande com texto e classificado certo")


def teste_regra_de_confirmacao(pasta: Path) -> None:
    print("quando perguntar ao usuario")

    com_texto = diagnosticar_texto(gerar(pasta / "c_texto.pdf", 12))
    escaneado = diagnosticar_texto(gerar_digitalizado(pasta / "c_scan.pdf", 6))

    verificar(
        _precisa_confirmar_ocr(escaneado, OpcoesConversao(ocr=False)),
        "PDF digitalizado com OCR desligado pede confirmacao",
    )
    verificar(
        not _precisa_confirmar_ocr(escaneado, OpcoesConversao(ocr=True)),
        "PDF digitalizado com OCR ligado segue direto",
    )
    verificar(
        _precisa_confirmar_ocr(com_texto, OpcoesConversao(ocr=True)),
        "PDF com texto e OCR ligado avisa do desperdicio",
    )
    verificar(
        not _precisa_confirmar_ocr(com_texto, OpcoesConversao(ocr=False)),
        "PDF com texto e OCR desligado segue direto",
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as temporaria:
        pasta = Path(temporaria)
        pdf = gerar(pasta / "exemplo.pdf", paginas=20)

        teste_intervalos_cobrem_todas_as_paginas(pdf)
        teste_lote_maior_que_documento(pdf)
        teste_conversao_completa(pdf, pasta / "exemplo.md")
        teste_cancelamento(pdf, pasta / "cancelado.md")
        teste_diagnostico(pasta)
        teste_regra_de_confirmacao(pasta)
        teste_nome_de_saida()

    print()
    if falhas:
        print(f"{len(falhas)} teste(s) falharam.")
        return 1
    print("Todos os testes passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

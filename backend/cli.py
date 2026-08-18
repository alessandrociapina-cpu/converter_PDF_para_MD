"""Conversao pela linha de comando, para quem preferir o terminal.

Exemplos:
    python -m backend.cli "C:\\Documentos\\peticao.pdf"
    python -m backend.cli documento.pdf --lote 30 --ocr --saida outro_nome.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .conversor import (
    ConversaoCancelada,
    OpcoesConversao,
    OuvinteProgresso,
    processar_pdf_em_lotes,
)


class _OuvinteTerminal(OuvinteProgresso):
    def mensagem(self, texto: str, nivel: str = "info") -> None:
        print(texto)

    def arquivo_aberto(self, total_paginas: int) -> None:
        print(f"PDF aberto: {total_paginas} pagina(s).")

    def lotes_definidos(self, intervalos: list[tuple[int, int]]) -> None:
        print(f"Total de lotes a processar: {len(intervalos)}")

    def lote_iniciado(self, indice: int, total: int, inicio: int, fim: int) -> None:
        print(f"\n--- Lote {indice}/{total} (paginas {inicio + 1} a {fim}) ---")

    def lote_concluido(self, indice: int, total: int, paginas: int, kb: float) -> None:
        print(f"Lote {indice} convertido: {kb:.2f} KB de Markdown.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Converte um PDF grande em Markdown com o Docling.")
    parser.add_argument("pdf", help="Caminho do PDF de entrada.")
    parser.add_argument("--saida", help="Arquivo .md de saida (padrao: mesmo nome do PDF).")
    parser.add_argument("--lote", type=int, default=50, help="Paginas por lote (padrao: 50).")
    parser.add_argument("--ocr", action="store_true", help="Liga o OCR (mais lento).")
    parser.add_argument("--sem-tabelas", action="store_true", help="Desliga o reconhecimento de tabelas.")
    parser.add_argument("--sem-corte-inteligente", action="store_true",
                        help="Corta os lotes em pontos fixos, sem checar tabelas (mais rapido).")
    args = parser.parse_args(argv)

    pdf = Path(args.pdf).expanduser()
    saida = Path(args.saida).expanduser() if args.saida else pdf.with_suffix(".md")

    opcoes = OpcoesConversao(
        tamanho_lote=args.lote,
        ocr=args.ocr,
        estrutura_tabelas=not args.sem_tabelas,
        corte_inteligente=not args.sem_corte_inteligente,
    )

    try:
        resultado = processar_pdf_em_lotes(pdf, saida, opcoes, _OuvinteTerminal())
    except FileNotFoundError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    except ConversaoCancelada:
        print("Conversao cancelada.", file=sys.stderr)
        return 130

    print(
        f"\nConcluido em {resultado.segundos:.1f}s: {resultado.caminho_markdown} "
        f"({resultado.kb_gerados:.2f} KB)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

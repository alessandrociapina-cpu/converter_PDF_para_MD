"""Gera um PDF de exemplo para testar o app sem depender de um documento real."""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf


def gerar(caminho: Path, paginas: int = 12) -> Path:
    doc = pymupdf.open()
    for numero in range(1, paginas + 1):
        pagina = doc.new_page()
        pagina.insert_text((72, 90), f"Capitulo {numero}", fontsize=20)
        corpo = "\n".join(
            f"Linha {i} da pagina {numero}: texto de teste para o conversor." for i in range(1, 26)
        )
        pagina.insert_text((72, 130), corpo, fontsize=10)
    doc.save(str(caminho))
    doc.close()
    return caminho


if __name__ == "__main__":
    destino = Path(sys.argv[1] if len(sys.argv) > 1 else "exemplo.pdf")
    paginas = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    print("gerado:", gerar(destino, paginas))

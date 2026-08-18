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


def gerar_digitalizado(caminho: Path, paginas: int = 6) -> Path:
    """Gera um PDF que imita um documento escaneado: paginas so com imagem."""
    original = pymupdf.open()
    for numero in range(1, paginas + 1):
        pagina = original.new_page()
        pagina.insert_text((72, 100), f"Documento digitalizado - folha {numero}", fontsize=18)
        pagina.insert_text((72, 140), "Conteudo que so existe como imagem.", fontsize=12)

    escaneado = pymupdf.open()
    for pagina in original:
        imagem = pagina.get_pixmap(dpi=90)
        nova = escaneado.new_page(width=pagina.rect.width, height=pagina.rect.height)
        nova.insert_image(nova.rect, pixmap=imagem)
    original.close()

    escaneado.save(str(caminho))
    escaneado.close()
    return caminho


def gerar_misto(caminho: Path, paginas_texto: int = 4, paginas_imagem: int = 6) -> Path:
    """Gera um PDF com parte das paginas em texto e parte digitalizadas."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)
        com_texto = gerar(pasta / "texto.pdf", paginas_texto)
        digitalizado = gerar_digitalizado(pasta / "imagem.pdf", paginas_imagem)

        destino = pymupdf.open()
        for parte in (com_texto, digitalizado):
            origem = pymupdf.open(str(parte))
            destino.insert_pdf(origem)
            origem.close()
        destino.save(str(caminho))
        destino.close()
    return caminho


if __name__ == "__main__":
    destino = Path(sys.argv[1] if len(sys.argv) > 1 else "exemplo.pdf")
    paginas = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    print("gerado:", gerar(destino, paginas))

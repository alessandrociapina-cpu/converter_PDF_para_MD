"""Gera os icones PNG do PWA sem dependencias externas.

Uso: python frontend/icones/gerar_icones.py

Desenha o mesmo simbolo do icone.svg (documento com seta de exportacao) com
anti-aliasing por supersampling e grava PNGs no formato RGBA.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

PASTA = Path(__file__).resolve().parent
AMOSTRAS = 3  # supersampling por eixo

AZUL_TOPO = (58, 132, 255)
AZUL_BASE = (20, 78, 190)
BRANCO = (255, 255, 255)


def _mistura(cor_a, cor_b, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(cor_a, cor_b))


def _dentro_retangulo_arredondado(x, y, x0, y0, x1, y1, raio):
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + raio), x1 - raio)
    cy = min(max(y, y0 + raio), y1 - raio)
    return (x - cx) ** 2 + (y - cy) ** 2 <= raio ** 2 or (
        x0 + raio <= x <= x1 - raio or y0 + raio <= y <= y1 - raio
    )


def _dentro_triangulo(x, y, pontos):
    (x1, y1), (x2, y2), (x3, y3) = pontos
    d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if d == 0:
        return False
    a = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / d
    b = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / d
    c = 1 - a - b
    return a >= 0 and b >= 0 and c >= 0


def _cor_do_ponto(x: float, y: float, margem: float):
    """Retorna (r, g, b, a) em coordenadas normalizadas 0..1."""

    # Area util do simbolo (encolhida quando o icone e maskable).
    u = (x - margem) / (1 - 2 * margem)
    v = (y - margem) / (1 - 2 * margem)

    if not _dentro_retangulo_arredondado(x, y, 0.0, 0.0, 1.0, 1.0, 0.22):
        return (0, 0, 0, 0)

    fundo = _mistura(AZUL_TOPO, AZUL_BASE, y)

    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        return fundo + (255,)

    # Folha de papel
    if _dentro_retangulo_arredondado(u, v, 0.26, 0.13, 0.74, 0.60, 0.05):
        # Canto dobrado
        if _dentro_triangulo(u, v, [(0.60, 0.13), (0.74, 0.13), (0.74, 0.27)]):
            return _mistura(fundo, BRANCO, 0.35) + (255,)
        # Linhas de texto
        for topo in (0.28, 0.37, 0.46):
            largura = 0.34 if topo < 0.46 else 0.22
            if 0.34 <= u <= 0.34 + largura and topo <= v <= topo + 0.045:
                return fundo + (255,)
        return BRANCO + (255,)

    # Seta de exportacao
    if 0.455 <= u <= 0.545 and 0.63 <= v <= 0.79:
        return BRANCO + (255,)
    if _dentro_triangulo(u, v, [(0.36, 0.76), (0.64, 0.76), (0.50, 0.92)]):
        return BRANCO + (255,)

    return fundo + (255,)


def gerar_png(caminho: Path, tamanho: int, margem: float = 0.0) -> None:
    linhas = bytearray()
    passo = 1.0 / (tamanho * AMOSTRAS)
    for py in range(tamanho):
        linhas.append(0)  # filtro "none" por linha
        for px in range(tamanho):
            r = g = b = a = 0
            for sy in range(AMOSTRAS):
                for sx in range(AMOSTRAS):
                    x = (px * AMOSTRAS + sx + 0.5) * passo
                    y = (py * AMOSTRAS + sy + 0.5) * passo
                    cor = _cor_do_ponto(x, y, margem)
                    r += cor[0] * cor[3]
                    g += cor[1] * cor[3]
                    b += cor[2] * cor[3]
                    a += cor[3]
            if a == 0:
                linhas.extend((0, 0, 0, 0))
            else:
                total = AMOSTRAS * AMOSTRAS
                linhas.extend((
                    round(r / a), round(g / a), round(b / a), round(a / total),
                ))

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        conteudo = tipo + dados
        return struct.pack(">I", len(dados)) + conteudo + struct.pack(">I", zlib.crc32(conteudo))

    cabecalho = struct.pack(">IIBBBBB", tamanho, tamanho, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + bloco(b"IHDR", cabecalho)
        + bloco(b"IDAT", zlib.compress(bytes(linhas), 9))
        + bloco(b"IEND", b"")
    )
    caminho.write_bytes(png)
    print(f"gerado: {caminho.name} ({tamanho}x{tamanho}, {len(png) / 1024:.1f} KB)")


if __name__ == "__main__":
    gerar_png(PASTA / "icone-192.png", 192)
    gerar_png(PASTA / "icone-512.png", 512)
    # Versao maskable: o simbolo fica dentro da zona segura circular.
    gerar_png(PASTA / "icone-maskable-512.png", 512, margem=0.14)

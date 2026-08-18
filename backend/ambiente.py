"""Configuracao de ambiente anti-crash.

Este modulo PRECISA ser importado antes de qualquer biblioteca de machine
learning (torch, docling, transformers). Ele desativa a compilacao dinamica do
PyTorch, que exige um compilador C++ instalado na maquina (cl.exe no Windows) e
e a causa mais comum de travamentos e crashes silenciosos em maquinas modestas.
"""

import os

VARIAVEIS_ANTI_CRASH = {
    # Desativa a compilacao C++/dynamo do PyTorch (evita o erro do cl.exe ausente)
    "TORCH_LOGS": "-dynamo",
    "TORCHDYNAMO_DISABLE": "1",
    "TORCH_COMPILE_DISABLE": "1",
    # Silencia avisos do HuggingFace Hub sobre symlinks no Windows
    "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
    # Evita concorrencia de tokenizers, que consome CPU e memoria sem ganho aqui
    "TOKENIZERS_PARALLELISM": "false",
}


def configurar_ambiente() -> None:
    """Aplica as variaveis de ambiente obrigatorias do pipeline."""
    for chave, valor in VARIAVEIS_ANTI_CRASH.items():
        os.environ[chave] = valor


# Aplicado no momento do import para garantir a ordem correta.
configurar_ambiente()

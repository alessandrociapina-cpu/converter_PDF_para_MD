"""Gerenciamento das tarefas (jobs) de conversao.

Cada arquivo enviado vira uma tarefa executada em uma fila com um unico
trabalhador: em maquinas de 8 GB, dois PDFs grandes em paralelo estouram a
memoria. O estado de cada tarefa e atualizado de forma thread-safe e consumido
pela interface via SSE ou polling.
"""

from __future__ import annotations

import re
import shutil
import threading
import time
import traceback
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .conversor import (
    ConversaoCancelada,
    DiagnosticoTexto,
    OpcoesConversao,
    OuvinteProgresso,
    processar_pdf_em_lotes,
)

# Pesos de cada fase no calculo do percentual global.
PESO_MAPEAMENTO = 8.0
PESO_CONVERSAO = 90.0
PESO_FINALIZACAO = 2.0

MAX_MENSAGENS = 200

STATUS_ATIVOS = {
    "aguardando_decisao",
    "na_fila",
    "preparando",
    "mapeando",
    "convertendo",
    "finalizando",
}
STATUS_FINAIS = {"concluido", "erro", "cancelado"}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitizar_nome(nome: str) -> str:
    """Gera um nome de arquivo seguro preservando o nome original do usuario."""

    nome = Path(nome or "").name or "documento.pdf"
    nome = unicodedata.normalize("NFC", nome)
    nome = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", nome).strip(" .")
    return nome or "documento.pdf"


class Tarefa:
    """Estado observavel de uma conversao."""

    def __init__(self, id_tarefa: str, nome_arquivo: str, opcoes: OpcoesConversao, pasta: Path):
        self.id = id_tarefa
        self.pasta = pasta
        self.opcoes = opcoes
        self._lock = threading.Lock()
        self._cancelar = threading.Event()
        self.versao = 0

        nome_seguro = sanitizar_nome(nome_arquivo)
        stem = Path(nome_seguro).stem or "documento"

        self.caminho_pdf = pasta / nome_seguro
        # Mesmo nome do PDF, trocando apenas a extensao.
        self.caminho_md = pasta / f"{stem}.md"

        self._estado: dict = {
            "id": id_tarefa,
            "nome_arquivo": nome_seguro,
            "nome_saida": self.caminho_md.name,
            "status": "na_fila",
            "fase": "Na fila",
            "percentual": 0.0,
            "total_paginas": 0,
            "paginas_processadas": 0,
            "lote_atual": 0,
            "total_lotes": 0,
            "kb_gerados": 0.0,
            "tamanho_pdf": 0,
            "posicao_fila": 0,
            "erro": None,
            "criado_em": _agora(),
            "iniciado_em": None,
            "finalizado_em": None,
            "segundos": 0.0,
            "opcoes": asdict(opcoes),
            "diagnostico": None,
            "mensagens": [],
        }

    # ------------------------------------------------------------------ estado
    def atualizar(self, **campos) -> None:
        with self._lock:
            self._estado.update(campos)
            self.versao += 1

    def registrar_mensagem(self, texto: str, nivel: str = "info") -> None:
        with self._lock:
            mensagens = self._estado["mensagens"]
            mensagens.append({"hora": _agora(), "nivel": nivel, "texto": texto})
            if len(mensagens) > MAX_MENSAGENS:
                del mensagens[: len(mensagens) - MAX_MENSAGENS]
            self.versao += 1

    def registrar_diagnostico(self, diagnostico: DiagnosticoTexto, precisa_decisao: bool) -> None:
        """Guarda a checagem de texto selecionavel feita logo apos o upload."""
        self.atualizar(diagnostico=diagnostico.para_dicionario())
        self.registrar_mensagem(
            diagnostico.resumo,
            "aviso" if diagnostico.ocr_recomendado else "info",
        )
        if precisa_decisao:
            self.atualizar(
                status="aguardando_decisao",
                fase="Aguardando sua decisão sobre o OCR",
            )

    def aplicar_decisao(self, ocr: bool) -> None:
        """Aplica a escolha do usuario sobre o OCR e libera a conversao."""
        self.opcoes.ocr = ocr
        self.atualizar(
            status="na_fila",
            fase="Na fila",
            opcoes=asdict(self.opcoes),
        )
        self.registrar_mensagem(
            f"Decisão do usuário: OCR {'ligado' if ocr else 'desligado'}."
        )

    def instantaneo(self) -> dict:
        with self._lock:
            estado = dict(self._estado)
            estado["mensagens"] = list(self._estado["mensagens"])
            estado["versao"] = self.versao
            estado["cancelamento_solicitado"] = self._cancelar.is_set()
            estado["ativo"] = estado["status"] in STATUS_ATIVOS
            estado["aguardando_decisao"] = estado["status"] == "aguardando_decisao"
            estado["markdown_disponivel"] = (
                self.caminho_md.exists() and self.caminho_md.stat().st_size > 0
            )
            return estado

    @property
    def status(self) -> str:
        with self._lock:
            return self._estado["status"]

    # ------------------------------------------------------------- cancelamento
    def solicitar_cancelamento(self) -> None:
        self._cancelar.set()
        if self.status == "aguardando_decisao":
            # Ainda nao foi para a fila: nao ha trabalhador para interromper.
            self.atualizar(status="cancelado", fase="Cancelado", finalizado_em=_agora())
        elif self.status == "na_fila":
            self.atualizar(status="cancelado", fase="Cancelado na fila", finalizado_em=_agora())
        self.registrar_mensagem("Cancelamento solicitado pelo usuario.", "aviso")

    @property
    def cancelamento_solicitado(self) -> bool:
        return self._cancelar.is_set()


class _OuvinteTarefa(OuvinteProgresso):
    """Traduz os eventos do pipeline em atualizacoes de estado da tarefa."""

    def __init__(self, tarefa: Tarefa):
        self.tarefa = tarefa

    def mensagem(self, texto: str, nivel: str = "info") -> None:
        self.tarefa.registrar_mensagem(texto, nivel)

    def arquivo_aberto(self, total_paginas: int) -> None:
        self.tarefa.atualizar(
            status="mapeando",
            fase="Mapeando pontos de corte seguros",
            total_paginas=total_paginas,
        )
        self.tarefa.registrar_mensagem(f"PDF aberto: {total_paginas} pagina(s).")

    def mapeamento_progresso(self, paginas_analisadas: int, total_paginas: int) -> None:
        if total_paginas <= 0:
            return
        fracao = min(1.0, paginas_analisadas / total_paginas)
        self.tarefa.atualizar(percentual=round(PESO_MAPEAMENTO * fracao, 2))

    def lotes_definidos(self, intervalos: list[tuple[int, int]]) -> None:
        self.tarefa.atualizar(
            total_lotes=len(intervalos),
            percentual=PESO_MAPEAMENTO,
            fase="Lotes definidos",
        )

    def lote_iniciado(self, indice: int, total: int, inicio: int, fim: int) -> None:
        self.tarefa.atualizar(
            status="convertendo",
            lote_atual=indice,
            total_lotes=total,
            fase=f"Processando lote {indice} de {total} (paginas {inicio + 1} a {fim})",
        )
        self.tarefa.registrar_mensagem(
            f"Lote {indice}/{total}: convertendo paginas {inicio + 1} a {fim}."
        )

    def lote_concluido(self, indice: int, total: int, paginas: int, kb: float) -> None:
        estado = self.tarefa.instantaneo()
        paginas_processadas = estado["paginas_processadas"] + paginas
        kb_gerados = estado["kb_gerados"] + kb
        total_paginas = max(1, estado["total_paginas"])
        fracao = min(1.0, paginas_processadas / total_paginas)
        self.tarefa.atualizar(
            paginas_processadas=paginas_processadas,
            kb_gerados=round(kb_gerados, 2),
            percentual=round(PESO_MAPEAMENTO + PESO_CONVERSAO * fracao, 2),
        )
        self.tarefa.registrar_mensagem(
            f"Lote {indice}/{total} concluido: +{kb:.2f} KB de Markdown.", "sucesso"
        )

    def cancelado(self) -> bool:
        return self.tarefa.cancelamento_solicitado


class GerenciadorDeTarefas:
    """Fila de conversoes com um unico trabalhador."""

    def __init__(self, pasta_dados: Path, retencao_horas: float = 24.0):
        self.pasta_dados = Path(pasta_dados)
        self.pasta_dados.mkdir(parents=True, exist_ok=True)
        self.retencao_horas = retencao_horas
        self._tarefas: dict[str, Tarefa] = {}
        self._ordem: list[str] = []
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="conversao")

    # ------------------------------------------------------------------- CRUD
    def criar(self, nome_arquivo: str, opcoes: OpcoesConversao) -> Tarefa:
        id_tarefa = uuid.uuid4().hex[:12]
        pasta = self.pasta_dados / id_tarefa
        pasta.mkdir(parents=True, exist_ok=True)
        tarefa = Tarefa(id_tarefa, nome_arquivo, opcoes, pasta)
        with self._lock:
            self._tarefas[id_tarefa] = tarefa
            self._ordem.append(id_tarefa)
        return tarefa

    def enfileirar(self, tarefa: Tarefa) -> None:
        tarefa.atualizar(
            tamanho_pdf=tarefa.caminho_pdf.stat().st_size if tarefa.caminho_pdf.exists() else 0,
            posicao_fila=self._posicao_na_fila(tarefa.id),
        )
        tarefa.registrar_mensagem("Na fila de processamento.")
        self._executor.submit(self._executar, tarefa)

    def obter(self, id_tarefa: str) -> Tarefa | None:
        with self._lock:
            return self._tarefas.get(id_tarefa)

    def listar(self) -> list[dict]:
        with self._lock:
            tarefas = [self._tarefas[i] for i in self._ordem if i in self._tarefas]
        return [t.instantaneo() for t in tarefas]

    def remover(self, id_tarefa: str) -> bool:
        with self._lock:
            tarefa = self._tarefas.pop(id_tarefa, None)
            if id_tarefa in self._ordem:
                self._ordem.remove(id_tarefa)
        if not tarefa:
            return False
        tarefa.solicitar_cancelamento()
        shutil.rmtree(tarefa.pasta, ignore_errors=True)
        return True

    def _posicao_na_fila(self, id_tarefa: str) -> int:
        with self._lock:
            pendentes = [
                i for i in self._ordem
                if i in self._tarefas and self._tarefas[i].status in {"na_fila", "preparando"}
            ]
        return pendentes.index(id_tarefa) if id_tarefa in pendentes else 0

    # -------------------------------------------------------------- execucao
    def _executar(self, tarefa: Tarefa) -> None:
        if tarefa.cancelamento_solicitado:
            tarefa.atualizar(status="cancelado", fase="Cancelado", finalizado_em=_agora())
            return

        inicio = time.monotonic()
        tarefa.atualizar(
            status="preparando",
            fase="Preparando ambiente",
            iniciado_em=_agora(),
            posicao_fila=0,
        )
        ouvinte = _OuvinteTarefa(tarefa)

        try:
            resultado = processar_pdf_em_lotes(
                tarefa.caminho_pdf, tarefa.caminho_md, tarefa.opcoes, ouvinte
            )
            tarefa.atualizar(
                status="finalizando",
                fase="Montagem final do Markdown",
                percentual=PESO_MAPEAMENTO + PESO_CONVERSAO,
            )
            tarefa.atualizar(
                status="concluido",
                fase="Concluido",
                percentual=100.0,
                kb_gerados=round(resultado.kb_gerados, 2),
                paginas_processadas=resultado.total_paginas,
                total_paginas=resultado.total_paginas,
                total_lotes=resultado.total_lotes,
                segundos=round(resultado.segundos, 1),
                finalizado_em=_agora(),
            )
            tarefa.registrar_mensagem(
                f"Conversao concluida em {resultado.segundos:.1f}s. "
                f"Arquivo final: {tarefa.caminho_md.name} ({resultado.kb_gerados:.2f} KB).",
                "sucesso",
            )
        except ConversaoCancelada:
            tarefa.atualizar(
                status="cancelado",
                fase="Cancelado pelo usuario",
                segundos=round(time.monotonic() - inicio, 1),
                finalizado_em=_agora(),
            )
            tarefa.registrar_mensagem("Processamento interrompido.", "aviso")
        except Exception as exc:  # noqa: BLE001 - erro precisa chegar a interface
            detalhe = f"{type(exc).__name__}: {exc}"
            tarefa.atualizar(
                status="erro",
                fase="Erro no processamento",
                erro=detalhe,
                segundos=round(time.monotonic() - inicio, 1),
                finalizado_em=_agora(),
            )
            tarefa.registrar_mensagem(detalhe, "erro")
            tarefa.registrar_mensagem(traceback.format_exc(limit=5), "erro")

    # -------------------------------------------------------------- limpeza
    def limpar_antigas(self) -> int:
        """Remove pastas de tarefas mais antigas que a janela de retencao."""

        if self.retencao_horas <= 0:
            return 0
        limite = time.time() - self.retencao_horas * 3600
        removidas = 0
        for pasta in self.pasta_dados.iterdir():
            if not pasta.is_dir():
                continue
            with self._lock:
                tarefa = self._tarefas.get(pasta.name)
            if tarefa and tarefa.status in STATUS_ATIVOS:
                continue
            try:
                if pasta.stat().st_mtime < limite:
                    shutil.rmtree(pasta, ignore_errors=True)
                    with self._lock:
                        self._tarefas.pop(pasta.name, None)
                        if pasta.name in self._ordem:
                            self._ordem.remove(pasta.name)
                    removidas += 1
            except OSError:
                continue
        return removidas

    def encerrar(self) -> None:
        for tarefa in list(self._tarefas.values()):
            if tarefa.status in STATUS_ATIVOS:
                tarefa.solicitar_cancelamento()
        self._executor.shutdown(wait=False, cancel_futures=True)

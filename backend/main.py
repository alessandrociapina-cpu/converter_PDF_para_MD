"""Servidor local do Conversor PDF -> Markdown.

Sobe uma API HTTP leve (FastAPI) e serve a interface PWA na mesma porta, para
que o usuario final trabalhe apenas pelo navegador, sem terminal.
"""

from __future__ import annotations

# Precisa vir antes de qualquer import que carregue PyTorch/Docling.
from . import ambiente  # noqa: F401

import asyncio
import importlib.util
import json
import os
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .conversor import MODO_SIMULADO, OpcoesConversao, diagnosticar_texto
from .tarefas import GerenciadorDeTarefas

RAIZ = Path(__file__).resolve().parent.parent
PASTA_FRONTEND = RAIZ / "frontend"
PASTA_DADOS = Path(os.environ.get("CONVERSOR_PASTA_DADOS", RAIZ / "dados")).resolve()

TAMANHO_BLOCO_UPLOAD = 1024 * 1024  # 1 MB por leitura, para nao inflar a RAM
LIMITE_UPLOAD_MB = float(os.environ.get("CONVERSOR_LIMITE_MB", "2048"))
RETENCAO_HORAS = float(os.environ.get("CONVERSOR_RETENCAO_HORAS", "24"))
LIMITE_PREVIA_KB = 800

gerenciador = GerenciadorDeTarefas(PASTA_DADOS, retencao_horas=RETENCAO_HORAS)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    removidas = gerenciador.limpar_antigas()
    if removidas:
        print(f"[limpeza] {removidas} conversao(oes) antiga(s) removida(s).")
    yield
    gerenciador.encerrar()


app = FastAPI(
    title="Conversor PDF para Markdown",
    description="Interface local para converter PDFs volumosos com Docling.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)


def _docling_instalado() -> bool:
    # find_spec nao executa o modulo: evita carregar o PyTorch so para checar.
    return importlib.util.find_spec("docling") is not None


def _tarefa_ou_404(id_tarefa: str):
    tarefa = gerenciador.obter(id_tarefa)
    if tarefa is None:
        raise HTTPException(status_code=404, detail="Conversao nao encontrada.")
    return tarefa


# --------------------------------------------------------------------- API
@app.get("/api/saude")
async def saude() -> dict:
    return {
        "ok": True,
        "docling_instalado": _docling_instalado(),
        "modo_simulado": MODO_SIMULADO,
        "limite_upload_mb": LIMITE_UPLOAD_MB,
        "pasta_dados": str(PASTA_DADOS),
    }


@app.get("/api/conversoes")
async def listar_conversoes() -> list[dict]:
    return gerenciador.listar()


@app.post("/api/conversoes", status_code=201)
async def criar_conversao(
    arquivo: UploadFile = File(...),
    tamanho_lote: int = Form(50),
    ocr: bool = Form(False),
    estrutura_tabelas: bool = Form(True),
    corte_inteligente: bool = Form(True),
) -> dict:
    nome = (arquivo.filename or "").strip()
    if not nome.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo com extensao .pdf.")

    opcoes = OpcoesConversao(
        tamanho_lote=tamanho_lote,
        ocr=ocr,
        estrutura_tabelas=estrutura_tabelas,
        corte_inteligente=corte_inteligente,
    ).normalizar()

    tarefa = gerenciador.criar(nome, opcoes)
    limite_bytes = int(LIMITE_UPLOAD_MB * 1024 * 1024)
    total = 0

    try:
        with open(tarefa.caminho_pdf, "wb") as destino:
            primeiro_bloco = True
            while bloco := await arquivo.read(TAMANHO_BLOCO_UPLOAD):
                if primeiro_bloco:
                    if not bloco.startswith(b"%PDF"):
                        raise HTTPException(
                            status_code=400,
                            detail="O arquivo enviado nao parece ser um PDF valido.",
                        )
                    primeiro_bloco = False
                total += len(bloco)
                if total > limite_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Arquivo maior que o limite de {LIMITE_UPLOAD_MB:.0f} MB.",
                    )
                destino.write(bloco)
    except HTTPException:
        gerenciador.remover(tarefa.id)
        raise
    except Exception as exc:  # noqa: BLE001
        gerenciador.remover(tarefa.id)
        raise HTTPException(status_code=500, detail=f"Falha ao salvar o arquivo: {exc}") from exc
    finally:
        await arquivo.close()

    if total == 0:
        gerenciador.remover(tarefa.id)
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    # Checagem rapida (PyMuPDF, sem carregar o Docling): o PDF tem texto
    # selecionavel ou vai precisar de OCR? Roda em thread separada para nao
    # travar o servidor durante a leitura das paginas amostradas.
    try:
        diagnostico = await asyncio.to_thread(diagnosticar_texto, tarefa.caminho_pdf)
    except Exception as exc:  # noqa: BLE001 - diagnostico nunca deve impedir a conversao
        tarefa.registrar_mensagem(
            f"Não foi possível verificar o texto do PDF ({exc}). Seguindo com as opções escolhidas.",
            "aviso",
        )
        gerenciador.enfileirar(tarefa)
        return tarefa.instantaneo()

    precisa_decisao = _precisa_confirmar_ocr(diagnostico, opcoes)
    tarefa.registrar_diagnostico(diagnostico, precisa_decisao)

    if not precisa_decisao:
        gerenciador.enfileirar(tarefa)
    return tarefa.instantaneo()


def _precisa_confirmar_ocr(diagnostico, opcoes: OpcoesConversao) -> bool:
    """Decide se vale interromper o usuario antes de comecar a conversao.

    Dois casos justificam a pergunta:

    * o PDF precisa de OCR e o OCR esta desligado -- sem confirmar, o usuario
      espera a conversao inteira para receber um Markdown vazio;
    * o PDF ja tem texto e o OCR foi ligado -- o OCR multiplicaria o tempo de
      CPU sem ganho nenhum.
    """

    if diagnostico.ocr_recomendado and not opcoes.ocr:
        return True
    if opcoes.ocr and diagnostico.classificacao == "texto":
        return True
    return False


@app.post("/api/conversoes/{id_tarefa}/iniciar")
async def iniciar_conversao(id_tarefa: str, ocr: bool = Body(False, embed=True)) -> dict:
    """Confirma a escolha de OCR feita na interface e libera a conversao."""

    tarefa = _tarefa_ou_404(id_tarefa)
    if tarefa.instantaneo()["status"] != "aguardando_decisao":
        raise HTTPException(
            status_code=409,
            detail="Esta conversão não está aguardando decisão.",
        )
    tarefa.aplicar_decisao(bool(ocr))
    gerenciador.enfileirar(tarefa)
    return tarefa.instantaneo()


@app.get("/api/conversoes/{id_tarefa}")
async def obter_conversao(id_tarefa: str) -> dict:
    return _tarefa_ou_404(id_tarefa).instantaneo()


@app.get("/api/conversoes/{id_tarefa}/eventos")
async def eventos_conversao(id_tarefa: str, request: Request) -> StreamingResponse:
    """Fluxo SSE com o estado da conversao (a interface tambem sabe usar polling)."""

    tarefa = _tarefa_ou_404(id_tarefa)

    async def gerador():
        ultima_versao = -1
        while True:
            if await request.is_disconnected():
                break
            estado = tarefa.instantaneo()
            if estado["versao"] != ultima_versao:
                ultima_versao = estado["versao"]
                yield f"data: {json.dumps(estado, ensure_ascii=False)}\n\n"
                if not estado["ativo"]:
                    break
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gerador(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/conversoes/{id_tarefa}/cancelar")
async def cancelar_conversao(id_tarefa: str) -> dict:
    tarefa = _tarefa_ou_404(id_tarefa)
    tarefa.solicitar_cancelamento()
    return tarefa.instantaneo()


@app.delete("/api/conversoes/{id_tarefa}")
async def remover_conversao(id_tarefa: str) -> dict:
    if not gerenciador.remover(id_tarefa):
        raise HTTPException(status_code=404, detail="Conversao nao encontrada.")
    return {"removido": True}


@app.get("/api/conversoes/{id_tarefa}/markdown")
async def previa_markdown(id_tarefa: str, limite_kb: int = LIMITE_PREVIA_KB) -> JSONResponse:
    tarefa = _tarefa_ou_404(id_tarefa)
    if not tarefa.caminho_md.exists():
        raise HTTPException(status_code=404, detail="Markdown ainda nao gerado.")

    limite_bytes = max(1, limite_kb) * 1024
    tamanho = tarefa.caminho_md.stat().st_size
    with open(tarefa.caminho_md, "r", encoding="utf-8", errors="replace") as arquivo:
        conteudo = arquivo.read(limite_bytes)

    return JSONResponse(
        {
            "nome": tarefa.caminho_md.name,
            "tamanho_bytes": tamanho,
            "truncado": tamanho > len(conteudo.encode("utf-8")),
            "conteudo": conteudo,
        }
    )


@app.get("/api/conversoes/{id_tarefa}/download")
async def baixar_markdown(id_tarefa: str) -> FileResponse:
    tarefa = _tarefa_ou_404(id_tarefa)
    if not tarefa.caminho_md.exists():
        raise HTTPException(status_code=404, detail="Markdown ainda nao gerado.")
    return FileResponse(
        tarefa.caminho_md,
        media_type="text/markdown; charset=utf-8",
        filename=tarefa.caminho_md.name,
    )


# ---------------------------------------------------------------- frontend
@app.get("/", include_in_schema=False)
async def pagina_inicial() -> HTMLResponse:
    indice = PASTA_FRONTEND / "index.html"
    if not indice.exists():
        raise HTTPException(status_code=500, detail="Interface nao encontrada.")
    return HTMLResponse(indice.read_text(encoding="utf-8"))


@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> FileResponse:
    # O Service Worker precisa ser servido na raiz para controlar todo o app.
    return FileResponse(
        PASTA_FRONTEND / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/manifest.json", include_in_schema=False)
async def manifesto() -> FileResponse:
    return FileResponse(PASTA_FRONTEND / "manifest.json", media_type="application/manifest+json")


app.mount("/estatico", StaticFiles(directory=PASTA_FRONTEND), name="estatico")


def iniciar(host: str = "127.0.0.1", porta: int = 8000, abrir_navegador: bool = True) -> None:
    """Sobe o servidor local (usado pelo iniciar_app.bat / iniciar_app.sh)."""

    import threading

    import uvicorn

    url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{porta}"
    print("=" * 62)
    print("  Conversor PDF -> Markdown (Docling)")
    print(f"  Interface disponivel em: {url}")
    print("  Feche esta janela para encerrar o servidor.")
    if not _docling_instalado() and not MODO_SIMULADO:
        print("  ATENCAO: o pacote 'docling' nao foi encontrado no ambiente.")
    print("=" * 62)

    if abrir_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=porta, log_level="info")


if __name__ == "__main__":
    iniciar(
        host=os.environ.get("CONVERSOR_HOST", "127.0.0.1"),
        porta=int(os.environ.get("CONVERSOR_PORTA", "8000")),
        abrir_navegador=os.environ.get("CONVERSOR_ABRIR_NAVEGADOR", "1") != "0",
    )

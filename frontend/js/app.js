/**
 * Interface do Conversor PDF -> Markdown.
 *
 * Conversa com o servidor local (FastAPI) por três canais:
 *   - POST /api/conversoes ............ envio do PDF (com progresso de upload)
 *   - GET  /api/conversoes/{id}/eventos  acompanhamento em tempo real (SSE)
 *   - GET  /api/conversoes/{id} ....... polling de reserva, se o SSE cair
 */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const elementos = {
    selo: $('selo-ambiente'),
    botaoInstalar: $('botao-instalar'),

    areaSolta: $('area-solta'),
    entradaArquivo: $('entrada-arquivo'),
    arquivoEscolhido: $('arquivo-escolhido'),
    arquivoNome: $('arquivo-nome'),
    arquivoTamanho: $('arquivo-tamanho'),
    arquivoSaida: $('arquivo-saida'),
    botaoTrocar: $('botao-trocar'),

    campoLote: $('campo-lote'),
    campoLoteFaixa: $('campo-lote-faixa'),
    campoOcr: $('campo-ocr'),
    campoTabelas: $('campo-tabelas'),
    campoCorte: $('campo-corte'),
    botaoConverter: $('botao-converter'),
    dicaConverter: $('dica-converter'),

    cartaoVerificacao: $('cartao-verificacao'),
    verificacaoResumo: $('verificacao-resumo'),
    verificacaoClassificacao: $('verificacao-classificacao'),
    verificacaoAmostra: $('verificacao-amostra'),
    verificacaoPercentual: $('verificacao-percentual'),
    verificacaoCaracteres: $('verificacao-caracteres'),
    verificacaoNota: $('verificacao-nota'),
    botaoDecisaoPrincipal: $('botao-decisao-principal'),
    botaoDecisaoAlternativa: $('botao-decisao-alternativa'),
    botaoDecisaoCancelar: $('botao-decisao-cancelar'),

    cartaoProgresso: $('cartao-progresso'),
    progressoArquivo: $('progresso-arquivo'),
    progressoFase: $('progresso-fase'),
    progressoNumero: $('progresso-numero'),
    barra: $('barra'),
    barraPreenchimento: $('barra-preenchimento'),
    fases: $('fases'),
    indicadorPaginas: $('indicador-paginas'),
    indicadorLotes: $('indicador-lotes'),
    indicadorKb: $('indicador-kb'),
    indicadorTempo: $('indicador-tempo'),
    registroLista: $('registro-lista'),
    botaoCancelar: $('botao-cancelar'),

    cartaoResultado: $('cartao-resultado'),
    resultadoResumo: $('resultado-resumo'),
    botaoBaixar: $('botao-baixar'),
    botaoPrevia: $('botao-previa'),
    botaoNova: $('botao-nova'),

    cartaoHistorico: $('cartao-historico'),
    historicoLista: $('historico-lista'),

    modal: $('modal-previa'),
    modalTitulo: $('modal-titulo'),
    modalAviso: $('modal-aviso'),
    modalFechar: $('modal-fechar'),
    abaRenderizado: $('aba-renderizado'),
    abaFonte: $('aba-fonte'),
    previaRenderizada: $('previa-renderizada'),
    previaFonte: $('previa-fonte'),

    avisos: $('avisos'),
  };

  const estado = {
    arquivo: null,
    idTarefa: null,
    fonteEventos: null,
    temporizadorPolling: null,
    cronometro: null,
    inicioCronometro: 0,
    mensagensExibidas: 0,
    envioEmAndamento: false,
    decisaoOcr: null,
    historico: [],
    promptInstalacao: null,
  };

  const ORDEM_FASES = ['mapeando', 'convertendo', 'finalizando'];

  // ------------------------------------------------------------- utilidades
  function formatarBytes(bytes) {
    if (!bytes) return '0 B';
    const unidades = ['B', 'KB', 'MB', 'GB'];
    const indice = Math.min(unidades.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    const valor = bytes / Math.pow(1024, indice);
    return `${valor.toFixed(valor >= 100 || indice === 0 ? 0 : 1)} ${unidades[indice]}`;
  }

  function formatarKb(kb) {
    return kb >= 1024 ? `${(kb / 1024).toFixed(2)} MB` : `${kb.toFixed(1)} KB`;
  }

  function formatarDuracao(segundos) {
    const total = Math.max(0, Math.floor(segundos));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const dois = (n) => String(n).padStart(2, '0');
    return h > 0 ? `${dois(h)}:${dois(m)}:${dois(s)}` : `${dois(m)}:${dois(s)}`;
  }

  function nomeDeSaida(nomePdf) {
    return nomePdf.replace(/\.pdf$/i, '') + '.md';
  }

  function avisar(texto, tipo) {
    const item = document.createElement('div');
    item.className = `aviso${tipo ? ` aviso--${tipo}` : ''}`;
    item.textContent = texto;
    elementos.avisos.appendChild(item);
    setTimeout(() => item.remove(), tipo === 'erro' ? 9000 : 5000);
  }

  // ------------------------------------------------------- seleção de arquivo
  function selecionarArquivo(arquivo) {
    if (!arquivo) return;
    const ehPdf = arquivo.type === 'application/pdf' || /\.pdf$/i.test(arquivo.name);
    if (!ehPdf) {
      avisar('Selecione um arquivo com extensão .pdf.', 'erro');
      return;
    }
    estado.arquivo = arquivo;
    elementos.arquivoNome.textContent = arquivo.name;
    elementos.arquivoTamanho.textContent = formatarBytes(arquivo.size);
    elementos.arquivoSaida.textContent = nomeDeSaida(arquivo.name);
    elementos.arquivoEscolhido.hidden = false;
    elementos.areaSolta.hidden = true;
    elementos.botaoConverter.disabled = false;
    elementos.dicaConverter.textContent =
      'O arquivo final terá o mesmo nome do PDF, apenas com a extensão .md.';
  }

  function limparSelecao() {
    estado.arquivo = null;
    elementos.entradaArquivo.value = '';
    elementos.arquivoEscolhido.hidden = true;
    elementos.areaSolta.hidden = false;
    elementos.botaoConverter.disabled = true;
    elementos.dicaConverter.textContent = 'Escolha um PDF para liberar a conversão.';
  }

  elementos.areaSolta.addEventListener('click', () => elementos.entradaArquivo.click());
  elementos.areaSolta.addEventListener('keydown', (evento) => {
    if (evento.key === 'Enter' || evento.key === ' ') {
      evento.preventDefault();
      elementos.entradaArquivo.click();
    }
  });
  elementos.entradaArquivo.addEventListener('change', (evento) => {
    selecionarArquivo(evento.target.files[0]);
  });
  elementos.botaoTrocar.addEventListener('click', () => {
    limparSelecao();
    elementos.entradaArquivo.click();
  });

  ['dragenter', 'dragover'].forEach((evt) => {
    elementos.areaSolta.addEventListener(evt, (evento) => {
      evento.preventDefault();
      elementos.areaSolta.classList.add('is-arrastando');
    });
  });
  ['dragleave', 'drop'].forEach((evt) => {
    elementos.areaSolta.addEventListener(evt, (evento) => {
      evento.preventDefault();
      elementos.areaSolta.classList.remove('is-arrastando');
    });
  });
  elementos.areaSolta.addEventListener('drop', (evento) => {
    selecionarArquivo(evento.dataTransfer.files[0]);
  });
  // Evita que o navegador abra o PDF ao soltá-lo fora da área indicada.
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => e.preventDefault());

  // ------------------------------------------------------------------ opções
  elementos.campoLoteFaixa.addEventListener('input', () => {
    elementos.campoLote.value = elementos.campoLoteFaixa.value;
  });
  elementos.campoLote.addEventListener('input', () => {
    const valor = Number(elementos.campoLote.value);
    if (Number.isFinite(valor)) {
      elementos.campoLoteFaixa.value = Math.min(200, Math.max(10, valor));
    }
  });

  function lerOpcoes() {
    const lote = Math.min(500, Math.max(1, Number(elementos.campoLote.value) || 50));
    elementos.campoLote.value = lote;
    return {
      tamanho_lote: lote,
      ocr: elementos.campoOcr.checked,
      estrutura_tabelas: elementos.campoTabelas.checked,
      corte_inteligente: elementos.campoCorte.checked,
    };
  }

  // -------------------------------------------------------------- conversão
  elementos.botaoConverter.addEventListener('click', enviarArquivo);

  function enviarArquivo() {
    if (!estado.arquivo || estado.envioEmAndamento) return;

    const opcoes = lerOpcoes();
    const dados = new FormData();
    dados.append('arquivo', estado.arquivo, estado.arquivo.name);
    Object.entries(opcoes).forEach(([chave, valor]) => dados.append(chave, String(valor)));

    prepararPainelProgresso(estado.arquivo.name);
    estado.envioEmAndamento = true;
    elementos.botaoConverter.disabled = true;
    elementos.botaoCancelar.disabled = true;

    const requisicao = new XMLHttpRequest();
    requisicao.open('POST', '/api/conversoes');
    requisicao.responseType = 'json';

    requisicao.upload.addEventListener('progress', (evento) => {
      if (!evento.lengthComputable) return;
      const percentual = (evento.loaded / evento.total) * 100;
      elementos.progressoFase.textContent = `Enviando o PDF para o servidor local… ${percentual.toFixed(0)}%`;
      definirBarra(percentual * 0.02);
    });

    requisicao.addEventListener('load', () => {
      estado.envioEmAndamento = false;
      elementos.botaoCancelar.disabled = false;
      const corpo = requisicao.response;
      if (requisicao.status !== 201) {
        const detalhe = (corpo && (corpo.detail || corpo.erro)) || `Erro ${requisicao.status}`;
        falhar(String(detalhe));
        return;
      }
      registrarMensagem({ nivel: 'info', texto: 'Upload concluído.', hora: new Date().toISOString() });
      estado.idTarefa = corpo.id;

      if (corpo.aguardando_decisao) {
        // O servidor analisou o PDF e a escolha de OCR não combina com ele.
        aplicarEstado(corpo);
        pararCronometro();
        mostrarVerificacao(corpo);
        return;
      }

      aplicarEstado(corpo);
      acompanhar(corpo.id);
    });

    requisicao.addEventListener('error', () => {
      estado.envioEmAndamento = false;
      falhar('Não foi possível falar com o servidor local. Verifique se a janela do servidor continua aberta.');
    });

    requisicao.send(dados);
  }

  function prepararPainelProgresso(nomeArquivo) {
    estado.mensagensExibidas = 0;
    elementos.registroLista.innerHTML = '';
    elementos.cartaoResultado.hidden = true;
    elementos.cartaoVerificacao.hidden = true;
    elementos.cartaoProgresso.hidden = false;
    elementos.botaoCancelar.hidden = false;
    elementos.barra.className = 'barra';
    elementos.progressoArquivo.textContent = `${nomeArquivo} → ${nomeDeSaida(nomeArquivo)}`;
    elementos.progressoFase.textContent = 'Enviando o PDF para o servidor local…';
    elementos.indicadorPaginas.textContent = '0 / 0';
    elementos.indicadorLotes.textContent = '0 / 0';
    elementos.indicadorKb.textContent = '0 KB';
    definirBarra(0);
    marcarFases(null);
    iniciarCronometro();
    elementos.cartaoProgresso.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function definirBarra(percentual) {
    const valor = Math.max(0, Math.min(100, percentual));
    elementos.barraPreenchimento.style.width = `${valor}%`;
    elementos.progressoNumero.textContent = valor.toFixed(valor >= 100 || valor === 0 ? 0 : 1);
    elementos.barra.setAttribute('aria-valuenow', valor.toFixed(0));
  }

  function marcarFases(statusAtual) {
    const indiceAtual = ORDEM_FASES.indexOf(statusAtual);
    elementos.fases.querySelectorAll('.fase').forEach((item) => {
      const indice = ORDEM_FASES.indexOf(item.dataset.fase);
      item.classList.remove('is-ativa', 'is-concluida');
      if (statusAtual === 'concluido') {
        item.classList.add('is-concluida');
      } else if (indiceAtual >= 0) {
        if (indice < indiceAtual) item.classList.add('is-concluida');
        else if (indice === indiceAtual) item.classList.add('is-ativa');
      }
    });
  }

  function iniciarCronometro() {
    pararCronometro();
    estado.inicioCronometro = Date.now();
    elementos.indicadorTempo.textContent = '00:00';
    estado.cronometro = setInterval(() => {
      elementos.indicadorTempo.textContent =
        formatarDuracao((Date.now() - estado.inicioCronometro) / 1000);
    }, 1000);
  }

  function pararCronometro() {
    if (estado.cronometro) {
      clearInterval(estado.cronometro);
      estado.cronometro = null;
    }
  }

  // --------------------------------------------------------- verificação
  const ROTULOS_CLASSIFICACAO = {
    texto: 'Texto selecionável',
    misto: 'Misto',
    digitalizado: 'Digitalizado',
    indefinido: 'Indefinido',
  };

  function mostrarVerificacao(tarefa) {
    const diagnostico = tarefa.diagnostico || {};
    const precisaOcr = Boolean(diagnostico.ocr_recomendado);

    elementos.verificacaoResumo.textContent = diagnostico.resumo || '';

    const classificacao = diagnostico.classificacao || 'indefinido';
    elementos.verificacaoClassificacao.innerHTML = '';
    const selo = document.createElement('span');
    selo.className = `verificacao__selo verificacao__selo--${classificacao}`;
    selo.textContent = ROTULOS_CLASSIFICACAO[classificacao] || classificacao;
    elementos.verificacaoClassificacao.appendChild(selo);

    elementos.verificacaoAmostra.textContent =
      `${diagnostico.paginas_amostradas || 0} de ${diagnostico.total_paginas || 0}`;
    elementos.verificacaoPercentual.textContent =
      `${(diagnostico.percentual_com_texto ?? 0).toFixed(0)}%`;
    elementos.verificacaoCaracteres.textContent =
      `${Math.round(diagnostico.media_caracteres || 0)} / página`;

    if (precisaOcr) {
      elementos.verificacaoNota.textContent =
        'Ligar o OCR resolve, mas multiplica o tempo de processamento — em documentos ' +
        'de centenas de páginas pode levar horas nesta máquina.';
      elementos.botaoDecisaoPrincipal.textContent = 'Ligar OCR e converter';
      elementos.botaoDecisaoAlternativa.textContent = 'Converter mesmo assim (sem OCR)';
      estado.decisaoOcr = { principal: true, alternativa: false };
    } else {
      elementos.verificacaoNota.textContent =
        'Você ligou o OCR, mas este PDF já tem texto selecionável. Desligar deixa a ' +
        'conversão muito mais rápida, com o mesmo resultado.';
      elementos.botaoDecisaoPrincipal.textContent = 'Desligar OCR e converter';
      elementos.botaoDecisaoAlternativa.textContent = 'Manter o OCR ligado';
      estado.decisaoOcr = { principal: false, alternativa: true };
    }

    definirBotoesDecisao(true);
    elementos.cartaoVerificacao.hidden = false;
    elementos.cartaoVerificacao.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  async function decidir(ocr) {
    if (!estado.idTarefa) return;
    definirBotoesDecisao(false);
    try {
      const resposta = await fetch(`/api/conversoes/${estado.idTarefa}/iniciar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ocr }),
      });
      if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
      const dados = await resposta.json();

      elementos.campoOcr.checked = ocr;
      elementos.cartaoVerificacao.hidden = true;
      iniciarCronometro();
      aplicarEstado(dados);
      acompanhar(dados.id);
    } catch (erro) {
      avisar('Não foi possível iniciar a conversão.', 'erro');
      definirBotoesDecisao(true);
    }
  }

  function definirBotoesDecisao(habilitados) {
    elementos.botaoDecisaoPrincipal.disabled = !habilitados;
    elementos.botaoDecisaoAlternativa.disabled = !habilitados;
    elementos.botaoDecisaoCancelar.disabled = !habilitados;
  }

  elementos.botaoDecisaoPrincipal.addEventListener('click', () => {
    decidir(estado.decisaoOcr ? estado.decisaoOcr.principal : false);
  });
  elementos.botaoDecisaoAlternativa.addEventListener('click', () => {
    decidir(estado.decisaoOcr ? estado.decisaoOcr.alternativa : false);
  });
  elementos.botaoDecisaoCancelar.addEventListener('click', async () => {
    if (!estado.idTarefa) return;
    definirBotoesDecisao(false);
    try {
      const resposta = await fetch(`/api/conversoes/${estado.idTarefa}/cancelar`, { method: 'POST' });
      const dados = await resposta.json();
      elementos.cartaoVerificacao.hidden = true;
      aplicarEstado(dados);
    } catch (erro) {
      avisar('Não foi possível cancelar.', 'erro');
    } finally {
      definirBotoesDecisao(true);
    }
  });

  // ------------------------------------------------------- acompanhamento
  function acompanhar(id) {
    encerrarAcompanhamento();

    if ('EventSource' in window) {
      const fonte = new EventSource(`/api/conversoes/${id}/eventos`);
      estado.fonteEventos = fonte;
      fonte.onmessage = (evento) => {
        try {
          aplicarEstado(JSON.parse(evento.data));
        } catch (erro) {
          console.error('Evento inválido', erro);
        }
      };
      fonte.onerror = () => {
        // Conexão perdida (ou fluxo encerrado): cai para o polling simples.
        fonte.close();
        estado.fonteEventos = null;
        iniciarPolling(id);
      };
    } else {
      iniciarPolling(id);
    }
  }

  function iniciarPolling(id) {
    if (estado.temporizadorPolling || !estado.idTarefa) return;
    const consultar = async () => {
      try {
        const resposta = await fetch(`/api/conversoes/${id}`);
        if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
        const dados = await resposta.json();
        aplicarEstado(dados);
        if (!dados.ativo) pararPolling();
      } catch (erro) {
        console.warn('Falha ao consultar o andamento', erro);
      }
    };
    estado.temporizadorPolling = setInterval(consultar, 1500);
    consultar();
  }

  function pararPolling() {
    if (estado.temporizadorPolling) {
      clearInterval(estado.temporizadorPolling);
      estado.temporizadorPolling = null;
    }
  }

  function encerrarAcompanhamento() {
    if (estado.fonteEventos) {
      estado.fonteEventos.close();
      estado.fonteEventos = null;
    }
    pararPolling();
  }

  function registrarMensagem(mensagem) {
    const item = document.createElement('li');
    item.dataset.nivel = mensagem.nivel || 'info';
    const hora = document.createElement('span');
    hora.className = 'registro__hora';
    const data = new Date(mensagem.hora);
    hora.textContent = Number.isNaN(data.getTime())
      ? '--:--:--'
      : data.toLocaleTimeString('pt-BR');
    const texto = document.createElement('span');
    texto.className = 'registro__texto';
    texto.textContent = mensagem.texto;
    item.append(hora, texto);
    elementos.registroLista.appendChild(item);
    elementos.registroLista.scrollTop = elementos.registroLista.scrollHeight;
  }

  function aplicarEstado(dados) {
    if (!dados || dados.id !== estado.idTarefa) return;

    definirBarra(dados.percentual || 0);
    elementos.progressoFase.textContent =
      dados.status === 'na_fila' && dados.posicao_fila > 0
        ? `Na fila (${dados.posicao_fila} conversão(ões) à frente)`
        : dados.fase || '—';
    elementos.progressoArquivo.textContent = `${dados.nome_arquivo} → ${dados.nome_saida}`;
    elementos.indicadorPaginas.textContent =
      `${dados.paginas_processadas || 0} / ${dados.total_paginas || 0}`;
    elementos.indicadorLotes.textContent =
      `${dados.lote_atual || 0} / ${dados.total_lotes || 0}`;
    elementos.indicadorKb.textContent = formatarKb(dados.kb_gerados || 0);
    marcarFases(dados.status);

    const novas = (dados.mensagens || []).slice(estado.mensagensExibidas);
    novas.forEach(registrarMensagem);
    estado.mensagensExibidas = (dados.mensagens || []).length;

    elementos.botaoCancelar.hidden = !dados.ativo;

    if (dados.ativo) return;

    encerrarAcompanhamento();
    pararCronometro();
    if (dados.segundos) elementos.indicadorTempo.textContent = formatarDuracao(dados.segundos);

    if (dados.status === 'concluido') {
      concluir(dados);
    } else if (dados.status === 'cancelado') {
      elementos.barra.classList.add('is-cancelado');
      avisar('Conversão cancelada.', null);
      elementos.botaoConverter.disabled = !estado.arquivo;
    } else if (dados.status === 'erro') {
      elementos.barra.classList.add('is-erro');
      avisar(dados.erro || 'Falha no processamento.', 'erro');
      elementos.botaoConverter.disabled = !estado.arquivo;
    }
    adicionarAoHistorico(dados);
  }

  function concluir(dados) {
    definirBarra(100);
    elementos.cartaoResultado.hidden = false;
    elementos.resultadoResumo.textContent =
      `${dados.nome_saida} · ${dados.total_paginas} página(s) em ${dados.total_lotes} lote(s) · ` +
      `${formatarKb(dados.kb_gerados || 0)} de Markdown · ${formatarDuracao(dados.segundos || 0)}`;
    elementos.botaoBaixar.href = `/api/conversoes/${dados.id}/download`;
    elementos.botaoBaixar.setAttribute('download', dados.nome_saida);
    elementos.cartaoResultado.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    elementos.botaoConverter.disabled = !estado.arquivo;
    elementos.dicaConverter.textContent =
      'Quer testar outras opções? Ajuste acima e converta o mesmo PDF de novo.';
    avisar('Markdown gerado com sucesso.', 'sucesso');
  }

  function falhar(mensagem) {
    elementos.barra.classList.add('is-erro');
    elementos.progressoFase.textContent = 'Falha no envio';
    registrarMensagem({ nivel: 'erro', texto: mensagem, hora: new Date().toISOString() });
    pararCronometro();
    avisar(mensagem, 'erro');
    elementos.botaoConverter.disabled = !estado.arquivo;
  }

  elementos.botaoCancelar.addEventListener('click', async () => {
    if (!estado.idTarefa) return;
    elementos.botaoCancelar.disabled = true;
    try {
      const resposta = await fetch(`/api/conversoes/${estado.idTarefa}/cancelar`, { method: 'POST' });
      if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
      elementos.progressoFase.textContent = 'Cancelando após o lote atual…';
    } catch (erro) {
      avisar('Não foi possível cancelar agora.', 'erro');
    } finally {
      elementos.botaoCancelar.disabled = false;
    }
  });

  elementos.botaoNova.addEventListener('click', () => {
    elementos.cartaoResultado.hidden = true;
    elementos.cartaoProgresso.hidden = true;
    estado.idTarefa = null;
    limparSelecao();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  // ------------------------------------------------------------- histórico
  function adicionarAoHistorico(dados) {
    if (estado.historico.some((item) => item.id === dados.id)) return;
    estado.historico.unshift(dados);
    elementos.cartaoHistorico.hidden = false;
    desenharHistorico();
  }

  function desenharHistorico() {
    elementos.historicoLista.innerHTML = '';
    const rotulos = {
      concluido: 'concluído',
      cancelado: 'cancelado',
      erro: 'erro',
    };
    estado.historico.forEach((item) => {
      const li = document.createElement('li');
      li.className = 'historico__item';

      const nome = document.createElement('span');
      nome.className = 'historico__nome';
      nome.textContent = item.nome_saida;

      const situacao = document.createElement('span');
      situacao.className = 'historico__estado';
      situacao.textContent = `${rotulos[item.status] || item.status} · ${formatarKb(item.kb_gerados || 0)}`;

      li.append(nome, situacao);

      if (item.status === 'concluido' || item.markdown_disponivel) {
        const baixar = document.createElement('a');
        baixar.className = 'botao botao--fantasma botao--pequeno';
        baixar.href = `/api/conversoes/${item.id}/download`;
        baixar.setAttribute('download', item.nome_saida);
        baixar.textContent = 'Baixar';

        const ver = document.createElement('button');
        ver.type = 'button';
        ver.className = 'botao botao--fantasma botao--pequeno';
        ver.textContent = 'Ver';
        ver.addEventListener('click', () => abrirPrevia(item.id, item.nome_saida));

        li.append(ver, baixar);
      }
      elementos.historicoLista.appendChild(li);
    });
  }

  // ----------------------------------------------------------- pré-visualização
  elementos.botaoPrevia.addEventListener('click', () => {
    if (estado.idTarefa) {
      const atual = estado.historico.find((item) => item.id === estado.idTarefa);
      abrirPrevia(estado.idTarefa, atual ? atual.nome_saida : 'documento.md');
    }
  });

  async function abrirPrevia(id, nome) {
    try {
      const resposta = await fetch(`/api/conversoes/${id}/markdown`);
      if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
      const dados = await resposta.json();

      elementos.modalTitulo.textContent = dados.nome || nome;
      elementos.previaFonte.textContent = dados.conteudo;
      elementos.previaRenderizada.innerHTML = window.Markdown.renderizar(dados.conteudo);
      elementos.modalAviso.hidden = !dados.truncado;
      if (dados.truncado) {
        elementos.modalAviso.textContent =
          `Pré-visualização parcial: o arquivo tem ${formatarBytes(dados.tamanho_bytes)}. ` +
          'Baixe o .md para ver o conteúdo completo.';
      }
      mostrarAba('renderizado');
      elementos.modal.showModal();
    } catch (erro) {
      avisar('Não foi possível carregar a pré-visualização.', 'erro');
    }
  }

  function mostrarAba(aba) {
    const renderizado = aba === 'renderizado';
    elementos.previaRenderizada.hidden = !renderizado;
    elementos.previaFonte.hidden = renderizado;
    elementos.abaRenderizado.classList.toggle('is-ativo', renderizado);
    elementos.abaFonte.classList.toggle('is-ativo', !renderizado);
    elementos.abaRenderizado.setAttribute('aria-selected', String(renderizado));
    elementos.abaFonte.setAttribute('aria-selected', String(!renderizado));
  }

  elementos.abaRenderizado.addEventListener('click', () => mostrarAba('renderizado'));
  elementos.abaFonte.addEventListener('click', () => mostrarAba('fonte'));
  elementos.modalFechar.addEventListener('click', () => elementos.modal.close());

  // ------------------------------------------------------------- ambiente
  async function verificarAmbiente() {
    try {
      const resposta = await fetch('/api/saude');
      if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
      const dados = await resposta.json();
      if (dados.modo_simulado) {
        elementos.selo.className = 'selo selo--alerta';
        elementos.selo.textContent = 'Modo simulado (sem Docling)';
      } else if (dados.docling_instalado) {
        elementos.selo.className = 'selo selo--ok';
        elementos.selo.textContent = 'Docling pronto';
      } else {
        elementos.selo.className = 'selo selo--erro';
        elementos.selo.textContent = 'Docling não instalado';
        avisar('O pacote docling não foi encontrado no ambiente Python. Rode: pip install -r requirements.txt', 'erro');
      }
    } catch (erro) {
      elementos.selo.className = 'selo selo--erro';
      elementos.selo.textContent = 'Servidor local indisponível';
    }
  }

  window.addEventListener('beforeunload', (evento) => {
    const ativo = estado.envioEmAndamento || Boolean(estado.fonteEventos) || Boolean(estado.temporizadorPolling);
    if (ativo) {
      evento.preventDefault();
      evento.returnValue = '';
    }
  });

  // ------------------------------------------------------------------- PWA
  window.addEventListener('beforeinstallprompt', (evento) => {
    evento.preventDefault();
    estado.promptInstalacao = evento;
    elementos.botaoInstalar.hidden = false;
  });

  elementos.botaoInstalar.addEventListener('click', async () => {
    if (!estado.promptInstalacao) return;
    estado.promptInstalacao.prompt();
    await estado.promptInstalacao.userChoice;
    estado.promptInstalacao = null;
    elementos.botaoInstalar.hidden = true;
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch((erro) => {
        console.warn('Service Worker não registrado:', erro);
      });
    });
  }

  verificarAmbiente();
})();

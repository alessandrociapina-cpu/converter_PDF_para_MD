/**
 * Service Worker do Conversor PDF -> Markdown.
 *
 * Estratégia:
 *   - Nada da API (/api/...) é cacheado: o andamento precisa ser sempre atual.
 *   - A "casca" do app (HTML, CSS, JS, ícones) fica em cache para abrir rápido
 *     e continuar funcionando se o servidor estiver reiniciando.
 *   - Navegações usam rede primeiro, com o cache como reserva.
 */

const VERSAO = 'conversor-md-v1';
const CASCA = [
  '/',
  '/manifest.json',
  '/estatico/css/style.css',
  '/estatico/js/app.js',
  '/estatico/js/markdown.js',
  '/estatico/icones/icone.svg',
  '/estatico/icones/icone-192.png',
  '/estatico/icones/icone-512.png',
];

self.addEventListener('install', (evento) => {
  evento.waitUntil(
    caches.open(VERSAO)
      .then((cache) => cache.addAll(CASCA))
      .then(() => self.skipWaiting())
      .catch((erro) => console.warn('[sw] falha ao montar o cache inicial', erro))
  );
});

self.addEventListener('activate', (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((chaves) => Promise.all(
        chaves.filter((chave) => chave !== VERSAO).map((chave) => caches.delete(chave))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (evento) => {
  const requisicao = evento.request;
  const url = new URL(requisicao.url);

  // Só tratamos GET de mesma origem.
  if (requisicao.method !== 'GET' || url.origin !== self.location.origin) return;

  // A API nunca passa pelo cache.
  if (url.pathname.startsWith('/api/')) return;

  if (requisicao.mode === 'navigate') {
    evento.respondWith(
      fetch(requisicao)
        .then((resposta) => {
          const copia = resposta.clone();
          caches.open(VERSAO).then((cache) => cache.put('/', copia));
          return resposta;
        })
        .catch(() => caches.match('/').then((cacheada) => cacheada || Response.error()))
    );
    return;
  }

  // Demais arquivos: responde do cache e revalida em segundo plano, para que
  // uma atualização do projeto chegue ao usuário no carregamento seguinte.
  evento.respondWith(
    caches.match(requisicao).then((cacheada) => {
      const daRede = fetch(requisicao).then((resposta) => {
        if (resposta.ok && resposta.type === 'basic') {
          const copia = resposta.clone();
          caches.open(VERSAO).then((cache) => cache.put(requisicao, copia));
        }
        return resposta;
      }).catch(() => cacheada || Response.error());
      return cacheada || daRede;
    })
  );
});

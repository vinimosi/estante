// Estante - Leitura: fica no navegador e avisa a Estante (no seu computador) qual capítulo você abriu.
// Só conversa com a Estante em 127.0.0.1. Nada vai para a internet.
const ESTANTE = 'http://127.0.0.1:8765';
const NAVEGADOR = /Edg\//.test(navigator.userAgent) ? 'edge' : 'chrome';
const VERSAO = chrome.runtime.getManifest().version;  // a Estante avisa quando a extensão da pasta é mais nova

// Regras usadas até a Estante mandar as dela (são as mesmas que vêm com a Estante).
const PADRAO = [
  {chave: 'comix', nome: 'Comix', dominio: 'comix.to', antigos: ['comix.ws'],
   capitulo: '^/title/(?<slug>[^/]+)/\\d+-chapter-(?<num>\\d+(?:\\.\\d+)?)', serie: '^/title/(?<slug>[^/]+?)/?$',
   lista: {endereco: '/user?tab=titles', caminho: '^/user/?$', parametro: 'tab=titles', cartao: "a.card[href^='/title/']",
           titulo: '.card__title', capitulos: '.card__ch', proxima: "button[aria-label='Next page']", pagina_ativa: '.npager__num.is-active'},
   atualizacoes: {endereco: '/', codigo: 'hid', numero: 'latestChapter'}, paginas: '.rpage-page',
   busca: {campo: 'form.search__form input', resultado: '.search-pop a.search-pop__item-link', codigo_no_endereco: true, espera: 8}},
  {chave: 'asura', nome: 'Asura Scans', dominio: 'asurascans.com', antigos: ['asuracomic.net'],
   capitulo: '^/(?:comics|series)/(?<slug>[^/]+?)(?:-(?=[a-f]*\\d)[0-9a-f]{8})?/chapter/(?<num>\\d+(?:\\.\\d+)?)',
   serie: '^/(?:comics|series)/(?<slug>[^/]+?)(?:-(?=[a-f]*\\d)[0-9a-f]{8})?/?$', atualizacoes: {endereco: '/'}},
  {chave: 'demonic', nome: 'Demonic Scans', dominio: 'demonicscans.org', antigos: [],
   capitulo: '^/title/(?<slug>[^/]+)/chapter/(?<num>\\d+(?:\\.\\d+)?)',
   capitulo_extra: '^/chaptered\\.php\\?(?=.*\\bmanga=(?<slug>\\d+))(?=.*\\bchapter=(?<num>\\d+(?:\\.\\d+)?))',
   serie: '^/manga/(?<slug>[^/?]+?)/?$', atualizacoes: {endereco: '/lastupdates.php'}},
];
const GENERICO = '(?:chapter|chapitre|capitulo|cap[ií]tulo|episode|ch)[-_/ ]?(?<num>\\d+(?:\\.\\d+)?)';

// uma coisa de cada vez, para a fila de capítulos guardados não se perder
let corrente = Promise.resolve();
const emOrdem = fn => (corrente = corrente.then(fn, fn));

async function pegarSites() {
  try {
    const r = await fetch(ESTANTE + '/api/leitura/sites?v=' + VERSAO + '&nav=' + NAVEGADOR, {cache: 'no-store'});
    if (r.ok) {
      const j = await r.json();
      await chrome.storage.local.set({sites: j.sites, generico: j.generico, bases: j.bases || {}, estanteVista: Date.now()});
      return j.sites;
    }
  } catch (e) { /* Estante fechada: usa o que já sabe */ }
  const v = await chrome.storage.local.get(['sites']);
  if (!v.sites) await chrome.storage.local.set({sites: PADRAO, generico: GENERICO});
  return v.sites || PADRAO;
}

const padroes = s => [s.dominio, ...(s.antigos || [])].filter(Boolean).flatMap(d => [`*://${d}/*`, `*://*.${d}/*`]);

async function registrarScripts() {
  const sites = await pegarSites();
  const origens = [...new Set(sites.flatMap(padroes))];
  // endereços antigos são usados só se já tiverem autorização; o aviso de autorizar é só para o endereço atual
  const atuais = new Set(sites.flatMap(s => s.dominio ? [`*://${s.dominio}/*`] : []));
  const permitidas = [];
  for (const o of origens) {
    try { if (await chrome.permissions.contains({origins: [o]})) permitidas.push(o); } catch (e) {}
  }
  try { await chrome.scripting.unregisterContentScripts({ids: ['estante']}); } catch (e) {}
  if (permitidas.length) {
    await chrome.scripting.registerContentScripts([{
      id: 'estante', js: ['conteudo.js', 'modo_leitura.js'], matches: permitidas, runAt: 'document_idle', persistAcrossSessions: true,
    }]);
  }
  const faltando = origens.filter(o => !permitidas.includes(o) && atuais.has(o));
  await chrome.storage.local.set({faltando});
  await chrome.action.setBadgeText({text: faltando.length ? '!' : ''});
  if (faltando.length) await chrome.action.setBadgeBackgroundColor({color: '#e5a00d'});
}

function enviar(dados) {
  return emOrdem(async () => {
    let {fila = []} = await chrome.storage.local.get('fila');
    // posição dentro do capítulo: só a mais recente importa
    if (dados.posicao || dados.terminou) fila = fila.filter(x => !(x.url === dados.url && (x.posicao || x.terminou) && !x.lendo));
    fila.push({...dados, quando: Date.now()});
    await chrome.storage.local.set({fila: fila.slice(-500)});
  }).then(esvaziar);
}

function esvaziar() {
  return emOrdem(async () => {
    const {fila = []} = await chrome.storage.local.get('fila');
    if (!fila.length) return {pendentes: 0};
    const resto = [];
    let ultimo = null, conectou = false;
    for (const item of fila) {
      if (conectou === null) { resto.push(item); continue; }
      try {
        const r = await fetch(ESTANTE + '/api/leitura/progresso', {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-Estante-Extensao': '1', 'X-Estante-Navegador': NAVEGADOR, 'X-Estante-Versao': VERSAO},
          body: JSON.stringify(item),
        });
        conectou = true;
        const j = await r.json().catch(() => ({}));
        if (r.status >= 500) resto.push(item);
        else if (r.ok && j.capitulo) ultimo = {...j, quando: item.quando};
      } catch (e) {
        resto.push(item);  // Estante fechada: guarda e manda quando ela abrir
        conectou = null;
      }
    }
    const extra = {fila: resto};
    if (ultimo) extra.ultimo = ultimo;
    await chrome.storage.local.set(extra);
    return {pendentes: resto.length, ultimo};
  });
}

// ---------------------------------------------------------------- a sua lista num site (Comix: Followed Titles)
// Cada página da lista vai para a Estante, que liga as séries ao endereço delas no site. Com a Estante fechada,
// as páginas ficam guardadas e vão quando ela abrir.
async function postarLista(dados) {
  const r = await fetch(ESTANTE + '/api/leitura/lista-site', {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Estante-Extensao': '1'}, body: JSON.stringify(dados),
  });
  if (!r.ok) throw new Error('Estante respondeu ' + r.status);
  return r.json();
}
function enviarLista(dados) {
  return emOrdem(async () => {
    try { return await postarLista(dados); } catch (e) { /* Estante fechada: guarda */ }
    const {listas = []} = await chrome.storage.local.get('listas');
    listas.push(dados);
    await chrome.storage.local.set({listas: listas.slice(-80)});
    return {guardada: true};
  });
}
function esvaziarListas() {
  return emOrdem(async () => {
    const {listas = []} = await chrome.storage.local.get('listas');
    if (!listas.length) return;
    const resto = [];
    for (let i = 0; i < listas.length; i++) {
      try { await postarLista(listas[i]); } catch (e) { resto.push(...listas.slice(i)); break; }
    }
    await chrome.storage.local.set({listas: resto});
  });
}

// ---------------------------------------------------------------- como o Mihon: olha os sites de tempos em tempos
// A cada 3 horas, pega na Estante a lista de séries e olha devagar (5 por minuto, com pausas) a página de cada uma
// nos sites onde você lê, para saber em que site cada capítulo novo saiu primeiro. Usa o seu próprio navegador,
// então funciona mesmo com a proteção dos sites. Se um site pedir verificação, ele é pulado até a próxima volta.
const INTERVALO_VERIF = 12 * 3600e3;  // a volta completa ficou mais espaçada: as novidades vêm das páginas de atualizações
let verificando = false;

const rxi = s => { try { return new RegExp(s, 'i'); } catch (e) { return null; } };
function entenderPath(site, path) {
  let m;
  for (const regra of [site.capitulo, site.capitulo_extra]) {
    const c = regra && rxi(regra);
    if (c && (m = path.match(c))) return {tipo: 'capitulo', slug: m.groups.slug, num: parseFloat(m.groups.num)};
  }
  const s = site.serie && rxi(site.serie);
  if (s && (m = path.match(s))) return {tipo: 'serie', slug: m.groups.slug};
  return null;
}
function capitulosDoHtml(html, base, site, slug) {
  const host = new URL(base).hostname, achados = [];
  const re = /(?:href\s*=\s*|"[A-Za-z]*[Uu]rl"\s*:\s*)["']([^"'<>\s]+)["']/g;
  let m;
  while ((m = re.exec(html))) {
    let u;
    try { u = new URL(m[1].replace(/&amp;/g, '&').replace(/\\\//g, '/'), base); } catch (e) { continue; }
    if (u.hostname !== host) continue;
    const i = entenderPath(site, u.pathname + u.search);
    if (i && i.tipo === 'capitulo' && isFinite(i.num)) achados.push({i, url: u.href});
  }
  let mesmos = achados.filter(x => x.i.slug === slug);
  if (!mesmos.length) {  // o site usa outro código para a série nos links de capítulo: vale o que mais aparece
    const conta = {};
    achados.forEach(x => { conta[x.i.slug] = (conta[x.i.slug] || 0) + 1; });
    const maior = Object.keys(conta).sort((a, b) => conta[b] - conta[a])[0];
    mesmos = maior && conta[maior] >= 3 ? achados.filter(x => x.i.slug === maior) : [];
  }
  const unicos = {};
  mesmos.forEach(x => { unicos[x.i.num] = x.url; });
  return Object.entries(unicos).map(([n, url]) => ({n: parseFloat(n), url}));
}
async function verificarSites() {
  if (verificando) return;
  verificando = true;
  try {
    const agora = Date.now();
    let {verif = null, ultimaVerif = 0, sites = []} = await chrome.storage.local.get(['verif', 'ultimaVerif', 'sites']);
    if (!verif || !verif.lista.length) {
      if (agora - ultimaVerif < INTERVALO_VERIF) return;
      try {
        const r = await fetch(ESTANTE + '/api/leitura/para-verificar', {cache: 'no-store'});
        if (!r.ok) return;
        verif = {lista: await r.json(), bloqueados: [], total: 0};
        verif.total = verif.lista.length;
      } catch (e) { return; }  // Estante fechada: tenta no próximo minuto
      await chrome.storage.local.set({ultimaVerif: agora});
    }
    const regras = Object.fromEntries(sites.map(s => [s.chave, s]));
    for (let k = 0; k < 5 && verif.lista.length; k++) {
      const it = verif.lista.shift();
      const site = regras[it.site];
      let host;
      try { host = new URL(it.url).hostname; } catch (e) { continue; }
      if (!site || verif.bloqueados.includes(host)) continue;
      if (!(await chrome.permissions.contains({origins: [`*://${host}/*`]}).catch(() => false))) continue;
      try {
        const r = await fetch(it.url, {credentials: 'include'});
        const html = r.ok ? await r.text() : '';
        if (!r.ok || (html.length < 60000 && /challenge-platform|cf-chl|Just a moment/i.test(html))) { verif.bloqueados.push(host); continue; }
        const caps = capitulosDoHtml(html, r.url, site, it.slug);
        if (caps.length) await enviar({url: r.url, capitulos: caps, verificacao: true});
      } catch (e) { /* site fora do ar: segue */ }
      await new Promise(res => setTimeout(res, 1500 + Math.random() * 3500));
    }
    await chrome.storage.local.set({verif});
  } finally {
    verificando = false;
  }
}

// ---------------------------------------------------------------- capítulos novos perto da hora em que saem
// A cada 15 minutos, olha só a página de últimas atualizações de cada site (uma página por site, como uma pessoa
// faria) e compara com a lista das suas séries, guardada aqui para funcionar mesmo com a Estante fechada.
// Capítulo novo vai para a fila da Estante (entregue quando ela abrir) e, se você está lendo a série, vira um aviso.
const INTERVALO_ATUALIZACOES = 15 * 60e3;
let olhandoAtualizacoes = false;

async function pegarMinhas() {
  try {
    const r = await fetch(ESTANTE + '/api/leitura/minhas', {cache: 'no-store'});
    if (r.ok) await chrome.storage.local.set({minhas: await r.json(), minhasEm: Date.now()});
  } catch (e) { /* Estante fechada: segue com a lista guardada */ }
}

// itens de uma página de atualizações: {slug, bloco, codigo, n, url}
function itensDaPagina(html, base, site) {
  const at = site.atualizacoes || {};
  const itens = [];
  if (at.codigo && at.numero) {  // dados das séries embutidos na página (Comix): código da série e último capítulo
    const re = new RegExp(`"${at.codigo}"\\s*:\\s*"([a-z0-9]+)"(?:(?!"${at.codigo}")[\\s\\S]){0,4000}?"${at.numero}"\\s*:\\s*([\\d.]+)`, 'g');
    let m;
    while ((m = re.exec(html))) itens.push({codigo: m[1], n: parseFloat(m[2])});
    return itens;
  }
  // links da página, na ordem: o link de uma série abre um bloco, e os capítulos logo depois são dela
  const host = new URL(base).hostname, re = /href\s*=\s*["']([^"'<>\s]+)["']/g;
  let m, bloco = '';
  while ((m = re.exec(html))) {
    let u;
    try { u = new URL(m[1].replace(/&amp;/g, '&'), base); } catch (e) { continue; }
    if (u.hostname !== host) continue;
    const i = entenderPath(site, u.pathname + u.search);
    if (i && i.tipo === 'serie') bloco = i.slug;
    else if (i && i.tipo === 'capitulo' && isFinite(i.num)) itens.push({slug: i.slug, bloco, n: i.num, url: u.href});
  }
  return itens;
}

function serieDoItem(minhas, chave, it) {
  return minhas.find(s => {
    const e = (s.sites || {})[chave];
    if (!e || !e.slug) return false;
    return it.codigo ? e.slug.startsWith(it.codigo + '-') : e.slug === it.slug || e.slug === it.bloco;
  });
}

async function avisar(novos) {
  const {avisos = true} = await chrome.storage.local.get('avisos');
  if (!avisos || !novos.length || !chrome.notifications) return;
  if (novos.length > 3) {  // vários de uma vez: um aviso só
    chrome.notifications.create('estante-varios-' + Date.now(), {type: 'basic', iconUrl: 'icone128.png', title: novos.length + ' capítulos novos',
      message: novos.slice(0, 6).map(x => `${x.nome} ${x.n} (${x.siteNome})`).join(' · ')});
    return;
  }
  for (const x of novos) {
    const id = 'estante|' + (x.url || '') + '|' + Date.now() + Math.random();
    chrome.notifications.create(id, {type: 'basic', iconUrl: 'icone128.png', title: 'Capítulo novo: ' + x.nome,
      message: `Saiu o capítulo ${x.n} no ${x.siteNome}.`});
  }
  const {avisados = []} = await chrome.storage.local.get('avisados');
  await chrome.storage.local.set({avisados: [...avisados, ...novos.map(x => ({nome: x.nome, n: x.n, site: x.siteNome, quando: Date.now()}))].slice(-30)});
}

async function verificarAtualizacoes(forcar) {
  if (olhandoAtualizacoes) return;
  olhandoAtualizacoes = true;
  try {
    const agora = Date.now();
    let {ultimasAtualizacoes = 0, sites = [], minhas = [], conhecido = {}, abrirSeries = [], bases = {}} =
      await chrome.storage.local.get(['ultimasAtualizacoes', 'sites', 'minhas', 'conhecido', 'abrirSeries', 'bases']);
    if (!forcar && agora - ultimasAtualizacoes < INTERVALO_ATUALIZACOES) return;
    await chrome.storage.local.set({ultimasAtualizacoes: agora});
    const novos = [];
    for (const site of sites) {
      if (!site.atualizacoes || !site.dominio) continue;
      const origem = `*://${site.dominio}/*`;
      if (!(await chrome.permissions.contains({origins: [origem]}).catch(() => false))) continue;
      let html = '', base = '';
      try {
        const raiz = bases[site.chave] || `https://${site.dominio}/`;
        const r = await fetch(new URL(site.atualizacoes.endereco || '/', raiz).href, {credentials: 'include'});
        html = r.ok ? await r.text() : '';
        base = r.url;
      } catch (e) { continue; }  // site fora do ar: tenta na próxima volta
      if (!html || (html.length < 60000 && /challenge-platform|cf-chl|Just a moment|Verify you're human/i.test(html))) continue;  // verificação de robô: pula
      const porSerie = {};
      for (const it of itensDaPagina(html, base, site)) {
        const s = serieDoItem(minhas, site.chave, it);
        if (!s) continue;
        const p = porSerie[s.id] || (porSerie[s.id] = {s, n: 0, caps: {}});
        p.n = Math.max(p.n, it.n);
        if (it.url) p.caps[it.n] = it.url;
      }
      for (const {s, n, caps} of Object.values(porSerie)) {
        const antes = Math.max(conhecido[s.id] || 0, s.ultimo || 0);
        if (!(n > antes)) continue;
        conhecido[s.id] = n;
        const pagina = s.sites[site.chave].url;
        if (Object.keys(caps).length) {
          await enviar({url: pagina, capitulos: Object.entries(caps).map(([k, url]) => ({n: parseFloat(k), url})), verificacao: true, novo: true});
        } else {  // a página não traz o link do capítulo (Comix): abre a página da série para pegar
          abrirSeries.push({id: s.id, site: site.chave, slug: s.sites[site.chave].slug, url: pagina, tentativas: 0});
        }
        if (s.lendo && antes > 0) novos.push({nome: s.nome, n, siteNome: site.nome, url: caps[n] || pagina});
      }
    }
    await chrome.storage.local.set({conhecido, abrirSeries});
    await avisar(novos);
    await abrirPaginasDeSerie();
  } finally {
    olhandoAtualizacoes = false;
  }
}

async function abrirPaginasDeSerie() {
  let {abrirSeries = [], sites = []} = await chrome.storage.local.get(['abrirSeries', 'sites']);
  const regras = Object.fromEntries(sites.map(s => [s.chave, s]));
  const resto = [];
  for (let k = 0; k < abrirSeries.length; k++) {
    const it = abrirSeries[k];
    if (k >= 8) { resto.push(it); continue; }  // devagar: o resto fica para o próximo minuto
    try {
      const r = await fetch(it.url, {credentials: 'include'});
      const html = r.ok ? await r.text() : '';
      const caps = html ? capitulosDoHtml(html, r.url, regras[it.site] || {}, it.slug) : [];
      if (caps.length) await enviar({url: r.url, capitulos: caps, verificacao: true, novo: true});
      else if (++it.tentativas < 3) resto.push(it);
    } catch (e) {
      if (++it.tentativas < 3) resto.push(it);
    }
    await new Promise(res => setTimeout(res, 1500 + Math.random() * 2500));
  }
  await chrome.storage.local.set({abrirSeries: resto});
}

chrome.notifications && chrome.notifications.onClicked.addListener(id => {
  const url = id.startsWith('estante|') ? id.split('|')[1] : '';
  if (url) chrome.tabs.create({url});
  chrome.notifications.clear(id);
});

chrome.runtime.onInstalled.addListener(() => { registrarScripts().then(pegarMinhas); chrome.alarms.create('estante', {periodInMinutes: 1}); });
chrome.runtime.onStartup.addListener(() => { registrarScripts().then(pegarMinhas); chrome.alarms.create('estante', {periodInMinutes: 1}); });
let voltas = 0;
chrome.alarms.onAlarm.addListener(a => {
  if (a.name !== 'estante') return;
  esvaziar().then(esvaziarListas).then(() => verificarAtualizacoes()).then(abrirPaginasDeSerie).then(verificarSites);
  ++voltas;
  if (voltas % 30 === 0) registrarScripts();  // pega mudanças de endereço feitas nas Configurações
  else if (voltas % 5 === 0) pegarSites();     // e regras novas, se a extensão foi recarregada com a Estante fechada
  if (voltas % 5 === 1) pegarMinhas();          // a lista das suas séries (guardada para quando a Estante estiver fechada)
});
chrome.permissions.onAdded.addListener(() => registrarScripts());
chrome.permissions.onRemoved.addListener(() => registrarScripts());

chrome.runtime.onMessage.addListener((msg, sender, responder) => {
  if (msg && msg.tipo === 'ping') {  // você está lendo dentro da janela da Estante: ela não deve se fechar
    fetch(ESTANTE + '/api/ping', {method: 'POST'}).catch(() => {}); return false;
  }
  if (msg && msg.tipo === 'posicao') {  // onde você parou neste capítulo
    fetch(ESTANTE + '/api/leitura/posicao?url=' + encodeURIComponent(msg.url), {cache: 'no-store'})
      .then(r => r.json()).then(responder, () => responder({}));
    return true;
  }
  if (msg && msg.tipo === 'pagina') { enviar(msg.dados).then(responder, () => responder({})); return true; }
  if (msg && msg.tipo === 'lista') { enviarLista(msg.dados).then(responder, () => responder({})); return true; }
  // ligar as séries "Sem site": a lista do que procurar e os resultados de cada busca (só com a Estante aberta)
  if (msg && msg.tipo === 'para-buscar') {
    fetch(ESTANTE + '/api/leitura/para-buscar?site=' + encodeURIComponent(msg.site), {cache: 'no-store', headers: {'X-Estante-Extensao': '1'}})
      .then(r => r.json()).then(responder, () => responder({erro: true}));
    return true;
  }
  if (msg && msg.tipo === 'busca') {
    fetch(ESTANTE + '/api/leitura/busca-site', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Estante-Extensao': '1'},
                                               body: JSON.stringify(msg.dados)})
      .then(r => r.status === 404 ? {ligada: false, sumiu: true} : r.json())  // a série foi apagada: segue para a próxima
      .then(responder, () => responder({erro: true}));
    return true;
  }
  if (msg && msg.tipo === 'verificar-agora') {
    chrome.storage.local.set({ultimaVerif: 0, verif: null}).then(pegarMinhas).then(() => verificarAtualizacoes(true)).then(verificarSites)
      .then(responder, () => responder({}));
    return true;
  }
  if (msg && msg.tipo === 'atualizar') { registrarScripts().then(esvaziar).then(responder, () => responder({})); return true; }
  return false;
});

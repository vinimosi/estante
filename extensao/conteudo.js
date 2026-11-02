// Roda só nas páginas dos sites de leitura da lista. Só lê a página: série, número do capítulo,
// link, capa e os links de capítulos que já estão na tela. Não mexe em nada e não baixa nada.
(() => {
  if (window.__estanteLeitura) return;
  window.__estanteLeitura = true;

  let sites = [], generico = '';
  const vistos = {};  // url -> {desde, enviado, qtd}

  const rx = s => { try { return new RegExp(s, 'i'); } catch (e) { return null; } };
  const numero = v => { const n = parseFloat(String(v).replace(',', '.')); return isFinite(n) ? n : null; };

  function siteAtual() {
    const h = location.hostname.replace(/^www\./, '');
    return sites.find(s => [s.dominio, ...(s.antigos || [])].some(d => d && (h === d || h.endsWith('.' + d))));
  }

  function slugGenerico(path) {
    const partes = path.split('/').filter(Boolean);
    const palavra = /(?:chapter|chapitre|capitulo|cap[ií]tulo|episode|ch)(?=[-_/ ]?\d)/i;
    for (let i = 0; i < partes.length; i++) {
      const m = partes[i].match(palavra);
      const sozinha = /^(?:chapter|chapitre|capitulo|cap[ií]tulo|episode|ch)$/i.test(partes[i]) && i + 1 < partes.length;
      if (m || sozinha) {
        const antes = m ? partes[i].slice(0, m.index).replace(/^[-_ ]+|[-_ ]+$/g, '') : '';
        return antes || (i > 0 ? partes[i - 1] : '');
      }
    }
    return partes[0] || '';
  }

  // mesmas regras da Estante: descobre se a página é de capítulo ou de série
  // path inclui o "?..." do link, porque alguns sites põem o capítulo ali
  function entender(site, path) {
    let m;
    for (const regra of [site.capitulo, site.capitulo_extra]) {
      const c = regra && rx(regra);
      if (c && (m = path.match(c))) return {tipo: 'capitulo', slug: m.groups.slug, num: numero(m.groups.num)};
    }
    const s = site.serie && rx(site.serie);
    if (s && (m = path.match(s))) return {tipo: 'serie', slug: m.groups.slug};
    const g = !site.capitulo && rx(generico);
    if (g && (m = path.match(g))) return {tipo: 'capitulo', slug: slugGenerico(path), num: numero(m.groups.num)};
    return null;
  }

  function linksDoSite(site) {
    const out = [];
    for (const a of document.querySelectorAll('a[href]')) {
      let u;
      try { u = new URL(a.href, location.href); } catch (e) { continue; }
      if (u.hostname !== location.hostname) continue;
      const i = entender(site, u.pathname + u.search);
      if (i) out.push({a, u, i});
    }
    return out;
  }
  // links de capítulo desta série. Alguns sites usam outro código para a série nos links de capítulo
  // (o Demonic Scans usa um número); aí vale o código que mais aparece na página.
  function capitulosDaSerie(todos, slug) {
    const caps = todos.filter(x => x.i.tipo === 'capitulo' && x.i.num !== null);
    const mesmos = caps.filter(x => x.i.slug === slug);
    if (mesmos.length) return mesmos;
    const conta = {};
    caps.forEach(x => { conta[x.i.slug] = (conta[x.i.slug] || 0) + 1; });
    const maior = Object.keys(conta).sort((a, b) => conta[b] - conta[a])[0];
    return maior && conta[maior] >= 3 ? caps.filter(x => x.i.slug === maior) : [];
  }

  const meta = p => (document.querySelector(`meta[property="${p}"], meta[name="${p}"]`) || {}).content || '';
  const ruim = /^(home|back|voltar|início|inicio|all chapters|chapters|chapter list|info|series|comics|manga|read|ler)$/i;

  function titulo(site, info, links) {
    if (info.tipo === 'serie') {
      const h1 = document.querySelector('h1');
      if (h1 && h1.textContent.trim().length > 1) return h1.textContent.trim();
    }
    // o link "voltar para a série" costuma ter o nome dela
    for (const {a, i} of links) {
      const t = (a.textContent || '').replace(/\s+/g, ' ').trim();
      if (i.tipo === 'serie' && t.length > 1 && t.length < 160 && !ruim.test(t) && !/^\d/.test(t)) return t;
    }
    return meta('og:title') || document.title || '';
  }

  function olhar() {
    const site = siteAtual();
    if (!site) return;
    const info = entender(site, location.pathname + location.search);
    if (!info) return;
    const agora = Date.now();
    const v = vistos[location.href] || (vistos[location.href] = {desde: agora, enviado: 0, qtd: -1});
    if (agora - v.desde < 2000) return;  // espera a página terminar de montar
    const todos = linksDoSite(site);
    const links = todos.filter(x => x.i.slug === info.slug);
    const caps = capitulosDaSerie(todos, info.slug);
    let dados = null;
    if (info.tipo === 'capitulo' && !v.enviado) {
      const rel = document.querySelector('a[rel="next"], link[rel="next"]');
      let maiores = caps.filter(x => x.i.num > info.num).sort((a, b) => a.i.num - b.i.num);
      if (!maiores.length) {  // botão "Próximo" com outro formato de link
        maiores = todos.filter(x => x.i.tipo === 'capitulo' && x.i.num > info.num && /next|pr[óo]x|seguinte/i.test(x.a.textContent || ''));
      }
      let proximo = maiores.length ? maiores[0].u.href : '';
      if (rel && rel.href) { const u = new URL(rel.href, location.href); const i = entender(site, u.pathname + u.search); if (i && i.num > info.num) proximo = rel.href; }
      dados = {url: location.href, titulo: titulo(site, info, links), capitulo: info.num, capa: meta('og:image'), proximo, lendo: true};
    } else if (info.tipo === 'serie' && caps.length !== v.qtd && agora - v.enviado > 4000 && (v.enviado === 0 || caps.length > v.qtd)) {
      const unicos = {};
      caps.forEach(x => { unicos[x.i.num] = x.u.href; });
      dados = {url: location.href, titulo: titulo(site, info, links), capa: meta('og:image'),
               capitulos: Object.entries(unicos).map(([n, url]) => ({n: numero(n), url}))};
      v.qtd = caps.length;
    }
    if (!dados) return;
    v.enviado = agora;
    try { chrome.runtime.sendMessage({tipo: 'pagina', dados}); } catch (e) { /* a extensão foi atualizada: recarregue a página */ }
  }

  // usado pelo modo leitura (modo_leitura.js): onde estou, capítulo anterior e próximo
  window.__estanteInfo = () => {
    const site = siteAtual();
    if (!site) return null;
    const info = entender(site, location.pathname + location.search);
    if (!info || info.tipo !== 'capitulo') return null;
    const todos = linksDoSite(site);
    const caps = capitulosDaSerie(todos, info.slug);
    const perto = (sinal, rx) => {
      let l = caps.filter(x => sinal * (x.i.num - info.num) > 0).sort((a, b) => sinal * (a.i.num - b.i.num));
      if (!l.length) l = todos.filter(x => x.i.tipo === 'capitulo' && sinal * (x.i.num - info.num) > 0 && rx.test(x.a.textContent || ''))
        .sort((a, b) => sinal * (a.i.num - b.i.num));
      return l.length ? {num: l[0].i.num, url: l[0].u.href} : null;
    };
    const links = todos.filter(x => x.i.slug === info.slug);
    return {site: site.nome, serie: titulo(site, info, links).replace(/\s*(?:[-|–—:·•]\s*)?\b(?:chapter|ch\.|cap[ií]tulo)\s*\d.*$/i, '').replace(/(?<=[a-z])Chapter\s*\d.*$/, ''),
            num: info.num, proximo: perto(1, /next|pr[óo]x|seguinte/i), anterior: perto(-1, /prev|anterior/i), paginas: site.paginas || ''};
  };

  // Textos curtos da tela que parecem um contador de páginas ("3 / 25", "Page 3 of 25"), com o lugar de cada um.
  // Servem para ensinar a Estante a ler a página onde você parou em leitores de uma página por vez (como o do Comix).
  function caminhoCss(el) {
    const partes = [];
    for (let e = el; e && e.nodeType === 1 && partes.length < 5; e = e.parentElement) {
      let p = e.tagName.toLowerCase();
      if (e.id) { partes.unshift(p + '#' + e.id); break; }
      const cls = [...e.classList].filter(c => !/^\d|[:[\]]/.test(c)).slice(0, 2);
      if (cls.length) p += '.' + cls.join('.');
      partes.unshift(p);
    }
    return partes.join(' > ');
  }
  function contadoresDePagina() {
    const rx = /^\s*(?:p[aá]g(?:ina)?\.?|page)?\s*(\d{1,4})\s*(?:\/|of|de)\s*(\d{1,4})\s*$/i;
    const achados = [];
    for (const el of document.querySelectorAll('body *')) {
      if (el.children.length > 3 || achados.length >= 6) continue;
      const t = (el.textContent || '').trim();
      if (t.length > 20 || !rx.test(t)) continue;
      if ([...el.children].some(f => (f.textContent || '').trim() === t)) continue;  // vale o elemento de dentro
      const r = el.getBoundingClientRect();
      achados.push(`${t.replace(/\s+/g, ' ')}  [${caminhoCss(el)}]${r.width && r.height ? '' : ' (escondido)'}`);
    }
    for (const s of document.querySelectorAll('select')) {
      const o = s.options[s.selectedIndex];
      if (o && /\d/.test(o.textContent) && s.options.length > 2 && achados.length < 8) achados.push(`lista: ${o.textContent.trim()} de ${s.options.length}  [${caminhoCss(s)}]`);
    }
    return achados;
  }

  // numa página que não é de capítulo nem de série (a busca do site, por exemplo): os links de séries que estão
  // nela e as caixas de busca, para dar para escrever as regras de um jeito novo de usar o site
  function seriesNaPagina(site) {
    const vistos = new Set(), out = [];
    for (const x of linksDoSite(site)) {
      if (x.i.tipo !== 'serie' || vistos.has(x.i.slug) || out.length >= 12) continue;
      vistos.add(x.i.slug);
      const a = x.a, img = a.querySelector('img');
      const txt = (a.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 90);
      out.push(`${x.u.pathname} · texto: "${txt}"` + (a.getAttribute('title') ? ` · title: "${a.getAttribute('title')}"` : '') +
               (img && img.alt ? ` · imagem: "${img.alt.slice(0, 80)}"` : '') + `  [${caminhoCss(a)}]`);
    }
    return out;
  }
  function caixasDeBusca() {
    return [...document.querySelectorAll('input[type=search], input[type=text], input:not([type])')].slice(0, 4).map(i => {
      const f = i.form;
      return `campo name="${i.name || ''}" placeholder="${(i.placeholder || '').slice(0, 40)}"` +
             (f ? ` · formulário ${(f.method || 'get').toUpperCase()} ${f.getAttribute('action') || '(mesma página)'}` : '') + `  [${caminhoCss(i)}]`;
    });
  }

  // usado pela janelinha da extensão: o que foi reconhecido nesta página e, quando nada foi, por quê
  function diagnostico() {
    const site = siteAtual();
    const path = location.pathname + location.search;
    if (!site) return {reconheceu: false, motivo: 'fora_da_lista', host: location.hostname};
    const info = entender(site, path);
    const base = {site: site.nome, conhecido: !!site.capitulo, endereco: path};
    if (!info) return {...base, reconheceu: false, motivo: 'endereco', series: seriesNaPagina(site), busca: caixasDeBusca()};
    const todos = linksDoSite(site);
    const links = todos.filter(x => x.i.slug === info.slug);
    const caps = capitulosDaSerie(todos, info.slug);
    const v = vistos[location.href];
    if (info.tipo === 'serie') {
      return {...base, reconheceu: true, tipo: 'serie', serie: titulo(site, info, links), capitulos: new Set(caps.map(x => x.i.num)).size};
    }
    const i = window.__estanteInfo ? window.__estanteInfo() : null;
    return {...base, reconheceu: true, tipo: 'capitulo', serie: (i && i.serie) || titulo(site, info, links), capitulo: info.num,
            proximo: i && i.proximo ? i.proximo.num : null, anterior: i && i.anterior ? i.anterior.num : null,
            enviado: !!(v && v.enviado), paginas: contadoresDePagina(), imagens: document.querySelectorAll('img').length,
            caixas: site.paginas ? (() => { try { return document.querySelectorAll(site.paginas).length; } catch (e) { return 0; } })() : null};
  }
  chrome.runtime.onMessage.addListener((msg, sender, responder) => {
    if (msg && msg.tipo === 'diagnostico') { responder(diagnostico()); return false; }
    return false;
  });

  // ---- a sua lista no site (no Comix, Perfil > Followed Titles). Lê os cartões que estão na tela: nome, endereço
  // da série e capítulos (lido / último). Quando a página foi aberta pela Estante (#estante-ligar), passa as páginas
  // sozinha, devagar, como uma pessoa faria, até a última. As regras ficam na Estante (SITES_PADRAO, "lista").
  const VARRER = 'estanteVarrer';
  const lista = {assinatura: '', proximaEm: 0, cliques: 0, paginas: 0, ligadas: 0, ja: 0, semPar: 0, marcadaAntes: ''};
  const ESPERAS_LISTA = [10000, 20000, 40000, 60000];  // paciência com o site, depois de cada clique sem resposta

  function avisoLista(texto, fim) {
    let el = document.getElementById('estante-lista');
    if (!el) {
      el = document.createElement('div');
      el.id = 'estante-lista';
      el.style.cssText = 'position:fixed;left:50%;top:12px;transform:translateX(-50%);z-index:2147483647;background:#16120a;color:#fff;' +
        'border:1px solid #e5a00d;border-radius:10px;padding:10px 16px;font:600 14px system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.5);max-width:90vw';
      document.documentElement.appendChild(el);
    }
    el.textContent = texto;
    if (fim) setTimeout(() => el.remove(), 20000);
  }

  function olharLista() {
    const site = siteAtual();
    const r = site && site.lista;
    if (!r || !r.cartao) return;
    const caminho = rx(r.caminho);
    if ((caminho && !caminho.test(location.pathname)) || (r.parametro && !location.search.includes(r.parametro))) return;
    const cartoes = [...document.querySelectorAll(r.cartao)].map(a => {
      let u;
      try { u = new URL(a.getAttribute('href'), location.href); } catch (e) { return null; }
      const i = entender(site, u.pathname);
      const t = ((r.titulo && a.querySelector(r.titulo)) || {}).textContent || a.getAttribute('title') || '';
      const ch = (((r.capitulos && a.querySelector(r.capitulos)) || {}).textContent || '').match(/([\d.,]+|[—-])\s*\/\s*([\d.,]+)/);
      return i && i.tipo === 'serie' && t.trim() ? {slug: i.slug, titulo: t.trim(), lido: ch ? numero(ch[1]) : null, ultimo: ch ? numero(ch[2]) : null} : null;
    }).filter(Boolean);
    let varrer = false;
    try {
      if (/estante-ligar/.test(location.hash)) sessionStorage.setItem(VARRER, '1');
      varrer = sessionStorage.getItem(VARRER) === '1';
    } catch (e) {}
    if (cartoes.length) {
      const assinatura = cartoes.map(c => c.slug).join('|');
      if (assinatura !== lista.assinatura) {  // página nova da lista: manda para a Estante
        lista.assinatura = assinatura;
        lista.cliques = 0;
        lista.paginas++;
        lista.proximaEm = Date.now() + 6000 + Math.random() * 4000;  // devagar, como uma pessoa lendo a lista
        try {
          chrome.runtime.sendMessage({tipo: 'lista', dados: {site: site.chave, cartoes}}, resp => {
            if (!resp || chrome.runtime.lastError) return;
            lista.ligadas += resp.ligadas || 0; lista.ja += resp.ja || 0; lista.semPar += resp.sem_par || 0;
            if (varrer) avisoLista(`Estante: lendo a sua lista do ${site.nome}, página ${lista.paginas}… ${lista.ligadas + lista.ja} séries ligadas até agora. Deixe esta aba aberta.`);
          });
        } catch (e) { /* a extensão foi atualizada: recarregue a página */ }
        return;
      }
    }
    if (!varrer || Date.now() < lista.proximaEm) return;
    const prox = r.proxima && document.querySelector(r.proxima);
    if (!prox || prox.disabled || prox.getAttribute('aria-disabled') === 'true') {  // última página: acabou de verdade
      try { sessionStorage.removeItem(VARRER); } catch (e) {}
      avisoLista(lista.paginas
        ? `Estante: pronto! ${lista.ligadas} séries ligadas ao ${site.nome} agora (${lista.ja} já estavam)` +
          (lista.semPar ? `, ${lista.semPar} sem série na Estante (importe o CSV do ${site.nome} para trazê-las)` : '') + '. Pode fechar esta aba.'
        : `Estante: não achei a sua lista nesta página do ${site.nome}.`, true);
      return;
    }
    // A página não mudou depois do clique: o site está demorando. Espera cada vez mais antes de tentar de novo,
    // e não clica outra vez se o site já marcou a página seguinte (senão pularia uma página).
    if (lista.cliques >= ESPERAS_LISTA.length) {
      try { sessionStorage.removeItem(VARRER); } catch (e) {}
      avisoLista(`Estante: o ${site.nome} parou de responder na página ${lista.paginas + 1}. ${lista.ligadas + lista.ja} séries ligadas até aqui. ` +
        `Espere alguns minutos e clique de novo em “Abrir a minha lista no ${site.nome}”, na Estante, para terminar.`, true);
      return;
    }
    const ativa = r.pagina_ativa && document.querySelector(r.pagina_ativa);
    const marcada = ativa ? ativa.textContent.trim() : '';
    lista.proximaEm = Date.now() + ESPERAS_LISTA[lista.cliques];
    if (!lista.cliques || !marcada || marcada === lista.marcadaAntes) {
      lista.marcadaAntes = marcada;
      prox.click();
    }
    lista.cliques++;
  }

  // ---- ligar as séries "Sem site" pela busca do site. Só quando a página foi aberta pela Estante
  // (#estante-buscar): a extensão digita o nome de cada série na caixa de busca, espera a lista de resultados,
  // manda para a Estante (que decide se liga) e espera alguns segundos antes da próxima, como uma pessoa faria.
  // Nada de abrir as páginas dos resultados nem de pedir nada ao site por trás: só a busca que está na tela.
  const BUSCAR = 'estanteBuscar';
  const busca = {fila: null, pedindo: false, i: 0, termo: 0, fase: 'digitar', ate: 0, desde: 0, assinatura: '', igual: 0,
                 ligadas: 0, sem: 0, total: 0};

  function digitar(campo, texto) {
    campo.focus();
    // sites feitos com React só percebem o texto quando ele entra pelo jeito de dentro do navegador
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(campo, texto);
    campo.dispatchEvent(new Event('input', {bubbles: true}));
    campo.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: texto.slice(-1)}));
  }
  function fimBusca(texto) {
    try { sessionStorage.removeItem(BUSCAR); } catch (e) {}
    busca.fila = [];
    avisoLista(texto, true);
  }
  function olharBusca() {
    const site = siteAtual();
    const r = site && site.busca;
    if (!r || !r.campo) return;
    try {
      if (/estante-buscar/.test(location.hash)) { sessionStorage.setItem(BUSCAR, '1'); history.replaceState(null, '', location.pathname + location.search); }
      if (sessionStorage.getItem(BUSCAR) !== '1') return;
    } catch (e) { return; }
    if (!busca.fila) {
      if (busca.pedindo) return;
      busca.pedindo = true;
      chrome.runtime.sendMessage({tipo: 'para-buscar', site: site.chave}, resp => {
        busca.pedindo = false;
        if (chrome.runtime.lastError || !resp || resp.erro || !resp.series) {
          fimBusca(`Estante: não consegui falar com a Estante. Abra a Estante e clique de novo em “Procurar no ${site.nome}”.`);
          return;
        }
        busca.fila = resp.series; busca.total = resp.series.length; busca.ate = Date.now() + 2000;
        if (!busca.total) fimBusca(`Estante: nenhuma série para procurar no ${site.nome} agora. Pode fechar esta aba.`);
      });
      return;
    }
    if (busca.i >= busca.fila.length) return;
    if (Date.now() < busca.ate) return;
    const campo = document.querySelector(r.campo);
    if (!campo) {
      if (!busca.desde) busca.desde = Date.now();
      if (Date.now() - busca.desde > 20000) fimBusca(`Estante: não achei a caixa de busca nesta página do ${site.nome}. O site pode ter mudado; avise.`);
      return;
    }
    const s = busca.fila[busca.i], termo = (s.nomes[busca.termo] || '').replace(/[’‘`´]/g, "'").replace(/[“”]/g, '"');  // aspas comuns, como se digita
    const espera = Math.max(2, Number(r.espera) || 8) * 1000;
    if (busca.fase === 'digitar') {
      digitar(campo, termo);
      busca.fase = 'esperar'; busca.desde = Date.now(); busca.assinatura = ''; busca.igual = 0;
      avisoLista(`Estante: procurando as suas séries no ${site.nome}, ${busca.i + 1} de ${busca.total}… ${busca.ligadas} ligadas até agora. Deixe esta aba aberta.`);
      return;
    }
    // espera a lista de resultados parar de mudar (no mínimo 2 s, no máximo 12 s)
    const links = [...document.querySelectorAll(r.resultado)].map(a => {
      let u;
      try { u = new URL(a.getAttribute('href'), location.href); } catch (e) { return null; }
      const i = entender(site, u.pathname);
      return i && i.tipo === 'serie' ? {slug: i.slug, texto: (a.textContent || '').replace(/\s+/g, ' ').trim()} : null;
    }).filter(Boolean);
    const assinatura = links.map(x => x.slug).join('|');
    busca.igual = assinatura === busca.assinatura ? busca.igual + 1 : 0;
    busca.assinatura = assinatura;
    const passou = Date.now() - busca.desde;
    if (passou < 2000 || (busca.igual < 2 && passou < 12000)) return;
    if (assinatura && assinatura === busca.anterior && passou < 12000) return;  // ainda é a lista da busca anterior
    busca.anterior = assinatura;
    busca.ate = Infinity;  // espera a resposta da Estante
    chrome.runtime.sendMessage({tipo: 'busca', dados: {site: site.chave, id: s.id, termo, resultados: links}}, resp => {
      if (chrome.runtime.lastError || !resp || resp.erro) {
        fimBusca(`Estante: a Estante parou de responder. ${busca.ligadas} séries ligadas até aqui. Clique de novo em “Procurar no ${site.nome}” para continuar.`);
        return;
      }
      if (resp.ligada) { busca.ligadas++; busca.i++; busca.termo = 0; }
      else if (busca.termo + 1 < s.nomes.length) busca.termo++;   // tenta o nome alternativo
      else { busca.sem++; busca.i++; busca.termo = 0; }
      busca.fase = 'digitar';
      busca.ate = Date.now() + espera + Math.random() * espera / 2;
      if (busca.i >= busca.fila.length) {
        digitar(campo, '');
        fimBusca(`Estante: pronto! ${busca.ligadas} séries ligadas ao ${site.nome}. ` +
          (busca.sem ? `${busca.sem} ficaram sem site porque a busca não trouxe um resultado com o mesmo nome; dá para ligar essas à mão, no painel de cada uma. ` : '') +
          'Pode fechar esta aba.');
      }
    });
  }

  chrome.storage.local.get(['sites', 'generico']).then(v => {
    sites = v.sites || [];
    generico = v.generico || '';
    olhar();
    setInterval(() => { olhar(); olharLista(); olharBusca(); }, 1000);  // sites que trocam de capítulo sem recarregar a página
  });
})();

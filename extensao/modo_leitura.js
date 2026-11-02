// Modo leitura da Estante: na página do capítulo, esconde menus e anúncios e põe a barra da Estante por cima.
// As imagens continuam sendo as do próprio site: nada é baixado, trocado ou desembaralhado.
(() => {
  if (window.__estanteModo) return;
  window.__estanteModo = true;

  let opc = {modoLeitura: true, autoProximo: true};
  // aberto de dentro da janela da Estante? (vale para os próximos capítulos nesta mesma aba)
  const ESTANTE = 'http://127.0.0.1:8765/';
  try { if (document.referrer.startsWith(ESTANTE)) sessionStorage.setItem('estanteEmbutido', '1'); } catch (e) {}
  const embutido = (() => { try { return sessionStorage.getItem('estanteEmbutido') === '1'; } catch (e) { return false; } })();
  if (embutido) {  // mantém a Estante aberta enquanto você lê aqui
    const ping = () => { try { chrome.runtime.sendMessage({tipo: 'ping'}); } catch (e) {} };
    ping(); setInterval(ping, 15000);
  }
  let url = '', host = null, raiz = null, limpo = false, contT = null, contN = 0, alvo = null, ultimaRolagem = 0;

  const ESTILO = `
    :host{all:initial}
    .barra{position:fixed;top:0;left:0;right:0;z-index:2147483646;display:flex;align-items:center;gap:8px;padding:7px 12px;
      background:rgba(22,25,32,.94);backdrop-filter:blur(6px);border-bottom:1px solid #2a2f3a;color:#e8e9ec;
      font:13px "Segoe UI",system-ui,sans-serif;transition:transform .2s;box-shadow:0 6px 20px rgba(0,0,0,.35)}
    .barra.some{transform:translateY(-110%)}
    .logo{width:22px;height:22px;border-radius:6px;background:#e5a00d;display:grid;place-items:center;flex:none}
    .tit{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:42vw}
    .cap{color:#9aa0ab;white-space:nowrap}
    .esp{flex:1}
    button{font:inherit;color:#e8e9ec;background:#1d2129;border:1px solid #2a2f3a;border-radius:7px;padding:5px 11px;cursor:pointer;white-space:nowrap}
    button:hover{border-color:#3a404c;background:#232833}
    button.pri{background:#e5a00d;border-color:#e5a00d;color:#16120a;font-weight:600}
    button:disabled{opacity:.45;cursor:default}
    .fim{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:2147483646;background:#161920;border:1px solid #2a2f3a;
      border-radius:14px;padding:12px 16px;display:none;align-items:center;gap:12px;color:#e8e9ec;font:14px "Segoe UI",system-ui,sans-serif;
      box-shadow:0 18px 50px rgba(0,0,0,.6)}
    .fim.show{display:flex}
    .dim{color:#9aa0ab}`;
  const CSS_PAGINA = `
    [data-estante-esconde]{display:none!important}
    html.estante-limpo,html.estante-limpo body{background:#0f1115!important}
    html.estante-limpo body{padding-top:44px!important}
    html.estante-limpo [data-estante-alvo]{margin-left:auto!important;margin-right:auto!important}`;

  function infoAtual() { try { return window.__estanteInfo && window.__estanteInfo(); } catch (e) { return null; } }

  // as páginas do capítulo são as imagens grandes "iguais entre si" (mesma classe e, se der, mesmo servidor);
  // assim, banners e anúncios no meio delas ficam de fora. O leitor é o menor bloco que contém essas páginas.
  let paginas = [];
  function acharLeitor() {
    const grandes = [...document.querySelectorAll('img, canvas')].filter(el => {
      const r = el.getBoundingClientRect();
      return r.width >= 250 && (r.height >= 250 || (el.naturalHeight || 0) >= 400);
    });
    const host = el => { try { return new URL(el.currentSrc || el.src).hostname; } catch (e) { return ''; } };
    const grupo = sig => { const c = {}; grandes.forEach(g => { const k = sig(g); c[k] = (c[k] || 0) + 1; }); const k = Object.keys(c).sort((a, b) => c[b] - c[a])[0]; return {k, n: c[k] || 0}; };
    const comHost = el => el.tagName + '|' + (el.getAttribute('class') || '') + '|' + host(el);
    const semHost = el => el.tagName + '|' + (el.getAttribute('class') || '');
    let g = grupo(comHost), sig = comHost;
    if (g.n < 2 || g.n < grandes.length / 2) { g = grupo(semHost); sig = semHost; }
    paginas = grandes.filter(el => sig(el) === g.k);
    if (paginas.length < 2) return null;
    let lca = paginas[0].parentElement;
    while (lca && !paginas.every(p => lca.contains(p))) lca = lca.parentElement;
    if (!lca || lca === document.body || lca === document.documentElement) return null;
    return lca;
  }

  function limpar() {
    // leitores que já ocupam a tela toda e rolam por dentro (como o do Comix) já são limpos: só a barra aparece
    if (document.documentElement.scrollHeight <= innerHeight * 1.5) return false;
    alvo = acharLeitor();
    if (!alvo) return false;
    let el = alvo;
    while (el && el !== document.body) {
      for (const irmao of el.parentElement.children) {
        if (irmao !== el && !['SCRIPT', 'STYLE', 'LINK'].includes(irmao.tagName) && irmao.id !== 'estante-raiz') irmao.setAttribute('data-estante-esconde', '');
      }
      el = el.parentElement;
    }
    for (const filho of alvo.children) {  // dentro do leitor: o que não é página do capítulo (banners, botões, anúncios)
      if (!['SCRIPT', 'STYLE', 'LINK'].includes(filho.tagName) && !paginas.some(p => filho === p || filho.contains(p))) filho.setAttribute('data-estante-esconde', '');
    }
    alvo.setAttribute('data-estante-alvo', '');
    document.documentElement.classList.add('estante-limpo');
    document.querySelectorAll('iframe').forEach(f => { if (!alvo.contains(f)) f.setAttribute('data-estante-esconde', ''); });
    return true;
  }
  function desfazer() {
    document.querySelectorAll('[data-estante-esconde]').forEach(e => e.removeAttribute('data-estante-esconde'));
    document.querySelectorAll('[data-estante-alvo]').forEach(e => e.removeAttribute('data-estante-alvo'));
    document.documentElement.classList.remove('estante-limpo');
  }

  function montar() {
    if (!document.getElementById('estante-estilo')) {
      const st = document.createElement('style');
      st.id = 'estante-estilo';
      st.textContent = CSS_PAGINA;
      document.documentElement.appendChild(st);
    }
    host = document.createElement('div');
    host.id = 'estante-raiz';
    raiz = host.attachShadow({mode: 'open'});
    raiz.innerHTML = `<style>${ESTILO}</style>
      <div class="barra" id="b"><button id="voltar" title="Voltar para a Estante">← Estante</button><div class="logo"><svg viewBox="0 0 24 24" width="15" height="15" fill="#16120a"><rect x="3" y="4" width="4" height="16" rx="1"/><rect x="9" y="4" width="4" height="16" rx="1"/><rect x="15" y="5" width="4" height="15" rx="1" transform="rotate(12 17 12)"/></svg></div>
        <span class="tit" id="tit"></span><span class="cap" id="cap"></span><span class="esp"></span>
        <button id="ant" title="Capítulo anterior (←)">‹ Anterior</button><button id="prox" class="pri" title="Próximo capítulo (→)">Próximo ›</button>
        <button id="lim" title="Mostrar a página como o site fez"></button><button id="fechar" title="Fechar a janela">✕</button></div>
      <div class="fim" id="fim"><span id="fimTxt"></span><button class="pri" id="ir">Ir agora</button><button id="ficar">Ficar</button></div>`;
    document.documentElement.appendChild(host);
    const $ = id => raiz.getElementById(id);
    $('ant').onclick = () => ir(-1);
    $('prox').onclick = () => ir(1);
    $('lim').onclick = () => { opc.modoLeitura = !opc.modoLeitura; chrome.storage.local.set({modoLeitura: opc.modoLeitura}); aplicarLimpeza(); };
    $('fechar').onclick = () => window.close();
    $('voltar').onclick = () => { try { sessionStorage.removeItem('estanteEmbutido'); } catch (e) {} location.href = ESTANTE; };
    $('voltar').style.display = embutido ? '' : 'none';
    $('fechar').style.display = embutido ? 'none' : '';
    $('ir').onclick = () => ir(1);
    $('ficar').onclick = () => cancelarContagem(true);
  }

  function aplicarLimpeza() {
    desfazer();
    limpo = opc.modoLeitura ? limpar() : false;
    raiz.getElementById('lim').textContent = opc.modoLeitura ? 'Página original' : 'Modo leitura';
  }

  function ir(sinal) {
    const i = infoAtual();
    const alvoCap = i && (sinal > 0 ? i.proximo : i.anterior);
    if (!alvoCap) return;
    if (sinal > 0 && !pos.terminou) {  // passou para o próximo: este conta como lido
      pos.terminou = true;
      try { chrome.runtime.sendMessage({tipo: 'pagina', dados: {url: location.href, capitulo: i.num, terminou: true}}); } catch (e) {}
    }
    location.href = alvoCap.url;
  }

  let ficar = false;
  function cancelarContagem(fica) {
    clearTimeout(contT); contT = null;
    if (fica) ficar = true;
    raiz.getElementById('fim').classList.remove('show');
  }
  function noFim() {
    const i = infoAtual();
    if (!i || !i.proximo || ficar) return;
    const fim = raiz.getElementById('fim');
    if (!opc.autoProximo) {
      raiz.getElementById('fimTxt').innerHTML = `Fim do capítulo. <span class="dim">Próximo: ${i.proximo.num}</span>`;
      fim.classList.add('show');
      return;
    }
    if (contT) return;
    contN = 5;
    const tic = () => {
      if (contN <= 0) { ir(1); return; }
      raiz.getElementById('fimTxt').innerHTML = `Indo para o capítulo ${i.proximo.num} em ${contN}…`;
      fim.classList.add('show');
      contN--;
      contT = setTimeout(tic, 1000);
    };
    tic();
  }

  function atualizar() {
    const i = infoAtual();
    if (!i) {  // página que não é de capítulo: dentro da Estante, a barra fica só com o "voltar"
      if (embutido) {
        if (!host) montar();
        host.style.display = '';
        for (const id of ['ant', 'prox', 'lim', 'cap']) raiz.getElementById(id).style.display = 'none';
        raiz.getElementById('tit').textContent = document.title || '';
      } else if (host) host.style.display = 'none';
      return;
    }
    if (!host) montar();
    host.style.display = '';
    for (const id of ['ant', 'prox', 'lim', 'cap']) raiz.getElementById(id).style.display = '';
    restaurar();
    if (location.href !== url) {  // capítulo novo (inclusive nos sites que trocam sem recarregar)
      url = location.href; ficar = false; cancelarContagem(); mostrarBarra();
      setTimeout(aplicarLimpeza, 1500);
    } else if (opc.modoLeitura && !limpo) {
      aplicarLimpeza();  // as imagens podem demorar a aparecer
    }
    raiz.getElementById('tit').textContent = i.serie || '';
    raiz.getElementById('cap').textContent = 'Capítulo ' + String(i.num).replace('.', ',') + ' · ' + i.site;
    raiz.getElementById('ant').disabled = !i.anterior;
    raiz.getElementById('prox').disabled = !i.proximo;
    raiz.getElementById('prox').textContent = i.proximo ? `Capítulo ${String(i.proximo.num).replace('.', ',')} ›` : 'Próximo ›';
  }

  window.addEventListener('scroll', () => {
    const y = window.scrollY, b = raiz && raiz.getElementById('b');
    if (b) b.classList.toggle('some', y > ultimaRolagem && y > 120);
    ultimaRolagem = y;
    const altura = document.documentElement.scrollHeight;
    if (altura > innerHeight * 2 && y + innerHeight >= altura - 150) noFim();
    else if (contT) cancelarContagem();
  }, {passive: true});
  let someT = null;
  function mostrarBarra() {
    if (!raiz) return;
    raiz.getElementById('b').classList.remove('some');
    clearTimeout(someT);
    someT = setTimeout(() => { if (raiz && !host.matches(':hover')) raiz.getElementById('b').classList.add('some'); }, 3500);
  }
  document.addEventListener('mousemove', e => { if (e.clientY < 50) mostrarBarra(); }, {passive: true});
  document.addEventListener('keydown', e => {
    if (!raiz || e.ctrlKey || e.altKey || e.metaKey || /INPUT|TEXTAREA|SELECT/.test((e.target || {}).tagName || '') || e.target.isContentEditable) return;
    // as setas trocam de capítulo só em leitores de rolagem (nos de página por página, elas viram as páginas do site)
    const rolagem = document.documentElement.scrollHeight > innerHeight * 2;
    if (rolagem && e.key === 'ArrowRight') { e.preventDefault(); ir(1); }
    if (rolagem && e.key === 'ArrowLeft') { e.preventDefault(); ir(-1); }
  });

  // ---------------- onde você parou dentro do capítulo
  // Conta como lido só quando você chega no fim (ou passa para o próximo). Se parar no meio, a Estante guarda
  // a página e, quando você voltar, a página rola sozinha até ela.
  let pos = {url: '', pagina: -1, pct: 0, enviadoEm: 0, terminou: false, enviadoPag: -1};
  // Sites com regra "paginas" (o Comix): as páginas do leitor são as caixas dessa regra, e a página onde você está
  // é a que mais aparece na tela. Vale para leitores que rolam por dentro e para os de uma página por vez.
  function paginasDaRegra() {
    const i = infoAtual();
    if (!i || !i.paginas) return null;
    let ps;
    try { ps = [...document.querySelectorAll(i.paginas)]; } catch (e) { return null; }
    return ps.length >= 2 ? ps : null;
  }
  function areaNaTela(el) {
    const r = el.getBoundingClientRect();
    return Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0)) * Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0));
  }
  function medirPelaRegra(ps) {
    let pagina = -1, maior = 0;
    ps.forEach((p, k) => { const a = areaNaTela(p); if (a > maior) { maior = a; pagina = k; } });
    if (pagina < 0) return null;
    const fimDaUltima = ps[pagina].getBoundingClientRect().bottom <= innerHeight + 60;
    return {pct: (pagina + 1) / ps.length, pagina, total: ps.length, noFim: pagina === ps.length - 1 && fimDaUltima};
  }
  function paginasDoCapitulo() {
    const regra = paginasDaRegra();
    if (regra) return regra;
    try { if (!paginas.length || !paginas[0].isConnected) acharLeitor(); } catch (e) {}
    return paginas.filter(p => p.isConnected);
  }
  function medir() {
    const regra = paginasDaRegra();
    if (regra) return medirPelaRegra(regra);
    const alt = document.documentElement.scrollHeight - innerHeight;
    if (alt < innerHeight) return null;  // leitor que não rola a página (como o do Comix): conta pela troca de capítulo
    const ps = paginasDoCapitulo();
    let pagina = 0;
    const meio = innerHeight / 2;
    ps.forEach((p, k) => { if (p.getBoundingClientRect().top < meio) pagina = k; });
    const ultima = ps.length ? ps[ps.length - 1].getBoundingClientRect() : null;
    const noFim = (ultima && ultima.bottom <= innerHeight + 60) || window.scrollY >= alt - 150;
    return {pct: Math.min(1, window.scrollY / alt), pagina, total: ps.length, noFim};
  }
  function enviarPosicao(forcar) {
    const i = infoAtual();
    const m = medir();
    if (!i || !m) return;
    if (restaurando && restaurando.url === location.href && Date.now() < restaurando.ate) return;  // ainda voltando para onde você parou
    if (location.href !== pos.url) pos = {url: location.href, pagina: -1, pct: 0, enviadoEm: 0, terminou: false, enviadoPag: -1};
    if (m.noFim && !pos.terminou) {
      pos.terminou = true;
      try { chrome.runtime.sendMessage({tipo: 'pagina', dados: {url: location.href, capitulo: i.num, terminou: true}}); } catch (e) {}
      return;
    }
    if (pos.terminou) return;
    const mudou = m.pagina !== pos.enviadoPag;
    if (!mudou || (!forcar && Date.now() - pos.enviadoEm < 8000)) return;
    pos.enviadoEm = Date.now(); pos.enviadoPag = m.pagina;
    try { chrome.runtime.sendMessage({tipo: 'pagina', dados: {url: location.href, capitulo: i.num, posicao: {pct: m.pct, pagina: m.pagina, total: m.total}}}); } catch (e) {}
  }
  setInterval(() => enviarPosicao(false), 3000);
  document.addEventListener('visibilitychange', () => { if (document.hidden) enviarPosicao(true); });
  window.addEventListener('pagehide', () => enviarPosicao(true));

  let restaurado = '', restaurando = null;
  function restaurar() {
    if (restaurado === location.href || !infoAtual()) return;
    restaurado = location.href;
    // até saber onde você parou, não manda "estou no começo" (isso apagaria a posição guardada)
    restaurando = {url: location.href, ate: Date.now() + 15000};
    const pronto = () => { restaurando = null; };
    try {
      chrome.runtime.sendMessage({tipo: 'posicao', url: location.href}, r => {
        if (!r || !r.pagina) return pronto();
        let tentativas = 0;
        const ir = () => {
          const ps = paginasDoCapitulo();
          const alvoPag = ps[Math.min(r.pagina, ps.length - 1)];
          if (alvoPag && ps.length >= Math.min(r.pagina + 1, r.total || 0)) {
            alvoPag.scrollIntoView({block: 'start'});
            // enquanto a página termina de carregar (anúncios somem, imagens crescem), segura no lugar certo;
            // se você mexer na página, para de segurar
            let mexeu = false;
            const parar = () => { mexeu = true; };
            ['wheel', 'keydown', 'mousedown', 'touchstart'].forEach(ev => addEventListener(ev, parar, {once: true, passive: true}));
            const ate = Date.now() + 4000;
            const segurar = () => {
              if (mexeu || Date.now() > ate || !alvoPag.isConnected) return pronto();
              if (Math.abs(alvoPag.getBoundingClientRect().top) > 40) alvoPag.scrollIntoView({block: 'start'});
              setTimeout(segurar, 250);
            };
            setTimeout(segurar, 250);
            const inicio = () => { window.scrollTo(0, 0); ps[0].scrollIntoView({block: 'start'}); };
            setTimeout(() => {  // num leitor de uma página por vez, rolar não troca a página: aí só avisa onde você parou
              const m = medir();
              if (m && m.pagina !== Math.min(r.pagina, ps.length - 1)) {
                aviso(`Você parou na página ${r.pagina + 1}${r.total ? ' de ' + r.total : ''}.`);
                // a página da tela não é a guardada: só manda quando você trocar de página, para não apagar a guardada
                pos = {url: location.href, pagina: -1, pct: 0, enviadoEm: Date.now(), terminou: false, enviadoPag: m.pagina};
                pronto();
              }
              else aviso(`Continuando da página ${r.pagina + 1}${r.total ? ' de ' + r.total : ''}.`, 'Voltar ao início', inicio);
            }, 400);
          } else if (++tentativas < 20) setTimeout(ir, 500);
          else pronto();
        };
        setTimeout(ir, 800);
      });
    } catch (e) { pronto(); }
  }
  function aviso(txt, botao, acao) {
    if (!raiz) return;
    const fim = raiz.getElementById('fim');
    raiz.getElementById('fimTxt').textContent = txt;
    raiz.getElementById('ir').textContent = botao || '';
    raiz.getElementById('ir').style.display = botao ? '' : 'none';
    raiz.getElementById('ir').onclick = () => { acao(); fim.classList.remove('show'); raiz.getElementById('ir').textContent = 'Ir agora'; raiz.getElementById('ir').onclick = () => ir(1); };
    raiz.getElementById('ficar').textContent = 'OK';
    fim.classList.add('show');
    setTimeout(() => { fim.classList.remove('show'); raiz.getElementById('ir').style.display = ''; raiz.getElementById('ficar').textContent = 'Ficar'; raiz.getElementById('ir').textContent = 'Ir agora'; raiz.getElementById('ir').onclick = () => ir(1); }, 7000);
  }

  chrome.storage.local.get(['modoLeitura', 'autoProximo']).then(v => {
    opc.modoLeitura = v.modoLeitura !== false;
    opc.autoProximo = v.autoProximo !== false;
    atualizar();
    setInterval(atualizar, 1500);
  });
  chrome.storage.onChanged.addListener(m => {
    if (m.autoProximo) opc.autoProximo = m.autoProximo.newValue !== false;
  });
})();

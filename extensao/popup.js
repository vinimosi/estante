const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

function quando(ms) {
  const m = Math.round((Date.now() - ms) / 60000);
  if (m < 1) return 'agora há pouco';
  if (m < 60) return 'há ' + m + ' min';
  const h = Math.round(m / 60);
  return h < 24 ? 'há ' + h + ' h' : 'há ' + Math.round(h / 24) + ' dia(s)';
}

async function mostrar() {
  const r = await chrome.runtime.sendMessage({tipo: 'atualizar'}).catch(() => ({}));
  const v = await chrome.storage.local.get(['fila', 'ultimo', 'faltando', 'sites', 'estanteVista', 'verif', 'ultimaVerif', 'ultimasAtualizacoes', 'minhas', 'avisados']);
  const aberta = v.estanteVista && Date.now() - v.estanteVista < 15000;
  $('st').className = 'st ' + (aberta ? 'ok' : 'off');
  $('stTxt').textContent = aberta ? 'Conectada à Estante' : 'A Estante está fechada';
  const fila = (v.fila || []).length;
  let html = '';
  if (v.ultimo) html += `Último registrado: <b>${esc(v.ultimo.nome || '')}</b>, capítulo ${esc(v.ultimo.capitulo)} <span class="dim">(${quando(v.ultimo.quando || Date.now())})</span>`;
  else html += 'Abra um capítulo num dos seus sites de leitura e ele aparece aqui.';
  if (fila) html += `<div class="dim" style="margin-top:6px">${fila} capítulo(s) guardado(s). Eles vão para a Estante assim que você abrir ela.</div>`;
  const vf = v.verif && v.verif.lista && v.verif.lista.length;
  html += `<div class="dim" style="margin-top:6px">${v.ultimasAtualizacoes ? 'Últimas atualizações dos sites olhadas ' + quando(v.ultimasAtualizacoes) + ' (a cada 15 min, mesmo com a Estante fechada, para ' + (v.minhas || []).length + ' séries).' : 'As páginas de últimas atualizações dos sites são olhadas a cada 15 minutos.'}</div>`;
  html += `<div class="dim" style="margin-top:4px">${vf ? 'Volta completa, série por série: faltam ' + vf + ' página(s).' : v.ultimaVerif ? 'Volta completa, série por série, ' + quando(v.ultimaVerif) + '. A próxima é em até 12 horas.' : 'A volta completa, série por série, é a cada 12 horas, com a Estante aberta.'}</div>`;
  $('ultimo').innerHTML = html;
  const falt = v.faltando || [];
  if (falt.length) {
    const doms = [...new Set(falt.map(o => o.replace(/^\*:\/\/(\*\.)?/, '').replace(/\/\*$/, '')))];
    $('faltando').innerHTML = `<div class="box">A Estante tem site(s) novo(s) na lista. O navegador pede sua autorização para a extensão ler: <b>${doms.map(esc).join(', ')}</b><br><br><button id="autorizar">Autorizar</button></div>`;
    $('autorizar').onclick = async () => {
      const ok = await chrome.permissions.request({origins: falt.flatMap(o => [o, o.replace('*://', '*://*.')])}).catch(() => false);
      if (ok) await chrome.runtime.sendMessage({tipo: 'atualizar'});
      mostrar();
    };
  } else $('faltando').innerHTML = '';
  const av = v.avisados || [];
  $('avisados').style.display = av.length ? '' : 'none';
  $('avisados').innerHTML = av.length ? 'Últimos avisos:<ul>' + av.slice(-4).reverse().map(a => `<li>${esc(a.nome)} ${esc(a.n)} <span class="dim">(${esc(a.site)}, ${quando(a.quando)})</span></li>`).join('') + '</ul>' : '';
  $('sites').innerHTML = 'Sites acompanhados:<ul>' + (v.sites || []).map(s => `<li>${esc(s.nome)} <span class="dim">(${esc(s.dominio)})</span></li>`).join('') + '</ul>';
}

// ---- o que a extensão reconheceu na aba aberta e, quando não reconheceu, por quê.
// "Copiar detalhes" ajuda a avisar quando um site muda o jeito da página.
const fmtN = n => String(n).replace('.', ',');
async function diagnosticar(tab) {
  let url;
  try { url = new URL(tab.url); } catch (e) { url = null; }
  if (!url || !/^https?:$/.test(url.protocol)) return {texto: 'Esta aba não é de um site.', detalhes: ''};
  const host = url.hostname.replace(/^www\./, '');
  const {sites = []} = await chrome.storage.local.get('sites');
  const site = sites.find(s => [s.dominio, ...(s.antigos || [])].some(d => d && (host === d || host.endsWith('.' + d))));
  const detalhes = ['Estante · Leitura ' + chrome.runtime.getManifest().version, 'Endereço: ' + url.href];
  if (!site) {
    return {texto: `${esc(host)} não está na sua lista de sites. Para a Estante marcar o que você lê aqui, acrescente o site na Estante, em Configurações › Leitura.`,
            detalhes: [...detalhes, 'Resultado: site fora da lista'].join('\n')};
  }
  const autorizado = await chrome.permissions.contains({origins: [`*://${url.hostname}/*`]}).catch(() => false);
  if (!autorizado) {
    return {texto: `${esc(site.nome)} está na sua lista, mas falta autorizar a extensão a ler este site. Use o botão “Autorizar” aqui embaixo.`,
            detalhes: [...detalhes, 'Resultado: site sem autorização'].join('\n')};
  }
  const d = await chrome.tabs.sendMessage(tab.id, {tipo: 'diagnostico'}).catch(() => null);
  if (!d) {
    return {texto: `A extensão ainda não está lendo esta aba. Recarregue a página (F5) e abra esta janelinha de novo.`,
            detalhes: [...detalhes, 'Resultado: sem resposta da página (precisa recarregar)'].join('\n')};
  }
  if (!d.reconheceu) {
    const porque = d.conhecido
      ? `O endereço não parece de um capítulo nem da página de uma série do ${esc(site.nome)}. Se for um capítulo, o site pode ter mudado o jeito dos endereços: copie os detalhes e avise.`
      : `Neste site a Estante reconhece o capítulo pelo endereço, quando ele tem algo como “chapter-12”. Este endereço não tem.`;
    const series = d.series || [];
    return {texto: porque + (series.length ? ` Nesta página há ${series.length} link(s) de séries do ${esc(site.nome)}.` : ''),
            detalhes: [...detalhes, 'Site: ' + site.nome, 'Resultado: endereço não reconhecido',
                       'Séries na página:' + (series.length ? '\n  ' + series.join('\n  ') : ' nenhuma'),
                       'Caixas de busca:' + ((d.busca || []).length ? '\n  ' + d.busca.join('\n  ') : ' nenhuma')].join('\n')};
  }
  if (d.tipo === 'serie') {
    return {texto: `✓ Página da série <b>${esc(d.serie)}</b> no ${esc(d.site)}. ${d.capitulos ? d.capitulos + ' capítulo(s) na tela.' : 'Nenhum link de capítulo na tela: se a lista aparecer depois de rolar ou clicar, ela é lida quando aparecer.'}`,
            detalhes: [...detalhes, 'Site: ' + d.site, 'Série: ' + d.serie, 'Capítulos na tela: ' + d.capitulos].join('\n')};
  }
  const prox = d.proximo != null ? `Próximo: ${fmtN(d.proximo)}.` : 'Não achei o link do próximo capítulo nesta página.';
  return {texto: `✓ <b>${esc(d.serie)}</b>, capítulo ${fmtN(d.capitulo)}, no ${esc(d.site)}. ${prox}${d.enviado ? ' Já foi mandado para a Estante.' : ''}`,
          detalhes: [...detalhes, 'Site: ' + d.site, 'Série: ' + d.serie, 'Capítulo: ' + d.capitulo, 'Próximo: ' + (d.proximo ?? 'não achado'),
                     'Anterior: ' + (d.anterior ?? 'não achado'), 'Mandado para a Estante: ' + (d.enviado ? 'sim' : 'ainda não'),
                     'Imagens na página: ' + (d.imagens ?? '?'), ...(d.caixas != null ? ['Páginas do leitor (pela regra do site): ' + d.caixas] : []),
                     'Contador de páginas:' + ((d.paginas || []).length ? '\n  ' + d.paginas.join('\n  ') : ' nenhum achado')].join('\n')};
}
async function mostrarPagina() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true}).catch(() => []);
  const r = tab ? await diagnosticar(tab) : {texto: 'Nenhuma aba aberta.', detalhes: ''};
  $('paginaTxt').innerHTML = r.texto;
  $('copiar').style.display = r.detalhes ? '' : 'none';
  $('copiar').onclick = async () => {
    try { await navigator.clipboard.writeText(r.detalhes); $('copiar').textContent = 'Copiado!'; } catch (e) { $('copiar').textContent = 'Não deu para copiar'; }
  };
}

$('atualizar').onclick = mostrar;
mostrarPagina();
chrome.storage.local.get(['modoLeitura', 'autoProximo', 'avisos']).then(v => {
  $('optModo').checked = v.modoLeitura !== false;
  $('optAuto').checked = v.autoProximo !== false;
  $('optAvisos').checked = v.avisos !== false;
});
$('optAvisos').onchange = e => chrome.storage.local.set({avisos: e.target.checked});
$('procurar').onclick = async () => {
  $('procurar').disabled = true; $('procurar').textContent = 'Procurando…';
  await chrome.runtime.sendMessage({tipo: 'verificar-agora'}).catch(() => {});
  $('procurar').disabled = false; $('procurar').textContent = 'Procurar capítulos novos agora';
  mostrar();
};
$('optModo').onchange = e => chrome.storage.local.set({modoLeitura: e.target.checked});
$('optAuto').onchange = e => chrome.storage.local.set({autoProximo: e.target.checked});
mostrar();

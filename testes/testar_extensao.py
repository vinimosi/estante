"""Testa a extensão de verdade num Chromium, com páginas que imitam os três sites.
Rode com: xvfb-run -a python3 testar_extensao.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

S = Path(_SAIDA)
T = S / "ext_teste"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)

# A extensão fala com 127.0.0.1:8765, a mesma porta da Estante de verdade e da extensão instalada no navegador.
# O teste usa uma cópia da extensão apontando para outra porta: assim os capítulos de mentira nunca chegam
# nos dados de verdade, e a extensão de verdade nunca conversa com a Estante de mentira.
PORTA = 8794
EXT = str(T / "extensao")
shutil.copytree(_os.path.join(_PROJ, "extensao"), EXT)
for _arq in Path(EXT).glob("*.*"):
    if _arq.suffix in (".js", ".json", ".html"):
        _arq.write_text(_arq.read_text("utf-8").replace("127.0.0.1:8765", f"127.0.0.1:{PORTA}"), "utf-8")
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import leitura  # noqa: E402
import testar_leitura_mocks as mocks  # noqa: E402

leitura._http_json = mocks.http_falso
_url_site = leitura.url_site
leitura.url_site = lambda chave, caminho: _url_site(chave, caminho).replace("https://", "http://")  # os sites de mentira são http
leitura.guardar_capa = mocks.capa_falsa

# ---------------- sites de mentira (mesma estrutura de links dos sites reais)
PAG = {
    ("asurascans.com", "/comics/solo-leveling-059befe1/chapter/108"): """<html><head>
      <title>Solo Leveling Chapter 108 - Read Online | Asura Scans</title>
      <meta property="og:title" content="Solo Leveling Chapter 108 - Read Online | Asura Scans">
      <meta property="og:image" content="https://cdn.asurascans.com/asura-images/covers/solo-leveling.c27830.webp"></head>
      <body><a href="/">Home</a> <a href="/comics/solo-leveling-3ebcc5a9"><span>Solo Leveling</span><span>Chapter 108</span></a>
      <a href="/comics/solo-leveling-3ebcc5a9/chapter/107">Prev</a> <a href="/comics/solo-leveling-3ebcc5a9/chapter/109">Next</a>
      <img src="/p1.webp"></body></html>""",
    ("comix.to", "/title/rm2xv-omniscient-reader/5531781-chapter-228"): """<html><head><title>Omniscient Reader · Ch.228</title></head>
      <body><div id="app-root"><a href="/title/rm2xv-omniscient-reader"></a><a href="/title/rm2xv-omniscient-reader">Omniscient Reader</a>
      <button id="prox">Next</button><div class="leitor__barra"><span class="leitor__pag">3 / 20</span></div></div>
      <script>
        // o Comix real não tem link de próximo: o botão troca de capítulo sem recarregar a página
        document.getElementById('prox').addEventListener('click', e => {
          history.pushState({}, '', '/title/rm2xv-omniscient-reader/5531999-chapter-229');
          document.title = 'Omniscient Reader · Ch.229';
        });
      </script></body></html>""",
    ("demonicscans.org", "/title/Swordmaster%2527s-Youngest-Son/chapter/218/1"): """<html><head>
      <title>Swordmaster's Youngest Son Chapter 218</title><meta property="og:title" content="Swordmaster's Youngest Son Chapter 218">
      <meta property="og:image" content="https://readermc.org/images/thumbnails/Swordmaster’s Youngest Son.webp"></head>
      <body><a href="/manga/Swordmaster%2527s-Youngest-Son">Swordmaster's Youngest Son</a>
      <a href="/chaptered.php?manga=12345&chapter=217">Prev</a> <a href="/chaptered.php?manga=12345&chapter=219">Next</a></body></html>""",
    ("demonicscans.org", "/manga/Swordmaster%2527s-Youngest-Son"): """<html><head><title>Swordmaster's Youngest Son</title>
      <meta property="og:image" content="https://readermc.org/images/thumbnails/Swordmaster’s Youngest Son.webp"></head>
      <body><h1>Swordmaster's Youngest Son</h1><a href="/chaptered.php?manga=12345&chapter=1">Read First Chap</a>
      <div id="chapters-list">""" + "".join(
        f'<a class="chplinks" href="/chaptered.php?manga=12345&chapter={n}">Chapter {n}<span>2024-12-01</span></a>'
        for n in range(220, 0, -1)) + "</div><a href='/chaptered.php?manga=999&chapter=5'>Recomendado</a></body></html>",
    ("google.com", "/chapter/1"): "<html><head><title>Outro site Chapter 1</title></head><body>nada</body></html>",
}


ASURA_ULTIMO = {"n": 112}
VISITAS = []


class Sites(BaseHTTPRequestHandler):
    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0].removeprefix("www.")
        VISITAS.append((host, self.path))
        if host == "asurascans.com" and self.path.rstrip("/") in ("/comics/solo-leveling", "/comics/solo-leveling-3ebcc5a9"):
            corpo = "<html><head><title>Solo Leveling | Asura Scans</title></head><body><h1>Solo Leveling</h1>" + "".join(
                f'<a href="/comics/solo-leveling-3ebcc5a9/chapter/{n}">Chapter {n}</a>' for n in range(ASURA_ULTIMO["n"], -1, -1)) + \
                '<a href="/comics/nano-machine-aa11bb22/chapter/300">Recomendado</a></body></html>'
            b = corpo.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if host == "comix.to" and self.path.rstrip("/") == "/title/rm2xv-omniscient-reader":
            corpo = ('<html><head><title>Omniscient Reader</title></head><body><a href="/title/rm2xv-omniscient-reader/5000001-chapter-1">Ler</a>'
                     '<script>{"latestChapter":231,"latestChapterUrl":"/title/rm2xv-omniscient-reader/5539000-chapter-231"},'
                     '{"latestChapter":99,"latestChapterUrl":"/title/qq1-outra/700-chapter-99"}</script></body></html>')
            b = corpo.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if host == "comix.to" and self.path.split("?")[0] == "/user":  # imita Perfil > Followed Titles: 3 páginas sem recarregar
            corpo = """<html><body><main><div id="cards"></div>
<nav class="npager"><button type="button" class="npager__num is-active" id="ativa">1</button>
<button type="button" class="npager__nav" aria-label="Next page" id="prox">&gt;</button></nav></main>
<script>
const PAGS = [[["ca1-serie-comix-a", "Série Comix A", "10 / 12"], ["cb2-serie-comix-b", "Série Comix B", "— / 7"]],
              [["cc3-serie-comix-c", "Série Comix C", "3 / 4"], ["cd4-serie-comix-d", "Série Comix D", "1 / 1"]],
              [["ce5-serie-comix-e", "Série Comix E", "50 / 51"]],
              [["cf6-serie-comix-f", "Série Comix F", "2 / 9"]]];
let i = 0;
function mostrar() {
  document.getElementById('cards').innerHTML = PAGS[i].map(([s, t, ch]) => `<a class="card card--compact" href="/title/${s}">
    <div class="card__body"><span class="card__ch">${ch}</span><div class="card__title">${t}</div></div></a>`).join('');
  document.getElementById('prox').disabled = i === PAGS.length - 1;
}
// o site marca a página nova na hora, mas a terceira demora 14 s para aparecer (como o Comix quando fica lento)
document.getElementById('prox').onclick = () => { if (i < PAGS.length - 1) { i++; document.getElementById('ativa').textContent = i + 1; setTimeout(mostrar, i === 2 ? 14000 : 300); } };
mostrar();
</script></body></html>"""
            b = corpo.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if self.path.startswith("/img/"):
            import io as _io
            from PIL import Image as _Im
            b = _io.BytesIO()
            _Im.new("RGB", (800, 1200), (60, 90, 140)).save(b, "PNG")
            b = b.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if host == "comix.to" and self.path.startswith("/title/zz9-leitor-comix/"):
            # imita o leitor do Comix: uma caixa .rpage-page por página; as que não carregaram mostram "4 / 20".
            # Capítulo 10: rola por dentro de um bloco do tamanho da tela. Capítulo 20: uma página por vez.
            n = int(self.path.rstrip("/").split("-")[-1])
            img = "<img src='/img/0.png' width='800' height='1200'>"
            if n == 10:
                caixas = "".join(f"<div class='rpage-page'>{img}</div>" if k < 3 else
                                 f"<div class='rpage-page' style='height:1200px'><div class='rpage-page__loader'><div class='rpage-page__loader-inner'>"
                                 f"<span class='rpage-page__counter mono'>{k + 1} / 20</span></div></div></div>" for k in range(20))
                leitor = f"<div class='rpage-main' style='height:100vh;overflow-y:auto'><div class='rpage-main__inner'>{caixas}</div></div>"
            else:
                caixas = "".join("<div class='rpage-page' style='display:none;height:80vh;overflow:hidden'>" + img + "</div>" for k in range(20))
                leitor = (f"<div class='rpage-main' style='height:100vh'><div class='rpage-main__inner'>{caixas}</div><button id='pagProx'>›</button></div>"
                          "<script>let atual = 0; const ps = document.querySelectorAll('.rpage-page');"
                          "const mostrar = () => ps.forEach((p, k) => p.style.display = k === atual ? '' : 'none'); mostrar();"
                          "document.getElementById('pagProx').onclick = () => { atual = Math.min(ps.length - 1, atual + 1); mostrar(); };"
                          "window.irPara = k => { atual = k; mostrar(); };</script>")
            corpo = (f"<html><head><title>Leitor Comix · Ch.{n}</title></head><body style='margin:0;overflow:hidden'><div id='app-root'>"
                     f"<a href='/title/zz9-leitor-comix'>Leitor Comix</a>{leitor}</div></body></html>")
            b = corpo.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if host == "comix.to" and self.path.split("?")[0] == "/procurar":  # imita a busca do topo do Comix
            corpo = """<html><body><header class="topnav"><div class="topnav__inner"><div class="search">
<form class="search__form"><input placeholder="Search any title..."></form></div></div></header><main>Início</main>
<script>
const CAT = [["19wgn-memorize", "Memorize", "MANHWA"], ["x9mgj-memorial", "Memorial", "MANHWA"], ["988xr-demonize", "Demonize", "MANHWA"],
             ["ab1-the-magic-towers-problem-child", "The Magic Tower's Problem Child", "MANHWA"],
             ["dp1-twin", "Twin", "MANGA"], ["dp2-twin", "Twin", "MANHWA"]];
const campo = document.querySelector('input');
let t = null, valor = '';
// como no site de verdade (React): o texto só conta quando entra pelo jeito de dentro do navegador
campo.addEventListener('input', () => {
  clearTimeout(t);
  t = setTimeout(() => {
    document.querySelectorAll('.search-pop').forEach(e => e.remove());
    const q = campo.value.toLowerCase().trim();
    window.BUSCAS = (window.BUSCAS || 0) + (q ? 1 : 0);
    if (!q) return;
    const r = CAT.filter(c => c[1].toLowerCase().includes(q));
    const d = document.createElement('div');
    d.className = 'search-pop';
    d.innerHTML = '<div class="search-pop__section"><ul class="search-pop__list">' + r.map(c =>
      '<li class="search-pop__item"><a class="search-pop__item-link" href="/title/' + c[0] + '"><span>' + c[1] + '</span><span>' + c[2] +
      '\u00b7Ch.5</span></a></li>').join('') + '</ul></div>';
    document.body.appendChild(d);
  }, 600);
});
</script></body></html>"""
            b = corpo.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if host == "asurascans.com" and self.path.startswith("/comics/solo-leveling-3ebcc5a9/chapter/12"):
            n = int(self.path.rstrip("/").split("/")[-1])
            corpo = (f"<html><head><title>Solo Leveling Chapter {n} - Read Online | Asura Scans</title></head><body style='margin:0'>"
                     "<header id='topo' style='height:80px;background:#333'>Menu do site</header>"
                     "<div id='lado' style='position:fixed;right:0;top:100px;width:160px;height:600px;background:red'>Anúncio</div>"
                     f"<a href='/comics/solo-leveling-3ebcc5a9'>Solo Leveling</a> <a href='/comics/solo-leveling-3ebcc5a9/chapter/{n - 1}'>Prev</a> "
                     f"<a href='/comics/solo-leveling-3ebcc5a9/chapter/{n + 1}'>Next</a>"
                     "<div id='leitor' style='max-width:800px;margin:auto'>"
                     + "".join(f"<img class='pagina' src='/img/{k}.png' width='800' height='1200'>" for k in range(3))
                     + "<div id='banner'><img class='propaganda' src='/img/ad.png' width='800' height='1200'></div>"
                     + "".join(f"<img class='pagina' src='/img/{k}.png' width='800' height='1200'>" for k in range(3, 6))
                     + "<button id='botao'>Clique aqui se as imagens não carregarem</button></div><footer style='height:300px'>Rodapé</footer></body></html>")
            b = corpo.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        corpo = PAG.get((host, self.path.split("?")[0]))
        if corpo is None:
            corpo = "<html><head><title>Página</title></head><body>ok</body></html>"
        b = corpo.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


sites_srv = ThreadingHTTPServer(("127.0.0.1", 9188), Sites)
threading.Thread(target=sites_srv.serve_forever, daemon=True).start()

from werkzeug.serving import make_server  # noqa: E402


def subir_estante():
    srv = make_server("127.0.0.1", PORTA, app.app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


estante = subir_estante()

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


def series():
    out = {}
    for s in leitura._load()["series"]:
        s["capitulos"] = {k: v for e in (s.get("por_site") or {}).values() for k, v in (e.get("caps") or {}).items()}
        out[s["name"]] = s
    return out


def esperar(cond, seg=15):
    fim = time.time() + seg
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.25)
    return False


from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(T / "perfil"), headless=False,
        args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}",
              "--host-resolver-rules=MAP asurascans.com 127.0.0.1:9188, MAP comix.to 127.0.0.1:9188, "
              "MAP demonicscans.org 127.0.0.1:9188, MAP www.demonicscans.org 127.0.0.1:9188, MAP google.com 127.0.0.1:9188"])
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=15000)
    ext_id = sw.url.split("/")[2]
    print("extensão carregada:", ext_id)
    time.sleep(2)
    regs = sw.evaluate("chrome.scripting.getRegisteredContentScripts()")
    check(regs and "*://asurascans.com/*" in regs[0]["matches"], "a extensão pegou a lista de sites da Estante e se ligou neles")
    reserva = sw.evaluate("PADRAO.find(s => s.chave === 'comix').lista")
    check(reserva == next(s for s in leitura.SITES_PADRAO if s["chave"] == "comix")["lista"],
          "as regras de reserva da extensão (Estante fechada) têm a mesma regra da lista do Comix que a Estante")
    check(all(sw.evaluate(f"PADRAO.find(s => s.chave === '{s['chave']}').atualizacoes") == s["atualizacoes"] for s in leitura.SITES_PADRAO),
          "e as mesmas páginas de últimas atualizações dos três sites")
    pg = ctx.new_page()

    print("Asura")
    pg.goto("http://asurascans.com/comics/solo-leveling-059befe1/chapter/108")
    check(esperar(lambda: "Solo Leveling" in series()), "abrir o capítulo criou a série na Estante")
    s = series()["Solo Leveling"]
    check((s.get("lendo") or {}).get("n") == 108 and s["ultimo_lido"] == 107 and s["capitulos"].get("109", "").endswith("/chapter/109"),
          "abriu o 108: ele fica \"lendo\" (o 107 conta como lido) e o link do 109 é guardado")

    print("Comix (troca de capítulo sem recarregar)")
    pg.goto("http://comix.to/title/rm2xv-omniscient-reader/5531781-chapter-228")
    check(esperar(lambda: ((series().get("Omniscient Reader") or {}).get("lendo") or {}).get("n") == 228), "capítulo 228 registrado como lendo")
    pg.click("#prox")
    check(esperar(lambda: ((series().get("Omniscient Reader") or {}).get("lendo") or {}).get("n") == 229 and series()["Omniscient Reader"]["ultimo_lido"] == 228),
          "trocou para o 229 sem recarregar: o 228 conta como lido e o 229 fica lendo")
    s = series()["Omniscient Reader"]
    check(s["capitulos"].get("229", "").endswith("5531999-chapter-229"), "link exato do capítulo lido guardado")

    print("Demonic Scans")
    pg.goto("http://demonicscans.org/title/Swordmaster%2527s-Youngest-Son/chapter/218/1")
    check(esperar(lambda: "Swordmaster's Youngest Son" in series()), "série criada com o nome certinho (do link para a série)")
    s = series()["Swordmaster's Youngest Son"]
    check((s.get("lendo") or {}).get("n") == 218 and "chapter=219" in s["capitulos"].get("219", ""), "botão Próximo (outro formato de link) guardado")
    pg.goto("http://www.demonicscans.org/manga/Swordmaster%2527s-Youngest-Son")
    check(esperar(lambda: series()["Swordmaster's Youngest Son"].get("ultimo_disponivel") == 220),
          "a lista de capítulos da página da série mostrou que já saiu o 220 (e ignorou o recomendado)")
    s = leitura.serie_out(series()["Swordmaster's Youngest Son"])
    check(s["url_serie"].split("://")[1] == "demonicscans.org/manga/Swordmaster%2527s-Youngest-Son" and s["capitulos"]["219"].endswith("chapter=219") and s["proximo_cap"]["continuar"],
          "link da série e do capítulo 219 certos")

    print("Outros sites")
    pg.goto("http://google.com/chapter/1")
    time.sleep(3.5)
    check("Outro Site" not in series() and len(series()) == 3, "site fora da lista: a extensão não faz nada")

    print("Estante fechada")
    estante.shutdown()
    time.sleep(0.5)
    pg.goto("http://asurascans.com/comics/solo-leveling-059befe1/chapter/108")
    pg.evaluate("history.pushState({}, '', '/comics/solo-leveling-059befe1/chapter/110')")
    check(esperar(lambda: len(sw.evaluate("chrome.storage.local.get('fila').then(v => v.fila || [])")) >= 1, 10),
          "com a Estante fechada, o capítulo fica guardado na extensão")
    estante = subir_estante()
    pop = ctx.new_page()
    pop.goto(f"chrome-extension://{ext_id}/popup.html")
    check(esperar(lambda: (series()["Solo Leveling"].get("lendo") or {}).get("n") == 110, 10), "quando a Estante abre de novo, o capítulo guardado chega")
    pop.reload()
    time.sleep(1.5)
    txt = pop.inner_text("body")
    check("Conectada à Estante" in txt and "Solo Leveling" in txt and "110" in txt, "a janelinha da extensão mostra o último capítulo registrado")
    pop.screenshot(path=str(S / "telas" / "l_extensao_popup.png"))

    print("Extensão olha os sites sozinha (como o Mihon)")
    ASURA_ULTIMO["n"] = 113
    leitura._marcar(series()["Solo Leveling"]["id"], status="Em andamento")  # séries completas não são olhadas
    pop.evaluate("chrome.runtime.sendMessage({tipo: 'verificar-agora'})")
    check(esperar(lambda: (series()["Solo Leveling"].get("por_site") or {}).get("asura", {}).get("ultimo") == 113, 40),
          "a extensão olhou a página da série no Asura e achou o capítulo 113")
    check(esperar(lambda: (series()["Omniscient Reader"].get("por_site") or {}).get("comix", {}).get("ultimo") == 231, 40),
          "no Comix, achou o último capítulo (231) dentro da página, ignorando a série recomendada")
    s = leitura.serie_out(series()["Solo Leveling"])
    check(s["tem_novo"] and any(x["site"] == "asura" and x["ultimo_txt"] == "113" for x in s["sites_info"]), "capítulo novo aparece com o selo e o Asura mostra até o 113")
    check(not any(h == "asurascans.com" and "nano-machine" in p for h, p in VISITAS), "não sai abrindo outras séries")

    print("Modo leitura")
    pg.goto("http://asurascans.com/comics/solo-leveling-3ebcc5a9/chapter/120")
    pg.wait_for_timeout(3500)
    esc_ = lambda sel: pg.evaluate(f"getComputedStyle(document.querySelector('{sel}')).display")
    check(pg.evaluate("!!document.getElementById('estante-raiz') && !!document.getElementById('estante-raiz').shadowRoot.getElementById('b')"),
          "a barra da Estante aparece por cima do capítulo")
    check(esc_("#topo") == "none" and esc_("#lado") == "none" and esc_("#banner") == "none" and esc_("#botao") == "none",
          "menu, anúncio lateral, banner no meio das páginas e botões do site escondidos")
    check(pg.evaluate("[...document.querySelectorAll('img.pagina')].every(i => getComputedStyle(i).display !== 'none')"), "as 6 páginas do capítulo continuam")
    txt = pg.evaluate("document.getElementById('estante-raiz').shadowRoot.getElementById('b').innerText")
    check("Solo Leveling" in txt and "Capítulo 120" in txt and "Capítulo 121" in txt, "barra mostra série, capítulo e o próximo")
    pg.screenshot(path=str(S / "telas" / "m1_modo_leitura.png"))
    pg.keyboard.press("ArrowRight")
    pg.wait_for_timeout(2500)
    check(pg.url.endswith("/chapter/121"), "seta para a direita vai para o próximo capítulo")
    pg.wait_for_timeout(2000)
    pg.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    pg.wait_for_timeout(1500)
    txt = pg.evaluate("document.getElementById('estante-raiz').shadowRoot.getElementById('fim').innerText")
    check("Indo para o capítulo 122" in txt, "no fim do capítulo começa a contagem para o próximo")
    pg.screenshot(path=str(S / "telas" / "m2_fim.png"))
    pg.wait_for_timeout(6500)
    check(pg.url.endswith("/chapter/122"), "e vai sozinho para o capítulo 122")
    check(esperar(lambda: series()["Solo Leveling"]["ultimo_lido"] >= 121 and (series()["Solo Leveling"].get("lendo") or {}).get("n") == 122, 10),
          "e a Estante registrou: 120 e 121 lidos até o fim, 122 lendo")

    print("Onde parei no meio do capítulo")
    pg.goto("http://asurascans.com/comics/solo-leveling-3ebcc5a9/chapter/125")
    pg.wait_for_timeout(3000)
    pg.evaluate("document.querySelectorAll('img.pagina')[3].scrollIntoView({block: 'start'})")
    check(esperar(lambda: (series()["Solo Leveling"].get("lendo") or {}).get("pagina") == 3, 15), "parou na página 4: a Estante guardou a posição")
    s = leitura.serie_out(series()["Solo Leveling"])
    check(s["ultimo_lido"] == 124 and s["proximo_cap"]["continuar"] and s["proximo_cap"]["num"] == "125", "o capítulo não conta como lido; o próximo é continuar o 125")
    pg.goto("http://asurascans.com/")
    pg.wait_for_timeout(500)
    pg.goto("http://asurascans.com/comics/solo-leveling-3ebcc5a9/chapter/125")
    pg.wait_for_timeout(5000)
    y = pg.evaluate("window.scrollY")
    alvo = pg.evaluate("document.querySelectorAll('img.pagina')[3].offsetTop")
    txt = pg.evaluate("document.getElementById('estante-raiz').shadowRoot.getElementById('fim').innerText")
    check(abs(y - alvo) < 250 and "Continuando da página 4" in txt, "ao voltar, a página rola sozinha até onde você parou")
    pg.screenshot(path=str(S / "telas" / "m4_continuando.png"))

    print("Onde parei no Comix (regra \"paginas\": cada página é uma caixa do leitor)")
    check(sw.evaluate("PADRAO.find(s => s.chave === 'comix').paginas") == next(s for s in leitura.SITES_PADRAO if s["chave"] == "comix")["paginas"],
          "a regra de reserva da extensão tem a mesma regra de páginas do Comix")
    lc = lambda: series().get("Leitor Comix") or {}
    pg.goto("http://comix.to/title/zz9-leitor-comix/7000010-chapter-10")
    pg.wait_for_timeout(3000)
    pg.evaluate("document.querySelectorAll('.rpage-page')[7].scrollIntoView({block: 'start'})")
    check(esperar(lambda: (lc().get("lendo") or {}).get("n") == 10 and lc()["lendo"].get("pagina") == 7, 15),
          "leitor que rola por dentro: parou na página 8 e a Estante guardou")
    check((lc().get("ultimo_lido") or 0) < 10, "o capítulo ainda não conta como lido")
    pg.goto("http://asurascans.com/")
    pg.wait_for_timeout(500)
    pg.goto("http://comix.to/title/zz9-leitor-comix/7000010-chapter-10")
    pg.wait_for_timeout(5000)
    topo = pg.evaluate("document.querySelectorAll('.rpage-page')[7].getBoundingClientRect().top")
    txt = pg.evaluate("document.getElementById('estante-raiz').shadowRoot.getElementById('fim').innerText")
    check(abs(topo) < 60 and "Continuando da página 8 de 20" in txt, "ao voltar, o leitor rola sozinho até a página 8")
    pg.screenshot(path=str(S / "telas" / "m5_comix_continuando.png"))
    pg.evaluate("document.querySelector('.rpage-main').scrollTop = 1e9")
    check(esperar(lambda: lc().get("ultimo_lido") == 10, 15), "chegou ao fim da última página: o capítulo 10 conta como lido")

    pg.goto("http://comix.to/title/zz9-leitor-comix/7000020-chapter-20")
    pg.wait_for_timeout(3000)
    pg.evaluate("irPara(4)")
    check(esperar(lambda: (lc().get("lendo") or {}).get("n") == 20 and lc()["lendo"].get("pagina") == 4, 15),
          "leitor de uma página por vez: parou na página 5 e a Estante guardou")
    pg.goto("http://asurascans.com/")
    pg.wait_for_timeout(500)
    pg.goto("http://comix.to/title/zz9-leitor-comix/7000020-chapter-20")
    pg.wait_for_timeout(5000)
    txt = pg.evaluate("document.getElementById('estante-raiz').shadowRoot.getElementById('fim').innerText")
    check("Você parou na página 5 de 20" in txt, "ao voltar, avisa em que página você parou (esse leitor não deixa rolar até ela)")
    check((lc().get("lendo") or {}).get("pagina") == 4, "e abrir de novo no começo não apaga a página guardada")
    pg.screenshot(path=str(S / "telas" / "m6_comix_uma_por_vez.png"))
    pg.evaluate("irPara(19)")
    check(esperar(lambda: lc().get("ultimo_lido") == 20, 15), "chegou na última página: o capítulo 20 conta como lido")
    app.app.test_client().delete(f"/api/leitura/{lc()['id']}")  # tira a série de teste, para não mexer nas contas das próximas partes

    print("Ler dentro da janela da Estante")
    pg.goto(f"http://127.0.0.1:{PORTA}/")
    pg.wait_for_timeout(1200)
    pg.click("#shelves >> text=Leitura")
    pg.wait_for_timeout(1500)
    pg.click(".grid .card:has-text('Solo Leveling') .meta")
    pg.wait_for_timeout(600)
    pg.screenshot(path=str(S / "telas" / "m5_painel_continuar.png"))
    antes = app.last_ping
    pg.click("#drawer button:has-text('Ler capítulo')")
    pg.wait_for_url("**/comics/**", timeout=10000)
    check("asurascans.com" in pg.url and len(ctx.pages) == 3, "o capítulo abriu na mesma janela da Estante, sem janela nova")
    pg.wait_for_timeout(3000)
    vis = pg.evaluate("getComputedStyle(document.getElementById('estante-raiz').shadowRoot.getElementById('voltar')).display")
    check(vis != "none", "a barra tem o botão “← Estante”")
    check(app.last_ping > antes and not app.ocioso(), "a extensão mantém a Estante aberta enquanto você lê")
    pg.mouse.move(640, 300)
    pg.mouse.move(640, 4)
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(S / "telas" / "m3_embutido.png"))
    pg.evaluate("document.getElementById('estante-raiz').shadowRoot.getElementById('voltar').click()")
    pg.wait_for_url(f"http://127.0.0.1:{PORTA}/", timeout=10000)
    pg.wait_for_timeout(2000)
    check(pg.locator("#drawer.show h2:has-text('Solo Leveling')").count() == 1, "“← Estante” volta para a Leitura com o painel da série aberto")

    print("Lista do Comix (Followed Titles)")
    with app.lock:
        d = leitura._load()
        for letra in "ABCDEF":
            s = leitura.nova_serie(f"Série Comix {letra}")
            s["nome_comix"] = f"Série Comix {letra}"
            d["series"].append(s)
        leitura._save(d)
    lista = ctx.new_page()
    lista.goto("http://comix.to/user?tab=titles")  # aberta sem a Estante: só lê a página que está na tela
    check(esperar(lambda: (leitura._load() and next(s for s in leitura._load()["series"] if s["name"] == "Série Comix A")
                           .get("por_site", {}).get("comix", {}).get("slug") == "ca1-serie-comix-a"), 15),
          "abrir a lista no Comix liga as séries da página que está na tela")
    time.sleep(9)
    check(not (next(s for s in leitura._load()["series"] if s["name"] == "Série Comix C").get("por_site") or {}).get("comix"),
          "aberta por fora da Estante, a extensão não passa as páginas sozinha")
    lista.goto("http://comix.to/user?tab=titles#estante-ligar")  # aberta pela Estante: passa as páginas devagar
    check(esperar(lambda: (next(s for s in leitura._load()["series"] if s["name"] == "Série Comix F").get("por_site") or {}).get("comix"), 150),
          "aberta pela Estante, a extensão passou as 4 páginas e ligou as séries da última")
    check((next(s for s in leitura._load()["series"] if s["name"] == "Série Comix E").get("por_site") or {}).get("comix"),
          "a página que demorou a aparecer não foi pulada (a extensão esperou em vez de clicar de novo)")
    check(esperar(lambda: "pronto" in (lista.evaluate("(document.getElementById('estante-lista') || {}).textContent || ''")), 30),
          "no fim, um aviso na página diz que ficou pronto")
    lista.screenshot(path=str(S / "telas" / "n1_lista_comix.png"))
    ss = {s["name"]: s for s in leitura._load()["series"]}
    check(ss["Série Comix A"]["ultimo_lido"] == 10 and ss["Série Comix B"]["ultimo_lido"] in (None, 0) and ss["Série Comix E"]["site"] == "comix",
          "capítulo lido de cada cartão anotado (só para frente) e o Comix vira o site principal")
    lista.close()

    print("Ligar as séries sem site pela busca do Comix")
    check(sw.evaluate("PADRAO.find(s => s.chave === 'comix').busca") == next(s for s in leitura.SITES_PADRAO if s["chave"] == "comix")["busca"],
          "a regra de reserva da busca na extensão é igual à da Estante")
    regra = next(s for s in leitura.SITES_PADRAO if s["chave"] == "comix")["busca"]
    regra["espera"] = 2  # no teste, sem esperar 8 segundos entre uma busca e outra
    leitura._esquecer_sites()
    sw.evaluate("pegarSites()")
    with app.lock:
        d = leitura._load()
        agora = time.time()
        for s in d["series"]:
            if not s.get("por_site"):
                s.setdefault("buscada", {})["comix"] = agora  # as outras séries do teste já foram procuradas
        for nome, alt in (("Memorize", []), ("The Magic Tower’s Problem Child", []), ("Twin", []), ("Kimetsu Qualquer", ["Demonize"])):
            s = leitura.nova_serie(nome)
            s["titulos_alt"] = alt
            d["series"].append(s)
        leitura._save(d)
    fila = [x["nomes"][0] for x in app.app.test_client().get("/api/leitura/para-buscar?site=comix").get_json()["series"]]
    check(sorted(fila) == sorted(["Memorize", "The Magic Tower’s Problem Child", "Twin", "Kimetsu Qualquer"]),
          "a Estante passa só as séries sem site que ainda não foram procuradas")
    busca = ctx.new_page()
    busca.goto("http://comix.to/procurar")
    time.sleep(4)
    check(busca.evaluate("window.BUSCAS || 0") == 0, "aberta por fora da Estante, a extensão não digita nada")
    busca.goto("http://comix.to/procurar#estante-buscar")
    check(esperar(lambda: "pronto" in (busca.evaluate("(document.getElementById('estante-lista') || {}).textContent || ''")), 120),
          "aberta pela Estante, a extensão procura uma por uma e avisa quando termina")
    ss = {s["name"]: s for s in leitura._load()["series"]}
    pc = lambda n: ((ss[n].get("por_site") or {}).get("comix") or {}).get("slug")  # noqa: E731
    check(pc("Memorize") == "19wgn-memorize" and ss["Memorize"]["site"] == "comix",
          "um único resultado com o mesmo nome (Memorial também apareceu, mas tem outro nome): ligada")
    check(pc("The Magic Tower’s Problem Child") == "ab1-the-magic-towers-problem-child", "acha pelo nome que está no endereço da série")
    check(pc("Kimetsu Qualquer") == "988xr-demonize", "sem resultado pelo nome, tenta o nome alternativo")
    check(not pc("Twin") and ss["Twin"]["buscada"]["comix"], "dois resultados com o mesmo nome: não chuta, e fica anotado que já procurou")
    check(busca.evaluate("window.BUSCAS") == 5, "uma busca por nome (duas para a série com nome alternativo)")
    check(app.app.test_client().get("/api/leitura/para-buscar?site=comix").get_json()["series"] == [], "procurada há pouco não volta para a fila")
    busca.screenshot(path=str(S / "telas" / "n2_busca_comix.png"))
    busca.close()

    print("Capítulos novos pelas páginas de últimas atualizações")
    with app.lock:
        d = leitura._load()
        a = next(s for s in d["series"] if s["name"] == "Série Comix A")
        a["lista_anilist"], a["ultimo_disponivel"] = "Lendo", 12.0
        for nome, site, slug, ult, lista in [("Atualiza Asura", "asura", "atualiza-asura", 20.0, "Lendo"),
                                             ("Atualiza Demonic", "demonic", "Atualiza-Demonic", 7.0, "Quero ler")]:
            s = leitura.nova_serie(nome)
            s.update({"ultimo_disponivel": ult, "lista_anilist": lista, "verificado_em": 1.0, "site": site})
            leitura._ps(s, site, slug)
            d["series"].append(s)
        leitura._save(d)
    PAG[("comix.to", "/")] = ('<html><body><script>self.dados=[{"hid":"ca1","title":"Série Comix A","poster":{"medium":"x"},"latestChapter":13,'
                              '"chapterUpdatedAtFormatted":"5m ago"},{"hid":"zz9","title":"Outra","latestChapter":99}]</script></body></html>')
    PAG[("comix.to", "/title/ca1-serie-comix-a")] = ('<html><body><a href="/title/ca1-serie-comix-a/9000013-chapter-13">13</a>'
                                                   '<a href="/title/ca1-serie-comix-a/9000012-chapter-12">12</a></body></html>')
    PAG[("asurascans.com", "/")] = ('<html><body><a href="/comics/outra-serie-3ebcc5a9">Outra</a><a href="/comics/outra-serie-3ebcc5a9/chapter/5">5</a>'
                                    '<a href="/comics/atualiza-asura-3ebcc5a9">Atualiza Asura</a><a href="/comics/atualiza-asura-3ebcc5a9/chapter/21">21</a>'
                                    '<a href="/comics/atualiza-asura-3ebcc5a9/chapter/20">20</a></body></html>')
    PAG[("demonicscans.org", "/lastupdates.php")] = ('<html><body><div><h2><a href="/manga/Atualiza-Demonic">Atualiza Demonic</a></h2>'
                                                     '<a href="chaptered.php?manga=555&amp;chapter=8">Chapter 8</a></div>'
                                                     '<div><h2><a href="/manga/Outra">Outra</a></h2><a href="chaptered.php?manga=1&amp;chapter=3">Chapter 3</a></div></body></html>')
    sw.evaluate("chrome.notifications.create = (id, o) => { self.__avisos = (self.__avisos || []).concat([o]); }")  # sem aviso de verdade na tela
    sw.evaluate("pegarMinhas()")
    visitas_antes = len(VISITAS)
    sw.evaluate("verificarAtualizacoes(true)")
    ss = lambda: {s["name"]: s for s in leitura._load()["series"]}
    check(esperar(lambda: ss()["Atualiza Asura"]["ultimo_disponivel"] == 21 and ss()["Atualiza Demonic"]["ultimo_disponivel"] == 8, 20),
          "Asura e Demonic: o capítulo novo visto na página de atualizações chegou na Estante")
    check(esperar(lambda: ss()["Série Comix A"]["ultimo_disponivel"] == 13, 20)
          and "13" in (ss()["Série Comix A"]["por_site"]["comix"].get("caps") or {}),
          "Comix: a página inicial mostrou o capítulo 13 e a extensão abriu a página da série para pegar o link certo")
    novidades = leitura._load()["novidades"]
    check(any(n["c"] == 21 and n["site"] == "asura" for n in novidades) and any(n["c"] == 13 and n["site"] == "comix" for n in novidades),
          "as Novidades dizem em que site cada capítulo saiu")
    paginas = [p for h, p in VISITAS[visitas_antes:] if not p.startswith("/img/")]
    check(sorted(set(paginas)) == ["/", "/lastupdates.php", "/title/ca1-serie-comix-a"],
          f"olhou só as páginas de atualizações e a página da única série do Comix que teve capítulo novo {sorted(set(paginas))}")
    avisos = sw.evaluate("(self.__avisos || []).filter(Boolean)")
    avisados = sw.evaluate("chrome.storage.local.get('avisados').then(v => v.avisados || [])")
    check(len(avisos) == 2 and any("Série Comix A" in x["title"] and "13" in x["message"] and "Comix" in x["message"] for x in avisos)
          and not any("Demonic" in x["title"] for x in avisos),
          f"aviso do Windows só para as séries que você está lendo, com o capítulo e o site {avisados}")
    sw.evaluate("verificarAtualizacoes(true)")
    time.sleep(2)
    check(len(sw.evaluate("(self.__avisos || []).filter(Boolean)")) == 2, "olhar de novo não repete o aviso")

    print("Com a Estante fechada")
    estante.shutdown()
    PAG[("asurascans.com", "/")] = PAG[("asurascans.com", "/")].replace("/chapter/21", "/chapter/22")
    sw.evaluate("verificarAtualizacoes(true)")
    check(esperar(lambda: any("atualiza-asura" in (x.get("url") or "") for x in sw.evaluate("chrome.storage.local.get('fila').then(v => v.fila || [])")), 15),
          "a extensão achou o capítulo 22 e guardou na fila, usando a lista de séries guardada")
    check(ss()["Atualiza Asura"]["ultimo_disponivel"] == 21, "a Estante fechada não recebeu nada ainda")
    estante = subir_estante()
    sw.evaluate("esvaziar()")
    check(esperar(lambda: ss()["Atualiza Asura"]["ultimo_disponivel"] == 22, 15), "quando a Estante abre, o capítulo guardado chega")
    sw.evaluate("chrome.storage.local.set({avisos: false})")
    PAG[("asurascans.com", "/")] = PAG[("asurascans.com", "/")].replace("/chapter/22", "/chapter/23")
    n_avisos = len(sw.evaluate("(self.__avisos || []).filter(Boolean)"))
    sw.evaluate("verificarAtualizacoes(true)")
    check(esperar(lambda: ss()["Atualiza Asura"]["ultimo_disponivel"] == 23, 15) and len(sw.evaluate("(self.__avisos || []).filter(Boolean)")) == n_avisos,
          "com os avisos desligados no popup, o capítulo chega mas não aparece aviso")
    pop2 = ctx.new_page()
    pop2.goto(f"chrome-extension://{ext_id}/popup.html")
    pop2.wait_for_selector("#optAvisos")
    check(not pop2.is_checked("#optAvisos") and "Procurar capítulos novos agora" in pop2.inner_text("body")
          and "a cada 15 min" in pop2.inner_text("body"), "o popup tem a opção de avisos, o botão de procurar e diz que olha a cada 15 minutos")
    pop2.screenshot(path=str(S / "telas" / "l_extensao_popup_avisos.png"))

    print("Versão da extensão")
    versao = json.loads(Path(EXT, "manifest.json").read_text("utf-8"))["version"]
    sw.evaluate("pegarSites()")
    check(esperar(lambda: leitura.cfg_leitura()[1].get("extensao_versao") == versao, 10), f"a extensão conta a versão dela ({versao}) para a Estante")
    cl = app.app.test_client()
    check(not cl.get("/api/leitura").get_json()["extensao_velha"], "mesma versão da pasta: nenhum aviso")
    cfg, l = leitura.cfg_leitura()
    l["extensao_versao"] = "1.2.0"
    app.save_cfg(cfg)
    r = cl.get("/api/leitura").get_json()
    check(r["extensao_velha"] and r["extensao_pasta"] == versao, "extensão mais velha que a da pasta: a Estante avisa")
    sw.evaluate("pegarSites()")
    check(esperar(lambda: not cl.get("/api/leitura").get_json()["extensao_velha"], 10), "depois de recarregar a extensão, o aviso some")

    print("O que a extensão reconheceu na página")

    def diagnostico(trecho=None, url=None):
        alvo = f"{{id: -1, url: {json.dumps(url)}}}" if url else \
            f"(await chrome.tabs.query({{}})).find(t => (t.url || '').includes({json.dumps(trecho)}))"
        return pop2.evaluate(f"(async () => {{ const t = {alvo}; return (await diagnosticar(t)); }})()")

    pg.goto("http://asurascans.com/comics/solo-leveling-3ebcc5a9/chapter/120")
    time.sleep(3)
    d = diagnostico("/chapter/120")
    check("Solo Leveling" in d["texto"] and "capítulo 120" in d["texto"] and "Próximo: 121" in d["texto"] and "Já foi mandado" in d["texto"],
          "num capítulo: mostra o site, a série, o capítulo e o próximo")
    check("Capítulo: 120" in d["detalhes"] and "asurascans.com/comics/solo-leveling-3ebcc5a9/chapter/120" in d["detalhes"] and versao in d["detalhes"],
          "e os detalhes para copiar têm o endereço, a versão e o que foi achado")
    pg.goto("http://comix.to/title/rm2xv-omniscient-reader/5531781-chapter-228")
    time.sleep(2.5)
    d = diagnostico("5531781-chapter-228")
    check("Contador de páginas:\n  3 / 20  [div#app-root > div.leitor__barra > span.leitor__pag]" in d["detalhes"] and d["detalhes"].count("3 / 20") == 1,
          "nos detalhes, o contador de páginas do leitor e onde ele fica (para ensinar o Comix)")
    pg.goto("http://www.demonicscans.org/manga/Swordmaster%2527s-Youngest-Son")
    time.sleep(2)
    d = diagnostico("/manga/Swordmaster")
    check("Página da série" in d["texto"] and "220 capítulo(s)" in d["texto"], "na página da série: quantos capítulos estão na tela")
    pg.goto("http://asurascans.com/sobre-nos")
    time.sleep(1.5)
    d = diagnostico("/sobre-nos")
    check("não parece de um capítulo" in d["texto"] and "avise" in d["texto"], "endereço que não é de capítulo nem de série: explica e pede para avisar")
    check("Séries na página: nenhuma" in d["detalhes"], "e diz que não há links de séries nela")
    pg.goto("http://comix.to/user?tab=titles")
    time.sleep(2)
    d = diagnostico("tab=titles")
    check("link(s) de séries" in d["texto"] and "Séries na página:\n  /title/" in d["detalhes"] and "texto: \"" in d["detalhes"],
          "numa página com séries (como a busca do site): os links, o nome de cada uma e onde ficam, para copiar")
    d = diagnostico(url="http://google.com/chapter/1")
    check("google.com não está na sua lista" in d["texto"] and "Configurações" in d["texto"], "site fora da lista: diz onde acrescentar")
    d = diagnostico(url="chrome://extensions")
    check("não é de um site" in d["texto"], "aba que não é de site")
    pop2.evaluate("(async () => { const t = (await chrome.tabs.query({})).find(t => (t.url || '').includes('/sobre-nos'));"
                  " const r = await diagnosticar(t); document.getElementById('paginaTxt').innerHTML = r.texto; })()")
    pop2.screenshot(path=str(S / "telas" / "l_extensao_popup_pagina.png"))
    pop2.close()

    print("Endereço novo")
    lc = leitura.cfg_leitura()
    cfg, l = lc
    for x in l["sites"]:
        if x["chave"] == "asura":
            x["antigos"] = [x["dominio"]] + x["antigos"]
            x["dominio"] = "asura-novo.net"
    app.save_cfg(cfg)
    pop.reload()
    time.sleep(1.5)
    check("Autorizar" in pop.inner_text("body") and "asura-novo.net" in pop.inner_text("body"),
          "site com endereço novo: a extensão pede autorização (o navegador exige)")
    pop.screenshot(path=str(S / "telas" / "l_extensao_autorizar.png"))
    ctx.close()

estante.shutdown()
print(f"\nTudo certo: {ok} verificações.")

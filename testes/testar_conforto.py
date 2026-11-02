"""Etapa 9, mais conforto: propagandas e escolha da fonte no Tocando agora, pular pela letra, busca única,
"Continuar lendo" e "Jogar de novo" no ícone perto do relógio, direção de leitura por série e as vezes jogadas
na tela. Com painel de mídia de mentira. Rode: python3 testar_conforto.py"""
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
from pathlib import Path

S = Path(_SAIDA)
T = S / "conforto"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402  (nada abre de verdade no Windows)
import app  # noqa: E402
import leitura  # noqa: E402
import lojas  # noqa: E402
import tocando as toc  # noqa: E402

for loja in lojas.LEITORES:
    lojas.LEITORES[loja] = lambda *a, **k: {"encontrada": False, "jogos": []}
c = app.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


# ---- painel de mídia de mentira
PAINEL, COMANDOS = [], []
SPOT, EDGE = "SpotifyAB.SpotifyMusic_x!Spotify", "MSEdge"


def sessao(app_id, titulo, artista, status="tocando", pos=10.0, dur=200.0, album="", posicao_ok=True):
    return {"app": app_id, "titulo": titulo, "artista": artista, "album": album, "status": status, "posicao": pos,
            "duracao": dur, "atualizado": time.time(), "atual": False,
            "botoes": {"tocar": status != "tocando", "pausar": status == "tocando", "anterior": True, "proximo": True,
                       "posicao": posicao_ok}}


def painel(*s):
    PAINEL[:] = list(s)
    toc._ultima["quando"] = 0.0


toc._ler_sessoes = lambda querem: json.loads(json.dumps(PAINEL))
def comando_falso(app_id, acao, segundos=0.0):
    COMANDOS.append((app_id, acao, segundos))
    for s in PAINEL:
        if s["app"] == app_id and acao == "posicao":  # o programa pulou: a posição informada muda
            s["posicao"], s["atualizado"] = segundos, time.time()
    toc._ultima["quando"] = 0.0
    return True


toc._comando = comando_falso
toc.disponivel = lambda: (True, "")
toc.ESPERA_CAPA = 99

print("Propagandas")
check(toc.e_anuncio(sessao(SPOT, "Compre já", "Loja X", dur=30)), "Spotify: sem álbum e curta é propaganda, mesmo com artista")
check(not toc.e_anuncio(sessao(SPOT, "Música Curta", "Banda", dur=30, album="Disco")), "música curta de verdade (com álbum) não é")
check(toc.e_anuncio(sessao(EDGE, "Anúncio: promoção", "Canal", dur=300)), "título com “Anúncio” é propaganda")
painel(sessao(EDGE, "Clipe Longo", "Canal", dur=240))
check(not c.get("/api/tocando").get_json()["faixa"]["anuncio"], "vídeo de 4 minutos no navegador")
painel(sessao(EDGE, "Clipe Longo", "Canal", dur=90, pos=2))
check(c.get("/api/tocando").get_json()["faixa"]["anuncio"], "o mesmo nome com 90 s: é a propaganda do YouTube antes do vídeo")
painel(sessao(EDGE, "Clipe Longo", "Canal", dur=238))
check(not c.get("/api/tocando").get_json()["faixa"]["anuncio"], "e quando o vídeo volta, deixa de ser")

print("Duas fontes tocando")
painel(sessao(SPOT, "Música A", "Artista A", album="Disco"), sessao(EDGE, "Vídeo B", "Canal B", status="pausado"))
f = c.get("/api/tocando").get_json()["faixa"]
check(f["app"] == SPOT and [x["fonte"] for x in f["fontes"]] == ["Spotify", "Edge"] and not f["escolhida"],
      "mostra a que está tocando e avisa que tem duas")
f = c.post("/api/tocando/fonte", json={"app": EDGE}).get_json()["faixa"]
check(f["app"] == EDGE and f["escolhida"], "dá para escolher mostrar a outra")
check(c.get("/api/tocando").get_json()["faixa"]["app"] == EDGE, "e a escolha continua valendo")
painel(sessao(SPOT, "Música A", "Artista A", album="Disco"))
f = c.get("/api/tocando").get_json()["faixa"]
check(f["app"] == SPOT and not f["escolhida"] and f["fontes"] == [], "a escolhida fechou: volta a escolher sozinha")

print("Pular pela letra")
r = c.post("/api/tocando/controle", json={"acao": "posicao", "segundos": 42.5})
check(r.status_code == 200 and COMANDOS[-1] == (SPOT, "posicao", 42.5), "pede ao programa para ir para 0:42")
check(c.post("/api/tocando/controle", json={"acao": "posicao", "segundos": "x"}).status_code == 400, "ponto inválido é recusado")
check(c.get("/api/tocando").get_json()["faixa"]["botoes"]["posicao"], "a tela sabe se o programa deixa pular")

print("Vezes jogadas")
def exe(n):  # o jogo precisa existir no PC de mentira, senão sai da estante quando a tela abre
    p = T / "jogos" / n / "jogo.exe"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"MZ")
    return str(p)


lib = app.get_lib()
g1, g2, g3 = (app.new_game(n, exe(n)) for n in ("Hollow Knight", "Celeste", "Oculto"))
agora = time.time()
g1["sessoes"] = [[int(agora - 30 * 86400), 3600], [int(agora - 86400), 1800], [int(agora - 3600), 600]]
g1["playtime"], g1["last_played"] = 6000, agora - 3000
g2["last_played"], g3["last_played"], g3["hidden"] = agora - 50000, agora, True
lib["games"] += [g1, g2, g3]
app.save_lib(lib)
o = app.game_out(app.find_game(app.get_lib(), g1["id"]))
check(o["sessoes_n"] == 3 and o["semana"] == 2400 and o["sessoes_recentes"][0][1] == 600, "resumo: 3 vezes, 40 min nos últimos 7 dias")
c.post(f"/api/games/{g1['id']}/reset-playtime")
check(app.find_game(app.get_lib(), g1["id"])["sessoes"] == [], "zerar o tempo jogado apaga também as vezes jogadas")
lib = app.get_lib()
app.find_game(lib, g1["id"])["sessoes"] = [[int(agora - 3600), 600]]
app.find_game(lib, g2["id"])["sessoes"] = [[int(agora - 7200), 300]]
app.save_lib(lib)
app.juntar([g1["id"], g2["id"]], g1["id"])
j = app.find_game(app.get_lib(), g1["id"])
check([s[1] for s in j["sessoes"]] == [300, 600], "juntar dois jogos junta as vezes jogadas, em ordem")
g2 = app.new_game("Celeste", exe("Celeste"))
g2["last_played"] = agora - 50000
lib = app.get_lib()
lib["games"].append(g2)
app.save_lib(lib)

print("Busca única")
d = leitura._load()
for nome, alt in (("Solo Leveling", ["Na Honjaman Level Up"]), ("Ação Total", []), ("Outra", [])):
    s = leitura.nova_serie(nome)
    s["titulos_alt"] = alt
    d["series"].append(s)
leitura._save(d)
r = c.get("/api/busca?em=leitura&q=level").get_json()
check(r["total"] == 1 and r["itens"][0]["nome"] == "Solo Leveling", "procurando na Leitura de dentro dos Jogos")
check(c.get("/api/busca?em=leitura&q=honjaman").get_json()["total"] == 1, "acha também pelos nomes alternativos")
check(c.get("/api/busca?em=leitura&q=acao").get_json()["itens"][0]["nome"] == "Ação Total", "sem se importar com acento")
r = c.get("/api/busca?em=jogos&q=CEL").get_json()
check(r["total"] == 1 and r["itens"][0]["nome"] == "Celeste", "procurando nos Jogos de dentro da Leitura")
check(c.get("/api/busca?em=jogos&q=oculto").get_json()["total"] == 0, "jogos ocultos não aparecem")
check(c.get("/api/busca?em=jogos&q=c").get_json()["total"] == 0, "uma letra só não procura")

print("Ícone perto do relógio")
EXT = {"Origin": "chrome-extension://abcdefghijklmnop", "X-Estante-Extensao": "1"}
c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://asurascans.com/comics/solo-leveling-059befe1/chapter/108",
                                                     "titulo": "Solo Leveling Chapter 108", "capitulo": 108,
                                                     "proximo": "https://asurascans.com/comics/solo-leveling-059befe1/chapter/109"})
a = app.atalhos_bandeja()
check([g["nome"] for g in a["jogos"]] == ["Hollow Knight", "Celeste"], "Jogar de novo: os últimos jogados, sem os ocultos")
check(len(a["series"]) == 1 and a["series"][0]["nome"] == "Solo Leveling" and a["series"][0]["rotulo"] == "cap. 109",
      "Continuar lendo: a série lida por último, com o próximo capítulo")
antes = len(sem_janelas.ABERTOS)
check(app.abrir_atalho("serie", a["series"][0]["id"]) and sem_janelas.ABERTOS[antes:] and "chapter/109" in sem_janelas.ABERTOS[-1],
      "clicar abre o capítulo na janela de leitura")
check(app.abrir_atalho("serie", "nao-existe") is False, "série sem site: abre a Estante no lugar")

print("Direção de leitura por série")
sid = a["series"][0]["id"]
r = c.patch(f"/api/leitura/{sid}", json={"modo_leitor": "rtl"})
check(r.status_code == 200 and leitura.achar(leitura._load(), sid)["modo_leitor"] == "rtl", "a série guarda o jeito de ler")
c.patch(f"/api/leitura/{sid}", json={"modo_leitor": "de-lado"})
check(leitura.achar(leitura._load(), sid)["modo_leitor"] == "rtl", "valor estranho é ignorado")

print("One-shot numerado 0")
d = leitura._load()
o = leitura.nova_serie("Oneshot")
o.update(status="Completa", ultimo_lido=0.0, ultimo_disponivel=1.0)
o["por_site"] = {"comix": {"slug": "x1-oneshot", "caps": {"0": "/title/x1-oneshot/1-chapter-0"}, "ultimo": 0.0}}
d["series"].append(o)
leitura._save(d)
check(leitura.proximo_capitulo(leitura.achar(leitura._load(), o["id"]))["existe"] is False,
      "série completa sem o capítulo seguinte em nenhum site: está em dia (o MangaUpdates conta o one-shot como 1)")
d = leitura._load()
leitura.achar(d, o["id"])["status"] = "Em andamento"
leitura._save(d)
check(leitura.proximo_capitulo(leitura.achar(leitura._load(), o["id"]))["existe"] is True, "em andamento, o próximo continua esperado")

print("Sites na lista do lado")
d = leitura._load()
o = leitura.achar(d, o["id"])
o["site"] = "asura"   # o site antigo da série é a Asura, mas o preferido (Comix) também tem
o["por_site"]["asura"] = {"slug": "oneshot", "caps": {}, "ultimo": 0.0}
leitura._save(d)
c.post("/api/leitura/sites", json={"sites": c.get("/api/leitura/sites").get_json()["sites"], "preferido": "comix"})
leitura._pref["quando"] = 0
so = c.get("/api/leitura").get_json()["series"]
so = next(x for x in so if x["id"] == o["id"])
check(so["site_principal"] == "comix" and so["site_nome"] == "Comix", "a série mostra o site preferido, com o nome dele")

print("Tela")
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8790, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
toc.letra = lambda f: {"estado": "achou", "linhas": [[i * 5.0, f"linha {i}"] for i in range(8)], "texto": ""}
painel(sessao(SPOT, "Música A", "Artista A", album="Disco", pos=1), sessao(EDGE, "Vídeo B", "Canal B", status="pausado"))
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8790/")
    pg.wait_for_selector("#tocando .tfontes")
    check(pg.locator("#tocando .tfontes button").count() == 2, "a faixa mostra as duas fontes para escolher")
    pg.click("#tocando .tfontes button:has-text('Edge')")
    pg.wait_for_selector("#tocando .tfontes button.on:has-text('Edge')")
    check(toc._preferida["app"] == EDGE, "clicar escolhe a fonte")
    pg.click("#tocando .tfontes button:has-text('Automático')")
    pg.wait_for_selector("#tocando .tfontes button.on:has-text('Spotify')")
    pg.screenshot(path=str(OUT / "conforto_fontes.png"))
    pg.click("#tocando .tq")
    pg.wait_for_selector("#tlLetra.pula p")
    pg.click("#tlLetra p:has-text('linha 4')")
    pg.wait_for_timeout(400)
    check(COMANDOS[-1] == (SPOT, "posicao", 20.0), "clicar na linha 4 da letra pula para 0:20")
    check(pg.locator("#tlLetra p.on").inner_text() == "linha 4", "e a linha fica destacada")
    pg.screenshot(path=str(OUT / "conforto_letra.png"))
    pg.keyboard.press("Escape")

    # busca única
    pg.fill("#q", "level")
    pg.wait_for_selector("#outraBusca.show .ob")
    check("Solo Leveling" in pg.inner_text("#outraBusca"), "buscando nos Jogos, aparece a série da Leitura numa faixa")
    pg.screenshot(path=str(OUT / "conforto_busca.png"))
    pg.click("#outraBusca .ob")
    pg.wait_for_selector("#drawer.show")
    check(pg.evaluate("S.estante") == "leitura" and "Solo Leveling" in pg.inner_text("#drawer"), "clicar troca para a Leitura e abre a série")
    pg.fill("#q", "")
    pg.dispatch_event("#q", "input")
    pg.wait_for_timeout(400)
    check(not pg.is_visible("#outraBusca"), "apagando a busca, a faixa some")

    # sites na lista do lado: cada site com o nome certo, e a série conta em todos onde está
    pg.evaluate("closeDrawer(); trocarEstante('leitura')")
    pg.wait_for_timeout(1200)
    sites = pg.evaluate("""[...document.querySelectorAll('#nav .item')].filter(b => b.getAttribute('onclick').startsWith("go('site'"))
        .map(b => b.childNodes[1].textContent + '=' + b.querySelector('.n').textContent)""")
    check(sites == ["Asura Scans=2", "Comix=1", "Sem site=2"], "sites na lista do lado, sem nomes repetidos: " + str(sites))
    pg.evaluate("go('site', 'asura')")
    pg.wait_for_timeout(300)
    check(pg.locator("#content .grid .card").count() == 2, "escolhendo a Asura, aparecem as duas séries que estão nela")
    pg.screenshot(path=str(OUT / "conforto_sites.png"))

    # vezes jogadas no painel do jogo
    lib = app.get_lib()
    app.find_game(lib, g1["id"])["sessoes"] = [[int(time.time() - 3600), 1500], [int(time.time() - 90000), 700]]
    app.save_lib(lib)
    pg.evaluate("closeDrawer(); trocarEstante('jogos')")
    pg.wait_for_timeout(1200)
    pg.evaluate(f"openDrawer('{g1['id']}')")
    pg.wait_for_selector("#drawer .sessoes li")
    check(pg.locator("#drawer .sessoes li").count() == 2 and "Nos últimos 7 dias" in pg.inner_text("#drawer"),
          "o painel do jogo mostra as últimas vezes jogadas e o tempo da semana")
    pg.screenshot(path=str(OUT / "conforto_sessoes.png"))
    check(not erros, "sem erros na página: " + "; ".join(erros))
    b.close()
srv.shutdown()
print(f"\nTudo certo: {ok} verificações.")

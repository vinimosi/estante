"""Etapa 10, coisas novas: situação e notas, sorteio, exportar a lista em XML, buscar de novo no MangaUpdates,
estatísticas, histórico de músicas e modo TV (com controle de mentira). Rode: python3 testar_novas.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import io
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

S = Path(_SAIDA)
T = S / "novas"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402  (nada abre de verdade no Windows)
import app  # noqa: E402
import estatisticas  # noqa: E402
import leitura  # noqa: E402
import lojas  # noqa: E402
import tocando as toc  # noqa: E402
from PIL import Image  # noqa: E402

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


def exe(n):  # o jogo precisa existir no PC de mentira, senão sai da estante quando a tela abre
    p = T / "jogos" / n / "jogo.exe"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"MZ")
    return str(p)


print("Situação e notas")
lib = app.get_lib()
g1, g2, g3 = (app.new_game(n, exe(n)) for n in ("Hollow Knight", "Celeste", "Hades"))
agora = time.time()
g1["sessoes"] = [[int(agora - 86400), 1800], [int(agora - 3600), 600], [int(agora - 20 * 86400), 3000]]
g1["playtime"], g1["last_played"] = 9000, agora - 3000
g2["playtime"] = 1200
lib["games"] += [g1, g2, g3]
app.save_lib(lib)
r = c.patch(f"/api/games/{g1['id']}", json={"situacao": "jogando", "nota": "Parei no chefe do pântano."})
check(r.status_code == 200 and r.get_json()["situacao"] == "jogando" and r.get_json()["nota"].startswith("Parei"),
      "o jogo guarda a sua situação e a nota")
c.patch(f"/api/games/{g1['id']}", json={"situacao": "dormindo"})
check(app.find_game(app.get_lib(), g1["id"])["situacao"] == "jogando", "situação estranha é ignorada")
c.patch(f"/api/games/{g2['id']}", json={"situacao": "zerei", "nota": "x" * 9000})
check(len(app.find_game(app.get_lib(), g2["id"])["nota"]) == 5000, "nota muito grande é cortada")
velho = {k: v for k, v in app.new_game("Antigo", exe("Antigo")).items() if k not in ("situacao", "nota")}
lib = app.get_lib()
lib["games"].append(velho)
app.save_lib(lib)
check(app.find_game(app.get_lib(), velho["id"]).get("situacao") == "", "jogo guardado antes ganha a situação vazia sozinho")
c.patch(f"/api/games/{velho['id']}", json={"nota": "Do antigo."})
app.juntar([g1["id"], velho["id"]], g1["id"])
j = app.find_game(app.get_lib(), g1["id"])
check(j["situacao"] == "jogando" and "Parei" in j["nota"] and "Do antigo." in j["nota"], "juntar dois jogos junta as notas")

d = leitura._load()
s1, s2, s3 = (leitura.nova_serie(n) for n in ("Solo Leveling", "Omniscient Reader", "Quadrinho do PC"))
s1.update(mu_id=1, ultimo_lido=110.0, lista_anilist="Lendo", mal_id=121496, capa_de="mangaupdates", cover=None)
s2.update(mu_id=2, ultimo_lido=50.5, lista_anilist="Pausado")
s3["local"] = {"pasta": "x", "caps": [], "paginas": {}}
d["series"] += [s1, s2, s3]
d["leituras"] = [{"s": s1["id"], "c": 100 + i, "t": agora - i * 3600, "site": "comix"} for i in range(5)] + \
                [{"s": s2["id"], "c": 50, "t": agora - 10 * 86400, "site": "comix"}]
leitura._save(d)
r = c.patch(f"/api/leitura/{s1['id']}", json={"nota": "Reler o arco do Japão."})
check(r.status_code == 200 and r.get_json()["nota"] == "Reler o arco do Japão.", "as séries também guardam nota")

print("Exportar a lista em XML")
r = c.get("/api/leitura/exportar")
check(r.status_code == 200 and "attachment" in r.headers["Content-Disposition"] and ".xml" in r.headers["Content-Disposition"],
      "baixa um arquivo .xml")
lida = leitura.ler_lista_xml(r.data)
check([x["titulo"] for x in lida] == ["Omniscient Reader", "Solo Leveling"], "quadrinhos do PC ficam de fora")
check(lida[1] == {"mal": 121496, "titulo": "Solo Leveling", "cap": 110.0, "lista": "Lendo"}
      and lida[0]["cap"] == 50.5 and lida[0]["lista"] == "Pausado",
      "a importação da Estante lê de volta o capítulo, a lista e o número do MyAnimeList")

print("Buscar de novo no MangaUpdates")
CAPAS, PEDIDOS = {1: "https://cdn.mangaupdates.com/image/1-a.jpg", 2: "https://cdn.mangaupdates.com/image/2.jpg"}, []


def http_falso(url, dados=None, timeout=20):
    PEDIDOS.append(url)
    sid = int(url.rstrip("/").split("/")[-1])
    return {"series_id": sid, "title": {1: "Na Honjaman Level Up", 2: "ORV"}[sid], "latest_chapter": 200,
            "description": f"História nova {sid}.", "image": {"url": {"original": CAPAS[sid]}}, "type": "Manhwa",
            "year": "2018", "genres": [{"genre": "Action"}], "status": "Complete", "completed": True,
            "authors": [{"name": "Autor Novo", "type": "Author"}], "associated": [{"title": f"Outro nome {sid}"}]}


BAIXADAS = []


def capa_falsa(sid, url, referer=None):
    BAIXADAS.append(url)
    b = io.BytesIO()
    Image.new("RGB", (30, 45), (len(BAIXADAS) * 40 % 255, 80, 120)).save(b, "JPEG")
    return leitura.guardar_capa_bytes(sid, b.getvalue(), ".jpg")


leitura._http_json = http_falso
leitura.guardar_capa = capa_falsa
r = c.post(f"/api/leitura/{s1['id']}/atualizar-mu")
x = r.get_json()
check(r.status_code == 200 and x["description"] == "História nova 1." and x["autor"] == "Autor Novo" and x["status"] == "Completa"
      and "Outro nome 1" in x["titulos_alt"], "traz de novo descrição, autor, situação e nomes alternativos")
check(x["name"] == "Solo Leveling" and x["ultimo_lido"] == 110.0, "o nome e o capítulo lido não mudam")
check(BAIXADAS == [CAPAS[1]] and x["cover_url"], "série sem capa ganha a do MangaUpdates")
capa1 = x["cover_url"]
c.post(f"/api/leitura/{s1['id']}/atualizar-mu")
check(len(BAIXADAS) == 1, "a mesma capa não é baixada de novo")
CAPAS[1] = "https://cdn.mangaupdates.com/image/1-b.jpg"
x = c.post(f"/api/leitura/{s1['id']}/atualizar-mu").get_json()
check(BAIXADAS[-1] == CAPAS[1] and x["cover_url"] != capa1, "capa nova no MangaUpdates: troca")
d = leitura._load()
leitura.achar(d, s2["id"]).update(capa_manual=True, cover="minha.jpg")
leitura._save(d)
(app.DATA / "covers").mkdir(exist_ok=True)
leitura.atualizar_todas_do_mu(intervalo=0)
for _ in range(100):
    if not leitura._atualizando["ativo"]:
        break
    time.sleep(0.05)
st = c.get("/api/leitura/atualizar-mu").get_json()
check(not st["ativo"] and st["feitos"] == 2 and st["total"] == 2 and st["erros"] == 0, "todas de uma vez: as duas ligadas ao MangaUpdates")
s2v = leitura.achar(leitura._load(), s2["id"])
check(s2v["cover"] == "minha.jpg" and s2v["description"] == "História nova 2." and CAPAS[2] not in BAIXADAS,
      "a capa escolhida por você fica")
r = c.post(f"/api/leitura/{s3['id']}/atualizar-mu")
check(r.status_code == 400 and "não está ligada" in r.get_json()["error"], "série sem MangaUpdates: explica")

print("Estatísticas")
e = c.get("/api/estatisticas").get_json()
check(e["semana"] == 2400 and e["mes"] == 5400 and e["total"] == 10200 and e["jogados"] == 2,
      "jogos: 40 min na semana, 1h30 no mês, total de todos")
esta = sum(d for t, d in g1["sessoes"] if t >= estatisticas.inicio_da_semana(time.time()))  # perto da meia-noite de segunda muda
check(len(e["por_semana"]) == 12 and sum(x["valor"] for x in e["por_semana"]) == 5400 and e["por_semana"][-1]["valor"] == esta,
      "12 semanas, com o tempo de cada vez jogada na semana certa")
check([t["nome"] for t in e["top"]] == ["Hollow Knight", "Celeste"] and e["situacoes"] == {"jogando": 1, "zerei": 1},
      "os mais jogados e a contagem das situações")
e = c.get("/api/estatisticas?em=leitura").get_json()
check(e["semana"] == 5 and e["mes"] == 6 and e["capitulos"] == 160 and e["comecadas"] == 2 and e["series"] == 3,
      "leitura: capítulos da semana, do mês e lidos ao todo")
check(e["top"][0]["nome"] == "Solo Leveling" and e["top"][0]["valor"] == 5 and e["listas"] == {"Lendo": 1, "Pausado": 1},
      "as mais lidas e as listas")
seg = estatisticas.inicio_da_semana(time.mktime((2026, 11, 4, 15, 0, 0, 0, 0, -1)))  # uma quarta-feira
check(time.localtime(seg).tm_wday == 0 and time.localtime(seg).tm_mday == 2 and time.localtime(seg).tm_hour == 0,
      "a semana começa na segunda-feira, 0h")

print("Histórico de músicas")
SPOT, EDGE = "SpotifyAB.SpotifyMusic_x!Spotify", "MSEdge"


def sessao(app_id, titulo, artista, status="tocando", dur=200.0, album="Disco"):
    return {"app": app_id, "titulo": titulo, "artista": artista, "album": album, "status": status, "posicao": 5.0,
            "duracao": dur, "atualizado": time.time(), "atual": False, "botoes": {}}


a = sessao(SPOT, "Música A", "Artista A")
toc._visto[SPOT] = agora - 10
toc.anotar_historico([a], agora)
check(c.get("/api/tocando/historico").get_json()["hoje"] == [], "com menos de 30 s tocando, ainda não entra")
toc.anotar_historico([a], agora + 25)
toc.anotar_historico([a], agora + 40)
h = c.get("/api/tocando/historico").get_json()
check(len(h["hoje"]) == 1 and h["hoje"][0]["titulo"] == "Música A" and h["hoje"][0]["fonte"] == "Spotify", "depois de 30 s, entra uma vez só")
toc._visto[SPOT] = agora + 100  # pausou e voltou a tocar
toc.anotar_historico([a], agora + 140)
check(len(c.get("/api/tocando/historico").get_json()["hoje"]) == 1, "pausar e voltar logo depois não conta de novo")
toc._visto[SPOT] = agora + 200
toc.anotar_historico([sessao(SPOT, "Compre já", "", album="", dur=30)], agora + 240)
toc._visto[EDGE] = agora + 200
toc.anotar_historico([sessao(EDGE, "Clipe B", "Artista A", album="")], agora + 240, )
h = c.get("/api/tocando/historico").get_json()
check([x["titulo"] for x in h["hoje"]] == ["Clipe B", "Música A"] and h["semana"] == 2, "propaganda não entra; o mais novo vem primeiro")
check(h["artistas"] == [{"nome": "Artista A", "vezes": 2}] and h["minutos_semana"] == 7, "resumo da semana por artista")
c.post("/api/tocando/historico/limpar")
check(c.get("/api/tocando/historico").get_json()["semana"] == 0, "dá para apagar o histórico")
toc._visto[EDGE] = agora + 300
toc.anotar_historico([sessao(EDGE, "Clipe B", "Artista A", album="")], agora + 340)

print("Tela")
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8789, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
toc.disponivel = lambda: (False, "teste")
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8789/")
    pg.evaluate("trocarEstante('jogos')")
    pg.wait_for_selector("#content .grid .card")
    check("sua situação" in pg.inner_text("#nav").lower() and "Jogando" in pg.inner_text("#nav"), "a lista do lado mostra as situações usadas")
    pg.evaluate("go('situacao', 'zerei')")
    check(pg.locator("#content .grid .card").count() == 1 and "Zerei" in pg.inner_text("#content .head"), "filtrar por situação")
    pg.evaluate("go('all')")
    pg.evaluate(f"openDrawer('{g3['id']}')")
    pg.click("#drawer .situacoes button:has-text('Quero jogar')")
    pg.wait_for_selector("#drawer .situacoes button.on:has-text('Quero jogar')")
    check(app.find_game(app.get_lib(), g3["id"])["situacao"] == "quero", "escolher a situação no painel do jogo")
    pg.fill("#notaIn", "Comprar a trilha sonora.")
    pg.click("#drawer h2")
    pg.wait_for_timeout(400)
    check(app.find_game(app.get_lib(), g3["id"])["nota"] == "Comprar a trilha sonora.", "a nota é guardada ao sair da caixa")
    pg.screenshot(path=str(OUT / "novas_situacao.png"))
    pg.evaluate("closeDrawer()")

    pg.click("#sortearBtn")
    pg.wait_for_selector("#drawer.show")
    check(pg.evaluate("S.open") in {g1["id"], g2["id"], g3["id"]}, "sortear abre um dos jogos da tela")
    pg.evaluate("closeDrawer(); go('situacao', 'zerei')")
    pg.click("#sortearBtn")
    check(pg.evaluate("S.open") == g2["id"], "o sorteio respeita o filtro")
    pg.evaluate("closeDrawer(); go('stats')")
    pg.wait_for_selector("#content .barras .barra")
    check(pg.locator("#content .barra").count() == 12 and "Hollow Knight" in pg.inner_text("#content .topo"),
          "estatísticas dos jogos: barras das semanas e os mais jogados")
    pg.screenshot(path=str(OUT / "novas_estatisticas.png"))

    # modo TV, pelo teclado
    pg.evaluate("go('all')")
    pg.click("#tvBtn")
    pg.wait_for_selector("#tv.show .tv-card.on")
    n = pg.locator("#tv .tv-card").count()
    check(n == 3 and pg.evaluate("TV.i") == 0, "o modo TV mostra os jogos da tela, com o primeiro escolhido")
    pg.keyboard.press("ArrowRight")
    check(pg.evaluate("TV.i") == 1 and pg.get_attribute("#tv .tv-card.on", "data-i") == "1", "seta para a direita anda um")
    pg.screenshot(path=str(OUT / "novas_tv.png"))
    pg.keyboard.press("Escape")
    check(not pg.is_visible("#tv"), "Esc sai do modo TV")

    # modo TV, com um controle de mentira
    pg.evaluate("""() => {
        window.PAD = {index: 0, connected: true, axes: [0, 0, 0, 0], buttons: Array.from({length: 17}, () => ({pressed: false, value: 0}))};
        navigator.getGamepads = () => [window.PAD];
        window.apertar = async i => { PAD.buttons[i].pressed = true; await new Promise(r => setTimeout(r, 300));
                                      PAD.buttons[i].pressed = false; await new Promise(r => setTimeout(r, 300)); };
        window.dispatchEvent(new Event('gamepadconnected'));
    }""")
    pg.evaluate("apertar(9)")
    pg.wait_for_selector("#tv.show")
    check(True, "Start no controle abre o modo TV")
    pg.evaluate("apertar(15)")
    check(pg.evaluate("TV.i") == 1, "direcional para a direita anda um")
    pg.evaluate("() => { PAD.axes[0] = 1; }")
    pg.wait_for_timeout(700)
    pg.evaluate("() => { PAD.axes[0] = 0; }")
    check(pg.evaluate("TV.i") == 2, "segurar a alavanca continua andando (até o último)")
    pg.evaluate("apertar(5)")
    pg.wait_for_selector("#tv.show .tv-card")
    pg.wait_for_timeout(300)
    check(pg.evaluate("S.estante") == "leitura" and "Leitura" in pg.inner_text("#tv h1"), "RB troca para a Leitura")
    pg.evaluate("apertar(1)")
    check(not pg.is_visible("#tv"), "B sai do modo TV")

    pg.evaluate("go('stats')")
    pg.wait_for_selector("#content .barras .barra")
    check("Solo Leveling" in pg.inner_text("#content .topo") and "Pausado" in pg.inner_text("#content .est"),
          "estatísticas da Leitura: as mais lidas e as listas")
    pg.evaluate(f"go('all'); openDrawer('{s1['id']}')")
    pg.wait_for_selector("#muDeNovo")
    check(pg.input_value("#notaIn") == "Reler o arco do Japão.", "a nota aparece no painel da série")
    pg.click("#muDeNovo")
    pg.wait_for_selector("#muDeNovo:not([disabled])")
    check(PEDIDOS[-1].endswith("/series/1"), "o botão do painel busca a série de novo no MangaUpdates")
    pg.evaluate("closeDrawer()")

    pg.evaluate("openHistoricoMusicas()")
    pg.wait_for_selector(".hist-mus")
    check("Clipe B" in pg.inner_text(".hist-mus") and "Artista A" in pg.inner_text(".hist-mus"), "a tela do que tocou hoje")
    pg.screenshot(path=str(OUT / "novas_musicas.png"))
    pg.evaluate("closeModal(); openSettings('leitura')")
    pg.wait_for_selector("#exportarXml")
    with pg.expect_download() as dl:
        pg.click("#exportarXml")
    check(dl.value.suggested_filename.startswith("estante-leitura-") and dl.value.suggested_filename.endswith(".xml"),
          "o botão Exportar baixa o arquivo")
    check(not erros, "sem erros na página: " + "; ".join(erros))
    b.close()
srv.shutdown()
print(f"\nTudo certo: {ok} verificações.")

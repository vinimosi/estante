"""Tocando agora: painel de mídia do Windows, limpeza dos nomes do YouTube, letras do LRCLIB guardadas,
botões, propagandas e o botão do Genius. Com painel, LRCLIB e Genius de mentira. Rode: python3 testar_tocando.py"""
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
import urllib.error
import urllib.parse
from pathlib import Path

S = Path(_SAIDA)
T = S / "tocando"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402  (nada abre de verdade no Windows)
import app  # noqa: E402
import tocando as toc  # noqa: E402

c = app.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


# ---- painel de mídia do Windows de mentira
PAINEL, COMANDOS, LEITURAS = [], [], [0]
def _png():
    import io
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (300, 300), (40, 70, 110))
    ImageDraw.Draw(im).ellipse((60, 60, 240, 240), fill=(229, 160, 13))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


PNG = _png()


def sessao(app_id, titulo, artista, status="tocando", pos=0.0, dur=200.0, atual=False, album="", atraso=0.0):
    return {"app": app_id, "titulo": titulo, "artista": artista, "album": album, "status": status, "posicao": pos,
            "duracao": dur, "atualizado": time.time() - atraso, "atual": atual,
            "botoes": {"tocar": status != "tocando", "pausar": status == "tocando", "anterior": True, "proximo": True}}


def ler_falso(querem):
    LEITURAS[0] += 1
    out = []
    for s in PAINEL:
        d = json.loads(json.dumps(s))
        if toc.chave(d) in querem:
            d["capa"] = PNG
        out.append(d)
    return out


ACEITA = [True]


def comando_falso(app_id, acao, segundos=0.0):
    COMANDOS.append((app_id, acao) if acao != "posicao" else (app_id, acao, segundos))
    return ACEITA[0]


def painel(*sessoes):
    PAINEL[:] = list(sessoes)
    toc._ultima["quando"] = 0.0


toc._ler_sessoes = ler_falso
toc._comando = comando_falso
toc.disponivel = lambda: (True, "")
toc.ESPERA_CAPA = 0
toc.ESPACO = 0

# ---- LRCLIB e Genius de mentira
SINC = "\n".join(f"[00:{i * 5:02d}.00] linha {i}" for i in range(8))
LRC = {  # (música, artista) -> resultado do /api/get
    ("never gonna give you up", "rick astley"): {"id": 1, "trackName": "Never Gonna Give You Up", "artistName": "Rick Astley",
                                                 "duration": 213, "plainLyrics": "\n".join(f"linha {i}" for i in range(8)), "syncedLyrics": SINC},
    ("vandalizada", "fulano"): {"id": 2, "trackName": "Vandalizada", "artistName": "Fulano", "duration": 180,
                                "plainLyrics": "probe", "syncedLyrics": "[00:00.00]probe"},
    ("so instrumental", "banda"): {"id": 3, "trackName": "Só Instrumental", "artistName": "Banda", "duration": 150, "instrumental": True},
}
BUSCA = {
    "vandalizada": [{"id": 4, "trackName": "Vandalizada", "artistName": "Fulano", "duration": 181,
                     "plainLyrics": "a\nb\nc\nd\ne", "syncedLyrics": "[00:01.00]a\n[00:02.00]b\n[00:03.00]c\n[00:04.00]d\n[00:05.00]e"},
                    {"id": 5, "trackName": "Outra Coisa", "artistName": "Fulano", "duration": 180, "plainLyrics": "x\ny\nz\nw"}],
    "ao vivo longa": [{"id": 6, "trackName": "Ao Vivo Longa", "artistName": "Cantora", "duration": 240,
                       "plainLyrics": "um\ndois\ntres\nquatro", "syncedLyrics": "[00:01.00]um\n[00:02.00]dois\n[00:03.00]tres\n[00:04.00]quatro"}],
}
PEDIDOS, ERRO_LRC = [], [None]
GENIUS_KEY = "genius-chave-boa-1234"
HITS = [{"type": "song", "result": {"title": "Envolver", "url": "https://genius.com/Outra-pessoa-envolver-lyrics", "primary_artist": {"name": "Outra Pessoa"}}},
        {"type": "song", "result": {"title": "Envolver", "url": "https://genius.com/Anitta-envolver-lyrics", "primary_artist": {"name": "Anitta"}}}]


def _erro(cod, cab=None):
    return urllib.error.HTTPError("https://falso", cod, "erro", cab or {}, None)


def http_falso(url, headers=None, espera=15):
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    PEDIDOS.append((u.netloc + u.path, q, dict(headers or {})))
    if u.netloc == "api.genius.com":
        if (headers or {}).get("Authorization") != "Bearer " + GENIUS_KEY:
            raise _erro(401)
        return {"response": {"hits": HITS}}
    if ERRO_LRC[0]:
        raise _erro(*ERRO_LRC[0])
    if u.path.endswith("/get"):
        r = LRC.get((toc.normal(q["track_name"]), toc.normal(q["artist_name"])))
        if not r or ("duration" in q and abs(r["duration"] - float(q["duration"])) > 2):
            raise _erro(404)
        return r
    return BUSCA.get(toc.normal(q.get("track_name") or q.get("q", "")), [])


toc._http_json = http_falso
H_TEST = {}


def lrclib():
    return [p for p in PEDIDOS if p[0].startswith("lrclib.net")]


print("Nomes que vêm do YouTube")
for antes, depois in [
    ("Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)", "Rick Astley - Never Gonna Give You Up"),
    ("Nome da Música [Lyric Video]", "Nome da Música"),
    ("Bohemian Rhapsody (Live At Wembley Stadium / July 1986)", "Bohemian Rhapsody (Live At Wembley Stadium / July 1986)"),
    ("MC Fulano - Música (Videoclipe Oficial) | KondZilla", "MC Fulano - Música"),
    ("Música Boa (Ao Vivo)", "Música Boa (Ao Vivo)"),
    ("Here Comes The Sun - Remastered 2009", "Here Comes The Sun"),
    ("Artista - Música (Letra/Legendado) #rock #2024", "Artista - Música"),
    ("Song Part 2", "Song Part 2"),
]:
    check(toc.limpar_titulo(antes) == depois, f"{antes!r} vira {depois!r} (deu {toc.limpar_titulo(antes)!r})")
check(toc.sem_feat("Despacito ft. Daddy Yankee") == "Despacito" and toc.sem_feat("Envolver (feat. Fulano)") == "Envolver",
      "participação especial sai do nome para procurar")
check(toc.limpar_canal("Rick Astley - Topic") == "Rick Astley" and toc.limpar_canal("RickAstleyVEVO") == "RickAstley"
      and toc.limpar_canal("Queen Official") == "Queen" and toc.limpar_canal("Mtv") == "Mtv", "o nome do canal fica só com o artista")
check(toc.separar("Anitta - Envolver") == ("Anitta", "Envolver") and toc.separar("AC/DC - Thunderstruck") == ("AC/DC", "Thunderstruck")
      and toc.separar("Jay-Z - Song") == ("Jay-Z", "Song") and toc.separar("Sem Traço") is None, "'Artista - Música' é separado certo")
check(toc.artista_parecido("Queen", "queen") and toc.artista_parecido("Anitta e Pedro Sampaio", "Pedro Sampaio")
      and not toc.artista_parecido("Queen", "Muse"), "artistas parecidos (inclusive em parceria) são reconhecidos")
cands = toc.candidatos({"app": "MSEdge", "titulo": "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)", "artista": "Rick Astley", "album": ""})
check(cands[0][0].startswith("Rick Astley - Never") and cands[1] == ("Never Gonna Give You Up", "Rick Astley", ""),
      "procura primeiro o nome do jeito que veio e depois o nome limpo")

print("Qual música mostrar")
painel()
r = c.get("/api/tocando").get_json()
check(r["ligado"] and r["disponivel"] and r["faixa"] is None, "nada tocando: a faixa fica escondida")
painel(sessao("SpotifyAB.SpotifyMusic_x!Spotify", "Silver Soul", "Beach House", status="pausado", pos=30, dur=298, atual=True),
       sessao("MSEdge", "Bohemian Rhapsody (Live At Wembley Stadium / July 1986)", "Queen", pos=5, dur=359))
f = c.get("/api/tocando").get_json()["faixa"]
check(f["fonte"] == "Edge" and f["titulo"].startswith("Bohemian") and f["tocando"], "a que está tocando vence a pausada")
painel(sessao("SpotifyAB.SpotifyMusic_x!Spotify", "Silver Soul", "Beach House", pos=30, dur=298, atual=True),
       sessao("MSEdge", "Bohemian Rhapsody (Live At Wembley Stadium / July 1986)", "Queen", pos=5, dur=359))
f = c.get("/api/tocando").get_json()["faixa"]
check(f["fonte"] == "Spotify" and f["artista"] == "Beach House", "com duas tocando, vale a que o Windows mostra")
painel(sessao("SpotifyAB.SpotifyMusic_x!Spotify", "Silver Soul", "Beach House", status="pausado", pos=30, dur=298),
       sessao("MSEdge", "Bohemian Rhapsody (Live At Wembley Stadium / July 1986)", "Queen", status="pausado", pos=5, dur=359, atual=True))
f = c.get("/api/tocando").get_json()["faixa"]
check(f["fonte"] == "Spotify", "com as duas pausadas, vale a que tocou por último")

print("Posição na música")
agora = time.time()
s = sessao("x", "t", "a", pos=20, dur=100, atraso=10)
check(abs(toc.posicao_agora(s, agora) - 30) < 0.5, "tocando: a posição anda sozinha entre um aviso e outro do Windows")
s["status"] = "pausado"
check(toc.posicao_agora(s, agora) == 20, "pausada: a posição fica parada")
s.update(status="tocando", atualizado=agora - 500)
check(toc.posicao_agora(s, agora) == 100, "nunca passa do fim da música")

print("Capa")
painel(sessao("SpotifyAB.SpotifyMusic_x!Spotify", "Música Com Capa", "Alguém", pos=1, dur=200))
f1 = c.get("/api/tocando").get_json()["faixa"]
toc._ultima["quando"] = 0.0
f2 = c.get("/api/tocando").get_json()["faixa"]
check(f1["capa"] == "" and f2["capa"].startswith("/api/tocando/capa/"), "a capa é lida depois que a música assenta (não pega a da anterior)")
rc = c.get(f2["capa"])
check(rc.status_code == 200 and rc.data == PNG and rc.mimetype == "image/png", "a capa vem do próprio Windows, como imagem")
antes = LEITURAS[0]
for _ in range(5):
    c.get("/api/tocando")
check(LEITURAS[0] - antes <= 1, "pedidos seguidos não leem o painel toda hora")

print("Botões")
painel(sessao("SpotifyAB.SpotifyMusic_x!Spotify", "Silver Soul", "Beach House", pos=30, dur=298))
r = c.post("/api/tocando/controle", json={"acao": "pausar", "app": "SpotifyAB.SpotifyMusic_x!Spotify"})
check(r.status_code == 200 and COMANDOS[-1] == ("SpotifyAB.SpotifyMusic_x!Spotify", "pausar"), "pausar vai para o programa certo")
for acao in ("tocar", "anterior", "proximo"):
    c.post("/api/tocando/controle", json={"acao": acao})
check([a for _, a in COMANDOS[-3:]] == ["tocar", "anterior", "proximo"], "tocar, anterior e próximo também")
check(c.post("/api/tocando/controle", json={"acao": "apagar"}).status_code == 400, "botão desconhecido é recusado")
check(c.post("/api/tocando/controle", json={"acao": "pausar"}, headers={"Origin": "https://site-qualquer.com"}).status_code == 403,
      "outros sites não conseguem apertar os botões")
ACEITA[0] = False
r = c.post("/api/tocando/controle", json={"acao": "proximo"})
check(r.status_code == 400 and "não aceitou" in r.get_json()["error"], "se o programa não aceita o botão, a Estante avisa")
ACEITA[0] = True

print("Propagandas")
painel(sessao("MSEdge", "Unidos pela velocidade.", "Mercado Livre Brasil", pos=0, dur=6))
f = c.get("/api/tocando").get_json()["faixa"]
n = len(PEDIDOS)
l = c.get(f"/api/tocando/letra/{f['chave']}").get_json()
check(f["anuncio"] and l["estado"] == "sem_busca" and len(PEDIDOS) == n, "propaganda curta no YouTube: nada de procurar letra")
check(toc.e_anuncio(sessao("SpotifyAB.SpotifyMusic_x!Spotify", "Spotify", "")), "propaganda do Spotify (sem artista) também")

print("Letras do LRCLIB")
painel(sessao("MSEdge", "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)", "Rick Astley", pos=12, dur=213.06))
f = c.get("/api/tocando").get_json()["faixa"]
check(f["fonte"] == "Edge" and not f["anuncio"], "vídeo do YouTube no Edge")
del PEDIDOS[:]
l = c.get(f"/api/tocando/letra/{f['chave']}").get_json()
check(l["estado"] == "achou" and l["linhas"][2] == [10.0, "linha 2"] and len(l["linhas"]) == 8, "letra sincronizada, com o tempo de cada linha")
pg = lrclib()
check(pg[0][1]["track_name"].startswith("Rick Astley - Never") and pg[1][1]["track_name"] == "Never Gonna Give You Up"
      and pg[1][1]["duration"] == "213", "procura pelo nome, artista e duração; com o nome sujo não achou e tentou o limpo")
check(all(p[2] == {} for p in pg) and toc.AGENTE.startswith("Estante"), "o pedido se identifica como Estante")
check(len(list((T / "dados" / "letras").glob("*.json"))) == 1, "a letra fica guardada na pasta de dados")
n = len(PEDIDOS)
l2 = c.get(f"/api/tocando/letra/{f['chave']}").get_json()
check(l2["estado"] == "achou" and len(PEDIDOS) == n, "da segunda vez vem da pasta de dados, sem pedir de novo")

painel(sessao("SpotifyAB.SpotifyMusic_x!Spotify", "Vandalizada", "Fulano", pos=1, dur=180))
f = c.get("/api/tocando").get_json()["faixa"]
l = c.get(f"/api/tocando/letra/{f['chave']}").get_json()
check(l["estado"] == "achou" and l["texto"].startswith("a\nb") and l["linhas"][0] == [1.0, "a"],
      "letra de uma linha só ('probe') é descartada e a busca acha a de verdade, do mesmo artista")

painel(sessao("SpotifyAB.SpotifyMusic_x!Spotify", "Ao Vivo Longa", "Cantora", pos=1, dur=300))
f = c.get("/api/tocando").get_json()["faixa"]
l = c.get(f"/api/tocando/letra/{f['chave']}").get_json()
check(l["estado"] == "achou" and l["linhas"] is None and l["texto"].startswith("um"),
      "versão com outra duração: a letra aparece inteira, sem tempo (não fica fora do ritmo)")

painel(sessao("SpotifyAB.SpotifyMusic_x!Spotify", "Só Instrumental", "Banda", pos=1, dur=150))
f = c.get("/api/tocando").get_json()["faixa"]
check(c.get(f"/api/tocando/letra/{f['chave']}").get_json()["estado"] == "instrumental", "música instrumental é avisada")

painel(sessao("MSEdge", "Anitta - Envolver [Official Music Video]", "Anitta", pos=1, dur=194))
f = c.get("/api/tocando").get_json()["faixa"]
ERRO_LRC[0] = (503,)
l = c.get(f"/api/tocando/letra/{f['chave']}").get_json()
check(l["estado"] == "erro" and "internet" in l["erro"], "LRCLIB fora do ar: avisa com calma")
ERRO_LRC[0] = None
n = len(lrclib())
l = c.get(f"/api/tocando/letra/{f['chave']}").get_json()
check(l["estado"] == "nao_achou" and len(lrclib()) > n and not l["tem_chave_genius"], "o erro não fica guardado: tenta de novo depois")
n = len(PEDIDOS)
c.get(f"/api/tocando/letra/{f['chave']}")
check(len(PEDIDOS) == n, "'não tem' fica guardado e não pergunta toda hora")

painel(sessao("MSEdge", "Outra Música", "Outro", pos=1, dur=200))
f = c.get("/api/tocando").get_json()["faixa"]
ERRO_LRC[0] = (429, {"Retry-After": "120"})
c.get(f"/api/tocando/letra/{f['chave']}")
ERRO_LRC[0] = None
n = len(PEDIDOS)
l = c.get(f"/api/tocando/letra/{f['chave']}").get_json()
check(l["estado"] == "erro" and len(PEDIDOS) == n, "quando o LRCLIB pede para esperar, a Estante espera")
toc._lrclib["pausa_ate"] = 0

print("Genius")
painel(sessao("MSEdge", "Anitta - Envolver [Official Music Video]", "Anitta", pos=1, dur=194))
f = c.get("/api/tocando").get_json()["faixa"]
del sem_janelas.ABERTOS[:]
r = c.post(f"/api/tocando/genius/{f['chave']}").get_json()
check(not r["pagina"] and sem_janelas.ABERTOS[-1].startswith("https://genius.com/search?q=Envolver+Anitta"),
      "sem chave: abre a busca do Genius com o nome da música (limpo)")
r = c.post("/api/tocando/config", json={"genius_key": "chave-errada"})
check(r.status_code == 400 and "não aceitou" in r.get_json()["error"], "chave errada do Genius: avisa e não guarda")
check(not c.get("/api/tocando/config").get_json()["genius"], "nada foi guardado")
r = c.post("/api/tocando/config", json={"genius_key": GENIUS_KEY})
cfg_t = c.get("/api/tocando/config").get_json()
check(r.status_code == 200 and cfg_t["genius"] and cfg_t["genius_dica"] == "•••• 1234", "chave certa: guardada, e a tela mostra só o fim dela")
check(all(GENIUS_KEY not in json.dumps(c.get(u).get_json()) for u in ("/api/tocando/config", "/api/config", "/api/tocando")),
      "nenhuma rota devolve a chave inteira")
r = c.post(f"/api/tocando/genius/{f['chave']}").get_json()
check(r["pagina"] and sem_janelas.ABERTOS[-1] == "https://genius.com/Anitta-envolver-lyrics",
      "com chave: abre a página certa da música (do mesmo artista, não a primeira da busca)")
n = len(PEDIDOS)
c.post(f"/api/tocando/genius/{f['chave']}")
check(len(PEDIDOS) == n and sem_janelas.ABERTOS[-1] == "https://genius.com/Anitta-envolver-lyrics", "o link fica guardado junto com a letra")
check(c.get(f"/api/tocando/letra/{f['chave']}").get_json()["tem_chave_genius"], "a tela da letra sabe que existe a chave")
check(not any("genius.com" in p[0] and "lyrics" in p[0] for p in PEDIDOS), "a Estante nunca pede a página da letra ao Genius")
c.post("/api/tocando/config", json={"tirar_genius": True})
check(not c.get("/api/tocando/config").get_json()["genius"], "dá para tirar a chave")

print("Ligar e desligar")
c.post("/api/tocando/config", json={"ligado": False})
antes = LEITURAS[0]
toc._ultima["quando"] = 0.0
check(c.get("/api/tocando").get_json() == {"ligado": False} and LEITURAS[0] == antes, "desligado: nem lê o painel")
c.post("/api/tocando/config", json={"ligado": True})
toc.disponivel = lambda: (False, "Falta um componente pequeno do Windows. Abra o Instalar.bat de novo para ele ser instalado.")
r = c.get("/api/tocando").get_json()
check(not r["disponivel"] and "Instalar.bat" in r["motivo"], "sem o componente do Windows: explica o que fazer")
toc.disponivel = lambda: (True, "")
cfg_txt = (T / "dados" / "config.json").read_text("utf-8")
check("senha" not in cfg_txt.lower() and "spotify" not in cfg_txt.lower(), "nada de conta ou senha de serviço no config.json")

print("Tela")
sinc = "\n".join(f"[00:{i * 5:02d}.00] Linha número {i} da música" for i in range(12))
LRC[("silver soul", "beach house")] = {"id": 9, "trackName": "Silver Soul", "artistName": "Beach House", "duration": 298,
                                       "plainLyrics": "\n".join(f"Linha número {i} da música" for i in range(12)), "syncedLyrics": sinc}
painel(sessao("SpotifyAB.SpotifyMusic_x!Spotify", "Silver Soul", "Beach House", pos=21, dur=298, atual=True))
toc.faixa_atual()
toc._ultima["quando"] = 0.0
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8797, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8797/")
    pg.wait_for_selector("#tocando .tq b", timeout=8000)
    check(pg.inner_text("#tocando .tq b") == "Silver Soul" and "Beach House · Spotify" in pg.inner_text("#tocando .tq small"),
          "a faixa embaixo mostra a música, o artista e de onde vem")
    check(pg.locator("#tocando img").count() == 1, "com a capa")
    pg.screenshot(path=str(OUT / "t1_faixa_jogos.png"))
    pg.click("#shelves >> text=Leitura")
    pg.wait_for_timeout(500)
    check(pg.is_visible("#tocando .tq"), "a faixa aparece também na estante de Leitura")
    pg.click("#tocando >> text=Letra")
    pg.wait_for_selector(".tl-letra p.on", timeout=8000)
    atual = pg.inner_text(".tl-letra p.on")
    check(atual in ("Linha número 4 da música", "Linha número 5 da música"), f"a linha que está tocando fica destacada ({atual})")
    pg.wait_for_timeout(700)
    pg.screenshot(path=str(OUT / "t2_letra.png"))
    pg.click(".tl-lado .tbot.grande")
    pg.wait_for_timeout(300)
    check(COMANDOS[-1][1] == "pausar", "o botão grande da tela da letra pausa")
    painel(sessao("MSEdge", "Anitta - Envolver [Official Music Video]", "Anitta", pos=1, dur=194))
    pg.wait_for_selector("text=Ver no Genius", timeout=8000)
    pg.screenshot(path=str(OUT / "t3_sem_letra.png"))
    del sem_janelas.ABERTOS[:]
    pg.click("text=Ver no Genius")
    pg.wait_for_timeout(500)
    check(sem_janelas.ABERTOS and "genius.com" in sem_janelas.ABERTOS[-1], "sem letra no LRCLIB: o botão abre o Genius")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    check(not pg.is_visible("#telaLetra"), "Esc fecha a tela da letra")
    pg.click("text=Configurações")
    pg.click("#cfgAbas >> text=Música")
    pg.wait_for_selector("text=Mostrar o que está tocando", timeout=8000)
    pg.locator("text=Chave do Genius").scroll_into_view_if_needed()
    pg.screenshot(path=str(OUT / "t4_config.png"))
    pg.keyboard.press("Escape")
    painel()
    pg.wait_for_timeout(2600)
    check(not pg.is_visible("#tocando"), "quando nada toca, a faixa some")
    check(not erros, f"nenhum erro na página {erros}")
    b.close()
srv.shutdown()

print(f"\nTudo certo: {ok} verificações.")

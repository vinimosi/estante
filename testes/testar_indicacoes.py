"""Indicações da Leitura: dados do MangaUpdates e do AniList, climas, escolha da semana, parecidas, pôr em Quero ler,
maratona, esquecidas, a próxima quando uma série acaba e a retrospectiva. AniList e MangaUpdates simulados.
Rode: python3 testar_indicacoes.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import datetime
import os
import shutil
import sys
import threading
import time
from pathlib import Path

S = Path(_SAIDA)
T = S / "indicacoes"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import indicacoes as I  # noqa: E402
import leitura  # noqa: E402
import lojas  # noqa: E402
import testar_leitura_mocks as mocks  # noqa: E402

leitura._http_json = mocks.http_falso
enfileiradas = []
leitura.enfileirar = lambda sid, forcar=False: enfileiradas.append(sid)
for loja in lojas.LEITORES:  # as lojas deste PC não entram no teste
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


def serie(nome):
    return next((s for s in leitura._load()["series"] if s["name"] == nome), None)


def rec(aid, nome, nota, genres, tags=(), adulto=False):
    return {"rating": 50, "mediaRecommendation": {"id": aid, "title": {"english": nome}, "coverImage": {"large": f"https://img.anilist/{aid}.jpg"},
            "averageScore": nota, "genres": list(genres), "countryOfOrigin": "KR", "isAdult": adulto,
            "tags": [{"name": t, "rank": 80} for t in tags]}}


# a estante: duas lidas (romance e ação), três em Quero ler, uma pausada, uma esquecida e uma para maratonar
AGORA = time.time()
with app.lock:
    d = leitura._load()
    for nome, lista, gen, extra in [
        ("Amor de Escritório", "Lendo", ["Romance", "Drama"], {"anilist_id": 1, "ultimo_lido": 40.0, "ultimo_disponivel": 40.0, "favorite": True}),
        ("Espada Sombria", "Terminado", ["Action", "Fantasy"], {"anilist_id": 2, "ultimo_lido": 100.0, "ultimo_disponivel": 100.0}),
        ("Coração Partido", "Quero ler", ["Romance", "Drama"], {"anilist_id": 3, "nota_mu": 8.4}),
        ("Mundo Novo", "Quero ler", ["Fantasy"], {"anilist_id": 4, "nota_mu": 7.0}),
        ("Risada Geral", "Quero ler", ["Comedy"], {"anilist_id": 5}),
        ("Parada no Meio", "Pausado", ["Romance"], {"anilist_id": 6, "ultimo_lido": 12.0}),
        ("Esquecida", "Lendo", ["Drama"], {"ultimo_lido": 10.0, "ultimo_disponivel": 30.0, "ultima_leitura": AGORA - 90 * 86400}),
        ("Maratona Boa", "Lendo", ["Action"], {"ultimo_lido": 5.0, "ultimo_disponivel": 45.0, "ultima_leitura": AGORA - 86400, "tipo": "Manhwa"}),
    ]:
        s = leitura.nova_serie(nome)
        s.update({"lista_anilist": lista, "genres": gen, "verificado_em": AGORA}, **extra)
        d["series"].append(s)
    leitura._save(d)
ids = {s["name"]: s["id"] for s in leitura._load()["series"]}

print("Dados do MangaUpdates")
m = leitura.dados_mu({"series_id": 50, "title": "X", "bayesian_rating": 8.47, "rating_votes": 2317,
                      "recommendations": [{"series_id": 60, "series_name": "Parecida A", "weight": 3, "series_image": {"url": {"original": "https://cdn.mu/a.jpg"}}}],
                      "category_recommendations": [{"series_id": 61, "series_name": "Parecida B", "weight": 900}, {"series_id": 60, "series_name": "Parecida A", "weight": 1}],
                      "categories": [{"category": "Isekai", "votes": 9}, {"category": "Sem Voto", "votes": 0}, {"category": "Magic", "votes": 20}]})
check(m["nota_mu"] == 8.47 and m["votos_mu"] == 2317, "a nota da comunidade do MangaUpdates é guardada")
check([r["nome"] for r in m["recs_mu"]] == ["Parecida B", "Parecida A"] and m["recs_mu"][1]["capa"] == "https://cdn.mu/a.jpg",
      "as parecidas, sem repetir e as mais votadas primeiro")
check(m["temas"] == ["Magic", "Isekai"], "os temas dos leitores, os mais votados primeiro e sem os que ninguém votou")
lst = c.get("/api/leitura").get_json()["series"][0]
check(not any(k in lst for k in ("recs_mu", "temas", "al")), "esses dados não pesam a lista que vai para a tela")

print("AniList, 50 por pedido")
pedidos = []
MEDIA = {
    1: {"id": 1, "averageScore": 82, "isAdult": False, "tags": [{"name": "Office Lover", "rank": 90}, {"name": "Final Secreto", "rank": 90, "isMediaSpoiler": True}],
        "recommendations": {"nodes": [rec(3, "Coração Partido", 85, ["Romance", "Drama"]), rec(20, "Romance de Fora", 88, ["Romance"], ["Enemies To Lovers"]),
                                      rec(21, "Adulta de Fora", 90, ["Romance", "Hentai"], adulto=True)]}},
    2: {"id": 2, "averageScore": 80, "isAdult": False, "tags": [],
        "recommendations": {"nodes": [rec(22, "Outro Mundo", 79, ["Fantasy", "Action"], ["Isekai"]), rec(4, "Mundo Novo", 70, ["Fantasy"])]}},
    3: {"id": 3, "averageScore": 85, "isAdult": False, "tags": [{"name": "Love Triangle", "rank": 70}], "recommendations": {"nodes": []}},
}


def anilist_falso(q, v):
    pedidos.append(list(v["ids"]))
    return {"Page": {"media": [MEDIA[i] for i in v["ids"] if i in MEDIA]}}


leitura.anilist = anilist_falso
n = I.enriquecer(lote=4, pausa=0)
check(n == 6 and len(pedidos) == 2 and pedidos[0][0] == 1, f"6 séries em 2 pedidos de até 4, a favorita primeiro ({pedidos})")
al = serie("Amor de Escritório")["al"]
check(al["nota"] == 82 and al["tags"] == ["Office Lover"], "nota e etiquetas do AniList (sem as que contam o final)")
check([r["nome"] for r in al["recs"]] == ["Coração Partido", "Romance de Fora", "Adulta de Fora"] and al["recs"][1]["tags"] == ["Enemies To Lovers"],
      "as parecidas, com nota, gêneros e etiquetas")
check(serie("Risada Geral")["al"] == {"em": serie("Risada Geral")["al"]["em"]}, "série que o AniList não devolveu fica marcada, para não perguntar de novo")
pedidos.clear()
check(I.enriquecer(lote=4, pausa=0) == 0 and not pedidos, "e nada é pedido de novo antes de 30 dias")

print("No clima de quê?")
climas = {x["chave"]: x["total"] for x in c.get("/api/leitura/climas").get_json()}
check(climas["romance"] >= 3 and climas["isekai"] == 1, f"cada clima diz quantas indicações tem ({climas})")
r = c.get("/api/leitura/indicacao?clima=romance").get_json()
check(r["item"]["nome"] == "Coração Partido" and "Amor de Escritório" in r["item"]["motivo"],
      f"romance: primeiro a da Quero ler que é parecida com uma lida, com o motivo ({r['item']['motivo']})")
vistos = [r["item"]["chave"]]
nomes = [r["item"]["nome"]]
for _ in range(3):
    r = c.get("/api/leitura/indicacao?clima=romance&pular=" + ",".join(vistos)).get_json()
    vistos.append(r["item"]["chave"])
    nomes.append(r["item"]["nome"])
check("Adulta de Fora" not in nomes and "Romance de Fora" in nomes and "Parada no Meio" in nomes, f"\"Outra\" passa pelas outras, sem conteúdo adulto de fora ({nomes})")
fora = next(x for x in [c.get("/api/leitura/indicacao?clima=romance&pular=" + ",".join(vistos[:i])).get_json()["item"] for i in range(4)] if x["de_fora"])
check(fora["nome"] == "Romance de Fora" and fora["capa"].startswith("https://img.anilist") and fora["nota"] == 88, "a de fora vem com capa e nota do AniList")
r = c.get("/api/leitura/indicacao?clima=isekai").get_json()
check(r["item"]["nome"] == "Outro Mundo" and "Espada Sombria" in r["item"]["motivo"], "isekai pela etiqueta do AniList da parecida")
r = c.get("/api/leitura/indicacao?clima=terror").get_json()
check(r["item"] is None and r["total"] == 0, "clima sem nada: avisa em vez de inventar")
check(c.get("/api/leitura/indicacao?clima=xyz").status_code == 400, "clima que não existe: erro")

print("Escolha da semana")
s1 = c.get("/api/leitura/semana").get_json()
check(s1["semana"] == I.semana_atual() and s1["item"]["nome"], f"uma série para a semana ({s1['item']['nome']})")
check(c.get("/api/leitura/semana").get_json() == s1, "a mesma a semana inteira")
with app.lock:
    cfg, lc = leitura.cfg_leitura()
    lc["escolha_semana"]["semana"] = "2000-01"
    app.save_cfg(cfg)
check(c.get("/api/leitura/semana").get_json()["semana"] == I.semana_atual(), "virou a semana: escolhe de novo")

print("Parecidas com esta")
p = c.get("/api/leitura/parecidas?id=" + ids["Amor de Escritório"]).get_json()
check([x["nome"] for x in p] == ["Coração Partido", "Romance de Fora"], "as parecidas, sem a adulta (a série não é adulta)")
check(p[0]["id"] == ids["Coração Partido"] and p[0]["lista"] == "Quero ler" and p[1]["id"] is None, "diz quais já estão na estante")
check(c.get("/api/leitura/parecidas?id=nada").status_code == 404, "série que não existe: 404")
r = c.post("/api/leitura/indicacao/adicionar", json={"anilist_id": 20, "nome": "Romance de Fora"}).get_json()
nova = serie("Romance de Fora")
check(r["nova"] and nova["lista_anilist"] == "Quero ler" and nova["anilist_id"] == 20 and enfileiradas[-1] == nova["id"],
      "Pôr em Quero ler cria a série ligada ao AniList, e os dados e a capa vêm pela fila")
r2 = c.post("/api/leitura/indicacao/adicionar", json={"anilist_id": 20, "nome": "Romance de Fora"}).get_json()
check(not r2["nova"] and r2["id"] == nova["id"], "pôr de novo não duplica")
p = c.get("/api/leitura/parecidas?id=" + ids["Amor de Escritório"]).get_json()
check(p[1]["id"] == nova["id"], "e agora ela aparece como já na estante")

print("Retrospectiva")
ini_mes = datetime.datetime.now().replace(day=1, hour=12, minute=0, second=0, microsecond=0).timestamp()
with app.lock:
    d = leitura._load()
    d["leituras"] = [{"s": ids["Amor de Escritório"], "c": float(n), "t": ini_mes + 3600 * n} for n in range(1, 9)] + \
                    [{"s": ids["Amor de Escritório"], "c": 8.0, "t": ini_mes + 3600 * 9}] + \
                    [{"s": ids["Espada Sombria"], "c": float(n), "t": ini_mes + 86400 + 60 * n} for n in range(1, 4)] + \
                    [{"s": ids["Espada Sombria"], "c": 0.5, "t": ini_mes - 40 * 86400}]
    leitura._save(d)
r = c.get("/api/leitura/retrospectiva").get_json()
check(r["capitulos"] == 11 and r["dias"] == 2 and r["series"] == 2, "o mês: 11 capítulos (o repetido conta uma vez), em 2 dias, de 2 séries")
check(r["mais_lidas"][0]["nome"] == "Amor de Escritório" and r["mais_lidas"][0]["capitulos"] == 8, "a mais lida")
check(r["generos"][0] == "Romance" and r["dia_top"]["capitulos"] == 8, f"o gênero e o dia que mais leu ({r['generos']})")
check([x["nome"] for x in r["comecadas"]] == ["Amor de Escritório"], "começadas: só a que teve o primeiro capítulo no mês")
check(r["pouco"] is False or r["capitulos"] < 10, "avisa quando ainda tem pouco histórico")
check(not r["vista"] and c.post("/api/leitura/retrospectiva/vista", json={"ref": r["ref"]}).get_json()["ok"]
      and c.get("/api/leitura/retrospectiva").get_json()["vista"], "fica marcada como vista (o aviso do começo do mês some)")
ra = c.get(f"/api/leitura/retrospectiva?periodo=ano&ref={datetime.date.today().year}").get_json()
check(ra["periodo"] == "ano" and ra["capitulos"] >= 11, "o ano também")

print("Tela")
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8800, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 900})
    pg.route("https://img.anilist/**", lambda rota: rota.fulfill(status=404, body=""))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8800/")
    pg.evaluate("trocarEstante('leitura')")
    pg.wait_for_selector("#paraVoce .chip.clima")
    check(pg.locator("#paraVoce .pv-semana .ind").count() == 1, "a escolha da semana aparece")
    check("Terror" not in pg.inner_text("#paraVoce .chips"), "clima sem indicação não aparece")
    pg.click("#paraVoce .chip.clima:has-text('Romance')")
    pg.wait_for_selector("#paraVoce .pv-clima .ind")
    primeira = pg.inner_text("#paraVoce .pv-clima .ind-t b")
    pg.click("#paraVoce .pv-clima button:has-text('Outra')")
    pg.wait_for_function(f"document.querySelector('#paraVoce .pv-clima .ind-t b') && document.querySelector('#paraVoce .pv-clima .ind-t b').textContent !== {primeira!r}")
    check(True, "escolher um clima mostra uma indicação, e \"Outra\" troca")
    check("Maratona Boa" in pg.inner_text("#paraVoce") and "40 capítulos · uns 2,7 h" in pg.inner_text("#paraVoce"),
          "Para maratonar: a série com 40 capítulos esperando, com o tempo aproximado")
    check("Esquecida" in pg.inner_text("#paraVoce") and pg.locator("#paraVoce button:has-text('Pausar')").count() == 1, "Esquecidas, com Pausar")
    pg.screenshot(path=str(OUT / "indicacoes_paravoce.png"))
    pg.click("#paraVoce button:has-text('Pausar')")
    pg.wait_for_function("!document.querySelector('#paraVoce') || !document.querySelector('#paraVoce').innerText.includes('Esquecida')")
    check(serie("Esquecida")["lista_anilist"] == "Pausado", "Pausar tira das esquecidas e põe nas pausadas")

    pg.evaluate(f"openDrawer({ids['Amor de Escritório']!r})")
    pg.wait_for_selector("#parecidasSec .fi")
    check(pg.locator("#parecidasSec .fi").count() == 2 and "Quero ler" in pg.inner_text("#parecidasSec"), "o painel da série mostra as parecidas")
    pg.screenshot(path=str(OUT / "indicacoes_parecidas.png"))
    pg.evaluate("closeDrawer()")

    # terminou: marcar como Terminado mostra a próxima
    with app.lock:
        d = leitura._load()
        x = next(s for s in d["series"] if s["id"] == ids["Amor de Escritório"])
        x["lista_anilist"] = "Terminado"
        leitura._save(d)
    pg.wait_for_selector(".toast.prox", timeout=15000)
    check("Terminou Amor de Escritório?" in pg.inner_text(".toast.prox"), "terminou uma série: aparece a próxima parecida")

    pg.evaluate("go('stats')")
    pg.click("button:has-text('Retrospectiva')")
    pg.wait_for_selector("#retroSlide .r-big")
    pg.wait_for_timeout(1100)
    check(pg.inner_text("#retroSlide .r-big") == "11", "a retrospectiva abre nas Estatísticas, contando os capítulos")
    pg.click("#retroProx")
    check("Amor de Escritório" in pg.inner_text("#retroSlide"), "Próximo: a mais lida")
    pg.keyboard.press("ArrowRight")
    check("Romance" in pg.inner_text("#retroSlide"), "a seta do teclado também passa")
    pg.screenshot(path=str(OUT / "indicacoes_retro.png"))
    check(not erros, "sem erros na página: " + "; ".join(erros))
    b.close()
srv.shutdown()

print(f"\nTudo certo: {ok} verificações.")

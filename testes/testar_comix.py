"""Comix: importar o CSV exportado, ligar as séries pela lista "Followed Titles" e o site preferido.
Rode: python3 testar_comix.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import io
import os
import shutil
import sys
from pathlib import Path

S = Path(_SAIDA)
T = S / "comix"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import leitura  # noqa: E402
import testar_leitura_mocks as mocks  # noqa: E402

leitura._http_json = mocks.http_falso
leitura.enfileirar = lambda *a, **k: None   # sem MangaUpdates neste teste
leitura.verificar_todas = lambda *a, **k: None
leitura.anilist_por_ids = lambda ids: [{"id": 9001, "title": {"romaji": "Ice Master", "english": "Ice Master"}, "synonyms": [],
                                        "coverImage": {}, "description": "Um mago de gelo.", "genres": ["Fantasy"],
                                        "status": "RELEASING", "countryOfOrigin": "KR", "idMal": None}] if 9001 in ids else []
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


# ---- a Leitura antes: séries que vieram da importação do XML (com os números do AniList e do MyAnimeList)
with app.lock:
    d = leitura._load()
    for nome, al, mal, lido, lista, extra in [
        ("Tower of God", 85143, 122663, 79.0, "Larguei", {"ultimo_disponivel": 640.0}),
        ("Childhood Friend of the Zenith", 151234, 150000, 120.0, "Lendo", {}),   # na Estante está mais adiantada
        ("Like a Chilling Flame", None, 160000, 90.0, "Lendo", {}),                # só o número do MyAnimeList bate
        ("Return of the Mad Demon", None, None, 10.0, "Lendo", {"url_mu": "https://www.mangaupdates.com/series/abc123x"}),
        ("Solo Leveling", 105398, 121496, 200.0, "Terminado", {"titulos_alt": ["Only I Level Up"]}),
        ("Gêmeos 1", None, None, 1.0, "Lendo", {"titulos_alt": ["Twins"]}),
        ("Gêmeos 2", None, None, 1.0, "Lendo", {"titulos_alt": ["Twins"]}),
    ]:
        s = leitura.nova_serie(nome)
        s.update({"anilist_id": al, "mal_id": mal, "ultimo_lido": lido, "lista_anilist": lista, "verificado_em": 1.0}, **extra)
        d["series"].append(s)
    leitura._save(d)

CSV = """title,chapter,folder,url_mal,url_al,url_mu
"Tower of God",79.000,Dropped,https://myanimelist.net/manga/122663,https://anilist.co/manga/85143,https://mangaupdates.com/series/5z98aus
"Childhood Friend of the Zenith",112.000,Reading,https://myanimelist.net/manga/150000,https://anilist.co/manga/151234,
"Like a Chilling Flame",100.000,Favoritos,https://myanimelist.net/manga/160000,,
"Return of the Mad Demon",218.000,On-Hold,,,https://mangaupdates.com/series/abc123x
"Ice Master",5.000,Plan to Read,,https://anilist.co/manga/9001,https://mangaupdates.com/series/zzz999a
"""

print("Importar o CSV do Comix")
r = c.post("/api/leitura/importar-arquivo", data={"file": (io.BytesIO(("﻿" + CSV).encode()), "manga-list.csv"), "usar_capitulo": "1"},
           content_type="multipart/form-data")
j = r.get_json()
check(r.status_code == 200 and j["comix"] and j["total"] == 5 and j["novas"] == 1, "CSV do Comix reconhecido: 5 séries, 1 nova")
import time  # noqa: E402
for _ in range(40):
    if not leitura._importando["ativo"]:
        break
    time.sleep(0.25)
check(len(leitura._load()["series"]) == 8, "nada foi duplicado")
tg = serie("Tower of God")
check(tg["nome_comix"] == "Tower of God" and tg["lista_anilist"] == "Larguei", "achada pelo número do AniList, situação Dropped = Larguei")
cf = serie("Childhood Friend of the Zenith")
check(cf["ultimo_lido"] == 120.0, "o capítulo lido só anda para frente (a Estante estava no 120, o Comix no 112)")
lf = serie("Like a Chilling Flame")
check(lf["ultimo_lido"] == 100.0 and lf["favorite"] and lf["lista_anilist"] == "Lendo",
      "pasta Favoritos: vira favorito sem mudar a situação; achada pelo número do MyAnimeList")
md = serie("Return of the Mad Demon")
check(md["lista_anilist"] == "Pausado" and md["ultimo_lido"] == 218.0, "achada pelo MangaUpdates; On-Hold = Pausado")
im = serie("Ice Master")
check(im and im["anilist_id"] == 9001 and im["description"] == "Um mago de gelo." and im["lista_anilist"] == "Quero ler"
      and im["url_mu"].endswith("/zzz999a"), "série nova trouxe os dados pelo número do AniList")

print("Ligar as séries pela lista do Comix (Followed Titles)")
cartoes = [
    {"slug": "x1-tower-of-god", "titulo": "Tower of God", "lido": 79, "ultimo": 650},
    {"slug": "0kxld-childhood-friend-of-the-zenith", "titulo": "Childhood Friend of the Zenith", "lido": 112, "ultimo": 113},
    {"slug": "7z2g-like-a-chilling-flame", "titulo": "Like a Chilling Flame", "lido": 101, "ultimo": 101},
    {"slug": "sl-solo-leveling", "titulo": "Only I Level Up", "lido": None, "ultimo": 200},   # pelo nome alternativo
    {"slug": "tw-twins", "titulo": "Twins", "lido": 3, "ultimo": 3},                           # dois batem: não chuta
    {"slug": "zz-nao-esta-na-estante", "titulo": "Não Está Na Estante", "lido": 1, "ultimo": 2},
]
j = c.post("/api/leitura/lista-site", json={"site": "comix", "cartoes": cartoes}, headers={"X-Estante-Extensao": "1"}).get_json()
check(j["ligadas"] == 4 and j["sem_par"] == 2 and "Twins" in j["nomes_sem_par"], "4 ligadas; o nome repetido e a que não existe ficam de fora")
tg = serie("Tower of God")
check(tg["por_site"]["comix"]["slug"] == "x1-tower-of-god" and tg["por_site"]["comix"]["serie"] == "/title/x1-tower-of-god"
      and tg["site"] == "comix", "série ligada ao endereço no Comix, que vira o site principal")
check(any(n["s"] == tg["id"] and n["c"] == 650 and n["site"] == "comix" for n in leitura._load()["novidades"]),
      "capítulo novo visto na lista entra em Novidades, com o site")
check(serie("Like a Chilling Flame")["ultimo_lido"] == 101.0, "lido no Comix mais adiantado avança a Estante")
check(serie("Gêmeos 1").get("por_site", {}).get("comix") is None, "nome que bate com duas séries não é ligado")
j = c.post("/api/leitura/lista-site", json={"site": "comix", "cartoes": cartoes[:3]}).get_json()
check(j["ligadas"] == 0 and j["ja"] == 3, "mandar a mesma página de novo não muda nada")
check(c.post("/api/leitura/lista-site", json={"site": "comix", "cartoes": cartoes},
             headers={"Origin": "https://site-qualquer.com"}).status_code == 403, "outros sites não conseguem mandar listas")

print("Ler capítulo no Comix")
lst = {s["name"]: s for s in c.get("/api/leitura").get_json()["series"]}
p = lst["Tower of God"]
check(p["url_serie"].endswith("/title/x1-tower-of-god") and p["site_nome"] == "Comix",
      "sem o link do capítulo ainda, o Ler abre a página da série no Comix")

print("Site preferido")
with app.lock:
    d = leitura._load()
    s = leitura.achar(d, serie("Solo Leveling")["id"])
    s["ultimo_lido"] = 100.0
    leitura._ps(s, "asura", "solo-leveling")["caps"] = {"101": "/comics/solo-leveling-3ebcc5a9/chapter/101"}
    s["por_site"]["asura"]["ultimo"] = 101.0
    s["por_site"]["comix"]["caps"] = {"101": "/title/sl-solo-leveling/999-chapter-101"}
    s["primeiro"] = {"101": {"site": "asura", "t": 1.0}}
    leitura._save(d)
leitura._pref["quando"] = 0
sl = {x["name"]: x for x in c.get("/api/leitura").get_json()["series"]}["Solo Leveling"]
check(sl["proximo_cap"]["site"] == "asura", "sem preferido: abre no site que lançou primeiro (Asura)")
sites = c.get("/api/leitura/sites").get_json()
check(sites["preferido"] == "", "começa sem site preferido")
r = c.post("/api/leitura/sites", json={"sites": sites["sites"], "preferido": "comix"}).get_json()
check(r["preferido"] == "comix", "Comix escolhido como preferido")
sl = {x["name"]: x for x in c.get("/api/leitura").get_json()["series"]}["Solo Leveling"]
check(sl["proximo_cap"]["site"] == "comix" and "999-chapter-101" in sl["proximo_cap"]["url"], "com o Comix preferido, o Ler abre no Comix")
with app.lock:
    d = leitura._load()
    leitura.achar(d, serie("Solo Leveling")["id"])["por_site"]["comix"]["caps"] = {}
    leitura._save(d)
sl = {x["name"]: x for x in c.get("/api/leitura").get_json()["series"]}["Solo Leveling"]
check(sl["proximo_cap"]["site"] == "asura", "capítulo que ainda não saiu no Comix abre onde já saiu")
r = c.post("/api/leitura/sites", json={"sites": sites["sites"], "preferido": "site-que-nao-existe"}).get_json()
check(r["preferido"] == "", "preferido que não está na lista de sites é ignorado")
c.post("/api/leitura/sites", json={"sites": sites["sites"], "preferido": "comix"})

print("Telas")
import threading  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8793, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
(S / "telas").mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    nav = pw.chromium.launch()
    pg = nav.new_page(viewport={"width": 1320, "height": 900})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    abertas = []
    pg.goto("http://127.0.0.1:8793/")
    pg.evaluate("localStorage.setItem('estante.estante', JSON.stringify('leitura'))")
    pg.reload()
    pg.wait_for_timeout(1500)
    pg.evaluate("window.open = (u) => { window.__aberta = u; }")
    pg.evaluate("openImportar()")
    pg.wait_for_selector("text=Abrir a minha lista no Comix")
    check(".csv" in pg.get_attribute("#iArq", "accept") and "CSV (Comix)" in pg.inner_text("#modal"),
          "a importação aceita o CSV do Comix e explica onde baixar")
    pg.screenshot(path=str(S / "telas" / "c1_importar_comix.png"))
    pg.click("text=Abrir a minha lista no Comix")
    check(pg.evaluate("window.__aberta") == "https://comix.to/user?tab=titles#estante-ligar",
          "o botão abre a sua lista do Comix numa aba, marcada para a extensão passar as páginas")
    pg.evaluate("closeModal(); openSettings()")
    pg.wait_for_selector("#sitePref")
    check(pg.eval_on_selector("#sitePref", "s => s.value") == "comix", "Configurações mostram o Comix como site preferido")
    pg.locator("#sitePref").scroll_into_view_if_needed()
    pg.screenshot(path=str(S / "telas" / "c2_site_preferido.png"))
    check(not erros, f"sem erros na página {erros}")
    nav.close()
srv.shutdown()

print(f"\nTudo certo: {ok} verificações.")

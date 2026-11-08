"""Testes da fase 2 (Leitura) com AniList, MangaUpdates e sites simulados."""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import io
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image

S = Path(_SAIDA)
T = S / "leit"
import shutil  # noqa: E402
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import leitura  # noqa: E402

# ---------------- internet de mentira
ANI = {
    105398: {"id": 105398, "title": {"romaji": "Na Honjaman Level Up", "english": "Solo Leveling", "native": "나 혼자만 레벨업"},
             "synonyms": ["Only I Level Up"], "coverImage": {"extraLarge": "https://img.anilist/solo.jpg"},
             "description": "Dez anos atrás, portais surgiram.<br><br>Sung Jinwoo é o caçador mais fraco. (Source: Webtoon)",
             "genres": ["Action", "Fantasy"], "status": "FINISHED", "chapters": 200, "countryOfOrigin": "KR",
             "startDate": {"year": 2018}, "siteUrl": "https://anilist.co/manga/105398",
             "staff": {"edges": [{"role": "Story", "node": {"name": {"full": "Chugong"}}}]}},
    119257: {"id": 119257, "title": {"romaji": "Omniscient Reader", "english": "Omniscient Reader", "native": None}, "synonyms": ["ORV"],
             "coverImage": {"extraLarge": "https://img.anilist/orv.jpg"}, "description": "O fim do mundo.", "genres": ["Action"],
             "status": "RELEASING", "chapters": None, "countryOfOrigin": "KR", "startDate": {"year": 2020}, "siteUrl": "",
             "staff": {"edges": []}},
    999: {"id": 999, "title": {"romaji": "Tower of God", "english": "Tower of God", "native": None}, "synonyms": [],
          "coverImage": {"extraLarge": "https://img.anilist/tog.jpg"}, "description": "A torre.", "genres": ["Adventure"],
          "status": "RELEASING", "chapters": None, "countryOfOrigin": "KR", "startDate": {"year": 2010}, "siteUrl": "", "staff": {"edges": []}},
}
MU = {"Solo Leveling": (1, 200), "Omniscient Reader": (2, 230), "The Heavenly Demon Can't Live a Normal Life": (3, 150), "Tower of God": (4, 640)}
chamadas = []


def http_falso(url, dados=None, timeout=20):
    chamadas.append(url)
    if "anilist" in url:
        q, v = dados["query"], dados["variables"]
        if "MediaListCollection" in q:
            if v["u"] != "pessoa-teste":
                return {"errors": [{"message": "User not found"}]}
            return {"data": {"MediaListCollection": {"lists": [{"entries": [
                {"progress": 150, "status": "CURRENT", "media": ANI[105398]},
                {"progress": 600, "status": "PAUSED", "media": ANI[999]}]}]}}}
        if "Media(id" in q:
            return {"data": {"Media": ANI.get(v["id"])}}
        s = v["s"].lower()
        return {"data": {"Page": {"media": [m for m in ANI.values() if s in json.dumps(m).lower()]}}}
    if "series/search" in url:
        t = dados["search"]
        return {"results": [{"record": {"series_id": sid, "title": nome}} for nome, (sid, _) in MU.items() if t.lower() in nome.lower()]}
    if "api.mangaupdates.com/v1/series/" in url:
        sid = int(url.rstrip("/").split("/")[-1])
        nome, lat = next((n, lt) for n, (i, lt) in MU.items() if i == sid)
        return {"series_id": sid, "title": nome, "latest_chapter": lat, "url": f"https://www.mangaupdates.com/series/{sid}",
                "description": f"Descrição de {nome} no MangaUpdates.<br><br>Segunda linha. <i>(fonte)</i>",
                "image": {"url": {"original": f"https://cdn.mangaupdates.com/image/{sid}.jpg"}}, "type": "Manhwa", "year": "2018",
                "genres": [{"genre": "Action"}, {"genre": "Fantasy"}], "status": "Ongoing" if sid != 1 else "200 Chapters (Complete)",
                "completed": sid == 1, "authors": [{"name": "Chugong", "type": "Author"}, {"name": "Jang Sung-Rak", "type": "Artist"}],
                "associated": [{"title": "Only I Level Up"}] if sid == 1 else []}
    raise RuntimeError("sem internet no teste")


def capa_falsa(sid, url, referer=None):
    b = io.BytesIO()
    Image.new("RGB", (300, 450), (hash(url) % 255, 80, 120)).save(b, "JPEG")
    return leitura.guardar_capa_bytes(sid, b.getvalue(), ".jpg")


leitura._http_json = http_falso
leitura.guardar_capa = capa_falsa
c = app.app.test_client()
EXT = {"Origin": "chrome-extension://abcdefghijklmnop", "X-Estante-Extensao": "1"}
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


def esperar(cond, seg=10):
    fim = time.time() + seg
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.1)
    return False


def serie(nome):
    s = next((s for s in c.get("/api/leitura").get_json()["series"] if s["name"] == nome), None)
    if s:  # a descrição não vem na lista: é pedida quando a série é aberta
        s["description"] = c.get("/api/leitura/sobre?id=" + s["id"]).get_json()["description"]
    return s


print("Entender links dos três sites")
E = leitura.entender_link
r = E("https://asurascans.com/comics/solo-leveling-059befe1/chapter/108")
check(r["site"] == "asura" and r["slug"] == "solo-leveling" and r["num"] == 108 and r["tipo"] == "capitulo", "Asura: capítulo, sem o código aleatório do fim")
check(E("https://asurascans.com/comics/solo-leveling-3ebcc5a9")["slug"] == "solo-leveling", "Asura: página da série")
check(E("https://asurascans.com/comics/the-tutorial-is-too-hard-villains/chapter/3")["slug"] == "the-tutorial-is-too-hard-villains", "Asura: nome que termina com palavra de 8 letras não é cortado")
check(E("https://asuracomic.net/series/solo-leveling-abc12345/chapter/7.5")["num"] == 7.5, "Asura: endereço antigo e capítulo 7,5")
r = E("https://comix.to/title/rm2xv-omniscient-reader/5531781-chapter-230")
check(r["site"] == "comix" and r["slug"] == "rm2xv-omniscient-reader" and r["num"] == 230, "Comix: capítulo")
check(E("https://comix.to/title/rm2xv-omniscient-reader")["tipo"] == "serie", "Comix: série")
r = E("https://demonicscans.org/title/The-Heavenly-Demon-Cant-Live-a-Normal-Life/chapter/163/2024120708")
check(r["site"] == "demonic" and r["num"] == 163 and r["slug"] == "The-Heavenly-Demon-Cant-Live-a-Normal-Life", "Demonic Scans: capítulo")
check(E("https://www.demonicscans.org/manga/The-Heavenly-Demon-Cant-Live-a-Normal-Life")["tipo"] == "serie", "Demonic Scans: série (com www)")
check(E("https://google.com/chapter/1") is None, "site fora da lista é ignorado")
r = E("https://demonicscans.org/chaptered.php?manga=12345&chapter=219")
check(r and r["tipo"] == "capitulo" and r["num"] == 219 and r["slug"] == "12345", "Demonic Scans: botão Próximo (chaptered.php) visto no site real")
r = E("https://demonicscans.org/title/Swordmaster%2527s-Youngest-Son/chapter/218/1")
check(r["slug"] == "Swordmaster%2527s-Youngest-Son" and leitura.titulo_do_slug(r["slug"]) == "Swordmaster's Youngest Son", "Demonic: nome com apóstrofo codificado duas vezes")
check(leitura.limpar_titulo("Solo LevelingChapter 109") == "Solo Leveling", "título colado ao 'Chapter' (como no Asura real)")
check(leitura.limpar_titulo("Return of the Mad Demon · Ch.218") == "Return of the Mad Demon", "título do Comix real ('· Ch.218')")
check(leitura.limpar_titulo("Solo Leveling Chapter 108 - Read Online | Asura Scans") == "Solo Leveling", "limpa o título da aba")
check(leitura.titulo_do_slug("rm2xv-omniscient-reader", "comix") == "Omniscient Reader", "nome tirado do link do Comix")

print("Segurança")
r = c.post("/api/leitura/progresso", json={"url": "https://asurascans.com/comics/x/chapter/1"}, headers={"Origin": "https://site-malicioso.com"})
check(r.status_code == 403, "um site qualquer não consegue mandar nada para a Estante")
r = c.post("/api/games", json={}, headers={"Origin": "https://site-malicioso.com"})
check(r.status_code == 403, "nem mexer nos jogos")

print("Extensão registra o capítulo")
r = c.post("/api/leitura/progresso", headers=EXT, json={
    "url": "https://asurascans.com/comics/solo-leveling-059befe1/chapter/108",
    "titulo": "Solo Leveling Chapter 108 - Read Online | Asura Scans", "capitulo": 108,
    "capa": "https://cdn.asurascans.com/asura-images/covers/solo-leveling.c27830.webp",
    "proximo": "https://asurascans.com/comics/solo-leveling-059befe1/chapter/109"}).get_json()
check(r["ok"] and r["nova"] and r["nome"] == "Solo Leveling", "série criada sozinha ao abrir o capítulo")
check(esperar(lambda: (serie("Solo Leveling") or {}).get("mu_id") == 1 and (serie("Solo Leveling") or {}).get("cover")), "dados e capa do MangaUpdates chegaram")
s = serie("Solo Leveling")
check(s["status"] == "Completa" and s["tipo"] == "Manhwa" and s["autor"] == "Chugong" and "Action" in s["genres"] and s["dados_de"] == "mangaupdates"
      and s["description"].startswith("Descrição de Solo Leveling no MangaUpdates.") and "<" not in s["description"], "MangaUpdates é a fonte principal: status, tipo, autor, gêneros e descrição limpa")
check(not s.get("anilist_id"), "o AniList não foi usado porque o MangaUpdates já deu tudo")
check(s["lido_txt"] == "108" and s["disp_txt"] == "200" and s["nao_lidos"] == 92 and s["tem_novo"], "lido 108 de 200: 92 capítulos novos")
check(s["proximo_cap"]["num"] == "109" and s["proximo_cap"]["url"] == "https://asurascans.com/comics/solo-leveling-059befe1/chapter/109" and s["proximo_cap"]["site_nome"] == "Asura Scans",
      "Ler capítulo 109 abre o link exato do próximo")
check(s["url_serie"] == "https://asurascans.com/comics/solo-leveling", "link da série")
check(c.get("/api/config").get_json()["extensao_dir"].endswith("extensao"), "a Estante sabe onde está a pasta da extensão")
check(c.get("/api/leitura").get_json()["extensao_vista"], "a Estante sabe que a extensão está funcionando")

c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://asurascans.com/comics/solo-leveling-059befe1/chapter/50", "titulo": "Solo Leveling Chapter 50"})
check(serie("Solo Leveling")["lido_txt"] == "108", "reler um capítulo antigo não faz voltar o progresso")
c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://asurascans.com/comics/solo-leveling-059befe1/chapter/115", "titulo": "Solo Leveling Chapter 115"})
s = serie("Solo Leveling")
check(s["lido_txt"] == "115" and s["proximo_cap"]["url"].endswith("/comics/solo-leveling/chapter/116"), "sem link exato, monta o link pelo formato do site")
check(len(c.get("/api/leitura").get_json()["historico"]) == 3, "histórico guarda cada capítulo aberto")

print("Comix: próximo capítulo e lista vista na página da série")
c.post("/api/leitura/progresso", headers=EXT, json={
    "url": "https://comix.to/title/rm2xv-omniscient-reader/5531781-chapter-228", "titulo": "Omniscient Reader", "capitulo": 228,
    "proximo": "https://comix.to/title/rm2xv-omniscient-reader/5531999-chapter-229"})
check(esperar(lambda: (serie("Omniscient Reader") or {}).get("verificado_em")), "série do Comix criada e verificada")
s = serie("Omniscient Reader")
check(s["proximo_cap"]["url"] == "https://comix.to/title/rm2xv-omniscient-reader/5531999-chapter-229", "Comix: Ler capítulo 229 usa o link visto na página")
check(s["disp_txt"] == "230" and not [n for n in c.get("/api/leitura").get_json()["novidades"] if n["s"] == s["id"]],
      "primeira verificação descobre até onde a série foi, sem encher as Novidades")
caps = [{"n": n, "url": f"https://comix.to/title/rm2xv-omniscient-reader/{5530000 + n}-chapter-{n}"} for n in range(220, 233)]
c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://comix.to/title/rm2xv-omniscient-reader", "titulo": "Omniscient Reader", "capitulos": caps})
s = serie("Omniscient Reader")
nov = [n for n in c.get("/api/leitura").get_json()["novidades"] if n["s"] == s["id"]]
check(s["disp_txt"] == "232" and nov and nov[0]["c"] == 232, "capítulo 232 visto na página da série entra em Novidades")
check(s["capitulos"]["231"].endswith("/5530231-chapter-231"), "links exatos de cada capítulo guardados")
c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://comix.to/title/rm2xv-omniscient-reader/5530232-chapter-232", "titulo": "x"})
s = serie("Omniscient Reader")
check(not s["tem_novo"] and s["proximo_cap"]["existe"] is False, "leu o último: em dia, sem selo de novo")
r = c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://comix.to/title/zz9-outra-serie", "titulo": "Outra", "capitulos": caps[:2]}).get_json()
check(r.get("ignorado") and not serie("Outra"), "abrir só a página de uma série que você não lê não cria nada")

print("MangaUpdates avisa capítulo novo")
MU["Omniscient Reader"] = (2, 235)
c.post(f"/api/leitura/{s['id']}/verificar")
s = serie("Omniscient Reader")
check(s["tem_novo"] and s["nao_lidos"] == 3 and s["proximo_cap"]["num"] == "233", "3 capítulos novos, próximo é o 233")

print("Link colado à mão (Demonic Scans)")
r = c.post("/api/leitura/link", json={"url": "https://demonicscans.org/title/The-Heavenly-Demon-Cant-Live-a-Normal-Life/chapter/163/2024120708"}).get_json()
check(r["nova"] and r["nome"] == "The Heavenly Demon Cant Live A Normal Life" and r["capitulo"] == "163", "série e capítulo reconhecidos pelo link")
r = c.post("/api/leitura/link", json={"url": "https://demonicscans.org/manga/The-Heavenly-Demon-Cant-Live-a-Normal-Life"})
check(r.status_code == 400 and "capítulo" in r.get_json()["error"], "link da série (e não do capítulo) explica o que colar")
r = c.get("/api/leitura/entender?url=" + "https://asurascans.com/comics/nano-machine-1a2b3c4d/chapter/200").get_json()
check(r["titulo"] == "Nano Machine" and r["num_txt"] == "200", "prévia do link colado")

print("Fila da extensão (Estante estava fechada)")
ontem = (time.time() - 86400) * 1000
c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://asurascans.com/comics/solo-leveling-059befe1/chapter/116", "titulo": "Solo Leveling", "quando": ontem})
s = serie("Solo Leveling")
check(abs(s["ultima_leitura"] - ontem / 1000) < 2, "capítulo guardado pela extensão entra com a hora em que você leu")

print("Trocar endereço do site")
sites = c.get("/api/leitura/sites").get_json()["sites"]
for x in sites:
    if x["chave"] == "asura":
        x["dominio"] = "asura-novo.net"
r = c.post("/api/leitura/sites", json={"sites": [{"chave": x["chave"], "nome": x["nome"], "dominio": x["dominio"]} for x in sites]}).get_json()
s = serie("Solo Leveling")
check(s["url_serie"] == "https://asura-novo.net/comics/solo-leveling" and s["proximo_cap"]["url"].startswith("https://asura-novo.net/"),
      "todos os links da série passam a usar o endereço novo")
check(E("https://asurascans.com/comics/solo-leveling/chapter/117")["site"] == "asura", "o endereço antigo continua sendo reconhecido")
r = c.post("/api/leitura/sites", json={"sites": [{"nome": "Meu site", "dominio": "https://www.leitor-exemplo.com/"}] + [{"chave": x["chave"], "nome": x["nome"], "dominio": x["dominio"]} for x in sites]}).get_json()
check(any(x["dominio"] == "leitor-exemplo.com" for x in r["sites"]), "acrescentar site novo (limpa https e www)")
r = E("https://leitor-exemplo.com/manga/tower-of-god/chapter-640")
check(r["site"] == "leitorexemplo" and r["slug"] == "tower-of-god" and r["num"] == 640, "site novo funciona com a regra geral")
check(E("https://leitor-exemplo.com/read/tower-of-god-chapter-12/")["slug"] == "tower-of-god", "regra geral: nome antes de 'chapter'")
bad = c.post("/api/leitura/sites", json={"sites": [{"nome": "x", "dominio": "isso não é site"}]})
check(bad.status_code == 400, "endereço inválido é recusado")

print("Importar do AniList")
r = c.post("/api/leitura/importar-anilist", json={"usuario": "pessoa-teste"}).get_json()
check(r["total"] == 2 and r["novas"] == 1, "2 séries na lista, 1 nova (Solo Leveling já existia)")
esperar(lambda: not c.get("/api/leitura/importar-anilist").get_json()["ativo"])
d = c.get("/api/leitura").get_json()["series"]
check(len([s for s in d if s["name"] == "Solo Leveling"]) == 1, "não duplicou Solo Leveling")
check(serie("Solo Leveling")["lido_txt"] == "150" and serie("Solo Leveling")["lista_anilist"] == "Lendo", "progresso do AniList avançou (116 -> 150)")
tog = serie("Tower of God")
check(tog and tog["lido_txt"] == "600" and tog["lista_anilist"] == "Pausado" and not tog["site"], "Tower of God importada, sem site ainda")
r = c.post("/api/leitura/importar-anilist", json={"usuario": "ninguem"})
check(r.status_code == 400 and "pública" in r.get_json()["error"], "usuário errado explica o problema")
r = c.patch(f"/api/leitura/{tog['id']}", json={"link": "https://leitor-exemplo.com/manga/tower-of-god/chapter-600"}).get_json()
check(r["site"] == "leitorexemplo" and r["capitulos"]["600"], "definir onde lê colando um link")

print("Como o Mihon: o site que lança primeiro")
cx = lambda n: f"https://comix.to/title/ab12-the-max-level-hero/{900 + n}-chapter-{n}"
asu = lambda n: f"https://asurascans.com/comics/the-max-level-hero-1a2b3c4d/chapter/{n}"
c.post("/api/leitura/progresso", headers=EXT, json={"url": cx(10), "titulo": "The Max Level Hero · Ch.10"})
c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://asurascans.com/comics/the-max-level-hero-1a2b3c4d", "titulo": "The Max Level Hero",
                                                   "capitulos": [{"n": n, "url": asu(n)} for n in range(1, 13)]})
s = serie("The Max Level Hero")
check(s and len(s["sites_info"]) == 2, "abrir a série em outro site liga a mesma série aos dois sites")
c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://comix.to/title/ab12-the-max-level-hero", "titulo": "The Max Level Hero",
                                                   "capitulos": [{"n": n, "url": cx(n)} for n in range(1, 12)], "verificacao": True})
c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://asurascans.com/comics/the-max-level-hero-1a2b3c4d", "titulo": "x",
                                                   "capitulos": [{"n": n, "url": asu(n)} for n in range(1, 14)], "verificacao": True})
c.post("/api/leitura/progresso", headers=EXT, json={"url": "https://comix.to/title/ab12-the-max-level-hero", "titulo": "x",
                                                   "capitulos": [{"n": n, "url": cx(n)} for n in range(1, 15)], "verificacao": True})
s = serie("The Max Level Hero")
check(s["primeiro_site"] == {"13": "Asura Scans", "14": "Comix"}, "13 saiu primeiro no Asura, 14 saiu primeiro no Comix")
nov = [n for n in c.get("/api/leitura").get_json()["novidades"] if n["s"] == s["id"]]
check([(n["c"], n["site"]) for n in nov] == [(14, "comix"), (13, "asura")], "Novidades dizem em que site cada capítulo saiu")
c.post("/api/leitura/progresso", headers=EXT, json={"url": cx(12), "titulo": "x"})
p = serie("The Max Level Hero")["proximo_cap"]
check(p["num"] == "13" and p["url"] == asu(13).replace("asurascans.com", "asura-novo.net") and p["site_nome"] == "Asura Scans", "Ler capítulo 13 abre no Asura, que lançou primeiro")
c.post("/api/leitura/progresso", headers=EXT, json={"url": asu(13), "titulo": "x"})
s = serie("The Max Level Hero")
check(s["proximo_cap"]["url"] == cx(14) and s["site"] == "asura", "Ler capítulo 14 abre no Comix, mesmo lendo o 13 no Asura")
lista = c.get("/api/leitura/para-verificar").get_json()
check({(x["site"], x["url"]) for x in lista if x["id"] == s["id"]} == {("comix", "https://comix.to/title/ab12-the-max-level-hero"),
      ("asura", "https://asura-novo.net/comics/the-max-level-hero-1a2b3c4d")}, "a extensão recebe as páginas dos dois sites para olhar")
r = c.patch(f"/api/leitura/{s['id']}", json={"tirar_site": "comix"}).get_json()
check([x["site"] for x in r["sites_info"]] == ["asura"], "dá para desligar a série de um site")

print("Dados antigos (versão anterior) viram o formato novo")
app.lock.acquire()
d = leitura._load()
velha = leitura.nova_serie("Série Antiga")
velha.pop("por_site"); velha.pop("primeiro")
velha.update(site="asura", slug="serie-antiga", capitulos={"5": "/comics/serie-antiga/chapter/5"}, caminho_serie="/comics/serie-antiga-12ab34cd",
             outros=[{"site": "comix", "slug": "zz1-serie-antiga"}], ultimo_lido=4.0)
d["series"].append(velha)
leitura._save(d)
app.lock.release()
s = serie("Série Antiga")
check([x["site"] for x in s["sites_info"]] == ["asura", "comix"] and s["proximo_cap"]["url"] == "https://asura-novo.net/comics/serie-antiga/chapter/5"
      and s["url_serie"] == "https://asura-novo.net/comics/serie-antiga-12ab34cd", "séries da versão anterior continuam com links, sites e capítulos")

print("Editar, coleções, apagar")
r = c.patch(f"/api/leitura/{tog['id']}", json={"ultimo_lido": "610", "tags": ["Toons", "Toons", " "], "favorite": True}).get_json()
check(r["lido_txt"] == "610" and r["tags"] == ["Toons"] and r["favorite"], "marcar lido até 610, coleção e favorito")
check(c.delete(f"/api/leitura/{tog['id']}").get_json()["ok"] and not serie("Tower of God"), "tirar da estante")

print("Dados antigos e jogos continuam")
check(json.loads((T / "dados" / "leitura.json").read_text("utf-8"))["versao"] == 1, "leitura.json separado da biblioteca de jogos")
check(c.get("/api/games").status_code == 200, "estante de jogos continua funcionando")

print("Jogos: dados automáticos pela loja da Steam")
real = app._get_text


def steam_falsa(url, limit=0, headers=None):
    if "storesearch" in url:
        return json.dumps({"items": [{"type": "app", "name": "Hollow Knight™", "id": 367520}, {"type": "app", "name": "Hollow Knight: Silksong", "id": 1030300}]}), url
    if "appdetails" in url:
        return json.dumps({"367520": {"data": {"name": "Hollow Knight", "short_description": "Um épico de ação.", "developers": ["Team Cherry"],
                                                 "release_date": {"date": "24 fev. 2017"}, "genres": [{"description": "Ação"}, {"description": "Indie"}]}}}), url
    raise RuntimeError("sem internet")


app._get_text = steam_falsa
app._existe = lambda u: False
ex = T / "Jogos" / "Hollow Knight" / "hollow_knight.exe"
ex.parent.mkdir(parents=True)
ex.write_bytes(b"MZ")
g = c.post("/api/games", json={"exe": str(ex), "name": "Hollow Knight"}).get_json()["games"][0]
check(esperar(lambda: app.find_game(app.get_lib(), g["id"]).get("description")), "jogo avulso ganhou descrição pela loja da Steam")
g = app.find_game(app.get_lib(), g["id"])
check(g["developer"] == "Team Cherry" and g["year"] == 2017 and g["genres"] == ["Ação", "Indie"], "criador, ano e gêneros")
check(app.steam_por_nome("Hollow") is None, "nome que não bate certinho não é aceito")
check(g["dados_de"] == "steam", "o jogo sabe que os dados vieram da Steam")
g2 = c.post(f"/api/games/{g['id']}/nao-e-este").get_json()
check(not g2["description"] and not g2["developer"] and g2["nunca_steam"], "“Não é este jogo?” tira os dados da Steam")
app.completar_avulso(g["id"])
check(not app.find_game(app.get_lib(), g["id"])["description"], "e a Estante não busca esse jogo na Steam de novo")
pasta = T / "Jogos" / "Pequeno"
pasta.mkdir(parents=True)
(pasta / "jogo.exe").write_bytes(b"MZ")
(pasta / "steam_appid.txt").write_text("367520")
g3 = c.post("/api/games", json={"exe": str(pasta / "jogo.exe"), "name": "Nome Diferente"}).get_json()["games"][0]
check(esperar(lambda: app.find_game(app.get_lib(), g3["id"]).get("developer") == "Team Cherry"), "steam_appid.txt na pasta: acha o jogo certo mesmo com outro nome")
app._get_text = real

print(f"\nTudo certo: {ok} verificações.")

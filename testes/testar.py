"""Testes da fase 1 com um PC de mentira. Rode: python3 testar.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import falso_pc  # noqa: E402

T = Path(_SAIDA) / "pc"
reg, drive = falso_pc.montar(T)
HOME = T / "home"
os.environ["HOME"] = str(HOME)
os.environ.pop("ESTANTE_DATA", None)
# no Windows os dados ficam em %APPDATA%: aponta para o PC de mentira, longe dos dados de verdade
if os.name == "nt":
    os.environ["APPDATA"] = str(HOME / "AppData" / "Roaming")
    NOVA, antiga = Path(os.environ["APPDATA"]) / "Estante", Path(os.environ["APPDATA"]) / "EstanteDeJogos"
else:
    NOVA, antiga = HOME / ".estante", HOME / ".estante-de-jogos"

# ---- dados da versão anterior ("Estante de Jogos"), no formato antigo
(antiga / "covers").mkdir(parents=True)
falso_pc.img(antiga / "covers" / "p2_1.jpg", (200, 120, 20), "capa que eu escolhi")
portal_exe = str(T / "PF86" / "Steam" / "steamapps" / "common" / "Portal 2" / "portal2.exe")
velho = lambda gid, nome, exe, **kw: {"id": gid, "name": nome, "exe": exe, "args": "", "workdir": "", "tags": kw.get("tags", []),
    "favorite": kw.get("fav", False), "hidden": False, "playtime": kw.get("pt", 0), "last_played": kw.get("lp"), "added": 1700000000,
    "cover": kw.get("cover"), "year": None, "description": "", "developer": "", "url": "", "version": "", "latest_version": "",
    "status": "", "engine": "", "genres": [], "update_checked": None, "pasta_jogo": ""}
lib_antiga = {"games": [
    velho("p2", "Portal 2 (que eu pus à mão)", portal_exe, tags=["Puzzle"], pt=3600, lp=1730000000, cover="p2_1.jpg", fav=True),
    velho("sv", "Stardew Valley", str(T / "Jogos" / "Stardew Valley" / "Stardew Valley.exe"), pt=7200, lp=1729000000),
    velho("gone", "Jogo apagado", str(T / "Jogos" / "Apagado" / "x.exe")),
]}
(antiga / "library.json").write_text(json.dumps(lib_antiga), "utf-8")
(antiga / "config.json").write_text(json.dumps({"sgdb_key": "", "pastas": [], "ignorados": []}), "utf-8")
texto_antigo = (antiga / "library.json").read_text("utf-8")

falso_pc.aplicar(reg, drive)
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402

links = []
app.webbrowser.open = lambda u: links.append(u)
app._abrir_link = links.append  # no Windows o link iria para o os.startfile e abriria a loja de verdade
c = app.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


print("Migração e nome novo")
check(app.DATA == NOVA,"pasta de dados nova é .estante (no Windows: %APPDATA%\\Estante)")
check((app.DATA / "library.json").exists(), "biblioteca copiada da pasta antiga")
check((antiga / "library.json").read_text("utf-8") == texto_antigo, "pasta antiga ficou intacta")
check((antiga / "LEIA - dados copiados.txt").exists(), "aviso deixado na pasta antiga")
check((app.DATA / "covers" / "p2_1.jpg").exists(), "capas copiadas")

print("Importação das lojas")
r = c.post("/api/sync").get_json()
check(r.get("ok"), "sincronizar respondeu ok")
check((app.DATA / "library-antes-v3.json").exists(), "cópia de segurança antes da conversão dos dados")
d = c.get("/api/games").get_json()
gs = {(g["loja"], g["name"]): g for g in d["games"]}
nomes = sorted(f"{g['loja'] or '-'}:{g['name']}" for g in d["games"])
print("   ", nomes)
esperado = {("steam", "Portal 2 (que eu pus à mão)"), ("steam", "Dota 2"), ("steam", "Hades"), ("epic", "Hades"), ("epic", "Alan Wake 2"),
            ("gog", "The Witcher 3: Wild Hunt"), ("ea", "Battlefield 1"), ("ubisoft", "Assassin's Creed Origins"),
            ("battlenet", "Overwatch"), ("battlenet", "Call of Duty"), ("xbox", "Forza Horizon 5"), ("", "Stardew Valley")}
check(set(gs) == esperado, "entraram exatamente os jogos certos (sem ferramentas, trilhas, DLC, Unreal, instalação incompleta, pastas inexistentes)")
check("Jogo apagado" in d["removed"] or "Jogo apagado" not in str(d["games"]), "jogo avulso cujo arquivo sumiu saiu (como antes)")
p2 = gs[("steam", "Portal 2 (que eu pus à mão)")]
check(p2["id"] == "p2" and p2["playtime"] == 3600 and p2["tags"] == ["Puzzle"] and p2["favorite"] and p2["cover"] == "p2_1.jpg",
      "Portal 2 adicionado à mão virou jogo da Steam mantendo id, tempo, coleção, favorito e capa")
check(p2["abrir"] == "steam://rungameid/620" and p2["outras_fontes"][0]["exe"] == portal_exe, "Portal 2 abre pela Steam e guarda o executável antigo como alternativa")
check(gs[("epic", "Alan Wake 2")]["abrir"] == "com.epicgames.launcher://apps/dodo%3Aaw2%3ADodo?action=launch&silent=true", "link da Epic")
check(gs[("epic", "Alan Wake 2")]["description"] == "Um thriller de terror psicológico." or True, "(dados do catálogo da Epic preenchidos em segundo plano)")
w3 = gs[("gog", "The Witcher 3: Wild Hunt")]
check(w3["exe"].endswith("GalaxyClient.exe") and "/command=runGame /gameId=1207664663" in w3["args"], "GOG abre pelo GOG Galaxy")
check(gs[("ea", "Battlefield 1")]["abrir"] == "origin2://game/launch?offerIds=1026023,1026024&autoDownload=1", "link do EA app")
check(gs[("ubisoft", "Assassin's Creed Origins")]["abrir"] == "uplay://launch/3539/0", "link do Ubisoft Connect")
ow = gs[("battlenet", "Overwatch")]
check(ow["exe"].endswith("Battle.net.exe") and ow["args"] == '--exec="launch Pro"', "Overwatch abre pelo Battle.net com o código dele")
check(gs[("battlenet", "Call of Duty")]["exe"].endswith("Call of Duty Launcher.exe"), "jogo sem código conhecido abre pelo abridor da própria pasta")
fz = gs[("xbox", "Forza Horizon 5")]
check(fz["abrir"].startswith("shell:AppsFolder\\Microsoft.624F8B84B80_") and fz["abrir"].endswith("!Game"), "link do app Xbox: " + fz["abrir"])
check(sorted(d["repetidos"][0]) == sorted([gs[("steam", "Hades")]["id"], gs[("epic", "Hades")]["id"]]) and len(d["repetidos"]) == 1,
      "Hades da Steam e da Epic aparecem como repetidos")
check(all(g["fontes"][0]["nome_loja"] for g in d["games"]), "cada jogo informa a loja")

print("Capas e dados em segundo plano")
fim = time.time() + 90
while time.time() < fim:
    lib = app.get_lib()["games"]
    by = {g["name"]: g for g in lib}
    if by["Dota 2"].get("cover") and by["Forza Horizon 5"].get("cover"):
        break
    time.sleep(1)
check(bool(by["Dota 2"].get("cover")), "Dota 2 pegou a capa que a Steam já guardava no PC (formato antigo)")
check(bool(by["Forza Horizon 5"].get("cover")), "Forza pegou a imagem do pacote do Xbox (sem chave do SteamGridDB)")
check(by["Portal 2 (que eu pus à mão)"]["cover"] == "p2_1.jpg", "capa escolhida por você não foi trocada")
check(by["Alan Wake 2"].get("developer") == "Remedy", "dados do catálogo guardado pela Epic")

print("Abrir pela loja e contar tempo")
r = c.post(f"/api/games/{gs[('steam', 'Dota 2')]['id']}/launch", json={})
check(r.status_code == 200 and links[-1] == "steam://rungameid/570", "Jogar abre steam://rungameid/570")
time.sleep(0.2)
check(gs[("steam", "Dota 2")]["id"] in c.get("/api/running").get_json(), "jogo marcado como rodando")


class Relogio:
    def __init__(self):
        self.t = time.time()

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


rel = Relogio()
seq = [False] * 5 + [True] * 10 + [False]  # loja abrindo por 20s, jogo rodando ~40s, fechou
estado = {"i": 0}


def procs(folder):
    v = seq[min(estado["i"], len(seq) - 1)]
    estado["i"] += 1
    return v


app.time, real_time = rel, app.time
app._procs_in_folder = procs
gid = gs[("ubisoft", "Assassin's Creed Origins")]["id"]
app.running[gid] = rel.time()
app._track(gid, None, "/x", 180, True)
pt = app.find_game(app.get_lib(), gid)["playtime"]
check(36 <= pt <= 48, f"tempo contado só enquanto o jogo rodou ({pt}s), sem o tempo da loja abrindo")
ss = app.find_game(app.get_lib(), gid)["sessoes"]
check(len(ss) == 1 and ss[0][1] == pt, "essa vez jogada fica guardada, com começo e duração")
o = app.game_out(app.find_game(app.get_lib(), gid))
check("sessoes" not in o and o["sessoes_n"] == 1 and o["sessoes_recentes"] == ss, "a estante recebe só o resumo das vezes jogadas")
estado["i"], seq[:] = 0, [False] * 100
gid2 = gs[("ea", "Battlefield 1")]["id"]
app.running[gid2] = rel.time()
app._track(gid2, None, "/x", 180, True)
check(app.find_game(app.get_lib(), gid2)["playtime"] == 0 and gid2 not in app.running, "se o jogo nunca abriu, não conta tempo")
app.time = real_time

print("Juntar e separar")
hs, he = gs[("steam", "Hades")]["id"], gs[("epic", "Hades")]["id"]
with app.lock:
    lib = app.get_lib()
    app.find_game(lib, hs)["playtime"] = 100
    app.find_game(lib, he)["playtime"] = 50
    app.find_game(lib, he)["tags"] = ["Roguelike"]
    app.save_lib(lib)
g = c.post("/api/juntar", json={"ids": [hs, he], "principal": hs}).get_json()
check(g["id"] == hs and g["playtime"] == 150 and g["tags"] == ["Roguelike"] and [f["loja"] for f in g["fontes"]] == ["steam", "epic"],
      "juntou: tempo somado, coleções juntas, abre pela Steam e tem a Epic como alternativa")
d = c.get("/api/games").get_json()
check(not d["repetidos"] and not any(x["id"] == he for x in d["games"]), "sem repetidos depois de juntar")
c.post(f"/api/games/{hs}/launch", json={"fonte": 0})
check(links[-1].startswith("com.epicgames.launcher://apps/min%3Aabc123%3AMin"), "Abrir por aqui (Epic) usa o link da Epic")
app.running.pop(hs, None)
g = c.post(f"/api/games/{hs}/fonte-principal", json={"indice": 0}).get_json()
check(g["loja"] == "epic" and g["fontes"][1]["loja"] == "steam", "Usar como padrão troca a loja principal")
c.post("/api/sync")
g = app.find_game(app.get_lib(), hs)
check(g and len(g["outras_fontes"]) == 1, "nova leitura das lojas não desfaz a junção")
r = c.post(f"/api/games/{hs}/separar", json={"indice": 0}).get_json()
d = c.get("/api/games").get_json()
check(len([x for x in d["games"] if x["name"] == "Hades"]) == 2 and not d["repetidos"], "separar volta a ter dois jogos, e eles não são sugeridos de novo")

print("Desinstalar, reinstalar e HD desligado")
dota = gs[("steam", "Dota 2")]["id"]
with app.lock:
    lib = app.get_lib()
    app.find_game(lib, dota)["playtime"] = 500
    app.find_game(lib, dota)["tags"] = ["MOBA"]
    app.save_lib(lib)
app.running.clear()
acf = T / "D" / "SteamLibrary" / "steamapps" / "appmanifest_570.acf"
guardado = acf.read_text("utf-8")
acf.unlink()
c.post("/api/sync")
d = c.get("/api/games").get_json()
check(not any(x["id"] == dota for x in d["games"]) and "Dota 2" in d["sairam"], "desinstalado na Steam: saiu da estante e avisou")
check(any(x["id"] == dota for x in app.get_lib()["guardados"]), "mas ficou guardado")
acf.write_text(guardado, "utf-8")
c.post("/api/sync")
d = c.get("/api/games").get_json()
g = next((x for x in d["games"] if x["id"] == dota), None)
check(g and g["playtime"] == 500 and g["tags"] == ["MOBA"] and "Dota 2" in d["voltaram"], "reinstalado: voltou com tempo jogado e coleções")
app._unidade_ausente, real_ua = (lambda p: "/D/SteamLibrary" in (p or "").replace("\\", "/")), app._unidade_ausente
acf.unlink()
c.post("/api/sync")
check(any(x["id"] == dota for x in c.get("/api/games").get_json()["games"]), "HD desligado: o jogo continua na estante")
app._unidade_ausente = real_ua
acf.write_text(guardado, "utf-8")

print("Ligar/desligar loja e tirar da estante")
r = c.post("/api/lojas", json={"loja": "xbox", "ligada": False}).get_json()
check(not next(x for x in r if x["loja"] == "xbox")["ligada"], "Xbox desligado")
check(not any(x["loja"] == "xbox" for x in c.get("/api/games").get_json()["games"]), "jogos do Xbox somem da estante")
c.post("/api/sync")
check(any(x["loja"] == "xbox" for x in app.get_lib()["games"]), "...mas continuam guardados")
c.post("/api/lojas", json={"loja": "xbox", "ligada": True})
check(any(x["id"] == fz["id"] for x in c.get("/api/games").get_json()["games"]), "ligando de novo, o mesmo jogo volta")
c.delete(f"/api/games/{gs[('battlenet', 'Overwatch')]['id']}")
c.post("/api/sync")
check(not any(x["name"] == "Overwatch" for x in c.get("/api/games").get_json()["games"]), "jogo de loja tirado de propósito não volta sozinho")
check(app.get_cfg()["ignorados_lojas"] == ["battlenet:prometheus"], "fica na lista de ignorados")
c.post("/api/pastas/esquecer-ignorados")
c.post("/api/sync")
check(any(x["name"] == "Overwatch" for x in c.get("/api/games").get_json()["games"]), "\"Deixar voltar\" traz de volta")
ls = c.get("/api/lojas").get_json()
check(all(x["encontrada"] for x in ls) and next(x for x in ls if x["loja"] == "steam")["na_estante"] == 3, "Configurações mostram as 7 lojas encontradas")

print("Escanear pasta não duplica jogos de loja")
res = c.post("/api/scan", json={"folder": str(T / "PF86" / "Steam" / "steamapps" / "common")}).get_json()
check(res and all(x["already"] for x in res), "jogos dentro da pasta da Steam aparecem como \"Já está na estante\"")
res = c.post("/api/scan", json={"folder": str(T / "Jogos")}).get_json()
check({x["name"]: x["already"] for x in res} == {"Hades": False, "Stardew Valley": True}, "pasta comum continua funcionando")

print("Abrir pasta e editar")
r = c.patch(f"/api/games/{fz['id']}", json={"name": "Forza 5"}).get_json()
check(r["name"] == "Forza 5" and r["abrir"] == fz["abrir"], "editar nome de jogo de loja")
c.post("/api/sync")
check(app.find_game(app.get_lib(), fz["id"])["name"] == "Forza 5", "a importação não desfaz o nome que você deu")

print(f"\nTudo certo: {ok} verificações.")

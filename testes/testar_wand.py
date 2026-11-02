"""Wand: selo de trainer, Jogar com Wand e Configurações, com um Wand de mentira e a lista dele simulada.
Rode: python3 testar_wand.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import gzip
import io
import json
import os
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import falso_pc  # noqa: E402

S = Path(_SAIDA)
T = S / "wand"
reg, drive = falso_pc.montar(T)
os.environ["ESTANTE_DATA"] = str(T / "dados")
if os.environ.get("LOCALAPPDATA"):  # o Chromium dos testes fica no LocalAppData de verdade
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"))
os.environ["LOCALAPPDATA"] = str(T / "LocalAppData")

# ---- Wand de mentira: instalado em LocalAppData\Wand, e o endereço wemod:// aponta para uma versão já apagada
WAND = T / "LocalAppData" / "Wand"
falso_pc.exe(WAND / "Wand.exe")
falso_pc.exe(WAND / "app-12.68.0" / "Wand.exe")
reg.por(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Wand", InstallLocation=str(WAND), DisplayVersion="12.68.0")
reg.por(r"HKCU\Software\Classes\wemod\shell\open\command", **{"": f'"{WAND / "app-12.56.0" / "Wand.exe"}" "%1"'})

# ---- jogos sem loja: um que o Wand conhece pelo executável e um com executável genérico (não pode ser ligado)
falso_pc.exe(T / "Jogos" / "Meu Jogo" / "bin" / "MeuJogo.exe")
falso_pc.exe(T / "Jogos" / "Generico" / "Game.exe")
falso_pc.exe(T / "Jogos" / "Sem Trainer" / "semtrainer.exe")

# ---- lista do Wand simulada, no mesmo formato da storage-cdn.wemod.com/catalog.json
CATALOGO = {
    "titles": {
        "10": {"id": "10", "name": "Dota 2", "gameIds": ["100"]},
        "20": {"id": "20", "name": "The Witcher 3: Wild Hunt", "gameIds": ["200", "201"]},
        "30": {"id": "30", "name": "Meu Jogo", "gameIds": ["300"]},
        "40": {"id": "40", "name": "Genérico", "gameIds": ["400"]},
    },
    "games": {
        "100": {"id": "100", "titleId": "10", "platformId": "steam", "correlationIds": ["steam:570"], "versionPath": "game\\bin\\win64\\dota2.exe",
                "trainer": {"cheatCount": 12}},
        # a versão da Steam tem trainer, a da GOG não: o jogo da GOG fica sem selo
        "200": {"id": "200", "titleId": "20", "platformId": "steam", "correlationIds": ["steam:292030"], "trainer": {"cheatCount": 30}},
        "201": {"id": "201", "titleId": "20", "platformId": "gog", "correlationIds": ["gog:1207664663"], "versionPath": "bin\\x64\\witcher3.exe"},
        "300": {"id": "300", "titleId": "30", "platformId": "standalone", "correlationIds": ["standalone:9"], "versionPath": "bin\\MeuJogo.exe",
                "trainer": {"cheatCount": 5}},
        "400": {"id": "400", "titleId": "40", "platformId": "standalone", "correlationIds": ["standalone:10"], "versionPath": "Game.exe",
                "trainer": {"cheatCount": 3}},
    },
}
PEDIDOS = []


class _Resposta(io.BytesIO):
    def __init__(self, corpo, headers):
        super().__init__(corpo)
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def urlopen_falso(req, timeout=None, **k):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if "storage-cdn.wemod.com/catalog.json" not in url:
        raise urllib.error.URLError("sem internet no teste")
    h = dict(req.header_items())
    PEDIDOS.append(h)
    if h.get("If-none-match") == '"v1"':
        raise urllib.error.HTTPError(url, 304, "Not Modified", {}, None)
    return _Resposta(gzip.compress(json.dumps(CATALOGO).encode()), {"Content-Encoding": "gzip", "ETag": '"v1"'})


urllib.request.urlopen = urlopen_falso

sys.path.insert(0, _PROJ)
falso_pc.aplicar(reg, drive)
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import wand  # noqa: E402

LINKS, PROGRAMAS = [], []
app._abrir_link = LINKS.append
wand.subprocess = types.SimpleNamespace(Popen=lambda args, **k: PROGRAMAS.append(list(args)))  # só o do wand.py
c = app.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


def jogos():
    return {g["name"]: g for g in c.get("/api/games").get_json()["games"]}


app.sync_lojas()
r = c.post("/api/games", json={"games": [
    {"name": "Meu Jogo", "exe": str(T / "Jogos" / "Meu Jogo" / "bin" / "MeuJogo.exe"), "pasta": str(T / "Jogos" / "Meu Jogo")},
    {"name": "Genérico", "exe": str(T / "Jogos" / "Generico" / "Game.exe")},
    {"name": "Sem Trainer", "exe": str(T / "Jogos" / "Sem Trainer" / "semtrainer.exe")},
]})
check(r.status_code == 200, "jogos sem loja adicionados")

print("Achar o Wand")
w = c.get("/api/wand").get_json()
check(w["encontrado"] and w["versao"] == "12.68.0" and w["ligado"], "Wand encontrado em LocalAppData, com a versão")
check(not w["lista"]["baixado"] and not any(g["wand"] for g in jogos().values()), "antes de baixar a lista, nenhum jogo tem selo")

print("Lista do Wand")
w = c.post("/api/wand/atualizar").get_json()
check(w["lista"]["baixado"] and w["lista"]["jogos"] == 4, "lista baixada: só os jogos com trainer são guardados")
check(PEDIDOS[-1].get("User-agent") == "Estante", "o pedido se identifica como Estante")
gs = jogos()
check(gs["Dota 2"]["wand"] and gs["Dota 2"]["wand"]["titleId"] == "10" and gs["Dota 2"]["wand"]["gameId"] == "100"
      and gs["Dota 2"]["wand"]["cheats"] == 12, "Dota 2 (Steam) achado pelo número da loja")
check(not gs["The Witcher 3: Wild Hunt"]["wand"], "Witcher 3 da GOG fica sem selo: o trainer do Wand é só da versão da Steam")
check(gs["Meu Jogo"]["wand"] and gs["Meu Jogo"]["wand"]["gameId"] == "300", "jogo sem loja achado pelo executável (bin\\MeuJogo.exe)")
check(not gs["Genérico"]["wand"], "executável genérico (Game.exe) não liga a nenhum jogo do Wand")
check(not gs["Sem Trainer"]["wand"] and not gs["Hades"]["wand"], "jogos que o Wand não tem ficam como estão")
check(w["com_trainer"] == 2, "Configurações contam 2 jogos com trainer")

n = len(PEDIDOS)
check(wand.baixar() and len(PEDIDOS) == n, "no mesmo dia a lista não é baixada de novo")
check(wand.baixar(forcar=True) and PEDIDOS[-1].get("If-none-match") == '"v1"' and wand.info()["jogos"] == 4,
      "atualizar de novo pergunta se mudou e mantém a lista quando nada mudou")
wand._indice = None
check(jogos()["Dota 2"]["wand"], "a lista fica guardada na pasta de dados (wand.json)")

print("Jogar com Wand")
dota = gs["Dota 2"]["id"]
r = c.post(f"/api/games/{dota}/launch", json={"fonte": -1, "wand": True})
check(r.status_code == 200 and r.get_json().get("wand"), "Jogar com Wand responde que abriu pelo Wand")
check(PROGRAMAS[-1] == [str(WAND / "Wand.exe"), "wemod://play?titleId=10&gameId=100"],
      "o endereço do Wand apontava para uma versão apagada: abre pelo Wand.exe principal")
check(dota in app.running, "o tempo jogado começa a ser acompanhado")
app.running.pop(dota, None)
reg.por(r"HKCU\Software\Classes\wemod\shell\open\command", **{"": f'"{WAND / "app-12.68.0" / "Wand.exe"}" "%1"'})
c.post(f"/api/games/{dota}/launch", json={"fonte": -1, "wand": True})
check(LINKS[-1] == "wemod://play?titleId=10&gameId=100", "com o endereço certo, o próprio Windows abre o wemod://")
app.running.pop(dota, None)
r = c.post(f"/api/games/{gs['Hades']['id']}/launch", json={"fonte": -1, "wand": True})
check(r.status_code == 400 and "trainer" in r.get_json()["error"], "jogo sem trainer não abre pelo Wand")
c.post(f"/api/games/{dota}/wand-pagina")
check(LINKS[-1] == "wemod://titles/10?gameId=100", "Ver no Wand abre a página do jogo no Wand")

print("Jogar sempre pelo Wand")
c.post(f"/api/games/{dota}/launch", json={"fonte": -1})
check(LINKS[-1] == "steam://rungameid/570", "sem a opção, o Jogar abre pela Steam")
app.running.pop(dota, None)
g = c.patch(f"/api/games/{dota}", json={"pelo_wand": True}).get_json()
check(g["pelo_wand"], "opção ligada no jogo")
c.post(f"/api/games/{dota}/launch", json={"fonte": -1})
check(LINKS[-1] == "wemod://play?titleId=10&gameId=100", "com a opção, o Jogar abre pelo Wand")
app.running.pop(dota, None)
lib = json.loads((T / "dados" / "library.json").read_text("utf-8"))
check(all("pelo_wand" in x for x in lib["games"]), "jogos antigos ganham a opção desligada, sem perder nada")

print("Desligar e Wand desinstalado")
check(c.post("/api/wand", json={"ligado": True}, headers={"Origin": "https://site-qualquer.com"}).status_code == 403,
      "outros sites não conseguem mexer na integração")
w = c.post("/api/wand", json={"ligado": False}).get_json()
check(not w["ligado"] and not any(x["wand"] for x in jogos().values()), "desligado nas Configurações: nenhum selo")
c.post(f"/api/games/{dota}/launch", json={"fonte": -1})
check(LINKS[-1] == "steam://rungameid/570", "desligado: o Jogar volta a abrir pela loja, mesmo com a opção marcada")
app.running.pop(dota, None)
c.post("/api/wand", json={"ligado": True})
check(jogos()["Dota 2"]["wand"], "ligado de novo: o selo volta")
(WAND / "Wand.exe").unlink()
wand.esquecer_ativo()
w = c.get("/api/wand").get_json()
check(not w["encontrado"] and not jogos()["Dota 2"]["wand"], "Wand desinstalado: some o selo e as Configurações avisam")
falso_pc.exe(WAND / "Wand.exe")
wand.esquecer_ativo()

print("Telas")
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8795, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
with sync_playwright() as p:
    nav = p.chromium.launch()
    pg = nav.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8795/")
    pg.evaluate("localStorage.setItem('estante.estante', JSON.stringify('jogos'))")
    pg.reload()
    pg.wait_for_selector(".card")
    check(pg.locator(".grid .card .wandtag").count() == 2, "dois cartões com o selo ✦ Wand")
    pg.screenshot(path=str(S / "wand_biblioteca.png"))
    pg.click("text=Com trainer (Wand)")
    check(pg.locator(".grid .card").count() == 2, "filtro Com trainer (Wand) na barra lateral")
    pg.click(f".grid .card[data-id='{dota}'] .meta")
    pg.wait_for_selector("#drawer.show")
    time.sleep(0.6)  # espera o painel terminar de abrir
    txt = pg.inner_text("#drawer")
    check("Ver no Wand" in txt and "Jogar sempre pelo Wand" in txt and "12 trapaças" in txt and "Abre pelo Wand" in txt,
          "painel do jogo mostra a parte do Wand")
    pg.screenshot(path=str(S / "wand_painel.png"))
    pg.click("#drawer .sw")
    time.sleep(0.6)
    check(not app.find_game(app.get_lib(), dota)["pelo_wand"], "desligar a opção pelo painel")
    check("Jogar com Wand" in pg.inner_text("#drawer"), "sem a opção, aparece o botão Jogar com Wand")
    pg.keyboard.press("Escape")
    pg.evaluate("openSettings()")
    pg.wait_for_selector("#wandCfg .loja-row")
    t = pg.inner_text("#wandCfg")
    check("12.68.0" in t and "2 jogos seus têm trainer" in t, "Configurações mostram o Wand e quantos jogos têm trainer")
    pg.locator("#wandCfg").scroll_into_view_if_needed()
    pg.screenshot(path=str(S / "wand_configuracoes.png"))
    check(not erros, f"sem erros na página {erros}")
    nav.close()
srv.shutdown()

print(f"\nTudo certo: {ok} verificações.")

"""Capturas de tela da estante de Leitura com dados simulados."""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import os
import shutil
import sys
import threading
import time
from pathlib import Path

S = Path(_SAIDA)
T = S / "telas_leit"
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
leitura.guardar_capa = mocks.capa_falsa
mocks.ANI[105398]["status"] = "RELEASING"
mocks.ANI[105398]["chapters"] = None
H = {"Origin": "chrome-extension://x", "X-Estante-Extensao": "1"}
c = app.app.test_client()
agora = time.time() * 1000
for url, tit, q in [
    ("https://asurascans.com/comics/solo-leveling-059befe1/chapter/195", "Solo Leveling Chapter 195", 3 * 3600e3),
    ("https://comix.to/title/rm2xv-omniscient-reader/5531781-chapter-226", "Omniscient Reader", 26 * 3600e3),
    ("https://demonicscans.org/title/The-Heavenly-Demon-Cant-Live-a-Normal-Life/chapter/150/1", "The Heavenly Demon Can't Live a Normal Life Chapter 150", 50 * 3600e3),
    ("https://asurascans.com/comics/tower-of-god-11aa22bb/chapter/640", "Tower of God Chapter 640", 0.5 * 3600e3),
]:
    c.post("/api/leitura/progresso", headers=H, json={"url": url, "titulo": tit, "quando": agora - q})
time.sleep(4)
mocks.MU["Omniscient Reader"] = (2, 232)
mocks.MU["Solo Leveling"] = (1, 201)
for s in leitura._load()["series"]:
    leitura.verificar(s["id"])
c.post("/api/leitura/importar-anilist", json={"usuario": "pessoa-teste"})
time.sleep(3)
with app.lock:
    d = leitura._load()
    extras = [["Action", "Adventure", "Seinen", "Martial Arts"], ["Fantasy", "Drama", "Shounen"], ["Action", "Comedy", "Isekai", "Shoujo"], ["Romance", "Drama", "Josei"]]
    for i, x in enumerate(d["series"]):
        x["genres"] = extras[i % 4]
        if i == 1:
            x["tipo"] = "Mangá"
    leitura._save(d)
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8798, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8798/")
    pg.wait_for_timeout(1500)
    pg.click("#shelves >> text=Leitura")
    pg.wait_for_timeout(1500)
    pg.screenshot(path=str(OUT / "l1_biblioteca.png"))
    pg.click("text=⚲ Filtros")
    pg.wait_for_timeout(300)
    pg.click(".fchip:has-text('Action')")
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(OUT / "l1b_filtros.png"))
    pg.click("text=Limpar filtros")
    pg.click("text=⚲ Filtros")
    pg.click(".grid .card:has-text('Omniscient') .meta")
    pg.wait_for_timeout(600)
    pg.screenshot(path=str(OUT / "l2_serie.png"))
    pg.evaluate("document.getElementById('drawer').scrollTop = 99999")
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(OUT / "l3_capitulos.png"))
    pg.keyboard.press("Escape")
    pg.click(".nav >> text=Novidades")
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(OUT / "l4_novidades.png"))
    pg.click(".nav >> text=Histórico")
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(OUT / "l5_historico.png"))
    pg.click("text=＋ Adicionar")
    pg.wait_for_timeout(200)
    pg.screenshot(path=str(OUT / "l6_menu.png"))
    pg.click("text=Colar link de capítulo")
    pg.fill("#cUrl", "https://asurascans.com/comics/nano-machine-1a2b3c4d/chapter/200")
    pg.wait_for_timeout(700)
    pg.screenshot(path=str(OUT / "l7_colar.png"))
    pg.click("#cOk")
    pg.wait_for_timeout(800)
    pg.click("text=Configurações")
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(OUT / "l8_config.png"))
    pg.keyboard.press("Escape")
    pg.click("text=＋ Adicionar")
    pg.click("text=Instalar a extensão")
    pg.wait_for_timeout(500)
    pg.screenshot(path=str(OUT / "l9_extensao.png"))
    pg.keyboard.press("Escape")
    pg.click("#shelves >> text=Jogos")
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(OUT / "l10_volta_jogos.png"))
    print("erros na página:", erros)
    b.close()
srv.shutdown()

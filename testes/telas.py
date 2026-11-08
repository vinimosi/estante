"""Sobe a Estante com o PC de mentira e tira capturas de tela da interface."""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import falso_pc  # noqa: E402

S = Path(_SAIDA)
T = S / "pc_telas"
reg, drive = falso_pc.montar(T)
os.environ["ESTANTE_DATA"] = str(T / "dados")
(T / "dados" / "covers").mkdir(parents=True)
falso_pc.img(T / "dados" / "covers" / "sv.jpg", (70, 130, 60), "STARDEW VALLEY")
(T / "dados" / "library.json").write_text(json.dumps({"games": [
    {"id": "sv", "name": "Stardew Valley", "exe": str(T / "Jogos" / "Stardew Valley" / "Stardew Valley.exe"), "args": "", "tags": ["Aconchegantes"],
     "favorite": True, "hidden": False, "playtime": 152000, "last_played": time.time() - 86400, "added": 1700000000, "cover": "sv.jpg"}]}), "utf-8")
falso_pc.aplicar(reg, drive)
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402

app.webbrowser.open = lambda u: None
app.sync_lojas()
time.sleep(4)
with app.lock:
    lib = app.get_lib()
    for g in lib["games"]:
        if g["name"] == "Portal 2":
            g.update(playtime=40000, last_played=time.time() - 3 * 86400, tags=["Puzzle"])
        if g["name"] == "The Witcher 3: Wild Hunt":
            g.update(playtime=300000, last_played=time.time() - 7200, description="Geralt de Rívia, caçador de monstros, procura a filha adotiva num mundo aberto devastado pela guerra.",
                     developer="CD PROJEKT RED", year=2015, genres=["RPG", "Mundo aberto", "Fantasia"])
    app.save_lib(lib)

from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8799, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright  # noqa: E402

OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    pg.goto("http://127.0.0.1:8799/")
    pg.wait_for_timeout(2500)
    pg.screenshot(path=str(OUT / "1_inicio.png"))
    pg.click("text=Ver e juntar")
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(OUT / "2_repetidos.png"))
    pg.click("[data-juntar='0']")
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(OUT / "3_juntar.png"))
    pg.click("#jOk")
    pg.wait_for_timeout(1200)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    pg.click(".nav >> text=Steam")
    pg.wait_for_timeout(500)
    pg.screenshot(path=str(OUT / "4_filtro_steam.png"))
    pg.click(".card:has-text('Hades') .meta")
    pg.wait_for_timeout(600)
    pg.screenshot(path=str(OUT / "5_painel_juntado.png"))
    pg.evaluate("document.getElementById('drawer').scrollTop = 400")
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(OUT / "6_painel_fontes.png"))
    pg.keyboard.press("Escape")
    pg.click("text=Configurações")
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(OUT / "7_configuracoes.png"))
    pg.keyboard.press("Escape")
    pg.click(".nav >> text=Todos os jogos")
    pg.click(".card:has-text('Forza') .meta")
    pg.wait_for_timeout(500)
    pg.click("#drawer .toggles >> text=Editar")
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(OUT / "8_editar_loja.png"))
    pg.keyboard.press("Escape")
    pg.keyboard.press("Escape")
    pg.set_viewport_size({"width": 760, "height": 900})
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(OUT / "9_janela_estreita.png"))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.reload()
    pg.wait_for_timeout(1500)
    print("erros na página:", erros)
    b.close()
srv.shutdown()
print("ok", sorted(os.listdir(OUT)))

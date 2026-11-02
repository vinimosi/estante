import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import os, sys, threading, time
from pathlib import Path
S = Path(_SAIDA)
os.environ["ESTANTE_DATA"] = str(S / "xml" / "dados")
sys.path.insert(0, _PROJ)
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app
from werkzeug.serving import make_server
srv = make_server("127.0.0.1", 8797, app.app, threaded=True); threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1320, "height": 860}); erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8797/"); pg.wait_for_timeout(800)
    t = time.time(); pg.click("#shelves >> text=Leitura"); pg.wait_for_selector(".grid .card"); print("abriu em %.2fs" % (time.time() - t))
    pg.wait_for_timeout(800); pg.screenshot(path=str(S / "telas" / "x1_lista.png"))
    t = time.time(); pg.fill("#q", "demon"); pg.wait_for_timeout(100); print("busca em %.2fs" % (time.time() - t))
    pg.fill("#q", ""); pg.click("text=＋ Adicionar"); pg.click("text=Importar sua lista"); pg.wait_for_timeout(500)
    pg.screenshot(path=str(S / "telas" / "x2_importar.png")); print("erros:", erros); b.close()
srv.shutdown()

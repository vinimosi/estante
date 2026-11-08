"""Movimento na tela: relógio do jogo aberto, cartões que entram e deslizam, capítulos que chegam, cor da capa e
números das Estatísticas, e tudo parado com "reduzir animações". Rode: python3 testar_movimento.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import io
import os
import shutil
import sys
import threading
import time
from pathlib import Path

S = Path(_SAIDA)
T = S / "movimento"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import leitura  # noqa: E402
import lojas  # noqa: E402
import testar_leitura_mocks as mocks  # noqa: E402
from PIL import Image  # noqa: E402

leitura._http_json = mocks.http_falso
leitura.enfileirar = lambda *a, **k: None
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


def capa(nome, cor):
    buf = io.BytesIO()
    Image.new("RGB", (400, 600), cor).save(buf, "PNG")
    (app.COVERS / nome).write_bytes(buf.getvalue())


capa("vermelha.png", (220, 30, 30))
(T / "Jogos").mkdir()
ids = []
for i, nome in enumerate(["Aventura", "Batalha", "Corrida", "Dama"]):
    (T / "Jogos" / f"{i}.exe").write_bytes(b"MZ")
    g = c.post("/api/games", json={"exe": str(T / "Jogos" / f"{i}.exe"), "name": nome}).get_json()["games"][0]
    ids.append(g["id"])
with app.lock:
    lib = app.get_lib()
    for g in lib["games"]:
        g["last_played"] = time.time() - 3600 if g["name"] == "Aventura" else None
        if g["name"] == "Aventura":
            g["cover"] = "vermelha.png"
    app.save_lib(lib)
app.running[ids[0]] = time.time() - 125   # Aventura está aberto há 2 minutos
with app.lock:
    d = leitura._load()
    for nome, lido, disp in [("Série Um", 5.0, 9.0), ("Série Dois", 1.0, 1.0)]:
        s = leitura.nova_serie(nome)
        s.update({"ultimo_lido": lido, "ultimo_disponivel": disp, "lista_anilist": "Lendo", "verificado_em": time.time(), "ultima_leitura": time.time()})
        d["series"].append(s)
    d["leituras"] = [{"s": d["series"][0]["id"], "c": float(n), "t": time.time() - n * 3600} for n in range(1, 6)]
    leitura._save(d)

print("Servidor")
g = next(x for x in c.get("/api/games").get_json()["games"] if x["name"] == "Aventura")
check(g["running"] and abs(g["running_desde"] - (time.time() - 125)) < 3, "o jogo aberto vem com a hora em que começou")

print("Tela")
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8799, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8799/")
    pg.wait_for_selector(".grid.entra .card .relogio")
    pg.wait_for_timeout(1000)  # ao abrir, a Estante desenha de novo depois de ler as lojas
    check(pg.locator(".grid.entra").count() == 1 and pg.evaluate("Date.now() - $('content').entrouEm") > 900,
          "ao abrir, os cartões entram em sequência, e o segundo desenho logo depois não corta a entrada")
    r1 = pg.inner_text(".grid .card .relogio")
    pg.wait_for_timeout(1300)
    r2 = pg.inner_text(".grid .card .relogio")
    check(r1.startswith("2:0") and r2 != r1, f"o cartão do jogo aberto conta o tempo da sessão ao vivo ({r1} -> {r2})")
    check("jogando agora" in pg.inner_text(".destaque .d-kick").lower() and pg.locator(".destaque .d-num .relogio").count() == 1,
          "o destaque vira Jogando agora, com o relógio")
    pg.wait_for_function("getComputedStyle($('content')).getPropertyValue('--brilho').includes('rgb')")
    cor = pg.evaluate("$('content').style.getPropertyValue('--brilho')")
    rr, gg, bb = [int(x) for x in cor.split("(")[1].split("/")[0].split()]
    check(rr > 150 and gg < 80 and bb < 80, f"o brilho do alto da estante tem a cor da capa do destaque ({cor})")
    pg.screenshot(path=str(OUT / "movimento_jogos.png"))

    pg.fill("#q", "a")
    pg.wait_for_timeout(500)
    pg.fill("#q", "dama")
    n = pg.evaluate("document.getAnimations().filter(a => a.effect && a.effect.target && a.effect.target.classList.contains('card')).length")
    check(n >= 1, "ao buscar, os cartões que ficam deslizam até o lugar novo")
    check(pg.locator(".grid.entra").count() == 0, "e não entram de novo (é a mesma parte da estante)")
    pg.fill("#q", "")

    pg.evaluate("trocarEstante('leitura')")
    pg.wait_for_selector(".grid .card .badge.cnovo")
    check(pg.locator(".content.troca").count() == 1, "trocar de estante faz a transição")
    sid = pg.get_attribute(".grid .card:has(.badge.cnovo)", "data-id")
    with app.lock:
        d = leitura._load()
        x = next(s for s in d["series"] if s["id"] == sid)
        leitura._subiu(d, x, 12.0)
        leitura._save(d)
    pg.wait_for_selector(f".grid .card.chegou[data-id='{sid}']", timeout=15000)
    pg.wait_for_timeout(1200)
    check(pg.inner_text(f".card[data-id='{sid}'] .badge.cnovo .n") == "7", "capítulo novo que chegou: o cartão pulsa e o número sobe até 7")
    check(pg.locator(".card.chegou").count() == 1, "só o cartão que ganhou capítulo")

    pg.evaluate("go('stats')")
    pg.wait_for_selector(".est.anima")
    pg.wait_for_timeout(1300)
    check(pg.inner_text(".est .stat b") == "5", "nas Estatísticas, os números contam até o valor certo")
    check(pg.locator(".est.anima .barra i").count() > 0, "e as barras crescem")
    pg.evaluate("go('all')")
    pg.wait_for_timeout(300)
    pg.evaluate("go('stats')")
    pg.wait_for_selector(".est.anima")
    check(True, "voltar às Estatísticas anima de novo")
    check(not erros, "sem erros na página: " + "; ".join(erros))

    print("Reduzir animações")
    pg2 = b.new_page(viewport={"width": 1320, "height": 860}, reduced_motion="reduce")
    pg2.on("pageerror", lambda e: erros.append(str(e)))
    pg2.goto("http://127.0.0.1:8799/")
    pg2.wait_for_selector(".grid .card")
    check(pg2.locator(".grid.entra").count() == 0, "com reduzir animações, os cartões aparecem sem entrar em sequência")
    pg2.evaluate("go('stats')")
    pg2.wait_for_selector(".est .stat b")
    check(pg2.locator(".est.anima").count() == 0, "e as Estatísticas aparecem paradas, já com os números")
    check(not erros, "sem erros na página: " + "; ".join(erros))
    b.close()
srv.shutdown()

print(f"\nTudo certo: {ok} verificações.")

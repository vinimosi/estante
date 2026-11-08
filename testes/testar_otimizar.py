"""Estante mais leve: a lista da Leitura guardada pronta na memória, a descrição só quando a série é aberta e as
capas reduzidas nos cartões. Rode: python3 testar_otimizar.py"""
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
from pathlib import Path

S = Path(_SAIDA)
T = S / "otimizar"
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


def capa(nome, largura, altura):
    buf = io.BytesIO()
    Image.new("RGB", (largura, altura), (200, 40, 40)).save(buf, "PNG")
    (app.COVERS / nome).write_bytes(buf.getvalue())


capa("grande.png", 600, 900)
capa("pequena.png", 200, 300)
with app.lock:
    d = leitura._load()
    for nome, desc, cv, alt in [("Torre Alta", "Um garoto sobe a torre.\nE descobre segredos.", "grande.png", ["Tower High"]),
                                ("Sem Capa", "", None, [])]:
        s = leitura.nova_serie(nome)
        s.update({"description": desc, "cover": cv, "titulos_alt": alt, "ultimo_lido": 3.0, "ultimo_disponivel": 5.0})
        d["series"].append(s)
    leitura._save(d)
sid = next(s["id"] for s in leitura._load()["series"] if s["name"] == "Torre Alta")

print("Lista da Leitura")
r = c.get("/api/leitura").get_json()
torre = next(s for s in r["series"] if s["id"] == sid)
check("description" not in torre, "a descrição não vem mais na lista")
check(torre["titulos_alt"] == ["Tower High"] and torre["cover_url"] == "/covers/grande.png" and torre["nao_lidos"] == 2,
      "os nomes alternativos (a busca usa), a capa e os capítulos novos continuam")
check(c.get("/api/leitura?marca=" + r["marca"]).get_json() == {"igual": True, "marca": r["marca"]}, "sem mudança, só avisa que está igual")
s = c.get("/api/leitura/sobre?id=" + sid).get_json()
check(s["description"] == "Um garoto sobe a torre.\nE descobre segredos.", "a descrição vem quando a série é aberta")
check(c.get("/api/leitura/sobre?id=nao-existe").status_code == 404, "série que não existe: 404")

montagens = []
_load = leitura._load
leitura._load = lambda: montagens.append(1) or _load()
for _ in range(5):
    c.get("/api/leitura?marca=" + r["marca"])
check(not montagens, "perguntar de novo não relê o leitura.json (a lista fica pronta na memória)")
with app.lock:
    d = _load()
    next(x for x in d["series"] if x["id"] == sid)["name"] = "Torre Mais Alta"
    leitura._save(d)
r2 = c.get("/api/leitura?marca=" + r["marca"]).get_json()
check(montagens and "igual" not in r2 and any(x["name"] == "Torre Mais Alta" for x in r2["series"]),
      "quando o arquivo muda, a lista é refeita e chega a mudança")
montagens.clear()
leitura._lista_cache["quando"] -= 61
c.get("/api/leitura")
check(montagens, "e é refeita de qualquer jeito depois de um minuto (capítulo baixado que sumiu)")
leitura._load = _load
p = c.patch("/api/leitura/" + sid, json={"autor": "Fulano"}).get_json()
check(p["description"].startswith("Um garoto"), "salvar uma mudança não mexe na descrição")

print("Capas pequenas")
g = c.get("/covers/mini/grande.png")
im = Image.open(io.BytesIO(g.data))
check(g.status_code == 200 and g.mimetype == "image/webp" and im.size == (340, 510), "a capa grande vira uma de 340 pixels, na mesma proporção")
check(len(g.data) < (app.COVERS / "grande.png").stat().st_size and (app.MINI / "grande.png.webp").exists(),
      "menor que a original, e guardada para as próximas vezes")
g.close()
p = c.get("/covers/mini/pequena.png")
check(p.status_code == 200 and p.data == (app.COVERS / "pequena.png").read_bytes(), "capa que já é pequena vai como está")
p.close()
check(not (app.MINI / "pequena.png.webp").exists(), "e não ganha cópia")
for ruim in ("../config.json", "..%5Cconfig.json", "nao-existe.png", ".grande.png"):
    check(c.get("/covers/mini/" + ruim).status_code == 404, "nome estranho ou capa que não existe: 404 (" + ruim + ")")
(app.COVERS / "estragada.png").write_bytes(b"isto nao e uma imagem")
e = c.get("/covers/mini/estragada.png")
check(e.status_code == 200 and e.data == b"isto nao e uma imagem", "imagem que não abre: vai a original, sem erro")
e.close()
check(c.get("/covers/grande.png").status_code == 200, "a original continua no mesmo endereço")
(app.COVERS / "grande.png").unlink()
app.limpar_minis()
check(not (app.MINI / "grande.png.webp").exists(), "capa apagada: a cópia pequena sai também")
capa("grande.png", 600, 900)

print("Tela")
(T / "Jogos").mkdir()
(T / "Jogos" / "jogo.exe").write_bytes(b"MZ")
c.post("/api/games", json={"exe": str(T / "Jogos" / "jogo.exe"), "name": "Um Jogo"})
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8798, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros, pedidos = [], []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("request", lambda q: pedidos.append(q.url))
    pg.goto("http://127.0.0.1:8798/")
    pg.wait_for_selector(".grid .card")
    pg.evaluate("""() => { const a = api;  // a lista dos jogos demora, e a troca acontece antes de ela chegar
        window.api = (u, o) => u === '/api/games' ? new Promise(r => setTimeout(r, 800)).then(() => a(u, o)) : a(u, o);
        load(); trocarEstante('leitura'); }""")
    pg.wait_for_selector(f".card[data-id='{sid}'] img.main")
    pg.wait_for_timeout(1500)
    check(pg.evaluate("S.games.every(x => x.lido_txt !== undefined)") and pg.locator(f".card[data-id='{sid}']").count() == 1,
          "trocar para a Leitura antes da lista dos jogos chegar não mistura as duas")
    check(pg.get_attribute(f".card[data-id='{sid}'] img.main", "src") == "/covers/mini/grande.png", "o cartão usa a capa pequena")
    check(not any(u.endswith("/covers/grande.png") for u in pedidos), "e a tela não baixa a original só para a lista")
    pg.click(f".card[data-id='{sid}']")
    pg.wait_for_selector("#drawer.show .desc")
    check("Um garoto sobe a torre." in pg.inner_text("#drawer .desc"), "abrir a série mostra a descrição")
    pg.screenshot(path=str(OUT / "otimizar_serie.png"))
    pg.click("#drawer button:has-text('Editar')")
    pg.wait_for_selector("#eDesc")
    check(pg.input_value("#eDesc").startswith("Um garoto sobe"), "editar a série já traz a descrição para o campo")
    pg.fill("#eAut", "Ciclano")
    pg.click("#eOk")
    pg.wait_for_timeout(600)
    s = next(x for x in leitura._load()["series"] if x["id"] == sid)
    check(s["autor"] == "Ciclano" and s["description"].startswith("Um garoto"), "salvar pela tela guarda a mudança e mantém a descrição")
    check(not erros, "sem erros na página: " + "; ".join(erros))
    b.close()
srv.shutdown()

print(f"\nTudo certo: {ok} verificações.")

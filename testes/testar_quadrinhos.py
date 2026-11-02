"""Quadrinhos do PC: pastas de mentira com CBZ, pasta de imagens e PDF, e capturas do leitor."""
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
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

S = Path(_SAIDA)
T = S / "quad"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import leitura  # noqa: E402
import quadrinhos  # noqa: E402
import testar_leitura_mocks as mocks  # noqa: E402

leitura._http_json = mocks.http_falso
leitura.guardar_capa = mocks.capa_falsa


def pagina(txt, cor, alto=1400):
    im = Image.new("RGB", (900, alto), cor)
    d = ImageDraw.Draw(im)
    for y in range(0, alto, 120):
        d.rectangle([60, y + 20, 840, y + 90], outline=(255, 255, 255), width=3)
    d.text((80, 40), txt, fill=(255, 255, 255))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


Q = T / "Quadrinhos"
serie = Q / "Minha Serie [scan]"
serie.mkdir(parents=True)
with zipfile.ZipFile(serie / "Minha Serie - Cap 001.cbz", "w") as z:
    for p in [10, 2, 1]:  # ordem natural: 1, 2, 10
        z.writestr(f"pag{p}.jpg", pagina(f"Cap 1 - pagina {p}", (40, 60, 120)))
cap2 = serie / "Cap 002"
cap2.mkdir()
for p in range(1, 4):
    (cap2 / f"{p:02d}.jpg").write_bytes(pagina(f"Cap 2 - pagina {p}", (120, 50, 60)))
(serie / "Cap 003.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
(serie / "leia-me.txt").write_text("não é capítulo")
with zipfile.ZipFile(Q / "Historia_Curta.cbz", "w") as z:
    z.writestr("01.png", pagina("Única", (30, 110, 70)))
(T / "Outra").mkdir()

c = app.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


print("Números dos capítulos")
check(quadrinhos.numero_do_nome("Solo Leveling - Cap 012.cbz") == 12 and quadrinhos.numero_do_nome("v03 c015.5") == 15.5
      and quadrinhos.numero_do_nome("Volume 2") == 2 and quadrinhos.numero_do_nome("Chapter_7") == 7, "número do capítulo pelo nome do arquivo")

print("Pastas")
r = c.post("/api/leitura/pastas", json={"acrescentar": str(T / "nao_existe")})
check(r.status_code == 400, "pasta que não existe é recusada")
r = c.post("/api/leitura/pastas", json={"acrescentar": str(Q)}).get_json()
check(r["novas"] == 2, "duas séries: a pasta da série e o CBZ solto")
d = {s["name"]: s for s in c.get("/api/leitura").get_json()["series"]}
s = d.get("Minha Serie")
check(s and [x["n"] for x in s["local"]["caps"]] == [1, 2, 3] and [x["tipo"] for x in s["local"]["caps"]] == ["zip", "pasta", "pdf"],
      "capítulos: CBZ, pasta de imagens e PDF, em ordem (o .txt é ignorado)")
check(s["site_nome"] == "No seu PC" and s["proximo_cap"]["num"] == "1", "a série é do seu PC e o próximo é o capítulo 1")
check("Historia Curta" in d, "arquivo solto vira série de um capítulo")
check(esperar := True, "")
fim = time.time() + 10
while time.time() < fim and not c.get("/api/leitura").get_json()["series"][0].get("cover"):
    time.sleep(0.2)
check(all(x.get("cover") for x in c.get("/api/leitura").get_json()["series"]), "capa = primeira página do primeiro capítulo")

print("Páginas")
sid = s["id"]
r = c.get(f"/api/leitura/local/{sid}/0").get_json()
check(r["paginas"] == 3, "o CBZ tem 3 páginas")
img = c.get(f"/api/leitura/local/{sid}/0/2")
check(img.status_code == 200 and img.mimetype == "image/jpeg" and Image.open(io.BytesIO(img.data)).size == (900, 1400), "página lida de dentro do CBZ")
check(c.get(f"/api/leitura/local/{sid}/1/0").status_code == 200 and c.get(f"/api/leitura/local/{sid}/1/9").status_code == 404, "pasta de imagens e página que não existe")
check(c.get(f"/api/leitura/local/{sid}/2").get_json()["pdf"], "PDF abre na janela de leitura")
check(c.get(f"/api/leitura/local/{sid}/1/..%2F..%2Fx").status_code == 404, "não deixa ler arquivos fora da pasta")

print("Progresso")
c.post(f"/api/leitura/local/{sid}/0/progresso", json={"pagina": 1})
s = next(x for x in c.get("/api/leitura").get_json()["series"] if x["id"] == sid)
check(s["lido_txt"] == "" and s["local"]["paginas"]["1"] == 1 and s["ultima_leitura"], "guardou a página onde parou, sem marcar como lido")
c.post(f"/api/leitura/local/{sid}/0/progresso", json={"pagina": 2, "fim": True})
s = next(x for x in c.get("/api/leitura").get_json()["series"] if x["id"] == sid)
check(s["lido_txt"] == "1" and s["local"]["proximo"] == 1 and s["nao_lidos"] == 2, "chegou no fim: capítulo 1 lido, próximo é o 2")

print("Capítulo novo na pasta")
(serie / "Cap 004.cbz").write_bytes(open(serie / "Minha Serie - Cap 001.cbz", "rb").read())
quadrinhos.sincronizar()
s = next(x for x in c.get("/api/leitura").get_json()["series"] if x["id"] == sid)
nov = [n for n in c.get("/api/leitura").get_json()["novidades"] if n["s"] == sid]
check(s["disp_txt"] == "4" and nov and nov[0]["site"] == "local", "capítulo 4 colocado na pasta aparece em Novidades")
check(s["dados_de"] != "mangaupdates" or s["disp_txt"] == "4", "o MangaUpdates não mexe nos capítulos do PC")

# ---------------- telas
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8796, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8796/")
    pg.wait_for_timeout(800)
    pg.click("#shelves >> text=Leitura")
    pg.wait_for_timeout(1000)
    pg.click(".grid .card:has-text('Minha Serie') .meta")
    pg.wait_for_timeout(500)
    pg.evaluate("document.getElementById('drawer').scrollTop = 500")
    pg.screenshot(path=str(OUT / "q1_serie.png"))
    pg.click("#drawer >> text=Ler capítulo 2")
    pg.wait_for_timeout(1200)
    pg.screenshot(path=str(OUT / "q2_leitor_rolagem.png"))
    check(pg.locator("#lPaginas img").count() == 3, "leitor abriu o capítulo 2 com 3 páginas em rolagem contínua")
    pg.evaluate("document.getElementById('lPaginas').scrollTop = 1e9")
    pg.wait_for_timeout(1500)
    check("Indo para o próximo" in pg.inner_text("#lCont"), "no fim, a contagem para o próximo capítulo começa")
    pg.screenshot(path=str(OUT / "q3_fim.png"))
    pg.evaluate("document.getElementById('lPaginas').scrollTop = 0")
    # o leitor guarda a página em que você está ao trocar de modo: espera ele ver que voltou para a primeira
    pg.wait_for_function("document.getElementById('lPag').textContent.includes('Página 1 de 3')", timeout=5000)
    pg.select_option(".lbar select >> nth=1", "rtl")
    pg.wait_for_timeout(600)
    pg.screenshot(path=str(OUT / "q4_pagina.png"))
    pg.keyboard.press("ArrowLeft")  # mangá: seta para a esquerda avança
    try:  # espera a página virar (com o computador ocupado, meio segundo às vezes não basta)
        pg.wait_for_function("document.getElementById('lPag').textContent.includes('Página 2 de 3')", timeout=5000)
    except Exception:
        pass
    check("Página 2 de 3" in pg.inner_text("#lPag"), "modo página por página (mangá): seta para a esquerda avança"
          + ("" if "Página 2 de 3" in pg.inner_text("#lPag") else f" [tela: {pg.inner_text('#lPag')} | {pg.inner_text('.lbar')[:120]!r}]"))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(800)
    check(not pg.locator("#leitor.show").count(), "Esc fecha o leitor e volta para a Estante")
    print("erros na página:", erros)
    b.close()
srv.shutdown()
s = next(x for x in c.get("/api/leitura").get_json()["series"] if x["id"] == sid)
check(s["lido_txt"] == "2", "o capítulo 2 lido no leitor foi marcado")
print(f"\nTudo certo: {ok} verificações.")

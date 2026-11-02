"""Etapa 8, pronta para outras pessoas: número de versão, cópias de segurança (automáticas, guardar, restaurar e
desfazer), escolhas da tela guardadas nos dados, a Leitura que só baixa a lista quando muda e a tela de
boas-vindas da instalação nova. Rode: python3 testar_compartilhar.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import json
import os
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path

S = Path(_SAIDA)
T = S / "compartilhar"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
del os.environ["ESTANTE_SEM_BOAS_VINDAS"]  # aqui a tela de boas-vindas é o que se testa
import leitura  # noqa: E402
leitura.SITES_INICIAIS = ()  # instalação nova de verdade
import app  # noqa: E402
import caminhos  # noqa: E402
import copias  # noqa: E402
import lojas  # noqa: E402
import tocando  # noqa: E402

for loja in lojas.LEITORES:
    lojas.LEITORES[loja] = lambda *a, **k: {"encontrada": False, "jogos": []}
tocando.disponivel = lambda: (True, "")
tocando._ler_sessoes = lambda querem: []
DATA = Path(os.environ["ESTANTE_DATA"])
c = app.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


print("Versão")
cfg = c.get("/api/config").get_json()
check(cfg["versao"] == caminhos.VERSAO and caminhos.VERSAO.count(".") == 2, "a Estante tem um número de versão e conta para a tela")
check(caminhos.VERSAO in tocando.AGENTE, "o LRCLIB recebe a mesma versão")

print("Boas-vindas")
check(cfg["boas_vindas"] is True, "numa instalação nova a tela de boas-vindas aparece")
check(c.post("/api/boas-vindas").get_json()["ok"] and c.get("/api/config").get_json()["boas_vindas"] is False,
      "depois de passar por ela (ou pular), não aparece mais")
cf = json.loads((DATA / "config.json").read_text("utf-8"))
del cf["boas_vindas"]
cf["pastas"] = ["C:/Jogos"]
(DATA / "config.json").write_text(json.dumps(cf), "utf-8")
app._marcar_boas_vindas()
check(c.get("/api/config").get_json()["boas_vindas"] is False, "quem já usava a Estante (tem pastas, jogos ou séries) não vê")
cf["pastas"] = []
(DATA / "config.json").write_text(json.dumps(cf), "utf-8")

print("Escolhas da tela nos dados")
r = c.post("/api/preferencias", json={"leitorOnde": "janela", "leitorAuto": False, "ruim-nome": 1, "lista": [1]}).get_json()
check(r["preferencias"] == {"leitorOnde": "janela", "leitorAuto": False}, "guarda só nomes e valores simples")
check(json.loads((DATA / "config.json").read_text("utf-8"))["preferencias"]["leitorOnde"] == "janela", "ficam no config.json")
c.post("/api/preferencias", json={"leitorAuto": None})
check("leitorAuto" not in c.get("/api/config").get_json()["preferencias"], "e dá para tirar uma")

print("Leitura só baixa a lista quando muda")
d = leitura._load()
s1 = leitura.nova_serie("Série Um")
d["series"].append(s1)
leitura._save(d)
r1 = c.get("/api/leitura").get_json()
check(r1.get("marca") and len(r1["series"]) == 1, "a lista vem com uma marca")
r2 = c.get("/api/leitura?marca=" + r1["marca"]).get_json()
check(r2 == {"igual": True, "marca": r1["marca"]}, "perguntando com a mesma marca, vem só {igual: true}")
c.patch(f"/api/leitura/{s1['id']}", json={"ultimo_lido": 3})
r3 = c.get("/api/leitura?marca=" + r1["marca"]).get_json()
check(r3.get("series") and r3["marca"] != r1["marca"] and r3["series"][0]["ultimo_lido"] == 3, "quando algo muda, vem a lista nova")

print("Cópias de segurança")
lib = app.get_lib()
lib["games"].append(app.new_game("Jogo Antigo", "C:/Jogos/Antigo/jogo.exe"))
app.save_lib(lib)
(DATA / "library-antes-v3.json").write_text("{}", "utf-8")
(DATA / "mangaupdates.acesso").write_bytes(b"segredo")
nome = c.post("/api/copias").get_json()["nome"]
z = zipfile.ZipFile(copias.pasta() / nome)
check({"library.json", "leitura.json", "config.json"} <= set(z.namelist()), "a cópia leva jogos, leitura e configurações")
check(not any("antes" in n or "acesso" in n or n.startswith("covers") for n in z.namelist()),
      "e deixa de fora as cópias de conversão, as capas e o acesso do MangaUpdates")
z.close()
lista = c.get("/api/copias").get_json()["copias"]
check(len(lista) == 1 and lista[0]["tipo"] == "manual" and lista[0]["tamanho"] > 0, "aparece na lista como guardada por você")

# depois da cópia, os dados mudam
lib = app.get_lib()
lib["games"] = [app.new_game("Jogo Novo", "C:/Jogos/Novo/jogo.exe")]
app.save_lib(lib)
c.post("/api/preferencias", json={"leitorOnde": "mesma"})
r = c.post("/api/copias/restaurar", json={"nome": nome}).get_json()
check(r["ok"] and [g["name"] for g in app.get_lib()["games"]] == ["Jogo Antigo"], "restaurar volta os jogos de antes")
check(c.get("/api/config").get_json()["preferencias"]["leitorOnde"] == "janela", "e as configurações")
check((DATA / "mangaupdates.acesso").read_bytes() == b"segredo", "sem mexer no acesso do MangaUpdates")
antes = [x for x in c.get("/api/copias").get_json()["copias"] if x["tipo"] == "antes"]
check(len(antes) == 1 and antes[0]["nome"] == r["antes"], "antes de restaurar, guarda como estava (para desfazer)")
c.post("/api/copias/restaurar", json={"nome": r["antes"]})
check([g["name"] for g in app.get_lib()["games"]] == ["Jogo Novo"], "e desfazer funciona")
c.post("/api/copias/restaurar", json={"nome": nome})

check(c.post("/api/copias/restaurar", json={"nome": "../config.json"}).status_code == 400, "nome com caminho é recusado")
check(c.post("/api/copias/restaurar", json={"nome": "nao-existe.zip"}).status_code == 404, "cópia que não existe dá 404")
(copias.pasta() / "estragada.zip").write_bytes(b"isto nao e zip")
r = c.post("/api/copias/restaurar", json={"nome": "estragada.zip"})
check(r.status_code == 400 and "ler" in r.get_json()["error"], "um arquivo estragado é recusado sem mexer em nada")
with zipfile.ZipFile(copias.pasta() / "malvada.zip", "w") as z:
    z.writestr("../fora.json", "{}")
    z.writestr("pasta/library.json", "{}")
r = c.post("/api/copias/restaurar", json={"nome": "malvada.zip"})
check(r.status_code == 400 and not (DATA.parent / "fora.json").exists() and app.get_lib()["games"],
      "arquivos com pasta ou caminho dentro da cópia são ignorados")
copias.apagar_arquivo(copias.pasta() / "estragada.zip")
c.post("/api/copias/apagar", json={"nome": "malvada.zip"})
check(not (copias.pasta() / "malvada.zip").exists(), "dá para apagar uma cópia")

# automáticas: uma por dia, ficam as 10 mais novas
for i in range(12):
    (copias.pasta() / f"estante-2026-01-{i + 1:02d}-120000-auto.zip").write_bytes(open(copias.pasta() / nome, "rb").read())
check(copias.ultima_auto() > 0 and time.time() - copias.ultima_auto() > copias.DIA, "a última automática é de dias atrás")
copias.vigiar(intervalo=3600)
for _ in range(50):
    if time.time() - copias.ultima_auto() < 60:
        break
    time.sleep(0.1)
autos = [x for x in copias.lista() if x["tipo"] == "auto"]
check(time.time() - copias.ultima_auto() < 60, "ao abrir, faz uma automática se a última tem mais de um dia")
check(len(autos) == copias.GUARDAR_AUTO and autos[-1]["nome"].startswith("estante-2026-01-04"), "ficam só as 10 automáticas mais novas")
check(any(x["nome"] == nome for x in copias.lista()), "as guardadas por você não são apagadas")
r = c.post("/api/copias/abrir-pasta").get_json()
check(r["ok"] and sem_janelas.ABERTOS[-1] == str(copias.pasta()), "o botão abre a pasta das cópias")

print("Tela")
cf = json.loads((DATA / "config.json").read_text("utf-8"))
cf["boas_vindas"] = "mostrar"
cf.pop("preferencias", None)
(DATA / "config.json").write_text(json.dumps(cf), "utf-8")
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8794, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    # escolhas antigas, guardadas só na janela, passam para os dados
    pg.add_init_script("try { if (!sessionStorage.getItem('x')) { localStorage.setItem('estante.leitorModo', '\"rtl\"'); sessionStorage.setItem('x', 1); } } catch (e) {}")
    pg.goto("http://127.0.0.1:8794/")
    pg.wait_for_selector("#modal h2:has-text('Boas-vindas')")
    check(True, "a tela de boas-vindas abre sozinha na instalação nova")
    pg.screenshot(path=str(OUT / "boas-vindas-1.png"))
    check(c.get("/api/config").get_json()["preferencias"].get("leitorModo") == "rtl",
          "uma escolha antiga da janela foi para os dados")
    pg.click("#bvProximo")
    pg.wait_for_selector("#lojasCfg .loja-row")
    check(pg.locator("#lojasCfg .loja-row").count() == len(lojas.ORDEM), "o passo Jogos mostra as lojas, para ligar e desligar")
    pg.screenshot(path=str(OUT / "boas-vindas-2-jogos.png"))
    pg.click("#bvProximo")
    pg.wait_for_selector("#bvSites button")
    pg.click("#bvSites button:has-text('Asura')")
    pg.wait_for_selector("#bvSites .chip:has-text('Asura')")
    check([s["chave"] for s in c.get("/api/leitura/sites").get_json()["sites"]] == ["asura"], "no passo Leitura, um clique acrescenta um site")
    pg.fill("#bvSiteOutro", "meusite.com")
    pg.press("#bvSiteOutro", "Enter")
    pg.wait_for_selector("#bvSites .chip:has-text('meusite.com')")
    check(len(c.get("/api/leitura/sites").get_json()["sites"]) == 2, "e dá para pôr outro site")
    check("edge://extensions" in pg.inner_text("#modal"), "explica como instalar a extensão")
    pg.screenshot(path=str(OUT / "boas-vindas-3-leitura.png"))
    pg.click("#bvProximo")
    pg.wait_for_selector("#bvTocando")
    pg.uncheck("#bvTocando")
    pg.wait_for_timeout(300)
    check(c.get("/api/tocando/config").get_json()["ligado"] is False, "no passo Música dá para desligar o Tocando agora")
    pg.check("#bvTocando")
    pg.click("#bvProximo")
    pg.wait_for_selector("#bvProximo:has-text('Abrir a Estante')")
    pg.screenshot(path=str(OUT / "boas-vindas-4-pronto.png"))
    pg.click("#bvProximo")
    pg.wait_for_timeout(500)
    check(not pg.is_visible("#modal h2") and c.get("/api/config").get_json()["boas_vindas"] is False, "no fim ela fecha e não volta mais")
    pg.reload()
    pg.wait_for_timeout(1200)
    check(not pg.is_visible("#modal h2"), "abrindo de novo, não aparece")

    # aba Geral: versão e cópias
    pg.evaluate("openSettings('geral')")
    pg.wait_for_selector("#copiasCfg .copia")
    txt = pg.inner_text(".cfg-aba[data-aba=geral]")
    check("Estante " + caminhos.VERSAO in txt, "a aba Geral mostra a versão")
    check(pg.locator("#copiasCfg .copia").count() == len(copias.lista()), "e a lista de cópias")
    pg.screenshot(path=str(OUT / "config-geral-copias.png"))
    n = len(copias.lista())
    pg.click("#copiaAgora")
    pg.wait_for_function(f"document.querySelectorAll('#copiasCfg .copia').length === {n + 1}")
    check(True, "“Guardar uma cópia agora” acrescenta uma na lista")
    lib = app.get_lib()
    lib["games"].append(app.new_game("Jogo Depois", "C:/Jogos/Depois/jogo.exe"))
    app.save_lib(lib)
    pg.on("dialog", lambda d: d.accept())
    pg.click("#copiasCfg .copia >> nth=0 >> button:has-text('Restaurar')")
    pg.wait_for_selector(".toast:has-text('voltaram')", timeout=5000)
    check(all(g["name"] != "Jogo Depois" for g in app.get_lib()["games"]), "restaurar pela tela funciona")

    # Leitura não baixa a lista de novo quando nada muda
    pg.evaluate("closeModal(); trocarEstante && trocarEstante('leitura')")
    pg.wait_for_timeout(1000)
    pedidos = []
    pg.on("response", lambda r: pedidos.append((r.url, len(r.body()))) if "/api/leitura?" in r.url or r.url.endswith("/api/leitura") else None)
    pg.evaluate("loadLeitura()")
    pg.wait_for_timeout(600)
    check(pedidos and "marca=" in pedidos[-1][0] and pedidos[-1][1] < 100, "a Leitura pergunta com a marca e, sem mudança, recebe quase nada")
    check(not erros, "sem erros na página: " + "; ".join(erros))
    b.close()
srv.shutdown()
print(f"\nTudo certo: {ok} verificações.")

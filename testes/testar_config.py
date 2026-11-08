"""Configurações em abas (Jogos, Leitura, Música, Geral) e uma instalação nova que não pressupõe nada:
sem sites de leitura, sem pastas, sem contas. Rode: python3 testar_config.py"""
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
from pathlib import Path

S = Path(_SAIDA)
T = S / "config"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import leitura  # noqa: E402
leitura.SITES_INICIAIS = ()  # aqui é uma instalação nova de verdade, como a de quem baixa a Estante
import app  # noqa: E402
import lojas  # noqa: E402
import tocando  # noqa: E402

for loja in lojas.LEITORES:
    lojas.LEITORES[loja] = lambda *a, **k: {"encontrada": False, "jogos": []}  # nenhuma loja instalada neste PC de mentira
tocando.disponivel = lambda: (True, "")
tocando._ler_sessoes = lambda querem: []
c = app.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


print("Instalação nova")
r = c.get("/api/leitura/sites").get_json()
check(r["sites"] == [], "começa sem nenhum site de leitura")
check({k["chave"] for k in r["conhecidos"]} == {"comix", "asura", "demonic"} and all(k["nome"] and k["dominio"] for k in r["conhecidos"]),
      "a tela recebe os sites que a Estante já sabe ler, para acrescentar com um clique")
cfg = c.get("/api/config").get_json()
check(cfg["pastas"] == [] and not cfg["has_key"] and not cfg["anilist_usuario"], "sem pastas, sem chave e sem usuário de ninguém")
check(not c.get("/api/leitura/mangaupdates").get_json().get("conectado"), "nenhuma conta ligada")
check(not c.get("/api/tocando/config").get_json()["genius"], "sem chave do Genius")
r = c.post("/api/leitura/sites", json={"sites": [{"chave": "asura", "nome": "Asura Scans", "dominio": "asurascans.com"}]}).get_json()
asura = r["sites"][0]
check(len(r["sites"]) == 1 and asura["chave"] == "asura" and asura["capitulo"] and asura["atualizacoes"],
      "um site conhecido acrescentado depois vem com todas as regras dele")
r = c.post("/api/leitura/sites", json={"sites": [{"chave": "asura", "nome": "Asura Scans", "dominio": "asurascans.com"},
                                                  {"nome": "Meu Site", "dominio": "https://www.meusite.com/manga"}]}).get_json()
check([s["dominio"] for s in r["sites"]] == ["asurascans.com", "meusite.com"], "e um site qualquer também entra")
c.post("/api/leitura/sites", json={"sites": []})

print("Tela")
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8796, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8796/")
    pg.wait_for_timeout(1200)

    def aba_on():
        return pg.inner_text("#cfgAbas button.on")

    def visivel(t):
        return pg.locator(f".cfg-aba:not([hidden]) >> text={t}").count() > 0

    pg.click("text=Configurações")
    pg.wait_for_selector("#cfgAbas")
    check("Jogos" in aba_on(), "na estante de Jogos, as Configurações abrem na aba Jogos")
    check(visivel("Lojas e launchers") and not visivel("Sites de leitura") and not visivel("Tocando agora"),
          "a aba Jogos mostra só as coisas dos jogos")
    texto = pg.inner_text("#modal")
    for proibido in ("F:\\", "D:\\", "Conectada", os.environ.get("USERNAME") or "?"):  # nada do PC de quem roda o teste
        check(proibido not in texto, f"nada do PC de ninguém nas Configurações ({proibido})")
    pg.screenshot(path=str(OUT / "c1_jogos.png"))
    pg.click("#cfgAbas >> text=Leitura")
    check("Leitura" in aba_on() and visivel("Sites de leitura") and not visivel("Lojas e launchers"), "trocar de aba mostra a outra parte")
    check(visivel("Nenhum site ainda") and pg.locator(".cfg-aba:not([hidden]) .site-row").count() == 0, "sem sites, a aba explica o que fazer")
    check(pg.locator("#sitePref").count() == 0, "a escolha do site preferido só aparece com dois sites ou mais")
    pg.screenshot(path=str(OUT / "c2_leitura_vazia.png"))
    pg.click("button.sug:has-text('Asura Scans')")
    pg.wait_for_selector("button.sug:has-text('Asura Scans')", state="detached")
    sites = c.get("/api/leitura/sites").get_json()["sites"]
    check([s["chave"] for s in sites] == ["asura"] and sites[0]["capitulo"], "um clique acrescenta e salva o site conhecido")
    check("Leitura" in aba_on() and pg.locator(".cfg-aba:not([hidden]) button.sug:has-text('Asura Scans')").count() == 0 and pg.locator(".cfg-aba:not([hidden]) button.sug:has-text('Comix')").count() > 0, "a tela continua na aba Leitura, e o site saiu das sugestões")
    pg.click("button.sug:has-text('Comix')")
    pg.wait_for_selector("#sitePref")
    check(pg.locator(".cfg-aba:not([hidden]) .site-row").count() == 2, "com dois sites, aparece a escolha do site preferido")
    pg.screenshot(path=str(OUT / "c3_leitura_sites.png"))
    pg.click("#cfgAbas >> text=Música")
    check(visivel("Mostrar o que está tocando") and visivel("Genius (opcional)") and not visivel("Sites de leitura"), "a aba Música tem o Tocando agora")
    pg.screenshot(path=str(OUT / "c4_musica.png"))
    pg.click("#cfgAbas >> text=Geral")
    check(visivel("Seus dados") and visivel("Privacidade") and visivel("Abrir pasta dos dados"), "a aba Geral tem os dados e a privacidade")
    pg.screenshot(path=str(OUT / "c5_geral.png"))
    pg.keyboard.press("Escape")
    pg.click("#shelves >> text=Leitura")
    pg.wait_for_timeout(500)
    pg.click("text=Configurações")
    pg.wait_for_selector("#cfgAbas")
    check("Leitura" in aba_on(), "na estante de Leitura, abrem na aba Leitura")
    pg.click("#cfgAbas >> text=Jogos")
    pg.fill("#kIn", "chave-qualquer")
    pg.evaluate("openSettings()")
    pg.wait_for_timeout(400)
    check("Jogos" in aba_on(), "depois de mudar alguma coisa, a tela continua na mesma aba")
    check(not erros, f"nenhum erro na página {erros}")
    b.close()
srv.shutdown()
check("sites" in json.loads((T / "dados" / "config.json").read_text("utf-8")).get("leitura", {}), "a lista escolhida fica gravada")

print(f"\nTudo certo: {ok} verificações.")

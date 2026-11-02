"""Etapa 12, atualização automática: ver no GitHub (de mentira) se saiu versão nova, baixar, conferir, esperar o jogo
fechar e trocar o programa numa instalação de mentira (o script de troca roda de verdade, numa pasta temporária).
Rode: python3 testar_atualizar.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import hashlib
import io
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

S = Path(_SAIDA)
T = S / "atualizar"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import atualizar as atu  # noqa: E402
import lojas  # noqa: E402

for loja in lojas.LEITORES:
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


def zip_versao(v, extra=None):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("app/Estante.pyw", "# nova\n")
        z.writestr("app/VERSAO.txt", v)
        z.writestr("python/pythonw.exe", "exe novo")
        for nome, conteudo in (extra or {}).items():
            z.writestr(nome, conteudo)
    return b.getvalue()


GITHUB = {"tag": "v2.1.0", "zip": zip_versao("2.1.0"), "digest": True}


def api_falsa(url):
    check(url == f"https://api.github.com/repos/{atu.REPOSITORIO}/releases/latest", "(pergunta ao repositório certo)") if not hasattr(api_falsa, "vista") else None
    api_falsa.vista = True
    dados = GITHUB["zip"]
    return {"tag_name": GITHUB["tag"], "body": "Novidades da versão.", "html_url": "https://github.com/x/estante/releases/tag/" + GITHUB["tag"],
            "assets": [{"name": "Instalar-Estante.exe", "browser_download_url": "https://exemplo/Instalar-Estante.exe", "size": 9},
                       {"name": f"Estante-{GITHUB['tag'][1:]}.zip", "browser_download_url": "https://exemplo/nova.zip", "size": len(dados),
                        "digest": ("sha256:" + hashlib.sha256(dados).hexdigest()) if GITHUB["digest"] else None}]}


def baixar_falso(url, destino, progresso=None):
    Path(destino).write_bytes(GITHUB["zip"])
    if progresso:
        progresso(1.0)


atu._get_json = api_falsa
atu._baixar = baixar_falso

print("Versão nova no GitHub")
check(atu.versao_tupla("v2.10.1") > atu.versao_tupla("2.9.9") > atu.versao_tupla("2.0.0") and atu.versao_tupla("2.0") < atu.versao_tupla("2.0.1"),
      "as versões são comparadas como números (2.10 é depois de 2.9)")
r = c.post("/api/atualizacao/verificar").get_json()
check(r["nova"]["versao"] == "2.1.0" and r["nova"]["url"] == "https://exemplo/nova.zip" and r["versao"] == atu.VERSAO,
      "achou a 2.1.0 e o arquivo certo (o zip, não o instalador)")
check(app.get_cfg()["atualizacao"]["ultima"] > time.time() - 5, "anota quando olhou (para olhar de novo só no dia seguinte)")
GITHUB["tag"] = "v" + atu.VERSAO
check(c.post("/api/atualizacao/verificar").get_json()["nova"] is None, "a mesma versão que você tem não conta como nova")
GITHUB["tag"] = "v2.1.0"
c.post("/api/atualizacao/verificar")
r = c.post("/api/atualizacao/instalar")
check(r.status_code == 400 and "código-fonte" in r.get_json()["error"], "rodando pelo código-fonte, não troca nada sozinha")

print("Baixar e preparar")
inst = T / "Programs" / "Estante"
(inst / "app").mkdir(parents=True)
(inst / "python").mkdir()
(inst / "app" / "Estante.pyw").write_text("# velha\n")
(inst / "app" / "VERSAO.txt").write_text(atu.VERSAO)
(inst / "python" / "pythonw.exe").write_text("exe velho")
atu.INSTALACAO, atu.BASE = inst, inst / "app"
check(atu.instalada(), "reconhece a Estante instalada (app e python lado a lado)")
nova = atu.situacao()["nova"]
pasta = atu.preparar(nova)
check((pasta / "app" / "Estante.pyw").read_text() == "# nova\n" and (pasta / "python" / "pythonw.exe").exists(), "baixa e deixa a versão nova pronta ao lado")
GITHUB["digest"] = True
nova_errada = dict(nova, sha256="0" * 64)
try:
    atu.preparar(nova_errada)
    check(False, "arquivo que não confere com o publicado")
except ValueError as e:
    check("não confere" in str(e), "arquivo que não confere com o publicado é recusado")
GITHUB["zip"] = zip_versao("2.1.0", {"../fora.txt": "x"})
try:
    atu.preparar(dict(nova, tamanho=len(GITHUB["zip"]), sha256=""))
    check(False, "zip com caminho para fora")
except ValueError:
    check(not (inst / "fora.txt").exists(), "zip com algo fora do lugar é recusado, sem escrever nada fora")
GITHUB["zip"] = zip_versao("2.1.0")

print("Esperar o jogo fechar")
abertos, trocou, saiu = {"n": 2}, [], []
atu.CTX["jogos_abertos"] = lambda: (abertos.update(n=abertos["n"] - 1) or abertos["n"] >= 0)
atu.CTX["sair"] = lambda: saiu.append(True)
atu._abrir_troca = lambda sem_abrir=False: trocou.append(True)
espera = atu.time.sleep
atu.time.sleep = lambda s: espera(min(s, 0.05))
c.post("/api/atualizacao/verificar")
r = c.post("/api/atualizacao/instalar")
check(r.status_code == 200, "com a Estante instalada, o botão Atualizar começa")
fim = time.time() + 10
while time.time() < fim and not saiu:
    espera(0.05)
atu.time.sleep = espera
check(abertos["n"] < 0 and trocou and saiu, "esperou os jogos fecharem, preparou, chamou a troca e fechou a Estante")
check(not atu.situacao()["baixando"] and not atu.situacao()["erro"], "sem erro")

print("A troca de verdade (script do PowerShell, numa pasta de mentira)")
morto = subprocess.Popen([sys.executable, "-c", "pass"])
morto.wait()
script = inst / "atualizar.ps1"
script.write_text(atu.TROCAR, encoding="utf-8-sig")
subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Pid_", str(morto.pid),
                "-Base", str(inst), "-SemAbrir"], check=True, timeout=60, creationflags=0x08000000 if os.name == "nt" else 0)
check((inst / "app" / "Estante.pyw").read_text() == "# nova\n" and (inst / "python" / "pythonw.exe").read_text() == "exe novo",
      "o programa e o Python foram trocados pela versão nova")
check((inst / "app-anterior" / "Estante.pyw").read_text() == "# velha\n" and (inst / "python-anterior").exists(),
      "a versão anterior fica guardada")
check(not (inst / "nova").exists() and "Estante atualizada." in (inst / "atualizacao.log").read_text("utf-8"), "e a pasta temporária some")

print("Tela")
atu.INSTALACAO, atu.BASE = Path(_PROJ).parent, Path(_PROJ)
c.post("/api/atualizacao/verificar")
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8787, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8787/")
    pg.wait_for_selector("#avisoAtu.show")
    t = pg.inner_text("#avisoAtu")
    check("2.1.0" in t and "Ver no GitHub" in t, "aviso no alto: saiu a versão nova (pelo código-fonte, o botão leva ao GitHub)")
    pg.screenshot(path=str(OUT / "atualizar_aviso.png"))
    pg.click("#avisoAtu button:has-text('Depois')")
    check(not pg.is_visible("#avisoAtu"), "“Depois” esconde o aviso")
    pg.evaluate("openSettings('geral')")
    pg.wait_for_selector("#atuCfg #atuVer")
    check("2.1.0" in pg.inner_text("#atuCfg") and "github.com/" + atu.REPOSITORIO in pg.inner_text("#atuCfg"),
          "a aba Geral mostra a versão nova e o endereço do repositório")
    check(not erros, "sem erros na página: " + "; ".join(erros))
    b.close()
srv.shutdown()
print(f"\nTudo certo: {ok} verificações.")

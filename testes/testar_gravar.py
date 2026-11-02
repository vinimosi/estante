"""Ler e gravar os arquivos de dados ao mesmo tempo (a janela, a extensão e as verificações fazem isso).
No Windows isso dava "Acesso negado", e uma leitura que falhava virava uma biblioteca vazia. Rode: python3 testar_gravar.py"""
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
from pathlib import Path

S = Path(_SAIDA)
T = S / "gravar"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
from caminhos import gravar_json, ler_json  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


def ao_mesmo_tempo(seg, *funcs):
    fim = time.time() + seg
    erros = []

    def rodar(f):
        while time.time() < fim:
            try:
                f()
            except Exception as e:
                erros.append(repr(e))
    ts = [threading.Thread(target=rodar, args=(f,)) for f in funcs]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return erros


print("Ler e gravar o mesmo arquivo ao mesmo tempo")
arq = T / "library.json"
gravar_json(arq, {"games": list(range(50))})
vazias = []


def ler():
    d = ler_json(arq, None)
    if not d or len(d["games"]) != 50:
        vazias.append(d)


erros = ao_mesmo_tempo(3, ler, ler, lambda: gravar_json(arq, {"games": list(range(50))}),
                       lambda: gravar_json(arq, {"games": list(range(50))}))
check(not erros, f"nenhum “Acesso negado” com duas gravações e duas leituras ao mesmo tempo {erros[:2]}")
check(not vazias, "nenhuma leitura voltou vazia enquanto o arquivo era trocado")
check(not list(T.glob("*.tmp")), "não sobram arquivos temporários")

print("Arquivo estragado e arquivo que não existe")
check(ler_json(T / "nao-existe.json", {"x": 1}) == {"x": 1}, "arquivo que não existe: usa o padrão")
(T / "config.json").write_text('{"pastas": [', "utf-8")
check(ler_json(T / "config.json", {}) == {}, "arquivo estragado: usa o padrão")
copias = list(T.glob("config-estragado-*.json"))
check(len(copias) == 1 and copias[0].read_text("utf-8") == '{"pastas": [', "e guarda uma cópia do arquivo estragado")

print("A Estante inteira, com a janela e a extensão ao mesmo tempo")
import app  # noqa: E402
import leitura  # noqa: E402
import testar_leitura_mocks as mocks  # noqa: E402

leitura._http_json = mocks.http_falso  # AniList e MangaUpdates de mentira
c = app.app.test_client()
for i in range(30):
    pasta = T / "Jogos" / f"Jogo {i}"
    pasta.mkdir(parents=True)
    (pasta / f"jogo{i}.exe").write_bytes(b"MZ")
app.completar_avulso = lambda gid: None  # sem internet no teste
c.post("/api/games", json={"games": [{"name": f"Jogo {i}", "exe": str(T / "Jogos" / f"Jogo {i}" / f"jogo{i}.exe")} for i in range(30)]})
with app.lock:
    d = leitura._load()
    for i in range(40):
        d["series"].append(leitura.nova_serie(f"Série {i}"))
    leitura._save(d)
gid = c.get("/api/games").get_json()["games"][0]["id"]
contagens = []


def janela():
    contagens.append(len(c.get("/api/games").get_json()["games"]))
    c.get("/api/config")
    c.get("/api/leitura")


def extensao():
    r = c.post("/api/leitura/progresso", json={"url": "https://comix.to/title/abc/1-chapter-1"},
               headers={"X-Estante-Extensao": "1", "X-Estante-Navegador": "edge"})
    assert r.status_code in (200, 400), r.status_code


def editar():
    c.patch(f"/api/games/{gid}", json={"favorite": True})
    c.post("/api/pastas/remover", json={"pasta": "nao-existe"})  # lê, muda e grava as configurações


erros = ao_mesmo_tempo(4, janela, janela, extensao, editar)
check(not erros, f"sem erros com a janela, a extensão e uma edição ao mesmo tempo {erros[:2]}")
check(contagens and set(contagens) == {30}, "a biblioteca nunca apareceu vazia nem pela metade")
check(len(app.get_lib()["games"]) == 30 and len(leitura._load()["series"]) >= 40, "nenhum jogo nem série se perdeu")
check(app.get_cfg()["leitura"]["navegador"] == "edge", "configurações gravadas pela extensão ficaram")
check(not list((T / "dados").glob("*.tmp")), "não sobram arquivos temporários na pasta de dados")

print(f"\nTudo certo: {ok} verificações.")

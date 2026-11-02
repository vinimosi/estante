"""Cópias de segurança dos dados da Estante.

Uma cópia é um .zip na pasta "copias", dentro da pasta de dados, com os arquivos de dados (library.json,
leitura.json, config.json...). Ficam de fora as capas (são buscadas de novo), as letras de música guardadas,
o estante.log e o acesso da conta do MangaUpdates (protegido pelo Windows, só vale neste usuário do Windows).

Uma cópia automática é feita ao abrir e depois uma vez por dia, enquanto a Estante estiver aberta, e ficam as
10 mais novas. As que você guarda pelo botão ficam até você apagar. Antes de restaurar, a Estante guarda o
estado atual numa cópia "antes de restaurar", para dar para desfazer."""
import json
import re
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from flask import abort, jsonify, request

from caminhos import apagar_arquivo, gravar_json, ler_json

CTX = {}  # preenchido por iniciar(): pasta de dados, lock e o que precisa ser esquecido depois de restaurar
TIPOS = {"auto": "automática", "manual": "guardada por você", "antes": "antes de restaurar"}
GUARDAR_AUTO = 10       # cópias automáticas que ficam
GUARDAR_ANTES = 5       # cópias "antes de restaurar" que ficam
DIA = 86400
NOME_OK = re.compile(r"^[\w.-]+\.json$")
NOME_COPIA = re.compile(r"^estante-(\d{4}-\d{2}-\d{2}-\d{6})-(auto|manual|antes)\.zip$")


def pasta():
    p = Path(CTX["DATA"]) / "copias"
    p.mkdir(exist_ok=True)
    return p


def arquivos_de_dados():
    """Os arquivos de dados da Estante. As cópias que ela mesma guarda antes de converter ou de algo
    dar errado (library-antes-v3.json, leitura-estragado-...json) ficam de fora."""
    return sorted(p for p in Path(CTX["DATA"]).glob("*.json")
                  if p.is_file() and "-antes-" not in p.name and "-estragado" not in p.name)


def guardar(tipo="manual"):
    """Faz uma cópia agora e devolve o nome dela."""
    nome = f"estante-{datetime.now():%Y-%m-%d-%H%M%S}-{tipo}.zip"
    destino = pasta() / nome
    tmp = destino.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in arquivos_de_dados():
            dados = ler_json(p, None)  # lido pelo ler_json: espera o arquivo ficar livre e nunca pega ele pela metade
            if dados is not None:
                z.writestr(p.name, json.dumps(dados, ensure_ascii=False, indent=1))
    tmp.replace(destino)
    limpar()
    return nome


def lista():
    out = []
    for p in pasta().glob("*.zip"):
        m = NOME_COPIA.match(p.name)
        quando = datetime.strptime(m.group(1), "%Y-%m-%d-%H%M%S").timestamp() if m else p.stat().st_mtime
        out.append({"nome": p.name, "quando": quando, "tamanho": p.stat().st_size,
                    "tipo": m.group(2) if m else "manual"})  # zip posto na pasta à mão conta como guardado por você
    return sorted(out, key=lambda c: -c["quando"])


def limpar():
    for tipo, fica in (("auto", GUARDAR_AUTO), ("antes", GUARDAR_ANTES)):
        for c in [c for c in lista() if c["tipo"] == tipo][fica:]:
            apagar_arquivo(pasta() / c["nome"])


def _arquivo(nome):
    if not isinstance(nome, str) or "/" in nome or "\\" in nome or not nome.endswith(".zip"):
        abort(400)
    p = pasta() / nome
    if not p.is_file():
        abort(404)
    return p


def conteudo(p):
    """Lê a cópia inteira antes de mexer em qualquer coisa. Só aceita arquivos .json soltos, sem pastas."""
    with zipfile.ZipFile(p) as z:
        dados = {}
        for nome in z.namelist():
            if not NOME_OK.match(nome):
                continue
            dados[nome] = json.loads(z.read(nome).decode("utf-8"))
    if not dados:
        raise ValueError("Essa cópia não tem dados da Estante.")
    return dados


def restaurar(nome):
    p = _arquivo(nome)
    try:
        dados = conteudo(p)
    except (zipfile.BadZipFile, ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"Não deu para ler essa cópia ({e}).")
    with CTX["lock"]:
        antes = guardar("antes")
        for arq, obj in dados.items():
            gravar_json(Path(CTX["DATA"]) / arq, obj)
    for f in CTX.get("depois_de_restaurar", ()):
        f()
    return {"ok": True, "arquivos": sorted(dados), "antes": antes}


def ultima_auto():
    autos = [c["quando"] for c in lista() if c["tipo"] == "auto"]
    return max(autos) if autos else 0


def vigiar(intervalo=3600):
    """Ao abrir e de hora em hora: se a última cópia automática tem mais de um dia, faz outra."""
    def loop():
        while True:
            try:
                if time.time() - ultima_auto() > DIA - 60:
                    guardar("auto")
            except Exception as e:
                print("[cópias] não consegui fazer a cópia de segurança:", e)
            time.sleep(intervalo)
    threading.Thread(target=loop, daemon=True).start()


def rotas(app):
    @app.get("/api/copias")
    def api_copias():
        return jsonify({"copias": lista(), "pasta": str(pasta())})

    @app.post("/api/copias")
    def api_guardar():
        try:
            return jsonify({"ok": True, "nome": guardar("manual")})
        except OSError as e:
            return jsonify({"error": f"Não deu para guardar a cópia ({e})."}), 500

    @app.post("/api/copias/restaurar")
    def api_restaurar():
        try:
            return jsonify(restaurar((request.get_json(force=True) or {}).get("nome")))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/copias/abrir-pasta")
    def api_abrir_pasta():
        CTX["abrir_pasta"](str(pasta()))
        return jsonify({"ok": True})

    @app.post("/api/copias/apagar")
    def api_apagar():
        apagar_arquivo(_arquivo((request.get_json(force=True) or {}).get("nome")))
        return jsonify({"ok": True})


def iniciar(app, ctx):
    CTX.update(ctx)
    rotas(app)

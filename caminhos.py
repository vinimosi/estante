"""Onde a Estante guarda os dados: no perfil do Windows, fora da pasta do programa.
Assim dá para trocar de versão da Estante sem perder a biblioteca.
Também é aqui que os arquivos de dados (library.json, leitura.json, config.json...) são lidos e gravados."""
import json
import os
import shutil
import threading
import time
from pathlib import Path

VERSAO = "2.0.0"  # versão da Estante, mostrada na aba Geral; a atualização automática compara com ela
REPOSITORIO = "vinimosi/estante"  # no GitHub: de onde vêm as versões novas
BASE = Path(__file__).resolve().parent
NOME_PASTA = "Estante"              # %APPDATA%\Estante
NOME_PASTA_ANTIGA = "EstanteDeJogos"  # nome usado quando o programa se chamava "Estante de Jogos"
TENTATIVAS = 60  # x 50 ms = até 3 segundos esperando o arquivo ficar livre


# ---------------------------------------------------------------- ler e gravar os arquivos de dados
# No Windows, um arquivo que está sendo lido não pode ser trocado, e um arquivo que está sendo trocado não pode
# ser lido: os dois dão "Acesso negado" por um instante. Como a janela, a extensão e as verificações em segundo
# plano leem e gravam ao mesmo tempo, isso acontece. Aqui as duas coisas esperam o arquivo ficar livre.
# O mais importante é a leitura: se ela desistisse e devolvesse uma biblioteca vazia, a próxima gravação
# apagaria os seus dados.

def ler_json(caminho, padrao):
    """Lê um arquivo de dados. Arquivo que não existe = padrao. Arquivo estragado: guarda uma cópia dele
    (nome-estragado-data.json) antes de seguir com o padrao, para nada se perder de vez."""
    caminho = Path(caminho)
    for i in range(TENTATIVAS):
        try:
            return json.loads(caminho.read_text("utf-8"))
        except FileNotFoundError:
            return padrao
        except PermissionError:
            if i == TENTATIVAS - 1:
                raise
            time.sleep(0.05)
        except ValueError as e:
            copia = caminho.with_name(f"{caminho.stem}-estragado-{time.strftime('%Y%m%d-%H%M%S')}{caminho.suffix}")
            try:
                shutil.copy2(caminho, copia)
            except OSError:
                copia = "(não consegui copiar)"
            print(f"[dados] {caminho.name} está estragado ({e}). Guardei uma cópia em {copia}.")
            return padrao


def gravar_json(caminho, obj, indent=2):
    """Grava num arquivo temporário só desta gravação e troca pelo arquivo de verdade de uma vez só,
    para o arquivo nunca ficar pela metade."""
    caminho = Path(caminho)
    tmp = caminho.with_name(f"{caminho.stem}.{os.getpid()}-{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), "utf-8")
    for i in range(TENTATIVAS):
        try:
            os.replace(tmp, caminho)
            return
        except PermissionError:
            if i == TENTATIVAS - 1:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise
            time.sleep(0.05)


def apagar_arquivo(caminho):
    """Apaga um arquivo da Estante (uma capa velha, por exemplo). Se ele já não existe, tudo bem;
    qualquer outro problema vai para o estante.log, em vez de passar em silêncio."""
    try:
        Path(caminho).unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        print(f"[dados] não consegui apagar {Path(caminho).name}: {e}")


def migrar(antiga, nova):
    """Copia uma pasta de dados antiga para a nova, se a nova ainda estiver vazia.
    A pasta antiga não é apagada: ela fica como cópia de segurança."""
    antiga, nova = Path(antiga), Path(nova)
    if not (antiga / "library.json").exists() or (nova / "library.json").exists():
        return False
    nova.mkdir(parents=True, exist_ok=True)
    for item in antiga.iterdir():
        destino = nova / item.name
        if item.is_dir():
            shutil.copytree(item, destino, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destino)
    return True


def _avisar_copia(antiga, nova):
    try:
        (Path(antiga) / "LEIA - dados copiados.txt").write_text(
            f"Em {time.strftime('%d/%m/%Y %H:%M')} a Estante copiou estes dados para:\n{nova}\n\n"
            "A partir de agora ela usa a pasta nova. Esta pasta ficou só como cópia de segurança\n"
            "e pode ser apagada quando você quiser.\n", "utf-8")
    except OSError:
        pass


def pasta_dados():
    if os.environ.get("ESTANTE_DATA"):
        d = Path(os.environ["ESTANTE_DATA"])
        antigas = []
    elif os.name == "nt" and os.environ.get("APPDATA"):
        d = Path(os.environ["APPDATA"]) / NOME_PASTA
        antigas = [Path(os.environ["APPDATA"]) / NOME_PASTA_ANTIGA]
    else:
        d = Path.home() / ".estante"
        antigas = [Path.home() / ".estante-de-jogos"]
    d.mkdir(parents=True, exist_ok=True)
    # versões antigas guardavam tudo em "data", ao lado do programa
    for antiga in antigas + [BASE / "data"]:
        try:
            if migrar(antiga, d):
                print(f"[dados] trouxe os dados de {antiga}")
                if antiga in antigas:
                    _avisar_copia(antiga, d)
                break
        except Exception as e:
            print("[dados] não consegui trazer os dados antigos:", e)
    return d


def navegador_app(preferido=""):
    """Edge ou Chrome, para abrir janelas no "modo app" (sem barra de endereço).
    preferido = "chrome" ou "edge": o navegador onde está a extensão da Leitura, se ela já avisou."""
    candidatos = [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ]
    if preferido == "chrome":
        candidatos = candidatos[2:] + candidatos[:2]
    for c in candidatos:
        c = os.path.expandvars(c)
        if os.path.exists(c):
            return c
    return ""

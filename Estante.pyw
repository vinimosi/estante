"""
Abre a Estante como um programa: sem terminal, numa janela própria
e com um ícone perto do relógio. Fecha sozinha quando a janela é fechada.
"""
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))
from caminhos import navegador_app, pasta_dados  # noqa: E402

# sem terminal, tudo o que seria mostrado vai para um arquivo de registro
_arq = pasta_dados() / "estante.log"
if _arq.exists() and _arq.stat().st_size > 1_000_000:  # começa de novo quando passa de 1 MB
    _arq.unlink()
_log = open(_arq, "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = _log
import logging  # noqa: E402
logging.getLogger("werkzeug").setLevel(logging.WARNING)  # não registra cada acesso
print(f"\n=== Estante aberta em {time.strftime('%d/%m/%Y %H:%M')} ===")

PORTA = 8765
URL = f"http://127.0.0.1:{PORTA}"


def ja_esta_aberta():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def abrir_janela():
    """Abre numa janela própria (modo app do Edge ou Chrome), sem barra de endereço."""
    nav = navegador_app()
    if nav:
        subprocess.Popen([nav, f"--app={URL}", "--window-size=1320,860"])
        return
    webbrowser.open(URL)


def main():
    if ja_esta_aberta():
        abrir_janela()
        return

    import app as estante
    from werkzeug.serving import make_server

    servidor = make_server("127.0.0.1", PORTA, estante.app, threaded=True)
    estante.vigiar_pastas()  # importa das lojas e procura jogos novos e versões novas a cada 5 minutos
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    abrir_janela()

    fim = threading.Event()
    icone = None

    def sair(*_):
        fim.set()
        if icone:
            icone.stop()

    def vigia():
        # fecha quando ninguém está com a janela aberta e nenhum jogo está rodando
        while not fim.is_set():
            time.sleep(5)
            if estante.ocioso():
                print("Janela fechada e nenhum jogo aberto: encerrando.")
                sair()

    threading.Thread(target=vigia, daemon=True).start()
    estante.AO_SAIR.append(sair)  # a atualização automática fecha a Estante por aqui

    try:
        import pystray
        from icone import desenhar

        def curto(t, n=40):
            return t if len(t) <= n else t[:n - 1] + "…"

        def abrir(tipo, ident):
            def f(*_):
                try:
                    if not estante.abrir_atalho(tipo, ident):
                        abrir_janela()
                except Exception as e:
                    print("[bandeja]", e)
                    abrir_janela()
            return f

        def itens():
            """Montado de novo a cada minuto: os últimos jogos jogados e as últimas séries lidas."""
            yield pystray.MenuItem("Abrir a Estante", lambda *_: abrir_janela(), default=True)
            try:
                a = estante.atalhos_bandeja()
            except Exception as e:
                print("[bandeja]", e)
                a = {"jogos": [], "series": []}
            if a["series"]:
                yield pystray.Menu.SEPARATOR
                yield pystray.MenuItem("Continuar lendo", None, enabled=False)
                for s in a["series"]:
                    yield pystray.MenuItem(curto(s["nome"]) + (f"  ·  {s['rotulo']}" if s["rotulo"] else ""), abrir("serie", s["id"]))
            if a["jogos"]:
                yield pystray.Menu.SEPARATOR
                yield pystray.MenuItem("Jogar de novo", None, enabled=False)
                for g in a["jogos"]:
                    yield pystray.MenuItem(curto(g["nome"]), abrir("jogo", g["id"]))
            yield pystray.Menu.SEPARATOR
            yield pystray.MenuItem("Fechar a Estante", sair)

        icone = pystray.Icon("estante", desenhar(64), "Estante", menu=pystray.Menu(lambda: tuple(itens())))

        def renovar_menu():
            while not fim.wait(60):
                try:
                    icone.update_menu()
                except Exception as e:
                    print("[bandeja]", e)
        threading.Thread(target=renovar_menu, daemon=True).start()
        icone.run()  # fica aqui até sair()
    except Exception as e:
        print("Ícone perto do relógio indisponível:", e)
        fim.wait()

    servidor.shutdown()
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "A Estante não conseguiu abrir. Veja o arquivo estante.log em %APPDATA%\\Estante para detalhes.", "Estante", 0x10)
        except Exception:
            pass

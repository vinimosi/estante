"""Importado antes do app em todos os testes: nada abre de verdade no computador.
No Linux isso já não acontecia (não existe os.startfile), mas no Windows o "Jogar" abria a loja de verdade,
"Abrir pasta" abria o Explorer e a janela de leitura abria o Edge. Aqui tudo isso só é anotado em ABERTOS."""
import os
import webbrowser

import caminhos

ABERTOS = []

os.startfile = lambda alvo, *a, **k: ABERTOS.append(str(alvo))
webbrowser.open = lambda url, *a, **k: ABERTOS.append(url)
caminhos.navegador_app = lambda *a, **k: ""  # sem Edge/Chrome no modo app: cai no webbrowser.open acima

# A tela de boas-vindas da instalação nova atrapalharia os testes da tela. O testar_boas_vindas.py tira isto.
os.environ.setdefault("ESTANTE_SEM_BOAS_VINDAS", "1")
os.environ.setdefault("ESTANTE_SEM_VIGIA_MUSICA", "1")
os.environ.setdefault("ESTANTE_SEM_VIGIA_ATUALIZACAO", "1")  # nada de perguntar ao GitHub nos testes  # o histórico de músicas não lê o painel por trás nos testes

# Instalação nova começa sem sites de leitura. Nos testes, a pessoa de mentira já lê nos três sites conhecidos
# (o testar_config.py confere a instalação nova de verdade, sem nenhum).
import leitura  # noqa: E402
leitura.SITES_INICIAIS = tuple(s["chave"] for s in leitura.SITES_PADRAO)

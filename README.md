# Estante

Um lugar só para o que você joga e lê, no Windows.

- **Jogos**: os jogos da Steam, Epic Games, GOG, EA app, Ubisoft Connect, Battle.net e Xbox entram sozinhos, junto com os que não vêm de loja (escaneando a pasta onde ficam). Tempo jogado, coleções, capas, versão nova de jogos de fora das lojas, estatísticas e modo TV com controle.
- **Leitura**: mangás, manhwas e HQs que você lê nos sites, com o capítulo onde parou, aviso de capítulo novo, ligação com a sua conta do MangaUpdates, leitor de quadrinhos do PC e capítulos baixados para ler sem internet.
- **Tocando agora**: o que toca no Spotify, no YouTube ou no YouTube Music, com a letra.

A Estante roda só no seu computador. Ela não tem conta, não guarda senhas e não manda os seus dados para ninguém.

## Instalar

1. Baixe o **Instalar-Estante.exe** da [versão mais nova](../../releases/latest).
2. Abra o arquivo. Como a Estante não tem assinatura digital paga, o Windows mostra o aviso **"O Windows protegeu o computador"**. Clique em **Mais informações** e depois em **Executar assim mesmo**. Se o navegador avisar que o arquivo "não é baixado com frequência", escolha manter o arquivo.
3. Confirme. A Estante vai para a sua pasta de usuário (sem pedir senha de administrador), ganha um atalho na área de trabalho e no menu Iniciar e já abre.

Não precisa instalar Python nem mais nada: tudo o que ela usa vem dentro do instalador.

Para atualizar, não precisa fazer nada: uma vez por dia a Estante olha se saiu versão nova e mostra o botão **Atualizar**. Ela baixa, fecha, troca o programa e abre de novo, esperando antes se algum jogo estiver aberto. Seus dados continuam iguais.

## A extensão do navegador (para a Leitura)

A extensão marca sozinha os capítulos que você abre nos sites. Ela vem junto com a Estante:

1. No Edge, abra `edge://extensions` (no Chrome, `chrome://extensions`).
2. Ligue o **Modo de desenvolvedor**.
3. Clique em **Carregar sem pacote** (no Chrome, **Carregar sem compactação**) e escolha a pasta `%LOCALAPPDATA%\Programs\Estante\app\extensao`.

Na Estante, em Leitura > Adicionar > Instalar a extensão, há o mesmo passo a passo e um botão que abre essa pasta. Quando a Estante for atualizada e trouxer uma extensão mais nova, ela avisa: é só clicar em **Recarregar** na página de extensões.

## Onde ficam os dados

Tudo o que é seu fica em `%APPDATA%\Estante`, separado do programa: atualizar ou desinstalar não apaga nada. A Estante guarda uma cópia de segurança por dia (Configurações > Geral).

Para desinstalar: Configurações do Windows > Aplicativos > Estante > Desinstalar.

## Rodar pelo código-fonte

Com o Python 3 instalado (marcando "Add python.exe to PATH"), dê dois cliques em `Instalar.bat`. Ele instala os componentes, cria o atalho e abre a Estante. Rodando assim, a atualização automática só avisa que saiu versão nova.

- Testes: `cd testes` e rode cada `testar_*.py` (precisam de `pip install flask psutil pillow playwright pystray` e `playwright install chromium`). Eles usam computadores, sites e serviços de mentira e nunca tocam nos seus dados.
- Montar o instalador: `python empacotar/empacotar.py`. Sai em `dist/` o `Estante-<versão>.zip` (o que a atualização baixa) e o `Instalar-Estante.exe`.

O uso completo está explicado no [LEIA-ME.txt](LEIA-ME.txt).

## Licença

[MIT](LICENSE).

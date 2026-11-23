# Implantacao no Render - preparacao (sem deploy)

Esta configuracao **nao cria** um servico no Render. A ativacao do Blueprint e do plano pago requer acao explicita na conta Render.

## Riscos do modo sem login

O modo `BIOSAUDE_AUTH_MODE=public` libera **apenas a area Operador**, sem acesso ao catalogo administrativo. Ele nao oferece controle de quem usa a aplicacao. Um link nao divulgado **nao e** protecao de acesso. Qualquer pessoa que descubra a URL podera enviar documentos.

**Use somente dados sinteticos de demonstracao nesta fase. Nao envie orcamentos reais com dados de pacientes enquanto nao houver uma barreira de acesso adequada (rede privada, VPN, proxy com controle de acesso, ou autenticacao).** HTTPS protege dados em transito, nao restringe visitantes.

## Como funciona a hospedagem

- O arquivo `render.yaml` prepara um servico Python pago, disco persistente em `/var/data` e deploy automatico desligado.
- O processo escuta `0.0.0.0` e a porta `PORT` informada pelo Render, sem mudar a configuracao local.
- O start exige `/var/data/tuss.sqlite3` existente e nao vazio; isso previne uma demonstracao sem catalogo. O app nao carrega nem atualiza bases privadas a partir do GitHub.
- `/var/data/audit.sqlite3` armazena decisoes de revisao sem gravar arquivos de cotacao no disco.
- O catalogo TUSS e os dados pessoais continuam fora do Git.

## Preparacao do catalogo

1. Em um computador privado com os dois arquivos TUSS reduzidos, execute `python -m scripts.import_tuss --diretorio /diretorio/privado --versao "Inicial"`.
2. Valide a quantidade e a integridade do SQLite, inclusive `PRAGMA integrity_check` e a existencia de uma versao ativa.
3. Copie `data/tuss.sqlite3` ao disco persistente do servico Render como `/var/data/tuss.sqlite3`, por uma transferencia segura de arquivos permitida no ambiente; nao publique o banco no Git.
4. Ajuste permissoes para o usuario do processo. Ao iniciar, o aplicativo verifica a presenca do arquivo. O arquivo de auditoria sera criado no mesmo disco.

**Atencao:** um deploy normal nao popula o disco por si so. O build e o pre-deploy nao escrevem no disco persistente. Planeje a transferencia antes de iniciar o servico; um primeiro start sem o banco ira falhar propositalmente.

## Passos de ativacao manual

1. Revisar o custo atual do plano pago e do disco no Render.
2. Verificar se o recurso para transferir o banco a um disco persistente esta disponivel no plano selecionado.
3. No painel Render, criar um Blueprint a partir do repositorio `Biosaude/Planilha-S-o-Camilo`, usando `render.yaml`.
4. Confirmar as variaveis e os custos apresentados; nao executar testes com dados reais.
5. Transferir o banco TUSS e iniciar/reiniciar o servico.
6. Verificar `/_stcore/health`, testar upload e download usando PDF e Excel **sinteticos** e conferir a preservacao da planilha.
7. Antes de liberar o uso operacional, avaliar formalmente a exposicao publica e aplicar uma camada de acesso que proteja arquivos hospitalares.

## Testes locais

```bash
python -m pytest -q
python -m pip check
```

A mera existencia do Blueprint nao comprova que o deploy, os testes de navegador, o Microsoft Excel ou os controles de acesso foram validados em producao.

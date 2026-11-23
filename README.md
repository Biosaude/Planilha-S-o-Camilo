# Automação de Cotações OPME — Hospital São Camilo

Aplicativo Streamlit da Biosaúde para consultar as duas bases TUSS e preencher a
planilha original do hospital com dados do orçamento VS|OPME. O processamento
de documentos ocorre na máquina que hospeda a aplicação.

## Instalação e execução local

Na raiz do projeto, com Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Coloque as duas planilhas TUSS em um diretório privado, com os nomes
`PLANILHA COM CÓDIGO TUSS_PARTE_1.xlsx` e `PLANILHA COM CÓDIGO TUSS_PARTE_2.xlsx`.
Aponte a importação para esse diretório ou informe cada arquivo com
`--parte-1` e `--parte-2`. O diretório padrão é `data/`.

```bash
python -m scripts.import_tuss --diretorio /caminho/privado --versao "Catálogo inicial"
python -m scripts.import_tuss --listar
```

Crie senhas locais distintas, com ao menos 16 caracteres. A senha de operador é
obrigatória para o modo local. Defina a senha de administrador caso precise
acessar o catálogo pela interface. O shell pode ler os valores sem exibi-los ou
registrá-los no histórico:

```bash
export BIOSAUDE_AUTH_MODE=local
read -rs -p 'Senha de operador: ' BIOSAUDE_OPERATOR_PASSWORD; printf '\n'
export BIOSAUDE_OPERATOR_PASSWORD
# Opcional
read -rs -p 'Senha de administrador: ' BIOSAUDE_ADMIN_PASSWORD; printf '\n'
export BIOSAUDE_ADMIN_PASSWORD
streamlit run app.py
```

Abra `http://127.0.0.1:8501` na mesma máquina. Consulte
[.env.example](.env.example) para os nomes de configuração. Um arquivo `.env`
é opcional e, se usado, deve ser carregado pelo shell antes do comando. O app
lê as variáveis de ambiente do processo.

## Operação

1. Entre com o perfil **Operador** e envie o Excel original e o PDF pesquisável.
2. Clique em **Processar cotação** e confira produtos, linhas e códigos TUSS.
3. Para cada linha pendente, confira as especificações e selecione e confirme
   a linha, ou omita o item. Cada linha só pode ser usada por um item. O sistema
   registra as decisões manuais ao preparar a exportação.
4. Clique em **Preparar planilha para download** e baixe o resultado. Códigos TUSS
   sem evidência suficiente ficam em branco. As demais linhas do hospital
   conservam o conteúdo original.

O importador mantém todos os registros, inclusive quando vários códigos
compartilham o mesmo registro ANVISA. A busca considera modelo, registro,
fabricante e termo oficial. A vigência é comparada com a data de emissão do PDF
quando a base informa limites. Candidatos TUSS ficam disponíveis para conferência
e a exportação só preenche os códigos confirmados pelo catálogo.

## Atualização e recuperação do catálogo

Entre como **Administrador**, abra **Catálogo TUSS**, informe uma versão e
envie ambos os arquivos. Os cabeçalhos e registros são validados em uma
transação antes da ativação do conjunto. A tela mostra contagens por parte,
registros repetidos, ANVISA inválidos e registros ANVISA associados a mais de um
código. As versões anteriores permanecem no banco.

Para reativar uma versão, use a opção administrativa ou os comandos abaixo.

```bash
python -m scripts.import_tuss --listar
python -m scripts.import_tuss --restaurar 1
```

O SQLite padrão fica em `data/tuss.sqlite3`. As decisões de revisão são
registradas em `data/audit.sqlite3` com identificador da operação, perfil,
identificador técnico do operador, item, linha, ação, horário UTC e versão do
catálogo. O modo local identifica a sessão que tomou a decisão. O modo OIDC
registra o identificador individual do usuário. Os bancos podem ficar em
diretórios privados separados por meio de `BIOSAUDE_TUSS_DB` e
`BIOSAUDE_AUDIT_DB`. Faça backup desses bancos pelo mecanismo de backup do
SQLite ou com o serviço parado.

## Confidencialidade e hospedagem

Use o modo local apenas em loopback, como configurado no projeto. Para publicar
em uma rede, use `BIOSAUDE_AUTH_MODE=oidc` com um único provedor institucional e
um proxy HTTPS com controle de acesso institucional para HTTP e WebSocket.
Aplique a autenticação do proxy também aos uploads e downloads do Streamlit,
inclusive à rota `/media/`, e desabilite o cache compartilhado. Mantenha o backend
acessível somente ao proxy. Use a URL HTTPS do aplicativo como origem permitida
se o proxy exigir configuração adicional. Configure o callback OIDC para
`https://seu-dominio/oauth2callback`.

No arquivo privado `.streamlit/secrets.toml`, configure a seção `[auth]` com
`redirect_uri`, `cookie_secret`, `client_id`, `client_secret` e
`server_metadata_url` do provedor. Restrinja o acesso com as listas de
identificadores estáveis `sub` em `BIOSAUDE_OPERATOR_SUBJECTS` e
`BIOSAUDE_ADMIN_SUBJECTS`, separados por vírgulas. Valide autenticação, perfis,
HTTPS, limites de requisição e políticas de logs do proxy no ambiente de
destino antes de liberar acesso.

Uploads e exportações ficam em memória durante a sessão. Encerrar a sessão
pelo botão **Sair** limpa a análise e o resultado do aplicativo. O aplicativo
limita cada arquivo a 25 MB, rejeita PDFs protegidos e limita a expansão dos
arquivos Excel. Documentos de cotação e bases privadas devem permanecer fora
do Git. O aplicativo não transmite esses documentos ao provedor de identidade,
nem usa serviços externos de extração ou OCR.

## Testes

```bash
python -m pytest -q
```

Para incluir o caso obrigatório, passe os quatro caminhos privados:

```bash
BIOSAUDE_REQUIRE_REFERENCE=1 \
BIOSAUDE_TEST_EXCEL='/privado/tabela orçamentária São Camilo.xlsx' \
BIOSAUDE_TEST_PDF='/privado/Orçamento São Camilo.pdf' \
BIOSAUDE_TEST_TUSS_1='/privado/PLANILHA COM CÓDIGO TUSS_PARTE_1.xlsx' \
BIOSAUDE_TEST_TUSS_2='/privado/PLANILHA COM CÓDIGO TUSS_PARTE_2.xlsx' \
python -m pytest -q
```

A execução com os quatro originais passou em 18 testes. O fluxo no Chromium
também passou com upload dos originais, revisão, download e separação dos
perfis. O banco importado contém 47.279 registros, com integridade SQLite
verificada.

O teste real confere as seis linhas e o total de R$ 3.480,00, as duas bases, os
três códigos TUSS confirmados e os campos em branco. As linhas 17 e 22 exigem
revisão manual pelas divergências nas especificações registradas nos originais.
O teste exerce a confirmação nas duas linhas indicadas como referência no
pedido. Essa confirmação depende de evidência técnica em uso operacional.

A exportação usa OpenPyXL para validar e preparar as células e aplica as
alterações no XML da aba original. A conferência compara a estrutura XML da aba fora dos valores autorizados
e verifica que todas as outras partes do pacote permaneçam idênticas em bytes.
Isso preserva inclusive a imagem, o binário de impressão, os estilos e a
cadeia de cálculo do modelo fornecido. Fórmulas permanecem no arquivo e o
recálculo fica a cargo do aplicativo de planilha ao abrir. O arquivo exportado
foi reaberto com OpenPyXL. A abertura no Microsoft Excel precisa de validação
no ambiente de destino.

O MVP aceita o PDF pesquisável no layout VS|OPME validado e uma única tabela
visível com os cabeçalhos autorizados do São Camilo nas colunas B e D–H.
Variações de layout não reconhecidas e recursos que impedem a preservação
segura são recusados.

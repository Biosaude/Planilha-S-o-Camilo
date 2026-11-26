# Instalacao local - Windows 11

**Uso exclusivamente neste computador**, em `http://127.0.0.1:8501`. Nao use Render, VPN, abertura de portas ou acesso publico. O modo `public` dispensa login, mas o servidor escuta apenas no proprio computador. O perfil administrador nao e exposto.

## Pre-requisitos

- Windows 11 e permissao para instalar programas.
- Python 3.12 de 64 bits, com o Python Launcher `py` disponivel no PowerShell.
- Internet **somente na instalacao** para baixar o codigo e as dependencias.
- Duas planilhas TUSS reduzidas, mantidas em uma pasta privada da Biosaude. Nao copiar esses arquivos para o GitHub.

## Instalar

1. Baixe o repositorio GitHub em **Code > Download ZIP** e extraia-o, por exemplo em `C:\Biosaude\SaoCamilo`. Evite executar o aplicativo dentro do ZIP, OneDrive ou uma pasta temporaria.
2. Abra o PowerShell dentro da pasta extraida.
3. Execute `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Instalar-Windows11.ps1`.
4. O instalador cria `.venv`, instala dependencias, executa `pip check` e `pytest`, e cria o atalho **Biosaude - Cotacao Sao Camilo** na area de trabalho. Se um teste falhar, o atalho nao sera criado.
5. Importe o catalogo (passo abaixo).
6. Clique duas vezes no atalho. O navegador abre `http://127.0.0.1:8501`. **Mantenha a janela do terminal aberta** enquanto utilizar a ferramenta.

## Importar a base TUSS

Mantenha os dois arquivos com os nomes oficiais em uma pasta privada, por exemplo `C:\Biosaude\BasesTUSS`. Na pasta do projeto, execute:

```powershell
.\.venv\Scripts\python.exe -m scripts.import_tuss --diretorio "C:\Biosaude\BasesTUSS" --versao "Catalogo inicial"
.\.venv\Scripts\python.exe -m scripts.import_tuss --listar
```

Confirme a versao ativa e os 47.279 registros esperados para a base original validada. Nao reimporte arquivos diferentes sem conferir a contagem. O banco fica em `data\tuss.sqlite3`; o registro de revisoes fica em `data\audit.sqlite3`.

Se o banco TUSS ja estiver validado no computador de desenvolvimento, tambem e possivel copiar **somente o banco** para `data\tuss.sqlite3` com o aplicativo fechado, por um meio interno seguro. Confirme a integridade e versao ativa antes do uso.

## Operacao e protecao

- O usuario abre Excel e PDF, confere as correspondencias e baixa a planilha preenchida.
- O atalho nao solicita login nem senha.
- O aplicativo nao e acessivel de outros computadores da rede, porque escuta apenas `127.0.0.1`.
- Documentos hospitalares e bases TUSS nao devem entrar no Git, nem em pastas sincronizadas publicamente.
- O Windows deve ter conta de usuario protegida, atualizacoes e antivirus ativos; restrinja o acesso fisico ao computador.
- Faca backup seguro de `data\tuss.sqlite3` e `data\audit.sqlite3` com o aplicativo fechado. Nao compartilhe esses arquivos.
- Nao feche a janela do terminal enquanto trabalha. Se a porta 8501 estiver ocupada, encerre a instancia anterior.
- Valide a planilha exportada no Microsoft Excel instalado antes de utilizar em uma cotacao real.

## Observacoes

O instalador nao foi executado no Windows 11 da empresa; precisa ser testado nesse ambiente. Nao altera o fluxo de processamento, correspondencia, consulta TUSS ou exportacao Excel. O modo `public` foi criado anteriormente e e limitado ao perfil operador.

## Atualizar uma instalação existente para a correção de cotações

1. Use o atalho **Biosaude - Encerrar Sao Camilo** para parar a instância em
   segundo plano. Com o aplicativo fechado, faça backup de `data` em um local
   interno seguro, incluindo `tuss.sqlite3` e `audit.sqlite3`, se existir.
2. Baixe e extraia **em outra pasta** o ZIP do commit aprovado pelo PR #6.
   Copie `src\pdf_extractor.py` e `src\excel_writer.py` dele para `src` na
   instalação existente. Preserve `.venv`, `data`, as duas bases e os atalhos.
   O leitor de PDF aceita itens que têm código e cujo ANVISA está em branco.
   O exportador grava os identificadores na coluna F. Use o Python e as
   dependências instalados.
3. Opcionalmente, na pasta instalada, confirme a versão do catálogo e a
   integridade das dependências existentes:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.import_tuss --listar
   .\.venv\Scripts\python.exe -m pip check
   ```

4. Inicie pelo atalho **Biosaude - Cotacao Sao Camilo**. Confira a abertura
   no navegador local, sem terminal e sem solicitação de login. No encerramento,
   use o atalho correspondente e confirme que a página local para de responder.

### Conferência no Microsoft Excel

1. Processe o PDF nº 73.582 com o Excel correspondente do hospital. Confira
   os 20 itens e o total de R$ 311.964,37 no aplicativo. Some a coluna
   Quantidade da conferência para confirmar as 27 unidades. Complete a revisão
   das correspondências antes de exportar. Abra o arquivo baixado no Excel,
   de preferência como a primeira pasta de trabalho da sessão.
2. Sem editar fórmulas ou usar **Enter/F9**, confirme os totais. A soma de H
   deve ser R$ 311.964,37 quando todos os 20 itens estiverem incluídos. A
   soma dos preços unitários em G deve ser R$ 205.364,37 para os mesmos itens.
3. Selecione as células de total e verifique na barra de fórmulas que as
   expressões de soma foram preservadas. Confira **Fórmulas > Opções de
   Cálculo > Automático** e verifique bordas, fontes, cores e visualização de
   impressão.
4. Compare B com o catálogo TUSS. Em F, confira o ANVISA seguido do valor da
   coluna Código do PDF, por exemplo `10349000875 - AFAPRO28`. Se houver um
   único identificador, confira que ele aparece sozinho. Confira também a
   preservação de letras, pontos e zeros à esquerda.
   Em E, confira o sufixo único ` - BIOSAUDE` nas linhas cotadas e os campos
   vazios nas linhas não cotadas.

# Execucao em segundo plano - Windows 11

Esta atualizacao **nao altera** `app.py`, regras de cotacao ou o banco TUSS.

## Atualizar o computador ja instalado

1. Feche a janela antiga do terminal que executa o Streamlit.
2. Baixe o codigo atualizado do GitHub e copie apenas os novos arquivos `Iniciar-Sao-Camilo-SegundoPlano.vbs`, `Encerrar-Sao-Camilo.vbs` e os tres scripts novos da pasta `scripts` para a pasta **ja instalada**, preservando `.venv`, `data` e `base TUSS`. **Nao substitua nem apague a pasta instalada inteira.**
3. Abra PowerShell na pasta instalada e execute:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\Configurar-SegundoPlano.ps1"
```

4. O atalho existente **Biosaude - Cotacao Sao Camilo** passa a abrir o Streamlit sem terminal. O novo atalho **Biosaude - Encerrar Sao Camilo** encerra a instancia iniciada por esse mecanismo.

O navegador abre em `http://127.0.0.1:8501`. Fechar a aba **nao** encerra o servidor. Use o atalho de encerramento ao terminar.

O aplicativo continua restrito a `127.0.0.1` (somente este computador), sem login, e nao e publicado na rede. Os logs locais ficam em `data\runtime`; eles podem conter detalhes operacionais e devem ser protegidos.

Se o servidor nao iniciar, consulte `data\runtime\startup-error.log` e `data\runtime\streamlit-error.log`.

**Nao execute simultaneamente o inicializador antigo `.cmd` e o novo modo em segundo plano**, pois ambos utilizam a porta 8501. A atualizacao ainda precisa ser testada no Windows 11 da empresa.

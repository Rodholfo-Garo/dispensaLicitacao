# Radar de Dispensas — Região de Jundiaí

Busca automaticamente, na **API pública oficial do PNCP**, as contratações
por **Dispensa de Licitação** (Lei 14.133/2021, art. 75) que estão com
**proposta em aberto agora** em 8 cidades: Jundiaí, Várzea Paulista, Campo
Limpo Paulista, Itupeva, Cabreúva, Louveira, Vinhedo e Cajamar.

⚠️ **Antes de tudo:** este script foi escrito com base na documentação
oficial do PNCP, mas eu não consegui testá-lo rodando de verdade contra a
API (o ambiente onde eu rodo bloqueia esse domínio). Rode-o você mesmo
primeiro (`python buscar_dispensas.py`) e confira se o `dispensas.json`
sai com dados plausíveis antes de confiar no automatismo diário. Se algo
der erro, me mande a mensagem que aparecer no terminal que eu ajusto.

## O que tem aqui

- `buscar_dispensas.py` — o script que consulta o PNCP e gera `dispensas.json`. Não precisa instalar nada (só Python 3.8+, que já vem em qualquer Mac/Linux; no Windows, baixe em python.org).
- `dispensas.json` — os dados coletados (começa vazio).
- `index.html` — o painel visual, que lê o `dispensas.json` e mostra tudo filtrável.
- `.github/workflows/atualizar.yml` — a automação que roda o script todo dia, de graça, na nuvem do GitHub.

## Opção A (recomendada): automação na nuvem, de graça, via GitHub

Essa é a forma "dinâmica de verdade" — roda todo dia mesmo com seu
computador desligado, e te dá um link público (ou privado) para acessar o
painel de qualquer lugar.

1. Crie uma conta gratuita em [github.com](https://github.com), se ainda não tiver.
2. Crie um repositório novo (pode ser público ou privado — se for privado, o GitHub Pages exige plano pago, então prefira público se quiser hospedar o painel).
3. Envie todos os arquivos desta pasta para o repositório (pelo site mesmo, arrastando os arquivos, ou via `git`).
4. Vá em **Settings → Actions → General** e confirme que "Allow all actions" está habilitado.
5. Vá em **Settings → Actions → General → Workflow permissions** e marque **"Read and write permissions"** — sem isso a Action não consegue salvar o `dispensas.json` atualizado.
6. Vá na aba **Actions** do repositório, clique no workflow "Atualizar dispensas de licitação" e clique em **"Run workflow"** para testar manualmente pela primeira vez.
7. Confira se o `dispensas.json` foi atualizado com um commit novo. Se sim, está funcionando — a partir daí ele roda sozinho todo dia às 08h (horário de Brasília).
8. (Opcional, para ver o painel bonito) Vá em **Settings → Pages**, em "Source" escolha **"Deploy from a branch"**, branch `main`, pasta `/ (root)`, salve. Em alguns minutos o painel fica em `https://SEU-USUARIO.github.io/NOME-DO-REPOSITORIO/`.

## Opção B: rodar no seu computador, agendado

Só funciona nos dias/horários em que seu computador estiver ligado.

**Windows (Agendador de Tarefas):**
1. Instale Python em [python.org](https://python.org) se não tiver.
2. Abra o "Agendador de Tarefas" → "Criar Tarefa Básica".
3. Defina para rodar todo dia, no horário que quiser.
4. Em "Ação", escolha "Iniciar um programa": aponte para `python.exe` e em "Argumentos" coloque o caminho completo de `buscar_dispensas.py`.

**Mac/Linux (cron):**
```bash
crontab -e
# adicione a linha abaixo para rodar todo dia às 8h:
0 8 * * * cd /caminho/para/radar-dispensas && /usr/bin/python3 buscar_dispensas.py
```

Depois, para ver o painel localmente, **não dá para simplesmente abrir o
`index.html` clicando duas vezes** — o navegador bloqueia a leitura do
`dispensas.json` por segurança (política de CORS para arquivos `file://`).
Rode um servidor local simples:
```bash
cd radar-dispensas
python3 -m http.server 8000
```
E abra `http://localhost:8000` no navegador.

## Testando manualmente uma cidade só

```bash
python buscar_dispensas.py --cidade "Jundiaí" --saida teste.json
```

## Limites e avisos importantes

- A API do PNCP é pública e gratuita, mas é um serviço do governo — pode
  ficar fora do ar ocasionalmente, especialmente fora do horário comercial
  de Brasília. O script não trava nesses casos, só registra o aviso e
  segue.
- O filtro "possível obra/serviço especializado" é só uma busca por
  palavras-chave no texto do objeto — é um alerta, não uma garantia.
  Sempre leia o edital.
- O agendamento do GitHub Actions ("cron") pode atrasar alguns minutos em
  horários de pico da plataforma — é do GitHub, não tem como evitar.
- Se algum dia a estrutura da API do PNCP mudar, o script pode passar a
  retornar vazio ou dar erro. Me avise que eu ajusto.

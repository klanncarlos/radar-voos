# Radar de Voos Cloud V3

Esta versão roda automaticamente na nuvem usando GitHub Actions, sem depender do seu computador ligado.

## O que ela faz
- monitora múltiplas origens e destinos
- pesquisa janelas flexíveis de datas e duração
- alerta por preço-alvo, queda percentual e novo menor preço
- guarda histórico para evitar alertas repetidos
- executa automaticamente às 08:00 e 20:00 (horário de Brasília)
- envia alertas por Telegram
- envia alertas por e-mail via Resend
- possui suporte opcional à WhatsApp Cloud API
- publica um painel web simples
- inclui uma extensão Chrome que lê o painel da nuvem

## 1. Criar um repositório no GitHub
Crie um repositório e envie todos os arquivos desta pasta para ele.

## 2. Configurar os segredos
No GitHub: Settings > Secrets and variables > Actions > New repository secret.

Obrigatórios:
- AMADEUS_CLIENT_ID
- AMADEUS_CLIENT_SECRET
- AMADEUS_ENV = production (ou test)

Telegram (recomendado):
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

E-mail via Resend (opcional):
- RESEND_API_KEY
- ALERT_EMAIL_TO
- ALERT_EMAIL_FROM

WhatsApp Cloud API (opcional):
- WHATSAPP_TOKEN
- WHATSAPP_PHONE_NUMBER_ID
- WHATSAPP_TO

## 3. Personalizar seus radares
Edite `config.json`.

Você pode ter quantos monitores quiser. Cada um aceita:
- origins
- destinations
- date_start / date_end
- stay_min_days / stay_max_days
- target_price
- drop_percent
- non_stop
- travel_class

O parâmetro `max_queries_per_run` controla o consumo da API.

## 4. Testar
Abra a aba Actions no GitHub, selecione Radar de Voos e clique em Run workflow.

Se tudo estiver correto, `data/latest.json` e `data/state.json` serão atualizados automaticamente.

## 5. Painel web
Ative GitHub Pages:
Settings > Pages > Deploy from a branch > main > /docs

O painel ficará parecido com:
https://SEU-USUARIO.github.io/SEU-REPOSITORIO/

O feed usado pela extensão será:
https://SEU-USUARIO.github.io/SEU-REPOSITORIO/latest.json

## 6. Extensão Chrome
Abra chrome://extensions/
Ative Modo do desenvolvedor
Clique em Carregar sem compactação
Selecione a pasta `extension`
Cole nela a URL pública do `latest.json`

## Alertas
Telegram é o canal mais simples para receber alertas em tempo real.
E-mail funciona via Resend.
WhatsApp Cloud API exige configuração da Meta e pode possuir regras adicionais de mensagens/templates dependendo do uso.

## Segurança
Nunca coloque tokens diretamente em config.json nem envie segredos para o repositório.
Use somente GitHub Actions Secrets.

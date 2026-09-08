import os
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "data/state.json"
LATEST_PATH = ROOT / "data/latest.json"
DOCS_LATEST_PATH = ROOT / "docs/latest.json"

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_TO = os.environ.get("WHATSAPP_TO", "")

CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

if STATE_PATH.exists():
    STATE = json.loads(STATE_PATH.read_text(encoding="utf-8"))
else:
    STATE = {}


def request_json(url, method="GET", headers=None, data=None):
    body = None

    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers = {
            **(headers or {}),
            "Content-Type": "application/json"
        }

    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=headers or {}
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def travel_class_code(value):
    mapping = {
        "ECONOMY": "1",
        "PREMIUM_ECONOMY": "2",
        "BUSINESS": "3",
        "FIRST": "4"
    }

    return mapping.get(
        str(value or "ECONOMY").upper(),
        "1"
    )


def search_monitor(monitor):
    origins = ",".join(monitor["origins"])

    params = {
        "engine": "google_flights_deals",
        "api_key": SERPAPI_KEY,
        "departure_id": origins,
        "currency": CONFIG.get("currency", "BRL"),
        "gl": "br",
        "hl": "pt-br",
        "type": "1",
        "travel_class": travel_class_code(
            monitor.get("travel_class")
        ),
        "adults": str(monitor.get("adults", 1)),
        "outbound_date":
            f'{monitor["date_start"]},{monitor["date_end"]}',
        "trip_length":
            f'{monitor.get("stay_min_days", 4)},'
            f'{monitor.get("stay_max_days", 8)}'
    }

    if monitor.get("non_stop"):
        params["stops"] = "1"

    url = (
        "https://serpapi.com/search.json?"
        + urllib.parse.urlencode(params)
    )

    print(
        f'Buscando {monitor["name"]}: '
        f'{origins} → {", ".join(monitor["destinations"])}'
    )

    data = request_json(url)

    if data.get("error"):
        raise RuntimeError(
            f'SerpApi: {data["error"]}'
        )

    wanted_destinations = {
        x.upper()
        for x in monitor["destinations"]
    }

    results = []

    for deal in data.get("deals", []):
        airport = str(
            deal.get("arrival_airport_code", "")
        ).upper()

        if airport not in wanted_destinations:
            continue

        price = deal.get("price")

        if price is None:
            continue

        results.append({
            "monitor_id": monitor["id"],
            "monitor_name": monitor["name"],
            "origin": deal.get(
                "departure_airport_code",
                origins
            ),
            "destination": airport,
            "destination_name": deal.get(
                "name",
                airport
            ),
            "country": deal.get("country", ""),
            "departure": deal.get(
                "start_date"
            ),
            "return": deal.get(
                "end_date"
            ),
            "price": float(price),
            "average_price": deal.get(
                "average_price"
            ),
            "discount_percentage":
                deal.get("discount_percentage"),
            "airline": deal.get(
                "airline",
                ""
            ),
            "stops": deal.get("stops"),
            "currency": CONFIG.get(
                "currency",
                "BRL"
            ),
            "flight_link": deal.get(
                "flight_link",
                ""
            )
        })

    return results


def format_price(value):
    formatted = (
        f"{float(value):,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )

    return f"R$ {formatted}"


def should_alert(monitor, best, old):
    reasons = []

    target = float(
        monitor.get("target_price", 0) or 0
    )

    previous = old.get("last_price")
    lowest = old.get("lowest_price")
    last_alert = old.get("last_alert_price")

    if target and best["price"] <= target:
        if (
            last_alert is None
            or best["price"]
            < float(last_alert) * 0.98
        ):
            reasons.append(
                "abaixo do seu preço-alvo"
            )

    if previous:
        drop = (
            (float(previous) - best["price"])
            / float(previous)
            * 100
        )

        if drop >= float(
            monitor.get("drop_percent", 12)
        ):
            reasons.append(
                f"queda de {drop:.0f}%"
            )

    if (
        lowest is not None
        and best["price"] < float(lowest)
    ):
        reasons.append(
            "novo menor preço histórico"
        )

    discount = best.get(
        "discount_percentage"
    )

    if (
        discount is not None
        and float(discount) >= 20
    ):
        reasons.append(
            f"{discount}% abaixo do preço médio"
        )

    return list(dict.fromkeys(reasons))


def whatsapp_message(monitor, deal, reasons):
    text = (
        f"✈️ PROMOÇÃO ENCONTRADA\n\n"
        f"{deal['origin']} → "
        f"{deal['destination']}\n"
        f"Destino: "
        f"{deal.get('destination_name', '')}\n\n"
        f"🛫 Ida: {deal['departure']}\n"
        f"🛬 Volta: {deal['return']}\n"
        f"💰 {format_price(deal['price'])}\n"
    )

    if deal.get("airline"):
        text += (
            f"✈ Companhia: "
            f"{deal['airline']}\n"
        )

    if deal.get(
        "discount_percentage"
    ) is not None:
        text += (
            f"🔥 Desconto indicado: "
            f"{deal['discount_percentage']}%\n"
        )

    text += (
        "\nMotivo do alerta: "
        + ", ".join(reasons)
    )

    if deal.get("flight_link"):
        text += (
            "\n\n🔎 Ver no Google Flights:\n"
            + deal["flight_link"]
        )

    return text


def send_whatsapp(text):
    if not (
        WHATSAPP_TOKEN
        and WHATSAPP_PHONE_NUMBER_ID
        and WHATSAPP_TO
    ):
        print(
            "WhatsApp ainda não configurado. "
            "Alerta apenas registrado."
        )
        return False

    url = (
        "https://graph.facebook.com/v23.0/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    payload = {
        "messaging_product": "whatsapp",
        "to": WHATSAPP_TO,
        "type": "text",
        "text": {
            "body": text
        }
    }

    request_json(
        url,
        method="POST",
        headers={
            "Authorization":
                "Bearer " + WHATSAPP_TOKEN
        },
        data=payload
    )

    return True


def main():
    if not SERPAPI_KEY:
        raise RuntimeError(
            "SERPAPI_KEY não configurada."
        )

    all_deals = []
    alerts_sent = 0

    for monitor in CONFIG.get(
        "monitors",
        []
    ):
        try:
            deals = search_monitor(
                monitor
            )

            all_deals.extend(deals)

            if not deals:
                print(
                    f'Nenhuma oferta compatível '
                    f'em {monitor["name"]}.'
                )
                continue

            best = min(
                deals,
                key=lambda x: x["price"]
            )

            old = STATE.get(
                monitor["id"],
                {}
            )

            reasons = should_alert(
                monitor,
                best,
                old
            )

            previous_low = old.get(
                "lowest_price"
            )

            if previous_low is None:
                lowest = best["price"]
            else:
                lowest = min(
                    float(previous_low),
                    best["price"]
                )

            new_state = {
                "last_price":
                    best["price"],
                "lowest_price":
                    lowest,
                "last_route":
                    (
                        f'{best["origin"]}-'
                        f'{best["destination"]}'
                    ),
                "last_departure":
                    best["departure"],
                "last_return":
                    best["return"],
                "updated_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat()
            }

            if reasons:
                message = whatsapp_message(
                    monitor,
                    best,
                    reasons
                )

                sent = send_whatsapp(
                    message
                )

                print(message)

                new_state[
                    "last_alert_price"
                ] = best["price"]

                if sent:
                    alerts_sent += 1

            elif old.get(
                "last_alert_price"
            ) is not None:
                new_state[
                    "last_alert_price"
                ] = old[
                    "last_alert_price"
                ]

            STATE[
                monitor["id"]
            ] = new_state

        except Exception as error:
            print(
                f'Erro em '
                f'{monitor.get("name")}: '
                f'{error}'
            )

    all_deals.sort(
        key=lambda x: x["price"]
    )

    latest = {
        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "deals":
            all_deals[:50],
        "alerts_sent":
            alerts_sent
    }

    STATE_PATH.write_text(
        json.dumps(
            STATE,
            indent=2,
            ensure_ascii=False
        ) + "\n",
        encoding="utf-8"
    )

    LATEST_PATH.write_text(
        json.dumps(
            latest,
            indent=2,
            ensure_ascii=False
        ) + "\n",
        encoding="utf-8"
    )

    DOCS_LATEST_PATH.write_text(
        json.dumps(
            latest,
            indent=2,
            ensure_ascii=False
        ) + "\n",
        encoding="utf-8"
    )

    print(
        f"Concluído: "
        f"{len(all_deals)} ofertas "
        f"e {alerts_sent} alerta(s)."
    )


if __name__ == "__main__":
    main()

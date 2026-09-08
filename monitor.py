import os
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
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

try:
    STATE = json.loads(STATE_PATH.read_text(encoding="utf-8"))
except Exception:
    STATE = {}

STATE.setdefault("_rotation", {})


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

    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def travel_class_code(value):
    mapping = {
        "ECONOMY": "1",
        "PREMIUM_ECONOMY": "2",
        "BUSINESS": "3",
        "FIRST": "4"
    }
    return mapping.get(str(value or "ECONOMY").upper(), "1")


def date_pairs(monitor):
    start = datetime.strptime(monitor["date_start"], "%Y-%m-%d").date()
    end = datetime.strptime(monitor["date_end"], "%Y-%m-%d").date()

    min_days = int(monitor.get("stay_min_days", 4))
    max_days = int(monitor.get("stay_max_days", 8))

    if end <= start:
        return []

    # Cria amostras de datas distribuídas pela janela.
    total_days = (end - start).days

    offsets = sorted(set([
        0,
        total_days // 4,
        total_days // 2,
        (total_days * 3) // 4
    ]))

    stays = sorted(set([
        min_days,
        (min_days + max_days) // 2,
        max_days
    ]))

    pairs = []

    for offset in offsets:
        outbound = start + timedelta(days=offset)

        for stay in stays:
            return_date = outbound + timedelta(days=stay)

            if return_date <= end:
                pairs.append((
                    outbound.isoformat(),
                    return_date.isoformat()
                ))

    return pairs


def choose_pairs(monitor):
    pairs = date_pairs(monitor)

    if not pairs:
        return []

    monitor_id = monitor["id"]

    position = int(
        STATE["_rotation"].get(monitor_id, 0)
    )

    # Duas combinações por monitor em cada execução.
    selected = []

    for i in range(min(2, len(pairs))):
        selected.append(
            pairs[(position + i) % len(pairs)]
        )

    STATE["_rotation"][monitor_id] = (
        position + len(selected)
    ) % len(pairs)

    return selected


def search_flights(monitor, outbound, return_date):
    params = {
        "engine": "google_flights",
        "api_key": SERPAPI_KEY,
        "departure_id": ",".join(monitor["origins"]),
        "arrival_id": ",".join(monitor["destinations"]),
        "outbound_date": outbound,
        "return_date": return_date,
        "type": "1",
        "travel_class": travel_class_code(
            monitor.get("travel_class")
        ),
        "adults": str(monitor.get("adults", 1)),
        "currency": CONFIG.get("currency", "BRL"),
        "gl": "br",
        "hl": "pt-br",
        "sort_by": "2"
    }

    if monitor.get("non_stop"):
        params["stops"] = "1"

    url = (
        "https://serpapi.com/search.json?"
        + urllib.parse.urlencode(params)
    )

    print(
        f'Buscando {monitor["name"]}: '
        f'{",".join(monitor["origins"])} → '
        f'{",".join(monitor["destinations"])} | '
        f'{outbound} a {return_date}'
    )

    data = request_json(url)

    if data.get("error"):
        raise RuntimeError(data["error"])

    flights = []

    raw_results = (
        data.get("best_flights", [])
        + data.get("other_flights", [])
    )

    for result in raw_results:
        price = result.get("price")

        if price is None:
            continue

        legs = result.get("flights", [])

        if not legs:
            continue

        first = legs[0]
        last = legs[-1]

        departure_airport = first.get(
            "departure_airport", {}
        )
        arrival_airport = last.get(
            "arrival_airport", {}
        )

        airlines = []

        for leg in legs:
            airline = leg.get("airline")
            if airline and airline not in airlines:
                airlines.append(airline)

        flights.append({
            "monitor_id": monitor["id"],
            "monitor_name": monitor["name"],
            "origin": departure_airport.get(
                "id",
                ",".join(monitor["origins"])
            ),
            "destination": arrival_airport.get(
                "id",
                ",".join(monitor["destinations"])
            ),
            "departure": outbound,
            "return": return_date,
            "price": float(price),
            "airline": ", ".join(airlines),
            "duration_minutes": result.get(
                "total_duration"
            ),
            "stops": max(len(legs) - 1, 0),
            "currency": CONFIG.get("currency", "BRL")
        })

    return flights


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

    historical_low = old.get("lowest_price")
    previous = old.get("last_price")
    last_alert = old.get("last_alert_price")

    if target and best["price"] <= target:
        if (
            last_alert is None
            or best["price"] < float(last_alert) * 0.98
        ):
            reasons.append("abaixo do preço-alvo")

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
                f"queda de {drop:.0f}% desde a última referência"
            )

    if (
        historical_low is not None
        and best["price"] < float(historical_low)
    ):
        reasons.append("novo menor preço registrado")

    return list(dict.fromkeys(reasons))


def whatsapp_message(monitor, deal, reasons):
    text = (
        "✈️ PASSAGEM EM PROMOÇÃO\n\n"
        f"{deal['origin']} → {deal['destination']}\n\n"
        f"🛫 Ida: {deal['departure']}\n"
        f"🛬 Volta: {deal['return']}\n"
        f"💰 {format_price(deal['price'])}\n"
    )

    if deal.get("airline"):
        text += f"✈️ Companhia: {deal['airline']}\n"

    text += (
        "\n🔥 " + ", ".join(reasons)
        + "\n\nPesquise estas datas no Google Flights."
    )

    return text


def send_whatsapp(text):
    if not (
        WHATSAPP_TOKEN
        and WHATSAPP_PHONE_NUMBER_ID
        and WHATSAPP_TO
    ):
        print("WhatsApp ainda não configurado.")
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

    all_results = []
    alerts_sent = 0

    for monitor in CONFIG.get("monitors", []):
        monitor_results = []

        pairs = choose_pairs(monitor)

        for outbound, return_date in pairs:
            try:
                results = search_flights(
                    monitor,
                    outbound,
                    return_date
                )

                monitor_results.extend(results)
                all_results.extend(results)

            except Exception as error:
                print(
                    f"Erro na busca {monitor['name']}: {error}"
                )

        if not monitor_results:
            print(
                f"Nenhum voo encontrado em {monitor['name']}."
            )
            continue

        best = min(
            monitor_results,
            key=lambda x: x["price"]
        )

        print(
            f"MELHOR PREÇO {monitor['name']}: "
            f"{format_price(best['price'])} | "
            f"{best['origin']} → {best['destination']} | "
            f"{best['departure']} a {best['return']}"
        )

        old = STATE.get(monitor["id"], {})

        reasons = should_alert(
            monitor,
            best,
            old
        )

        historical_low = old.get("lowest_price")

        if historical_low is None:
            lowest = best["price"]
        else:
            lowest = min(
                float(historical_low),
                best["price"]
            )

        new_state = {
            "last_price": best["price"],
            "lowest_price": lowest,
            "last_route":
                f"{best['origin']}-{best['destination']}",
            "last_departure": best["departure"],
            "last_return": best["return"],
            "updated_at":
                datetime.now(timezone.utc).isoformat()
        }

        if old.get("last_alert_price") is not None:
            new_state["last_alert_price"] = old[
                "last_alert_price"
            ]

        if reasons:
            message = whatsapp_message(
                monitor,
                best,
                reasons
            )

            print("\n" + message + "\n")

            if send_whatsapp(message):
                alerts_sent += 1

            new_state["last_alert_price"] = best["price"]

        STATE[monitor["id"]] = new_state

    all_results.sort(
        key=lambda x: x["price"]
    )

    latest = {
        "updated_at":
            datetime.now(timezone.utc).isoformat(),
        "results": all_results[:100],
        "alerts_sent": alerts_sent
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
        f"Concluído: {len(all_results)} voos encontrados "
        f"e {alerts_sent} alerta(s) enviado(s)."
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os, json, random, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
STATE_PATH = ROOT/"data/state.json"
LATEST_PATH = ROOT/"data/latest.json"
STATE = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}

AMADEUS_ID = os.environ.get("AMADEUS_CLIENT_ID", "")
AMADEUS_SECRET = os.environ.get("AMADEUS_CLIENT_SECRET", "")
AMADEUS_ENV = os.environ.get("AMADEUS_ENV", "production")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")
ALERT_EMAIL_FROM = os.environ.get("ALERT_EMAIL_FROM", "")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_TO = os.environ.get("WHATSAPP_TO", "")

def request_json(url, method="GET", headers=None, data=None):
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode()
            headers = {**(headers or {}), "Content-Type":"application/json"}
        else:
            body = data
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())

def amadeus_token():
    if not AMADEUS_ID or not AMADEUS_SECRET:
        raise RuntimeError("Configure AMADEUS_CLIENT_ID e AMADEUS_CLIENT_SECRET.")
    root = "https://api.amadeus.com" if AMADEUS_ENV == "production" else "https://test.api.amadeus.com"
    form = urllib.parse.urlencode({
        "grant_type":"client_credentials",
        "client_id":AMADEUS_ID,
        "client_secret":AMADEUS_SECRET
    }).encode()
    data = request_json(root+"/v1/security/oauth2/token", "POST",
                        {"Content-Type":"application/x-www-form-urlencoded"}, form)
    return root, data["access_token"]

def daterange(start, end, step):
    d = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    while d <= e:
        yield d
        d += timedelta(days=step)

def build_combos(m):
    combos = []
    step = max(1, int(CONFIG.get("date_step_days", 2)))
    stays = list(range(int(m.get("stay_min_days", 7)), int(m.get("stay_max_days", 7))+1))
    for o in m["origins"]:
        for d in m["destinations"]:
            for dep in daterange(m["date_start"], m["date_end"], step):
                for stay in stays:
                    combos.append((o,d,dep,stay))
    random.shuffle(combos)
    return combos

def search_offer(api_root, token, m, combo):
    o,d,dep,stay = combo
    ret = dep + timedelta(days=stay)
    params = {
        "originLocationCode":o,
        "destinationLocationCode":d,
        "departureDate":dep.isoformat(),
        "returnDate":ret.isoformat(),
        "adults":str(m.get("adults",1)),
        "currencyCode":CONFIG.get("currency","BRL"),
        "max":"10"
    }
    if m.get("non_stop"): params["nonStop"]="true"
    if m.get("travel_class"): params["travelClass"]=m["travel_class"]
    url = api_root+"/v2/shopping/flight-offers?"+urllib.parse.urlencode(params)
    try:
        data = request_json(url, headers={"Authorization":"Bearer "+token})
    except urllib.error.HTTPError as e:
        print("API", e.code, o, d, dep)
        return None
    offers = data.get("data", [])
    if not offers: return None
    best = min(offers, key=lambda x: float(x.get("price",{}).get("grandTotal","999999999")))
    return {
        "monitor_id":m["id"], "monitor_name":m["name"],
        "origin":o, "destination":d,
        "departure":dep.isoformat(), "return":ret.isoformat(),
        "price":float(best["price"]["grandTotal"]),
        "currency":best["price"].get("currency", CONFIG.get("currency","BRL"))
    }

def fmt_price(d):
    return f'{d["currency"]} {d["price"]:,.2f}'.replace(",", "X").replace(".", ",").replace("X",".")

def alert_reasons(m, best, old):
    reasons = []
    target = float(m.get("target_price",0) or 0)
    prev = old.get("last_price")
    low = old.get("lowest_price")
    if target and best["price"] <= target:
        # Don't spam same target hit unless materially improved since last alert
        last_alert = old.get("last_alert_price")
        if not last_alert or best["price"] < float(last_alert) * 0.98:
            reasons.append(f"abaixo do teto de R$ {target:,.0f}".replace(",","."))
    if prev:
        drop = (float(prev)-best["price"]) / float(prev) * 100
        if drop >= float(m.get("drop_percent",12)):
            reasons.append(f"queda de {drop:.0f}%")
    if low and best["price"] < float(low):
        reasons.append("novo menor preço histórico")
    return reasons

def text_for(m, best, reasons):
    return (f'✈ {m["name"]}\n'
            f'{best["origin"]} → {best["destination"]}\n'
            f'Ida: {best["departure"]} | Volta: {best["return"]}\n'
            f'Preço: {fmt_price(best)}\n'
            f'Motivo: {", ".join(reasons)}')

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    request_json(url,"POST",data={"chat_id":TELEGRAM_CHAT_ID,"text":text})

def send_email(subject, text):
    if not RESEND_API_KEY or not ALERT_EMAIL_TO or not ALERT_EMAIL_FROM: return
    request_json("https://api.resend.com/emails","POST",
      {"Authorization":"Bearer "+RESEND_API_KEY},
      {"from":ALERT_EMAIL_FROM,"to":[ALERT_EMAIL_TO],"subject":subject,"text":text})

def send_whatsapp(text):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_TO: return
    url=f"https://graph.facebook.com/v23.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    request_json(url,"POST",{"Authorization":"Bearer "+WHATSAPP_TOKEN},
      {"messaging_product":"whatsapp","to":WHATSAPP_TO,"type":"text","text":{"body":text}})

def main():
    api_root, token = amadeus_token()
    budget = int(CONFIG.get("max_queries_per_run",80))
    all_deals = []
    alerts = 0

    for m in CONFIG["monitors"]:
        if budget <= 0: break
        best = None
        for combo in build_combos(m)[:budget]:
            offer = search_offer(api_root, token, m, combo)
            budget -= 1
            if offer:
                all_deals.append(offer)
                if best is None or offer["price"] < best["price"]:
                    best = offer
            if budget <= 0: break
        if not best: continue

        old = STATE.get(m["id"], {})
        reasons = alert_reasons(m, best, old)
        lowest = min(float(old.get("lowest_price", best["price"])), best["price"])
        STATE[m["id"]] = {
            "last_price":best["price"],
            "lowest_price":lowest,
            "last_route":f'{best["origin"]}-{best["destination"]}',
            "last_departure":best["departure"],
            "updated_at":datetime.now(timezone.utc).isoformat()
        }
        if reasons:
            STATE[m["id"]]["last_alert_price"] = best["price"]
            txt = text_for(m,best,reasons)
            print(txt)
            for fn in (send_telegram, send_whatsapp):
                try: fn(txt)
                except Exception as e: print("Falha em alerta:", e)
            try: send_email(f'Radar de Voos: {m["name"]}', txt)
            except Exception as e: print("Falha no e-mail:", e)
            alerts += 1

    all_deals.sort(key=lambda x:x["price"])
    latest = {
        "updated_at":datetime.now(timezone.utc).isoformat(),
        "deals":all_deals[:50],
        "alerts_sent":alerts
    }
    STATE_PATH.write_text(json.dumps(STATE,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    LATEST_PATH.write_text(json.dumps(latest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    (ROOT/"docs/latest.json").write_text(json.dumps(latest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"Concluído. {len(all_deals)} ofertas úteis; {alerts} alerta(s).")

if __name__=="__main__":
    main()

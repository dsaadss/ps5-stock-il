"""Checks PS5 stock in Israeli stores via Zap price comparison and updates data.json."""
import html, json, re, sys, time, urllib.request
from datetime import datetime, timezone

# Zap model id -> (type shown on the site, short name)
MODELS = {
    1212371: ("דיסק", "PS5 Slim 1TB עם דיסק"),
    1212373: ("דיגיטלי", "PS5 Slim 1TB דיגיטלי"),
    1236321: ("Pro", "PS5 Pro 2TB"),
    1259070: ("Pro", "PS5 Pro 2TB + FC 26"),
    943747: ("דיסק", "PS5 825GB עם דיסק (דגם ישן)"),
    1096042: ("דיגיטלי", "PS5 825GB דיגיטלי (דגם ישן)"),
    1257068: ("דיסק", "PS5 Slim עם דיסק + FC 26"),
    1246900: ("דיסק", "PS5 Slim עם דיסק + Astro Bot"),
    1212378: ("דיסק", "PS5 Slim עם דיסק + Spider-Man 2"),
    1246933: ("דיסק", "PS5 Slim עם דיסק + 2 שלטים"),
    1212380: ("דיסק", "PS5 Slim עם דיסק + שלט נוסף ומטען"),
    1258425: ("דיגיטלי", "PS5 Slim דיגיטלי + FC 26"),
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
ROW = re.compile(r'class="compare-item-row product-item[^"]*"([^>]*)>')


def parse_stores(page):
    """Each store offering the model is one compare-item-row with data-* attributes."""
    stores = []
    for m in ROW.finditer(page):
        a = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', m.group(1)))
        if "site-name" not in a:
            continue
        stores.append({
            "store": html.unescape(a["site-name"]),
            "price": int(re.sub(r"\D", "", a.get("product-price", "")) or 0),
            "url": f"https://www.zap.co.il/fs?pid={a['pid']}" if a.get("pid") else None,
        })
    return sorted(stores, key=lambda s: s["price"] or 10**9)


def fetch(mid):
    req = urllib.request.Request(f"https://www.zap.co.il/model.aspx?modelid={mid}", headers={"User-Agent": UA})
    page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    if "compare-item" not in page and "model-page" not in page:
        raise RuntimeError("page does not look like a Zap model page (blocked?)")
    return page


def update(data, mid, stores, now):
    kind, name = MODELS[mid]
    m = data["models"].setdefault(str(mid), {"last_in_stock": None, "since": None})
    was = bool(m.get("stores"))
    m.update(name=name, type=kind, zap=f"https://www.zap.co.il/model.aspx?modelid={mid}",
             stores=stores, checked=now, error=None)
    if stores:
        m["last_in_stock"] = now
    if was != bool(stores) or m["since"] is None:
        m["since"] = now
        if was != bool(stores) or stores:
            data["log"].insert(0, {"time": now, "model": name,
                                   "event": "נכנס למלאי" if stores else "אזל מהמלאי",
                                   "stores": [s["store"] for s in stores]})
    del data["log"][300:]


def main():
    try:
        data = json.load(open("data.json", encoding="utf-8"))
    except FileNotFoundError:
        data = {"models": {}, "log": []}
    ok = 0
    for mid in MODELS:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            update(data, mid, parse_stores(fetch(mid)), now)
            ok += 1
        except Exception as e:  # keep the old stock data, just mark the error
            data["models"].setdefault(str(mid), {"name": MODELS[mid][1], "type": MODELS[mid][0]})["error"] = str(e)[:200]
            print(mid, "ERROR", e, file=sys.stderr)
        time.sleep(2)  # be polite to Zap
    data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    json.dump(data, open("data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{ok}/{len(MODELS)} models checked")
    sys.exit(0 if ok else 1)


def selftest():
    row = ('<div data-x="1" class="compare-item-row product-item has-tag" data-product-price="3,200" '
           'data-pid="42" data-site-name="Best &amp; Co">')
    assert parse_stores(row) == [{"store": "Best & Co", "price": 3200, "url": "https://www.zap.co.il/fs?pid=42"}]
    d = {"models": {}, "log": []}
    update(d, 1236321, [], "t1")
    assert d["models"]["1236321"]["last_in_stock"] is None and d["log"] == []
    update(d, 1236321, [{"store": "A", "price": 1, "url": None}], "t2")
    assert d["log"][0]["event"] == "נכנס למלאי" and d["models"]["1236321"]["last_in_stock"] == "t2"
    update(d, 1236321, [], "t3")
    m = d["models"]["1236321"]
    assert d["log"][0]["event"] == "אזל מהמלאי" and m["last_in_stock"] == "t2" and m["since"] == "t3"
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--test" in sys.argv else main()

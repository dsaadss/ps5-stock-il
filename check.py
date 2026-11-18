"""Checks PS5 stock in Israel (Zap price comparison + store sites directly) and updates data.json."""
import html, json, re, sys, time, urllib.parse, urllib.request
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
# Store product pages whose JSON-LD "availability" (InStock/OutOfStock) is the store's own stock flag.
JSONLD_PAGES = [
    ("באג", "https://www.bug.co.il/brand/sony/playstation/5/slim/digital"),
    ("באג", "https://www.bug.co.il/brand/sony/playstation/5/slim/fc26"),
    ("אייבורי", "https://www.ivory.co.il/catalog.php?id=156145"),
]
# WooCommerce Store API search (site, search word): each product has "is_in_stock".
WOO_SEARCH = [
    ("Cellfi", "https://cellfi.co.il", "playstation 5"),
    ("Green Mobile", "https://greenmobile.co.il", "playstation 5"),
    ("הייטק מובייל", "https://www.itechmobile.co.il", "playstation 5"),
    ("Roy Games", "https://roy-games.co.il", "playstation 5"),
    ("Roy Games", "https://roy-games.co.il", "פלייסטישן 5"),
]
# Konimbo store category pages: every product card has <span class="stock_state">in_stock|out_of_stock</span>.
KONIMBO_LISTS = [
    ("ד\"ר צ'יפ", "https://www.drchip.co.il/179526-playstation-5-consoles"),
    ("אנג'וי סטיק", "https://www.enjoystick.co.il/272731-%D7%A7%D7%95%D7%A0%D7%A1%D7%95%D7%9C%D7%95%D7%AA-PS5"),
]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
ROW = re.compile(r'class="compare-item-row product-item[^"]*"([^>]*)>')
PS5_NAME = re.compile(r"(?i)playstation\s*5|ps5|פלייסטיישן\s*5|פלייסטישן\s*5")
CONSOLE_WORD = re.compile(r"(?i)קונסול|console|825\s*gb|1\s*tb|2\s*tb|slim|סלים|digital|דיגיטל|blu-?ray|בלו.?ריי")
# shortcut: keyword list built from the stores' current titles; extend it if an accessory shows up as a console
NOT_CONSOLE = re.compile(r"(?i)portal|\bvr|^\s*(משחק|בקר|שלט)|כיסוי|מדבק|עמדת|טעינה|charging|הגה|ניקוי|משקפי|cover|skin|\bssd\b|"
                         r"כונן קשיח|תושבת|נרתיק|manager|access|נגישות|gift|קוד הורדה בלבד")


def is_console(title):
    return bool(PS5_NAME.search(title) and CONSOLE_WORD.search(title) and not NOT_CONSOLE.search(title))


def kind_of(title):
    return "Pro" if re.search(r"(?i)\bpro\b|פרו", title) else "דיגיטלי" if re.search(r"(?i)digital|דיגיטל", title) else "דיסק"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def parse_zap(page):
    """Each store offering the model on Zap is one compare-item-row with data-* attributes."""
    if "compare-item" not in page and "model-page" not in page:
        raise RuntimeError("page does not look like a Zap model page (blocked?)")
    stores = []
    for m in ROW.finditer(page):
        a = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', m.group(1)))
        if "site-name" in a:
            stores.append({"store": html.unescape(a["site-name"]),
                           "price": int(re.sub(r"\D", "", a.get("product-price", "")) or 0),
                           "url": f"https://www.zap.co.il/fs?pid={a['pid']}" if a.get("pid") else None})
    return sorted(stores, key=lambda s: s["price"] or 10**9)


def parse_jsonld(page):
    """-> (title, in_stock, price) from a product page's schema.org JSON-LD."""
    av = re.search(r'"availability"\s*:\s*"(?:https?://schema\.org/)?(\w+)"', page)
    if not av:
        raise RuntimeError("no availability on page (blocked or layout changed?)")
    title = re.search(r'<title>\s*([^<]+)', page)
    price = re.search(r'"price"\s*:\s*"?([\d.]+)', page)
    return (html.unescape(title.group(1)).strip()[:90] if title else "?", av.group(1) in ("InStock", "LimitedAvailability"),
            int(float(price.group(1))) if price else 0)


def parse_konimbo(page, base):
    """-> [(title, in_stock, price, url)] for PS5 console cards on a Konimbo category page."""
    out = []
    for card in page.split('class="layout_list_item')[1:]:
        t = re.search(r"<h3[^>]*>\s*(?:<a[^>]*>)?\s*([^<]+)", card)
        st = re.search(r'stock_state hidden">(\w+)', card)
        href = re.search(r"""href=['"]\s*(/items/[^'"\s]+)""", card)
        if not (t and st and href):
            continue
        title = re.sub(r"\s+", " ", html.unescape(t.group(1))).strip()
        if is_console(title):
            prices = [int(x.replace(",", "")) for x in re.findall(r"([\d,]+)\s*₪", card)]  # max: skips monthly-payment amounts
            out.append((title[:90], st.group(1) == "in_stock", max(prices, default=0), base + href.group(1)))
    if not out and "stock_state" not in page:
        raise RuntimeError("no product cards (blocked or layout changed?)")
    return out


def parse_woo(text):
    """-> [(title, in_stock, price, url)] for PS5 consoles in a WooCommerce Store API product list."""
    out = []
    for p in json.loads(text):
        title = html.unescape(p["name"])
        if is_console(title):
            pr = p.get("prices") or {}
            price = int(pr.get("price") or 0) // 10 ** int(pr.get("currency_minor_unit") or 0)
            out.append((title[:90], bool(p["is_in_stock"]), price, p["permalink"]))
    return out


def track(data, rec, in_stock, now, label, stores):
    """Update since/last_in_stock and log a line whenever stock starts or ends."""
    was = rec.get("in_stock")
    rec.update(in_stock=in_stock, checked=now, error=None)
    if in_stock:
        rec["last_in_stock"] = now
    rec.setdefault("last_in_stock", None)
    if was != in_stock:
        rec["since"] = now
        if was is not None or in_stock:
            data["log"].insert(0, {"time": now, "model": label, "event": "נכנס למלאי" if in_stock else "אזל מהמלאי", "stores": stores})
    del data["log"][300:]


def update_zap(data, mid, stores, now):
    kind, name = MODELS[mid]
    rec = data["models"].setdefault(str(mid), {})
    rec.update(name=name, type=kind, zap=f"https://www.zap.co.il/model.aspx?modelid={mid}", stores=stores)
    track(data, rec, bool(stores), now, name, [s["store"] for s in stores])


def update_direct(data, store, url, title, in_stock, price, now):
    rec = data["direct"].setdefault(url, {})
    rec.update(store=store, name=title, type=kind_of(title), price=price, url=url)
    track(data, rec, in_stock, now, f"{title} ({store})", [store])


def safe(data, key, bucket, fn, **fallback):
    try:
        fn()
        return 1
    except Exception as e:  # keep the old stock data, just mark the error
        data[bucket].setdefault(key, fallback)["error"] = str(e)[:200]
        print(key, "ERROR", e, file=sys.stderr)
        return 0
    finally:
        time.sleep(2)  # be polite to the sites


def main():
    try:
        data = json.load(open("data.json", encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    for k, v in (("models", {}), ("direct", {}), ("log", [])):
        data.setdefault(k, v)
    now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok = total = 0
    for mid in MODELS:
        total += 1
        ok += safe(data, str(mid), "models", lambda: update_zap(data, mid, parse_zap(fetch(f"https://www.zap.co.il/model.aspx?modelid={mid}")), now()),
                   name=MODELS[mid][1], type=MODELS[mid][0])
    for store, url in JSONLD_PAGES:
        total += 1
        ok += safe(data, url, "direct", lambda: update_direct(data, store, url, *parse_jsonld(fetch(url)), now()), store=store, name=url, url=url)
    for store, site, q in WOO_SEARCH:
        total += 1
        api = f"{site}/wp-json/wc/store/v1/products?per_page=100&search={urllib.parse.quote(q)}"
        ok += safe(data, site, "lists", lambda: [update_direct(data, store, u, t, s, p, now()) for t, s, p, u in parse_woo(fetch(api))])
    for store, url in KONIMBO_LISTS:
        total += 1
        base = re.match(r"https://[^/]+", url).group(0)
        ok += safe(data, url, "lists", lambda: [update_direct(data, store, u, t, s, p, now()) for t, s, p, u in parse_konimbo(fetch(url), base)])
    data.pop("lists", None)  # list-page errors are only printed
    data["updated"] = now()
    json.dump(data, open("data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{ok}/{total} sources checked")
    sys.exit(0 if ok else 1)


def selftest():
    row = ('<div data-x="1" class="compare-item-row product-item has-tag" data-product-price="3,200" '
           'data-pid="42" data-site-name="Best &amp; Co">')
    assert parse_zap("compare-item" + row) == [{"store": "Best & Co", "price": 3200, "url": "https://www.zap.co.il/fs?pid=42"}]
    assert parse_jsonld('<title>PS5</title>{"price":"2199.00","availability":"http://schema.org/OutOfStock"}') == ("PS5", False, 2199)
    assert parse_jsonld('"availability": "InStock"')[1] is True
    card = ('<div class="layout_list_item x"><h3><a href=" /items/1-a ">PlayStation 5 Pro 2TB</a></h3>'
            '<span class="stock_state hidden">in_stock</span> 6,999 ₪</div>'
            '<div class="layout_list_item x"><h3><a href="/items/2-b">GTA VI PlayStation 5</a></h3><span class="stock_state hidden">in_stock</span></div>')
    assert parse_konimbo(card, "https://s") == [("PlayStation 5 Pro 2TB", True, 6999, "https://s/items/1-a")]
    woo = ('[{"name":"Sony PlayStation 5 Pro 2TB","is_in_stock":true,"prices":{"price":"599900","currency_minor_unit":2},"permalink":"u"},'
           '{"name":"בקר Razer Raiju V3 Pro PlayStation 5","is_in_stock":true,"prices":{},"permalink":"v"}]')
    assert parse_woo(woo) == [("Sony PlayStation 5 Pro 2TB", True, 5999, "u")]
    assert is_console("קונסולת Sony PlayStation 5 Slim Digital Edition עם בקר DualSense") and not is_console("משחק Astro Bot ל-PlayStation 5")
    assert is_console("PlayStation 5 Pro Console – 30th Anniversary") and not is_console("כיסויים לקונסולת Sony PlayStation 5")
    assert is_console("פלייסטיישן 5 פרו דיגיטלי | Playstation 5 Pro Digital יבואן רשמי") and is_console("Playstation 5 SLIM כונן בלו ריי")
    assert not is_console("תושבת תלייה לקיר עבור קונסולת PlayStation PS5/Slim/Pro") and not is_console("Football manager console 2024 PS5")
    assert kind_of("PS5 Slim Digital") == "דיגיטלי" and kind_of("PS5 Pro 2TB") == "Pro" and kind_of("PS5 Slim 1TB Blu-ray") == "דיסק"
    d = {"models": {}, "direct": {}, "log": []}
    update_zap(d, 1236321, [], "t1")
    assert d["models"]["1236321"]["last_in_stock"] is None and d["log"] == []
    update_zap(d, 1236321, [{"store": "A", "price": 1, "url": None}], "t2")
    assert d["log"][0]["event"] == "נכנס למלאי" and d["models"]["1236321"]["last_in_stock"] == "t2"
    update_zap(d, 1236321, [], "t3")
    m = d["models"]["1236321"]
    assert d["log"][0]["event"] == "אזל מהמלאי" and m["last_in_stock"] == "t2" and m["since"] == "t3"
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--test" in sys.argv else main()

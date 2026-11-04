"""Turn the pages saved by capture.py into one listings file per source.

Reads out/pages/<source>/ and writes out/listings/<source>.json:
  {source, date, count, incomplete, listings: [{key, address, unit, beds, baths,
   rent, basis, available, status, url, ...}]}
A source whose parser finds nothing is written with incomplete=true and a note.

Usage: python parse.py [out_dir]
"""
import html as htmllib
import json
from datetime import datetime
import re
import sys
from pathlib import Path

from urllib.parse import urljoin

from bs4 import BeautifulSoup

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent / "out")
PAGES = OUT / "pages"
COMPANY = re.compile(r"\b(inc|ltd|limited|corp|properties|property|management|housing|rentals?|homes|realty|"
                     r"group|co-?op|developments?|patry|panadew|calden|frontenac|axon|limestone|williamsville)\b", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def money(s):
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", s or "")
    return float(m.group(1).replace(",", "")) if m else None


def num(s):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(s or ""))
    return float(m.group(0).replace(",", "")) if m else None


def clean_num(x):
    return int(x) if isinstance(x, float) and x.is_integer() else x


def soup(path):
    return BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")


def lines(path):
    s = soup(path)
    for t in s(["script", "style", "noscript", "svg"]):
        t.decompose()
    return [l.strip() for l in s.get_text("\n").split("\n") if l.strip()]


def files(source, suffix=None):
    d = PAGES / source
    return sorted(p for p in d.glob("*") if suffix is None or p.name.endswith(suffix)) if d.exists() else []


def json_body(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:  # page saved by the browser's JSON viewer
        return json.loads(BeautifulSoup(text, "lxml").get_text())


def L(key, address="", unit="", beds=None, baths=None, rent=None, basis="unit", available="",
      status="listed", url="", **extra):
    rec = dict(key=key, address=address, unit=unit, beds=clean_num(beds), baths=clean_num(baths),
               rent=clean_num(rent), basis=basis, available=available, status=status, url=url)
    rec.update({k: v for k, v in extra.items() if v not in (None, "", [])})
    return rec


# ---------------------------------------------------------------- per source

def amberpeak():
    best = None
    for p in files("amberpeak", ".json"):
        try:
            d = json_body(p)
        except ValueError:
            continue
        units = d.get("data") if isinstance(d, dict) else None
        if isinstance(units, list) and (best is None or len(units) > len(best)):
            best = units
    out = []
    for u in best or []:
        if not u.get("listed"):
            continue
        c = u.get("coordinates") or {}
        out.append(L(f"amberpeak|{u['id']}", u.get("address", ""), str(u.get("unitNumber") or ""),
                     u.get("bedrooms"), u.get("bathrooms"), u.get("price"), "unit",
                     str(u.get("availableDate") or "")[:10], "listed", "",
                     property=u.get("propertyName"), lat=c.get("lat"), lng=c.get("lng"),
                     sqft=u.get("netLeasableArea"), furnished=u.get("furnished"),
                     photos=(u.get("images") or [])[:8]))
    return out, {"listed": len(out), "portfolio_units": len(best or [])}


def axon():
    out, seen = [], set()
    for p in files("axon", ".html"):
        s = soup(p)
        for a in s.find_all("a", href=True):
            m = re.search(r"/residential-rentals/(?!cities/)([^/?#]+)/?$", a["href"])
            if not m or m.group(1) in seen:
                continue
            card = a
            while card.parent is not None and "rent from" not in card.get_text(" ").lower():
                card = card.parent
            if card.parent is None or len({x["href"] for x in card.find_all("a", href=re.compile(r"/residential-rentals/(?!cities/)"))}) > 2:
                continue
            seen.add(m.group(1))
            ls = [l.strip() for l in card.get_text("\n").split("\n") if l.strip()]
            name = ls[0] if ls else ""
            address = next((l for l in ls if re.search(r",\s*Kingston", l)), "")
            beds = []
            for i, l in enumerate(ls):
                if l.lower().startswith("bedroom") and i > 0:
                    beds = [int(x) for x in re.findall(r"\d+", ls[i - 1])]
            rent = next((money(ls[i - 1]) for i, l in enumerate(ls) if l.lower() == "rent from" and i > 0), None)
            img = card.find("img")
            out.append(L(f"axon|{m.group(1)}", address, "", beds, None, rent, "unit-from", "", "listed",
                         "https://www.axonproperties.ca/residential-rentals/" + m.group(1), name=name,
                         student=True if "student" in name.lower() else None,
                         photos=[img.get("src")] if img is not None and img.get("src") else None))
    return out, {}


def queens_als():
    rows, shown = {}, None
    for p in files("queens_als"):
        try:
            arr = json_body(p)
        except ValueError:
            continue
        if not isinstance(arr, list) or not arr:
            continue
        for x in arr[1:]:
            m = re.search(r"of\s+(\d+)\s*$", str(x))
            if m and "Showing" in str(x):
                shown = int(m.group(1))
        s = BeautifulSoup(f"<table>{arr[0]}</table>", "lxml")
        for tr in s.find_all("tr", attrs={"data-id": True}):
            tds = tr.find_all("td")
            if len(tds) < 9:
                continue
            t = [td.get_text(" ", strip=True) for td in tds]
            who = t[8]
            img = tds[0].find("a", href=True)
            rooms = num(t[4])
            rows[tr["data-id"]] = L(
                f"queens_als|{tr['data-id']}", t[1], "", rooms, None, money(t[7]), "as listed", t[5], "listed",
                f"https://listingservice.housing.queensu.ca/index.php/public/detail/{tr['data-id']}",
                type=t[2], lease_type=t[3], rooms=clean_num(rooms),
                landlord=who if COMPANY.search(who) else "private",
                photos=[img["href"]] if img else None)
    out = list(rows.values())
    return out, {"shown_total": shown, "incomplete": bool(shown and len(out) < shown)}


def casa():
    out = []
    for p in files("casa", ".html"):
        ls = lines(p)
        s = soup(p)
        for i, l in enumerate(ls):
            if l not in ("Available", "Just Leased", "Leased") or i + 6 >= len(ls):
                continue
            addr, bedl, bathl = ls[i + 1], ls[i + 2], ls[i + 4]
            if not re.search(r"\bbed\b", bedl) or "bath" not in bathl:
                continue
            rent = money(ls[i + 5])
            a = s.find(string=re.compile(re.escape(addr)))
            link = a.find_parent("a", href=True) if a else None
            out.append(L(f"casa|{norm(addr)}", addr, "", num(bedl), num(bathl), rent, "bed", "2027-28",
                         "listed" if l == "Available" else "leased",
                         urljoin("https://livecasa.ca/", link["href"]) if link else "", status_text=l, den=True if "den" in bedl else None))
    return out, {}


def panadew():
    out = []
    for p in files("panadew", ".html"):
        for el in soup(p).select(".featured-listing"):
            txt = re.sub(r"\s+", " ", el.get_text(" ")).strip()
            if "parking" in txt[:60].lower():
                continue
            m = re.search(r"/rentals/(\d+)", el.get("href", ""))
            if not m:
                continue
            addr = re.search(r"Address:\s*(.+?)\s+(?:Rent|Available):", txt)
            rtxt = re.search(r"Rent:\s*(.+?)\s+Available:", txt)
            avail = re.search(r"Available:\s*((?:[A-Z][a-z]+\.? \d{1,2}(?:st|nd|rd|th)?,? \d{4})|Now|Immediately)", txt)
            rent_text = rtxt.group(1) if rtxt else ""
            img = el.find("img")
            out.append(L(f"panadew|{m.group(1)}", addr.group(1) if addr else txt[:60], "",
                         num(el.get("data-bedrooms")), num(el.get("data-bathrooms")), num(el.get("data-rent")),
                         "bed" if re.search(r"per (room|bed)|/room|/bed", rent_text, re.I) else "unit",
                         avail.group(1) if avail else "", "listed",
                         "https://panadew.managebuilding.com/Resident/public/rentals/" + m.group(1),
                         rent_text=rent_text, photos=[img.get("src")] if img is not None and img.get("src") else None))
    return out, {}


def homestead():
    out, promos, seen = [], [], set()
    for p in files("homestead", ".html"):
        slug = re.search(r"residential-([a-z0-9-]+-kingston)", p.name)
        slug = slug.group(1) if slug else p.stem
        address = " ".join(w.capitalize() for w in slug.replace("-kingston", "").split("-"))
        ls = lines(p)
        try:
            start = next(i for i, l in enumerate(ls) if "CURRENT SUITE AVAILABILITY" in l.upper())
        except StopIteration:
            continue
        for i in range(start, len(ls) - 2):
            m = re.match(r"^(Bachelor|Studio|(\d) Bedroom(?: \+ Den)?)$", ls[i])
            if not m or not (ls[i + 1].startswith("Starting") or ls[i + 1] == "N/A"):
                continue
            beds = int(m.group(2)) if m.group(2) else 0
            sqft = next((num(x) for x in ls[i + 3:i + 15] if x.startswith("Sqft")), None)
            avail = ls[i + 2]
            key = f"homestead|{slug}-{beds}" + ("d" if "Den" in ls[i] else "")
            if key in seen:      # the same building can be captured twice (listed URL + followed link)
                continue
            seen.add(key)
            out.append(L(key, address, "", beds, None, money(ls[i + 1]), "unit-from", "",
                         "available" if avail.lower() == "available" else "unavailable",
                         "https://www.homestead.ca/residential/" + slug, sqft=sqft, suite=ls[i]))
        promos += [f"{address}: {l}" for l in ls if len(l) < 160 and not l.startswith("*")
                   and re.search(r"\bmonths? free\b|\$\d[\d,]* off\b|\d+% off\b|first month", l, re.I)][:2]
    return out, {"promo": "; ".join(promos)[:600]}


def frontenac_pm():
    out = {}
    for p in files("frontenac_pm", ".html"):
        student = "student" in p.name
        for a in soup(p).find_all("a", href=True):
            box = a.select_one(".listing-container")
            if box is None:
                continue
            slug = a["href"].strip("/").split("/")[-1]
            title = box.select_one(".title")
            title = title.get_text(" ", strip=True) if title else slug
            labels = [x.get_text(" ", strip=True) for x in box.select(".labela")]
            bed = next((num(x) for x in labels if "Bed" in x), None)
            bath = next((num(x) for x in labels if "Bath" in x), None)
            price = box.select_one(".price-box")
            rib = box.select_one(".ribbon")
            rib_text = rib.get_text(" ", strip=True) if rib else ""
            rented = "Rented" in rib_text or (rib is not None and "Rented" in rib.get("class", []))
            img = box.select_one(".image")
            bg = re.search(r'url\("?([^")]+)', img.get("style", "")) if img else None
            address = re.split(r"\s+\(|\s+-\s+", title)[0].strip()
            rec = out.get(slug) or L(
                f"frontenac_pm|{norm(slug)}", address, "", bed, bath, money(price.get_text()) if price else None,
                "unit", "" if rented else rib_text, "rented" if rented else "listed",
                "https://www.frontenacproperty.com/" + slug, title=title, photos=[htmllib.unescape(bg.group(1))] if bg else None)
            if student:
                rec["student"] = True
            out[slug] = rec
    return list(out.values()), {}


def williamsville():
    out = []
    statuses = ("New Build", "Now Leasing", "Fully Leased")
    for p in files("williamsville", ".html"):
        ls = lines(p)
        s = soup(p)
        for i, l in enumerate(ls):
            if not re.search(r"Bedrooms?$", l) or i == 0 or not re.match(r"^\d", ls[i - 1]):
                continue
            addr = ls[i - 1]
            prev = [x for x in ls[max(0, i - 3):i - 1] if x in statuses or x.startswith("Leasing for")]
            status = next((x for x in prev if x != "New Build"), "unstated")
            window = ls[i + 1:i + 8]
            rent = None
            if "From $" in window:
                j = window.index("From $")
                rent = num(window[j + 1]) if j + 1 < len(window) else None
            beds = re.findall(r"\d+", l)
            link = None
            node = s.find(string=re.compile(r"^\s*" + re.escape(addr) + r"\s*$"))
            for _ in range(6):
                node = node.parent if node is not None else None
                if node is None:
                    break
                view = [a for a in node.find_all("a", href=True) if a.get_text(strip=True) == "View"]
                if view:
                    link = view[0]
                    break
            out.append(L(f"williamsville|{norm(addr)}", addr, "", int(beds[0]) if beds else (0 if "Bachelor" in l else None),
                         None, rent, "bed-from", status.replace("Leasing for ", "") if status.startswith("Leasing for") else "",
                         status, urljoin("https://www.williamsvilleproperties.com/", link["href"]) if link else "", bed_range=l.replace(" Bedrooms", "").replace(" Bedroom", ""),
                         new_build=True if "New Build" in prev else None))
    return out, {}


def kshc():
    out, year, premium = [], None, None
    opts = [("12 Months", "12month", 12), ("8 Months", "8month", 8), ("4 Months", "4monthfall", 4),
            ("4 Months", "4monthwinter", 4), ("Members Summer", "memberssummer", 4),
            ("Non-Member Summer Only", "nonmembersummer", 4)]
    for p in files("kshc", ".html"):
        ls = lines(p)
        year = next((re.search(r"\d{4}/\d{4}", l).group(0) for l in ls if re.search(r"Fee Listing \d{4}/\d{4}", l)), None)
        premium = next((l for l in ls if "premium" in l.lower()), None)
        used = set()
        for label, key, months in opts:
            i = next((i for i, l in enumerate(ls) if l == label and i not in used), None)
            if i is None or i + 2 >= len(ls):
                continue
            used.add(i)
            dates, price = ls[i + 1], ls[i + 2]
            amt = money(price)
            if amt is None:
                continue
            monthly = "/month" in price
            out.append(L(f"kshc|{key}", "", "", 1, None, amt if monthly else round(amt / months, 2), "bed", dates,
                         "listed", "", lease_option=key, months=months, total=None if monthly else amt,
                         academic_year=year))
    return out, {"academic_year": year, "building_premium": premium}


def mackinnondev():
    out = {}
    home = next(iter(files("mackinnondev", "mackinnondev-ca.html")), None)
    if home is None:
        return [], {}
    s = soup(home)
    hrefs = {norm(re.sub(r"\.html$", "", a["href"].split("/")[-1])): a["href"]
             for a in s.find_all("a", href=True) if a["href"].endswith(".html")}
    ls = lines(home)
    status_words = re.compile(r"^(Available.*|Pending|Leased|Coming soon)$")
    for i, l in enumerate(ls):
        m = re.match(r"^(\d+) bedrooms?$", l)
        if not m or i < 2:
            continue
        name = ls[i - 1]
        j = i - 2
        while j >= 0 and not status_words.match(ls[j]) and i - j < 4:
            j -= 1
        status = ls[j] if j >= 0 and status_words.match(ls[j]) else ""
        href = hrefs.get(norm(name.replace(" 1/2", "-5")), "")
        out[norm(name)] = L(f"mackinnondev|{norm(name)}", name, "", int(m.group(1)), None, None, "unit",
                            status if status.startswith("Available") else "",
                            status or "unstated", ("https://mackinnondev.ca" + href) if href.startswith("/") else href)
    # unit pages: rent and baths
    for p in files("mackinnondev", ".html"):
        if p.name == "mackinnondev-ca.html":
            continue
        text = " ".join(lines(p))
        total = re.search(r"\$([\d,]+)\s*/\s*month total", text)
        per_bed = re.search(r"\$([\d,]+)\s*/\s*bed", text)
        for rec in out.values():
            stem = re.sub(r"(html)+$", "", norm(p.name.replace("mackinnondev-ca-", "")))
            if rec["url"] and re.sub(r"html$", "", norm(rec["url"].split("/")[-1])) == stem:
                beds = rec["beds"] or 0
                rec["rent"] = clean_num(float(total.group(1).replace(",", ""))) if total else (
                    clean_num(float(per_bed.group(1).replace(",", "")) * beds) if per_bed and beds else None)
                if per_bed:
                    rec["rent_text"] = f"${per_bed.group(1)} / bed / month"
                b = re.search(r"(\d+(?:\.\d)?)\s*(?:bath|Bath)", text)
                if b:
                    rec["baths"] = clean_num(float(b.group(1)))
                sq = re.search(r"([\d,]{3,6})\s*sq\s*ft", text)
                if sq:
                    rec["sqft"] = clean_num(float(sq.group(1).replace(",", "")))
    return list(out.values()), {}


def limestone():
    out = {}
    for p in files("limestone", ".html"):
        for a in soup(p).find_all("a", href=True):
            m = re.search(r"/property/([^/?#]+)/?$", a["href"])
            if not m or a.get_text(strip=True) != "Details" or m.group(1) in out:
                continue
            card = a
            while card.parent is not None and "$" not in card.get_text():
                card = card.parent
            ls = [l.strip() for l in card.get_text("\n").split("\n") if l.strip()]
            if "$" not in ls:
                continue
            i = ls.index("$")
            f = ls[i + 1:i + 9]
            if len(f) < 8 or f[1] != "Kingston":
                continue
            img = card.find("img")
            out[m.group(1)] = L(f"limestone|{norm(m.group(1))}", f[3], "", num(f[6]), num(f[7]), num(f[0]), "unit",
                                ls[i - 1] if i > 0 else "", "listed", urljoin("https://limestonepropertymanagement.ca/", a["href"]),
                                category=f[2], title=f[5], student=True if f[2] == "Students" else None,
                                photos=[img.get("src")] if img is not None and img.get("src") else None)
    return list(out.values()), {}


def floorplans(source, address):
    out, promo = {}, []
    for p in files(source, ".html"):
        ls = lines(p)
        for i, l in enumerate(ls[:-2]):
            bb = re.match(r"^(?:(\d+) Bed \| (\d+(?:\.\d)?) Bath|Studio)$", ls[i + 1]) if i + 1 < len(ls) else None
            if not bb or not ls[i + 2].startswith("Starting at") or norm(l) in out:
                continue
            sq = ls[i + 3] if i + 3 < len(ls) and "Sq. Ft" in ls[i + 3] else ""
            status = ls[i - 1] if i > 0 and ls[i - 1].isupper() else ""
            out[norm(l)] = L(f"{source}|{norm(l)}", address, l, int(bb.group(1)) if bb.group(1) else 0,
                             num(bb.group(2)) if bb.group(2) else None, money(ls[i + 2]), "bed",
                             re.search(r"20\d\d", status).group(0) if re.search(r"20\d\d", status) else "",
                             "listed", "", rent_text=ls[i + 2], sqft=num(sq) if sq else None, status_text=status)
        promo += [l for l in ls if len(l) < 160 and re.search(r"special|promo|\bfree\b|open house|\$\d[\d,]* off|% off|bonus", l, re.I)]
    seen = []
    for x in promo:
        if x not in seen:
            seen.append(x)
    return list(out.values()), {"promo": " | ".join(seen[:4])}


def geo_central():
    return floorplans("geo_central", "575 Princess St")


def unity_place():
    return floorplans("unity_place", "495 Princess St, Kingston, ON, Canada, K7L 0G4")


def unity_point():
    return floorplans("unity_point", "333 University Avenue, Kingston, ON, Canada, K7L 0G3")


MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def condo_history(source, address):
    """Rental history of one condo building (condos.ca "Rented" listing history). Each entry is a unit that was
    listed for rent (list price and date) and rented in the month shown. Recorded as supply and leasing pace
    for 1-3 bed units, not as comparables."""
    out, months, seen = [], [], set()
    for p in files(source, ".html"):
        if "pricehistory" not in p.name:
            continue
        ls = lines(p)
        try:
            i = ls.index("Listing History")
        except ValueError:
            continue
        month = None
        while i < len(ls):
            l = ls[i]
            m = re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (20\d\d)$", l)
            if m:
                month = f"{m.group(2)}-{MONTHS[m.group(1)]:02d}"
                nl = next((num(x) for x in ls[i + 1:i + 3] if "Listed" in x), None)
                nr = next((num(x) for x in ls[i + 1:i + 5] if "Rented" in x), None)
                months.append(dict(month=month, listed=nl, rented=nr))
            elif l == "Listed for" and month and i + 3 < len(ls):
                rent, when = money(ls[i + 1]), ls[i + 3]
                back = ls[max(0, i - 14):i]
                def before(tag):
                    j = max((k for k, x in enumerate(back) if x == tag), default=None)
                    return back[j - 1] if j else None
                beds_t, baths_t, sq = before("beds"), before("bath"), before("sqft")
                beds = 0 if beds_t in ("Studio", "0") else num((beds_t or "").split("+")[0])
                key = f"{source}|{month}|{when}|{rent}|{beds_t}|{baths_t}|{sq}"
                if rent and key not in seen:
                    seen.add(key)
                    try:
                        listed_on = datetime.strptime(when, "%b %d, %Y").strftime("%Y-%m-%d")
                    except Exception:
                        listed_on = ""
                    out.append(L(f"{source}|{listed_on}|{int(rent)}|{beds_t}", address, "", beds, num(baths_t), rent, "unit", "",
                                 "rented", "https://condos.ca/addresses/" + address.lower().replace(" ", "-") + "-kingston",
                                 rented_month=month, listed_on=listed_on, sqft_range=sq, den="+" in str(beds_t or ""), type="condo"))
                i += 3
            i += 1
    return out, {"months": months[:24], "kind": "rental history (rented units)"}


def sage():
    return condo_history("sage", "652 Princess Street")


def crown():
    return condo_history("crown", "223 Princess Street")


PARSERS = {"amberpeak": amberpeak, "axon": axon, "queens_als": queens_als, "casa": casa, "panadew": panadew,
           "homestead": homestead, "frontenac_pm": frontenac_pm, "williamsville": williamsville, "kshc": kshc,
           "mackinnondev": mackinnondev, "limestone": limestone, "geo_central": geo_central,
           "unity_place": unity_place, "unity_point": unity_point, "sage": sage, "crown": crown}


def main():
    status = json.loads((OUT / "status.json").read_text()) if (OUT / "status.json").exists() else {}
    date = status.get("date")
    (OUT / "listings").mkdir(exist_ok=True)
    summary = {}
    for name in sorted(p.name for p in PAGES.iterdir() if p.is_dir()) if PAGES.exists() else []:
        fn = PARSERS.get(name)
        if fn is None:
            continue
        try:
            listings, extra = fn()
            err = None
        except Exception as e:  # one broken site must not stop the others
            listings, extra, err = [], {}, f"{type(e).__name__}: {e}"[:300]
        doc = {"source": name, "date": date, "count": len(listings),
               "incomplete": bool(extra.pop("incomplete", False)) or not listings or err is not None,
               **{k: v for k, v in extra.items() if v not in (None, "")}, "listings": listings}
        if err:
            doc["note"] = "parse error: " + err
        elif not listings:
            doc["note"] = "no listings found on the saved page(s)"
        (OUT / "listings" / f"{name}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False))
        summary[name] = doc["count"]
        print(f"{name:14s} {doc['count']:4d}{'  INCOMPLETE ' + doc.get('note', '') if doc['incomplete'] else ''}")
    status["parsed"] = summary
    (OUT / "status.json").write_text(json.dumps(status, indent=1))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Živý test klienta proti webmail.zcu.cz. Vypisuje jen stavy a počty, ne heslo ani obsah zpráv.

Spuštění: python3 zivy_test.py (stačí Python 3.9 bez instalace). Co změní, vrátí zpět; zkušební maily přesune do koše.
"""
import getpass
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from zcu_mail_mcp.eas import Client  # noqa: E402

MARK = "[zcu-mail-mcp test]"


def step(name, fn):
    try:
        print(f"OK     {name}: {fn()}")
    except Exception as e:  # test má doběhnout celý, i když jeden krok selže
        print(f"CHYBA  {name}: {type(e).__name__}: {e}")


def main():
    user = input("Login ZČU (bez @zcu.cz): ").strip()
    pw = getpass.getpass("Heslo (nezobrazuje se): ")
    c = Client(user, pw)
    me = c.addresses()[0]  # adresa, ze které SOGo odesílá
    print(f"Adresy účtu podle SOGo: {', '.join(c.addresses())}")
    s = {}

    def inbox(days=7):
        return c.list_messages("inbox", days, 50, False)["messages"]

    def current(mid, field):
        return next(m for m in inbox() if m["id"] == mid)[field]

    def folders():
        found = {k: c.folder(k)["type"] for k in ("inbox", "drafts", "sent", "trash")}
        return f"{len(c.folders())} složek, typy {found}"

    def listing():
        s["msgs"] = inbox()
        assert s["msgs"], "v doručené poště za 7 dní nic není"
        m = s["msgs"][0]
        filled = [k for k, v in m.items() if v not in ("", 0, False)]
        return f"{len(s['msgs'])} zpráv za 7 dní, vyplněno: {', '.join(filled)}; složka v id: {m['id'].rpartition('+')[0]}"

    def read_marks():
        unread = [m for m in s["msgs"] if not m["read"]]
        target = (unread or s["msgs"])[0]
        msg = c.read(target["id"], 5000)
        info = f"text {len(msg['body'])} znaků, příloh {len(msg['attachments'])}; "
        if not unread:
            return info + "žádná nepřečtená zpráva, vliv čtení na stav neověřen"
        if current(target["id"], "read"):
            c.mark(target["id"], read=False)
            return info + "čtení zprávu OZNAČÍ jako přečtenou (vráceno zpět)"
        return info + "čtení stav přečtení nemění"

    def toggle(field):
        def run():
            mid = s["msgs"][0]["id"]
            was = current(mid, field)
            c.mark(mid, **{field: not was})
            changed = current(mid, field)
            c.mark(mid, **{field: was})
            back = current(mid, field)
            assert changed == (not was) and back == was, f"{was} -> {changed} -> {back}"
            return f"{was} -> {changed} -> {back}"
        return run

    def search():
        m = s["msgs"][0]
        word = max(m["subject"].split(), key=len, default="")
        assert word, "nejnovější zpráva nemá předmět"
        everywhere = c.search(word, None, None, 10)
        in_inbox = c.search(word, "inbox", date.today() - timedelta(days=7), 10)
        s["found"] = everywhere["messages"]
        hit = any(x["id"] == m["id"] for x in everywhere["messages"] + in_inbox["messages"])
        return (f"všude {everywhere['total']}, v inboxu za 7 dní {in_inbox['total']}; "
                f"nejnovější zpráva {'nalezena se stejným id' if hit else 'NENALEZENA nebo jiné id'}")

    def read_found():
        assert s.get("found"), "hledání nic nevrátilo"
        x = s["found"][0]
        return f"text {len(c.read(x['id'], 1000)['body'])} znaků, složka {x['folder']}"

    def attachment():
        m = next((m for m in s["msgs"] if m["attachments"]), None)
        if not m:
            return "za 7 dní žádná zpráva s přílohou, přeskočeno"
        a = c.read(m["id"], 0)["attachments"][0]
        ctype, data = c.attachment(a["ref"])
        return f"{ctype}, {len(data)} B (server hlásil {a['size']} B)"

    def draft():
        mid = c.save_draft([me], f"{MARK} koncept", "Zkušební koncept: Příliš žluťoučký kůň.")
        seen = any(x["id"] == mid for x in c.list_messages("drafts", 1, 50, False)["messages"])
        return f"id {mid}, v Konceptech {'je' if seen else 'NENÍ vidět'}"

    def wait_inbox(needle, n):  # jen zprávy tohoto běhu: předmět obsahuje čas odeslání
        for _ in range(15):
            hits = [m for m in inbox(1) if needle in m["subject"]]
            if len(hits) >= n:
                return hits
            time.sleep(3)
        raise AssertionError(f"za 45 s dorazilo {len(hits)} z {n} zkušebních zpráv")

    def send():
        subject = f"{MARK} žluťoučký kůň {time.strftime('%H:%M:%S')}"
        c.send([me], subject, "Zkušební zpráva: Příliš žluťoučký kůň úpěl ďábelské ódy.")
        s["sent"] = wait_inbox(subject, 1)[0]
        in_sent = any(MARK in m["subject"] for m in c.list_messages("sent", 1, 50, False)["messages"])
        return f"dorazila, předmět s diakritikou {'sedí' if s['sent']['subject'] == subject else 'SE ZMĚNIL'}, " \
               f"kopie v Odeslané poště {'je' if in_sent else 'NENÍ'}"

    def reply():
        orig = c.read(s["sent"]["id"], 0)
        to, cc = c.reply_recipients(orig, True)
        c.reply(orig["id"], "Zkušební odpověď.", to, cc, "Re: " + orig["subject"])
        c.forward(orig["id"], [me], "Zkušební přeposlání.", "Fwd: " + orig["subject"])
        wait_inbox(orig["subject"], 3)  # původní, Re: a Fwd:
        return f"odpověď (komu {len(to)}, kopie {len(cc)}) i přeposlání dorazily"

    def cleanup():
        moved = []
        for f in ("inbox", "drafts", "sent"):
            for m in c.list_messages(f, 3, 50, False)["messages"]:  # i zprávy z dřívějšího nedokončeného běhu
                if MARK in m["subject"]:
                    moved.append(bool(c.move(m["id"], "trash")))
        return f"{len(moved)} zkušebních zpráv v koši, nové id vráceno u {sum(moved)}"

    print()
    step("složky", folders)
    step("seznam zpráv", listing)
    if s.get("msgs"):
        step("čtení zprávy", read_marks)
        step("přečteno/nepřečteno", toggle("read"))
        step("příznak", toggle("flagged"))
        step("hledání", search)
        step("čtení výsledku hledání", read_found)
        step("příloha", attachment)
    step("koncept", draft)
    if input("\nOdeslat 3 zkušební maily sám sobě (nový, odpověď, přeposlání)? [a/N]: ").strip().lower() == "a":
        step("odeslání", send)
        if s.get("sent"):
            step("odpověď a přeposlání", reply)
    step("úklid do koše", cleanup)
    print("\nHotovo. Heslo ani obsah zpráv ve výpisu nejsou.")


if __name__ == "__main__":
    main()

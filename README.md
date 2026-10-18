# zcu-mail-mcp

MCP server k univerzitní poště ZČU (webmail.zcu.cz). Napsaný pro Grok Bot, funguje s každým MCP klientem, který
spouští servery přes stdio. Se schránkou mluví přes Exchange ActiveSync na `https://webmail.zcu.cz/Microsoft-Server-ActiveSync`,
takže stačí obyčejný webový provoz (HTTPS), IMAP ani SMTP nepotřebuje.

## Nástroje

| Nástroj | Co dělá | Potvrzení |
|---|---|---|
| `list_folders` | složky schránky | – |
| `list_messages` | nejnovější zprávy ve složce (1–30 dní) | – |
| `search_messages` | hledání v předmětu a odesílateli | – |
| `read_message` | celá zpráva s přílohami | – |
| `get_attachment` | uloží přílohu do `~/zcu-mail-prilohy`, text a obrázky vrátí i přímo | – |
| `save_draft` | uloží koncept do Konceptů | – |
| `mark_message` | přečteno / nepřečteno, příznak | – |
| `send_message` | odešle nový e-mail | ano |
| `reply_message` | odpoví (i všem) | ano |
| `forward_message` | přepošle i s přílohami | ano |
| `move_message` | přesune, smazání = přesun do koše | ano |

Odeslání, odpověď, přeposlání a přesun se provedou až po souhlasu uživatele. Jsou na to dvě cesty a použije se jen jedna:

- Klient v úvodním handshaku ohlásí elicitaci (`capabilities.elicitation`). Server během volání pošle
  `elicitation/create` s formulářem a zaškrtávacím polem „Ano, provést“ (`provest`). Akce proběhne jen když
  klient vrátí `accept` a `provest: true`. `decline`, `cancel` i přijetí s nezaškrtnutým polem vrátí
  `zrušeno uživatelem, nic se neprovedlo` a nic se neprovede. Tokenová cesta se v tomhle případě vůbec nespustí.
- Klient elicitaci neohlašuje. Nástroj nic neprovede a vrátí náhled s `confirmation_token`, platným jen pro
  přesně ty parametry a jen do restartu serveru.

Grok Bot elicitaci ohlásí (jinak by server vrátil náhled s tokenem, ne tuhle větu), dialog uživateli ale neukáže
a `elicitation/create` uzavře sám. Server nerozliší `decline`, `cancel` ani `accept` s nezaškrtnutým `provest`:
všechno je „zrušeno uživatelem, nic se neprovedlo“. Výzva v chatu se neobjeví, protože ji měl vykreslit klient
jako elicitaci. Souhlas, který uživatel dává zvlášť v chatu, se k serveru nedostane.

Kdo schvaluje akci už v klientovi, může tohle druhé potvrzení vypnout: `ZCU_SKIP_CONFIRMATION=1` (stejně platí
`true`, `yes` a `on`, bez ohledu na velikost písmen a okolní mezery). `send_message`, `reply_message`,
`forward_message` a `move_message` pak akci provedou při prvním volání. Parametr `confirmation_token` v nástroji
zůstává, starší klient ho může poslat a server ho ignoruje. Druhé volání se stejnými parametry odešle další kopii.
Bez proměnné, nebo s hodnotou `0`, `false`, `no`, `off` či prázdnou, se chování nemění.

Proměnná se čte při startu procesu. Po doplnění do konfigurace MCP klienta server restartuj. Instalace přes
`uvx --from git+...` si navíc pamatuje starý checkout: ať naběhne tahle verze, jednou spusť

```
uvx --refresh --reinstall-package zcu-mail-mcp --from git+https://github.com/VojtajSvin/zcu-mail-mcp zcu-mail-mcp
```

případně `uv cache clean zcu-mail-mcp`, a pak server v klientovi znovu. Bez obnovení cache dál běží starý kód, který proměnnou nezná.

## Nastavení v Grok Botu

- Příkaz: `uvx`
- Argumenty: `--from git+https://github.com/VojtajSvin/zcu-mail-mcp zcu-mail-mcp`
- Proměnné prostředí (skryté): `ZCU_USER` = login Orion (bez domény), `ZCU_PASSWORD` = heslo
- Volitelně `ZCU_SKIP_CONFIRMATION` = `1`, pokud se má odeslání, odpověď, přeposlání a přesun provést hned

Totéž jako konfigurace MCP klienta:

```json
{
  "mcpServers": {
    "zcu-mail": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/VojtajSvin/zcu-mail-mcp", "zcu-mail-mcp"],
      "env": {"ZCU_USER": "login", "ZCU_PASSWORD": "heslo"}
    }
  }
}
```

## Omezení

- Hledání umí jen předmět a odesílatele, ne text zprávy (tak hledá SOGo).
- Skrytou kopii (Bcc) SOGo přes ActiveSync nepošle.
- Seznam složek se načte jednou za běh; novou složku server uvidí po restartu.
- Odesílá se z hlavní adresy účtu v SOGo (u studentů `login@students.zcu.cz`).

## Testy

- `python test_offline.py` (s nainstalovaným balíčkem): nástroje, anotace a potvrzování přes stdio, bez sítě a hesla.
  Ověří i `ZCU_SKIP_CONFIRMATION`. Heslo ani login se nikam nevypisují.
- `python3 zivy_test.py`: proti skutečné schránce, stačí Python 3.9 bez instalace. Zeptá se na login a heslo,
  vypisuje jen stavy a počty, zkušební zprávy nakonec přesune do koše.

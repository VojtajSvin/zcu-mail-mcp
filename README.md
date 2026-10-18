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

Odeslání, odpověď, přeposlání a přesun se provedou až po souhlasu uživatele. Když klient umí elicitaci, zeptá se
sám. Jinak nástroj vrátí náhled s `confirmation_token`, platným jen pro přesně ty parametry a jen do restartu
serveru.

## Nastavení v Grok Botu

- Příkaz: `uvx`
- Argumenty: `--from git+https://github.com/VojtajSvin/zcu-mail-mcp zcu-mail-mcp`
- Proměnné prostředí (skryté): `ZCU_USER` = login Orion (bez domény), `ZCU_PASSWORD` = heslo

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
- `python3 zivy_test.py`: proti skutečné schránce, stačí Python 3.9 bez instalace. Zeptá se na login a heslo,
  vypisuje jen stavy a počty, zkušební zprávy nakonec přesune do koše.

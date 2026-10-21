"""Klient Exchange ActiveSync (EAS 14.1) pro SOGo na webmail.zcu.cz.

Jen standardní knihovna, běží i na Pythonu 3.9, aby šel živý test spustit bez instalace.
Chování SOGo (které prvky čte, co vrací) je ověřené proti jeho zdrojům: SOGo/ActiveSync/*.m.
"""
from __future__ import annotations

import base64
import email
import email.policy
import html
import mimetypes
import re
import stat
import uuid
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid
from pathlib import Path

URL = "https://webmail.zcu.cz/Microsoft-Server-ActiveSync"
DEVICE_ID, DEVICE_TYPE = "ZcuMailMcp01", "ZcuMailMcp"

# MS-ASWBXML: kódové stránky a tokeny tagů, ověřeno proti Z-Push wbxmldefs.php. Jen tagy, které tu používáme.
PAGES = {0: "AirSync", 2: "Email", 5: "Move", 7: "FolderHierarchy", 15: "Search", 17: "AirSyncBase",
         18: "Settings", 20: "ItemOperations", 21: "ComposeMail", 22: "Email2"}
TAGS = {
    0: {0x05: "Sync", 0x06: "Responses", 0x07: "Add", 0x08: "Change", 0x09: "Delete", 0x0A: "Fetch",
        0x0B: "SyncKey", 0x0C: "ClientId", 0x0D: "ServerId", 0x0E: "Status", 0x0F: "Collection", 0x10: "Class",
        0x12: "CollectionId", 0x13: "GetChanges", 0x14: "MoreAvailable", 0x15: "WindowSize", 0x16: "Commands",
        0x17: "Options", 0x18: "FilterType", 0x1C: "Collections", 0x1D: "ApplicationData",
        0x1E: "DeletesAsMoves", 0x22: "MIMESupport", 0x23: "MIMETruncation"},
    2: {0x05: "Attachment", 0x06: "Attachments", 0x0C: "Body", 0x0F: "DateReceived", 0x11: "DisplayTo",
        0x12: "Importance", 0x13: "MessageClass", 0x14: "Subject", 0x15: "Read", 0x16: "To", 0x17: "Cc",
        0x18: "From", 0x19: "ReplyTo", 0x1B: "Categories", 0x1C: "Category", 0x35: "ThreadTopic", 0x3A: "Flag",
        0x3B: "FlagStatus", 0x3D: "FlagType"},
    5: {0x05: "MoveItems", 0x06: "Move", 0x07: "SrcMsgId", 0x08: "SrcFldId", 0x09: "DstFldId", 0x0A: "Response",
        0x0B: "Status", 0x0C: "DstMsgId"},
    7: {0x07: "DisplayName", 0x08: "ServerId", 0x09: "ParentId", 0x0A: "Type", 0x0C: "Status", 0x0E: "Changes",
        0x0F: "Add", 0x10: "Delete", 0x11: "Update", 0x12: "SyncKey", 0x16: "FolderSync", 0x17: "Count"},
    15: {0x05: "Search", 0x07: "Store", 0x08: "Name", 0x09: "Query", 0x0A: "Options", 0x0B: "Range",
         0x0C: "Status", 0x0D: "Response", 0x0E: "Result", 0x0F: "Properties", 0x10: "Total", 0x12: "Value",
         0x13: "And", 0x15: "FreeText", 0x17: "DeepTraversal", 0x18: "LongId", 0x19: "RebuildResults",
         0x1A: "LessThan", 0x1B: "GreaterThan"},
    17: {0x05: "BodyPreference", 0x06: "Type", 0x07: "TruncationSize", 0x0A: "Body", 0x0B: "Data",
         0x0C: "EstimatedDataSize", 0x0D: "Truncated", 0x0E: "Attachments", 0x0F: "Attachment",
         0x10: "DisplayName", 0x11: "FileReference", 0x12: "Method", 0x13: "ContentId", 0x15: "IsInline",
         0x16: "NativeBodyType", 0x17: "ContentType", 0x18: "Preview"},
    18: {0x05: "Settings", 0x06: "Status", 0x07: "Get", 0x1D: "UserInformation", 0x1E: "EmailAddresses",
         0x1F: "SmtpAddress", 0x23: "PrimarySmtpAddress", 0x24: "Accounts", 0x25: "Account"},
    20: {0x05: "ItemOperations", 0x06: "Fetch", 0x07: "Store", 0x08: "Options", 0x09: "Range", 0x0A: "Total",
         0x0B: "Properties", 0x0C: "Data", 0x0D: "Status", 0x0E: "Response"},
    21: {0x05: "SendMail", 0x06: "SmartForward", 0x07: "SmartReply", 0x08: "SaveInSentItems", 0x09: "ReplaceMime",
         0x0B: "Source", 0x0C: "FolderId", 0x0D: "ItemId", 0x0E: "LongId", 0x10: "MIME", 0x11: "ClientId",
         0x12: "Status"},
    22: {0x09: "ConversationId", 0x0B: "LastVerbExecuted", 0x0E: "Sender", 0x15: "IsDraft", 0x16: "Bcc",
         0x17: "Send"},
}
PAGE_OF = {name: page for page, name in PAGES.items()}
TOKEN = {(page, name): tok for page, tags in TAGS.items() for tok, name in tags.items()}

# Typy složek z FolderSync a slova, kterými je jde zadat místo názvu
FOLDER_TYPES = {"inbox": 2, "doručená pošta": 2, "drafts": 3, "koncepty": 3, "trash": 4, "koš": 4,
                "sent": 5, "odeslaná pošta": 5, "odeslané": 5}
# Sync FilterType: počet dní -> kód EAS
FILTER_TYPE = {1: "1", 3: "2", 7: "3", 14: "4", 30: "5"}

# Součet příloh jedné zprávy. Větší MIME už SOGo ani schránka nemusí přijmout.
ATTACHMENT_LIMIT = 25 * 1024 * 1024

# Na některých instalacích mimetypes Office a OpenDocument nezná.
for _ext, _ctype in {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
}.items():
    if mimetypes.guess_type("soubor" + _ext)[0] != _ctype:
        mimetypes.add_type(_ctype, _ext)
del _ext, _ctype

HTTP_HINTS = {
    401: "Přihlášení odmítnuto: zkontroluj ZCU_USER (login Orion, bez domény) a ZCU_PASSWORD.",
    403: "Server ActiveSync pro tenhle účet zakázal.",
    449: "Server chce Provision (schválení zařízení), tenhle klient ho neumí.",
    500: "SOGo vrátil chybu 500 (často zpráva nebo složka už neexistuje, nebo neplatný dotaz).",
}


try:  # MCP server pošle modelu text jen u ToolError, jiné výjimky skryje
    from mcp.server.mcpserver.exceptions import ToolError as _ErrorBase
except ImportError:  # živý test běží bez balíčku mcp
    _ErrorBase = Exception


class EasError(_ErrorBase):
    pass


def _mbint(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.insert(0, 0x80 | (n & 0x7F))
        n >>= 7
    return bytes(out)


def encode(root: list) -> bytes:
    """Prvek je [jméno, *děti]; jméno může nést stránku „Stránka:Tag“, děti ji dědí. Dítě je str, bytes nebo prvek."""
    out = bytearray(b"\x03\x01\x6a\x00")  # WBXML 1.3, public id 1, UTF-8, prázdná tabulka řetězců
    page = 0

    def put(el: list, ns: str) -> None:
        nonlocal page
        name, *kids = el
        if ":" in name:
            ns, name = name.split(":")
        p = PAGE_OF[ns]
        if p != page:
            out.extend((0, p))
            page = p
        tok = TOKEN[(p, name)]
        if not kids:
            out.append(tok)
            return
        out.append(tok | 0x40)
        for k in kids:
            if isinstance(k, list):
                put(k, ns)
            elif isinstance(k, bytes):
                out.append(0xC3)
                out.extend(_mbint(len(k)) + k)
            else:
                out.append(0x03)
                out.extend(str(k).encode() + b"\x00")
        out.append(0x01)

    put(root, "AirSync")
    return bytes(out)


def decode(data: bytes) -> list:
    """Dekóduje WBXML na seznam kořenových prvků [jméno, *děti]; jména jsou bez stránky."""
    pos = 1

    def mbint() -> int:
        nonlocal pos
        v = 0
        while True:
            b = data[pos]
            pos += 1
            v = (v << 7) | (b & 0x7F)
            if not b & 0x80:
                return v

    mbint(), mbint()  # public id, charset (EAS posílá vždy UTF-8)
    n = mbint()  # délka tabulky řetězců
    pos += n
    page, root = 0, []
    stack = [root]
    while pos < len(data):
        b = data[pos]
        pos += 1
        if b == 0x00:
            page = data[pos]
            pos += 1
        elif b == 0x01:
            stack.pop()
        elif b == 0x03:
            end = data.index(0, pos)
            stack[-1].append(data[pos:end].decode())
            pos = end + 1
        elif b == 0xC3:
            n = mbint()
            stack[-1].append(data[pos:pos + n])
            pos += n
        else:
            tag = b & 0x3F
            el = [TAGS.get(page, {}).get(tag, f"{page}:{tag:#x}")]
            stack[-1].append(el)
            if b & 0x40:
                stack.append(el)
    return root


def find(el, name: str) -> list:
    return [c for c in (el or [])[1:] if isinstance(c, list) and c[0] == name]


def first(el, *path: str):
    for name in path:
        found = find(el, name)
        if not found:
            return None
        el = found[0]
    return el


def text(el, *path: str) -> str:
    el = first(el, *path)
    if not el or len(el) < 2:
        return ""
    v = el[1]
    return v.decode() if isinstance(v, bytes) else v if isinstance(v, str) else ""


# Self-check: FolderSync z ověřeného testu (probe 2026-10-18) a průchod přes stránky, text i OPAQUE
assert encode(["FolderHierarchy:FolderSync", ["SyncKey", "0"]]) == bytes([3, 1, 0x6A, 0, 0, 7, 0x56, 0x52, 3]) + b"0\x00" + bytes([1, 1])
_sample = ["AirSync:Sync", ["Collections", ["Collection", ["SyncKey", "7"], ["Options", ["AirSyncBase:BodyPreference",
           ["Type", "1"]], ["MIMETruncation", "1"]], ["ComposeMail:MIME", b"\x00\x01" * 100], ["GetChanges"]]]]
assert decode(encode(_sample)) == [["Sync", ["Collections", ["Collection", ["SyncKey", "7"], ["Options", ["BodyPreference",
           ["Type", "1"]], ["MIMETruncation", "1"]], ["MIME", b"\x00\x01" * 100], ["GetChanges"]]]]]


def split_id(message_id: str):
    folder_id, _, uid = message_id.rpartition("+")  # SOGo LongId: {složka}+{uid}, uid je číslo
    if not folder_id or not uid.isdigit():
        raise EasError(f"Neplatné message_id „{message_id}“. Id vrací list_messages a search_messages.")
    return folder_id, uid


def content_type(filename: str) -> str:
    ctype, _ = mimetypes.guess_type(filename)
    return (ctype or "application/octet-stream").split(";", 1)[0].strip()


def load_attachments(paths) -> list:
    """(jméno, content-type, obsah) pro každou absolutní cestu. Prázdný vstup vrátí []."""
    if not paths:
        return []
    pending, total = [], 0
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            raise EasError(f"Cesta „{raw}“ není absolutní. Zadej celou cestu k souboru na počítači, kde běží server.")
        try:
            info = path.stat()
        except FileNotFoundError:
            raise EasError(f"Soubor „{raw}“ neexistuje.") from None
        except OSError as e:
            raise EasError(f"Soubor „{raw}“ nejde přečíst: {e.strerror or e}.") from None
        if not stat.S_ISREG(info.st_mode):
            raise EasError(f"„{raw}“ není soubor.")
        name = path.name
        if name in ("", ".", "..") or any(c in name for c in "\r\n\x00"):
            raise EasError(f"Jméno souboru „{name}“ nejde použít jako přílohu.")
        total += info.st_size
        if total > ATTACHMENT_LIMIT:
            raise EasError(f"Přílohy mají dohromady {total} B, limit je {ATTACHMENT_LIMIT} B (25 MB).")
        pending.append((raw, path, name))
    out, total = [], 0
    for raw, path, name in pending:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise EasError(f"Soubor „{raw}“ neexistuje.") from None
        except OSError as e:
            raise EasError(f"Soubor „{raw}“ nejde přečíst: {e.strerror or e}.") from None
        total += len(data)
        if total > ATTACHMENT_LIMIT:
            raise EasError(f"Přílohy mají dohromady {total} B, limit je {ATTACHMENT_LIMIT} B (25 MB).")
        out.append((name, content_type(name), data))
    return out


def threading_headers(message_id: str, references: str = "") -> tuple:
    """In-Reply-To a References. Stejně jako SOGo při deseti a více id vyhodí druhé."""
    mid = " ".join((message_id or "").split())
    refs = (references or "").split()
    if not mid:
        return "", " ".join(refs)
    if len(refs) >= 10:
        del refs[1]
    refs.append(mid)
    return mid, " ".join(refs)


_TAG = re.compile(r"<[^>]+>")


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    return html.unescape(_TAG.sub("", text))


def _part_text(part) -> str:
    try:
        text = part.get_content()
    except (LookupError, UnicodeError, ValueError, TypeError):
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", "replace")
    return text if isinstance(text, str) else ""


def _message_text(msg) -> str:
    if msg.is_multipart():
        plain = html_part = ""
        for part in msg.walk():
            if part.is_multipart() or part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain" and not plain:
                plain = _part_text(part)
            elif ctype == "text/html" and not html_part:
                html_part = _part_text(part)
        return plain or _html_to_text(html_part)
    if msg.get_content_type() == "text/html":
        return _html_to_text(_part_text(msg))
    return _part_text(msg)


def parse_original(raw: bytes) -> dict:
    """Hlavičky a text původní zprávy, ze kterých se skládá odpověď."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    return {
        "message_id": " ".join((msg.get("Message-ID") or "").split()),
        "references": " ".join((msg.get("References") or "").split()),
        "from": " ".join((msg.get("From") or "").split()),
        "date": " ".join((msg.get("Date") or "").split()),
        "subject": " ".join((msg.get("Subject") or "").split()),
        "body": _message_text(msg).strip(),
    }


def quote_original(body: str, original: dict) -> str:
    """Text odpovědi a pod ním citace. Řádky původní zprávy začínají „>“."""
    who = original.get("from") or "odesílatel"
    when = original.get("date") or ""
    intro = " ".join(f"Dne {when} {who} napsal(a):".split())
    quoted = "\n".join(("> " + line) if line else ">" for line in (original.get("body") or "").splitlines())
    return f"{body.rstrip()}\n\n{intro}\n{quoted}\n"


def build_mime(to: list, subject: str, body: str, cc: list = (), attachments: list = (),
               sender: str = "", in_reply_to: str = "", references: str = "") -> bytes:
    """MIME jen v ASCII (hlavičky RFC 2047, tělo quoted-printable, přílohy base64).

    Jméno s diakritikou je v parametru filename* (RFC 2231 / RFC 5987). SOGo čte
    odesílané MIME jako UTF-8 řetězec, surové bajty by se rozbily.
    """
    msg = EmailMessage()
    if sender:
        msg["From"] = sender
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="zcu.cz")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body, cte="quoted-printable")
    for name, ctype, data in attachments:
        main, _, sub = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=main or "application", subtype=sub or "octet-stream", filename=name)
    raw = msg.as_bytes(policy=email.policy.SMTP)
    try:
        raw.decode("ascii")
    except UnicodeDecodeError:
        raise EasError("MIME zprávy není ASCII. SOGo by ho přečetl špatně.") from None
    return raw


assert build_mime(["Jan Novák <jan@zcu.cz>"], "Žluťoučký kůň", "Příliš úpěl ďábelské ódy.").decode("ascii")
_att = build_mime(["a@zcu.cz"], "A", "b", attachments=[(
    "žluťoučký.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK")])
assert b"filename*" in _att and b"utf-8''" in _att and "žluťoučký".encode() not in _att
del _att


def _node_bytes(el) -> bytes:
    if not el or len(el) < 2:
        return b""
    v = el[1]
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        return v.encode()
    return b""


def compose_request(cmd: str, mime: bytes, source: str = "", replace_mime: bool = False, client_id: str = "") -> list:
    """WBXML tělo SendMail / SmartReply / SmartForward. ReplaceMime jen když MIME už obsahuje citaci i vlákno."""
    req = [f"ComposeMail:{cmd}", ["ClientId", client_id or uuid.uuid4().hex]]
    if source:
        fid, uid = split_id(source)
        req.append(["Source", ["FolderId", fid], ["ItemId", uid]])
    if replace_mime:
        req.append(["ReplaceMime"])
    req += [["SaveInSentItems"], ["MIME", mime]]
    return req


def summary(folder_id: str, uid: str, props, preview: int = 300) -> dict:
    body = text(props, "Body", "Data").strip()
    return {
        "id": f"{folder_id}+{uid}",
        "from": text(props, "From"),
        "to": text(props, "To"),
        "cc": text(props, "Cc"),
        "subject": text(props, "Subject"),
        "date": text(props, "DateReceived"),
        "read": text(props, "Read") == "1",
        "flagged": text(props, "Flag", "FlagStatus") == "2",
        "attachments": len(find(first(props, "Attachments"), "Attachment")),
        "preview": " ".join(body[:preview].split()),
    }


class Client:
    def __init__(self, user: str, password: str):
        self.user = user
        self._auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self._folders = None
        self._addresses = None

    def call(self, cmd: str, body: list):
        query = urllib.parse.urlencode({"Cmd": cmd, "User": self.user, "DeviceId": DEVICE_ID, "DeviceType": DEVICE_TYPE})
        req = urllib.request.Request(f"{URL}?{query}", data=encode(body), method="POST")
        req.add_header("Authorization", self._auth)
        req.add_header("User-Agent", "zcu-mail-mcp")
        req.add_header("Content-Type", "application/vnd.ms-sync.wbxml")
        req.add_header("MS-ASProtocolVersion", "14.1")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            raise EasError(f"{cmd}: " + HTTP_HINTS.get(e.code, f"HTTP {e.code} {e.reason}")) from None
        except urllib.error.URLError as e:
            raise EasError(f"webmail.zcu.cz je nedostupný: {e.reason}") from None
        return decode(data)[0] if data else None  # SendMail a spol. při úspěchu vrací prázdné tělo

    def addresses(self) -> list:
        """Vlastní adresy účtu podle identit v SOGo; z první SOGo odesílá."""
        if self._addresses is None:
            resp = self.call("Settings", ["Settings:Settings", ["UserInformation", ["Get"]]])
            box = first(resp, "UserInformation", "Get", "Accounts", "Account", "EmailAddresses")
            self._addresses = [c[1] for c in find(box, "PrimarySmtpAddress") + find(box, "SmtpAddress") if len(c) > 1]
            if not self._addresses:
                raise EasError("SOGo nevrátil adresy účtu (Settings UserInformation).")
        return self._addresses

    # --- složky ---

    def folders(self) -> list:
        # shortcut: seznam složek se načte jednou za běh procesu, nová složka se ukáže až po restartu serveru
        if self._folders is None:
            fs = self.call("FolderSync", ["FolderHierarchy:FolderSync", ["SyncKey", "0"]])
            if text(fs, "Status") != "1":
                raise EasError(f"FolderSync vrátil Status {text(fs, 'Status')}")
            raw = {text(f, "ServerId"): f for f in find(first(fs, "Changes"), "Add")}

            def path(fid: str) -> str:
                f = raw[fid]
                parent = text(f, "ParentId")
                return f"{path(parent)}/{text(f, 'DisplayName')}" if parent in raw else text(f, "DisplayName")

            self._folders = [{"id": fid, "path": path(fid), "type": int(text(f, "Type") or 0)} for fid, f in raw.items()]
        return self._folders

    def folder(self, spec: str) -> dict:
        """Složka podle id, cesty, názvu, nebo slova inbox/drafts/sent/trash (česky i anglicky)."""
        s = spec.strip().lower()
        fs = self.folders()
        for match in (lambda f: f["id"] == spec, lambda f: f["path"].lower() == s,
                      lambda f: f["path"].rsplit("/", 1)[-1].lower() == s, lambda f: f["type"] == FOLDER_TYPES.get(s)):
            for f in fs:
                if match(f):
                    return f
        raise EasError(f"Složka „{spec}“ neexistuje. Platné složky vrátí list_folders.")

    def folder_path(self, folder_id: str) -> str:
        return next((f["path"] for f in self.folders() if f["id"] == folder_id), folder_id)

    # --- Sync ---

    def _sync(self, folder_id: str, key: str, *extra: list):
        self.folders()  # SOGo odmítne Sync složky, kterou zařízení nezná z FolderSync (Status 12)
        resp = self.call("Sync", ["AirSync:Sync", ["Collections", ["Collection", ["SyncKey", key],
                                                                   ["CollectionId", folder_id], *extra]]])
        if resp is None:
            return None  # žádné změny
        coll = first(resp, "Collections", "Collection")
        status = text(coll, "Status") or text(resp, "Status")
        if status != "1":
            raise EasError(f"Sync složky {self.folder_path(folder_id)} vrátil Status {status}")
        return coll

    def _sync_key(self, folder_id: str) -> str:
        return text(self._sync(folder_id, "0"), "SyncKey")

    def list_messages(self, folder: str, days: int, limit: int, unread_only: bool) -> dict:
        fid = self.folder(folder)["id"]
        key = self._sync_key(fid)
        options = ["Options", ["FilterType", FILTER_TYPE[days]], ["AirSyncBase:BodyPreference", ["Type", "1"]],
                   ["MIMETruncation", "1"]]  # 1 = tělo zkrácené na 4 kB, stačí na náhled
        found = []
        for _ in range(100):  # pojistka; jedna stránka má 100 zpráv
            coll = self._sync(fid, key, ["WindowSize", "100"], options)
            if coll is None:
                break
            key = text(coll, "SyncKey") or key
            for add in find(first(coll, "Commands"), "Add"):
                found.append(summary(fid, text(add, "ServerId"), first(add, "ApplicationData")))
            if not find(coll, "MoreAvailable"):
                break
        if unread_only:
            found = [m for m in found if not m["read"]]
        found.sort(key=lambda m: m["date"], reverse=True)
        return {"folder": self.folder_path(fid), "total": len(found), "messages": found[:limit]}

    def mark(self, message_id: str, read=None, flagged=None) -> None:
        fid, uid = split_id(message_id)
        data = ["ApplicationData"]
        if read is not None:
            data.append(["Email:Read", "1" if read else "0"])
        if flagged is not None:
            data.append(["Email:Flag", ["FlagStatus", "2"]] if flagged else ["Email:Flag"])
        coll = self._sync(fid, self._sync_key(fid), ["GetChanges", "0"],
                          ["Commands", ["Change", ["ServerId", uid], data]])
        status = text(coll, "Responses", "Change", "Status")
        if status not in ("", "1"):
            raise EasError(f"Změna zprávy selhala, Status {status}" + (" (zpráva neexistuje)" if status == "8" else ""))

    def save_draft(self, to: list, subject: str, body: str, cc: list = (), attachments: list = ()) -> str:
        fid = self.folder("drafts")["id"]
        # shortcut: koncept bez Bcc, SOGo by tag Email2:Bcc (EAS 16) nemusel znát
        data = ["ApplicationData", ["Email:To", ", ".join(to)]]
        if cc:
            data.append(["Email:Cc", ", ".join(cc)])
        if attachments:
            # Type 4 = celé MIME. storeMail ho do Konceptů zapíše tak, jak je, včetně příloh a typu souboru.
            # Bez příloh zůstává textové tělo (Type 1), ať se koncept bez souborů nemění.
            mime = build_mime(to, subject, body, cc, attachments, sender=self.addresses()[0]).decode("ascii")
            data += [["Email:Subject", subject], ["AirSyncBase:Body", ["Type", "4"], ["Data", mime]]]
        else:
            data += [["Email:Subject", subject], ["AirSyncBase:Body", ["Type", "1"], ["Data", body]]]
        coll = self._sync(fid, self._sync_key(fid), ["GetChanges", "0"],
                          ["Commands", ["Add", ["ClientId", uuid.uuid4().hex], data]])
        add = first(coll, "Responses", "Add")
        if text(add, "Status") != "1" or not text(add, "ServerId"):
            raise EasError(f"Uložení konceptu selhalo, Status {text(add, 'Status') or '(žádný)'}")
        return f"{fid}+{text(add, 'ServerId')}"

    # --- hledání a čtení ---

    def search(self, query: str, folder=None, since=None, limit: int = 20) -> dict:
        self.folders()  # hledání ve všech složkách bere složky známé z FolderSync
        q = " ".join(query.translate({ord(c): " " for c in "'\"%\\"}).split())  # SOGo je vkládá do dotazu bez escapování
        if not q:
            raise EasError("Dotaz je prázdný (znaky ' \" % \\ se vynechávají).")
        cond = ["And"]
        if folder:
            cond.append(["AirSync:CollectionId", self.folder(folder)["id"]])
        cond.append(["FreeText", q])
        if since:
            cond.append(["GreaterThan", ["Email:DateReceived"], ["Value", f"{since}T00:00:00.000Z"]])
        resp = self.call("Search", ["Search:Search", ["Store", ["Name", "Mailbox"], ["Query", cond], ["Options",
                                    ["Range", f"0-{limit - 1}"], ["AirSyncBase:BodyPreference", ["Type", "1"]]]]])
        store = first(resp, "Response", "Store")
        if text(store, "Status") != "1":
            raise EasError(f"Hledání selhalo, Status {text(store, 'Status') or text(resp, 'Status')}")
        # Bez složky vrací SOGo id složky neescapované („mail/INBOX“), FolderSync escapované: sjednotit na FolderSync
        canon = {urllib.parse.unquote(f["id"]): f["id"] for f in self.folders()}
        found = []
        for r in find(store, "Result")[:limit]:
            fid, uid = split_id(text(r, "LongId"))
            fid = canon.get(urllib.parse.unquote(fid), fid)
            found.append({**summary(fid, uid, first(r, "Properties")), "folder": self.folder_path(fid)})
        return {"total": int(text(store, "Total") or 0), "messages": found}

    def _fetch(self, *what: list):
        resp = self.call("ItemOperations", ["ItemOperations:ItemOperations", ["Fetch", ["Store", "Mailbox"], *what]])
        fetch = first(resp, "Response", "Fetch")
        status = text(fetch, "Status") or text(resp, "Status")
        props = first(fetch, "Properties")
        if status != "1" or props is None:
            raise EasError(f"Načtení selhalo, Status {status or '(žádný)'}; zpráva možná už neexistuje.")
        return props

    def original_for_reply(self, message_id: str):
        """MIME původní zprávy, nebo None když z něj nejde složit citaci a vlákno."""
        fid, uid = split_id(message_id)
        props = self._fetch(["AirSync:CollectionId", fid], ["AirSync:ServerId", uid], ["Options",
                            ["AirSyncBase:BodyPreference", ["Type", "4"], ["TruncationSize", "2000000"]],
                            ["AirSync:MIMESupport", "2"]])
        if text(props, "Body", "Truncated") == "1":
            return None  # ořezané MIME by citovalo jen začátek; SmartReply doplní celou původní zprávu
        raw = _node_bytes(first(props, "Body", "Data"))
        if not raw:
            return None
        info = parse_original(raw)
        return info if info["message_id"] else None

    def read(self, message_id: str, max_chars: int = 20000) -> dict:
        fid, uid = split_id(message_id)
        props = self._fetch(["AirSync:CollectionId", fid], ["AirSync:ServerId", uid],
                            ["Options", ["AirSyncBase:BodyPreference", ["Type", "1"]]])
        body = text(props, "Body", "Data")
        msg = summary(fid, uid, props)
        del msg["preview"], msg["attachments"]
        msg.update(folder=self.folder_path(fid), reply_to=text(props, "ReplyTo"),
                   body=body[:max_chars], body_truncated=len(body) > max_chars,
                   attachments=[{"name": text(a, "DisplayName"), "ref": text(a, "FileReference"),
                                 "size": int(text(a, "EstimatedDataSize") or 0), "inline": text(a, "IsInline") == "1"}
                                for a in find(first(props, "Attachments"), "Attachment")])
        return msg

    def attachment(self, ref: str):
        props = self._fetch(["AirSyncBase:FileReference", ref])
        data = first(props, "Data")
        raw = data[1] if data and len(data) > 1 else b""
        return text(props, "ContentType"), raw if isinstance(raw, bytes) else base64.b64decode(raw)

    # --- odesílání a přesun ---

    def _compose(self, cmd: str, mime: bytes, source=None, replace_mime: bool = False) -> None:
        req = compose_request(cmd, mime, source or "", replace_mime)
        resp = self.call(cmd, req)
        if resp is not None and text(resp, "Status") not in ("", "1"):
            raise EasError(f"{cmd} selhal, Status {text(resp, 'Status')}; nic se neodeslalo.")

    def send(self, to: list, subject: str, body: str, cc: list = (), attachments: list = ()) -> None:
        # SaveInSentItems uloží totéž MIME, takže kopie v Odeslané poště má přílohy taky.
        self._compose("SendMail", build_mime(to, subject, body, cc, attachments))

    def reply_recipients(self, original: dict, reply_all: bool) -> tuple:
        to = [original["reply_to"] or original["from"]]
        cc = []
        if reply_all:
            mine = {a.lower() for a in self.addresses()}
            cc = [f"{n} <{a}>" if n else a for n, a in getaddresses([original["to"], original["cc"]])
                  if a and a.lower() not in mine and a not in to[0]]
        return to, cc

    def reply(self, message_id: str, body: str, to: list, cc: list, subject: str, attachments: list = ()) -> None:
        # Bez příloh nechává citaci i In-Reply-To/References na SOGo (SmartReply bez ReplaceMime).
        # S přílohami se zpráva složí tady: SOGo by ji jinak rozložil a jméno souboru (filename*) nemuselo přežít.
        # ReplaceMime pošle naše MIME tak, jak je, včetně příloh do Odeslané pošty. Source pořád označí původní jako zodpovězenou.
        if attachments:
            try:
                info = self.original_for_reply(message_id)
            except (EasError, UnicodeError, email.errors.MessageError):
                info = None
            if info and info["body"]:
                in_reply_to, references = threading_headers(info["message_id"], info["references"])
                mime = build_mime(to, subject, quote_original(body, info), cc, attachments,
                                  in_reply_to=in_reply_to, references=references)
                self._compose("SmartReply", mime, source=message_id, replace_mime=True)
                return
        self._compose("SmartReply", build_mime(to, subject, body, cc, attachments), source=message_id)

    def forward(self, message_id: str, to: list, body: str, subject: str) -> None:
        self._compose("SmartForward", build_mime(to, subject, body), source=message_id)

    def move(self, message_id: str, folder: str) -> str:
        fid, uid = split_id(message_id)
        dst = self.folder(folder)["id"]
        resp = self.call("MoveItems", ["Move:MoveItems", ["Move", ["SrcMsgId", uid], ["SrcFldId", fid], ["DstFldId", dst]]])
        r = first(resp, "Response")
        if text(r, "Status") != "3":  # 3 = přesunuto
            raise EasError(f"Přesun selhal, Status {text(r, 'Status') or '(žádný)'}")
        return f"{dst}+{text(r, 'DstMsgId')}" if text(r, "DstMsgId") else ""

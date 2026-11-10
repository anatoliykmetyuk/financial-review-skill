#!/usr/bin/env python3
"""Skill-owned financial ledger. All monetary JSON values are decimal strings."""
from __future__ import annotations

import argparse
import calendar
import csv
from contextlib import closing
import json
import re
import sqlite3
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path
from unicodedata import normalize as unicode_normalize
from zoneinfo import ZoneInfo

import yaml

getcontext().prec = 40
ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
SCHEMA_VERSION = 5


class ReviewError(ValueError):
    pass


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def read_json(path):
    return json.loads(Path(path).read_text(), parse_float=Decimal)


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        f.write(text)
    tmp.replace(path)


def number(value):
    try:
        n = Decimal(str(value).replace(",", ""))
    except InvalidOperation as e:
        raise ReviewError(f"Invalid amount: {value!r}") from e
    if not n.is_finite():
        raise ReviewError("Amounts and rates must be finite")
    return n


def currency(value):
    if not re.fullmatch(r"[A-Z]{3}", str(value)):
        raise ReviewError(f"Invalid currency: {value!r}")
    return value


def epoch_us(dt):
    d = dt.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (d.days * 86400 + d.seconds) * 1000000 + d.microseconds


def from_us(value):
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value)


def parse_instant(value, source_zone=None):
    value = value.strip()
    try:
        if re.match(r"\d{2}-\d{2}-\d{4}", value):
            fmt = "%d-%m-%Y %H:%M:%S.%f" if "." in value else "%d-%m-%Y %H:%M:%S"
            dt = datetime.strptime(value, fmt)
        else:
            # Python only preserves microseconds: reject finer precision, never truncate it.
            if re.search(r"\.\d{7,}", value):
                raise ReviewError("Timestamp precision finer than microseconds needs an adapter")
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if "T" not in value and " " not in value:
                raise ReviewError("Date-only transaction: time/timezone must be resolved before ingestion")
    except ValueError as e:
        raise ReviewError(f"Invalid transaction timestamp: {value!r}") from e
    if dt.tzinfo is None:
        if not source_zone:
            raise ReviewError("Set the source timezone for timestamps without an offset")
        zone = ZoneInfo(source_zone)
        candidates = [dt.replace(tzinfo=zone, fold=f) for f in (0, 1)]
        valid = [c for c in candidates if c.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == dt]
        if not valid or len({c.utcoffset() for c in valid}) > 1:
            raise ReviewError(f"Ambiguous/nonexistent local time: {value}; supply explicit UTC offset")
        dt = valid[0]
    return dt.astimezone(UTC)


def period(start, end, zone):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a > b:
        raise ReviewError("Start must not follow end")
    z = ZoneInfo(zone)
    return a, b, epoch_us(datetime.combine(a, time(), z)), epoch_us(datetime.combine(b + timedelta(days=1), time(), z))


SCHEMA = """
CREATE TABLE accounts(
 id TEXT PRIMARY KEY, name TEXT NOT NULL,
 currency TEXT NOT NULL CHECK(currency GLOB '[A-Z][A-Z][A-Z]'),
 source_timezone TEXT, tracked INTEGER NOT NULL DEFAULT 1 CHECK(tracked IN (0,1)));
CREATE TABLE transactions(
 id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 bank_transaction_id TEXT NOT NULL, timestamp_us INTEGER NOT NULL,
 posting_date TEXT, balance_after_minor INTEGER,
 description TEXT NOT NULL, merchant TEXT NOT NULL, payment_reference TEXT NOT NULL,
 details_type TEXT NOT NULL, amount_minor INTEGER NOT NULL,
 currency TEXT NOT NULL CHECK(currency GLOB '[A-Z][A-Z][A-Z]'),
 charged_amount_minor INTEGER, charged_currency TEXT CHECK(charged_currency GLOB '[A-Z][A-Z][A-Z]'),
 kind TEXT NOT NULL CHECK(kind IN ('expense','refund','income','internal','credit-review')),
 category TEXT, classification_origin TEXT CHECK(classification_origin IN ('rule','manual')),
 CHECK((posting_date IS NULL) = (balance_after_minor IS NULL)),
 CHECK((category IS NULL) = (classification_origin IS NULL)),
 CHECK((charged_amount_minor IS NULL) = (charged_currency IS NULL)));
CREATE INDEX transaction_period ON transactions(timestamp_us);
CREATE UNIQUE INDEX transaction_source ON transactions(account_id,bank_transaction_id,timestamp_us)
 WHERE posting_date IS NULL;
CREATE UNIQUE INDEX transaction_posting ON transactions(account_id,posting_date,bank_transaction_id,amount_minor,balance_after_minor)
 WHERE posting_date IS NOT NULL;
"""


def currency_digits(cur):
    if cur in {'BIF','CLP','DJF','GNF','ISK','JPY','KMF','KRW','PYG','RWF','UGX','UYI','VND','VUV','XAF','XOF','XPF'}:
        return 0
    if cur in {'BHD','IQD','JOD','KWD','LYD','OMR','TND'}:
        return 3
    return 4 if cur in {'CLF','UYW'} else 2


def to_minor(value, cur):
    scaled = number(value) * (10 ** currency_digits(cur))
    if scaled != scaled.to_integral_value():
        raise ReviewError(f"Amount {value} has fractional minor units for {cur}; no rounding applied")
    result = int(scaled)
    if not -(2**63) <= result < 2**63:
        raise ReviewError("Amount exceeds SQLite integer range")
    return result


def from_minor(value, cur):
    return Decimal(value).scaleb(-currency_digits(cur))


class Ledger:
    def __init__(self, data):
        self.data = Path(data).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.path = self.data / "transactions.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3, 4, SCHEMA_VERSION):
            raise ReviewError(f"Unsupported database version: {version}; explicit migration required")
        self.prune_backups()
        if 0 < version < SCHEMA_VERSION:
            try:
                self.migrate_schema()
            except Exception:
                self.db.close()
                raise
        if version == 0:
            self.db.executescript("BEGIN;\n" + SCHEMA + f"PRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;")

    def migrate_schema(self):
        if self.db.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
            self.before_write()
        self.db.execute("PRAGMA foreign_keys=OFF")
        self.db.execute("PRAGMA secure_delete=ON")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == SCHEMA_VERSION:
                self.db.commit()
                return
            self.db.execute("ALTER TABLE accounts RENAME TO old_accounts")
            self.db.execute("ALTER TABLE transactions RENAME TO old_transactions")
            for index in ("transaction_period","transaction_source"):
                self.db.execute(f"DROP INDEX IF EXISTS {index}")
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    self.db.execute(statement)
            self.db.execute("INSERT INTO accounts SELECT id,name,currency,source_timezone,tracked FROM old_accounts")
            columns = [row[1] for row in self.db.execute("PRAGMA table_info(transactions)")
                       if row[1] not in {"posting_date", "balance_after_minor"}]
            names = ",".join(columns)
            for old in self.db.execute("SELECT * FROM old_transactions").fetchall():
                values = dict(old)
                if version < 4:
                    values['amount_minor'] = to_minor(values['amount'],values['currency'])
                    values['charged_amount_minor'] = to_minor(values['charged_amount'],values['charged_currency']) if values['charged_amount'] is not None else None
                self.db.execute(f"INSERT INTO transactions({names}) VALUES ({','.join('?' for _ in columns)})",[values[k] for k in columns])
            for table in ("import_transactions","imports","institutions","legacy_corrections","metadata","old_transactions","old_accounts"):
                self.db.execute(f"DROP TABLE IF EXISTS {table}")
            self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        finally:
            self.db.execute("PRAGMA foreign_keys=ON")

    def close(self):
        self.db.close()

    def settings(self):
        path=self.data/'settings.yaml'
        config=yaml.safe_load(path.read_text()) if path.exists() else {}
        missing=missing_settings(config or {})
        if missing:
            raise ReviewError("Complete first-run setup in data/settings.yaml: " + ", ".join(missing))
        return config

    def setup_status(self):
        path=self.data/'settings.yaml'
        config=yaml.safe_load(path.read_text()) if path.exists() else {}
        missing=missing_settings(config or {})
        accounts=self.db.execute('SELECT id,source_timezone FROM accounts WHERE tracked=1').fetchall()
        if not accounts:missing.append('tracked accounts')
        missing.extend('source timezone for '+account['id'] for account in accounts if not account['source_timezone'])
        return {'ready':not missing,'missing':missing}

    def backup_today(self):
        path=self.data/'settings.yaml'
        config=yaml.safe_load(path.read_text()) if path.exists() else {}
        zone=(config or {}).get('defaults',{}).get('timezone')
        if not zone:
            return None,None
        zone=ZoneInfo(zone)
        return datetime.now(zone).date(),zone

    def prune_backups(self):
        """Keep one snapshot per date for today and the previous six dates."""
        today,zone = self.backup_today()
        if today is None:
            return
        oldest = today - timedelta(days=6)
        folder = self.data / "backups"
        groups = {}
        for path in sorted(folder.glob("*.sqlite3")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.sqlite3",path.name):
                    day = date.fromisoformat(path.stem)
                elif re.fullmatch(r"\d{8}T\d{12}Z\.sqlite3",path.name):
                    day = datetime.strptime(path.stem,"%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC).astimezone(zone).date()
                else:
                    continue
            except ValueError:
                continue
            if day < oldest or day > today:
                path.unlink()
            else:
                groups.setdefault(day,[]).append(path)
        for day,paths in groups.items():
            daily = folder / f"{day.isoformat()}.sqlite3"
            keep = daily if daily in paths else paths[-1]
            for path in paths:
                if path != keep:
                    path.unlink()
            if keep != daily:
                keep.rename(daily)

    def before_write(self):
        if self.db.in_transaction:
            return
        self.settings()
        self.prune_backups()
        today,_ = self.backup_today()
        folder = self.data / "backups"
        folder.mkdir(exist_ok=True)
        path = folder / f"{today.isoformat()}.sqlite3"
        try:
            path.open("xb").close()
        except FileExistsError:
            return
        try:
            with closing(sqlite3.connect(path)) as destination:
                self.db.backup(destination)
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def rules(self):
        path = self.data / "rules.yaml"
        if not path.exists():
            raise ReviewError(f"Missing classification rules: {path}")
        config = yaml.safe_load(path.read_text())
        if not isinstance(config, dict) or not isinstance(config.get("rules"), list):
            raise ReviewError("rules.yaml must contain a rules list")
        for r in config["rules"]:
            if not isinstance(r, dict) or not isinstance(r.get("category"), str) or not r["category"].strip() or not isinstance(r.get("keywords"), list):
                raise ReviewError("Each rule needs a category string and keywords list")
            if any(not isinstance(k, str) or not k.strip() for k in r["keywords"]):
                raise ReviewError("Keywords must be nonempty strings")
        return config

    def configure_account(self, bank, source_id, name, cur, source_zone=None):
        currency(cur)
        if source_zone:
            ZoneInfo(source_zone)
        account_id = f"{bank}:{source_id}"
        self.before_write()
        with self.db:
            self.db.execute("""INSERT INTO accounts(id,name,currency,source_timezone) VALUES (?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,currency=excluded.currency,
                source_timezone=COALESCE(excluded.source_timezone,accounts.source_timezone)""",
                (account_id,name,cur,source_zone))
        return account_id

    def ingest(self, path, account_id, adapter):
        account = self.db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not account:
            raise ReviewError("Unknown account; configure it first")
        if adapter == "sony-bank":
            payload = json.load(sys.stdin, parse_float=Decimal) if Path(path) == Path('-') else read_json(path)
            return self.ingest_sony(sony_postings(payload, account), account_id)
        content = Path(path).read_text(encoding="utf-8-sig")
        reader = csv.DictReader(content.splitlines(keepends=True),strict=True)
        required = {"TransferWise ID","Date Time","Amount","Currency","Description","Transaction Details Type"} if adapter == "wise" else {"timestamp","amount","currency","description","kind"} if adapter == "normalized" else None
        if required is None:
            raise ReviewError(f"Unknown adapter: {adapter}")
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not required.issubset(headers):
            raise ReviewError(f"Invalid {adapter} headers; required: {sorted(required)}")
        rows = list(reader)
        if any(None in row or any(v is None for v in row.values()) for row in rows):
            raise ReviewError("Malformed CSV row: column count does not match headers")
        prepared = [normalize(row,adapter,account) for row in rows]
        added,seen = 0,set()
        with self.db:
            for row in prepared:
                key = tuple(row.values())
                if key in seen:
                    raise ReviewError("Indistinguishable rows within one file; ask about duplicate/collision")
                seen.add(key)
                matches = self.db.execute("""SELECT * FROM transactions WHERE account_id=? AND timestamp_us=? AND posting_date IS NULL
                    AND (bank_transaction_id=? OR bank_transaction_id='' OR ?='')""",
                    (account_id,row['timestamp_us'],row['bank_transaction_id'],row['bank_transaction_id'])).fetchall()
                def equal(old):
                    return all(old[k]==v for k,v in row.items())
                if matches:
                    if len(matches)==1 and equal(matches[0]):
                        continue
                    raise ReviewError(f"Conflicting duplicate/ambiguous timestamp: existing IDs {[m['id'] for m in matches]}")
                self.insert_transaction(account_id, row)
                added+=1
        return {"added":added,"rows":len(rows)}

    def insert_transaction(self, account_id, row):
        self.before_write()
        self.db.execute(f"INSERT INTO transactions(account_id,{','.join(row)}) VALUES (?,{','.join('?' for _ in row)})",
                        [account_id, *row.values()])

    def ingest_sony(self, rows, account_id):
        added, refreshed = 0, 0
        if not rows:
            return {"added":0,"rows":0,"refreshed":0}
        self.before_write()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for key, row in rows.items():
                matches = self.db.execute("""SELECT * FROM transactions WHERE account_id=? AND posting_date=?
                    AND amount_minor=? AND balance_after_minor=?
                    AND (bank_transaction_id=? OR bank_transaction_id='' OR ?='')""",
                    (account_id, *key, row["bank_transaction_id"])).fetchall()
                if len(matches) > 1 or (matches and matches[0]["bank_transaction_id"] != row["bank_transaction_id"]):
                    raise ReviewError("Ambiguous Sony Bank posting reference")
                old = matches[0] if matches else None
                if old is None:
                    self.insert_transaction(account_id, row)
                    added += 1
                elif any(old[field] != row[field] for field in ("description", "merchant")):
                    if not row["bank_transaction_id"]:
                        raise ReviewError(f"Ambiguous Sony Bank posting: existing transaction {old['id']}")
                    self.db.execute("UPDATE transactions SET description=?,merchant=? WHERE id=?",
                                    (row["description"], row["merchant"], old["id"]))
                    refreshed += 1
        return {"added":added,"rows":len(rows),"refreshed":refreshed}

    def select(self, start, end, zone=None):
        zone=zone or self.settings()['defaults']['timezone']
        first, last, a, b = period(start,end,zone)
        report_zone = ZoneInfo(zone)
        rows = self.db.execute("""SELECT t.*,a.name AS account_name FROM transactions t
            JOIN accounts a ON a.id=t.account_id
            WHERE (posting_date IS NULL AND timestamp_us>=? AND timestamp_us<?) OR posting_date BETWEEN ? AND ?
            ORDER BY timestamp_us,t.id""", (a,b,first.isoformat(),last.isoformat())).fetchall()
        result = []
        for row in rows:
            r = dict(row)
            r['amount'] = str(from_minor(r['amount_minor'],r['currency']))
            r['charged_amount'] = str(from_minor(r['charged_amount_minor'],r['charged_currency'])) if r['charged_amount_minor'] is not None else None
            dt = from_us(r["timestamp_us"]).astimezone(report_zone)
            posting_date = r['posting_date']
            r.update(local_date=posting_date or dt.date().isoformat(),local_time=None if posting_date else dt.strftime("%H:%M"),
                     local_datetime=posting_date or dt.isoformat(),
                     timestamp_unix=str(Decimal(r["timestamp_us"])/1000000))
            result.append(r)
        result.sort(key=lambda row: row['local_date'])
        return result

    def classify(self, start, end, zone=None):
        config = self.rules()
        updated = 0
        with self.db:
            for r in self.select(start,end,zone):
                if r["classification_origin"] == "manual":
                    continue
                category = match(r,config["rules"])
                origin = "rule" if category else None
                if r["category"] == category and r["classification_origin"] == origin:
                    continue
                self.before_write()
                self.db.execute("UPDATE transactions SET category=?,classification_origin=? WHERE id=?",
                                (category,"rule" if category else None,r["id"]))
                updated += 1
        return {"processed":updated,"unclassified":[r for r in self.select(start,end,zone) if r["category"] is None]}

    def assign(self, ids, category, kind=None):
        if category is not None and not category.strip():
            raise ReviewError("Use clear to remove a classification")
        if kind and kind not in {"expense","refund","income","internal","credit-review"}:
            raise ReviewError("Invalid transaction kind")
        with self.db:
            for tid in ids:
                if not self.db.execute("SELECT 1 FROM transactions WHERE id=?", (tid,)).fetchone():
                    raise ReviewError(f"Unknown transaction: {tid}")
                self.before_write()
                self.db.execute("UPDATE transactions SET category=?,classification_origin=?,kind=COALESCE(?,kind) WHERE id=?",
                                (category,"manual" if category else None,kind,tid))

    def add_rule(self, keyword, category, start, end, zone):
        config = self.rules()
        keyword = keyword.strip()
        if not keyword or not category.strip():
            raise ReviewError("Keyword and category must be nonempty")
        for r in config["rules"]:
            r["keywords"] = [k for k in r["keywords"] if k.strip().lower() != keyword.lower()]
        target = next((r for r in config["rules"] if r["category"] == category),None)
        if target is None:
            target = {"category":category,"keywords":[]}
            config["rules"].append(target)
        target["keywords"] = sorted(target["keywords"] + [keyword],key=str.lower)
        period(start,end,zone)
        old = (self.data/"rules.yaml").read_text()
        atomic_write(self.data/"rules.yaml",yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
        try:
            return self.classify(start,end,zone)
        except Exception:
            atomic_write(self.data/"rules.yaml",old)
            raise

    def coverage(self, start, end, zone=None, as_of=None, cutoff=None):
        """Per-report display context only. Nothing is persisted about exports."""
        zone=zone or self.settings()['defaults']['timezone']
        first,last,_,_ = period(start,end,zone)
        now = parse_instant(as_of) if as_of else datetime.now(UTC)
        through = min(parse_instant(cutoff),now) if cutoff else None
        observed = {row['local_date'] for row in self.select(start,end,zone)}
        days=[]
        for i in range((last-first).days+1):
            day=first+timedelta(days=i)
            _,_,lo,hi=period(day.isoformat(),day.isoformat(),zone)
            if through:
                status='complete' if epoch_us(through)>=hi else 'partial' if epoch_us(through)>lo else 'missing'
            else:
                status='partial' if day.isoformat() in observed else 'missing'
            days.append({'date':day.isoformat(),'status':status,
                         'cutoff':min(through,from_us(hi)).isoformat() if through and status!='missing' else None})
        return {'days':days,'complete':all(d['status']=='complete' for d in days),
                'usable_for_review':through is not None,'as_of':now.isoformat()}


def match(row, rules):
    haystack = " ".join(row.get(k) or "" for k in ("description","merchant","payment_reference","details_type")).strip().lower()
    best, length = None, -1
    for r in rules:
        for keyword in r["keywords"]:
            k = keyword.strip().lower()
            if k and k in haystack and len(k) > length:
                best,length = r["category"],len(k)
    return best


def normalize(row, adapter, account):
    if adapter == "wise":
        required = {"TransferWise ID","Date Time","Amount","Currency","Description","Transaction Details Type"}
        if not required.issubset(row):
            raise ReviewError(f"Missing Wise headers: {sorted(required-set(row))}")
        raw_time = row["Date Time"].strip()
        amount,cur = number(row["Amount"]),currency(row["Currency"])
        details = row["Transaction Details Type"].strip()
        kind = "internal" if details == "CONVERSION" else "expense" if amount < 0 else "refund" if details=="CARD" else "income" if details=="DEPOSIT" else "credit-review"
        charged = re.match(r"Card transaction of ([\d,.]+) ([A-Z]{3}) issued by ",row["Description"])
        values = dict(bank_transaction_id=row["TransferWise ID"].strip(),description=row["Description"],
                      merchant=row.get("Merchant","") or "",payment_reference=row.get("Payment Reference","") or "",
                      details_type=details,charged_amount=str(number(charged[1])) if charged else None,
                      charged_currency=charged[2] if charged else None,kind=kind)
    elif adapter == "normalized":
        required = {"timestamp","amount","currency","description","kind"}
        if not required.issubset(row):
            raise ReviewError(f"Missing normalized CSV headers: {sorted(required-set(row))}")
        raw_time = row["timestamp"]
        amount,cur = number(row["amount"]),currency(row["currency"])
        if row["kind"] not in {"expense","refund","income","internal","credit-review"}:
            raise ReviewError("Unknown normalized transaction kind")
        values = dict(bank_transaction_id=row.get("bank_transaction_id","") or "",description=row["description"],
                      merchant=row.get("merchant","") or "",payment_reference=row.get("payment_reference","") or "",
                      details_type=row.get("details_type","") or "",kind=row["kind"],
                      charged_amount=str(number(row["charged_amount"])) if row.get("charged_amount") else None,
                      charged_currency=currency(row["charged_currency"]) if row.get("charged_currency") else None)
    else:
        raise ReviewError(f"Unknown adapter: {adapter}")
    if cur != account["currency"]:
        raise ReviewError("CSV currency does not match account currency")
    if bool(values["charged_amount"]) != bool(values["charged_currency"]):
        raise ReviewError("Charged amount and currency must be supplied together")
    dt = parse_instant(raw_time,account["source_timezone"])
    ts = epoch_us(dt)
    charged_value = values.pop('charged_amount')
    values.update(timestamp_us=ts,amount_minor=to_minor(amount,cur),currency=cur,
                  charged_amount_minor=to_minor(charged_value,values['charged_currency']) if charged_value is not None else None)

    return values


def sony_postings(payload, account):
    if not account["id"].startswith("sony-bank:"):
        raise ReviewError("The Sony Bank adapter requires a Sony Bank account")
    if not isinstance(payload, dict) or payload.get("currency") != account["currency"]:
        raise ReviewError("Sony Bank result currency does not match the account")
    rows = payload.get("rows")
    count = payload.get("result_count")
    if not isinstance(rows, list) or type(count) is not int or count != len(rows):
        raise ReviewError("Sony Bank row count does not match the displayed result count")
    if any(not isinstance(payload.get(field), str) for field in ("start", "end")):
        raise ReviewError("Sony Bank results require start and end dates")
    first, last = date.fromisoformat(payload["start"]), date.fromisoformat(payload["end"])
    if first > last:
        raise ReviewError("Sony Bank result start must not follow end")
    prepared = {}
    fields = ("date", "currency", "description", "amount", "balance_after")
    for raw in rows:
        if not isinstance(raw, dict) or any(not isinstance(raw.get(field), str) for field in fields):
            raise ReviewError("Sony Bank rows require date, currency, description, amount, and balance_after strings")
        day = date.fromisoformat(raw["date"])
        if not first <= day <= last:
            raise ReviewError("Sony Bank posting date is outside the displayed range")
        if any(not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", raw[field]) for field in ("amount", "balance_after")):
            raise ReviewError("Sony Bank amounts and balances must be plain signed decimal strings")
        description = " ".join(unicode_normalize("NFKC", raw["description"]).split())
        card = re.fullmatch(r"Visa\s*(?:デビット|Debit)(?:\s+(\d{2}\s+\d{6}))?(?:\s+(.+))?", description, re.IGNORECASE)
        transfer = re.fullmatch(r"(?:円|外貨)普通預金(?:\([^()]+\))?(?:へ|より|から)振替", description)
        reference = card[1] if card and card[1] else ""
        amount = number(raw["amount"])
        kind = "expense" if amount < 0 else "credit-review"
        details_type = ""
        if transfer:
            kind, details_type = "internal", "SONY BANK SAVINGS TRANSFER"
        elif card:
            kind, details_type = ("refund" if amount > 0 else kind), "CARD"
        row = normalize({
            "timestamp": f"{day.isoformat()}T00:00:00", "amount": amount, "currency": raw["currency"],
            "description": description, "merchant": card[2] if card and card[2] else "",
            "bank_transaction_id": reference, "payment_reference": reference, "kind": kind,
            "details_type": details_type,
        }, "normalized", account)
        row.update(posting_date=day.isoformat(), balance_after_minor=to_minor(raw["balance_after"], row["currency"]))
        key = (row["posting_date"], row["amount_minor"], row["balance_after_minor"], reference)
        if key in prepared:
            raise ReviewError("Indistinguishable Sony Bank rows in the displayed results")
        prepared[key] = row
    return prepared


def rate_table(snapshot, needed, base):
    if not snapshot.get("retrieved_at"):
        raise ReviewError("Rates need retrieval time")
    parse_instant(snapshot["retrieved_at"])
    if snapshot.get('base_currency')!=base:
        raise ReviewError('Rate snapshot base currency must match settings')
    rates = {base:Decimal(1)}
    for cur in needed-{base}:
        r = snapshot.get("rates",{}).get(cur)
        if not r or not r.get("source_url","").startswith("https://wise.com/"):
            raise ReviewError(f"Missing current Wise rate for {cur}")
        rates[cur] = number(r["base_per_unit"])
        if rates[cur] <= 0:
            raise ReviewError("Rates must be positive")
    return rates


def budget_balance(spent, allowance, threshold):
    excess = spent - allowance
    return {
        "spent_base": spent, "allowance_base": allowance, "remaining_base": -excess,
        "excess_base": max(excess, Decimal(0)),
        "status": "red" if excess > threshold else "yellow" if excess > 0 else "green",
    }


def check_budgets(last, today, available, months, totals, ongoing, threshold):
    checks = []
    for month in months:
        start = date.fromisoformat(f"{month}-01")
        if start > today:
            continue
        days = calendar.monthrange(start.year, start.month)[1]
        month_end = start.replace(day=days)
        review_end = min(last, month_end)
        anchor = min(review_end, today)
        sunday = anchor + timedelta(days=6 - anchor.weekday())
        for category, amounts in sorted(available.items()):
            if month not in amounts:
                continue
            cumulative = category in ongoing
            allowance_end = min(sunday, month_end) if cumulative else month_end
            monthly = number(amounts[month])
            allowance = monthly * allowance_end.day / days if cumulative else monthly
            spent = totals.get((month, category), Decimal(0))
            checks.append({
                "category": category, "cadence": "ongoing" if cumulative else "monthly",
                "month": month, "allowance_end": allowance_end.isoformat(),
                **budget_balance(spent, allowance, threshold),
            })
    return checks


def report(ledger, start, end, zone, budget, fx, category=None, local_currency=None, as_of=None, cutoff=None):
    config=ledger.settings()
    zone=zone or config['defaults']['timezone']
    base=config['defaults']['base_currency']
    local_currency=local_currency or config['defaults']['local_currency']
    threshold=number(config['defaults']['yellow_excess_max'])
    category=config['category_aliases'].get(category,category)
    a,b,_,_ = period(start,end,zone)
    review_time = parse_instant(as_of) if as_of else datetime.now(UTC)
    current_local = review_time.astimezone(ZoneInfo(zone)).date()
    data_end = min(parse_instant(cutoff), review_time) if cutoff else review_time
    cutoff_day = data_end.astimezone(ZoneInfo(zone)).date().isoformat()
    cutoff_us = epoch_us(data_end)
    rows = [r for r in ledger.select(a.replace(day=1).isoformat(),end,zone)
            if (r["posting_date"] <= cutoff_day if r["posting_date"] else r["timestamp_us"] <= cutoff_us)]
    unknown = [r for r in rows if r["category"] is None]
    ambiguous_credit = [r for r in rows if r["kind"]=="credit-review"]
    if unknown or ambiguous_credit:
        return {"status":"needs-classification","unclassified":unknown,"credits_needing_kind":ambiguous_credit}
    coverage = ledger.coverage(start,end,zone,as_of,cutoff)
    needed = {r["currency"] for r in rows}
    if category:
        needed.add(currency(local_currency))
    rates = rate_table(fx,needed,base)
    age = review_time - parse_instant(fx["retrieved_at"])
    if age < timedelta(minutes=-5) or age > timedelta(hours=24):
        raise ReviewError("Fetch current Wise rates for this review; supplied snapshot is stale or future-dated")
    issues = []
    available = budget["categories"]
    for c in sorted({r["category"] for r in rows if r['kind'] not in {'income','internal'}}-set(available)):
        issues.append({"category":c,"problem":"Category absent from current budget spreadsheet"})
    if category and category not in available:
        issues.append({"category":category,"problem":"Requested category has no verified spreadsheet row"})
    totals = {}
    monthly_totals = {}
    for r in rows:
        if r["kind"] in {"internal","income"}:
            continue
        cost = -number(r["amount"])*rates[r["currency"]]
        if r["kind"]=="expense" and number(r["amount"])>0 or r["kind"]=="refund" and number(r["amount"])<0:
            raise ReviewError(f"Transaction kind/sign conflict: {r['id']}")
        r["spent_base"] = cost
        c = r["category"]
        key = (r["local_date"][:7], c)
        monthly_totals[key] = monthly_totals.get(key, Decimal(0)) + cost
        if r["local_date"] >= a.isoformat():
            totals[c] = totals.get(c, Decimal(0)) + cost
    for issue in issues:
        c = issue["category"]
        issue["spent_base"] = sum((spent for (_, name), spent in monthly_totals.items() if name == c), Decimal(0))
        issue["transactions"] = [r for r in rows if r["category"]==c]
    results = []
    days = [a+timedelta(days=i) for i in range((b-a).days+1)]
    months = dict.fromkeys(d.strftime('%Y-%m') for d in days)
    for c in sorted(set(available)|set(totals)|({category} if category else set())):
        if c not in available:
            continue
        allowances = []
        for day in days:
            m = day.strftime("%Y-%m")
            if m not in available[c]:
                issues.append({"category":c,"problem":f"Missing verified month column {m}"})
                break
            allowances.append(number(available[c][m])/calendar.monthrange(day.year,day.month)[1])
        else:
            allowance,spent = sum(allowances,Decimal(0)),totals.get(c,Decimal(0))
            results.append({"category":c,**budget_balance(spent, allowance, threshold),
                            "daily_allowances_base":allowances,"monthly_base":{m:available[c][m] for m in months}})
    budget_checks = check_budgets(b, current_local, available, months, monthly_totals,
                                  config.get("ongoing_categories", []), threshold)
    latest = rows[-1]["local_datetime"] if rows else None
    is_current_week = (b-a).days == 6 and a.weekday() == 0 and a <= current_local <= b
    result = {"base_currency":base,"mode":"category" if category else "general","start":start,"end":end,"timezone":zone,"is_current_week":is_current_week,
              "coverage":coverage,"rate_snapshot":fx,"issues":issues,"categories":results,
              "budget_checks":budget_checks,"latest_transaction":latest,
              "all_within_budget":not issues and coverage["usable_for_review"]
              and any(d["status"] != "missing" for d in coverage["days"])
              and all(r["status"]=="green" for r in budget_checks),
              "status":"budget-mapping-required" if issues else "ready"}
    if category:
        target = next((r for r in results if r["category"]==category),None)
        if target is None:
            return result
        target["local_currency"] = local_currency
        for key in ("spent","allowance","remaining","excess"):
            target[key+"_local"] = target[key+"_base"]/rates[local_currency]
        target["percent_used"] = target["spent_base"]/target["allowance_base"]*100 if target["allowance_base"] else None
        target["segments"] = [{"date":d.isoformat(),"allowance_local":allow/rates[local_currency]} for d,allow in zip(days,target["daily_allowances_base"])]
        included = [r for r in rows if r["local_date"] >= a.isoformat() and r["category"]==category and "spent_base" in r]
        chart = []
        for cov in coverage["days"]:
            transactions = [r for r in included if r["local_date"]==cov["date"]]
            for r in transactions:
                r["spent_local"] = r["spent_base"]/rates[local_currency]
            total = sum((r["spent_local"] for r in transactions),Decimal(0))
            chart.append({**cov,"total_local":total if cov["status"]!="missing" else None,"transactions":transactions})
        target["days"] = chart
        assert sum((r["spent_base"] for r in included),Decimal(0)) == target["spent_base"]
        result["category_report"] = target
    return result


def empty_settings():
    return {'version':2,
            'defaults':{'timezone':None,'browser':'chrome','period':None,'base_currency':None,'local_currency':None,'yellow_excess_max':None},
            'budget':{'spreadsheet_id':None,'sheet':None},
            'category_aliases':{},'ongoing_categories':[],'banks':{}}


def missing_settings(config):
    missing=[]
    defaults=config.get('defaults') or {};budget=config.get('budget') or {}
    for key in ('timezone','browser','period','base_currency','local_currency','yellow_excess_max'):
        if defaults.get(key) is None or defaults.get(key)=='':missing.append('defaults.'+key)
    if defaults.get('timezone'):
        ZoneInfo(defaults['timezone'])
    for key in ('base_currency','local_currency'):
        if defaults.get(key):currency(defaults[key])
    if defaults.get('period') and defaults['period'] not in ('this_week','this_month','last_week','last_month'):
        raise ReviewError('Unsupported default period')
    if defaults.get('yellow_excess_max') is not None and number(defaults['yellow_excess_max'])<0:
        raise ReviewError('Warning threshold must be nonnegative')
    for key in ('spreadsheet_id','sheet'):
        if not budget.get(key):missing.append('budget.'+key)
    if not isinstance(config.get('category_aliases'),dict):missing.append('category_aliases')
    ongoing = config.get("ongoing_categories", [])
    if not isinstance(ongoing, list) or any(not isinstance(c, str) or not c.strip() for c in ongoing):
        raise ReviewError("ongoing_categories must be a list of spreadsheet category names")
    if not isinstance(config.get('banks'),dict):missing.append('banks')
    return missing


def bootstrap(ledger, zone=None, spreadsheet_id=None, sheet=None):
    if zone:ZoneInfo(zone)
    config=empty_settings()
    config['defaults']['timezone']=zone
    config['budget'].update(spreadsheet_id=spreadsheet_id,sheet=sheet)
    created=[]
    for folder in ('backups',):(ledger.data/folder).mkdir(exist_ok=True)
    for path,value in ((ledger.data/'settings.yaml',config),(ledger.data/'rules.yaml',{'rules':[]})):
        if not path.exists():
            atomic_write(path,yaml.safe_dump(value,allow_unicode=True,sort_keys=False));created.append(path.name)
    return {'database':str(ledger.path),'schema_version':SCHEMA_VERSION,'created':created,'setup':ledger.setup_status()}


def configure(ledger,path):
    config=yaml.safe_load(Path(path).read_text())
    missing=missing_settings(config or {})
    if missing:raise ReviewError('Incomplete setup: '+', '.join(missing))
    atomic_write(ledger.data/'settings.yaml',yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
    return {'setup':ledger.setup_status()}


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir",type=Path,default=ROOT/"data")
    subs = p.add_subparsers(dest="command",required=True)
    init = subs.add_parser("init")
    init.add_argument("--timezone")
    init.add_argument("--budget-spreadsheet-id")
    init.add_argument("--budget-sheet")
    subs.add_parser("status")
    configure_parser=subs.add_parser('configure')
    configure_parser.add_argument('path',type=Path)
    ac = subs.add_parser("account")
    for name in ("bank","source-id","name","currency"):
        ac.add_argument("--"+name,required=True)
    for name in ("source-timezone",):
        ac.add_argument("--"+name)
    ing = subs.add_parser("ingest")
    ing.add_argument("path",type=Path)
    ing.add_argument("--account",required=True)
    ing.add_argument("--adapter",choices=["wise","normalized","sony-bank"],required=True)
    for name in ("classify","query","rule","report"):
        sub = subs.add_parser(name)
        sub.add_argument("--start",required=True)
        sub.add_argument("--end",required=True)
        sub.add_argument("--timezone")
        if name=="report":
            sub.add_argument("--as-of")
            sub.add_argument("--cutoff",help="Optional data cutoff for this report only; not stored")
        if name=="query":
            sub.add_argument("--unclassified",action="store_true")
        if name=="rule":
            sub.add_argument("--keyword",required=True)
            sub.add_argument("--category",required=True)
        if name=="report":
            sub.add_argument("--budget",required=True,type=Path)
            sub.add_argument("--rates",required=True,type=Path)
            sub.add_argument("--category")
            sub.add_argument("--local-currency")
    assign = subs.add_parser("assign")
    assign.add_argument("ids",nargs="+",type=int)
    assign.add_argument("--category",required=True)
    assign.add_argument("--kind",choices=["expense","refund","income","internal","credit-review"])
    clear = subs.add_parser("clear")
    clear.add_argument("ids",nargs="+",type=int)
    return p


def main():
    args = build_parser().parse_args()
    ledger = None
    try:
        ledger = Ledger(args.data_dir)
        cmd = args.command
        if cmd not in {'init','configure','status'}:
            config=ledger.settings()
            if cmd!='account' and not ledger.setup_status()['ready']:
                raise ReviewError('Finish setup: '+', '.join(ledger.setup_status()['missing']))
            if getattr(args,'category',None):args.category=config['category_aliases'].get(args.category,args.category)
        if cmd=="init":
            result = bootstrap(ledger,args.timezone,args.budget_spreadsheet_id,args.budget_sheet)
        elif cmd=='configure':
            result=configure(ledger,args.path)
        elif cmd=="account":
            result = {"account":ledger.configure_account(args.bank,args.source_id,args.name,args.currency,args.source_timezone)}
        elif cmd=="ingest":
            result = ledger.ingest(args.path,args.account,args.adapter)
        elif cmd=="classify":
            result = ledger.classify(args.start,args.end,args.timezone)
        elif cmd=="rule":
            result = ledger.add_rule(args.keyword,args.category,args.start,args.end,args.timezone)
        elif cmd=="query":
            result = ledger.select(args.start,args.end,args.timezone)
            if args.unclassified:
                result = [r for r in result if r["category"] is None]
        elif cmd in {"assign","clear"}:
            ledger.assign(args.ids,args.category if cmd=="assign" else None,args.kind if cmd=="assign" else None)
            result = {"updated":args.ids}
        elif cmd=="report":
            result = report(ledger,args.start,args.end,args.timezone,read_json(args.budget),read_json(args.rates),args.category,args.local_currency,args.as_of,args.cutoff)
        else:
            result = {"setup":ledger.setup_status(),"schema_version":SCHEMA_VERSION,"accounts":[dict(r) for r in ledger.db.execute("SELECT * FROM accounts")],
                      "transactions":ledger.db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]}

        print(dump(result))
        return 0
    except (ReviewError,ValueError,KeyError,OSError,sqlite3.Error,yaml.YAMLError,csv.Error) as e:
        print(dump({"error":str(e)}),file=sys.stderr)
        return 2
    finally:
        if ledger:
            ledger.close()


if __name__ == "__main__":
    sys.exit(main())

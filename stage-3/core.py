from __future__ import annotations
import base64, copy, hashlib, json, os, re, secrets, sqlite3, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from stage import STAGE

MAX_AMOUNT = 1_000_000_000
MAX_NOTE = 200
KEY_MAX = 255
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CURRENCIES = {"EUR": 2, "JPY": 0, "BHD": 3}

def now_dt() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt: datetime | None = None) -> str:
    if dt is None:
        dt = now_dt()
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","+00:00")

def parse_dt(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid instant")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(normalized)
    except Exception as exc:
        raise ValueError("invalid instant") from exc
    if dt.tzinfo is None:
        raise ValueError("invalid instant")
    return dt.astimezone(timezone.utc)

def ts_key(value: Any) -> datetime:
    """Chronological sort key for stored instants; unparsable values sort first."""
    try:
        return parse_dt(value)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=False)

def new_id(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex[:20]
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 180_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return "pbkdf2_sha256$%d$%s$%s" % (
        rounds,
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )

def check_password(password: str, stored: str) -> bool:
    try:
        alg, rounds, salt, digest = stored.split("$",3)
        if alg != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode(),
            base64.urlsafe_b64decode(salt), int(rounds))
        return secrets.compare_digest(
            base64.urlsafe_b64encode(got).decode(), digest)
    except Exception:
        return False

def fmt_amount(amount: int, minor_units: int, currency: str) -> str:
    if minor_units == 0:
        return f"{amount} {currency}"
    s = str(abs(int(amount))).rjust(minor_units+1,"0")
    sign = "-" if amount < 0 else ""
    return f"{sign}{s[:-minor_units]}.{s[-minor_units:]} {currency}"

def equal_split(amount: int, n: int) -> list[int]:
    base, rem = divmod(amount, n)
    return [base + (1 if i < rem else 0) for i in range(n)]

class PocketError(Exception):
    def __init__(self, status: int, code: str, message: str=""):
        self.status = status
        self.code = code
        self.message = message or code
        super().__init__(self.message)

def err(status: int, code: str, message: str="") -> None:
    raise PocketError(status, code, message or code)
class Store:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._init()

    def conn(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None,
                            check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=15000")
        return c

    def _init(self):
        c = self.conn()
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS state
                         (id INTEGER PRIMARY KEY CHECK(id=1), blob TEXT NOT NULL)""")
            if c.execute("SELECT 1 FROM state WHERE id=1").fetchone() is None:
                c.execute("INSERT INTO state(id,blob) VALUES(1,?)",
                          (json.dumps(self.empty()),))
        finally:
            c.close()

    @staticmethod
    def empty():
        return {"track":"pocketful","format_version":1,"currency":"EUR",
                "minor_units":2,"authorization_ttl_seconds":600,
                "users":{},"tokens":{},"payments":[],"requests":[],
                "authorizations":[],"settlements":[],
                "settlement_operator_ids":[],"idempotency":[],
                "snapshots":{},"opening_balances":{}}
    def read(self):
        c=self.conn()
        try:
            return json.loads(c.execute("SELECT blob FROM state WHERE id=1").fetchone()[0])
        finally:
            c.close()

    def tx(self):
        c=self.conn()
        c.execute("BEGIN IMMEDIATE")
        return c

    def commit_state(self,c,state):
        c.execute("UPDATE state SET blob=? WHERE id=1",
                  (json.dumps(state,separators=(",",":")),))
        c.execute("COMMIT")

    def rollback(self,c):
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass

    def replace(self,state):
        c=self.tx()
        try:
            self.commit_state(c,state)
        except Exception:
            self.rollback(c)
            raise

    def mutate(self, fn):
        with self.lock:
            c=self.tx()
            try:
                st=json.loads(c.execute("SELECT blob FROM state WHERE id=1").fetchone()[0])
                out=fn(st)
                self.commit_state(c,st)
                return out
            except Exception:
                self.rollback(c)
                raise
    def reset(self, fixture):
        self.replace(self.make_fixture(fixture))

    def export(self):
        return self.read()

    def make_fixture(self, fx):
        if not isinstance(fx,dict):
            err(422,"validation_failed")
        currency=fx.get("currency")
        mu=fx.get("minor_units")
        if currency not in CURRENCIES or mu != CURRENCIES[currency]:
            err(422,"validation_failed")
        users_raw=fx.get("users")
        if not isinstance(users_raw,list) or not users_raw:
            err(422,"validation_failed")
        st=self.empty()
        st["currency"]=currency
        st["minor_units"]=mu
        st["authorization_ttl_seconds"]=fx.get("authorization_ttl_seconds",600)
        if type(st["authorization_ttl_seconds"]) is not int or st["authorization_ttl_seconds"]<=0:
            err(422,"validation_failed")
        seen_handles=set()
        seen_emails=set()
        seen_ids=set()
        for u in users_raw:
            if not isinstance(u,dict):
                err(422,"validation_failed")
            uid,handle,email,password,balance = (
                u.get("id"),u.get("handle"),u.get("email"),u.get("password"),u.get("balance"))
            if (not isinstance(uid,str) or not ID_RE.fullmatch(uid) or
                not isinstance(handle,str) or not HANDLE_RE.fullmatch(handle)):
                err(422,"validation_failed")
            if handle in seen_handles or uid in seen_ids or not isinstance(email,str) or not EMAIL_RE.fullmatch(email):
                err(422,"validation_failed")
            if email in seen_emails or not isinstance(password,str) or len(password)<8 or type(balance) is not int or balance<0:
                err(422,"validation_failed")
            seen_handles.add(handle); seen_emails.add(email); seen_ids.add(uid)
            st["users"][uid]={
                "id":uid,"email":email,"password_hash":hash_password(password),
                "display_name":str(u.get("display_name","")),
                "handle":handle,"balance":balance}
            st["opening_balances"][uid]=balance
        st["settlement_operator_ids"]=list(fx.get("settlement_operator_ids") or [])
        if any(x not in st["users"] for x in st["settlement_operator_ids"]):
            err(422,"validation_failed")
        reset_time=now_dt()
        seeded=[]
        for p in fx.get("payments") or []:
            if not isinstance(p,dict):
                err(422,"validation_failed")
            pid=p.get("id",new_id("p"))
            sid=p.get("from_user_id"); rid=p.get("to_user_id"); amt=p.get("amount")
            if (not isinstance(pid,str) or not ID_RE.fullmatch(pid) or
                sid not in st["users"] or rid not in st["users"] or sid==rid):
                err(422,"validation_failed")
            amt=self.validate_amount(amt)
            created=p.get("created_at") or iso(reset_time)
            try:
                cdt=parse_dt(created)
            except Exception:
                err(422,"validation_failed")
            if cdt > reset_time:
                err(422,"validation_failed")
            note=p.get("note",""); vis=p.get("visibility","public")
            if not isinstance(note,str) or len(note)>MAX_NOTE or vis not in ("public","private"):
                err(422,"validation_failed")
            seeded.append(self.make_payment(st,pid,sid,rid,amt,note,vis,
                p.get("request_id"),p.get("authorization_id"),
                p.get("settlement_id"),p.get("refund_of"),created))
        st["payments"]=seeded
        for p in seeded:
            st["opening_balances"][p["from_user_id"]]+=p["amount"]
            st["opening_balances"][p["to_user_id"]]-=p["amount"]
        if any(v<0 for v in st["opening_balances"].values()):
            err(422,"validation_failed")
        for r in fx.get("requests") or []:
            if not isinstance(r,dict):
                err(422,"validation_failed")
            rid=r.get("id",new_id("rq"))
            requester=r.get("requester_id")
            payer=r.get("payer_id")
            amt=r.get("amount")
            if requester not in st["users"] or payer not in st["users"] or requester==payer:
                err(422,"validation_failed")
            amt=self.validate_amount(amt)
            note=r.get("note",""); status=r.get("status","pending")
            if (not isinstance(note,str) or len(note)>MAX_NOTE or
                status not in ("pending","paid","declined","cancelled")):
                err(422,"validation_failed")
            st["requests"].append({
                "request_id":rid,"requester_id":requester,"payer_id":payer,
                "amount":amt,"currency":currency,"note":note,"status":status,
                "payment_id":r.get("payment_id"),
                "created_at":r.get("created_at") or iso(reset_time)})
        if STAGE >= 2:
            for a in fx.get("authorizations") or []:
                if not isinstance(a,dict):
                    err(422,"validation_failed")
                aid=a.get("id",new_id("a")); sid=a.get("from_user_id"); rid=a.get("to_user_id")
                amt=a.get("amount"); status=a.get("status","open")
                if (sid not in st["users"] or rid not in st["users"] or sid==rid or
                    type(amt) is not int or not 1<=amt<=MAX_AMOUNT or
                    status not in ("open","captured","voided","expired")):
                    err(422,"validation_failed")
                exp=a.get("expires_at")
                if not isinstance(exp,str):
                    err(422,"validation_failed")
                try:
                    parse_dt(exp)
                except Exception:
                    err(422,"validation_failed")
                created=a.get("created_at") or iso(reset_time)
                st["authorizations"].append({
                    "authorization_id":aid,"from_user_id":sid,"to_user_id":rid,
                    "amount":amt,"captured_amount":int(a.get("captured_amount",0)),
                    "currency":currency,"note":a.get("note",""),
                    "visibility":a.get("visibility","public"),"status":status,
                    "expires_at":exp,"payment_id":a.get("payment_id"),
                    "payment_ids":list(a.get("payment_ids") or
                                       ([] if a.get("payment_id") is None else [a.get("payment_id")])),
                    "created_at":created,"closed_at":a.get("closed_at")})
            held=self.held_map(st,reset_time)
            for uid,v in held.items():
                if v>st["users"][uid]["balance"]:
                    err(422,"validation_failed")
        return st

    def make_payment(self,st,pid,sid,rid,amt,note,vis,request_id=None,
                     auth_id=None,settlement_id=None,refund_of=None,created_at=None):
        created_at=created_at or iso()
        return {
            "payment_id":pid,"from_user_id":sid,
            "from_handle":st["users"][sid]["handle"],
            "to_user_id":rid,"to_handle":st["users"][rid]["handle"],
            "amount":amt,"currency":st["currency"],"note":note,
            "visibility":vis,"request_id":request_id,
            "authorization_id":auth_id,"settlement_id":settlement_id,
            "refund_of":refund_of,"created_at":created_at,
            "revisions":[{"revision":1,"amount":amt,
                "effective_at":created_at,"recorded_at":created_at,
                "reason":"","correction_batch_id":None}]}
    def user_by_handle(self,st,h):
        for u in st["users"].values():
            if u["handle"]==h:
                return u
        return None

    def user_from_token(self,st,token):
        return st["users"].get(st["tokens"].get(token)) if token else None

    def active_user(self,st,token):
        u=self.user_from_token(st,token)
        if not u:
            err(401,"unauthenticated")
        return u

    def expire(self,st,at=None):
        at=at or now_dt()
        for a in st["authorizations"]:
            if a["status"]=="open":
                try:
                    exp=parse_dt(a["expires_at"])
                except Exception:
                    continue
                if exp <= at:
                    a["status"]="expired"
                    a["closed_at"]=a["expires_at"]

    def held_map(self,st,at=None):
        self.expire(st,at)
        held={uid:0 for uid in st["users"]}
        for a in st.get("authorizations",[]):
            if a["status"]=="open":
                held[a["from_user_id"]]+=max(0,a["amount"]-a.get("captured_amount",0))
        return held
    def me(self,st,u,as_of=None,known_at=None):
        if as_of is None:
            h=self.held_map(st)
            return self.basic_user(st,u,h[u["id"]],known_at)
        return self.historical_me(st,u,as_of,known_at)

    def basic_user(self,st,u,held=0,known_at=None):
        d={"user_id":u["id"],"display_name":u["display_name"],"handle":u["handle"],
           "balance":u["balance"],"total":u["balance"],
           "available":u["balance"]-held,"held":held,
           "currency":st["currency"],"minor_units":st["minor_units"]}
        if known_at is not None:
            d["known_at"]=known_at
        return d

    def selected_revision(self,p,known_at=None):
        if known_at is None:
            return p["revisions"][-1]
        k=parse_dt(known_at); chosen=None
        for r in p["revisions"]:
            if parse_dt(r["recorded_at"])<=k and (
                chosen is None or parse_dt(r["recorded_at"])>parse_dt(chosen["recorded_at"])):
                chosen=r
        return chosen

    def payment_events(self,st,known_at=None):
        out=[]
        for p in st["payments"]:
            r=self.selected_revision(p,known_at)
            if r is not None:
                out.append((p,r))
        return out

    def historical_totals(self,st,as_of=None,known_at=None):
        base=copy.deepcopy(st["opening_balances"])
        as_dt=parse_dt(as_of) if as_of is not None else now_dt()
        events=[(parse_dt(r["effective_at"]),p["payment_id"],p,r)
                 for p,r in self.payment_events(st,known_at)]
        events.sort(key=lambda x:(x[0],x[1]))
        for eff,_,p,r in events:
            if eff<=as_dt:
                base[p["from_user_id"]]-=r["amount"]
                base[p["to_user_id"]]+=r["amount"]
        return base

    def historical_me(self,st,u,as_of,known_at):
        totals=self.historical_totals(st,as_of,known_at)
        held=self.historical_held(st,as_of,known_at,u["id"])
        shadow={**u,"balance":totals[u["id"]]}
        d=self.basic_user(st,shadow,held,known_at)
        d["as_of"]=as_of
        return d
    def historical_held(self,st,as_of,known_at,uid):
        t=parse_dt(as_of)
        k=parse_dt(known_at) if known_at else None
        held=0
        for a in st.get("authorizations",[]):
            if a["from_user_id"]!=uid:
                continue
            created=parse_dt(a["created_at"])
            if created>t or (k and created>k):
                continue
            captured=0
            for pid in a.get("payment_ids",[]):
                p=next((p for p in st["payments"] if p["payment_id"]==pid),None)
                if not p:
                    continue
                ct=parse_dt(p["created_at"])
                if ct<=t and (not k or ct<=k):
                    captured+=p["amount"]
            rem=max(0,a["amount"]-captured)
            try:
                exp=parse_dt(a["expires_at"])
            except Exception:
                exp=None
            closed=parse_dt(a["closed_at"]) if a.get("closed_at") else None
            # A hold never outlives its expiry, whether or not a write has
            # persisted the "expired" status yet.
            if exp and exp<=t:
                rem=0
            if closed and closed<=t and a["status"] in ("captured","voided","expired"):
                rem=0
            if rem>0:
                held+=rem
        return held

    def serialize_payment(self,st,p):
        return {k:p.get(k) for k in (
            "payment_id","from_user_id","from_handle","to_user_id","to_handle",
            "amount","currency","note","visibility","request_id",
            "authorization_id","settlement_id","refund_of","created_at")}

    def serialize_request(self,st,r):
        return {"request_id":r["request_id"],
            "requester_id":r["requester_id"],
            "requester_handle":st["users"][r["requester_id"]]["handle"],
            "payer_id":r["payer_id"],
            "payer_handle":st["users"][r["payer_id"]]["handle"],
            "amount":r["amount"],"currency":r["currency"],"note":r["note"],
            "status":r["status"],"payment_id":r.get("payment_id"),
            "created_at":r["created_at"]}

    def serialize_auth(self,st,a):
        rem=max(0,a["amount"]-a.get("captured_amount",0))
        return {"authorization_id":a["authorization_id"],
            "from_user_id":a["from_user_id"],
            "from_handle":st["users"][a["from_user_id"]]["handle"],
            "to_user_id":a["to_user_id"],
            "to_handle":st["users"][a["to_user_id"]]["handle"],
            "amount":a["amount"],"captured_amount":a.get("captured_amount",0),
            "remaining_amount":rem,"currency":a["currency"],"note":a["note"],
            "visibility":a["visibility"],"status":a["status"],
            "expires_at":a["expires_at"],"payment_id":a.get("payment_id"),
            "payment_ids":list(a.get("payment_ids") or []),
            "created_at":a["created_at"],"closed_at":a.get("closed_at")}
    def visible_activity(self,st,u):
        out=[self.serialize_payment(st,p) for p in st["payments"]
             if p["visibility"]=="public" or u["id"] in (p["from_user_id"],p["to_user_id"])]
        return sorted(out,key=lambda x:(ts_key(x["created_at"]),x["payment_id"]),reverse=True)

    def idem_replay(self,st,u,key,method,path,body):
        if not isinstance(key,str) or not key:
            err(400,"missing_idempotency_key")
        if len(key)>KEY_MAX:
            err(422,"validation_failed")
        c=canon(body)
        for rec in st["idempotency"]:
            if rec["user_id"]==u["id"] and rec["key"]==key and rec["method"]==method and rec["path"]==path:
                if rec["body"]!=c:
                    err(409,"idempotency_key_reuse")
                return rec["response"]
        return None

    def record_idem(self,st,u,key,method,path,body,status,response):
        st["idempotency"].append({"user_id":u["id"],"key":key,
            "method":method,"path":path,"body":canon(body),
            "status":status,"response":response})

    def validate_amount(self,x,allow_zero=False):
        lo=0 if allow_zero else 1
        if isinstance(x,bool):
            err(422,"validation_failed")
        if isinstance(x,float):
            if not x.is_integer():
                err(422,"validation_failed")
            x=int(x)
        elif type(x) is not int:
            err(422,"validation_failed")
        if x<lo or x>MAX_AMOUNT:
            err(422,"validation_failed")
        return x

    def validate_note_visibility(self,note,vis):
        if not isinstance(note,str) or len(note)>MAX_NOTE or vis not in ("public","private"):
            err(422,"validation_failed")

    def transfer(self,st,u,to_handle,amount,note,vis,request_id=None,
                 auth_id=None,settlement_id=None,refund_of=None):
        amount=self.validate_amount(amount)
        self.validate_note_visibility(note,vis)
        target=self.user_by_handle(st,to_handle)
        if target is None:
            err(404,"not_found")
        if target["id"]==u["id"]:
            err(422,"self_payment")
        held=self.held_map(st)[u["id"]]
        if u["balance"]-held<amount:
            err(409,"insufficient_funds")
        if target["balance"]+amount>(1<<63)-1:
            err(422,"validation_failed")
        u["balance"]-=amount
        target["balance"]+=amount
        p=self.make_payment(st,new_id("p"),u["id"],target["id"],amount,note,vis,
            request_id,auth_id,settlement_id,refund_of,iso())
        st["payments"].append(p)
        if request_id:
            r=next(x for x in st["requests"] if x["request_id"]==request_id)
            r["status"]="paid"; r["payment_id"]=p["payment_id"]
        return p

    def check_historical_nonnegative(self,st,overrides=None):
        overrides=overrides or {}
        cur=copy.deepcopy(st["opening_balances"])
        events=[]
        for p in st["payments"]:
            r=overrides.get(p["payment_id"],p["revisions"][-1])
            events.append((parse_dt(r["effective_at"]),p["payment_id"],p,r))
        events.sort(key=lambda x:(x[0],x[1]))
        for _,_,p,r in events:
            cur[p["from_user_id"]]-=r["amount"]
            cur[p["to_user_id"]]+=r["amount"]
            if any(v<0 for v in cur.values()):
                return False
        return True

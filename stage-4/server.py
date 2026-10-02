from __future__ import annotations
import json, os, re, secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response
from core import Store, PocketError, err, iso, parse_dt, ts_key, canon, new_id, hash_password, check_password, equal_split, fmt_amount, MAX_AMOUNT, MAX_NOTE, KEY_MAX, HANDLE_RE, EMAIL_RE, now_dt
from stage import STAGE

DB_PATH=os.getenv("POCKETFUL_DB","/tmp/pocketful/state.db")
store=Store(DB_PATH)
app=FastAPI(title="Pocketful")

def jerr(code,status=422,message=None):
    return JSONResponse({"error":{"code":code,"message":message or code}},status_code=status)

@app.exception_handler(PocketError)
async def pocket_error_handler(_request,exc):
    return jerr(exc.code,exc.status,exc.message)

@app.exception_handler(Exception)
async def unexpected_handler(_request,exc):
    return jerr("internal_error",500,"internal error")

async def body(request: Request):
    try:
        obj=await request.json()
    except Exception:
        err(400,"malformed_request")
    if not isinstance(obj,dict):
        err(400,"malformed_request")
    return obj

def token(request: Request):
    raw=request.headers.get("authorization","")
    if not raw.startswith("Bearer "):
        err(401,"unauthenticated")
    return raw[7:].strip()

def is_html(request: Request):
    return "text/html" in request.headers.get("accept","")
def qint(request: Request,name: str,default:int,maxv:int=200,minv:int=1):
    raw=request.query_params.get(name)
    if raw is None: return default
    if not re.fullmatch(r"[0-9]+",raw):
        err(422,"validation_failed")
    v=int(raw)
    if v<minv or v>maxv:
        err(422,"validation_failed")
    return v

def qoffset(request: Request):
    raw=request.query_params.get("offset")
    if raw is None: return 0
    if not re.fullmatch(r"[0-9]+",raw):
        err(422,"validation_failed")
    return int(raw)

def instant_param(request: Request,name:str):
    if name not in request.query_params:
        return None
    raw=request.query_params.get(name)
    try:
        parse_dt(raw)
    except Exception:
        err(422,"validation_failed")
    return raw

def require_write_key(request):
    k=request.headers.get("Idempotency-Key")
    if k is None or k=="":
        err(400,"missing_idempotency_key")
    if len(k)>KEY_MAX:
        err(422,"validation_failed")
    return k

def auth_user(st,request):
    return store.active_user(st,token(request))

def replay_or_none(st,u,key,body_obj,method,path):
    return store.idem_replay(st,u,key,method,path,body_obj)

@app.get("/health")
async def health():
    return {"status":"ok"}

@app.get("/_test/export")
async def export_state():
    return {"track":"pocketful","format_version":1,"state":store.export()}

@app.post("/_test/reset")
async def reset(request: Request):
    try:
        fx=await body(request)
        store.reset(fx)
        return Response(status_code=204)
    except PocketError:
        raise
    except Exception:
        err(422,"validation_failed")

@app.post("/_test/import")
async def import_state(request: Request):
    obj=await body(request)
    if obj.get("track")!="pocketful" or obj.get("format_version")!=1 or not isinstance(obj.get("state"),dict):
        err(422,"validation_failed")
    st=obj["state"]
    if st.get("track")!="pocketful" or st.get("format_version")!=1 or not isinstance(st.get("users"),dict):
        err(422,"validation_failed")
    try:
        # Validate that a private round-trip state can be serialized and reopened.
        json.dumps(st)
        store.replace(st)
    except Exception:
        err(422,"validation_failed")
    return Response(status_code=204)
@app.post("/auth/signup")
async def signup(request: Request):
    obj=await body(request)
    email=obj.get("email"); password=obj.get("password"); display=obj.get("display_name")
    if not isinstance(email,str) or not isinstance(password,str) or not isinstance(display,str):
        err(400,"malformed_request")
    if not EMAIL_RE.fullmatch(email) or len(password)<8:
        err(422,"validation_failed")
    def op(st):
        for u in st["users"].values():
            if u["email"]==email:
                err(409,"email_taken")
        local=email.split("@",1)[0].lower()
        handle=re.sub(r"[^a-z0-9_]","_",local)[:20]
        if not HANDLE_RE.fullmatch(handle):
            err(422,"validation_failed")
        if store.user_by_handle(st,handle) is not None:
            err(409,"handle_taken")
        uid=new_id("u")
        st["users"][uid]={"id":uid,"email":email,"password_hash":hash_password(password),
            "display_name":display,"handle":handle,"balance":0}
        st["opening_balances"][uid]=0
        tok=secrets.token_urlsafe(32)
        st["tokens"][tok]=uid
        return {"user_id":uid,"display_name":display,"token":tok}
    out=store.mutate(op)
    return JSONResponse(out,status_code=201)

@app.post("/auth/login")
async def login(request: Request):
    obj=await body(request)
    email=obj.get("email"); password=obj.get("password")
    if not isinstance(email,str) or not isinstance(password,str):
        err(400,"malformed_request")
    demo_login=os.getenv("POCKETFUL_DEMO_LOGIN","").lower() in ("1","true","yes","on")
    if not email or not password or not EMAIL_RE.fullmatch(email):
        err(422,"validation_failed")
    def op(st):
        u=next((u for u in st["users"].values() if u["email"].lower()==email.lower()),None)
        if u is None and demo_login:
            local=email.split("@",1)[0].lower()
            base=re.sub(r"[^a-z0-9_]","_",local)[:14].strip("_") or "guest"
            handle=base
            if store.user_by_handle(st,handle) is not None:
                handle=(base[:13]+"_"+secrets.token_hex(3))[:20]
            uid=new_id("u")
            display_name=local[:40] or "Guest"
            u={"id":uid,"email":email,"password_hash":hash_password(password),
               "display_name":display_name,"handle":handle,"balance":0}
            st["users"][uid]=u
            st["opening_balances"][uid]=0
        elif u is None or (not demo_login and not check_password(password,u["password_hash"])):
            err(401,"unauthenticated")
        tok=secrets.token_urlsafe(32); st["tokens"][tok]=u["id"]
        return {"user_id":u["id"],"display_name":u["display_name"],"token":tok}
    return store.mutate(op)

@app.get("/me")
async def me(request: Request):
    st=store.read(); u=auth_user(st,request)
    as_of=instant_param(request,"as_of") if STAGE>=3 else None
    known_at=instant_param(request,"known_at") if STAGE>=3 else None
    return store.me(st,u,as_of,known_at)
@app.post("/payments")
async def create_payment(request: Request):
    obj=await body(request)
    def op(st):
        u=auth_user(st,request)
        key=require_write_key(request)
        replay=replay_or_none(st,u,key,obj,"POST","/payments")
        if replay is not None: return JSONResponse(replay,status_code=200)
        if "to_handle" not in obj or "amount" not in obj:
            err(422,"validation_failed")
        if not isinstance(obj["to_handle"],str):
            err(400,"malformed_request")
        amount=store.validate_amount(obj["amount"])
        note=obj.get("note",""); vis=obj.get("visibility","public")
        store.validate_note_visibility(note,vis)
        p=store.transfer(st,u,obj["to_handle"],amount,note,vis)
        out=store.serialize_payment(st,p)
        store.record_idem(st,u,key,"POST","/payments",obj,201,out)
        return JSONResponse(out,status_code=201)
    return store.mutate(op)

@app.post("/requests")
async def create_request(request: Request):
    obj=await body(request)
    def op(st):
        u=auth_user(st,request)
        key=require_write_key(request)
        replay=replay_or_none(st,u,key,obj,"POST","/requests")
        if replay is not None: return JSONResponse(replay,status_code=200)
        if "payer_handle" not in obj or "amount" not in obj:
            err(422,"validation_failed")
        if not isinstance(obj["payer_handle"],str):
            err(400,"malformed_request")
        payer=store.user_by_handle(st,obj["payer_handle"])
        if payer is None: err(404,"not_found")
        if payer["id"]==u["id"]: err(422,"self_request")
        amount=store.validate_amount(obj["amount"])
        note=obj.get("note","")
        if not isinstance(note,str) or len(note)>MAX_NOTE: err(422,"validation_failed")
        r={"request_id":new_id("rq"),"requester_id":u["id"],"payer_id":payer["id"],
           "amount":amount,"currency":st["currency"],"note":note,"status":"pending",
           "payment_id":None,"created_at":iso()}
        st["requests"].append(r); out=store.serialize_request(st,r)
        store.record_idem(st,u,key,"POST","/requests",obj,201,out)
        return JSONResponse(out,status_code=201)
    return store.mutate(op)

@app.get("/requests")
async def list_requests(request: Request):
    if is_html(request) and request.url.path=="/requests":
        return HTMLResponse(ui_html("/requests"))
    st=store.read(); u=auth_user(st,request)
    direction=request.query_params.get("direction")
    status=request.query_params.get("status")
    if direction not in (None,"incoming","outgoing"): err(422,"validation_failed")
    if status not in (None,"pending","paid","declined","cancelled"): err(422,"validation_failed")
    limit=qint(request,"limit",50); offset=qoffset(request)
    rows=[]
    for r in st["requests"]:
        if u["id"] not in (r["requester_id"],r["payer_id"]): continue
        if direction=="incoming" and r["payer_id"]!=u["id"]: continue
        if direction=="outgoing" and r["requester_id"]!=u["id"]: continue
        if status and r["status"]!=status: continue
        rows.append(store.serialize_request(st,r))
    rows.sort(key=lambda x:(ts_key(x["created_at"]),x["request_id"]),reverse=True)
    return {"requests":rows[offset:offset+limit],"has_more":offset+limit<len(rows)}
@app.post("/requests/{rid}/pay")
async def pay_request(rid:str,request: Request):
    obj=await body(request)
    def op(st):
        u=auth_user(st,request)
        key=require_write_key(request)
        replay=replay_or_none(st,u,key,obj,"POST",f"/requests/{rid}/pay")
        if replay is not None: return JSONResponse(replay,status_code=200)
        r=next((x for x in st["requests"] if x["request_id"]==rid),None)
        if r is None: err(404,"not_found")
        if r["payer_id"]!=u["id"]: err(403,"forbidden")
        if r["status"]!="pending": err(409,"request_not_pending")
        vis=obj.get("visibility","public")
        if vis not in ("public","private"): err(422,"validation_failed")
        p=store.transfer(st,u,st["users"][r["requester_id"]]["handle"],r["amount"],r["note"],vis,request_id=rid)
        out=store.serialize_payment(st,p)
        store.record_idem(st,u,key,"POST",f"/requests/{rid}/pay",obj,201,out)
        return JSONResponse(out,status_code=201)
    return store.mutate(op)

@app.post("/requests/{rid}/decline")
async def decline_request(rid:str,request: Request):
    def op(st):
        u=auth_user(st,request)
        r=next((x for x in st["requests"] if x["request_id"]==rid),None)
        if r is None: err(404,"not_found")
        if r["payer_id"]!=u["id"]: err(403,"forbidden")
        if r["status"]=="declined": return store.serialize_request(st,r)
        if r["status"]!="pending": err(409,"request_not_pending")
        r["status"]="declined"
        return store.serialize_request(st,r)
    return store.mutate(op)

@app.post("/requests/{rid}/cancel")
async def cancel_request(rid:str,request: Request):
    def op(st):
        u=auth_user(st,request)
        r=next((x for x in st["requests"] if x["request_id"]==rid),None)
        if r is None: err(404,"not_found")
        if r["requester_id"]!=u["id"]: err(403,"forbidden")
        if r["status"]=="cancelled": return store.serialize_request(st,r)
        if r["status"]!="pending": err(409,"request_not_pending")
        r["status"]="cancelled"
        return store.serialize_request(st,r)
    return store.mutate(op)
@app.post("/splits")
async def create_split(request: Request):
    obj=await body(request)
    def op(st):
        u=auth_user(st,request)
        key=require_write_key(request)
        replay=replay_or_none(st,u,key,obj,"POST","/splits")
        if replay is not None: return JSONResponse(replay,status_code=200)
        if "amount" not in obj or "participant_handles" not in obj:
            err(422,"validation_failed")
        amount=store.validate_amount(obj["amount"]); handles=obj["participant_handles"]; note=obj.get("note","")
        if not isinstance(handles,list):
            err(400,"malformed_request")
        if not handles or any(not isinstance(h,str) for h in handles) or len(set(handles))!=len(handles):
            err(422,"validation_failed")
        if not isinstance(note,str) or len(note)>MAX_NOTE: err(422,"validation_failed")
        users=[]
        for h in handles:
            x=store.user_by_handle(st,h)
            if x is None: err(404,"not_found")
            users.append(x)
        shares=equal_split(amount,len(users))
        reqs=[]
        for x,share in zip(users,shares):
            if x["id"]==u["id"]: continue
            r={"request_id":new_id("rq"),"requester_id":u["id"],"payer_id":x["id"],
               "amount":share,"currency":st["currency"],"note":note,"status":"pending",
               "payment_id":None,"created_at":iso()}
            st["requests"].append(r); reqs.append(store.serialize_request(st,r))
        out={"split_id":new_id("sp"),"amount":amount,"currency":st["currency"],"note":note,
             "shares":[{"handle":x["handle"],"amount":s} for x,s in zip(users,shares)],
             "requests":reqs,"created_at":iso()}
        store.record_idem(st,u,key,"POST","/splits",obj,201,out)
        return JSONResponse(out,status_code=201)
    return store.mutate(op)

@app.get("/activity")
async def activity(request: Request):
    if is_html(request) and request.url.path=="/":
        return HTMLResponse(ui_html("/"))
    st=store.read(); u=auth_user(st,request)
    limit=qint(request,"limit",50); offset=qoffset(request)
    rows=store.visible_activity(st,u)
    return {"payments":rows[offset:offset+limit],"has_more":offset+limit<len(rows)}

@app.post("/settlements")
async def settlement(request: Request):
    obj=await body(request)
    def op(st):
        u=auth_user(st,request)
        key=require_write_key(request)
        replay=replay_or_none(st,u,key,obj,"POST","/settlements")
        if replay is not None: return JSONResponse(replay,status_code=200)
        if u["id"] not in st["settlement_operator_ids"]: err(403,"forbidden")
        transfers=obj.get("transfers")
        if not isinstance(transfers,list) or not 1<=len(transfers)<=32: err(422,"validation_failed")
        parsed=[]
        delta={}
        for t in transfers:
            if not isinstance(t,dict) or "from_handle" not in t or "to_handle" not in t or "amount" not in t:
                err(422,"validation_failed")
            sender=store.user_by_handle(st,t["from_handle"]); receiver=store.user_by_handle(st,t["to_handle"])
            if sender is None or receiver is None: err(404,"not_found")
            if sender["id"]==receiver["id"]: err(422,"self_payment")
            amt=store.validate_amount(t["amount"])
            note=t.get("note",""); vis=t.get("visibility","public"); store.validate_note_visibility(note,vis)
            parsed.append((sender,receiver,amt,note,vis))
            delta[sender["id"]]=delta.get(sender["id"],0)-amt
            delta[receiver["id"]]=delta.get(receiver["id"],0)+amt
        held=store.held_map(st)
        for uid,dd in delta.items():
            if st["users"][uid]["balance"]-held.get(uid,0)+dd<0: err(409,"insufficient_funds")
        sid=new_id("set"); committed=iso(); outs=[]
        for sender,receiver,amt,note,vis in parsed:
            sender["balance"]-=amt; receiver["balance"]+=amt
            p=store.make_payment(st,new_id("p"),sender["id"],receiver["id"],amt,note,vis,settlement_id=sid,created_at=committed)
            st["payments"].append(p); outs.append(store.serialize_payment(st,p))
        st["settlements"].append({"settlement_id":sid,"committed_at":committed,"payment_ids":[p["payment_id"] for p in st["payments"] if p["settlement_id"]==sid]})
        out={"settlement_id":sid,"committed_at":committed,"payments":outs}
        store.record_idem(st,u,key,"POST","/settlements",obj,201,out)
        return JSONResponse(out,status_code=201)
    return store.mutate(op)
def require_stage(n):
    if STAGE < n:
        err(404,"not_found")

def find_payment(st,pid):
    return next((p for p in st["payments"] if p["payment_id"]==pid),None)

@app.post("/authorizations")
async def create_authorization(request: Request):
    require_stage(2)
    obj=await body(request)
    def op(st):
        u=auth_user(st,request)
        key=require_write_key(request)
        replay=replay_or_none(st,u,key,obj,"POST","/authorizations")
        if replay is not None: return JSONResponse(replay,status_code=200)
        if "to_handle" not in obj or "amount" not in obj: err(422,"validation_failed")
        if not isinstance(obj["to_handle"],str): err(422,"validation_failed")
        target=store.user_by_handle(st,obj["to_handle"])
        if target is None: err(404,"not_found")
        if target["id"]==u["id"]: err(422,"self_payment")
        amount=store.validate_amount(obj["amount"]); note=obj.get("note",""); vis=obj.get("visibility","public")
        store.validate_note_visibility(note,vis)
        held=store.held_map(st)[u["id"]]
        if u["balance"]-held<amount: err(409,"insufficient_funds")
        created_dt=now_dt(); created=iso(created_dt); exp=iso(created_dt+timedelta(seconds=st["authorization_ttl_seconds"]))
        a={"authorization_id":new_id("a"),"from_user_id":u["id"],"to_user_id":target["id"],
           "amount":amount,"captured_amount":0,"currency":st["currency"],"note":note,
           "visibility":vis,"status":"open","expires_at":exp,"payment_id":None,
           "payment_ids":[],"created_at":created,"closed_at":None}
        st["authorizations"].append(a)
        out=store.serialize_auth(st,a)
        store.record_idem(st,u,key,"POST","/authorizations",obj,201,out)
        return JSONResponse(out,status_code=201)
    return store.mutate(op)

@app.post("/authorizations/{aid}/capture")
async def capture_authorization(aid:str,request: Request):
    require_stage(2)
    obj=await body(request)
    def op(st):
        u=auth_user(st,request)
        key=require_write_key(request)
        replay=replay_or_none(st,u,key,obj,"POST",f"/authorizations/{aid}/capture")
        if replay is not None: return JSONResponse(replay,status_code=200)
        a=next((x for x in st["authorizations"] if x["authorization_id"]==aid),None)
        if a is None: err(404,"not_found")
        if a["to_user_id"]!=u["id"]: err(403,"forbidden")
        store.expire(st)
        if a["status"]=="expired": err(409,"authorization_expired")
        if a["status"]!="open": err(409,"authorization_not_open")
        rem=a["amount"]-a.get("captured_amount",0)
        amount=store.validate_amount(obj.get("amount",rem))
        if amount>rem: err(422,"capture_exceeds_authorization")
        final=obj.get("final",True)
        if not isinstance(final,bool): err(422,"validation_failed")
        sender=st["users"][a["from_user_id"]]; receiver=st["users"][a["to_user_id"]]
        if sender["balance"]<amount: err(409,"insufficient_funds")
        sender["balance"]-=amount; receiver["balance"]+=amount
        p=store.make_payment(st,new_id("p"),sender["id"],receiver["id"],amount,a["note"],a["visibility"],auth_id=aid)
        st["payments"].append(p)
        a["captured_amount"]=a.get("captured_amount",0)+amount
        a["payment_id"]=p["payment_id"]; a.setdefault("payment_ids",[]).append(p["payment_id"])
        remaining=a["amount"]-a["captured_amount"]
        if final or remaining==0:
            a["status"]="captured"; a["closed_at"]=iso()
        out=store.serialize_payment(st,p)
        store.record_idem(st,u,key,"POST",f"/authorizations/{aid}/capture",obj,201,out)
        return JSONResponse(out,status_code=201)
    return store.mutate(op)

@app.post("/authorizations/{aid}/void")
async def void_authorization(aid:str,request: Request):
    require_stage(2)
    def op(st):
        u=auth_user(st,request)
        a=next((x for x in st["authorizations"] if x["authorization_id"]==aid),None)
        if a is None: err(404,"not_found")
        if a["from_user_id"]!=u["id"]: err(403,"forbidden")
        store.expire(st)
        if a["status"]=="voided": return store.serialize_auth(st,a)
        if a["status"]!="open": err(409,"authorization_not_open")
        a["status"]="voided"; a["closed_at"]=iso()
        return store.serialize_auth(st,a)
    return store.mutate(op)

@app.get("/authorizations")
async def list_authorizations(request: Request):
    require_stage(2)
    if is_html(request): return HTMLResponse(ui_html("/authorizations"))
    st=store.read(); u=auth_user(st,request); store.expire(st)
    direction=request.query_params.get("direction"); status=request.query_params.get("status")
    if direction not in (None,"incoming","outgoing"): err(422,"validation_failed")
    if status not in (None,"open","captured","voided","expired"): err(422,"validation_failed")
    limit=qint(request,"limit",50); offset=qoffset(request)
    rows=[]
    for a in st["authorizations"]:
        if u["id"] not in (a["from_user_id"],a["to_user_id"]): continue
        if direction=="outgoing" and a["from_user_id"]!=u["id"]: continue
        if direction=="incoming" and a["to_user_id"]!=u["id"]: continue
        if status and a["status"]!=status: continue
        rows.append(store.serialize_auth(st,a))
    rows.sort(key=lambda x:(ts_key(x["created_at"]),x["authorization_id"]),reverse=True)
    return {"authorizations":rows[offset:offset+limit],"has_more":offset+limit<len(rows)}
def statement_compute(st,u,from_s,to_s,limit,offset,known_at):
    f=parse_dt(from_s) if from_s else datetime.min.replace(tzinfo=timezone.utc)
    t=parse_dt(to_s) if to_s else now_dt()
    if f>t: err(422,"validation_failed")
    events=[]
    for p,r in store.payment_events(st,known_at):
        if u["id"] not in (p["from_user_id"],p["to_user_id"]):
            continue
        eff=parse_dt(r["effective_at"])
        events.append((eff,p["payment_id"],p,r))
    events.sort(key=lambda x:(x[0],x[1]))
    running=st["opening_balances"][u["id"]]
    for eff,_,p,r in events:
        if eff<f:
            running += -r["amount"] if p["from_user_id"]==u["id"] else r["amount"]
    opening=running
    all_entries=[]
    for eff,pid,p,r in events:
        if f<=eff<t:
            delta=-r["amount"] if p["from_user_id"]==u["id"] else r["amount"]
            running+=delta
            pay=store.serialize_payment(st,p).copy(); pay["amount"]=r["amount"]
            all_entries.append({"payment":pay,"delta":delta,"balance_after":running,
                "revision":r["revision"],"effective_at":r["effective_at"],"recorded_at":r["recorded_at"]})
    closing=running
    return {"opening_balance":opening,"entries":all_entries,"closing_balance":closing,
            "has_more":offset+limit<len(all_entries),
            "snapshot_range":{"from":from_s,"to":to_s,"known_at":known_at}}

@app.get("/statement")
async def get_statement(request: Request):
    require_stage(3)
    st=store.read(); u=auth_user(st,request)
    limit=qint(request,"limit",50); offset=qoffset(request)
    snap=request.query_params.get("snapshot")
    if snap:
        if any(k in request.query_params for k in ("from","to","known_at")): err(422,"validation_failed")
        data=st["snapshots"].get(snap)
        if not data or data["user_id"]!=u["id"]: err(404,"not_found")
        base=data["data"].copy()
    else:
        frm=instant_param(request,"from"); to=instant_param(request,"to"); known=instant_param(request,"known_at")
        data=statement_compute(st,u,frm,to,limit,offset,known)
        snap=new_id("snap")
        store.mutate(lambda s: s["snapshots"].__setitem__(snap,{"user_id":u["id"],"data":data}))
        base=data.copy()
    entries=base["entries"]
    out = {k:base[k] for k in ("opening_balance","closing_balance","snapshot_range")} | {
        "entries":entries[offset:offset+limit],"has_more":offset+limit<len(entries),"snapshot":snap}
    if base["snapshot_range"].get("known_at") is not None:
        out["known_at"] = base["snapshot_range"]["known_at"]
    return out

@app.get("/payments/{pid}/revisions")
async def payment_revisions(pid:str,request: Request):
    require_stage(3)
    st=store.read(); u=auth_user(st,request); p=find_payment(st,pid)
    if p is None: err(404,"not_found")
    if u["id"] not in (p["from_user_id"],p["to_user_id"]): err(404,"not_found")
    return {"revisions":p["revisions"]}

@app.post("/payments/{pid}/corrections")
async def correct_payment(pid:str,request: Request):
    require_stage(3)
    obj=await body(request)
    def op(st):
        u=auth_user(st,request)
        key=require_write_key(request)
        replay=replay_or_none(st,u,key,obj,"POST",f"/payments/{pid}/corrections")
        if replay is not None: return JSONResponse(replay,status_code=200)
        p=find_payment(st,pid)
        if p is None: err(404,"not_found")
        if p["from_user_id"]!=u["id"]: err(403,"forbidden")
        if p.get("authorization_id") or p.get("refund_of") or p.get("settlement_id"):
            err(422,"linked_payment_immutable")
        for k in ("expected_revision","amount","effective_at","reason"):
            if k not in obj: err(422,"validation_failed")
        if type(obj["expected_revision"]) is not int or obj["expected_revision"]<1:
            err(422,"validation_failed")
        amount=store.validate_amount(obj["amount"],allow_zero=True)
        try: eff=parse_dt(obj["effective_at"])
        except Exception: err(422,"validation_failed")
        if eff>now_dt() or not isinstance(obj["reason"],str) or not 1<=len(obj["reason"])<=200:
            err(422,"validation_failed")
        current=p["revisions"][-1]
        if current["revision"]!=obj["expected_revision"]: err(409,"stale_revision")
        refunded=sum(x["amount"] for x in st["payments"] if x.get("refund_of")==pid)
        if amount<refunded: err(422,"refund_exceeds_payment")
        delta=amount-current["amount"]
        held=store.held_map(st)
        if delta>0 and u["balance"]-held[u["id"]]<delta: err(409,"insufficient_funds")
        if delta<0:
            receiver=st["users"][p["to_user_id"]]
            if receiver["balance"]-held[receiver["id"]]<-delta: err(409,"insufficient_funds")
        rec_dt=now_dt()
        if parse_dt(rec_dt.isoformat())<=parse_dt(current["recorded_at"]):
            rec_dt=parse_dt(current["recorded_at"])+timedelta(microseconds=1)
        newrev={"revision":current["revision"]+1,"amount":amount,
                "effective_at":obj["effective_at"],"recorded_at":rec_dt.isoformat(),
                "reason":obj["reason"],"correction_batch_id":None}
        overrides={pid:newrev}
        if not store.check_historical_nonnegative(st,overrides): err(409,"historical_overdraft")
        sender=st["users"][p["from_user_id"]]; receiver=st["users"][p["to_user_id"]]
        sender["balance"]-=delta; receiver["balance"]+=delta
        p["revisions"].append(newrev)
        out={"payment_id":pid,"revision":newrev["revision"],"amount":newrev["amount"],
             "effective_at":newrev["effective_at"],"recorded_at":newrev["recorded_at"],
             "reason":newrev["reason"]}
        store.record_idem(st,u,key,"POST",f"/payments/{pid}/corrections",obj,201,out)
        return JSONResponse(out,status_code=201)
    return store.mutate(op)
@app.post("/payments/{pid}/refunds")
async def refund_payment(pid:str,request: Request):
    require_stage(4)
    obj=await body(request)
    def op(st):
        u=auth_user(st,request)
        key=require_write_key(request)
        replay=replay_or_none(st,u,key,obj,"POST",f"/payments/{pid}/refunds")
        if replay is not None: return JSONResponse(replay,status_code=200)
        p=find_payment(st,pid)
        if p is None: err(404,"not_found")
        if p.get("refund_of") is not None: err(422,"invalid_refund_target")
        if u["id"]!=p["to_user_id"]: err(403,"forbidden")
        amount=store.validate_amount(obj.get("amount"))
        current=p["revisions"][-1]["amount"]
        refunded=sum(x["amount"] for x in st["payments"] if x.get("refund_of")==pid)
        if refunded+amount>current: err(422,"refund_exceeds_payment")
        held=store.held_map(st)
        if u["balance"]-held[u["id"]]<amount: err(409,"insufficient_funds")
        source=u; target=st["users"][p["from_user_id"]]
        source["balance"]-=amount; target["balance"]+=amount
        rp=store.make_payment(st,new_id("p"),source["id"],target["id"],amount,p["note"],p["visibility"],refund_of=pid,created_at=iso())
        st["payments"].append(rp)
        out=store.serialize_payment(st,rp)
        store.record_idem(st,u,key,"POST",f"/payments/{pid}/refunds",obj,201,out)
        return JSONResponse(out,status_code=201)
    return store.mutate(op)
@app.post("/correction-batches")
async def correction_batch(request: Request):
    require_stage(4)
    obj=await body(request)
    def op(st):
        u=auth_user(st,request)
        key=require_write_key(request)
        replay=replay_or_none(st,u,key,obj,"POST","/correction-batches")
        if replay is not None: return JSONResponse(replay,status_code=200)
        if u["id"] not in st["settlement_operator_ids"]: err(403,"forbidden")
        items=obj.get("corrections")
        if not isinstance(items,list) or not 1<=len(items)<=32: err(422,"validation_failed")
        ids=[]
        proposed={}
        deltas={}
        settlement_groups={}
        for item in items:
            if not isinstance(item,dict): err(422,"validation_failed")
            for k in ("payment_id","expected_revision","amount","effective_at","reason"):
                if k not in item: err(422,"validation_failed")
            pid=item["payment_id"]
            if pid in ids: err(422,"validation_failed")
            ids.append(pid)
            p=find_payment(st,pid)
            if p is None: err(404,"not_found")
            if type(item["expected_revision"]) is not int or item["expected_revision"]<1:
                err(422,"validation_failed")
            amount=store.validate_amount(item["amount"],allow_zero=True)
            try: eff=parse_dt(item["effective_at"])
            except Exception: err(422,"validation_failed")
            if eff>now_dt() or not isinstance(item["reason"],str) or not 1<=len(item["reason"])<=200:
                err(422,"validation_failed")
            if p.get("authorization_id") or p.get("refund_of"):
                err(422,"linked_payment_immutable")
            current=p["revisions"][-1]
            if current["revision"]!=item["expected_revision"]: err(409,"stale_revision")
            refunded=sum(x["amount"] for x in st["payments"] if x.get("refund_of")==pid)
            if amount<refunded: err(422,"refund_exceeds_payment")
            proposed[pid]={"revision":current["revision"]+1,"amount":amount,
                "effective_at":item["effective_at"],"recorded_at":"","reason":item["reason"],
                "correction_batch_id":None}
            delta=amount-current["amount"]
            deltas[p["from_user_id"]]=deltas.get(p["from_user_id"],0)-delta
            deltas[p["to_user_id"]]=deltas.get(p["to_user_id"],0)+delta
            if p.get("settlement_id"):
                settlement_groups.setdefault(p["settlement_id"],[]).append(pid)
        for sid,pids in settlement_groups.items():
            members=[p["payment_id"] for p in st["payments"] if p.get("settlement_id")==sid]
            if set(pids)!=set(members): err(422,"incomplete_settlement")
            effs={parse_dt(proposed[x]["effective_at"]).replace(tzinfo=timezone.utc) for x in pids}
            if len(effs)!=1: err(422,"validation_failed")
        held=store.held_map(st)
        for uid,delta in deltas.items():
            if st["users"][uid]["balance"]+delta-held[uid]<0: err(409,"insufficient_funds")
        rec=now_dt()
        for p in st["payments"]:
            if p["payment_id"] in proposed:
                last=parse_dt(p["revisions"][-1]["recorded_at"])
                if rec<=last: rec=last+timedelta(microseconds=1)
        batch_id=new_id("cb")
        for pid,rv in proposed.items():
            rv["recorded_at"]=rec.isoformat(); rv["correction_batch_id"]=batch_id
        overrides=proposed
        if not store.check_historical_nonnegative(st,overrides): err(409,"historical_overdraft")
        for pid,rv in proposed.items():
            p=find_payment(st,pid); delta=rv["amount"]-p["revisions"][-1]["amount"]
            st["users"][p["from_user_id"]]["balance"]-=delta
            st["users"][p["to_user_id"]]["balance"]+=delta
            p["revisions"].append(rv)
        revisions=[{"payment_id":pid,"revision":rv["revision"],"amount":rv["amount"],
                    "effective_at":rv["effective_at"],"recorded_at":rv["recorded_at"],
                    "reason":rv["reason"],"correction_batch_id":batch_id} for pid,rv in proposed.items()]
        out={"correction_batch_id":batch_id,"recorded_at":rec.isoformat(),"revisions":revisions}
        store.record_idem(st,u,key,"POST","/correction-batches",obj,201,out)
        return JSONResponse(out,status_code=201)
    return store.mutate(op)

def ui_html(route="/"):
    page = json.dumps(route)
    return """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pocketful</title>
<style>
:root{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#16202a;background:#f4f1eb}
*{box-sizing:border-box}body{margin:0}.shell{min-height:100vh}.nav{position:sticky;top:0;z-index:5;background:#fffdf9;border-bottom:1px solid #e4ded4}
.navin{max-width:1160px;margin:auto;padding:14px 20px;display:flex;gap:18px;align-items:center;justify-content:space-between}
.brand{font-weight:850;letter-spacing:-.03em}.links{display:flex;gap:8px;flex-wrap:wrap}.links a{color:#45515c;text-decoration:none;padding:8px 10px;border-radius:10px}.links a:hover{background:#eee8df}
.userbar{display:flex;gap:8px;align-items:center;font-size:13px}.chip{background:#eee8df;border-radius:999px;padding:7px 10px}
main{max-width:1160px;margin:auto;padding:28px 20px 60px}.grid{display:grid;grid-template-columns:1.3fr .7fr;gap:18px}@media(max-width:850px){.grid{grid-template-columns:1fr}}
.card{background:#fffdf9;border:1px solid #ded7cc;border-radius:22px;padding:22px;box-shadow:0 14px 40px rgba(55,45,30,.06)}
h1{font-size:42px;line-height:1.03;letter-spacing:-.04em;margin:0 0 10px}h2{font-size:18px;margin:0 0 15px}.muted{color:#68737c}.balance{font-size:42px;font-weight:820;letter-spacing:-.04em}.secondary{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px}.metric{background:#f1ece4;border-radius:14px;padding:11px 13px}.metric strong{display:block;font-size:18px}.metric span{font-size:11px;color:#6e777e}
form{display:grid;gap:12px}label{font-size:12px;font-weight:700;color:#5f686f}input,select,textarea,button{width:100%;font:inherit;border:1px solid #cfc7bb;border-radius:12px;padding:12px;background:#fffdf9;color:#16202a}button{cursor:pointer;background:#1e2a2f;color:#fff;border-color:#1e2a2f;font-weight:760}button.secondarybtn{background:#eee8df;color:#253039;border-color:#d8d0c6}
.row{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;padding:12px 0;border-bottom:1px solid #ece6de}.pill{font-size:11px;padding:5px 8px;border-radius:999px;background:#ece7de}.ok{color:#226d4a}.err{color:#a13333}.uncertain{color:#8b5a12}.small{font-size:12px;color:#67727a}
.panel{display:grid;gap:12px}.empty{padding:24px;border:1px dashed #d8d0c6;border-radius:14px;color:#71808a;text-align:center}
.sharegrid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}@media(max-width:700px){.sharegrid{grid-template-columns:1fr 1fr}}
.errorbox{padding:10px 12px;border-radius:11px;background:#fff0ee;color:#9b2e2e}.uncertainbox{padding:10px 12px;border-radius:11px;background:#fff7df;color:#825707}
.authhead{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-bottom:16px}
</style></head><body><div class="shell">
<div class="nav"><div class="navin">
<a href="/" style="text-decoration:none;color:inherit"><div class="brand">Pocketful</div></a>
<div class="links"><a href="/">Wallet</a><a href="/requests">Requests</a><a href="/split">Split</a>__RESERVE_LINK__</div>
<div id="userbar" class="userbar"></div>
</div></div>
<main id="app"></main>
</div>
<script>
const ROUTE = __ROUTE__;
const app = document.getElementById("app");
const tokenKey = "pocketful-token";
let refreshSeq=0;
let paySig="";
let payKey=crypto.randomUUID();
let paySubmitting=false;
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>{switch(c){case "&":return "&amp;";case "<":return "&lt;";case ">":return "&gt;";case '"':return "&quot;";case "'":return "&#39;";default:return c;}});
function money(minor,mu,curr){if(mu===0)return minor+" "+curr;let s=String(Math.abs(minor)).padStart(mu+1,"0");return (minor<0?"-":"")+s.slice(0,-mu)+"."+s.slice(-mu)+" "+curr}
function tok(){return localStorage.getItem(tokenKey)||""}
async function api(path,opts={}){const h=new Headers(opts.headers||{});h.set("Accept","application/json");if(!(opts.body instanceof FormData)&&opts.body!==undefined)h.set("Content-Type","application/json");if(tok())h.set("Authorization","Bearer "+tok());return fetch(path,{...opts,headers:h})}
async function j(resp){try{return await resp.json()}catch{return {}}}
function setUserBar(me){const b=document.getElementById("userbar");if(!b)return;if(!me){b.innerHTML='<a href="/login">Login</a><a href="/signup">Sign up</a>';return}b.innerHTML='<span class="chip"><span data-testid="current-user">'+esc(me.display_name)+'</span> · <span data-testid="current-handle">'+esc(me.handle)+'</span></span><button id="logout-button" data-testid="logout-button" class="secondarybtn" style="width:auto">Log out</button>';document.getElementById("logout-button").onclick=()=>{localStorage.removeItem(tokenKey);location.href="/login"}}
function mustAuth(){if(!tok()){location.href="/login";return false}return true}
async function loadMe(){if(!tok()){setUserBar(null);return null}const r=await api("/me");if(!r.ok){localStorage.removeItem(tokenKey);setUserBar(null);return null}const me=await j(r);setUserBar(me);return me}
function decimalToMinor(raw,mu){const s=String(raw).trim();if(!/^\d+(\.\d+)?$/.test(s))throw new Error("Enter a valid amount");const parts=s.split(".");const dec=parts[1]||"";if(dec.length>mu)throw new Error("Too many decimal places");return Number(parts[0])*10**mu+Number((dec+"0".repeat(mu)).slice(0,mu)||0)}
function payBody(){return {to_handle:document.getElementById("pay-handle").value,amount:decimalToMinor(document.getElementById("pay-amount").value,currentMu),note:document.getElementById("pay-note").value,visibility:document.getElementById("pay-visibility").value}}
function sig(v){return JSON.stringify(v)}
function ensurePayKey(s){if(paySig!==s){paySig=s;payKey=crypto.randomUUID()}}
function payBox(testid, cls){let x=document.querySelector('[data-testid="'+testid+'"]');if(!x){x=document.createElement('div');x.dataset.testid=testid;x.className=cls;document.getElementById('pay-form').appendChild(x)}return x}
function dropPayBox(testid){document.querySelector('[data-testid="'+testid+'"]')?.remove()}
async function refreshWallet(){if(!mustAuth())return;const seq=++refreshSeq;const [mr,ar]=await Promise.all([api("/me"),api("/activity?limit=200")]);const [me,activity]=await Promise.all([j(mr),j(ar)]);if(seq!==refreshSeq)return;renderWalletData(me,activity)}
function renderWalletData(me,activity){const bal=document.querySelector('[data-testid="wallet-balance"]');if(bal){bal.textContent=money(me.total??me.balance,me.minor_units,me.currency);bal.dataset.amount=String(me.total??me.balance)}const av=document.querySelector('[data-testid="wallet-available"]');if(av){av.textContent=money(me.available,me.minor_units,me.currency);av.dataset.amount=String(me.available)}let held=document.querySelector('[data-testid="wallet-held"]');const sec=document.querySelector('[data-testid="wallet-available"]')?.parentElement;if(me.held>0 && !held && sec){sec.insertAdjacentHTML("beforeend",'<div class="metric"><strong data-testid="wallet-held"></strong><span>Held</span></div>');held=document.querySelector('[data-testid="wallet-held"]')}if(me.held===0&&held){held.parentElement.remove()}if(held){held.textContent=money(me.held,me.minor_units,me.currency);held.dataset.amount=String(me.held)}const list=document.querySelector('[data-testid="activity-list"]');const empty=document.querySelector('[data-testid="empty-activity"]');if(list){list.innerHTML=(activity.payments||[]).map(p=>'<div class="row" data-testid="activity-item-'+esc(p.payment_id)+'" data-visibility="'+esc(p.visibility)+'"><div><div data-testid="activity-parties-'+esc(p.payment_id)+'">'+esc(p.from_handle)+' → '+esc(p.to_handle)+'</div><div class="small" data-testid="activity-note-'+esc(p.payment_id)+'">'+esc(p.note||"")+'</div></div><div><strong data-testid="activity-amount-'+esc(p.payment_id)+'">'+esc(money(p.amount,me.minor_units,me.currency))+'</strong><div class="small">'+esc(p.visibility)+'</div></div></div>').join("");if(empty)empty.style.display=(activity.payments||[]).length?"none":""}}

function walletView(){return '<div class="grid"><section class="card"><div class="authhead"><div><h1>Move money with confidence.</h1><div class="muted">Available funds are always explicit; every write is retry-safe.</div></div></div><div data-testid="wallet-balance" class="balance" data-amount="0">—</div><div class="secondary"><div class="metric"><strong data-testid="wallet-available">—</strong><span>Available</span></div><div class="metric" id="heldbox" style="display:none"><strong data-testid="wallet-held">—</strong><span>Held</span></div></div><div style="margin-top:15px"><button id="wallet-refresh" data-testid="wallet-refresh" class="secondarybtn">Refresh balance & feed</button></div></section><section class="card"><h2>Send money</h2><form id="pay-form"><label>Recipient handle<input data-testid="pay-handle" id="pay-handle"></label><label>Amount<input data-testid="pay-amount" id="pay-amount" inputmode="decimal" value="15.00"></label><label>Note<textarea data-testid="pay-note" id="pay-note" rows="2"></textarea></label><label>Visibility<select data-testid="pay-visibility" id="pay-visibility"><option value="public">Public</option><option value="private">Private</option></select></label><button type="submit" data-testid="pay-submit">Send</button></form></section></div><section class="card" style="margin-top:18px"><div class="authhead"><h2>Activity</h2><span class="pill">Newest first</span></div><div id="activity-list" data-testid="activity-list"></div><div id="empty-activity" data-testid="empty-activity" class="empty">No visible payments yet.</div></section>'}
function requestForm(){return '<section class="card"><h2>Request money</h2><form id="request-form"><label>Payer handle<input id="request-handle" data-testid="request-handle"></label><label>Amount<input id="request-amount" data-testid="request-amount" inputmode="decimal" value="12.00"></label><label>Note<textarea id="request-note" data-testid="request-note" rows="2"></textarea></label><button id="request-submit" data-testid="request-submit">Request</button><div id="request-error" data-testid="request-error" class="errorbox" style="display:none"></div></form></section>'}
function splitView(){return '<section class="card"><h2>Split a bill</h2><form id="split-form"><label>Total<input id="split-amount" data-testid="split-amount" inputmode="decimal" value="10.00"></label><label>Handles, in order<input id="split-handles" data-testid="split-handles" placeholder="ada,bob,cy"></label><label>Note<textarea id="split-note" data-testid="split-note" rows="2"></textarea></label><div id="split-preview" data-testid="split-preview" class="panel"></div><button id="split-submit" data-testid="split-submit">Create split</button><div id="split-error" data-testid="split-error" class="errorbox" style="display:none"></div></form></section>'}
function renderRequestsPage(){app.innerHTML='<div class="grid">'+requestForm()+'<section class="card"><h2>What is here</h2><div class="muted">Incoming and outgoing requests are scoped to you.</div></section></div><section class="card" style="margin-top:18px"><div class="grid"><div><h2>Incoming</h2><div data-testid="incoming-list" id="incoming-list"></div></div><div><h2>Outgoing</h2><div data-testid="outgoing-list" id="outgoing-list"></div></div></div><div data-testid="empty-requests" id="empty-requests" class="empty" style="display:none">No requests.</div><div data-testid="request-error" id="request-error" class="errorbox" style="display:none"></div></section>';wireRequestCreate();loadRequests()}
function loadRequests(){api("/requests?limit=200").then(j).then(data=>{const inc=document.getElementById("incoming-list"),out=document.getElementById("outgoing-list");let incoming=[],outgoing=[];(data.requests||[]).forEach(r=>{if(r.payer_handle===window.currentHandle)incoming.push(r);else outgoing.push(r)});inc.innerHTML=incoming.map(requestRow).join("")||'<div class="small">None</div>';out.innerHTML=outgoing.map(requestRow).join("")||'<div class="small">None</div>';document.getElementById("empty-requests").style.display=(data.requests||[]).length?"none":"";wireRequestButtons()})}
function requestRow(r){let b='';if(r.status==="pending"&&r.payer_handle===window.currentHandle)b='<button class="secondarybtn" data-action="pay" data-rid="'+esc(r.request_id)+'" data-testid="request-pay-'+esc(r.request_id)+'">Pay</button><button class="secondarybtn" data-action="decline" data-rid="'+esc(r.request_id)+'" data-testid="request-decline-'+esc(r.request_id)+'">Decline</button>';if(r.status==="pending"&&r.requester_handle===window.currentHandle)b='<button class="secondarybtn" data-action="cancel" data-rid="'+esc(r.request_id)+'" data-testid="request-cancel-'+esc(r.request_id)+'">Cancel</button>';return '<div class="row" data-status="'+esc(r.status)+'" data-testid="request-item-'+esc(r.request_id)+'"><div><strong>'+esc(r.requester_handle)+' → '+esc(r.payer_handle)+'</strong><div class="small">'+esc(r.note||"")+'</div></div><div><strong data-testid="request-amount-'+esc(r.request_id)+'">'+esc(money(r.amount,window.currentMu,window.currentCurrency))+'</strong><div>'+b+'</div></div></div>'}

function wireRequestCreate(){const f=document.getElementById("request-form");f.onsubmit=async e=>{e.preventDefault();const errbox=document.getElementById("request-error");errbox.style.display="none";try{const body={payer_handle:document.getElementById("request-handle").value,amount:decimalToMinor(document.getElementById("request-amount").value,window.currentMu),note:document.getElementById("request-note").value};const r=await api("/requests",{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify(body)});if(!r.ok){const d=await j(r);throw new Error(d.error?.message||d.error?.code||"Request refused")}await loadRequests()}catch(ex){errbox.textContent=ex.message;errbox.style.display=""}}}
function wireRequestButtons(){document.querySelectorAll("[data-action]").forEach(b=>b.onclick=async()=>{const action=b.dataset.action;const rid=b.dataset.rid;const box=document.getElementById("request-error");box.style.display="none";let opts={method:"POST"};if(action==="pay"){opts.headers={"Idempotency-Key":crypto.randomUUID(),"Content-Type":"application/json"};opts.body=JSON.stringify({})}const r=await api("/requests/"+rid+"/"+action,opts);if(!r.ok){const d=await j(r);box.textContent=d.error?.message||d.error?.code||"Action refused";box.style.display=""}await loadRequests()})}
function renderSplit(){app.innerHTML=splitView();const a=document.getElementById("split-amount"),h=document.getElementById("split-handles");const update=()=>{const box=document.getElementById("split-preview");try{const handles=h.value.split(",").map(x=>x.trim()).filter(Boolean);if(!handles.length){box.innerHTML='<div class="small">Add participant handles.</div>';return}const amount=decimalToMinor(a.value,window.currentMu);const shares=equalSplitClient(amount,handles.length);box.innerHTML='<div class="small">Preview</div><div class="sharegrid">'+handles.map((x,i)=>'<div class="metric"><strong data-testid="split-share-'+esc(x)+'">'+esc(money(shares[i],window.currentMu,window.currentCurrency))+'</strong><span data-testid="split-share-label-'+esc(x)+'">'+esc(x)+'</span></div>').join("")+'</div>'}catch(ex){box.innerHTML='<div class="small">'+esc(ex.message)+'</div>'}};a.oninput=update;h.oninput=update;update();document.getElementById("split-form").onsubmit=async e=>{e.preventDefault();const er=document.getElementById("split-error");er.style.display="none";try{const handles=h.value.split(",").map(x=>x.trim()).filter(Boolean);const body={amount:decimalToMinor(a.value,window.currentMu),participant_handles:handles,note:document.getElementById("split-note").value};const r=await api("/splits",{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify(body)});if(!r.ok){const d=await j(r);throw new Error(d.error?.message||d.error?.code||"Split refused")}update()}catch(ex){er.textContent=ex.message;er.style.display=""}}}
function equalSplitClient(amount,n){const base=Math.floor(amount/n),rem=amount%n;return Array.from({length:n},(_,i)=>base+(i<rem?1:0))}

function authView(){return '<section class="card"><h2>Reserve money</h2><form id="auth-form"><label>Recipient<input id="authorize-handle" data-testid="authorize-handle"></label><label>Amount<input id="authorize-amount" data-testid="authorize-amount" inputmode="decimal" value="20.00"></label><label>Note<textarea id="authorize-note" data-testid="authorize-note" rows="2"></textarea></label><label>Visibility<select id="authorize-visibility" data-testid="authorize-visibility"><option value="public">Public</option><option value="private">Private</option></select></label><button id="authorize-submit" data-testid="authorize-submit">Reserve</button><div id="authorize-error" data-testid="authorize-error" class="errorbox" style="display:none"></div></form></section><section class="card" style="margin-top:18px"><h2>Authorizations</h2><div id="authorization-list" data-testid="authorization-list"></div><div id="authorization-error" data-testid="authorization-error" class="errorbox" style="display:none"></div><div id="empty-authorizations" data-testid="empty-authorizations" class="empty" style="display:none">None.</div></section>'}
function renderAuth(){app.innerHTML=authView();document.getElementById("auth-form").onsubmit=async e=>{e.preventDefault();const er=document.getElementById("authorize-error");er.style.display="none";try{const body={to_handle:document.getElementById("authorize-handle").value,amount:decimalToMinor(document.getElementById("authorize-amount").value,window.currentMu),note:document.getElementById("authorize-note").value,visibility:document.getElementById("authorize-visibility").value};const r=await api("/authorizations",{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID(),"Content-Type":"application/json"},body:JSON.stringify(body)});if(!r.ok){const d=await j(r);throw new Error(d.error?.code||"Reserve refused")}loadAuths();refreshWallet()}catch(ex){er.textContent=ex.message;er.style.display=""}};loadAuths()}

function authFormsPage(kind){app.innerHTML='<section class="card" style="max-width:520px;margin:auto"><h1>'+ (kind==="signup"?"Join Pocketful":"Welcome back") +'</h1><p class="muted">A clean consumer-finance surface with retry-safe writes.</p><form id="auth-form">'+(kind==="signup"?'<label>Email<input id="signup-email" data-testid="signup-email"></label><label>Password<input id="signup-password" data-testid="signup-password" type="password"></label><label>Display name<input id="signup-display-name" data-testid="signup-display-name"></label>':'<label>Email<input id="login-email" data-testid="login-email"></label><label>Password<input id="login-password" data-testid="login-password" type="password"></label>')+'<button data-testid="'+(kind==="signup"?"signup-submit":"login-submit")+'">'+(kind==="signup"?"Create account":"Log in")+'</button><div id="auth-error" data-testid="auth-error" class="errorbox" style="display:none"></div></form></section>';document.getElementById("auth-form").onsubmit=async e=>{e.preventDefault();const er=document.getElementById("auth-error");er.style.display="none";const obj=kind==="signup"?{email:document.getElementById("signup-email").value,password:document.getElementById("signup-password").value,display_name:document.getElementById("signup-display-name").value}:{email:document.getElementById("login-email").value,password:document.getElementById("login-password").value};const r=await fetch(kind==="signup"?"/auth/signup":"/auth/login",{method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},body:JSON.stringify(obj)});const d=await j(r);if(!r.ok){er.textContent=d.error?.code||d.error?.message||"Authentication failed";er.style.display="";return}localStorage.setItem(tokenKey,d.token);location.href="/"}}

async function loadAuths(){
 const r=await api("/authorizations?limit=200"); const data=await j(r);
 const list=document.getElementById("authorization-list"); if(!list)return;
 list.innerHTML=(data.authorizations||[]).map(a=>{
   let actions="";
   if(a.status==="open"&&a.to_handle===window.currentHandle){
     actions='<input data-testid="authorization-capture-amount-'+esc(a.authorization_id)+'" value="'+esc((a.remaining_amount/10**window.currentMu).toFixed(window.currentMu))+'"><button data-cap="'+esc(a.authorization_id)+'" data-testid="authorization-capture-'+esc(a.authorization_id)+'">Capture</button>';
   }
   if(a.status==="open"&&a.from_handle===window.currentHandle){
     actions+='<button data-void="'+esc(a.authorization_id)+'" data-testid="authorization-void-'+esc(a.authorization_id)+'">Void</button>';
   }
   const cap=a.status==="captured"?'<div data-testid="authorization-captured-'+esc(a.authorization_id)+'">'+esc(money(a.captured_amount,window.currentMu,window.currentCurrency))+'</div>':"";
   return '<div class="row" data-status="'+esc(a.status)+'" data-testid="authorization-item-'+esc(a.authorization_id)+'"><div><strong>'+esc(a.from_handle)+' → '+esc(a.to_handle)+'</strong><div class="small">'+esc(a.status)+'</div>'+cap+'</div><div><strong data-testid="authorization-amount-'+esc(a.authorization_id)+'">'+esc(money(a.amount,window.currentMu,window.currentCurrency))+'</strong><div data-testid="authorization-expires-'+esc(a.authorization_id)+'">'+esc(a.expires_at)+'</div><div>'+actions+'</div></div></div>'
 }).join("");
 document.getElementById("empty-authorizations").style.display=(data.authorizations||[]).length?"none":"";
 document.querySelectorAll("[data-cap]").forEach(b=>b.onclick=async()=>{
   const er=document.getElementById("authorization-error"); er.style.display="none";
   const id=b.dataset.cap; const inp=document.querySelector('[data-testid="authorization-capture-amount-'+CSS.escape(id)+'"]');
   try{
     const r=await api("/authorizations/"+id+"/capture",{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID(),"Content-Type":"application/json"},body:JSON.stringify({amount:decimalToMinor(inp.value,window.currentMu)})});
     if(!r.ok){const d=await j(r);throw new Error(d.error?.code||"Capture refused")}
   }catch(ex){er.textContent=ex.message;er.style.display=""}
   loadAuths(); refreshWallet();
 });
 document.querySelectorAll("[data-void]").forEach(b=>b.onclick=async()=>{
   const er=document.getElementById("authorization-error");er.style.display="none";
   const r=await api("/authorizations/"+b.dataset.void+"/void",{method:"POST"});
   if(!r.ok){const d=await j(r);er.textContent=d.error?.code||"Void refused";er.style.display=""}
   loadAuths();refreshWallet();
 });
}

async function render(){if(ROUTE==="/login"){setUserBar(null);authFormsPage("login");return}if(ROUTE==="/signup"){setUserBar(null);authFormsPage("signup");return}const me=await loadMe();window.currentUser=me;window.currentHandle=me?.handle||"";window.currentMu=me?.minor_units??2;window.currentCurrency=me?.currency||"EUR";if(!me){location.href="/login";return}if(ROUTE==="/"){app.innerHTML=walletView()+requestForm();wireRequestCreate();document.getElementById("wallet-refresh").onclick=refreshWallet;document.getElementById("pay-form").onsubmit=async e=>{e.preventDefault();dropPayBox("pay-error");dropPayBox("pay-uncertain");try{const body=payBody();const s=sig(body);ensurePayKey(s);paySubmitting=true;const r=await api("/payments",{method:"POST",headers:{"Idempotency-Key":payKey},body:JSON.stringify(body)});const d=await j(r);if(!r.ok)throw new Error(d.error?.code||d.error?.message||"Payment refused");await refreshWallet();paySubmitting=false}catch(ex){paySubmitting=false;if(ex instanceof TypeError){const un=payBox("pay-uncertain","uncertainbox");un.textContent="The outcome is uncertain. Retry this same form without changing a field."}else{const er=payBox("pay-error","errorbox");er.textContent=ex.message}}};
await refreshWallet();return}if(ROUTE==="/requests"){renderRequestsPage();return}if(ROUTE==="/split"){renderSplit();return}if(ROUTE==="/authorizations"){renderAuth();return}}
render();
</script></body></html>""".replace("__ROUTE__", page).replace(
        "__RESERVE_LINK__", '<a href="/authorizations">Reserve</a>' if STAGE>=2 else "")

@app.get("/", response_class=HTMLResponse)
async def root_page():
    return HTMLResponse(ui_html("/"))

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(ui_html("/login"))

@app.get("/signup", response_class=HTMLResponse)
async def signup_page():
    return HTMLResponse(ui_html("/signup"))

@app.get("/split", response_class=HTMLResponse)
async def split_page():
    return HTMLResponse(ui_html("/split"))


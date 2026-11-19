"""Loopback-only Zhiyu prototype. Python 3.10+, standard library."""
import argparse, hashlib, json, os, re, secrets, sqlite3, time
from contextlib import closing
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from fixtures import EXAMPLE, SOURCES, rank

ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get("ZHIYU_DB", ROOT/"var"/"zhiyu.sqlite3"))
def uid(): return secrets.token_urlsafe(18)
def pack(x): return json.dumps(x,ensure_ascii=False,separators=(",",":"))
def init():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(DB)) as c, c:
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,owner TEXT NOT NULL,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,pid TEXT,rid TEXT,data TEXT,UNIQUE(pid,rid));
        CREATE TABLE IF NOT EXISTS cards(slug TEXT PRIMARY KEY,pid TEXT,version INTEGER,signature TEXT,data TEXT,active INTEGER DEFAULT 1,UNIQUE(pid,version));
        CREATE TABLE IF NOT EXISTS visits(slug TEXT,reader TEXT,opened INTEGER DEFAULT 0,PRIMARY KEY(slug,reader));
        CREATE TABLE IF NOT EXISTS feedback(slug TEXT,reader TEXT,sid TEXT,status TEXT,step TEXT,note TEXT,at INTEGER,PRIMARY KEY(slug,reader),UNIQUE(slug,sid));
        CREATE TABLE IF NOT EXISTS limits(k TEXT PRIMARY KEY,window INTEGER,n INTEGER);
        """)
class Problem(Exception):
    def __init__(self,code,msg):self.code=code;self.msg=msg
def ck(v,code,msg):
    if not v: raise Problem(code,msg)
def fields(b,keys,maxlen=2000,optional=()):
    out={}
    for k in keys:
        v=b.get(k,"");ck(isinstance(v,str) and len(v.strip())<=maxlen and (v.strip() or k in optional),400,"请检查字段："+k)
        out[k]=v.strip()
    return out
def tool_url(v):
    if v=="/sample": return
    try:
        u=urlsplit(v);valid=u.scheme in ("http","https") and u.hostname and not u.username and not u.password and not any(ord(c)<33 or c in '<>"\\' for c in v)
    except ValueError: valid=False
    ck(valid,400,"工具入口须为 http(s) 链接，或保留本机示例 /sample。")
class Handler(BaseHTTPRequestHandler):
    server_version="ZhiyuLocal/1"
    def log_message(self,*args): pass
    def respond(self,code,data,typ="application/json; charset=utf-8"):
        raw=pack(data).encode() if typ.startswith("application/json") else data
        self.send_response(code);self.send_header("Content-Type",typ);self.send_header("Content-Length",str(len(raw)))
        self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        for v in self.pending:self.send_header("Set-Cookie",v)
        self.end_headers();self.wfile.write(raw)
    def ident(self,key,new=False):
        name="zhiyu_"+key
        jar=SimpleCookie();jar.load(self.headers.get("Cookie",""));m=jar.get(name);v=m.value if m else ""
        if re.fullmatch(r"[A-Za-z0-9_-]{32,64}",v):return v
        ck(new,403,"会话已失效，请刷新后重试。")
        v=secrets.token_urlsafe(32);self.pending.append(f"{name}={v}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000");return v
    def own(self,c,pid):
        r=c.execute("SELECT data FROM projects WHERE id=? AND owner=?",(pid,self.ident("dev"))).fetchone()
        ck(r,404,"项目不存在或不属于当前工作区。");return json.loads(r[0])
    def card(self,c,slug):
        r=c.execute("SELECT data FROM cards WHERE slug=? AND active=1",(slug,)).fetchone()
        ck(r,404,"试用卡不存在或已撤回。");return json.loads(r[0])
    def limit(self,c):
        now=int(time.time())//60;k=self.client_address[0]
        c.execute("INSERT INTO limits VALUES(?,?,1) ON CONFLICT(k) DO UPDATE SET n=CASE WHEN window=excluded.window THEN n+1 ELSE 1 END,window=excluded.window",(k,now))
        ck(c.execute("SELECT n FROM limits WHERE k=?",(k,)).fetchone()[0]<=100,429,"提交过于频繁，请稍后重试。")
    def handle_req(self,post=False):
        self.pending=[]
        try:
            host=self.headers.get("Host","")
            ck(host in (f"localhost:{self.server.server_port}",f"127.0.0.1:{self.server.server_port}"),403,"仅支持本机访问。")
            path=urlsplit(self.path).path
            b={}
            if post:
                origin=self.headers.get("Origin");ck(not origin or origin=="http://"+host,403,"来源不匹配。")
                ck(self.headers.get_content_type()=="application/json",415,"需要 JSON 请求。")
                n=int(self.headers.get("Content-Length","0"));ck(0<n<=24000,413,"请求内容过大或为空。");b=json.loads(self.rfile.read(n));ck(isinstance(b,dict),400,"请求格式不正确。")
            elif not path.startswith("/api/"):
                static={"/styles.css":("styles.css","text/css"),"/app.js":("app.js","text/javascript"),"/mark.svg":("mark.svg","image/svg+xml")}
                if path in static: name,typ=static[path]
                else:
                    ck(path in ["/","/sample"] or re.fullmatch(r"/(?:t|source)/[A-Za-z0-9_-]+",path),404,"页面不存在。")
                    name,typ="index.html","text/html"
                return self.respond(200,(ROOT/name).read_bytes(),typ+"; charset=utf-8")
            with closing(sqlite3.connect(DB,timeout=8)) as c, c:
                if post: c.execute("BEGIN IMMEDIATE")
                data=self.api(c,path,b,post)
            self.respond(200,data)
        except Problem as e: self.respond(e.code,{"error":e.msg})
        except (ValueError,UnicodeError): self.respond(400,{"error":"请求格式不正确。"})
        except (sqlite3.Error,OSError):self.respond(503,{"error":"本地存储暂不可用，请稍后重试。"})
    def api(self,c,path,b,post):
        seg=path.strip("/").split("/");m="POST" if post else "GET"
        if path=="/api/workspace" and not post:
            owner=self.ident("dev",True)
            projects=[dict(projectId=r[0],**json.loads(r[1])) for r in c.execute("SELECT id,data FROM projects WHERE owner=? ORDER BY rowid DESC",(owner,))]
            return dict(projects=projects,example=EXAMPLE,mode="synthetic",liveStatus="not_configured")
        if path=="/api/projects" and post:
            p=fields(b,EXAMPLE.keys(),optional=("limits",));tool_url(p["url"]);owner=self.ident("dev");pid=b.get("projectId")
            if pid:self.own(c,pid);c.execute("UPDATE projects SET data=? WHERE id=?",(pack(p),pid))
            else:pid=uid();c.execute("INSERT INTO projects VALUES(?,?,?)",(pid,owner,pack(p)))
            return dict(projectId=pid,**p)
        if len(seg)>=3 and seg[:2]==["api","projects"]:
            pid=seg[2];p=self.own(c,pid)
            if len(seg)==3 and not post:
                r=c.execute("SELECT data FROM runs WHERE pid=? ORDER BY rowid DESC LIMIT 1",(pid,)).fetchone()
                cards=[dict(**json.loads(d),active=bool(a)) for d,a in c.execute("SELECT data,active FROM cards WHERE pid=? ORDER BY version DESC",(pid,))]
                return dict(project=p,run=json.loads(r[0]) if r else None,cards=cards)
            if seg[3:]==["runs"] and post:
                rid=fields(b,["requestId"],100)["requestId"];r=c.execute("SELECT data FROM runs WHERE pid=? AND rid=?",(pid,rid)).fetchone()
                if r:return json.loads(r[0])
                mode=b.get("mode","synthetic");ck(mode in ("synthetic","live"),400,"未知模式。")
                items=rank(p) if mode=="synthetic" else []
                r=dict(runId=uid(),requestId=rid,mode=mode,status=("success" if items else "empty") if mode=="synthetic" else "failed",errorCode=None if mode=="synthetic" else "not_configured",candidates=items,projectSnapshot=p)
                c.execute("INSERT INTO runs VALUES(?,?,?,?)",(r["runId"],pid,rid,pack(r)));return r
            if len(seg)==5 and seg[3]=="runs" and not post:
                r=c.execute("SELECT data FROM runs WHERE id=? AND pid=?",(seg[4],pid)).fetchone();ck(r,404,"找不到匹配记录。");return json.loads(r[0])
            if seg[3:]==["publish"] and post:
                d=fields(b,["runId","candidateId","title","material","steps","criterion","question"])
                r=c.execute("SELECT data FROM runs WHERE id=? AND pid=?",(d["runId"],pid)).fetchone()
                ck(r,400,"无效的匹配记录。");run=json.loads(r[0])
                ck(run["projectSnapshot"]==p,409,"工具登记已变更，请重新匹配后发布。")
                selected=next((x for x in run["candidates"] if x["id"]==d["candidateId"] and x["judgment"]=="适配"),None)
                ck(selected,400,"只能发布有明确依据的适配场景。")
                signature=hashlib.sha256(pack([d,p]).encode()).hexdigest()
                last=c.execute("SELECT version,signature,data,active FROM cards WHERE pid=? ORDER BY version DESC LIMIT 1",(pid,)).fetchone()
                if last and last[1]==signature and last[3]:return json.loads(last[2])
                snap={k:d[k] for k in ("title","material","steps","criterion","question")}
                snap.update(slug=uid(),version=1+(last[0] if last else 0),tool=p["name"],url=p["url"],scene=selected["title"],mode=run["mode"])
                c.execute("INSERT INTO cards(slug,pid,version,signature,data) VALUES(?,?,?,?,?)",(snap["slug"],pid,snap["version"],signature,pack(snap)));return snap
            if len(seg)==5 and seg[3]=="withdraw" and post:
                q=c.execute("UPDATE cards SET active=0 WHERE pid=? AND slug=?",(pid,seg[4]));ck(q.rowcount,404,"卡片不存在。");return dict(ok=True)
            if seg[3:]==["results"] and not post:
                blocks=[]
                for slug,v in c.execute("SELECT slug,version FROM cards WHERE pid=? ORDER BY version DESC",(pid,)):
                    visits,opened=c.execute("SELECT count(*),coalesce(sum(opened),0) FROM visits WHERE slug=?",(slug,)).fetchone()
                    rows=[dict(status=s,step=t,note=n,at=a) for s,t,n,a in c.execute("SELECT status,step,note,at FROM feedback WHERE slug=? ORDER BY at DESC,rowid DESC",(slug,))]
                    blocks.append(dict(slug=slug,version=v,visits=visits,opened=opened,completed=sum(x["status"]=="done" for x in rows),feedback=rows))
                return dict(versions=blocks)
        if len(seg)==3 and seg[:2]==["api","sources"] and not post:
            s=next((s for s in SOURCES if s["id"]==seg[2]),None);ck(s,404,"样例不存在。");return {k:s[k] for k in ["title","body","evidence","author"]}
        if len(seg)>=3 and seg[:2]==["api","cards"]:
            slug=seg[2];card=self.card(c,slug)
            if len(seg)==3 and not post:
                self.ident("reader",True);return card
            if post and seg[3:] in (["visit"],["open"],["feedback"]):
                reader=self.ident("reader");ck(type(b.get("version")) is int and b["version"]==card["version"],409,"卡片版本不匹配。")
                self.limit(c);c.execute("INSERT OR IGNORE INTO visits(slug,reader) VALUES(?,?)",(slug,reader))
                if seg[3]=="open":c.execute("UPDATE visits SET opened=1 WHERE slug=? AND reader=?",(slug,reader))
                if seg[3]=="feedback":
                    f=fields(b,["submissionId","status","step","note"],1000,optional=("step",))
                    ck(f["status"] in ("done","blocked") and (f["status"]=="done" or f["step"]),400,"请注明卡住的步骤。")
                    c.execute("INSERT OR IGNORE INTO feedback VALUES(?,?,?,?,?,?,?)",(slug,reader,f["submissionId"],f["status"],f["step"],f["note"],int(time.time())))
                rr=c.execute("SELECT sid,status FROM feedback WHERE slug=? AND reader=?",(slug,reader)).fetchone()
                if seg[3]=="feedback":ck(rr,409,"提交 ID 已使用，请刷新后重试。")
                return dict(receipt=dict(submissionId=rr[0],status=rr[1]) if rr else None)
        raise Problem(404,"接口不存在。")
    def do_GET(self): self.handle_req()
    def do_POST(self): self.handle_req(True)
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--port",type=int,default=4173);parser.add_argument("--open",action="store_true");args=parser.parse_args()
    init()
    try:server=ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    except OSError as e:
        if args.open:
            import urllib.request, webbrowser
            try:
                base=f"http://127.0.0.1:{args.port}"
                with urllib.request.urlopen(base+"/api/workspace",timeout=2) as r: same=json.load(r).get("example")==EXAMPLE
                if same:webbrowser.open(base);raise SystemExit(0)
            except (OSError,ValueError):pass
        raise SystemExit(f"Port unavailable: {e}. Choose --port 4180.")
    if args.open:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{server.server_port}/")
    print(f"Zhiyu: http://127.0.0.1:{server.server_port}/",flush=True);server.serve_forever()

"""Regression coverage for v1 data, isolated restore and readiness checks."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from test_flow import Client

import server
from fixtures import EXAMPLE
from scripts.dbops import backup


class Upgrade(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.path = Path(self.scratch.name) / "old.sqlite3"
        patches = [patch.object(server, "DB", self.path), patch.dict(os.environ, {"ZHIYU_HOSTS": "127.0.0.1",
                   "ZHIYU_PUBLIC_ORIGIN": "", "ZHIYU_SECURE_COOKIE": "0", "ZHIYU_RATE_CLAIM": "99"})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        server.READ_WINDOWS.clear()

    def start(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(lambda: (httpd.shutdown(), worker.join(), httpd.server_close()))
        return "http://127.0.0.1:" + str(httpd.server_port)

    def test_populated_v1_backup_upgrade_and_feedback(self):
        with closing(sqlite3.connect(self.path)) as c, c:
            c.executescript("""
                CREATE TABLE projects(id TEXT PRIMARY KEY,owner TEXT NOT NULL,data TEXT NOT NULL);
                CREATE TABLE runs(id TEXT PRIMARY KEY,pid TEXT,rid TEXT,data TEXT,UNIQUE(pid,rid));
                CREATE TABLE cards(slug TEXT PRIMARY KEY,pid TEXT,version INTEGER,signature TEXT,data TEXT,active INTEGER DEFAULT 1,UNIQUE(pid,version));
                CREATE TABLE visits(slug TEXT,reader TEXT,opened INTEGER DEFAULT 0,PRIMARY KEY(slug,reader));
                CREATE TABLE feedback(slug TEXT,reader TEXT,sid TEXT,status TEXT,step TEXT,note TEXT,at INTEGER,PRIMARY KEY(slug,reader),UNIQUE(slug,sid));
                INSERT INTO visits VALUES('old-card','previous',1);
                INSERT INTO feedback VALUES('old-card','previous','original','blocked','核对','旧反馈',1);
            """)
            c.execute("INSERT INTO projects VALUES ('pid','legacy-owner',?)", (json.dumps(EXAMPLE),))
            c.execute("INSERT INTO cards VALUES ('old-card','pid',1,'sig',?,1)", (json.dumps({"slug":"old-card","title":"旧卡","version":1}),))
        snapshot = backup(self.path, self.path.parent / "backup", 14)
        cli = Path(__file__).parent / "scripts" / "dbops.py"
        args = [sys.executable, str(cli), "restore", str(snapshot)]
        run = subprocess.run(args, capture_output=True, text=True, check=True, timeout=15)
        self.assertIn('"feedback": 1', run.stdout)
        with closing(sqlite3.connect(snapshot)) as c:
            self.assertEqual([r[1] for r in c.execute("PRAGMA table_info(projects)")], ["id","owner","data"])
        server.init()
        server.init()
        base = self.start()
        reader = Client(base)
        self.assertEqual(reader.call("cards/old-card")["title"], "旧卡")
        reader.call("cards/old-card/feedback", dict(version=1, submissionId="new", status="done", note="迁移后提交", step=""))
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute("SELECT note FROM feedback ORDER BY at").fetchall(), [("旧反馈",),("迁移后提交",)])
        # Rehearsing on an occupied port must fail rather than reading another instance.
        self.assertNotEqual(subprocess.run(args+[base.rsplit(":",1)[1]],capture_output=True, timeout=15).returncode,0)

    def test_recovered_browser_only_manages_selected_workspace(self):
        server.init()
        base = self.start()
        a,b = Client(base),Client(base)
        for client in (a,b): client.call("workspace")
        pa=a.call("projects",dict(EXAMPLE,name="A"))["projectId"]
        pb=b.call("projects",dict(EXAMPLE,name="B"))["projectId"]
        code=a.call("recovery",{})["code"]
        restored=b.call("recovery/claim",{"code":code})
        self.assertEqual([p["projectId"] for p in restored["projects"]],[pa])
        self.assertEqual(b.call("projects/"+pa)["project"]["name"],"A")
        with self.assertRaises(HTTPError) as denied: b.call("projects/"+pb)
        self.assertEqual(denied.exception.code,404)
        denied.exception.close()

    def test_readiness_does_not_recreate_missing_database(self):
        server.init()
        reader=Client(self.start())
        self.assertTrue(reader.call("health")["ok"])
        self.path.rename(self.path.with_suffix(".saved"))
        with self.assertRaises(HTTPError) as unavailable: reader.call("health")
        self.assertEqual(unavailable.exception.code,503)
        unavailable.exception.close()
        self.assertFalse(self.path.exists())

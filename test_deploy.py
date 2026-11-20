"""Deployment behaviour tests: host allowlist, proxy IPs, secure cookies, origin,
recovery codes, health check, rate limits, and schema migration.

Each test runs against a temporary SQLite file and restores every environment
variable it touches, so the suite is safe to run on a developer machine.
"""
import http.client
import http.cookiejar
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

import server
from fixtures import EXAMPLE

ENV_KEYS = [
    "ZHIYU_HOSTS",
    "ZHIYU_PUBLIC_ORIGIN",
    "ZHIYU_TRUST_PROXY",
    "ZHIYU_SECURE_COOKIE",
    "ZHIYU_RATE_READER",
    "ZHIYU_RATE_DEV",
    "ZHIYU_RATE_READ",
    "ZHIYU_RATE_CLAIM",
    "ZHIYU_DEMO",
    "ZHIYU_BUILD",
]


class Client:
    def __init__(self, base, headers=None):
        self.base = base
        self.headers = headers or {}
        self.agent = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.last = None

    def call(self, path, data=None, headers=None, raw=False):
        merged = {"Content-Type": "application/json"}
        merged.update(self.headers)
        merged.update(headers or {})
        request = urllib.request.Request(
            self.base + "/api/" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=merged,
        )
        with self.agent.open(request, timeout=5) as response:
            self.last = response
            if raw:
                return response
            return json.load(response)


class Deploy(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = server.DB
        server.DB = Path(self.tmp.name) / "test.sqlite3"
        server.READ_WINDOWS.clear()
        server.init()
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_port
        self.base = f"http://127.0.0.1:{self.port}"
        self.dev = Client(self.base)
        self.dev.call("workspace")
        self.pid = self.dev.call("projects", EXAMPLE)["projectId"]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        server.DB = self.old_db
        server.READ_WINDOWS.clear()
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    # --- helpers -----------------------------------------------------------

    def publish(self):
        run = self.dev.call(f"projects/{self.pid}/runs", {"requestId": "deploy-1"})
        draft = dict(
            runId=run["runId"],
            candidateId="interview",
            title="部署测试卡",
            material="脱敏逐字稿",
            steps="准备材料\n核对引文",
            criterion="定位到原文",
            question="哪一句有效？",
        )
        card = self.dev.call(f"projects/{self.pid}/publish", draft)
        return card["slug"]

    def status_of(self, fn, *args, **kwargs):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            fn(*args, **kwargs)
        caught.exception.close()
        return caught.exception.code

    def raw_get(self, path, host):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host)
        conn.endheaders()
        response = conn.getresponse()
        response.read()
        code = response.status
        conn.close()
        return code

    # --- cases -------------------------------------------------------------

    def test_host_allowlist(self):
        os.environ["ZHIYU_HOSTS"] = "example.test,127.0.0.1"
        self.assertEqual(self.raw_get("/api/health", "example.test"), 200)
        self.assertEqual(self.raw_get("/api/health", "127.0.0.1"), 200)
        self.assertEqual(self.raw_get("/api/health", "evil.test"), 403)

    def test_secure_cookie_flag(self):
        os.environ["ZHIYU_SECURE_COOKIE"] = "1"
        fresh = Client(self.base)
        response = fresh.call("workspace", raw=True)
        cookies = response.headers.get_all("Set-Cookie") or []
        self.assertTrue(cookies)
        self.assertTrue(all("Secure" in item for item in cookies))

    def test_origin_allowlist(self):
        os.environ["ZHIYU_PUBLIC_ORIGIN"] = "https://zhiyu.test"
        payload = dict(EXAMPLE, name="来源测试")
        self.dev.call("projects", payload, headers={"Origin": "https://zhiyu.test"})
        self.assertEqual(
            self.status_of(self.dev.call, "projects", payload, headers={"Origin": "https://evil.test"}), 403
        )

    def test_proxy_forwarded_for_splits_buckets(self):
        os.environ["ZHIYU_TRUST_PROXY"] = "1"
        os.environ["ZHIYU_RATE_READER"] = "2"
        slug = self.publish()
        reader = Client(self.base)
        reader.call(f"cards/{slug}")
        for ip in ("198.51.100.1", "198.51.100.2"):
            self.assertEqual(
                reader.call(f"cards/{slug}/visit", {"version": 1}, headers={"X-Forwarded-For": ip}).get("receipt"),
                None,
            )
        reader.call(f"cards/{slug}/visit", {"version": 1}, headers={"X-Forwarded-For": "198.51.100.2"})
        self.assertEqual(
            self.status_of(reader.call, f"cards/{slug}/visit", {"version": 1}, headers={"X-Forwarded-For": "198.51.100.2"}),
            429,
        )
        reader.call(f"cards/{slug}/visit", {"version": 1}, headers={"X-Forwarded-For": "203.0.113.9"})

    def test_reader_rate_limit_without_proxy(self):
        os.environ["ZHIYU_RATE_READER"] = "2"
        slug = self.publish()
        reader = Client(self.base)
        reader.call(f"cards/{slug}")
        reader.call(f"cards/{slug}/visit", {"version": 1})
        reader.call(f"cards/{slug}/visit", {"version": 1})
        self.assertEqual(self.status_of(reader.call, f"cards/{slug}/visit", {"version": 1}), 429)

    def test_rejected_writes_still_consume_quota(self):
        """A 400 must not roll its own rate-limit counter back.

        The counter lives in a separate transaction on purpose: sharing the
        handler's transaction let every rejected request reset the count, so the
        limiter never fired for malformed input.
        """
        os.environ["ZHIYU_RATE_DEV"] = "2"
        bad = {"name": "只有一个字段"}
        self.assertEqual(self.status_of(self.dev.call, "projects", bad), 400)
        self.assertEqual(self.status_of(self.dev.call, "projects", bad), 429)

    def test_claim_attempts_are_capped(self):
        os.environ["ZHIYU_RATE_CLAIM"] = "2"
        bad = {"code": "ZY-AAAA-AAAA"}
        self.assertEqual(self.status_of(self.dev.call, "recovery/claim", bad), 400)
        self.assertEqual(self.status_of(self.dev.call, "recovery/claim", bad), 400)
        self.assertEqual(self.status_of(self.dev.call, "recovery/claim", bad), 429)

    def test_recovery_round_trip(self):
        code = self.dev.call("recovery", {})["code"]
        self.assertRegex(code, r"^ZY-[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}$")

        other = Client(self.base)
        other.call("workspace")
        self.assertEqual(self.status_of(other.call, "recovery/claim", {"code": "ZY-AAAA-AAAA"}), 400)

        restored = other.call("recovery/claim", {"code": code.lower()})
        self.assertEqual(len(restored["projects"]), 1)
        detail = other.call(f"projects/{self.pid}")
        self.assertEqual(detail["project"]["name"], EXAMPLE["name"])

    def test_health_needs_no_cookie(self):
        fresh = Client(self.base)
        body = fresh.call("health")
        self.assertTrue(body["ok"])
        self.assertEqual(body["db"], "ok")
        self.assertIn("version", body)

    def test_old_schema_migrates(self):
        legacy = Path(self.tmp.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy)) as conn, conn:
            conn.execute("CREATE TABLE projects(id TEXT PRIMARY KEY,owner TEXT NOT NULL,data TEXT NOT NULL)")
            conn.execute("INSERT INTO projects VALUES('p1','o1',?)", (json.dumps({"name": "旧项目"}),))
            # A card table from before provenance was recorded must not block startup.
            conn.execute(
                "CREATE TABLE cards(slug TEXT PRIMARY KEY,pid TEXT NOT NULL,version INTEGER NOT NULL,"
                "signature TEXT NOT NULL,data TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1)"
            )
        server.DB = legacy
        server.init()
        server.init()  # 幂等
        with closing(sqlite3.connect(legacy)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
            self.assertIn("created_at", columns)
            self.assertIn("updated_at", columns)
            self.assertEqual(json.loads(conn.execute("SELECT data FROM projects").fetchone()[0])["name"], "旧项目")
            self.assertEqual(conn.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()[0], "2")
            card_columns = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
            for name in ("published_at", "run_id", "candidate_id"):
                self.assertIn(name, card_columns)


class Retention(unittest.TestCase):
    """`runs` grows on every match request, so it is the one table needing a cap."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = server.DB
        server.DB = Path(self.tmp.name) / "retention.sqlite3"
        server.init()

    def tearDown(self):
        server.DB = self.old_db
        self.tmp.cleanup()

    def add_run(self, run_id, age_days):
        with closing(sqlite3.connect(server.DB)) as conn, conn:
            conn.execute(
                "INSERT INTO runs(id,pid,rid,data,created_at) VALUES(?,?,?,?,?)",
                (run_id, "p1", run_id, json.dumps({"status": "ok"}), server.now() - age_days * 86400),
            )

    def add_card(self, slug, run_id):
        with closing(sqlite3.connect(server.DB)) as conn, conn:
            conn.execute(
                "INSERT INTO cards(slug,pid,version,signature,data,active,published_at,run_id,candidate_id) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (slug, "p1", 1, "sig", "{}", 1, server.now(), run_id, "c1"),
            )

    def run_ids(self):
        with closing(sqlite3.connect(server.DB)) as conn:
            return sorted(row[0] for row in conn.execute("SELECT id FROM runs"))

    def test_old_unreferenced_runs_are_removed(self):
        self.add_run("old", 100)
        self.add_run("fresh", 1)
        report = server.prune(days=90)
        self.assertEqual(self.run_ids(), ["fresh"])
        self.assertEqual((report["candidates"], report["deleted"], report["remaining"]), (1, 1, 1))

    def test_runs_behind_a_card_are_kept_forever(self):
        self.add_run("old", 400)
        self.add_card("s1", "old")
        server.prune(days=90)
        self.assertEqual(self.run_ids(), ["old"], "已发布卡片的来源运行不能删，否则反馈追不回当时展示的内容")

    def test_dry_run_deletes_nothing(self):
        self.add_run("old", 100)
        report = server.prune(days=90, dry_run=True)
        self.assertEqual((report["candidates"], report["deleted"], report["dryRun"]), (1, 0, True))
        self.assertEqual(self.run_ids(), ["old"])

    def test_default_window_is_ninety_days(self):
        self.add_run("inside", 89)
        self.add_run("outside", 91)
        report = server.prune()
        self.assertEqual(report["days"], 90)
        self.assertEqual(self.run_ids(), ["inside"])

    def test_pruning_leaves_counts_alone(self):
        self.add_run("old", 200)
        with closing(sqlite3.connect(server.DB)) as conn, conn:
            conn.execute("INSERT INTO visits(slug,reader,opened,first_seen) VALUES('s1','r1',1,1)")
            conn.execute("INSERT INTO feedback VALUES('s1','r1','sid','done','','ok',1)")
        server.prune(days=90)
        with closing(sqlite3.connect(server.DB)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM visits").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM feedback").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

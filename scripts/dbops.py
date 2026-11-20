"""Create a private online SQLite backup or rehearse recovery on a disposable copy."""
import argparse
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import tempfile
import threading
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=8)


def counts(conn):
    if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("SQLite integrity check failed")
    return {t: conn.execute("SELECT count(*) FROM " + t).fetchone()[0]
            for t in ("projects", "runs", "cards", "visits", "feedback")}


def backup(db, out, keep):
    if keep < 1:
        raise ValueError("Retention must be at least one day")
    out = Path(out).resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    with closing(readonly(db)) as src:
        # mkstemp makes the copy private before SQLite writes any data.
        fd, name = tempfile.mkstemp(dir=out, prefix=".zhiyu-", suffix=".part")
        os.close(fd)
        tmp = Path(name)
        target = out / ("zhiyu-" + datetime.now().strftime("%Y-%m-%d-%H%M%S-%f") + ".sqlite3")
        try:
            with closing(sqlite3.connect(tmp)) as dst:
                src.backup(dst)
                counts(dst)
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
    cutoff = time.time() - keep * 86400
    for old in out.glob("zhiyu-*.sqlite3"):
        if (old != target and old != Path(db).resolve() and not old.is_symlink() and old.is_file()
                and re.fullmatch(r"zhiyu-\d{4}-\d{2}-\d{2}-(?:\d{4}|\d{6}-\d{6})\.sqlite3", old.name)
                and old.stat().st_mtime < cutoff):
            old.unlink()
    return target


def rehearse(snapshot, port):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import server
    with tempfile.TemporaryDirectory(prefix="zhiyu-restore-") as work:
        restored = Path(work) / "copy.sqlite3"
        with closing(readonly(snapshot)) as src, closing(sqlite3.connect(restored)) as dst:
            before = counts(src)
            src.backup(dst)
        server.DB = restored
        os.environ["ZHIYU_HOSTS"] = "127.0.0.1"
        marker = "restore-" + secrets.token_hex(12)
        os.environ["ZHIYU_BUILD"] = marker
        server.init()
        class RestoreHTTPServer(server.ThreadingHTTPServer):
            allow_reuse_address = False

            def server_bind(self):
                if os.name == "nt":
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                super().server_bind()

        # Binding here, not just polling a port, proves this is our instance.
        with RestoreHTTPServer(("127.0.0.1", port), server.Handler) as httpd:
            worker = threading.Thread(target=httpd.serve_forever, daemon=True)
            worker.start()
            try:
                url = f"http://127.0.0.1:{httpd.server_port}/api/health"
                with build_opener(ProxyHandler({})).open(url, timeout=5) as resp:
                    health = json.load(resp)
                if health.get("ok") is not True or health.get("db") != "ok" or health.get("version") != marker:
                    raise ValueError("Restored instance is not healthy")
            finally:
                httpd.shutdown()
                worker.join()
        with closing(readonly(restored)) as conn:
            after = counts(conn)
        if before != after:
            raise ValueError(f"Restored row counts differ: backup={before} restored={after}")
        return after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup")
    rec = sub.add_parser("restore")
    rec.add_argument("snapshot", type=Path)
    rec.add_argument("port", type=int, nargs="?", default=0)
    a = parser.parse_args()
    if a.cmd == "backup":
        target = backup(os.environ.get("ZHIYU_DB", "/srv/zhiyu/var/zhiyu.sqlite3"),
                        os.environ.get("ZHIYU_BACKUP_DIR", "/srv/zhiyu/backup"),
                        int(os.environ.get("ZHIYU_BACKUP_KEEP", "14")))
        print("backup ok:", target)
    else:
        print("restore rehearsal ok:", json.dumps(rehearse(a.snapshot, a.port)))

if __name__ == "__main__":
    main()

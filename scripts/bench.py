"""Concurrency benchmark for POST /api/projects/:id/runs.

Run against a local instance that was started with a high developer write cap,
otherwise the 120/min limiter will dominate the result:

    ZHIYU_RATE_DEV=100000 python server.py --port 4173
    python scripts/bench.py --concurrency 1,3,5 --n 20 --out bench.csv

The script creates its own workspace and project, prints p50/p95 per level,
and reports HTTP error codes so a failing run is visible rather than hidden
inside an average.
"""
import argparse
import csv
import http.cookiejar
import json
import threading
import time
import urllib.error
import urllib.request
import uuid

PROJECT = dict(
    name="压测工具",
    url="/sample",
    audience="压测用",
    material="一段脱敏的中文访谈文字稿",
    task="从访谈稿中找出支持研究结论的原话",
    output="三句带原文位置的候选引文",
    limits="只接收文字，不处理录音；引文是否支持结论需要人工核对。",
)


class Client:
    def __init__(self, base, cookie=None):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.cookie = cookie

    def call(self, path, data=None, timeout=30):
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        request = urllib.request.Request(
            self.base + "/api/" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
        )
        started = time.perf_counter()
        try:
            with self.opener.open(request, timeout=timeout) as response:
                body = json.load(response)
                code = response.status
        except urllib.error.HTTPError as error:
            body = json.loads(error.read() or b"{}")
            code = error.code
        return code, body, (time.perf_counter() - started) * 1000

    def cookie_header(self):
        return "; ".join(f"{item.name}={item.value}" for item in self.jar)


def percentile(values, ratio):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return ordered[index]


def run_level(base, pid, cookie, threads, per_thread, mode):
    results = []
    lock = threading.Lock()

    def worker():
        client = Client(base, cookie)
        for _ in range(per_thread):
            code, _, elapsed = client.call(
                f"projects/{pid}/runs", {"requestId": str(uuid.uuid4()), "mode": mode}
            )
            with lock:
                results.append((code, elapsed))

    workers = [threading.Thread(target=worker) for _ in range(threads)]
    started = time.perf_counter()
    for item in workers:
        item.start()
    for item in workers:
        item.join()
    wall = time.perf_counter() - started

    latencies = [elapsed for code, elapsed in results if code == 200]
    errors = {}
    for code, _ in results:
        if code != 200:
            errors[code] = errors.get(code, 0) + 1
    return dict(
        concurrency=threads,
        requests=len(results),
        ok=len(latencies),
        errors=errors,
        p50=round(percentile(latencies, 0.50), 1),
        p95=round(percentile(latencies, 0.95), 1),
        max=round(max(latencies), 1) if latencies else 0.0,
        wall_s=round(wall, 2),
        rps=round(len(results) / wall, 2) if wall else 0.0,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:4173")
    parser.add_argument("--concurrency", default="1,3,5")
    parser.add_argument("--n", type=int, default=20, help="requests per thread")
    parser.add_argument("--mode", default="synthetic", choices=["synthetic", "live"])
    parser.add_argument("--out", help="write per-level rows to this CSV file")
    args = parser.parse_args()

    setup = Client(args.base)
    setup.call("workspace")
    code, project, _ = setup.call("projects", PROJECT)
    if code != 200:
        raise SystemExit(f"setup failed: HTTP {code} {project}")
    pid = project["projectId"]
    cookie = setup.cookie_header()

    levels = [int(item) for item in args.concurrency.split(",") if item.strip()]
    rows = [run_level(args.base, pid, cookie, level, args.n, args.mode) for level in levels]

    header = f"{'并发':>4} {'请求':>6} {'成功':>6} {'p50ms':>7} {'p95ms':>7} {'maxms':>7} {'RPS':>7}  错误"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['concurrency']:>4} {row['requests']:>6} {row['ok']:>6} "
            f"{row['p50']:>7} {row['p95']:>7} {row['max']:>7} {row['rps']:>7}  {row['errors'] or ''}"
        )
    if any(429 in row["errors"] for row in rows):
        print("\n出现 429：请用 ZHIYU_RATE_DEV=100000 启动服务后重跑，否则测到的是限流而不是匹配。")
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwritten: {args.out}")


if __name__ == "__main__":
    main()

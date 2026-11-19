# 运行手册

## 启停

```bash
sudo systemctl start zhiyu
sudo systemctl stop zhiyu
sudo systemctl restart zhiyu
systemctl status zhiyu --no-pager
```

本地：`python server.py --open`，`Ctrl+C` 停止。

## 健康检查

```bash
curl -s http://127.0.0.1:4173/api/health
```

正常返回 `{"ok":true,"version":"...","db":"ok","time":...}`。`version` 与服务器上 `git describe --tags --always` 应一致。503 表示数据库不可用，先看日志。

## 日志

```bash
journalctl -u zhiyu -f
journalctl -u zhiyu --since "1 hour ago"
tail -f /var/log/caddy/zhiyu.log
```

应用默认只记录存储异常。需要访问日志时设 `ZHIYU_ACCESS_LOG=1` 并重启，输出方法、路径、状态、耗时、IP。不记录 Cookie、恢复码与反馈正文。

## 备份

```bash
/srv/zhiyu/app/scripts/backup.sh
```

输出 `backup ok: ...` 表示备份通过完整性检查。保留 14 天。不要用 `cp` 复制运行中的数据库文件，WAL 模式下会拿到不完整副本。

## 恢复演练（每周一次）

```bash
/srv/zhiyu/app/scripts/restore-check.sh /srv/zhiyu/backup/zhiyu-2026-11-28-0300.sqlite3
```

脚本把备份复制到临时目录，用 4199 端口启动独立实例，跑健康检查并打印项目、卡片、反馈数量。看到 `restore rehearsal ok` 才算通过。真实恢复时停服，把备份文件覆盖到 `ZHIYU_DB`，再启动。

## 演示码

```bash
sudo cat /srv/zhiyu/var/DEMO_CODE
```

丢失后删除 `meta` 里的 `demo_owner` 不会自动重建，直接删库重启会清空全部数据，不要在生产上做。需要重新生成时，用工作台所在浏览器打开 `/recover`，点“在当前浏览器生成恢复码”。

## 常见故障

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 全站 403，提示域名不在列表 | `ZHIYU_HOSTS` 未加域名 | 加域名并重启 |
| 发布或反馈 403 来源不匹配 | `ZHIYU_PUBLIC_ORIGIN` 与访问地址不一致 | 改成 `https://域名` |
| 所有读者很快 429 | `ZHIYU_TRUST_PROXY` 未开，限流按反代 IP 计 | 设为 1，确认反代传 `X-Forwarded-For` |
| 页面打不开，反代 502 | 进程未启动或端口不符 | `systemctl status zhiyu`，核对 4173 |
| 重启后数据消失 | `ZHIYU_DB` 指向临时目录，或 systemd 未放行路径 | 指向 `/srv/zhiyu/var`，检查 `ReadWritePaths` |
| 反馈时间不对 | 服务器时区为 UTC | 设 `TZ=Asia/Shanghai`，接口本身用 Unix 秒 |
| 证书未签发 | 80 端口被封或域名未解析 | 检查安全组与 DNS，`journalctl -u caddy` |
| 提交提示存储不可用 | 磁盘满或数据库损坏 | `df -h`，`sqlite3 <db> 'PRAGMA integrity_check;'` |

## 发布

1. 本地 `python -m unittest -v test_flow test_deploy` 全绿。
2. 打 tag：`v0.9.0-test`（11/26）、`v1.0.0-rc1`（12/04）、`v1.0.0`（12/06）。
3. 服务器 `git checkout <tag>`，更新 `ZHIYU_BUILD`，重启。
4. `/api/health` 核对版本，跑一遍发布、读者、反馈、看板四步。
5. 记录到本文件的发布记录。

## 回退

```bash
git checkout <上一个 tag>
sudo systemctl restart zhiyu
curl -s https://<域名>/api/health
```

数据兼容，无需回退数据库。若确实需要，停服后覆盖 `ZHIYU_DB` 再启动，并在群里说明影响范围与时间。

## 压测

```bash
ZHIYU_RATE_DEV=100000 python server.py --port 4173
python scripts/bench.py --concurrency 1,3,5 --n 20 --out bench.csv
```

不放开 `ZHIYU_RATE_DEV` 会测到 429 而不是匹配。脚本会打印错误码分布，出现 429 时按提示重跑。结果同时交给 B1 记录到计划书。

## 数据清理

限流窗口每 10 分钟自动清理。读者反馈与访问记录按项目保留，不做自动删除。提交前如需演示库干净，重新生成演示数据即可，不要删生产库。

## 发布记录

| 日期 | 版本 | 操作人 | 结果 |
| --- | --- | --- | --- |
| 待填 | | | |

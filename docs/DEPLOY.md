# 部署手册

目标：一台阿里云主机，Caddy 终止 TLS，Python 进程只监听回环，数据落在持久目录，每日备份。

## 0. 前置条件

| 项 | 要求 | 由谁提供 |
| --- | --- | --- |
| 主机 | 2 vCPU / 2 GiB / 40 GiB，Ubuntu 22.04 LTS | P |
| 公网 IP 与 SSH | 可登录，安全组可改 | P |
| 域名 | 已解析到该 IP | P |
| 备案 | 大陆地域需 ICP 备案；无备案走第 1 节的 B 或 C | P |
| 安装许可 | 允许安装 `caddy`、`sqlite3` | 主机所有者 |

## 1. 先定 HTTPS 路线

大陆地域服务器绑定未备案域名时，80/443 会被拦截，备案周期 7 至 20 个工作日，赶不上 12/07。

| 路线 | 条件 | 做法 |
| --- | --- | --- |
| A | 有已备案域名 | A 记录指向主机，Caddy 自动签发证书 |
| B | 无备案域名 | 换中国香港或海外地域主机，或用其轻量应用服务器 |
| C | 都不行 | `http://IP:4173`，`ZHIYU_SECURE_COOKIE=0`，在提交说明里注明 |

不要在未备案的情况下先上线再补。

**路线 C 曾让读者端直接报错，现已加前端兜底修复。** 2026-11-20 真机验证（小米/Android 17，浏览器直连 `http://172.31.26.77:4199`）发现：点「试跑访谈稿示例」报 `crypto.randomUUID is not a function`，页面停留原地，读者无法提交反馈。原因是 `crypto.randomUUID()` 按规范**只在 secure context（HTTPS 或 localhost）暴露**，明文 IP 访问不是安全上下文。浏览器证书无效的 HTTPS 同样不算 secure context，自签证书救不了这条路。

**兜底已在 `app.js` 顶部加好**（`crypto.getRandomValues` 在任何上下文都可用，仅在原生方法缺失时生效）。补丁必须放在外部脚本 `app.js` 里——CSP 是 `script-src 'self'`，往 `index.html` 写内联 `<script>` 会被拦掉。

注意静态资源缓存头是 `max-age=300`。部署后若改了 `app.js`/`styles.css`，用户浏览器最多 5 分钟内仍拿旧文件；演示前应强刷一次，或给 `<script src>` 加版本查询串（后者要 F1 改 `index.html`）。这次真机验证就踩过缓存的坑。详见 `docs/进度与交接.md` 的「真机验证」。

## 2. 主机初始化

```bash
sudo apt update
sudo apt install -y python3 sqlite3 caddy
sudo adduser --system --group --home /srv/zhiyu zhiyu
sudo mkdir -p /srv/zhiyu/var /srv/zhiyu/backup /var/log/caddy
sudo chown -R zhiyu:zhiyu /srv/zhiyu
sudo chown caddy:caddy /var/log/caddy
```

安全组入方向：22 仅本人 IP，80 与 443 对 0.0.0.0/0。不使用 4173 对公网开放。

## 3. 代码

部署的是带 B2 改动的分支，不是上游 `main`：

```bash
sudo -u zhiyu git clone https://github.com/Yaki-Blake/zhiyu-hackathon.git /srv/zhiyu/app
cd /srv/zhiyu/app
sudo -u zhiyu git checkout feat/b2-deploy-foundation
git log -1 --format='%h %s'   # 应显示 84b22de 或更新
```

上游仓库是 `https://github.com/kane959/zhiyu-hackathon.git`，`main` 停在 `554f13e`，没有 B2 的任何改动，不要直接部署它。

## 4. 环境变量

```bash
sudo install -m 600 -o root -g root .env.example /etc/zhiyu.env
sudo editor /etc/zhiyu.env
```

生产至少改这几项：

```ini
ZHIYU_DB=/srv/zhiyu/var/zhiyu.sqlite3
ZHIYU_HOSTS=zhiyu.example.com,127.0.0.1
ZHIYU_PUBLIC_ORIGIN=https://zhiyu.example.com
ZHIYU_TRUST_PROXY=1
ZHIYU_SECURE_COOKIE=1
ZHIYU_BUILD=v1.0.0-rc1+<short-sha>
ZHIYU_RATE_READER=30
ZHIYU_RATE_DEV=120
```

`ZHIYU_TRUST_PROXY=1` 必须与反代同时生效，否则所有读者共用一个 IP，30 次/分钟会误伤。`ZHIYU_HOSTS` 只写主机名，不带协议和端口。

`ZHIYU_HOST` 是监听地址，默认 `127.0.0.1`，只允许本机与反代访问，这是生产该用的值。改成 `0.0.0.0` 会把端口暴露到网络上，此时必须把手机或局域网能访问到的地址一并写进 `ZHIYU_HOSTS`（只写主机名，不带端口），否则每个请求都会拿到 403「当前访问地址不在允许的域名列表内」。命令行等价写法是 `--host 0.0.0.0`。

## 5. 进程托管

```bash
sudo cp deploy/zhiyu.service /etc/systemd/system/zhiyu.service
sudo systemctl daemon-reload
sudo systemctl enable --now zhiyu
systemctl status zhiyu --no-pager
curl -s http://127.0.0.1:4173/api/health
```

`ProtectSystem=strict` 会把文件系统设为只读，`ReadWritePaths=/srv/zhiyu/var` 是写入放行，删掉会导致 SQLite 无法建库。因此 `ZHIYU_DB` 必须是绝对路径，写成相对的 `var/...` 会落到只读的 app 目录，启动即失败。

## 6. 反向代理

Caddy：

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo editor /etc/caddy/Caddyfile   # 把 zhiyu.example.com 换成真实域名
sudo systemctl reload caddy
```

nginx 备选：

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/zhiyu
sudo ln -s /etc/nginx/sites-available/zhiyu /etc/nginx/sites-enabled/zhiyu
sudo certbot --nginx -d zhiyu.example.com
sudo nginx -t && sudo systemctl reload nginx
```

## 7. 备份、探活与定时任务

定时任务固化在 `deploy/crontab`，不要再手写 `crontab -e`——手写的条目没人复核，`backup.sh` 漏掉执行位这类问题就是这么来的。

```bash
cd /srv/zhiyu/app
sudo cp deploy/crontab /tmp/zhiyu.crontab    # 先在临时副本上改，改坏了不影响仓库
sudo editor /tmp/zhiyu.crontab               # 把 watch.sh 的 --url 换成真实地址
sudo crontab -u zhiyu /tmp/zhiyu.crontab
sudo crontab -u zhiyu -l                     # 核对四条都在
```

注意 `crontab -u zhiyu <file>` 会**整份替换**该用户的 crontab，所以这份文件必须是唯一来源。

| 时间 | 任务 | 作用 |
| --- | --- | --- |
| 每日 03:00 | `backup.sh` | WAL 安全的 `.backup`，并对副本做完整性检查 |
| 每 5 分钟 | `watch.sh --url https://<域名>/api/health` | 探活，连续 3 次失败告警一次，恢复再告警一次 |
| 每周日 04:10 | `watch.sh --integrity` | 线上库 `PRAGMA integrity_check` |
| 每周日 04:30 | `prune.py --apply` | 清理超出保留期的匹配运行 |

首次手动各跑一次，确认行为：

```bash
sudo -u zhiyu /srv/zhiyu/app/scripts/backup.sh
sudo -u zhiyu /srv/zhiyu/app/scripts/watch.sh --url https://<域名>/api/health --verbose
sudo -u zhiyu /srv/zhiyu/app/scripts/watch.sh --integrity --verbose
```

第一条应打印 `backup ok:`，后两条应打印 `ok: http=200` 与 `integrity ok:`。`watch.sh` 的输出同时写进 `var/watch.log`。

告警去向要显式配一个：默认 crontab 里 `MAILTO=""` 且没有 `--notify`，告警只会落在 `var/watch.log` 与 `var/watch.out`，夜里出事没人会看到。配法见 `docs/RUNBOOK.md` 的「监控与告警」；预检 E6 会在两种渠道都没有时报 `WARN`。

异地副本可选：`ossutil cp` 到 OSS，或每周手动下载。

## 8. 部署预检

前面几节有二十多处「看起来对了」，靠人眼逐条核对很容易漏。预检把 DEPLOY.md 与 RUNBOOK 里的判据变成一条命令：

```bash
cd /srv/zhiyu/app
sudo ./scripts/preflight.sh                       # 地址从 /etc/zhiyu.env 读
sudo ./scripts/preflight.sh --base https://zhiyu.example.com
sudo ./scripts/preflight.sh --skip-net            # 机器还没通外网时
```

它只读，不改任何东西。满配共 43 项，分七组：

| 组 | 查什么 |
| --- | --- |
| A 系统与依赖 | python3 ≥ 3.8、sqlite3、curl、反向代理在跑、数据与备份目录属主是 `zhiyu`、五个脚本带执行位 |
| B 配置 | `/etc/zhiyu.env` 是 600 root、`ZHIYU_DB` 绝对路径且落在 `ReadWritePaths` 内、`ZHIYU_HOSTS` 不带协议端口、`ZHIYU_PUBLIC_ORIGIN` 主机名与白名单一致、`SECURE_COOKIE` 与协议匹配、有反代却 `TRUST_PROXY=0`、监听地址不是 `0.0.0.0` |
| C 进程与回环 | systemd 单元已安装 / enabled / active、回环 `/api/health` 有响应、`version` 与 `ZHIYU_BUILD` 一致、监听绑在回环 |
| D 公网 | 站点 200、证书剩余天数、http 跳 https、HSTS、经反代的 health、`Server` 头是否暴露实现 |
| E 备份与定时任务 | crontab 里有 `backup.sh` 与 `watch.sh`、48 小时内有备份、最新备份 `integrity_check` 通过、探活地址不是占位域名、告警有去向（`--notify` 或 `MAILTO`） |
| F 数据 | 库存在、WAL 模式、`runs` 是否超过保留期、`limits` 行数、`DEMO_CODE` 权限 600 |
| G 版本 | 部署目录在哪个分支、`ZHIYU_BUILD` 与 `git describe` 是否对得上、工作区是否干净 |

输出每项 `PASS` / `WARN` / `FAIL` / `SKIP`，结尾汇总。**有 `FAIL` 退出码为 1，只有 `WARN` 为 0**，所以能直接接进脚本或 CI。

`SKIP` 不等于通过：读不到 `zhiyu` 用户的 crontab（要 root）、机器上没有 systemctl 时都会跳过，那几项要手动确认一次。

什么时候跑：部署完第一次、交地址前、每次回退之后。

本机在一套模拟主机环境上验证过两件事：配置齐全时 **0 项失败**，只留下真实存在的警告，不制造假警报（证书与明文跳转两项在无 HTTPS 的机器上记 `SKIP`）；把 `ZHIYU_DB` 改成相对路径、`ZHIYU_HOSTS` 加上端口、`PUBLIC_ORIGIN` 换成白名单外的域名、`TRUST_PROXY` 归零、`SECURE_COOKIE` 与 https 不符、`ReadWritePaths` 指错、`ZHIYU_BUILD` 与运行版本不一致，这七项各自准确报 `FAIL`，退出码 1。

定时任务那三项（E4 至 E6）用假 `crontab` 命令喂了四份不同的 crontab 验证：完整一份全过；去掉 `watch.sh` 行时 E4 报 `FAIL`、E5/E6 记 `SKIP`，不重复报同一条缺失；探活地址留着 `zhiyu.example.com` 时 E5 报 `FAIL`；只有回环地址时 E5 报 `WARN` 而不是 `FAIL`——单机演示可以接受，有域名就不该这样。空 crontab 与「读不到 crontab」分开判定：前者是装漏了，报 `FAIL`；后者权限不足，记 `SKIP` 并提示人工确认。

A7 的执行位检查在 Windows 上无法复现失败路径：Git Bash 对 `.sh` 恒判为可执行，`chmod -x` 也不改它的 `-x` 结果。到 Linux 主机上才是准确判据。

这条检查是补出来的：`backup.sh`、`restore-check.sh` 在 Git 里原本记成 644，而 crontab 和文档都是直接按路径调用 `scripts/backup.sh`，部署后 cron 会以权限不足静默失败，手动 `bash scripts/backup.sh` 却照常工作——最容易被误判成「备份没问题」。

## 9. 验收

1. `https://<域名>/` 打开，证书有效。
2. `/api/health` 返回 200，`version` 与 tag 一致。
3. 桌面 Chrome、Edge 各完成一次发布与反馈。
4. 手机 Safari、Chrome 打开卡片并提交反馈。
5. 双击提交只多一条。
6. 撤回后读者链接 404，看板仍有历史反馈。
7. `sudo systemctl restart zhiyu` 后数据不变。
8. `scripts/restore-check.sh <最新备份>` 输出计数一致。
9. 第 31 次读者写入返回 429，1 分钟后恢复。
10. 回退到上一 tag 后服务可用，再切回。

## 10. 发布与回退

```bash
cd /srv/zhiyu/app
git fetch --tags
git checkout v1.0.0-rc1
sudo systemctl restart zhiyu
curl -s https://<域名>/api/health
```

回退：

```bash
git checkout <上一个 tag>
sudo systemctl restart zhiyu
```

数据层是加法迁移，回退代码不需要回退数据库。若迁移破坏兼容，停服后用 `scripts/backup.sh` 的备份覆盖 `ZHIYU_DB` 指向的文件，再启动。

## 11. 演示账号

```bash
sudo sed -i 's/^ZHIYU_DEMO=0/ZHIYU_DEMO=1/' /etc/zhiyu.env
sudo systemctl restart zhiyu
sudo cat /srv/zhiyu/var/DEMO_CODE
```

`DEMO_CODE` 权限 600，只发给评委，不写进公开仓库。提交表单填：站点地址 + 恢复码 + “打开 /recover 粘贴恢复码”三步。

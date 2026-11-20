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

**路线 C 会让读者端直接报错，必须先补前端兜底。** 2026-11-20 真机验证（小米/Android 17，浏览器直连 `http://172.31.26.77:4199`）发现：点「试跑访谈稿示例」报 `crypto.randomUUID is not a function`，页面停留原地，读者无法提交反馈。原因是 `crypto.randomUUID()` 按规范**只在 secure context（HTTPS 或 localhost）暴露**，明文 IP 访问不是安全上下文。浏览器证书无效的 HTTPS 同样不算 secure context，自签证书救不了这条路。

走路线 C 时必须先在 `index.html` 注入一段兜底（`crypto.getRandomValues` 在任何上下文都可用），或者改用自签证书**之外**的方案（如内网穿透到已备案域名）。详见 `docs/进度与交接.md` 的「真机验证」。

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

## 7. 备份

```bash
sudo -u zhiyu crontab -e
# 0 3 * * * /srv/zhiyu/app/scripts/backup.sh >> /var/log/zhiyu-backup.log 2>&1
```

首次手动跑一次，确认 `backup/` 出现文件且日志无报错。异地副本可选：`ossutil cp` 到 OSS，或每周手动下载。

## 8. 验收

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

## 9. 发布与回退

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

## 10. 演示账号

```bash
sudo sed -i 's/^ZHIYU_DEMO=0/ZHIYU_DEMO=1/' /etc/zhiyu.env
sudo systemctl restart zhiyu
sudo cat /srv/zhiyu/var/DEMO_CODE
```

`DEMO_CODE` 权限 600，只发给评委，不写进公开仓库。提交表单填：站点地址 + 恢复码 + “打开 /recover 粘贴恢复码”三步。

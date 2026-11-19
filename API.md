# 本机接口契约 · 第一版

请求及响应为 JSON。先 GET /api/workspace 取得开发者 HttpOnly 会话。除明确公开的接口外，所有项目访问均在服务端检查所属会话。错误返回非 2xx 和 {"error":"可展示的中文原因"}。匹配的业务失败仍有 runId、可查询，不能仅看 HTTP 状态判断成功。

| 方法与路径 | 请求或响应 |
| --- | --- |
| GET /api/workspace | projects、example、mode=synthetic、liveStatus=not_configured |
| POST /api/projects | name、url、audience、material、task、output、limits；带 projectId 为更新。返回已保存项目 |
| GET /api/projects/:id | project、最新 run 或 null、历史 cards（含 active） |
| POST /api/projects/:id/runs | requestId、mode=synthetic/live；相同项目和 requestId 去重 |
| GET /api/projects/:id/runs/:runId | runId、requestId、mode、status、errorCode、candidates、projectSnapshot |
| GET /api/sources/:fixtureId | 公开的合成全文与引用；不代表知乎内容 |
| POST /api/projects/:id/publish | runId、candidateId、title、material、steps、criterion、question。核验归属、当前能力和候选判断后生成 slug/version。重复发布相同当前快照返回同一版本 |
| GET /api/cards/:slug | 公开快照：slug、version、tool、url、scene、mode 及上面的五项卡片内容；签发读者会话 |
| POST /api/cards/:slug/visit 或 /open | version；服务端由读者 Cookie + slug 去重；visit 返回既有 receipt 或 null |
| POST /api/cards/:slug/feedback | version、submissionId、status=done/blocked、step、note。blocked 必填 step；同会话同版本一份，返回 receipt |
| POST /api/projects/:id/withdraw/:slug | 空对象；撤回读者链接，保留反馈 |
| GET /api/projects/:id/results | versions[]：slug、version、visits、opened、completed、feedback[]；前端选择版本或汇总 |

前端路由：/#home、/#edit/new、/#edit/:projectId、/#match/:projectId、/#card/:projectId/:candidateId、/#published/:projectId/:slug、/#result/:projectId；匿名读者 /t/:slug；样例原工具 /sample；合成来源 /source/:fixtureId。

## 可复现的匹配结果

| 示例 | 触发方式 | 返回 |
| --- | --- | --- |
| 成功 | 访谈稿示例；运行本地匹配 | success；interview 适配（证据片段可在 /source/interview 定位），transcribe 排除（工具不处理录音）。字段 id/title/author/url/sourceType/evidence/judgment/reason/unknown；未知作者为 null |
| 空结果 | 另登记一项“输入盆栽照片、任务辨认花卉、产出花名、限制留空”的工具 | empty、candidates=[]、errorCode=null |
| 失败 | 已保存工具 → 检查真实模式 | failed、errorCode=not_configured、candidates=[]；可切回本地匹配测试 |

本版为同步本地计算，不模拟异步进度、真实限额和网络超时。接官方接口后再扩展队列、请求重试和错误码。读者会话标识保存在 HttpOnly Cookie 中，不对前端或开发者反馈列表暴露。

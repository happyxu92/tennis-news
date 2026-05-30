# tennis-news

网球赛事信息采集与微信公众号草稿生成系统。

当前代码已具备这些能力：

1. 通过 WTA 内部 API 抓取赛事、比赛、Order of Play 和单场比分详情
2. 将赛事、比赛、快照、发布任务落库到 SQLite
3. 检测赛程变化和重点比赛赛果变化，并生成发布任务
4. 渲染微信公众号图文 HTML，并创建公众号草稿
5. 通过调度器执行 `抓取 -> 比对 -> 创建草稿` 自动化循环

说明：默认自动化链路当前停留在“创建草稿”阶段，尚未接入正式提交发布；`check-publish-status` 仅用于已存在 `publishing` 任务的状态同步。

## 目录

```text
app/
  crawler/       WTA client、适配器、抓取服务、标准化 schema
  models/        SQLAlchemy ORM 模型
  publisher/     微信文章渲染、草稿创建、微信 API client
  services/      sync、diff、dispatch、scheduler 编排服务
  settings/      环境变量配置加载
  storage/       数据库初始化与 repository
  logging.py     日志配置
  main.py        CLI 入口
scripts/
  init_db.py
  render_schedule_pages.py
tests/           单元测试
data/            SQLite 数据库、媒体文件、渲染输出
```

## 环境准备

1. 复制 `.env.example` 为 `.env`
2. 安装依赖：`uv sync --extra dev`
3. 如果暂时不接微信发布，把 `TENNIS_NEWS_WECHAT_PUBLISH_ENABLED=false`

Python 版本要求：`>= 3.12`

## 常用命令

初始化数据库：

```bash
uv run python -m app.main init-db
```

执行一次抓取、比对并生成发布任务：

```bash
uv run python -m app.main sync
```

处理待发布任务并创建公众号草稿：

```bash
uv run python -m app.main publish-pending
```

同步已进入 `publishing` 状态任务的发布结果：

```bash
uv run python -m app.main check-publish-status
```

启动常驻调度器：

```bash
uv run python -m app.main run-scheduler
```

渲染赛程文章本地预览页：

```bash
uv run python scripts/render_schedule_pages.py
```

运行测试：

```bash
uv run pytest
```

静态检查：

```bash
uv run ruff check .
```

## 关键配置

配置通过 `.env` 加载，环境变量前缀为 `TENNIS_NEWS_`。

常用项：

```dotenv
TENNIS_NEWS_ENVIRONMENT=local
TENNIS_NEWS_LOG_LEVEL=INFO
TENNIS_NEWS_DATABASE_URL=sqlite:///./data/tennis_news.db

TENNIS_NEWS_SOURCE_PROVIDER=wta
TENNIS_NEWS_SOURCE_BASE_URL=https://www.wtatennis.com
TENNIS_NEWS_SOURCE_TIMEOUT_SECONDS=20

TENNIS_NEWS_SCHEDULER_INTERVAL_MINUTES=15
TENNIS_NEWS_FOCUS_COUNTRIES=CHN
TENNIS_NEWS_ARTICLE_TIMEZONE=Asia/Shanghai

TENNIS_NEWS_WECHAT_PUBLISH_ENABLED=false
TENNIS_NEWS_WECHAT_APP_ID=
TENNIS_NEWS_WECHAT_APP_SECRET=
TENNIS_NEWS_WECHAT_AUTHOR=happy
TENNIS_NEWS_WECHAT_DEFAULT_COVER_MEDIA_ID=
TENNIS_NEWS_WECHAT_DEFAULT_COVER_IMAGE_PATH=
```

补充说明：

1. `source_provider` 当前仅支持 `wta`
2. `focus_countries` 会影响重点比赛判定，默认包含 `CHN`
3. 微信发布开启后，创建草稿时必须提供封面：`wechat_default_cover_media_id` 或 `wechat_default_cover_image_path` 至少配置一个

## 数据库说明

默认数据库文件：`data/tennis_news.db`

主要表：

1. `tournaments`：赛事
2. `matches`：比赛当前状态
3. `match_snapshots`：上游抓取快照，用于变更检测
4. `publish_jobs`：待发布或已完成的发布任务
5. `published_articles`：公众号草稿或文章记录

查看所有表：

```bash
sqlite3 data/tennis_news.db ".tables"
```

查看赛事总数：

```bash
sqlite3 data/tennis_news.db "select count(*) from tournaments;"
```

查看比赛总数：

```bash
sqlite3 data/tennis_news.db "select count(*) from matches;"
```

查看最新 20 场比赛：

```bash
sqlite3 -header -column data/tennis_news.db "select m.id, coalesce(t.name, '<unlinked>') as tournament, m.source_match_id, m.round_name, m.scheduled_at_utc, m.court_name, m.player1_name, m.player2_name, m.status, m.score_text, m.winner_name from matches m left join tournaments t on t.id = m.tournament_id order by m.updated_at desc limit 20;"
```

查看发布任务：

```bash
sqlite3 -header -column data/tennis_news.db "select id, job_type, biz_key, status, retry_count, created_at, updated_at from publish_jobs order by id desc limit 20;"
```

查看已生成草稿或文章记录：

```bash
sqlite3 -header -column data/tennis_news.db "select id, job_id, title, wechat_media_id, publish_id, article_url, published_at from published_articles order by id desc limit 20;"
```

交互模式查看：

```bash
sqlite3 data/tennis_news.db
.mode column
.headers on
```

## 当前数据源状态

当前默认且唯一的数据源为 `WTA`。

已实现：

1. 通过 `https://api.wtatennis.com/tennis/tournaments/` 抓取赛事列表
2. 通过 `https://api.wtatennis.com/tennis/tournaments/{id}/{year}/matches` 抓取比赛列表
3. 通过 `https://api.wtatennis.com/tennis/tournaments/{id}/{year}/oop` 补充场地和赛程信息
4. 通过 `https://api.wtatennis.com/tennis/tournaments/{id}/{year}/matches/{matchId}/score` 深抓单场详情
5. 将原始数据标准化后写入 `tournaments`、`matches`、`match_snapshots`

当前限制：

1. 比赛详情抓取还是串行执行，未做并发优化
2. 正式发布提交虽然已有微信 API client 能力，但默认流程还未接通 `submit_publish`
3. 当前抓取窗口聚焦最近 21 天到未来 3 天内的赛事

## 自动化运行

调度入口：`uv run python -m app.main run-scheduler`

当前调度行为：

1. 启动后立即执行一轮自动化周期
2. 每轮执行 `sync -> publish-pending`
3. `sync` 内部包含 `抓取 -> 比对 -> 创建 publish_jobs`
4. 后续按 `TENNIS_NEWS_SCHEDULER_INTERVAL_MINUTES` 周期运行，默认每 15 分钟一次
5. 每个阶段使用独立数据库会话，避免常驻进程长事务堆积
6. 若 `wechat_publish_enabled=false`，发布阶段会直接跳过
7. 默认调度不会执行 `check-publish-status`

日志会输出：

1. 调度启动间隔
2. 每轮同步到的赛事数、比赛数、创建任务数
3. 发布阶段处理任务数、成功数、可重试数、失败数

## 本地预览文章

可用脚本把赛程任务渲染为本地 HTML，便于调样式：

```bash
uv run python scripts/render_schedule_pages.py --dates 2026-05-30 2026-05-31
```

默认输出目录：`data/rendered`

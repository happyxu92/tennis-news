# tennis-news

网球赛事信息采集与微信公众号发布系统。

当前已完成 PRD 第 1-7 阶段基础能力：

1. 项目初始化
2. 数据模型与存储
3. WTA 官方页面抓取接入骨架
4. 变化检测与重点比赛判定
5. 内容生成
6. 微信公众号草稿创建与发布状态检查基础能力
7. 调度与自动化运行

说明：当前自动化发布链路默认仍停留在“创建草稿”阶段，尚未接入正式发布提交。

## 目录

```text
app/
  crawler/      数据源 client、adapter、crawler service
  models/       SQLAlchemy ORM 模型
  publisher/    后续微信公众号发布模块占位
  services/     后续业务编排模块占位
  settings/     配置加载
  storage/      数据库初始化与 repository
  main.py       启动入口
tests/          基础测试
scripts/        辅助脚本
```

## 环境准备

1. 复制 `.env.example` 为 `.env`
2. 安装依赖：`uv sync --extra dev`

## 常用命令

初始化数据库：

```bash
uv run python -m app.main init-db
```

执行一次数据同步：

```bash
uv run python -m app.main sync
```

启动常驻调度器：

```bash
uv run python -m app.main run-scheduler
```

运行测试：

```bash
uv run pytest
```

静态检查：

```bash
uv run ruff check .
```

## 查看赛事数据

数据库文件：`data/tennis_news.db`

查看所有表：

```bash
sqlite3 data/tennis_news.db ".tables"
```

查看赛事总数：

```bash
sqlite3 data/tennis_news.db "select count(*) from tournaments;"
```

查看赛事列表：

```bash
sqlite3 data/tennis_news.db "select id, source_tournament_id, name, tour, level, start_date, end_date from tournaments order by start_date;"
```

只看大满贯：

```bash
sqlite3 data/tennis_news.db "select source_tournament_id, name, start_date, end_date from tournaments where tour = 'grand_slam' order by start_date;"
```

查看某条赛事的原始抓取数据：

```bash
sqlite3 data/tennis_news.db "select metadata from tournaments where name = 'Australian Open';"
```

查看表结构：

```bash
sqlite3 data/tennis_news.db ".schema tournaments"
```

更适合阅读的交互模式：

```bash
sqlite3 data/tennis_news.db
.mode column
.headers on
select id, source_tournament_id, name, tour, level, start_date, end_date from tournaments order by start_date;
```

## 查看比赛数据

查看比赛总数：

```bash
sqlite3 data/tennis_news.db "select count(*) from matches;"
```

查看最新更新的 20 场比赛：

```bash
sqlite3 -header -column data/tennis_news.db "select m.id, coalesce(t.name, '<unlinked>') as tournament, m.source_match_id, m.round_name, m.scheduled_at_utc, m.court_name, m.player1_name, m.player2_name, m.status, m.score_text, m.winner_name from matches m left join tournaments t on t.id = m.tournament_id order by m.updated_at desc limit 20;"
```

按赛事汇总比赛数量：

```bash
sqlite3 -header -column data/tennis_news.db "select coalesce(t.name, '<unlinked>') as tournament, count(*) as total_matches, sum(case when m.status = 'finished' then 1 else 0 end) as finished_matches, sum(case when m.status in ('scheduled', 'in_progress', 'live', 'delayed') then 1 else 0 end) as active_matches, max(m.updated_at) as last_match_update from matches m left join tournaments t on t.id = m.tournament_id group by coalesce(t.name, '<unlinked>') order by last_match_update desc limit 20;"
```

查看指定球员相关比赛：

```bash
sqlite3 -header -column data/tennis_news.db "select m.id, coalesce(t.name, '<unlinked>') as tournament, m.round_name, m.scheduled_at_utc, m.player1_name, m.player2_name, m.status, m.score_text, m.winner_name from matches m left join tournaments t on t.id = m.tournament_id where m.player1_name like '%Zheng Qinwen%' or m.player2_name like '%Zheng Qinwen%' order by m.scheduled_at_utc desc;"
```

交互模式下查看比赛数据：

```bash
sqlite3 data/tennis_news.db
.mode column
.headers on
select m.id, coalesce(t.name, '<unlinked>') as tournament, m.source_match_id, m.round_name, m.scheduled_at_utc, m.court_name, m.player1_name, m.player2_name, m.status, m.score_text, m.winner_name
from matches m
left join tournaments t on t.id = m.tournament_id
order by m.updated_at desc
limit 20;
```

## 当前数据源状态

当前默认数据源为 `WTA` 官方站页面抓取。

已实现：

1. 通过 `https://api.wtatennis.com/tennis/tournaments/` 抓取赛事列表
2. 通过 `https://api.wtatennis.com/tennis/tournaments/{id}/{year}/matches` 抓取比赛赛程和赛果
3. 通过 `https://api.wtatennis.com/tennis/tournaments/{id}/{year}/oop` 融合场地补充信息
4. 通过 `https://api.wtatennis.com/tennis/tournaments/{id}/{year}/matches/{matchId}/score` 深抓单场详情
5. 将赛事与比赛标准化后落库

暂未实现：

1. 单场详情抓取的并发优化与重试控制
2. 更多详情字段的结构化落库

说明：`/scores` 页面数据主要由前端异步加载，本项目当前已转为直接调用其内部 WTA API。

## 自动化运行

调度入口：`uv run python -m app.main run-scheduler`

当前调度行为：

1. 启动后立即执行一轮 `抓取 -> 比对 -> 创建草稿`
2. 后续按 `TENNIS_NEWS_SCHEDULER_INTERVAL_MINUTES` 周期执行，默认每 15 分钟一次
3. 每轮使用独立数据库会话，避免常驻进程中长事务堆积
4. `check-publish-status` 命令保留，但当前默认调度不执行，因为正式发布链路尚未接通

日志观察：

1. 启动日志会输出调度间隔
2. 每轮会输出同步到的赛事数、比赛数、创建任务数、处理任务数
3. 若出现 `retryable` 或 `failed` 发布任务，会输出告警日志

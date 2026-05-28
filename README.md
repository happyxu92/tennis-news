# tennis-news

网球赛事信息采集与微信公众号发布系统。

当前已完成 PRD 第 1-3 阶段基础能力：

1. 项目初始化
2. 数据模型与存储
3. WTA 官方页面抓取接入骨架

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

## 当前数据源状态

当前默认数据源为 `WTA` 官方站页面抓取。

已实现：

1. 通过 `https://api.wtatennis.com/tennis/tournaments/` 抓取赛事列表
2. 通过 `https://api.wtatennis.com/tennis/tournaments/{id}/{year}/matches` 抓取比赛赛程和赛果
3. 将赛事与比赛标准化后落库

暂未实现：

1. `oop` 场地补充数据的完整融合
2. 单场详情接口的深入抓取

说明：`/scores` 页面数据主要由前端异步加载，本项目当前已转为直接调用其内部 WTA API。

# Case 数据格式说明

这里存放**脱敏后**的 SE 真实 case，作为能力建模和题目生成的种子数据。

## 脱敏规则

复制 case 内容前，把以下字段替换成占位符：

| 真实内容 | 占位符 |
|---|---|
| 客户公司名 | `<CUSTOMER>` |
| 客户姓名 / 邮箱 | `<USER>` / `<EMAIL>` |
| AWS 账号 ID（12 位数字） | `<ACCOUNT_ID>` |
| Bucket 名 | `<BUCKET_NAME>` |
| Glue Job 名 | `<JOB_NAME>` |
| Database / Table 名 | `<DB_NAME>` / `<TABLE_NAME>` |
| ARN | `<ARN>` |
| IP 地址 | `<IP>` |
| 任何能定位到客户的 ID | `<XXX_ID>` |

技术细节、报错信息、堆栈、SE 的分析过程都**保留原文**，这些才是建模的核心信息。

## 文件命名

```
glue-001-job-bookmarks-not-working.json
glue-002-spark-oom-on-large-shuffle.json
glue-003-crawler-schema-detection-failed.json
```

格式：`glue-编号-简短英文标题.json`，编号从 001 开始连续。

## 数据 schema

参见 `_template.json`，字段说明：

- `id`：和文件名一致
- `service`：固定 `Glue`（MVP 阶段）
- `title`：一句话概括客户问题
- `severity`：客户报的严重等级，`low` / `normal` / `high` / `urgent`
- `tags`：技术标签数组，比如 `["spark", "memory", "shuffle"]`
- `summary`：3~5 句话总结这个 case 是什么问题、怎么解决的（你写，方便 AI 用）
- `customer_problem`：客户原始描述（脱敏后）
- `conversation`：客户和 SE 的来回沟通，按时间顺序
  - `role`：`customer` 或 `se`
  - `content`：消息内容（脱敏后）
- `resolution`：最终解决方案（脱敏后）
- `key_skills`：你判断这个 case 考察了哪些能力，自由填，比如 `["Spark 内存调优", "Glue Job 配置", "日志分析"]`
- `references`：相关的 KB 链接、官方文档（可选）

## MVP 阶段目标

整理 **5~10 个 Glue case**，覆盖不同子领域：

- [ ] Glue Job 性能 / 资源问题（OOM、慢、Spark 调优）
- [ ] Glue Crawler 问题（schema 识别、分区、增量）
- [ ] Glue Catalog 问题（权限、共享、版本）
- [ ] Glue 与其他服务集成（S3、Redshift、Athena）
- [ ] Glue Job 配置 / IAM 权限问题

每个子领域 1~2 个 case 即可。

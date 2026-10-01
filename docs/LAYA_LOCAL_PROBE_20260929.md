# Laya 本地部署与评分试验（2026-09-29）

## 部署状态

- 独立环境：项目目录下 `.cache/laya-venv`，Laya `0.3.21`，PyTorch `2.14.0+cu132`。
- Hugging Face 权重缓存：项目目录下 `.cache/huggingface`。`uv` 下载缓存、临时文件和 Torch 缓存也指向项目的 `.cache`。
- 只加载 `multilingual` 权重；本次 `/health` 返回 revision `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`、`device=cuda`、`cpu_fallbacks.count=0`。
- 服务地址：`http://127.0.0.1:8011`，绑定本机地址。启动命令（在项目根目录执行）：`& scripts/start_laya_local.ps1`。关闭启动它的终端即可停止。
- 首次下载需要 Hugging Face 网络访问；权重已在 D 盘缓存。Windows 不支持 symlink 时 Hugging Face 会退化成普通文件缓存，可能额外占用 D 盘。
- 部署前后 C 盘可用空间均约 62.4 GiB。D 盘部署后约 135.5 GiB 可用。路径和空间为该电脑本次运行的观测值。

如需重新安装，在项目根目录的 PowerShell 执行以下命令；系统 Python 启动器可以位于 C 盘，环境、依赖缓存与临时文件会写入 D 盘项目目录：

```powershell
$cache = Join-Path (Get-Location) '.cache'
$env:UV_CACHE_DIR = Join-Path $cache 'uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $cache 'python'
$env:TEMP = Join-Path $cache 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
uv venv .cache/laya-venv --python 3.11
uv pip install --python .cache/laya-venv/Scripts/python.exe --torch-backend auto 'laya[serve]==0.3.21' 'httpx[socks]'
```

## 可复现验证

1. `GET http://127.0.0.1:8011/health`：返回 `status=ok`，仅加载多语言模型，运行在 CUDA。
2. 完整样本：`& .cache/laya-venv/Scripts/python.exe backend/app/scripts/evaluate_laya_local.py --output data/evals/runs/another_laya_probe.json`。运行前需将 `HF_HOME` 指向项目 `.cache/huggingface`，或先启动服务并参考 `scripts/start_laya_local.ps1` 中的环境变量。
3. HTTP 小样本：`& .cache/laya-venv/Scripts/python.exe backend/app/scripts/smoke_laya_http.py`。服务需先启动。

原始输出位于 `data/evals/runs/laya_local_glue_probe_10.json`，该目录被 Git 忽略，避免实验结果混入业务记录。输入来自已有的 `data/evals/scoring_quality_flash_20260928.json`，由评测者预先编写；人工标签仅是初步参照，不是独立专家盲评。

## 观察结果

| 试验 | 结果 |
| --- | --- |
| 10 份 Glue 答案：正确 / 部分 / 错误三类选择 | 与既有标签一致 2/10 |
| 简短正确的 Crawler 答案 | Laya 判为错误，等级评分接近最低档 |
| 冗长错误的 Crawler、NAT 答案 | Laya 判为高质量 |
| 3 条简短中文事实表述判断 | 2/3；“先查看日志”被误认为“声称 Crawler 会清洗” |
| 速度 | 已加载后的单份样本约 46–64 ms；新进程首次加载约 13 秒。首次下载不计入稳定推理延迟。 |

该零样本检查覆盖范围很小，但已经出现关键错误答案被高估，因此目前不适合让 Laya 接管正式测评评分。`score` 输出也有明显倒置；官方仓库记录了多语言 `score` 选项位置偏差：[Laya honest limits](https://github.com/NandhaKishorM/laya#honest-limits)。当前正式评分流程没有改动，历史成绩没有重算。

下一步若继续研究，应先建立跨服务、跨难度的人工核验数据，明确每个评分要点的正反例，训练或校准多语言模型，然后在独立保留样本上重点检查错误答案高估率与否定句/缺失证据的误判。只有达到预设质量门槛，才考虑把它用于辅助判定；总分、事实硬规则和报告解释仍须单独验证。

# cycani-watch

追番更新提醒（次元城）。

## 目录

| 路径 | 作用 | 状态 |
| --- | --- | --- |
| `cycani/cycani_watch.py` | 次元城追番提醒（公开接口，无需登录） | 在用，跑在国内 IP 的机器上（cron 每 10 分钟） |
| `archive/` | AniCh、中通签收提醒、早期 Termux 方案 | 已停用归档 |

## 次元城部分

站点按出口 IP 地区限制：国内 IP 正常，美国 IP（GitHub Actions 运行器）返回 403「不提供服务」，所以 Actions 跑不了，只能在国内机器上定时执行。细节见 `cycani/README.md`。

## 跑在哪

国内 IP 的 Linux 机器，cron 条目：

```
*/10 * * * * cd /path/to/cycani && python3 cycani_watch.py >> run.log 2>&1
```

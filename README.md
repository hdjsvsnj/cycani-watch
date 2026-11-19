# cycani-watch

追番更新提醒 + 中通签收提醒。

## 目录

| 路径 | 作用 | 状态 |
| --- | --- | --- |
| `cycani/cycani_watch.py` | 次元城追番提醒（公开接口，无需登录） | 在用，跑在国内 IP 的机器上（cron 每 10 分钟） |
| `zto/zto_watch.py` | 中通签收查询（快递100） | 在用，GitHub Actions 定时 |
| `.github/workflows/zto-watch.yml` | 中通的定时工作流（7/27/47 分） | 在用 |
| `archive/` | AniCh 与早期 Termux 方案，已停用 | 归档 |

## 次元城部分

站点按出口 IP 地区限制：国内 IP 正常，美国 IP（GitHub Actions 运行器）返回 403「不提供服务」，所以 Actions 跑不了，只能在国内机器上定时执行。细节见 `cycani/README.md`。

## 中通部分

`zto-watch.yml` 定时调用快递100 查 `ZTO_WAYBILL` 对应运单，签收后发邮件，状态写入 `zto/`。Secret 需要 `KD100_CUSTOMER`、`KD100_KEY`、`ZTO_WAYBILL`、`ZTO_PHONE`、`CYCANI_SMTP_USER`、`CYCANI_SMTP_PASS`、`CYCANI_MAIL_TO`。

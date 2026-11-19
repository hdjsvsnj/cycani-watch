# 次元城追番提醒

按账号「正在追 / 收藏」列表自动监控：登录站点 → 拉 `/api/user/favorites` → 逐部读 `remarks` 里的集数 → 和基线比对。

- 登录：`POST /api/auth/login`，body `{"username","password"}`，返回 `token`（Bearer）与 `expires_at`
- 追番列表：`GET /api/user/favorites?page=&page_size=50`，带 `Authorization: Bearer <token>`
- 集数：`video.remarks` 前缀数字，如 `06|周五23:35后`
- 必需请求头：`X-App-Name: cyc_web`、浏览器 UA、`Referer: https://www.cycani.org/`

## 行为

| 情况 | 动作 |
| --- | --- |
| 集数变大 | 发一封邮件，更新基线 |
| 集数变小 | 静默重置（换季 / 换字幕组） |
| 新追的番 | 只建基线，不发信 |
| 无变化 | 完全静默 |

token 缓存在 `state.json`，到期前 6 小时自动重登。

## 用法

```
cp config.example.json config.json   # 填 SMTP 授权码、账号密码
python3 cycani_watch.py              # 首跑只建基线
python3 cycani_watch.py --test       # 发一封链路测试邮件
```

`config.json`、`state.json` 已在 `.gitignore` 内，不要入库。

## 定时

```
*/10 * * * * cd /path/to/cycani && python3 cycani_watch.py >> run.log 2>&1
```

站点按出口 IP 地区限制，美国 IP 返回 403「不提供服务」，GitHub Actions 运行器不可用，必须在国内 IP 的机器上跑。

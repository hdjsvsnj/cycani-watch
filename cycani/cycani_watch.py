#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""次元城追番提醒（按账号「正在追」列表）

每轮登录站点（token 缓存，过期前重登），拉 /api/user/favorites 得到正在追的全部番，
逐部解析 remarks 里的集数，和 state.json 的基线比对：
  变大  -> 发一封邮件，更新基线
  变小  -> 静默重置（换季/换字幕组）
  新番  -> 只建基线，不发信
  相同  -> 静默
"""
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
STATE = os.path.join(HERE, "state.json")
API = "https://www.cycani.org/api"
TZ = timezone(timedelta(hours=8))
PAGE_SIZE = 50

HEADERS = {
    "X-App-Name": "cyc_web",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "X-Time-Zone": "Asia/Shanghai",
    "Referer": "https://www.cycani.org/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def api(method, path, body=None, token=None, timeout=25):
    hd = dict(HEADERS)
    if token:
        hd["Authorization"] = token if token.lower().startswith("bearer") else "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hd["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, headers=hd, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as exc:
        print("[warn] %s %s HTTP %s %s" % (method, path, exc.code,
                                           exc.read().decode("utf-8", "ignore")[:200]))
        return None
    except Exception as exc:
        print("[warn] %s %s %r" % (method, path, exc))
        return None


def login(cfg, state):
    """返回可用 token；先用缓存，过期前 6 小时内不依赖缓存"""
    cached = state.get("token") or ""
    exp = state.get("token_exp_ts") or 0
    if cached and exp and time.time() < exp - 6 * 3600:
        return cached
    acct = cfg.get("account") or {}
    user, pwd = acct.get("username"), acct.get("password")
    if not (user and pwd):
        print("[error] config.json 缺少 account.username / account.password")
        return None
    got = api("POST", "/auth/login", {"username": user, "password": pwd}, timeout=30)
    if not got or got.get("code") != 0 or not got.get("data", {}).get("token"):
        print("[error] 登录失败: %s" % (got or {}))
        return None
    data = got["data"]
    state["token"] = data["token"]
    try:
        state["token_exp_ts"] = int(datetime.fromisoformat(
            str(data["expires_at"]).split(".")[0]).replace(tzinfo=TZ).timestamp())
    except Exception:
        state["token_exp_ts"] = int(time.time()) + 7 * 86400
    print("[login] 成功，token 到期 %s" % data.get("expires_at"))
    return state["token"]


def fetch_favorites(token):
    items, page = [], 1
    while page <= 20:
        got = api("GET", "/user/favorites?page=%d&page_size=%d" % (page, PAGE_SIZE), token=token)
        if not got or got.get("code") != 0:
            print("[warn] 收藏列表第 %d 页读取失败" % page)
            break
        data = got.get("data") or {}
        batch = data.get("list") or []
        items.extend(batch)
        pager = data.get("pager") or {}
        if page >= int(pager.get("page") or 1) or len(batch) < PAGE_SIZE:
            break
        page += 1
    return items


def ep_of(remarks):
    if not remarks:
        return None
    m = re.match(r"\s*第?\s*([0-9]+(?:\.[0-9]+)?)", str(remarks))
    if not m:
        m = re.search(r"([0-9]+)", str(remarks))
    if not m:
        return None
    v = float(m.group(1))
    return int(v) if v == int(v) else v


def send_mail(subject, html, text, cfg):
    user = cfg.get("smtp_user") or os.environ.get("SMTP_USER")
    pwd = cfg.get("smtp_pass") or os.environ.get("SMTP_PASS")
    to = cfg.get("mail_to") or os.environ.get("MAIL_TO") or user
    if not (user and pwd and to):
        print("[warn] 邮件配置缺失，跳过发送")
        return False
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((str(Header("次元城追番提醒", "utf-8")), user))
    msg["To"] = to
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=30) as s:
        s.login(user, pwd)
        s.sendmail(user, [to], msg.as_string())
    print("[mail] 已发送: %s" % subject)
    return True


def build_mail(events):
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    rows, lines = [], ["欧尼酱！有番更新啦～", ""]
    for e in events:
        rows.append("<tr><td style='padding:6px 12px'>%s</td><td style='padding:6px 12px'>"
                    "第 %s 话</td></tr>" % (e["title"], e["ep"]))
        lines.append("· 《%s》更新到第 %s 话（%s）" % (e["title"], e["ep"], e["remarks"]))
    lines += ["", "巡检时间：%s" % now]
    html = ("<div style='font-family:-apple-system,Segoe UI,sans-serif'>"
            "<p>欧尼酱！有番更新啦～</p>"
            "<table style='border-collapse:collapse;border:1px solid #eee'>"
            "<tr style='background:#fafafa'><th style='padding:6px 12px;text-align:left'>番剧</th>"
            "<th style='padding:6px 12px;text-align:left'>进度</th></tr>%s</table>"
            "<p style='color:#888;font-size:12px'>巡检时间：%s</p></div>" % ("".join(rows), now))
    subject = "次元城更新：" + "；".join("《%s》第%s话" % (e["title"], e["ep"]) for e in events)
    return subject, html, "\n".join(lines)


def main():
    cfg = load_json(CONFIG, {})
    state = load_json(STATE, {})
    videos = state.get("videos") or {}

    token = login(cfg, state)
    if not token:
        save_json(STATE, state)
        return 1

    favs = fetch_favorites(token)
    if not favs:
        print("[warn] 正在追列表为空或读取失败")
        save_json(STATE, state)
        return 1

    events, seen = [], {}
    for it in favs:
        v = it.get("video") or it
        vid = v.get("video_id") or it.get("video_id")
        if not vid:
            continue
        title = (v.get("title") or "").strip() or str(vid)
        remarks = (v.get("remarks") or "").strip()
        ep = ep_of(remarks)
        key = str(vid)
        seen[key] = {"title": title, "ep": ep, "remarks": remarks}
        prev = videos.get(key)
        if ep is None:
            print("[skip] %s(%s) 集数无法解析: %r" % (title, vid, remarks))
            continue
        if not prev or prev.get("ep") is None:
            print("[init] %s(%s) 基线=%s (%s)" % (title, vid, ep, remarks))
        elif ep > prev["ep"]:
            events.append({"title": title, "ep": ep, "remarks": remarks})
            print("[new] %s(%s) %s -> %s" % (title, vid, prev["ep"], ep))
        elif ep < prev["ep"]:
            print("[reset] %s(%s) %s -> %s 静默重置" % (title, vid, prev["ep"], ep))
        else:
            print("[ok] %s 无更新 (%s)" % (title, ep))

    state["videos"] = seen
    state["last_run"] = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S")
    state["count"] = len(seen)

    if "--test" in sys.argv:
        send_mail("次元城提醒链路测试", "<p>欧尼酱，链路正常～</p>", "欧尼酱，链路正常～", cfg)
    elif events:
        subject, html, text = build_mail(events)
        send_mail(subject, html, text, cfg)

    save_json(STATE, state)
    print("[done] 正在追 %d 部，新增 %d 部" % (len(seen), len(events)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

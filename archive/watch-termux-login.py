#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""次元城动画：自动同步账号收藏，集数变大就发邮件。纯标准库。

配置 config.json（不要提交到公开仓库）：
{
  "smtp_host": "smtp.qq.com", "smtp_port": 465,
  "smtp_user": "...", "smtp_pass": "...", "mail_to": "...",
  "account": {"username": "手机号或邮箱", "password": "站点密码"},
  "watch": [{"id": 123, "title": "手动补充的番剧"}]
}
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

API = "https://www.cycani.org/api"
BASE_HEADERS = {
    "X-App-Name": "cyc_web",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "X-Time-Zone": "Asia/Shanghai",
    "Referer": "https://www.cycani.org/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.environ.get("CYCANI_STATE") or os.path.join(HERE, "state.json")
TZ = timezone(timedelta(hours=8))


def _cfg():
    try:
        with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def request(method, path, body=None, token=None):
    url = API + path
    headers = dict(BASE_HEADERS)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer") else "Bearer " + token
    last_err = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("code") == 0:
                return payload.get("data")
            last_err = f"{payload.get('code')} {payload.get('msg')}"
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
            if exc.code in (403, 429):
                time.sleep(30)
                continue
        except Exception as exc:
            last_err = repr(exc)
        time.sleep(3)
    print(f"[warn] 请求失败 {path}: {last_err}", file=sys.stderr)
    return None


def ep_of(remarks):
    if not remarks:
        return None
    m = re.match(r"\s*(\d+)", str(remarks))
    return int(m.group(1)) if m else None


def item_of(video):
    return {
        "id": int(video.get("video_id") or video.get("id") or 0),
        "title": (video.get("title") or "").strip(),
        "remarks": (video.get("remarks") or "").strip(),
        "ep": ep_of(video.get("remarks")),
        "total": video.get("total") or 0,
    }


def login():
    cfg = _cfg()
    if os.environ.get("CYCANI_USER"):
        acct = {"username": os.environ.get("CYCANI_USER"),
                "password": os.environ.get("CYCANI_PASS")}
    else:
        acct = cfg.get("account") or {}
    if not acct.get("username") or not acct.get("password"):
        return None
    data = request("POST", "/auth/login", body={
        "username": acct["username"], "password": acct["password"],
    })
    if not data or not data.get("token"):
        print("[warn] 登录失败，本轮只按手动名单监控", file=sys.stderr)
        return None
    return {"token": data["token"], "expires_at": data.get("expires_at")}


def token_ok(state):
    tok = state.get("token")
    if not tok:
        return None
    exp = tok.get("expires_at")
    if exp:
        try:
            dt = datetime.fromisoformat(exp)
            if dt - datetime.now(TZ) > timedelta(hours=6):
                return tok.get("token")
        except Exception:
            pass
    return None


def fetch_favorites(token):
    out = {}
    page = 1
    while page <= 20:
        data = request("GET", f"/user/favorites?page={page}&page_size=50", token=token)
        if not data:
            break
        items = data.get("list") or []
        for it in items:
            item = item_of(it.get("video") or {})
            if item["id"]:
                out[str(item["id"])] = item
        pager = data.get("pager") or {}
        if page >= (pager.get("page") or 1) or len(items) < 50:
            break
        page += 1
    return out


def manual_targets():
    cfg = _cfg()
    items = cfg.get("watch") or cfg.get("watch_ids") or []
    out = []
    for it in items:
        if isinstance(it, int):
            out.append({"id": it})
        elif isinstance(it, dict) and it.get("id"):
            out.append({"id": int(it["id"]), "title": (it.get("title") or "").strip()})
        elif isinstance(it, str) and it.strip().isdigit():
            out.append({"id": int(it.strip())})
    return out


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            st = json.load(fh)
        if isinstance(st.get("videos"), dict):
            st.setdefault("token", None)
            return st
    except Exception:
        pass
    return {"videos": {}, "last_run": None, "token": None}


def save_state(st):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, STATE_FILE)


def build_mail(events):
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    if len(events) == 1:
        subject = f"次元城更新：{events[0]['title']} 第{events[0]['ep']:02d}集"
    else:
        subject = f"次元城更新：{len(events)} 部收藏番剧有新集"
    rows = []
    for e in events:
        ep_txt = f"{e['old_ep']:02d} → {e['ep']:02d}" if e.get("old_ep") is not None else (e["remarks"] or "-")
        rows.append("<tr>"
                    f'<td style="padding:8px;border-bottom:1px solid #eee">{e["title"]}</td>'
                    f'<td style="padding:8px;border-bottom:1px solid #eee">{ep_txt}</td>'
                    f'<td style="padding:8px;border-bottom:1px solid #eee;color:#888">{e["remarks"]}</td>'
                    "</tr>")
    html = ('<html><body style="font-family:-apple-system,Segoe UI,Microsoft YaHei,sans-serif;color:#222">'
            f"<p>你收藏的番剧有新集了（{now}）。</p>"
            '<table style="border-collapse:collapse;font-size:14px"><thead><tr style="background:#f5f5f5">'
            '<th style="padding:8px;text-align:left">番剧</th>'
            '<th style="padding:8px;text-align:left">进度</th>'
            '<th style="padding:8px;text-align:left">站点标注</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            '<p style="color:#999;font-size:12px">本邮件由自动巡检脚本发送。</p></body></html>')
    lines = [f"你收藏的番剧有新集了（{now}）", ""]
    for e in events:
        lines.append(f"{e['title']}  第{e['ep']:02d}集  （{e['remarks']}）")
    return subject, html, "\n".join(lines)


def send_mail(subject, html, text):
    cfg = _cfg()
    host = os.environ.get("CYCANI_SMTP_HOST") or cfg.get("smtp_host") or "smtp.qq.com"
    port = int(os.environ.get("CYCANI_SMTP_PORT") or cfg.get("smtp_port") or 465)
    user = os.environ.get("CYCANI_SMTP_USER") or cfg.get("smtp_user")
    password = os.environ.get("CYCANI_SMTP_PASS") or cfg.get("smtp_pass")
    if not user or not password:
        raise RuntimeError("缺少发信账号")
    mail_to = os.environ.get("CYCANI_MAIL_TO") or cfg.get("mail_to") or user
    mail_from = os.environ.get("CYCANI_MAIL_FROM") or cfg.get("mail_from") or user
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("次元城监控", "utf-8")), mail_from))
    msg["To"] = mail_to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls()
    try:
        server.login(user, password)
        server.sendmail(mail_from, [x.strip() for x in mail_to.split(",") if x.strip()], msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass


def main():
    init = "--init" in sys.argv
    dry = "--dry-run" in sys.argv
    state = load_state()

    snaps = []
    token = token_ok(state)
    if token is None:
        tok = login()
        if tok:
            state["token"] = tok
            token = tok["token"]
    if token:
        favs = fetch_favorites(token)
        if favs:
            snaps.extend(favs.values())
            print(f"[sync] 收藏 {len(favs)} 部")
        else:
            print("[warn] 收藏列表为空或读取失败", file=sys.stderr)

    seen = {str(s["id"]) for s in snaps}
    for entry in manual_targets():
        if str(entry["id"]) in seen:
            continue
        data = request("GET", f"/videos/{entry['id']}")
        if data:
            snaps.append(item_of(data))

    if not snaps:
        print("[error] 未取到任何番剧，本轮跳过", file=sys.stderr)
        return 1

    if init or not state["videos"]:
        state["videos"] = {str(s["id"]): s for s in snaps}
        state["last_run"] = datetime.now(TZ).isoformat(timespec="seconds")
        save_state(state)
        print("[init] 基线：" + "、".join(f"{s['title']} 第{s['ep']}集" for s in snaps))
        return 0

    events, merged = [], dict(state["videos"])
    for s in snaps:
        prev = state["videos"].get(str(s["id"])) or {}
        if s["ep"] is not None and (prev.get("ep") is None or s["ep"] > prev["ep"]):
            events.append({"title": s["title"], "ep": s["ep"], "old_ep": prev.get("ep"),
                           "remarks": s["remarks"], "total": s["total"]})
        merged[str(s["id"])] = s

    if not events:
        state["videos"] = merged
        state["last_run"] = datetime.now(TZ).isoformat(timespec="seconds")
        save_state(state)
        print(f"[ok] 无更新（{len(snaps)} 部：" + "、".join(f"{s['title']} {s['remarks']}" for s in snaps) + "）")
        return 0

    subject, html, text = build_mail(events)
    print(f"[found] {len(events)} 条更新")
    print(text)
    if dry:
        return 0
    try:
        send_mail(subject, html, text)
    except Exception as exc:
        print(f"[error] 发信失败，基线不变：{exc}", file=sys.stderr)
        return 1
    state["videos"] = merged
    state["last_run"] = datetime.now(TZ).isoformat(timespec="seconds")
    save_state(state)
    print("[sent] 邮件已发送")
    return 0


if __name__ == "__main__":
    sys.exit(main())

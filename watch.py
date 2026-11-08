#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""次元城动画：只监控指定收藏番剧，集数变大时发邮件。纯标准库。"""

import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

API = "https://www.cycani.org/api"
HEADERS = {
    "X-App-Name": "cyc_web",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.cycani.org/",
    "Origin": "https://www.cycani.org",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.environ.get("CYCANI_STATE") or os.path.join(HERE, "state.json")
TZ = timezone(timedelta(hours=8))
DEFAULT_WATCH = [{"id": 3945, "title": "魔法少女育成计划 restart"}]


def _cfg():
    try:
        with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def api_get(path):
    url = API + path
    last_err = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("code") == 0:
                return payload.get("data")
            last_err = payload.get("msg")
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


def watch_list():
    cfg = _cfg()
    raw = os.environ.get("CYCANI_WATCH_IDS")
    if raw:
        return [{"id": int(x), "title": ""} for x in raw.split(",") if x.strip().isdigit()]
    items = cfg.get("watch") or cfg.get("watch_ids") or DEFAULT_WATCH
    out = []
    for it in items:
        if isinstance(it, int):
            out.append({"id": it, "title": ""})
        elif isinstance(it, dict) and it.get("id"):
            out.append({"id": int(it["id"]), "title": (it.get("title") or "").strip()})
        elif isinstance(it, str) and it.strip().isdigit():
            out.append({"id": int(it.strip()), "title": ""})
    return out or DEFAULT_WATCH


def fetch_one(entry):
    data = api_get(f"/videos/{entry['id']}")
    if not data:
        return None
    return {
        "id": int(entry["id"]),
        "title": (data.get("title") or entry.get("title") or "").strip(),
        "remarks": (data.get("remarks") or "").strip(),
        "ep": ep_of(data.get("remarks")),
        "total": data.get("total") or 0,
        "completed": bool(data.get("completed")),
    }


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        if isinstance(state.get("videos"), dict):
            return state
    except Exception:
        pass
    return {"videos": {}, "last_run": None}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
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
    snaps = [s for s in (fetch_one(e) for e in watch_list()) if s]
    if not snaps:
        print("[error] 未取到数据，跳过")
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
        print("[ok] 无更新：" + "、".join(f"{s['title']} {s['remarks']}" for s in snaps))
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

# -*- coding: utf-8 -*-
"""腾讯云 SCF：次元城「正在追」集数变化 → QQ 邮件

环境变量：
  CYCANI_USER / CYCANI_PASS   次元城账号
  SMTP_USER / SMTP_PASS / MAIL_TO
  GH_TOKEN / GH_REPO / GH_PATH  （基线文件，默认 hdjsvsnj/cycani-watch / cycani/state.json）
"""
import base64
import json
import os
import re
import smtplib
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

API = "https://www.cycani.org/api"
GH = "https://api.github.com"
TZ = timezone(timedelta(hours=8))
TOK_PATH = "/tmp/cycani_tok.json"
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


def req_json(method, url, body=None, headers=None, timeout=15):
    hd = {"Accept": "application/json"}
    if headers:
        hd.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hd["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=hd, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def api(method, path, body=None, token=None, timeout=15):
    hd = dict(HEADERS)
    if token:
        hd["Authorization"] = token if token.lower().startswith("bearer") else "Bearer " + token
    try:
        return req_json(method, API + path, body=body, headers=hd, timeout=timeout)
    except urllib.error.HTTPError as exc:
        print("[warn] %s %s HTTP %s %s" % (method, path, exc.code,
                                           exc.read().decode("utf-8", "ignore")[:150]))
        return None
    except Exception as exc:
        print("[warn] %s %s %r" % (method, path, exc))
        return None


def _load_tok():
    try:
        with open(TOK_PATH, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("token") and d.get("exp", 0) > time.time() + 3600:
            return d["token"]
    except Exception:
        pass
    return None


def _save_tok(token, exp):
    try:
        with open(TOK_PATH, "w", encoding="utf-8") as fh:
            json.dump({"token": token, "exp": exp}, fh)
    except Exception:
        pass


def login():
    tk = _load_tok()
    if tk:
        return tk
    user, pwd = os.environ.get("CYCANI_USER"), os.environ.get("CYCANI_PASS")
    if not (user and pwd):
        print("[error] 缺 CYCANI_USER / CYCANI_PASS")
        return None
    got = api("POST", "/auth/login", {"username": user, "password": pwd}, timeout=20)
    if not got or got.get("code") != 0 or not (got.get("data") or {}).get("token"):
        print("[error] 登录失败: %s" % (str(got)[:200],))
        return None
    data = got["data"]
    exp = int(time.time()) + 7 * 86400
    try:
        exp = int(datetime.fromisoformat(str(data["expires_at"]).split(".")[0]
                                          .replace("Z", "")).replace(tzinfo=TZ).timestamp())
    except Exception:
        pass
    _save_tok(data["token"], exp)
    print("[login] 成功，到期 %s" % data.get("expires_at"))
    return data["token"]


def fetch_favorites(token):
    items, page = [], 1
    while page <= 20:
        got = api("GET", "/user/favorites?page=%d&page_size=%d" % (page, PAGE_SIZE), token=token)
        if not got or got.get("code") != 0:
            print("[warn] 收藏列表第 %d 页失败" % page)
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


def gh_headers():
    return {"Authorization": "token %s" % os.environ.get("GH_TOKEN", ""),
            "User-Agent": "cycani-scf"}


def gh_load():
    repo = os.environ.get("GH_REPO") or "hdjsvsnj/cycani-watch"
    path = os.environ.get("GH_PATH") or "cycani/state.json"
    if not os.environ.get("GH_TOKEN"):
        print("[warn] 缺 GH_TOKEN，基线只在本实例内存")
        return {}, None
    try:
        got = req_json("GET", "%s/repos/%s/contents/%s" % (GH, repo, path), headers=gh_headers(), timeout=15)
        content = base64.b64decode(got.get("content") or "").decode("utf-8")
        st = json.loads(content)
        vids = dict(st.get("videos") or {})
        vids.pop("_last_mail", None)
        return vids, got.get("sha")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}, None
        print("[warn] 读基线 HTTP %s" % exc.code)
        return {}, None
    except Exception as exc:
        print("[warn] 读基线失败 %r" % (exc,))
        return {}, None


def gh_save(videos, sha, last_run):
    repo = os.environ.get("GH_REPO") or "hdjsvsnj/cycani-watch"
    path = os.environ.get("GH_PATH") or "cycani/state.json"
    if not os.environ.get("GH_TOKEN"):
        return False
    payload = {"videos": videos, "last_run": last_run}
    content = base64.b64encode(json.dumps(payload, ensure_ascii=False, indent=2).encode()).decode()
    body = {"message": "chore: 更新次元城基线 %s" % last_run, "content": content}
    if sha:
        body["sha"] = sha
    try:
        req_json("PUT", "%s/repos/%s/contents/%s" % (GH, repo, path), body=body,
                 headers=gh_headers(), timeout=20)
        return True
    except Exception as exc:
        print("[warn] 写基线失败 %r" % (exc,))
        return False


def send_mail(events):
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_PASS")
    to = os.environ.get("MAIL_TO") or user
    if not (user and pwd):
        print("[warn] 缺 SMTP 配置，跳过发信")
        return False
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    rows, lines = [], ["欧尼酱！有番更新啦～", ""]
    for e in events:
        rows.append("<tr><td style='padding:6px 12px'>%s</td><td style='padding:6px 12px'>第 %s 话</td></tr>"
                    % (e["title"], e["ep"]))
        lines.append("· 《%s》更新到第 %s 话（%s）" % (e["title"], e["ep"], e["remarks"]))
    lines += ["", "巡检时间：%s" % now]
    subject = "次元城更新：" + "；".join("《%s》第%s话" % (e["title"], e["ep"]) for e in events)
    html = ("<div style='font-family:-apple-system,Segoe UI,sans-serif'><p>欧尼酱！有番更新啦～</p>"
            "<table style='border-collapse:collapse;border:1px solid #eee'>"
            "<tr style='background:#fafafa'><th style='padding:6px 12px;text-align:left'>番剧</th>"
            "<th style='padding:6px 12px;text-align:left'>进度</th></tr>%s</table>"
            "<p style='color:#888;font-size:12px'>巡检时间：%s</p></div>" % ("".join(rows), now))
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((str(Header("次元城追番提醒", "utf-8")), user))
    msg["To"] = to
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText("\n".join(lines), "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=20) as s:
        s.login(user, pwd)
        s.sendmail(user, [to], msg.as_string())
    print("[mail] 已发送: %s" % subject)
    return True


def main_handler(event, context):
    token = login()
    if not token:
        return {"ok": False, "reason": "login"}
    favs = fetch_favorites(token)
    if not favs:
        return {"ok": False, "reason": "no_favorites"}

    videos, sha = gh_load()
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
            continue
        if not prev or prev.get("ep") is None:
            print("[init] %s(%s) 基线=%s" % (title, vid, ep))
        elif ep > prev["ep"]:
            events.append({"title": title, "ep": ep, "remarks": remarks})
            print("[new] %s(%s) %s -> %s" % (title, vid, prev["ep"], ep))
        elif ep < prev["ep"]:
            print("[reset] %s(%s) %s -> %s" % (title, vid, prev["ep"], ep))
        else:
            print("[ok] %s %s" % (title, ep))

    last_run = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S")
    mailed, mail_err = False, ""
    if events:
        try:
            mailed = send_mail(events)
        except Exception as exc:
            mail_err = repr(exc)[:200]
            print("[error] 发信失败: %s" % mail_err)
    if events:
        seen["_last_mail"] = {"time": last_run, "events": [e["title"] + " " + str(e["ep"]) for e in events],
                              "ok": mailed, "error": mail_err}
    clean = {k: v for k, v in seen.items() if not k.startswith("_")}
    changed = clean != videos
    saved = gh_save(seen, sha, last_run) if changed else False
    print("[done] 追番 %d 部 更新 %d 部 基线写回 %s" % (len(seen), len(events), saved))
    return {"ok": True, "count": len(seen), "updates": [e["title"] for e in events],
            "mailed": mailed, "state_saved": saved}

#!/data/data/com.termux/files/usr/bin/bash
# 安卓 Termux 一键安装：只监控收藏番剧，集数变大时发 QQ 邮件
set -e
echo "== 安装依赖 =="
pkg update -y >/dev/null 2>&1 || true
pkg install -y python curl >/dev/null 2>&1 || true

mkdir -p "$HOME/cycani"
cd "$HOME/cycani"

echo "== 下载脚本 =="
curl -fsSL https://raw.githubusercontent.com/hdjsvsnj/cycani-watch/main/watch.py -o watch.py

echo "== 写配置 =="
cat > config.json <<'EOF'
{
  "smtp_host": "smtp.qq.com",
  "smtp_port": 465,
  "smtp_user": "1250712498@qq.com",
  "mail_to": "1250712498@qq.com",
  "watch": [{"id": 3945, "title": "魔法少女育成计划 restart"}]
}
EOF
read -rsp "粘贴 QQ 邮箱 16 位授权码: " pass
echo
python3 - "$pass" <<'PY'
import json, sys
cfg = json.load(open('config.json', encoding='utf-8'))
cfg['smtp_pass'] = sys.argv[1].strip()
json.dump(cfg, open('config.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('授权码已写入 config.json')
PY
chmod 600 config.json

echo "== 建立基线 =="
python3 watch.py --init

cat > run.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null || true
cd "$HOME/cycani"
while true; do
  python3 watch.py >> run.log 2>&1
  sleep 60
done
EOF
chmod +x run.sh

echo
echo "== 完成 =="
echo "现在后台常驻：nohup ./run.sh >/dev/null 2>&1 &"
echo "开机自启：安装 Termux:Boot 后执行 mkdir -p ~/.termux/boot 并把 run.sh 软链进去"

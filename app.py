"""Personal Growth OS · 精简版单文件应用

一个文件搞定：数据库 / API / 网页 / 调度 / 推送。
支持双模式：有 DATABASE_URL 环境变量 → PostgreSQL（云端部署）；否则 SQLite（本地）。
"""
import sqlite3, json, os, re, threading, random, urllib.request, urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import apscheduler.schedulers.background as bg

BASE = Path(__file__).resolve().parent
DB = BASE / "growth.db"
WEB = BASE / "web"
TZ = ZoneInfo("Asia/Shanghai")

# 云端部署时在 Render 环境变量里配置 DATABASE_URL / NTFY_TOPIC / WEB_URL
DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_PG = bool(DATABASE_URL)
CONFIG = {
    "ntfy_topic": os.environ.get("NTFY_TOPIC", "topic_workbuddy"),
    "web_url": os.environ.get("WEB_URL", "https://aa794e79a5c6e2821.app.workbuddy.link"),
}

# ==================== 数据库（SQLite / PostgreSQL 双模式） ====================
_local = threading.local()

def db():
    c = getattr(_local, "conn", None)
    if c is not None and (not IS_PG or not c.closed):
        return c
    if IS_PG:
        import psycopg2
        c = psycopg2.connect(DATABASE_URL)
        c.autocommit = False
        _local.conn = c
    else:
        c = sqlite3.connect(str(DB), timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _local.conn = c
    return c

def _exec(sql, p=()):
    """统一执行入口：PG 用 RealDictCursor（fetchall 返回 dict 行）；失败自动回滚防连接报废"""
    if IS_PG:
        import psycopg2.extras
        try:
            cur = db().cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql, p)
            return cur
        except Exception:
            try: db().rollback()
            except Exception: pass
            raise
    return db().execute(sql, p)

def _sql(sql):
    """SQLite 风格 ? 占位符统一转换为 PostgreSQL 的 %s"""
    return sql.replace("?", "%s") if IS_PG else sql

def q(sql, p=()):
    cur = _exec(_sql(sql), p)
    return [dict(r) for r in cur.fetchall()]

def q1(sql, p=()):
    r = q(sql, p); return r[0] if r else None

def x(sql, p=()):
    cur = _exec(_sql(sql), p)
    db().commit()
    return getattr(cur, "lastrowid", None)

def now(): return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
def today(): return datetime.now(TZ).date().isoformat()
def J(o): return json.dumps(o, ensure_ascii=False)
def P(s, d=None):
    if not s: return d
    try: return json.loads(s)
    except: return d

# ==================== 庆祝话术（随机触发，纯代码不吃积分） ====================
CELEBRATIONS = [
    ("🎉 今日全部完成！", "你今天把该做的都落地了，享受胜利吧。"),
    ("🎉 全绿收工！", "每一项都划掉了，今天做得很漂亮。"),
    ("🏆 今日满分！", "没有一项欠账，这就是复利的样子。"),
    ("🎯 今日全中！", "你又一次做到了说到做到。"),
    ("✨ 今日清零！", "任务清单干干净净，剩下时间都是你的。"),
    ("🔥 全数完成！", "今天没有给拖延留机会，够硬气。"),
    ("🌱 今日达成！", "又向英语和 FAE 走近了一步。"),
    ("💪 收工漂亮！", "把该做的都做完了，明天从更高处开始。"),
    ("⭐ 全勤今日！", "坚持的人不多，今天你是其中之一。"),
    ("🫵 今日靠谱！", "你不是完成了一个任务，是给未来的自己加了信用。"),
]

def random_celebrate():
    title, body = random.choice(CELEBRATIONS)
    push(title, body, click=f"{CONFIG['web_url']}/?today")

# ==================== 推送 ====================
def push(title, body, click=None):
    """ntfy 推送：JSON publishing（中文标题放 body，无 header 编码问题）"""
    payload = {"topic": CONFIG["ntfy_topic"], "title": title, "message": body, "tags": ["bell"]}
    if click:
        payload["click"] = click
    req = urllib.request.Request("https://ntfy.sh/",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[push] 发送失败: {e}", flush=True)
        return False

# ==================== 初始化（双方言 schema） ====================
def init_db():
    schema = (BASE / "schema.sql").read_text(encoding="utf-8")
    if IS_PG:
        # PostgreSQL 方言转换：自增主键 / 去掉 PRAGMA / OR REPLACE 语法
        schema = (schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
                        .replace("INSERT OR REPLACE INTO reviews", "INSERT INTO reviews"))
        stmts = [s.strip() for s in schema.split(";") if s.strip()]
        # 带行内注释的语句块过滤注释行
        clean = []
        for s in stmts:
            lines = [ln for ln in s.splitlines() if not ln.strip().startswith("--")]
            s2 = "\n".join(lines).strip()
            if s2 and not s2.upper().startswith("PRAGMA"):
                clean.append(s2)
        for s in clean:
            try: _exec(s)
            except Exception as e:
                if "already exists" not in str(e): raise
        try: _exec("ALTER TABLE tasks ADD COLUMN advanced INTEGER DEFAULT 0")
        except Exception: pass
        try: _exec("ALTER TABLE plans ADD COLUMN start_date TEXT")
        except Exception: pass
        db().commit()
    else:
        db().executescript(schema)
        try: db().execute("ALTER TABLE tasks ADD COLUMN advanced INTEGER DEFAULT 0")
        except Exception: pass
        try: db().execute("ALTER TABLE plans ADD COLUMN start_date TEXT")
        except Exception: pass
        db().commit()
    # 数据迁移：若 pgos_seed.json 存在且 plans 为空，自动恢复进度/新闻/周报
    seedf = BASE / "pgos_seed.json"
    if seedf.exists() and q1("SELECT COUNT(*) AS n FROM plans")["n"] == 0:
        data = json.loads(seedf.read_text(encoding="utf-8"))
        sd = today()
        for p in data.get("plans", []):
            if not p.get("start_date"):
                p["start_date"] = sd
            cols = ",".join(p.keys()); ph = ",".join("?"*len(p))
            x(f"INSERT INTO plans({cols}) VALUES({ph})", tuple(p.values()))
        for t in data.get("tasks", []):
            cols = ",".join(t.keys()); ph = ",".join("?"*len(t))
            x(f"INSERT INTO tasks({cols}) VALUES({ph})", tuple(t.values()))
        for r in data.get("reviews", []):
            x("INSERT INTO reviews(week_start,content_md,content_html,created_at) VALUES(?,?,?,?)",
              (r["week_start"], r["content_md"], r["content_html"], r["created_at"]))
        print(f"[seed] 已从 pgos_seed.json 恢复 {len(data.get('plans',[]))} 计划 / {len(data.get('tasks',[]))} 任务 / {len(data.get('reviews',[]))} 周报", flush=True)

# ==================== 种子：长期计划录入 ====================
def seed():
    if q1("SELECT COUNT(*) AS n FROM plans")["n"] > 0:
        return
    t = now()
    fae_route = [
        {"w":1,"u":"C语言基础"},{"w":2,"u":"C语言基础"},{"w":3,"u":"数组、字符串、函数"},
        {"w":4,"u":"指针、struct、头文件"},{"w":5,"u":"电路基础+原理图"},{"w":6,"u":"STM32环境+GPIO"},
        {"w":7,"u":"GPIO输入+中断"},{"w":8,"u":"USART串口"},{"w":9,"u":"串口深化"},
        {"w":10,"u":"ESP8266手动调试"},{"w":11,"u":"STM32+ESP8266"},{"w":12,"u":"网络基础+Linux"},
        {"w":13,"u":"HTTP请求"},{"w":14,"u":"项目整合"},{"w":15,"u":"项目优化"},
        {"w":16,"u":"项目验收"},{"w":17,"u":"3款核心产品"},{"w":18,"u":"竞品分析"},
        {"w":19,"u":"需求分析案例"},{"w":20,"u":"选型案例"},{"w":21,"u":"Linux补完"},
        {"w":22,"u":"技术英语"},{"w":23,"u":"面试准备"},{"w":24,"u":"投递"},
    ]
    plans = [
        {"id":"english","name":"English","goal":"A1+ → IELTS 6.5 / CEFR B2（18~22个月）",
         "normal":"3h","minimum":"1h","frequency":"每天",
         "route":J(["家庭与人际","工作与日常","爱好与休闲","时间与生活","交通与出行","购物与消费",
                    "地点与城市","天气与季节","食物与饮食","健康与身体","综合描述","综合复习"]),
         "checkpoints":J([{"name":"阶段0验证","period":"第3个月末","criteria":"200题≥75%+50句+1500词+30秒口语"}]),
         "extra":J({"daily_structure":"1h输入(语法+20词+对话) / 1h内化(10句关于自己) / 1h输出(改写+录音)",
                     "review":"2/4/7天复习","test":"周测不通过→重复本周"}),
         "cur_week":1,"cur_day":1,"cur_topic":"家庭与人际","cur_unit":"Day 1：输入",
         "pending":J(["Day 1：输入","Day 2：内化","Day 3：输出"]),
         "next_cp":"阶段0验证（第3个月末）","updated_at":t},
        {"id":"fae","name":"FAE 技术学习","goal":"6个月系统学习，具备应聘 FAE 助理/技术支持/技术销售的基础能力",
         "normal":"2h","minimum":"完成一个最小任务即可","frequency":"每周6天",
         "route":J(fae_route),
         "checkpoints":J([{"w":4,"name":"C语言"},{"w":8,"name":"串口"},{"w":9,"name":"串口生死线","critical":True},
                          {"w":12,"name":"Linux"},{"w":16,"name":"项目验收"},{"w":20,"name":"选型"},{"w":24,"name":"面试"}]),
         "extra":J({"rules":"只用Keel；Week9不过必须提醒用户做决策"}),
         "cur_week":1,"cur_day":0,"cur_topic":None,"cur_unit":"C语言基础",
         "pending":J([f"Week {r['w']}：{r['u']}" for r in fae_route]),
         "next_cp":"Week 4：C语言","updated_at":t},
        {"id":"exercise","name":"运动","goal":"每周5天，力量训练+跳舞","normal":"去了就算完成",
         "minimum":None,"frequency":"每周5天","route":J([]),"checkpoints":J([]),"extra":J({}),
         "cur_week":None,"cur_day":None,"cur_topic":None,"cur_unit":None,
         "pending":J([]),"next_cp":None,"updated_at":t},
        {"id":"content","name":"自媒体视频输出","goal":"每天输出 1 条自媒体视频（选题自定）","normal":"每天",
         "minimum":None,"frequency":"每天","route":J([]),"checkpoints":J([]),
         "extra":J({"output_count":15}),
         "cur_week":None,"cur_day":None,"cur_topic":None,"cur_unit":None,
         "pending":J([]),"next_cp":None,"updated_at":t},
    ]
    sd = today()
    for p in plans:
        p["start_date"] = sd
        cols = ",".join(p.keys())
        ph = ",".join("?"*len(p))
        x(f"INSERT INTO plans({cols}) VALUES({ph})", tuple(p.values()))

# ==================== 计划周期工具 ====================
# 各计划的周期（用于倒推结束日期 / 剩余天数）
PLAN_PERIODS = {
    "english": {"months": 18, "label": "18个月", "nodes": ["阶段0：基础重建","阶段1：旅行场景","阶段2：工作沟通","阶段3：雅思输入","阶段4：雅思输出","阶段5：冲刺B2"]},
    "fae":     {"months": 6,  "label": "6个月",  "nodes": ["C语言+电路+STM32+串口","通信+WiFi+Linux+项目","产品选型+需求分析+面试"]},
}

def _month_add(d, months):
    """日期 + N 个月（近似：按 30 天/月，避免复杂闰月计算）"""
    return d + timedelta(days=30 * months)

def plan_period(plan):
    """返回计划的起止日期与剩余信息"""
    sid = plan.get("id")
    meta = PLAN_PERIODS.get(sid)
    # 起点：优先用数据库记录的 start_date，否则用今天
    sd = None
    if plan.get("start_date"):
        try: sd = date.fromisoformat(str(plan["start_date"])[:10])
        except Exception: sd = None
    if sd is None:
        sd = datetime.now(TZ).date()
    today_d = datetime.now(TZ).date()
    if meta:
        ed = _month_add(sd, meta["months"])
        total_days = (ed - sd).days
        # 当前已完成的天数：按 start_date 到今天的自然日（近似进度）
        elapsed = max(0, (today_d - sd).days)
        remaining = max(0, (ed - today_d).days)
        pct = round(elapsed * 100 / total_days) if total_days else 0
        return {"start": sd.isoformat(), "end": ed.isoformat(),
                "total_days": total_days, "elapsed": elapsed, "remaining": remaining,
                "pct": min(100, pct), "period_label": meta["label"], "nodes": meta["nodes"]}
    return {"start": sd.isoformat(), "end": None, "total_days": None,
            "elapsed": 0, "remaining": None, "pct": None, "period_label": None, "nodes": []}

# ==================== 今日任务生成（08:00 进度驱动）====================
def gen_today(force=False):
    td = today()
    if not force and q1("SELECT COUNT(*) AS n FROM tasks WHERE task_date=? AND type='long_term'", (td,))["n"] > 0:
        return {"created": 0, "skipped": True}

    # 跨天未完成 → postponed
    y = (datetime.now(TZ).date() - timedelta(days=1)).isoformat()
    for t in q("SELECT id FROM tasks WHERE task_date<? AND type='long_term' AND status IN ('pending','in_progress')", (y,)):
        x("UPDATE tasks SET status='postponed' WHERE id=?", (t["id"],))

    d = datetime.now(TZ).date()
    created = 0
    def add(title, pid, dur, notes=None, pri="normal"):
        nonlocal created
        seq = len(q("SELECT id FROM tasks WHERE id LIKE ?", (f"t_{td.replace('-','')}_%",))) + 1
        tid = f"t_{td.replace('-','')}_{seq:03d}"
        x("INSERT INTO tasks(id,title,type,plan_id,task_date,status,priority,duration,notes,created_at) VALUES(?,?,'long_term',?,?,?,?,?,?,?)",
          (tid, title, pid, td, "pending", pri, dur, notes, now()))
        created += 1

    plans = {p["id"]: p for p in q("SELECT * FROM plans")}
    for pid, p in plans.items():
        if pid == "english":
            # 一个任务 = 一整天三段（1h输入 / 1h内化 / 1h输出）
            pending = P(p["pending"], [])
            notes = (f"当前位置：阶段0 · 主题周{p['cur_week']} · Day {p['cur_day']}（{p['cur_topic']}）\n"
                     f"今日三段：{' / '.join(pending[:3])}\n"
                     f"结构：1h输入(语法+20词+对话) / 1h内化(10句关于自己) / 1h输出(改写+录音)\n"
                     f"复习：2/4/7天节奏\n检查点：{p['next_cp'] or '无'}")
            add(f"English · Day {p['cur_day']}（{p['cur_topic']}）", pid, p["normal"], notes)
        elif pid == "fae":
            pending = P(p["pending"], [])
            focus = pending[0] if pending else p["cur_unit"]
            cps = P(p["checkpoints"], [])
            pri, note = "normal", f"当前位置：Week {p['cur_week']}（{p['cur_unit']}）· 本周已学 {p['cur_day'] or 0}/6 天"
            for cp in cps:
                w = cp.get("w")
                if isinstance(w, int) and w >= (p["cur_week"] or 1):
                    dist = w - (p["cur_week"] or 1)
                    if dist <= 2:
                        pri = "high"
                        note += f"\n⚠️ 检查点临近：Week {w} {cp['name']}（还差 {dist} 周），今日优先保证达标"
                    else:
                        note += f"\n检查点：Week {w} {cp['name']}（还差 {dist} 周）"
                    break
            add(f"FAE · {focus}", pid, p["normal"], note, pri)
        elif pid == "exercise":
            if d.weekday() < 5:
                add("运动 · 力量训练/跳舞（去了就算完成）", pid, "45min")
        elif pid == "content":
            # 自媒体视频输出：每天都有（选题自定，不做具体内容生成）
            add("自媒体视频 · 输出 1 条（选题自定）", pid, "1h",
                "每天 1 条；选题/脚本/剪辑由你自己安排，本任务只负责提醒与记录")

    if created > 0:
        push("今日任务已生成",
             f"共 {created} 项任务，点击查看详情",
             click=f"{CONFIG['web_url']}/?today")
    return {"created": created, "skipped": False}

# ==================== 当前位置推进（完成长期任务时调用）====================
def advance(pid):
    p = q1("SELECT * FROM plans WHERE id=?", (pid,))
    if not p: return
    if pid == "english":
        # 一天 = 输入+内化+输出 三段合一，完成当天任务即进入下一天
        day = (p["cur_day"] or 0) + 1
        week = p["cur_week"] or 1
        topics = P(p["route"], [])
        if day > 7:
            day, week = 1, week + 1
            if week > len(topics): week = len(topics)
        topic = topics[week-1] if topics and week <= len(topics) else p["cur_topic"]
        pending = [f"Day {day}：输入", f"Day {day}：内化", f"Day {day}：输出"]
        x("UPDATE plans SET cur_week=?,cur_day=?,cur_topic=?,cur_unit=?,pending=?,updated_at=? WHERE id=?",
          (week, day, topic, f"Day {day}", J(pending), now(), pid))
    elif pid == "fae":
        # 每周 6 个学习日：当天完成 → 本周已学 +1；学满 6 天才推进到下一周（未满则停留原周）
        pday = (p["cur_day"] or 0) + 1
        pending = P(p["pending"], [])
        week = p["cur_week"] or 1
        if pday >= 6 and pending:
            done = pending.pop(0)
            m = re.match(r"Week (\d+)", done or "")
            if m: week = int(m.group(1)) + 1
            pday = 0
        nxt = pending[0] if pending else None
        cps = P(p["checkpoints"], [])
        ncp = p["next_cp"]
        for cp in cps:
            w = cp.get("w")
            if isinstance(w, int) and w >= week:
                ncp = f"Week {w}：{cp['name']}"; break
        x("UPDATE plans SET cur_week=?,cur_day=?,cur_unit=?,pending=?,next_cp=?,updated_at=? WHERE id=?",
          (week, pday, (nxt.split("：",1)[1] if nxt and "：" in nxt else nxt), J(pending), ncp, now(), pid))

# ==================== Scheduler ====================
sched = bg.BackgroundScheduler(timezone="Asia/Shanghai")

def night_urge():
    """21:00~23:00 每 30 分钟检查未完成任务"""
    td = today()
    pending = q("SELECT * FROM tasks WHERE task_date=? AND type='long_term' AND status IN ('pending','in_progress')", (td,))
    if not pending:
        return
    titles = "、".join(t["title"].split(" · ")[-1][:12] for t in pending[:3])
    push("提醒", f"还有 {len(pending)} 项未完成：{titles}", click=f"{CONFIG['web_url']}/?today")

# ==================== 每周周报（第2档：纯代码模板生成） ====================
def weekly_review():
    """周日 21:30 生成周报。纯代码统计过去 7 天真实执行数据 + 规则模板分析，
    不吃 AI 积分。生成的 content_md 可一键复制，由用户自己拿去给 AI 做深度分析。"""
    # 本周范围：周一 ~ 今天
    d = datetime.now(TZ).date()
    monday = d - timedelta(days=d.weekday())
    wk_start = monday.isoformat()
    wk_end = d.isoformat()
    # 防止同日重复生成
    if q1("SELECT COUNT(*) AS n FROM reviews WHERE week_start=?", (wk_start,))["n"] > 0:
        return {"created": 0, "skipped": True}

    # 本周所有任务（含长期+临时）
    tasks = q("SELECT * FROM tasks WHERE task_date>=? AND task_date<=?", (wk_start, wk_end))
    long_term = [t for t in tasks if t["type"] == "long_term"]
    temp = [t for t in tasks if t["type"] == "temporary"]
    plans = {p["id"]: p for p in q("SELECT * FROM plans")}

    def plan_stat(pid, expect_per_week):
        """统计某长期计划本周：应做/正常完成/最低完成/未完成"""
        pt = [t for t in long_term if t["plan_id"] == pid]
        planned = len([t for t in pt if t["status"] != "postponed"])
        done_normal = len([t for t in pt if t["status"] == "completed" and (t.get("level") != "minimum")])
        done_min = len([t for t in pt if t["status"] == "completed" and t.get("level") == "minimum"])
        undone = len([t for t in pt if t["status"] in ("pending", "in_progress")])
        postponed = len([t for t in pt if t["status"] == "postponed"])
        return {"planned": planned, "done_normal": done_normal, "done_min": done_min,
                "undone": undone, "postponed": postponed, "total_done": done_normal + done_min}

    def light(done, planned):
        """打灯：完成>=应做🟢 / 50-99%🟡 / <50%🔴"""
        if planned <= 0: return "🟢"
        r = done / planned
        return "🟢" if r >= 1 else ("🟡" if r >= 0.5 else "🔴")

    es = plan_stat("english", 7)
    fs = plan_stat("fae", 6)
    ex = plan_stat("exercise", 5)
    cs = plan_stat("content", 7)
    temp_done = len([t for t in temp if t["status"] == "completed"])
    temp_undone = len([t for t in temp if t["status"] in ("pending", "in_progress")])
    temp_postponed = len([t for t in temp if t["status"] == "postponed"])

    # 进度信息
    eng = plans.get("english", {}); fae = plans.get("fae", {})
    eng_total = eng.get("cur_day") or 0
    fae_week = fae.get("cur_week"); fae_day = fae.get("cur_day") or 0

    # ---- 规则模板分析 ----
    notes = []
    if es["undone"] >= 2:
        notes.append(f"⚠️ 英语本周有 {es['undone']} 天未完成，连续性受损，下周优先补回节奏。")
    elif es["done_min"] > 0:
        notes.append(f"🟡 英语本周有 {es['done_min']} 天以最低剂量完成，已保住连续性，但尽量回归正常目标。")
    else:
        notes.append("🟢 英语本周执行稳定。")
    if fae_week is not None and fae.get("next_cp"):
        notes.append(f"📌 FAE 当前 Week {fae_week}，下一检查点：{fae.get('next_cp')}。")
    if fs["undone"] >= 2:
        notes.append(f"⚠️ FAE 本周有 {fs['undone']} 天未完成。")
    if ex["total_done"] == 0:
        notes.append("🔴 运动本周没有打卡，下周至少完成 1 次。")
    if cs["undone"] >= 2:
        notes.append(f"⚠️ 自媒体视频本周有 {cs['undone']} 天未输出。")
    if temp_postponed > 0:
        notes.append(f"📌 本周有 {temp_postponed} 个临时任务被延期。")
    if not notes:
        notes.append("🟢 本周整体执行良好，没有明显掉队项。")

    # 下周重点（模板）
    next3 = []
    if fae_week is not None:
        next3.append(f"FAE Week {fae_week}（检查点：{fae.get('next_cp') or '无'}）")
    if es["undone"] > 0:
        next3.append("English 补回上周缺漏")
    else:
        next3.append("English 保持每天节奏")
    if ex["total_done"] == 0:
        next3.append("运动重新启动")
    else:
        next3.append("自媒体视频每天输出")
    next3 = next3[:3] if len(next3) >= 3 else (next3 + ["保持当前节奏"])[:3]

    # ---- 组装 Markdown（可一键复制给 AI）----
    md_lines = []
    md_lines.append(f"# 📊 本周执行报告（{wk_start} ~ {wk_end}）\n")
    md_lines.append("## 🚦 各计划本周情况")
    md_lines.append(f"- 🟢 完成率按「实际完成 / 应做」计算")
    md_lines.append(f"- **English** {light(es['total_done'], es['planned'])}：应做 {es['planned']} 天，正常完成 {es['done_normal']}，最低剂量 {es['done_min']}，未完成 {es['undone']}，延期 {es['postponed']}")
    md_lines.append(f"- **FAE** {light(fs['total_done'], fs['planned'])}：应做 {fs['planned']} 天，正常完成 {fs['done_normal']}，最低任务 {fs['done_min']}，未完成 {fs['undone']}，延期 {fs['postponed']}（当前 Week {fae_week or '—'}）")
    md_lines.append(f"- **运动** {light(ex['total_done'], ex['planned'])}：应做 {ex['planned']} 天，实际完成 {ex['total_done']}（目标每周 5 天）")
    md_lines.append(f"- **自媒体视频** {light(cs['total_done'], cs['planned'])}：应做 {cs['planned']} 天，完成 {cs['done_normal']}，未完成 {cs['undone']}")
    md_lines.append(f"- **临时任务**：完成 {temp_done} / 未完成 {temp_undone} / 延期 {temp_postponed}\n")
    md_lines.append("## 🧭 长期计划进度")
    md_lines.append(f"- English：Day {eng_total or 0}（主题周 {eng.get('cur_week') or '—'}）· 下一检查点 {eng.get('next_cp') or '无'}")
    md_lines.append(f"- FAE：Week {fae_week or '—'} / 已学 {fae_day} 天 · 下一检查点 {fae.get('next_cp') or '无'}\n")
    md_lines.append("## ⭐ 本周分析（规则模板）")
    for n in notes:
        md_lines.append(f"- {n}\n")
    md_lines.append("## 🔥 下周最重要的 3 件事")
    for i, t in enumerate(next3, 1):
        md_lines.append(f"{i}. {t}")
    content_md = "\n".join(md_lines)

    # ---- 组装 HTML（移动端阅读用）----
    def light_html(lt):
        return {"🟢": "<span style='font-size:18px'>🟢</span>",
                "🟡": "<span style='font-size:18px'>🟡</span>",
                "🔴": "<span style='font-size:18px'>🔴</span>"}.get(lt, lt)
    h = []
    h.append(f"<h3>📊 本周执行报告<br><small>{wk_start} ~ {wk_end}</small></h3>")
    h.append("<h4>🚦 各计划本周情况</h4>")
    h.append(f"<p>{light_html(light(es['total_done'], es['planned']))} <b>English</b>：应做 {es['planned']} 天 · 正常 {es['done_normal']} · 最低 {es['done_min']} · 未完成 {es['undone']} · 延期 {es['postponed']}</p>")
    h.append(f"<p>{light_html(light(fs['total_done'], fs['planned']))} <b>FAE</b>：应做 {fs['planned']} 天 · 正常 {fs['done_normal']} · 最低 {fs['done_min']} · 未完成 {fs['undone']} · 延期 {fs['postponed']}（Week {fae_week or '—'}）</p>")
    h.append(f"<p>{light_html(light(ex['total_done'], ex['planned']))} <b>运动</b>：应做 {ex['planned']} 天 · 实际 {ex['total_done']}（目标每周 5 天）</p>")
    h.append(f"<p>{light_html(light(cs['total_done'], cs['planned']))} <b>自媒体视频</b>：应做 {cs['planned']} 天 · 完成 {cs['done_normal']} · 未完成 {cs['undone']}</p>")
    h.append(f"<p>📌 <b>临时任务</b>：完成 {temp_done} / 未完成 {temp_undone} / 延期 {temp_postponed}</p>")
    h.append("<h4>🧭 长期计划进度</h4>")
    h.append(f"<p>🇬🇧 English：Day {eng_total or 0}（主题周 {eng.get('cur_week') or '—'}）· 下一检查点 {eng.get('next_cp') or '无'}</p>")
    h.append(f"<p>💻 FAE：Week {fae_week or '—'} · 已学 {fae_day} 天 · 下一检查点 {fae.get('next_cp') or '无'}</p>")
    h.append("<h4>⭐ 本周分析（规则模板）</h4>")
    h.append("<ul>" + "".join(f"<li>{n}</li>" for n in notes) + "</ul>")
    h.append("<h4>🔥 下周最重要的 3 件事</h4>")
    h.append("<ol>" + "".join(f"<li>{t}</li>" for t in next3) + "</ol>")
    h.append("<p style='color:#6b7280;font-size:13px'>💡 想深度分析？点周报右上角「复制」，把 Markdown 内容贴给 AI 跑。</p>")
    content_html = "".join(h)

    x("INSERT INTO reviews(week_start,content_md,content_html,created_at) VALUES(?,?,?,?)",
      (wk_start, content_md, content_html, now()))
    # 总进度（按周期天数） + 本周完成数
    eng_p = plan_period(eng); fae_p = plan_period(fae)
    eng_pct = eng_p.get("pct") if eng_p.get("pct") is not None else 0
    fae_pct = fae_p.get("pct") if fae_p.get("pct") is not None else 0
    week_done_total = es["total_done"] + fs["total_done"] + ex["total_done"] + cs["total_done"] + temp_done
    week_plan_total = es["planned"] + fs["planned"] + ex["planned"] + cs["planned"] + len(temp)
    week_pct = round(week_done_total * 100 / week_plan_total) if week_plan_total else 0
    push("📊 本周执行报告已生成",
         f"本周完成 {week_done_total}/{week_plan_total}（{week_pct}%）· 总进度：英语 {eng_pct}% / FAE {fae_pct}% · 点击查看详情",
         click=f"{CONFIG['web_url']}/reviews")
    return {"created": 1, "skipped": False}

def start_scheduler():
    def job(fn):
        """PG 模式下：每次任务用新连接、用完即弃（云端数据库会闲置断连）"""
        if not IS_PG:
            return fn
        def wrapped():
            _local.conn = None
            try: fn()
            finally:
                c = getattr(_local, "conn", None)
                if c is not None:
                    try: c.close()
                    except Exception: pass
                    _local.conn = None
        return wrapped
    sched.add_job(job(gen_today), "cron", hour=8, minute=0, id="daily", misfire_grace_time=3600)
    for h, m in [(21,0),(21,30),(22,0),(22,30),(23,0)]:
        sched.add_job(job(night_urge), "cron", hour=h, minute=m, id=f"urge_{h}_{m}", misfire_grace_time=600)
    sched.add_job(job(weekly_review), "cron", day_of_week="sun", hour=21, minute=30, id="weekly", misfire_grace_time=3600)
    sched.start()

# ==================== FastAPI ====================
app = FastAPI(title="Personal Growth OS")

@app.on_event("startup")
def startup():
    init_db()
    seed()
    gen_today()
    start_scheduler()

app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")

@app.get("/")
def page():
    return FileResponse(str(WEB / "index.html"))

@app.get("/reviews")
def reviews_page():
    return FileResponse(str(WEB / "reviews.html"))

@app.get("/overview")
def overview_page():
    return FileResponse(str(WEB / "overview.html"))

# ---- 今日视图 ----
@app.get("/api/today")
def api_today():
    td = today()
    tasks = q("SELECT * FROM tasks WHERE task_date=? AND status!='postponed' ORDER BY CASE type WHEN 'long_term' THEN 0 ELSE 1 END, priority DESC, created_at", (td,))
    done = [t for t in tasks if t["status"] == "completed"]
    active = [t for t in tasks if t["status"] in ("pending", "in_progress")]
    total = len(done) + len(active)
    plans = []
    for p in q("SELECT * FROM plans ORDER BY CASE id WHEN 'english' THEN 1 WHEN 'fae' THEN 2 WHEN 'exercise' THEN 3 ELSE 4 END"):
        plans.append({"id":p["id"],"name":p["name"],"goal":p["goal"],"normal":p["normal"],
                       "cur_week":p["cur_week"],"cur_day":p["cur_day"],"cur_topic":p["cur_topic"],
                       "cur_unit":p["cur_unit"],"next_cp":p["next_cp"],
                       "period": plan_period(p),
                       "pending":P(p["pending"],[])[:3]})
    nu = next((t for t in tasks if t["status"] == "pending"), None)
    return {"date":td,"tasks":tasks,
            "progress":{"done":len(done),"total":total,"pct":round(len(done)*100/total) if total else 0},
            "next_up":nu,"plans":plans}

# ---- 添加临时任务（自然语言 → 简单解析）----
@app.post("/api/task")
async def add_task(req: Request):
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text: raise HTTPException(400, "空输入")
    # 简单时间解析
    td = today()
    d = datetime.now(TZ).date()
    task_date, scheduled, due = td, None, None
    if "明天" in text: task_date = (d + timedelta(days=1)).isoformat()
    elif "后天" in text: task_date = (d + timedelta(days=2)).isoformat()
    elif "周末" in text or "周六" in text: task_date = _next_weekday(5, d).isoformat()
    elif "周日" in text or "周天" in text: task_date = _next_weekday(6, d).isoformat()
    m = re.search(r"周([一二三四五六日天])", text)
    if m and task_date == td:
        wd = "一二三四五六日天".index(m.group(1))
        task_date = _next_weekday(wd, d).isoformat()
    m = re.search(r"(\d{1,2})[:：点](\d{2}|半)?", text)
    if m:
        h = int(m.group(1)); mi = 30 if m.group(2) == "半" else (int(m.group(2)) if m.group(2) else 0)
        if "下午" in text or "晚上" in text or "今晚" in text or "明晚" in text:
            if h < 12: h += 12
        if "今晚" in text: task_date = td
        if "明晚" in text: task_date = (d + timedelta(days=1)).isoformat()
        scheduled = f"{h:02d}:{mi:02d}"
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]", text)
    if m:
        try: task_date = date(d.year, int(m.group(1)), int(m.group(2))).isoformat()
        except: pass
    if "之前" in text or "以前" in text:
        due = task_date
    # 标题清理
    title = re.sub(r"(明天|后天|今天|今晚|明晚|周[一二三四五六日天]|周末|\d{1,2}月\d{1,2}[日号]?|\d{1,2}[:：点]\d{0,2}|之前|以前|下午|晚上|上午|去|我|要)", " ", text)
    title = re.sub(r"\s+", " ", title).strip(" ，。,.！!？?的") or text

    seq = len(q("SELECT id FROM tasks WHERE id LIKE ?", (f"t_{td.replace('-','')}_%",))) + 1
    tid = f"t_{td.replace('-','')}_{seq:03d}"
    x("INSERT INTO tasks(id,title,type,task_date,due_date,scheduled,status,raw_input,created_at) VALUES(?,?,'temporary',?,?,?,?,?,?)",
      (tid, title, task_date, due, scheduled, "pending", text, now()))
    return {"ok": True, "task": q1("SELECT * FROM tasks WHERE id=?", (tid,))}

def _next_weekday(target, base):
    delta = (target - base.weekday()) % 7
    if delta == 0: delta = 7
    return base + timedelta(days=delta)

# ---- 状态流转 ----
@app.post("/api/tasks/{tid}/status")
async def set_status(tid: str, req: Request):
    body = await req.json()
    status = body.get("status")
    raw = body.get("raw_input", "")
    if status not in ("pending","in_progress","completed","postponed"):
        raise HTTPException(400, "无效状态")
    t = q1("SELECT * FROM tasks WHERE id=?", (tid,))
    if not t: raise HTTPException(404, "任务不存在")
    level = body.get("level") or ("normal" if status == "completed" else None)
    ct = now() if status == "completed" else None
    x("UPDATE tasks SET status=?,level=?,completed_at=?,notes=COALESCE(?,notes) WHERE id=?",
      (status, level, ct, body.get("note"), tid))
    # 完成长期任务 → 推进当前位置（每条任务只推进一次，撤销重做不重复计）
    advanced = False
    if status == "completed" and t["type"] == "long_term" and t["plan_id"] and not t.get("advanced"):
        advance(t["plan_id"])
        x("UPDATE tasks SET advanced=1 WHERE id=?", (tid,))
        advanced = True
        # 自媒体视频：完成一条 → output_count +1
        if t["plan_id"] == "content":
            cp = q1("SELECT * FROM plans WHERE id='content'")
            if cp:
                extra = P(cp["extra"], {}) or {}
                extra["output_count"] = (extra.get("output_count") or 0) + 1
                x("UPDATE plans SET extra=?,updated_at=? WHERE id='content'",
                  (J(extra), now()))
    # 全部完成 → 夸赞推送
    if status == "completed":
        td = t["task_date"]
        remaining = q1("SELECT COUNT(*) AS n FROM tasks WHERE task_date=? AND type='long_term' AND status IN ('pending','in_progress')", (td,))
        if remaining["n"] == 0:
            random_celebrate()
    return {"ok": True, "advanced": advanced, "task": q1("SELECT * FROM tasks WHERE id=?", (tid,))}

# ---- 计划 ----
@app.get("/api/plans")
def api_plans():
    plans = q("SELECT * FROM plans ORDER BY CASE id WHEN 'english' THEN 1 WHEN 'fae' THEN 2 WHEN 'exercise' THEN 3 ELSE 4 END")
    for p in plans:
        p["period"] = plan_period(p)
    return {"plans": plans}

# ---- 总览沙盘 ----
@app.get("/api/overview")
def api_overview():
    td = today()
    d = datetime.now(TZ).date()
    plans = q("SELECT * FROM plans ORDER BY CASE id WHEN 'english' THEN 1 WHEN 'fae' THEN 2 WHEN 'exercise' THEN 3 ELSE 4 END")

    # 1) 日历热力图：过去 26 周（约半年）每天是否有任务完成
    start = d - timedelta(days=26 * 7)
    heat = {}
    rows = q("SELECT completed_at, status, task_date FROM tasks WHERE type='long_term' AND status='completed' AND task_date>=?",
             (start.isoformat(),))
    for r in rows:
        cd = (r.get("completed_at") or r.get("task_date") or "")[:10]
        if cd:
            heat[cd] = heat.get(cd, 0) + 1
    heat_weeks = []
    # 按周分组（周一为起点），每天一个格
    cur = start - timedelta(days=start.weekday())
    day_names = ["一","二","三","四","五","六","日"]
    for w in range(26):
        week = []
        for i in range(7):
            day = cur + timedelta(days=i)
            iso = day.isoformat()
            cnt = heat.get(iso, 0)
            week.append({"date": iso, "count": cnt, "level": min(4, cnt), "future": day > d, "today": iso == td})
        heat_weeks.append(week)
        cur += timedelta(days=7)

    # 2) 里程碑地图
    milestones = []
    for p in plans:
        pid = p["id"]
        meta = PLAN_PERIODS.get(pid)
        if not meta:
            continue
        nodes = meta["nodes"]
        # 大节点默认等分，附加子节点信息
        node_items = []
        if pid == "english":
            # 英语 12 主题周作为小节点，归入 6 大阶段
            topics = P(p["route"], [])
            stage_names = ["阶段0","阶段1","阶段2","阶段3","阶段4","阶段5"]
            # 每个阶段 2 个主题周
            for si, sname in enumerate(stage_names):
                sub = topics[si*2:(si+1)*2]
                cur_w = p["cur_week"] or 1
                # 阶段 i 覆盖主题周 2i+1 ~ 2i+2
                stage_start = si*2 + 1
                stage_end = si*2 + 2
                passed = cur_w > stage_end
                current = stage_start <= cur_w <= stage_end
                node_items.append({"name": sname, "full": meta["nodes"][si], "sub": sub,
                                   "done": passed, "current": current})
        elif pid == "fae":
            # FAE 3 大节点（第1-2月/第3-4月/第5-6月），每个含若干周小节点
            sub_names = [["C语言基础","数组函数","指针struct","电路+原理图","STM32+GPIO","GPIO中断","USART串口","串口深化"],
                         ["ESP8266调试","STM32+ESP8266","网络+Linux","HTTP请求","项目整合","项目优化","项目验收"],
                         ["3款产品","竞品分析","需求案例","选型案例","Linux补完","技术英语","面试准备","投递"]]
            cw = p["cur_week"] or 1
            for si, sname in enumerate(nodes):
                subs = sub_names[si] if si < len(sub_names) else []
                passed = cw > (si+1)*8
                current = (not passed and cw > si*8)
                node_items.append({"name": sname, "full": sname, "sub": subs,
                                   "done": passed, "current": current})
        else:
            continue
        pct = plan_period(p).get("pct") or 0
        milestones.append({"id": pid, "name": p["name"], "pct": pct, "nodes": node_items})

    # 3) 数据看板
    board = []
    for p in plans:
        per = plan_period(p)
        # 累计完成天数
        done_days = q1("SELECT COUNT(DISTINCT task_date) AS n FROM tasks WHERE plan_id=? AND type='long_term' AND status='completed'", (p["id"],))["n"] or 0
        output_count = None
        if p["id"] == "content":
            extra = P(p["extra"], {}) or {}
            output_count = extra.get("output_count") or 0
        board.append({"id": p["id"], "name": p["name"], "goal": p["goal"],
                      "cur_week": p["cur_week"], "cur_day": p["cur_day"],
                      "cur_unit": p["cur_unit"], "done_days": done_days,
                      "output_count": output_count,
                      "pct": per.get("pct"), "remaining": per.get("remaining"),
                      "end": per.get("end"), "period_label": per.get("period_label")})

    return {"date": td, "heat_weeks": heat_weeks, "day_names": day_names,
            "milestones": milestones, "board": board}

# ---- 周报 ----
@app.get("/api/reviews")
def api_reviews():
    return {"reviews": q("SELECT * FROM reviews ORDER BY id DESC LIMIT 20")}

@app.get("/api/reviews/{rid}")
def api_review_detail(rid: int):
    return q1("SELECT * FROM reviews WHERE id=?", (rid,)) or {}

# ---- 手动触发（测试用）----
@app.post("/api/test/gen_today")
def api_gen():
    return gen_today(force=True)

@app.post("/api/test/urge")
def api_urge():
    night_urge()
    return {"ok": True}

@app.post("/api/test/weekly")
def api_weekly():
    return weekly_review()

@app.post("/api/test/push")
def api_push():
    push("测试", "如果你看到这条，说明 Push 链路正常。", click=CONFIG["web_url"])
    return {"ok": True}

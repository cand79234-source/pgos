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
    "web_url": os.environ.get("WEB_URL", "https://personal-growth-os-1wdg.onrender.com"),
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
            try:
                _exec(s)
                db().commit()   # 每条建表立即提交：PG 的 DDL 是事务性的，
                                # 单条失败回滚时不会连带撤销之前已建的表
            except Exception as e:
                try: db().rollback()
                except Exception: pass
                if "already exists" not in str(e): raise
        # 兼容迁移（老库补列）：失败单独回滚，不影响已建的表
        for alt in ("ALTER TABLE tasks ADD COLUMN advanced INTEGER DEFAULT 0",
                    "ALTER TABLE plans ADD COLUMN start_date TEXT",
                    "ALTER TABLE plans ADD COLUMN stage_details TEXT",
                    "ALTER TABLE plans ADD COLUMN postpone_days INTEGER DEFAULT 0",
                    "ALTER TABLE plans ADD COLUMN paused INTEGER DEFAULT 0",
                    "ALTER TABLE tasks ADD COLUMN postponed_at TEXT"):
            try:
                _exec(alt)
                db().commit()
            except Exception:
                try: db().rollback()
                except Exception: pass
        db().commit()
    else:
        db().executescript(schema)
        try: db().execute("ALTER TABLE tasks ADD COLUMN advanced INTEGER DEFAULT 0")
        except Exception: pass
        try: db().execute("ALTER TABLE plans ADD COLUMN start_date TEXT")
        except Exception: pass
        try: db().execute("ALTER TABLE plans ADD COLUMN stage_details TEXT")
        except Exception: pass
        try: db().execute("ALTER TABLE plans ADD COLUMN postpone_days INTEGER DEFAULT 0")
        except Exception: pass
        try: db().execute("ALTER TABLE plans ADD COLUMN paused INTEGER DEFAULT 0")
        except Exception: pass
        try: db().execute("ALTER TABLE tasks ADD COLUMN postponed_at TEXT")
        except Exception: pass
        db().commit()
    # 数据迁移：若 pgos_seed.json 存在且 plans 为空，自动恢复进度/新闻/周报
    seedf = BASE / "pgos_seed.json"
    if seedf.exists() and q1("SELECT COUNT(*) AS n FROM plans")["n"] == 0:
        data = json.loads(seedf.read_text(encoding="utf-8"))
        sd = today()
        for p in data.get("plans", []):
            if not p.get("paused") and not p.get("start_date"):
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
         "paused":1,
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
        if not p.get("paused"):
            p["start_date"] = sd
        cols = ",".join(p.keys())
        ph = ",".join("?"*len(p))
        x(f"INSERT INTO plans({cols}) VALUES({ph})", tuple(p.values()))

# ==================== 计划周期与阶段进度 ====================
# 阶段模型：English 6 阶段（各占全局 16.67%），FAE 3 节点（各占全局 33.3%）
# 阶段周数按月数换算（1个月=4周）：阶段0/1 各3个月=12周，阶段2~5 各4个月=16周
EN_STAGES = [
    {"name": "阶段0：基础重建", "weeks": 12},
    {"name": "阶段1：旅行场景", "weeks": 12},
    {"name": "阶段2：工作沟通", "weeks": 16},
    {"name": "阶段3：雅思输入", "weeks": 16},
    {"name": "阶段4：雅思输出", "weeks": 16},
    {"name": "阶段5：冲刺B2",   "weeks": 16},
]
FAE_STAGES = [
    {"name": "C语言+电路+STM32+串口", "weeks": 8},
    {"name": "通信+WiFi+Linux+项目",  "weeks": 8},
    {"name": "产品选型+需求分析+面试", "weeks": 8},
]
PLAN_PERIODS = {
    "english": {"months": 22, "label": "22个月", "stages": EN_STAGES},
    "fae":     {"months": 6,  "label": "6个月",  "stages": FAE_STAGES},
}

def _month_add(d, months):
    """日期 + N 个月（近似：按 30 天/月，避免复杂闰月计算）"""
    return d + timedelta(days=30 * months)

def _en_stage_of(cur_week):
    """English 当前周 → 阶段索引与该阶段起始周"""
    w = max(1, cur_week or 1)
    start = 1
    for i, st in enumerate(EN_STAGES):
        if w < start + st["weeks"]:
            return i, start
        start += st["weeks"]
    return len(EN_STAGES) - 1, start - EN_STAGES[-1]["weeks"]

def _en_done_days(plan):
    """English 已完成学习天数：cur_day 表示今天进行到第 N 天（未完成）"""
    return (max(1, plan["cur_week"] or 1) - 1) * 7 + (max(1, plan["cur_day"] or 1) - 1)

def _fae_done_days(plan):
    """FAE 已完成学习天数：cur_day 表示本周已学 N 天"""
    return (max(1, plan["cur_week"] or 1) - 1) * 6 + (plan["cur_day"] or 0)

def _fmt_md(d):
    return f"{d.month}/{d.day}"

def en_progress(plan):
    """English 进度：全局百分比（6阶段等分）+ 当前阶段内百分比 + 检查点日期"""
    done = _en_done_days(plan)
    stage_idx, stage_start = _en_stage_of(plan["cur_week"])
    stage = EN_STAGES[stage_idx]
    stage_days = stage["weeks"] * 7
    stage_done = done - (stage_start - 1) * 7          # 本阶段已完成天数
    stage_done = max(0, min(stage_done, stage_days))
    stage_pct = round(stage_done * 100 / stage_days, 1)
    # 全局：前面阶段若被提前完成则计满额；当前阶段按实际
    stage_share = 100.0 / len(EN_STAGES)
    global_pct = round(stage_share * stage_idx + stage_share * (stage_done / stage_days), 1)
    # 检查点：阶段0验证 = 今天 + 剩余学习量（自然日）
    today_d = datetime.now(TZ).date()
    cp_date = today_d + timedelta(days=stage_days - stage_done)
    return {
        "done_days": done, "stage_idx": stage_idx, "stage_name": stage["name"],
        "stage_start_week": stage_start, "stage_weeks": stage["weeks"],
        "stage_done": stage_done, "stage_days": stage_days,
        "stage_pct": stage_pct, "global_pct": global_pct,
        "next_stage": EN_STAGES[stage_idx + 1]["name"] if stage_idx + 1 < len(EN_STAGES) else None,
        "cp_name": "阶段0验证" if stage_idx == 0 else EN_STAGES[stage_idx]["name"] + "完成",
        "cp_date": cp_date.isoformat(), "cp_date_fmt": _fmt_md(cp_date),
        "remaining_days": max(0, stage_days - stage_done),
    }

def fae_progress(plan):
    """FAE 进度：全局百分比（3节点等分）+ 节点内百分比 + 下一检查点日期"""
    done = _fae_done_days(plan)
    w = max(1, plan["cur_week"] or 1)
    node_idx = min((w - 1) // 8, len(FAE_STAGES) - 1)
    node = FAE_STAGES[node_idx]
    node_days = node["weeks"] * 6          # FAE 每周 6 个学习日
    node_done = done - node_idx * node_days
    node_done = max(0, min(node_done, node_days))
    node_pct = round(node_done * 100 / node_days, 1)
    node_share = 100.0 / len(FAE_STAGES)
    global_pct = round(node_share * node_idx + node_share * (node_done / node_days), 1)
    # 下一检查点：最近的未过检查点（Week 4/8/9/12/16/20/24），按自然周推算日期
    today_d = datetime.now(TZ).date()
    cps = P(plan.get("checkpoints"), []) or []
    cp_w, cp_name, cp_date, cp_date_fmt = None, None, None, None
    for cp in cps:
        cw = cp.get("w")
        if isinstance(cw, int) and cw >= w:
            cp_w, cp_name = cw, cp.get("name", f"Week {cw}")
            # 剩余自然日：还需完成的学习日按每周6学+1休折算
            remain_days = (cw - w) * 7 + (7 - (plan["cur_day"] or 0))
            cp_date = today_d + timedelta(days=remain_days)
            cp_date_fmt = _fmt_md(cp_date)
            break
    return {
        "done_days": done, "stage_idx": node_idx, "stage_name": node["name"],
        "stage_start_week": node_idx * 8 + 1, "stage_weeks": node["weeks"],
        "stage_done": node_done, "stage_days": node_days,
        "stage_pct": node_pct, "global_pct": global_pct,
        "next_stage": FAE_STAGES[node_idx + 1]["name"] if node_idx + 1 < len(FAE_STAGES) else None,
        "cp_name": f"Week {cp_w}：{cp_name}" if cp_w else None,
        "cp_date": cp_date.isoformat() if cp_date else None,
        "cp_date_fmt": cp_date_fmt,
        "remaining_days": max(0, (node_days - node_done) // 6 * 7 + ((node_days - node_done) % 6)),
    }

def plan_period(plan):
    """计划的起止日期与周期信息（进度百分比由 *_progress 单独计算）"""
    sid = plan.get("id")
    meta = PLAN_PERIODS.get(sid)
    sd = None
    if plan.get("start_date"):
        try: sd = date.fromisoformat(str(plan["start_date"])[:10])
        except Exception: sd = None
    if sd is None:
        # 未设置起点（如暂停的 FAE）：不计算周期与剩余天数
        return {"start": None, "end": None, "total_days": None, "remaining": None,
                "period_label": meta["label"] if meta else None,
                "stage_names": [s["name"] for s in meta["stages"]] if meta else []}
    today_d = datetime.now(TZ).date()
    if meta:
        ed = _month_add(sd, meta["months"])
        total_days = (ed - sd).days
        remaining = max(0, (ed - today_d).days)
        return {"start": sd.isoformat(), "end": ed.isoformat(),
                "total_days": total_days, "remaining": remaining,
                "period_label": meta["label"],
                "stage_names": [s["name"] for s in meta["stages"]]}
    return {"start": sd.isoformat(), "end": None, "total_days": None,
            "remaining": None, "period_label": None, "stage_names": []}

def plan_progress(plan):
    """统一入口：按计划类型返回进度信息"""
    if plan.get("id") == "english":
        return en_progress(plan)
    if plan.get("id") == "fae":
        return fae_progress(plan)
    return None

def display_cp(plan):
    """显示用检查点：名称 + 预计具体日期（每天动态重算）"""
    prog = plan_progress(plan)
    if prog and prog.get("cp_name") and prog.get("cp_date_fmt"):
        return f"{prog['cp_name']} · 预计 {prog['cp_date_fmt']}"
    return plan.get("next_cp") or "无"

def _en_week_topic(p, week):
    """当前周主题：优先取阶段细则（stage_details）对应行；阶段0 回退 route"""
    prog = en_progress(p)
    det = P(p.get("stage_details"), {}) or {}
    det_text = det.get(str(prog.get("stage_idx")))
    if det_text:
        lines = [l.strip() for l in str(det_text).splitlines() if l.strip()]
        li = week - (prog.get("stage_start_week") or 1)
        if 0 <= li < len(lines):
            return lines[li]
    topics = P(p.get("route"), [])
    if topics and week <= len(topics):
        return topics[week-1]
    return None

def _next_task_id(td):
    """当天任务 ID：取已存在最大序号 +1（删除旧任务后也不会撞主键）"""
    mx = 0
    for r in q("SELECT id FROM tasks WHERE id LIKE ?", (f"t_{td.replace('-','')}_%",)):
        try: mx = max(mx, int(r["id"].rsplit("_", 1)[1]))
        except Exception: pass
    return f"t_{td.replace('-','')}_{mx+1:03d}"

# ==================== 今日任务生成（08:00 进度驱动）====================
def gen_today(force=False):
    td = today()
    # 今天已存在的长期任务（任何状态）→ 对应计划不再生成新任务，防止重复/覆盖用户推迟
    existing_plans = {t["plan_id"] for t in q("SELECT plan_id FROM tasks WHERE task_date=? AND type='long_term'", (td,))}
    if not force and existing_plans:
        return {"created": 0, "skipped": True}

    # 跨天未完成（昨天及更早仍 pending/in_progress）→ postponed，记 +1 欠账
    # postponed_at 记为原任务日期（非今天）→ 跨天延期不可撤销；手动推迟才记今天→可反悔
    for t in q("SELECT id,plan_id,task_date FROM tasks WHERE task_date<? AND type='long_term' AND status IN ('pending','in_progress')", (td,)):
        x("UPDATE tasks SET status='postponed', postponed_at=? WHERE id=?", (t["task_date"], t["id"]))
        if t["plan_id"] in ("english", "fae"):
            pl = q1("SELECT paused FROM plans WHERE id=?", (t["plan_id"],))
            if pl and not pl.get("paused"):
                x("UPDATE plans SET postpone_days=COALESCE(postpone_days,0)+1 WHERE id=?", (t["plan_id"],))

    d = datetime.now(TZ).date()
    created = 0
    def add(title, pid, dur, notes=None, pri="normal"):
        nonlocal created
        tid = _next_task_id(td)
        x("INSERT INTO tasks(id,title,type,plan_id,task_date,status,priority,duration,notes,created_at) VALUES(?,?,'long_term',?,?,?,?,?,?,?)",
          (tid, title, pid, td, "pending", pri, dur, notes, now()))
        created += 1

    plans = {p["id"]: p for p in q("SELECT * FROM plans")}
    for pid, p in plans.items():
        if p.get("paused"):
            continue   # 未启动计划不生成任务、不推送、不记账
        if pid in existing_plans:
            continue   # 该计划今天已有任务，不再生成（推迟/完成/进行中都不覆盖）
        if pid == "english":
            # 一个任务 = 一整天三段（1h输入 / 1h内化 / 1h输出）
            pending = P(p["pending"], [])
            prog = en_progress(p)
            stage_name = prog["stage_name"] if prog else "阶段0"
            topic = _en_week_topic(p, p["cur_week"] or 1) or p["cur_topic"]
            notes = (f"当前位置：{stage_name} · 主题周{p['cur_week']} · Day {p['cur_day']}（{topic or '主题待定'}）\n"
                     f"今日三段：{' / '.join(pending[:3])}\n"
                     f"结构：1h输入(语法+20词+对话) / 1h内化(10句关于自己) / 1h输出(改写+录音)\n"
                     f"复习：2/4/7天节奏\n检查点：{display_cp(p)}")
            add(f"English · Day {p['cur_day']}（{topic or '主题待定'}）", pid, p["normal"], notes)
        elif pid == "fae":
            pending = P(p["pending"], [])
            focus = pending[0] if pending else p["cur_unit"]
            cps = P(p["checkpoints"], [])
            pri, note = "normal", f"当前位置：Week {p['cur_week']}（{p['cur_unit']}）· 本周已学 {p['cur_day'] or 0}/6 天"
            for cp in cps:
                w = cp.get("w")
                if isinstance(w, int) and w >= (p["cur_week"] or 1):
                    dist = w - (p["cur_week"] or 1)
                    cp_txt = display_cp(p)
                    if dist <= 2:
                        pri = "high"
                        note += f"\n⚠️ 检查点临近：{cp_txt}（还差 {dist} 周），今日优先保证达标"
                    else:
                        note += f"\n检查点：{cp_txt}（还差 {dist} 周）"
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
        total_weeks = sum(s["weeks"] for s in EN_STAGES)
        if day > 7:
            day, week = 1, week + 1
            if week > total_weeks: week = total_weeks
        topic = _en_week_topic(p, week) or p["cur_topic"]
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

    # 进度信息（阶段模型：全局% / 阶段内% / 检查点日期均动态计算）
    eng = plans.get("english", {}); fae = plans.get("fae", {})
    eng_prog = plan_progress(eng) or {}
    fae_prog = plan_progress(fae) or {}
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
    if fae_week is not None:
        notes.append(f"📌 FAE 当前 Week {fae_week}（{fae_prog.get('stage_name') or ''}），下一检查点：{display_cp(fae)}。")
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
        next3.append(f"FAE Week {fae_week}（检查点：{display_cp(fae)}）")
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
    md_lines.append(f"- **English**：{eng_prog.get('stage_name') or '—'} · 全局进度 **{eng_prog.get('global_pct', 0)}%**（当前阶段 {eng_prog.get('stage_pct', 0)}%）· 下一检查点 {display_cp(eng)}")
    md_lines.append(f"- **FAE**：Week {fae_week or '—'} · {fae_prog.get('stage_name') or '—'} · 全局进度 **{fae_prog.get('global_pct', 0)}%**（当前节点 {fae_prog.get('stage_pct', 0)}%）· 已学 {fae_prog.get('done_days', 0)} 天 · 下一检查点 {display_cp(fae)}\n")
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
    h.append(f"<p>🇬🇧 English：{eng_prog.get('stage_name') or '—'} · 全局 <b>{eng_prog.get('global_pct', 0)}%</b>（阶段内 {eng_prog.get('stage_pct', 0)}%）· 检查点 {display_cp(eng)}</p>")
    h.append(f"<p>💻 FAE：{fae_prog.get('stage_name') or '—'} · 全局 <b>{fae_prog.get('global_pct', 0)}%</b>（节点内 {fae_prog.get('stage_pct', 0)}%）· 检查点 {display_cp(fae)}</p>")
    h.append("<h4>⭐ 本周分析（规则模板）</h4>")
    h.append("<ul>" + "".join(f"<li>{n}</li>" for n in notes) + "</ul>")
    h.append("<h4>🔥 下周最重要的 3 件事</h4>")
    h.append("<ol>" + "".join(f"<li>{t}</li>" for t in next3) + "</ol>")
    h.append("<p style='color:#6b7280;font-size:13px'>💡 想深度分析？点周报右上角「复制」，把 Markdown 内容贴给 AI 跑。</p>")
    content_html = "".join(h)

    x("INSERT INTO reviews(week_start,content_md,content_html,created_at) VALUES(?,?,?,?)",
      (wk_start, content_md, content_html, now()))
    # 总进度（阶段模型全局%）+ 本周完成数
    eng_pct = eng_prog.get("global_pct", 0)
    fae_pct = fae_prog.get("global_pct", 0)
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
    postponed = q("SELECT * FROM tasks WHERE status='postponed' ORDER BY task_date DESC, created_at", ())
    done = [t for t in tasks if t["status"] == "completed"]
    active = [t for t in tasks if t["status"] in ("pending", "in_progress")]
    total = len(done) + len(active)
    plans = []
    for p in q("SELECT * FROM plans ORDER BY CASE id WHEN 'english' THEN 1 WHEN 'fae' THEN 2 WHEN 'exercise' THEN 3 ELSE 4 END"):
        plans.append({"id":p["id"],"name":p["name"],"goal":p["goal"],"normal":p["normal"],
                       "cur_week":p["cur_week"],"cur_day":p["cur_day"],"cur_topic":p["cur_topic"],
                       "cur_unit":p["cur_unit"],"next_cp": display_cp(p),
                       "period": plan_period(p), "progress": plan_progress(p),
                       "paused": p.get("paused") or 0, "postpone_days": p.get("postpone_days") or 0,
                       "pending":P(p["pending"],[])[:3]})
    nu = next((t for t in tasks if t["status"] == "pending"), None)
    return {"date":td,"tasks":tasks,"postponed":postponed,
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
    td = today()
    x("UPDATE tasks SET status=?,level=?,completed_at=?,postponed_at=?,notes=COALESCE(?,notes) WHERE id=?",
      (status, level, ct, (td if status == "postponed" else None), body.get("note"), tid))
    # 推迟记账（仅未暂停的 English/FAE）：手动推迟 +1；当天推迟反悔（重新入队）-1
    if t["plan_id"] in ("english", "fae") and t["type"] == "long_term":
        pl = q1("SELECT paused FROM plans WHERE id=?", (t["plan_id"],))
        if pl and not pl.get("paused"):
            if status == "postponed":
                x("UPDATE plans SET postpone_days=COALESCE(postpone_days,0)+1 WHERE id=?", (t["plan_id"],))
            elif status == "pending" and t["status"] == "postponed" and (t.get("postponed_at") or "")[:10] == td:
                x("UPDATE plans SET postpone_days=CASE WHEN COALESCE(postpone_days,0)>0 THEN postpone_days-1 ELSE 0 END WHERE id=?", (t["plan_id"],))
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
        p["progress"] = plan_progress(p)
        p["next_cp"] = display_cp(p)
        # 阶段细则（每行一周主题）供前端渲染周节点
        det = P(p["stage_details"], {}) if p.get("stage_details") else {}
        p["stage_details"] = det if isinstance(det, dict) else {}
    return {"plans": plans}

# ---- 阶段细则保存（每行 = 一周主题）----
@app.post("/api/plans/{pid}/stage_details")
async def save_stage_details(pid: str, req: Request):
    body = await req.json()
    stage = body.get("stage")
    text = (body.get("text") or "").strip()
    p = q1("SELECT * FROM plans WHERE id=?", (pid,))
    if not p: raise HTTPException(404, "计划不存在")
    if pid not in ("english", "fae"): raise HTTPException(400, "该计划不支持阶段细则")
    stages = EN_STAGES if pid == "english" else FAE_STAGES
    if not isinstance(stage, int) or stage < 0 or stage >= len(stages):
        raise HTTPException(400, f"阶段编号应为 0~{len(stages)-1}")
    det = P(p["stage_details"], {}) or {}
    if text:
        det[str(stage)] = text
    else:
        det.pop(str(stage), None)
    x("UPDATE plans SET stage_details=?,updated_at=? WHERE id=?", (J(det), now(), pid))
    return {"ok": True, "stage_details": det}

# ---- 提前完成：跳到下一阶段，剩余周作废 ----
def _regen_today_for(pid):
    """跳阶后：删除该计划今天未完成的长期任务，按新位置重新生成今天的任务"""
    td = today()
    for t in q("SELECT id FROM tasks WHERE task_date=? AND plan_id=? AND type='long_term' AND status IN ('pending','in_progress')",
               (td, pid)):
        x("DELETE FROM tasks WHERE id=?", (t["id"],))
    p = q1("SELECT * FROM plans WHERE id=?", (pid,))
    if not p: return 0
    def add(title, dur, notes=None, pri="normal"):
        tid = _next_task_id(td)
        x("INSERT INTO tasks(id,title,type,plan_id,task_date,status,priority,duration,notes,created_at) VALUES(?,?,'long_term',?,?,?,?,?,?,?)",
          (tid, title, pid, td, "pending", pri, dur, notes, now()))
    if pid == "english":
        pending = P(p["pending"], [])
        prog = en_progress(p)
        topic = _en_week_topic(p, p["cur_week"] or 1) or p["cur_topic"]
        notes = (f"当前位置：{prog['stage_name']} · 主题周{p['cur_week']} · Day {p['cur_day']}（{topic or '主题待定'}）\n"
                 f"今日三段：{' / '.join(pending[:3])}\n"
                 f"结构：1h输入(语法+20词+对话) / 1h内化(10句关于自己) / 1h输出(改写+录音)\n"
                 f"复习：2/4/7天节奏\n检查点：{display_cp(p)}")
        add(f"English · Day {p['cur_day']}（{topic or '主题待定'}）", p["normal"], notes)
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
                    note += f"\n⚠️ 检查点临近：{display_cp(p)}（还差 {dist} 周），今日优先保证达标"
                else:
                    note += f"\n检查点：{display_cp(p)}（还差 {dist} 周）"
                break
        add(f"FAE · {focus}", p["normal"], note, pri)
    return 1

@app.post("/api/plans/{pid}/skip_stage")
async def skip_stage(pid: str):
    """提前完成：当前阶段剩余周作废（不显示欠账），直接进入下一阶段"""
    p = q1("SELECT * FROM plans WHERE id=?", (pid,))
    if not p: raise HTTPException(404, "计划不存在")
    if pid not in ("english", "fae"): raise HTTPException(400, "该计划不支持阶段推进")
    stages = EN_STAGES if pid == "english" else FAE_STAGES
    if pid == "english":
        idx, start = _en_stage_of(p["cur_week"])
        if idx + 1 >= len(stages):
            raise HTTPException(400, "已是最后一个阶段，无法再提前")
        prog = en_progress(p)
        new_week = start + stages[idx]["weeks"]          # 下一阶段第 1 周
        topics = P(p["route"], [])
        # 新阶段首周主题：优先取阶段细则第一行（阶段0 12周外回退 route）
        det = P(p["stage_details"], {}) or {}
        ndet = det.get(str(idx + 1))
        new_topic = next((l.strip() for l in str(ndet).splitlines() if l.strip()), None) if ndet else None
        if new_topic is None:
            new_topic = topics[new_week-1] if topics and new_week <= len(topics) else None
        skipped_days = max(0, prog["stage_days"] - prog["stage_done"])
        x("UPDATE plans SET cur_week=?, cur_day=1, cur_topic=?, "
          "pending=?, updated_at=? WHERE id=?",
          (new_week, new_topic, J(["Day 1：输入", "Day 2：内化", "Day 3：输出"]), now(), pid))
    else:
        w = max(1, p["cur_week"] or 1)
        idx = min((w - 1) // 8, len(stages) - 1)
        if idx + 1 >= len(stages):
            raise HTTPException(400, "已是最后一个节点，无法再提前")
        prog = fae_progress(p)
        new_week = (idx + 1) * 8 + 1                     # 下一节点第 1 周
        # pending 队列跳到新节点：只保留新周及以后的项，不足则按 route 补齐
        pending = P(p["pending"], [])
        kept = []
        for t in pending:
            m = re.match(r"Week (\d+)", t or "")
            if m and int(m.group(1)) >= new_week:
                kept.append(t)
        route = {r["w"]: r["u"] for r in P(p["route"], [])}
        wk = new_week
        while len(kept) < 8 and wk in route:
            kept.append(f"Week {wk}：{route[wk]}")
            wk += 1
        nxt = kept[0] if kept else None
        new_unit = (nxt.split("：", 1)[1] if nxt and "：" in nxt else nxt) or f"Week {new_week}"
        skipped_days = max(0, prog["stage_days"] - prog["stage_done"])
        x("UPDATE plans SET cur_week=?, cur_day=0, cur_unit=?, pending=?, updated_at=? WHERE id=?",
          (new_week, new_unit, J(kept), now(), pid))
    next_name = stages[idx + 1]["name"]
    _regen_today_for(pid)   # 今天未完成旧任务删除，按新阶段重新生成
    new_prog = plan_progress(q1("SELECT * FROM plans WHERE id=?", (pid,))) or {}
    push("🚀 提前进入下一阶段",
         f"{p['name']}已推进：{next_name}（作废 {skipped_days} 天未完成量，不计欠账）· 全局进度 {new_prog.get('global_pct', 0)}%",
         click=f"{CONFIG['web_url']}/overview")
    return {"ok": True, "pid": pid, "old_stage": stages[idx]["name"], "new_stage": next_name,
            "skipped_days": skipped_days, "new_week": new_week,
            "progress": new_prog}

# ---- 清零推迟欠账（手动平账）----
@app.post("/api/plans/{pid}/clear_postpone")
async def clear_postpone(pid: str):
    if pid not in ("english", "fae"):
        raise HTTPException(400, "该计划不支持")
    x("UPDATE plans SET postpone_days=0, updated_at=? WHERE id=?", (now(), pid))
    return {"ok": True, "postpone_days": 0}

# ---- 启动 FAE（从点击当天起算 6 个月周期）----
@app.post("/api/plans/fae/start")
async def start_fae():
    p = q1("SELECT * FROM plans WHERE id='fae'")
    if not p: raise HTTPException(404, "计划不存在")
    if not p.get("paused"):
        return {"ok": True, "already_started": True}
    td = today()
    x("UPDATE plans SET paused=0, start_date=?, postpone_days=0, updated_at=? WHERE id='fae'",
      (td, now()))
    created = _regen_today_for("fae")
    push("🚀 FAE 已启动",
         "从今天开始按 6 个月周期计算进度，去总览看看你的里程碑地图",
         click=f"{CONFIG['web_url']}/overview")
    return {"ok": True, "created": created,
            "progress": plan_progress(q1("SELECT * FROM plans WHERE id='fae'")) or {}}

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

    # 2) 里程碑地图：当前阶段 + 百分比 + 下一阶段（填了细则 → 显示周节点）
    milestones = []
    for p in plans:
        pid = p["id"]
        if pid not in ("english", "fae"):
            continue
        prog = plan_progress(p) or {}
        stages = EN_STAGES if pid == "english" else FAE_STAGES
        det = P(p["stage_details"], {}) or {}
        # 当前阶段的细则文本（每行一周）→ 周节点；English 阶段0 无细则回退 route 主题
        detail_text = det.get(str(prog.get("stage_idx"))) or ""
        lines = [l.strip() for l in str(detail_text).splitlines() if l.strip()]
        if not lines and pid == "english" and prog.get("stage_idx") == 0:
            lines = [t for t in (P(p["route"], []) or []) if t]
        weeks_detail = [{"week": (prog.get("stage_start_week") or 1) + i, "topic": ln}
                        for i, ln in enumerate(lines)]
        # 编辑弹层用：每个阶段的细则（English 阶段0 预填 route 主题方便直接改）
        route_topics = "\n".join(t for t in (P(p["route"], []) or []) if t) if pid == "english" else ""
        milestones.append({
            "id": pid, "name": p["name"],
            "stage_idx": prog.get("stage_idx"),
            "stage_name": prog.get("stage_name"),
            "stage_pct": prog.get("stage_pct"),
            "global_pct": prog.get("global_pct"),
            "next_stage": prog.get("next_stage"),
            "cp": display_cp(p),
            "stage_weeks": prog.get("stage_weeks"),
            "cur_week": p["cur_week"],
            "weeks_detail": weeks_detail,           # 填了细则（或阶段0）才有内容
            # 全部阶段（供「阶段细则」编辑弹层使用）
            "stages": [{"idx": i, "name": s["name"], "weeks": s["weeks"],
                        "detail": det.get(str(i)) or (route_topics if i == 0 and pid == "english" else "")}
                       for i, s in enumerate(stages)],
        })

    # 3) 数据看板（English/FAE 显示百分比；运动/自媒体只显示累计）
    board = []
    for p in plans:
        pid = p["id"]
        per = plan_period(p)
        done_days = q1("SELECT COUNT(DISTINCT task_date) AS n FROM tasks WHERE plan_id=? AND type='long_term' AND status='completed'", (pid,))["n"] or 0
        item = {"id": pid, "name": p["name"], "goal": p["goal"],
                "done_days": done_days,
                "remaining": per.get("remaining"), "end": per.get("end"),
                "period_label": per.get("period_label")}
        if pid in ("english", "fae"):
            prog = plan_progress(p) or {}
            item.update({"stage_name": prog.get("stage_name"),
                         "global_pct": prog.get("global_pct"),
                         "stage_pct": prog.get("stage_pct"),
                         "done_study_days": prog.get("done_days"),
                         "cp": display_cp(p)})
        if pid == "content":
            extra = P(p["extra"], {}) or {}
            item["output_count"] = extra.get("output_count") or 0
        board.append(item)

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

@app.post("/api/test/reset")
def api_reset():
    """清空数据并按 pgos_seed.json 重建（预览/测试用；正式站请勿随意调用）"""
    x("DELETE FROM tasks"); x("DELETE FROM reviews"); x("DELETE FROM plans")
    db().commit()
    seedf = BASE / "pgos_seed.json"
    if seedf.exists():
        data = json.loads(seedf.read_text(encoding="utf-8"))
        sd = today()
        for p in data.get("plans", []):
            if not p.get("paused") and not p.get("start_date"):
                p["start_date"] = sd
            cols = ",".join(p.keys()); ph = ",".join("?"*len(p))
            x(f"INSERT INTO plans({cols}) VALUES({ph})", tuple(p.values()))
        for t in data.get("tasks", []):
            cols = ",".join(t.keys()); ph = ",".join("?"*len(t))
            x(f"INSERT INTO tasks({cols}) VALUES({ph})", tuple(t.values()))
        for r in data.get("reviews", []):
            x("INSERT INTO reviews(week_start,content_md,content_html,created_at) VALUES(?,?,?,?)",
              (r["week_start"], r["content_md"], r["content_html"], r["created_at"]))
        print(f"[reset] 已从 pgos_seed.json 恢复 {len(data.get('plans',[]))} 计划 / {len(data.get('tasks',[]))} 任务 / {len(data.get('reviews',[]))} 周报", flush=True)
    else:
        seed()
    gen_today()
    return {"ok": True, "reset": True}

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

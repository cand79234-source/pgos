# Personal Growth OS · 免费云端部署指南

> **目标**：把系统部署到永久免费的云平台，获得固定网址（手机随时打开、每天 08:00 推送不中断）。
> **耗时**：约 30–40 分钟（都是网页点击，无需命令行知识）。
> **花费**：0 元。全部使用免费套餐。
> **架构**：Render（跑程序）+ Neon（存数据）+ UptimeRobot（保活）+ GitHub（存代码）。
> 卡在任何一步，把报错截图发给你的 AI 助手即可。

---

## 你将获得

- 固定网址，如 `https://personal-growth-os.onrender.com`，永不变化
- 你的全部进度（English Day 2、FAE Week 1 已学 1/6、历史周报）自动迁移过去
- 每天 08:00 任务生成 + 推送、21:00–23:00 催促、周日 21:30 周报——全自动
- 纯本地统计，**不消耗 AI 积分**

---

## 本版变化（相比旧版）

1. **新闻模块已完全移除**（页面、接口、数据表、定时任务、历史数据全部删除）。
2. **内容计划改版**：从"隔天发布 FAE+新闻讲解"改成"**自媒体视频输出 · 每天 1 条**"，选题由你自己定，系统只负责每天生成提醒任务。已录入起点 **15 条**，完成一条自动 +1。
3. **周报改为纯代码自动生成**（第 2 档）：每周日 21:30 自动统计一周真实执行数据，生成信号灯/完成率/进度/检查点倒计时/规则模板分析。
   - 生成的周报可以**一键复制（Markdown）**，复制后粘贴给 AI 即可做深度分析——深度分析那一步才需要 AI，日常不消耗。
4. **每日完成庆祝推送改为随机话术**（共 10 组，随机触发，纯代码不吃积分）。
5. **任务红绿状态**：按计划完成 → 绿色+完成日期；推迟/未完成 → 红色+已拖天数。
6. **长期计划日期区间**：自动以部署日为起点，英语 18 个月、FAE 6 个月倒推结束日期和剩余天数。
7. **新增总览页（沙盘式）**：`/overview`，包含 📊数据看板（各计划进度/累计天数/剩余天数）、🗺️里程碑地图（英语6大节点含12主题周、FAE 3大节点含每周）、🔥执行热力图（近26周每天完成情况）。
8. 自然语言自动勾选已移除：**完成任务由你手动在任务卡片上点「完成」**。

> **当前已录入进度**：English 阶段0 · 主题周2（工作与日常）· Day 3；FAE Week 1 · 本周已学 0 天；自媒体视频已输出 15 条。

---

## 第 1 步 · GitHub（存代码，约 8 分钟）

1. 打开 https://github.com → 注册账号（Sign up，邮箱即可）
2. 登录后点右上角 **+** → **New repository**
   - Repository name 填：`pgos`
   - 选 **Private**（私有）
   - 勾选 **Add a README file**
   - 点 **Create repository**
3. 进入仓库页面 → 点 **Add file** → **Upload files**
4. 把部署包 `pgos` 文件夹里的**全部内容**（app.py、schema.sql、requirements.txt、render.yaml、pgos_seed.json、web 文件夹等）拖进上传区
   - 注意：`web` 是文件夹，GitHub 网页上传不支持拖文件夹 → 先进入仓库页面上的 `web` 目录再上传 web 里面的文件；`web/static` 同理（两层级）
   - `.gitignore` 这类隐藏文件如果拖不进去就算了，不影响
5. 点 **Commit changes**

✅ 检查点：仓库里能看到 `app.py`，点进去内容不是空的。

---

## 第 2 步 · Neon（云数据库，约 5 分钟）

1. 打开 https://neon.com → 点 **Sign Up** → 用 Google 账号登录（最快）
2. 登录后进入控制台 → **Create project**
   - Project name：`pgos`
   - Postgres version：默认即可
   - Region：选 **Singapore**（离国内最近）
   - 点 **Create**
3. 创建完成后会弹出一个连接串，形如：
   ```
   postgresql://neondb_owner:xxxxx@ep-xxx-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
4. **完整复制并保存**这一串（这就是数据库地址，下一步要用）

✅ 检查点：你手里有一串 `postgresql://` 开头的字符。

---

## 第 3 步 · Render（跑程序，约 10 分钟）

1. 打开 https://render.com → **Get Started** → 用 **GitHub** 账号登录（授权访问你的仓库）
2. 登录后点 **New +** → **Web Service**
3. 选刚才的 `pgos` 仓库 → **Connect**（如果列表没有，点 Configure account 给 Render 授权）
4. 填写配置：
   - **Name**：`personal-growth-os`（决定你的网址前缀）
   - **Region**：Singapore
   - **Branch**：`main`
   - **Runtime**：Python 3
   - **Build Command**：`pip install -r requirements.txt`
   - **Start Command**：`uvicorn app:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**：**Free**（重要！）
5. 展开 **Advanced** → **Add Environment Variable**，添加 2 个变量：

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | （第 2 步复制的 Neon 连接串，完整粘贴） |
   | `WEB_URL` | `https://personal-growth-os.onrender.com`（先把预计网址填上，Name 是什么就填什么） |

   > **注意**：ntfy 推送主题默认是 `topic_workbuddy`（你在 ntfy 里订阅这个主题就能收到全部通知），已写死在代码里，正常不需要额外配置。如果想换成自己的主题，可额外加一个变量 `NTFY_TOPIC`。

6. 点 **Create Web Service** → 等待构建（首次约 3–5 分钟，状态从 Deploying 变成 **Live**）

✅ 检查点：页面顶部显示 `https://personal-growth-os.onrender.com` 且状态为 Live。
打开这个网址，能看到你的任务列表（English Day 2、FAE Week 1）——数据自动迁移成功。

---

## 第 4 步 · UptimeRobot（保活，约 5 分钟）

> Render 免费版 15 分钟无人访问会休眠 → 定时任务会停。UptimeRobot 每 5 分钟访问一次，让它永不休眠。

1. 打开 https://uptimerobot.com → **Sign up**（免费）
2. 登录后点 **Add New Monitor**：
   - **Monitor Type**：HTTP(s)
   - **Friendly Name**：`Growth OS`
   - **URL**：`https://personal-growth-os.onrender.com`
   - **Monitoring Interval**：5 minutes
   - 点 **Create Monitor**

✅ 检查点：Monitor 列表里显示绿色状态。

---

## 第 5 步 · 手机切换到新地址（约 2 分钟）

1. 手机 Chrome 打开 `https://personal-growth-os.onrender.com`
2. 菜单 **⋮** → **添加到主屏幕**（新图标会替代旧的临时图标，把旧的长按删掉）
3. ntfy 推送里的链接以后都指向新地址，点通知直达

✅ 最终检查点：
- 桌面图标点开 → 任务列表正常
- 明早 08:00 → 收到「今日任务已生成」推送（English Day 3 + FAE Week 1 + 运动 + 自媒体视频）

---

## 日常使用

- **每天**：08:00 收到今日任务推送 → 点通知进入工作台 → 完成后在卡片上点「完成」
- **添加临时任务**：在工作台输入框输入，如「周六下午2点看房」「明天买洗衣液」
- **看总览**：导航栏「总览」页 → 数据看板 / 里程碑地图 / 执行热力图
- **完成庆祝**：当天全部任务完成时，自动推送随机夸赞
- **每周日 21:30**：自动生成周报（纯代码统计）→ 点「复制」→ 粘贴给 AI 做深度分析

---

## 常见问题

| 问题 | 说明 |
|---|---|
| 打开网页很慢（30–60 秒） | 免费实例冷启动，正常现象；UptimeRobot 保活后极少发生 |
| Render 偶尔重启 | 数据存在 Neon 云数据库，重启不丢；几秒后自动恢复 |
| 明早没收到 08:00 推送 | 检查 UptimeRobot 是否在运行（绿色）；检查 Render 服务状态是否 Live |
| 想改功能/修 bug | 回来找 AI 助手改代码 → 新文件在 GitHub 网页上传覆盖 → Render 自动重新部署 |
| Neon 免费额度 | 0.5GB 存储（这个系统用几十年也够） |

## 以后怎么更新代码（重要）

1. AI 助手给你改好的文件（如 `app.py`）
2. GitHub 打开你的仓库 → 进入对应文件 → 点铅笔图标 ✏️ → 全选粘贴新内容 → **Commit changes**
3. Render 检测到变化会自动重新部署（约 2–3 分钟）
4. 刷新手机网页即可看到更新

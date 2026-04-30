# Watchdog — Global Process Manager

## 用途
独立的进程守护工具，管理这台 Windows 机器上所有需要持续运行的进程。
与具体项目解耦，任何项目都可以注册自己的进程进来。

## 文件结构
```
C:\watchdog\
  watchdog.py          # 主运行脚本（Task Scheduler 每5分钟触发）
  register.py          # CLI 注册工具
  registrations/       # 每个进程一个 .json 文件
  logs/
    watchdog.log       # 运行日志（每次触发追加）
  CLAUDE.md
```

## 工作原理
1. Task Scheduler 每5分钟触发 `watchdog.py`
2. 扫描 `registrations/` 下所有 .json 文件
3. 根据每个 registration 的 `check` 类型检查进程状态
4. 检查失败 → 重启；实例过多 → kill 多余的再重启
5. 运行完毕退出（不是持续运行的守护进程）

## 支持的检查类型

### process
检查指定 cmdline 关键词的进程是否存在，并控制实例数量。

可选字段：
- `max_instances`：允许最多几个实例（默认1），超出时 kill 最老的
- `max_memory_mb`：进程内存超过阈值时 kill（之后若无存活实例则重启）
- `kill_match`：重启前先 kill 所有 cmdline 含此关键词的进程
- `restart_cmd`：省略则只监控不重启（外部管理的进程）

```json
{
  "name": "MyApp-Bot",
  "project": "myapp",
  "check": "process",
  "match": "bot.py",
  "max_instances": 1,
  "restart_cmd": "python C:\\myapp\\bot.py",
  "cwd": "C:\\myapp",
  "enabled": true
}
```

### port
检查指定端口是否在监听。端口不通时，先 kill 端口持有者，再 kill `kill_match` 匹配的残留进程，然后重启。

`kill_match` 在 port 检查中尤其重要：进程崩溃后可能仍有残留子进程存活但不再监听端口，不清理会导致进程累积占用内存。

```json
{
  "name": "MyApp-WebUI",
  "project": "myapp",
  "check": "port",
  "port": 5000,
  "restart_cmd": "python C:\\myapp\\web\\app.py",
  "cwd": "C:\\myapp",
  "enabled": true
}
```

对于会产生子进程的应用（如 Edge），必须加 `kill_match`：

```json
{
  "name": "MyApp-EdgeCDP",
  "project": "myapp",
  "check": "port",
  "port": 9223,
  "kill_match": "--remote-debugging-port=9223",
  "restart_cmd": "\"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe\" --remote-debugging-port=9223 --user-data-dir=\"C:\\myapp\\edge-profile\"",
  "cwd": "C:\\myapp",
  "enabled": true
}
```

### file_age
检查文件最后修改时间是否在允许范围内（适用于 tunnel_url.txt 等需要定期刷新的文件）。
```json
{
  "name": "MyApp-Tunnel",
  "project": "myapp",
  "check": "file_age",
  "file": "C:\\myapp\\tunnel_url.txt",
  "max_age_seconds": 7200,
  "kill_match": "update_tunnel.py",
  "restart_cmd": "python C:\\myapp\\update_tunnel.py",
  "cwd": "C:\\myapp",
  "enabled": true
}
```

### schedule
每天在指定时间重启一次（本地时间，HH:MM 24小时制）。常用于定时刷新长期运行的进程。
```json
{
  "name": "MyApp-DailyRefresh",
  "project": "myapp",
  "check": "schedule",
  "daily_at": "02:00",
  "kill_match": "some-process-keyword",
  "restart_cmd": "python C:\\myapp\\start.py",
  "cwd": "C:\\myapp",
  "enabled": true
}
```

## 注册命令（register.py）

```cmd
# 注册新进程
python C:\watchdog\register.py add --name "MyApp-Bot" --project "myapp" --check process --match "bot.py" --max-instances 1 --restart "python C:\myapp\bot.py" --cwd "C:\myapp"

python C:\watchdog\register.py add --name "MyApp-WebUI" --project "myapp" --check port --port 5000 --restart "python C:\myapp\web\app.py" --cwd "C:\myapp"

python C:\watchdog\register.py add --name "MyApp-Tunnel" --project "myapp" --check file_age --file "C:\myapp\tunnel_url.txt" --max-age-seconds 7200 --restart "python C:\myapp\update_tunnel.py" --cwd "C:\myapp"

# 查看所有注册
python C:\watchdog\register.py list

# 删除
python C:\watchdog\register.py remove --name "MyApp-Bot"

# 临时禁用/启用（不删除）
python C:\watchdog\register.py disable --name "MyApp-Bot"
python C:\watchdog\register.py enable --name "MyApp-Bot"
```

## restart_cmd 规范

**永远不要用 `wscript.exe`**。wscript.exe 是 GUI 应用，出错时弹 MessageBox；COM 对象初始化在内存压力下容易失败，且失败是静默的（用户只看到弹窗，进程并未启动）。

| 启动类型 | 正确写法 |
|----------|----------|
| Python 脚本 | `python C:\\path\\script.py` |
| 直接可执行文件 | `\"C:\\Program Files\\App\\app.exe\" --flag value` |
| 需要 shell 特性 | `cmd /c "..."` （shell=True 已默认支持） |

**环境变量**：如果进程需要特定 env var（如 API key），不要在 vbs 里设置，改用 Windows 用户级环境变量，在新的 shell 中自动继承：
```powershell
[System.Environment]::SetEnvironmentVariable("MY_API_KEY", "value", "User")
```

## Task Scheduler 配置

用 `setup_startup.ps1`（各项目自己的）注册 watchdog 任务：
```powershell
$action  = New-ScheduledTaskAction -Execute "C:\Python314\python.exe" -Argument "C:\watchdog\watchdog.py"
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At (Get-Date)
Register-ScheduledTask -TaskName "GlobalWatchdog" -Action $action -Trigger $trigger -RunLevel Highest -Force
```

或手动在 Task Scheduler 创建：
- 程序：`C:\Python314\python.exe`
- 参数：`C:\watchdog\watchdog.py`
- 触发：每5分钟重复，无限期
- 运行级别：最高（Highest privileges）

## 新项目 Onboarding

1. 确定项目里哪些进程需要持续运行（bot、web server、tunnel 等）
2. 为每个进程运行一条 `register.py add` 命令
3. 注册完成后，下次 watchdog 触发自动开始监控

不需要改 watchdog.py 本身，也不需要重启 watchdog。

## 依赖
```cmd
pip install psutil
```

## 注意事项
- watchdog 与 bot.py 内部的 `_job_watchdog` 是独立的：迁移到本工具后应删除 bot.py 内部的 watchdog
- `registrations/` 里的 .json 文件可以直接编辑（watchdog 每次运行时重读）
- 日志在 `logs/watchdog.log`，每次运行追加
- `kill_match` 在 `port` 和 `file_age`、`schedule` 检查中均有效；对于会产生多个子进程的程序（Edge、Chrome）务必设置，否则崩溃后子进程残留会导致内存累积

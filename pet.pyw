# -*- coding: utf-8 -*-
"""
小克 · Claude 桌宠
==================
形象严格按照 Claude Code 终端里的吉祥物（Clawd）还原：

     ▐▛███▜▌
    ▝▜█████▛▘
      ▘▘ ▝▝

终端里每个字符格被拆成 2×2 的“象限像素”，每个象限像素宽:高 = 1:2。
这里用同样的网格（18×5 象限）和同样的比例绘制，颜色同为 #D77757。
“原大”尺寸 = 终端默认字号下的大小，右键菜单可放大。

运行：双击“启动桌宠.vbs”（立即出现），或 pythonw pet.pyw（等你开始工作时才出现）
"""
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import queue
import random
import socket
import sys
import threading
import time
import traceback
import tkinter as tk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(APP_DIR, 'config.json')
LOG_PATH = os.path.join(APP_DIR, 'pet.log')
PORT = 47613
STARTUP_VBS = os.path.join(os.environ.get('APPDATA', ''),
                           r'Microsoft\Windows\Start Menu\Programs\Startup', 'ClaudePet.vbs')

# ---------------------------------------------------------------- Win32 helpers
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [('cbSize', wt.UINT), ('dwTime', wt.DWORD)]


def idle_seconds():
    li = LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(li)
    if not user32.GetLastInputInfo(ctypes.byref(li)):
        return 0
    return ((kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0


def fg_exe():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ''
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)
    if not h:
        return ''
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h)
    return ''


def work_area():
    r = wt.RECT()
    user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right, r.bottom


def screen_height():
    return user32.GetSystemMetrics(1)


def system_dpi():
    try:
        return user32.GetDpiForSystem()
    except Exception:
        return 96


def log(msg):
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except Exception:
        pass


# ---------------------------------------------------------------- config
DEFAULT_CFG = {
    'pixel': 2.5,                # 每个象限像素的宽度（逻辑像素）；2.5 = 吉祥物原大，约 40×25
    'autostart': False,
    'sleep_after_min': 5,        # 你离开多久后小克睡着
    'leave_after_min': 20,       # 你离开多久后小克下班躲起来
    'break_remind_min': 50,      # 连续工作多久提醒休息
    'work_apps': [               # 这些程序在前台 = 你开始工作了
        'code.exe', 'cursor.exe', 'windsurf.exe', 'trae.exe', 'devenv.exe', 'sublime_text.exe',
        'notepad++.exe', 'idea64.exe', 'pycharm64.exe', 'webstorm64.exe', 'clion64.exe',
        'goland64.exe', 'rider64.exe', 'phpstorm64.exe', 'datagrip64.exe', 'studio64.exe',
        'hbuilderx.exe', 'windowsterminal.exe', 'wt.exe', 'powershell.exe', 'pwsh.exe', 'cmd.exe',
        'claude.exe', 'winword.exe', 'excel.exe', 'powerpnt.exe', 'wps.exe', 'et.exe', 'wpp.exe',
        'typora.exe', 'obsidian.exe', 'notion.exe', 'acrobat.exe', 'acrord32.exe', 'sumatrapdf.exe',
    ],
    'code_apps': [               # 这些程序在前台时小克更爱敲代码
        'code.exe', 'cursor.exe', 'windsurf.exe', 'trae.exe', 'devenv.exe', 'sublime_text.exe',
        'notepad++.exe', 'idea64.exe', 'pycharm64.exe', 'webstorm64.exe', 'clion64.exe',
        'goland64.exe', 'rider64.exe', 'phpstorm64.exe', 'datagrip64.exe', 'studio64.exe',
        'hbuilderx.exe', 'windowsterminal.exe', 'wt.exe', 'powershell.exe', 'pwsh.exe', 'cmd.exe',
        'claude.exe',
    ],
    'read_apps': [               # 这些程序在前台时小克更爱翻书
        'chrome.exe', 'msedge.exe', 'firefox.exe', 'winword.exe', 'wps.exe', 'typora.exe',
        'obsidian.exe', 'notion.exe', 'acrobat.exe', 'acrord32.exe', 'sumatrapdf.exe',
    ],
}


def load_cfg():
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    try:
        with open(CFG_PATH, 'r', encoding='utf-8') as f:
            cfg.update(json.load(f))
        if cfg.pop('size', None) is not None:   # 旧版配置：改用新的默认大小
            cfg['pixel'] = DEFAULT_CFG['pixel']
            save_cfg(cfg)
    except FileNotFoundError:
        save_cfg(cfg)
    except Exception:
        log('config error: ' + traceback.format_exc())
    for k in ('work_apps', 'code_apps', 'read_apps'):
        cfg[k] = [a.lower() for a in cfg[k]]
    return cfg


def save_cfg(cfg):
    try:
        with open(CFG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        log('save config error: ' + traceback.format_exc())


def set_autostart(on):
    if on:
        pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        if not os.path.exists(pyw):
            pyw = sys.executable
        script = os.path.abspath(__file__)
        vbs = 'CreateObject("WScript.Shell").Run """%s"" ""%s""", 0, False\r\n' % (pyw, script)
        with open(STARTUP_VBS, 'w', encoding='utf-16') as f:   # 带 BOM，支持中文路径
            f.write(vbs)
    elif os.path.exists(STARTUP_VBS):
        os.remove(STARTUP_VBS)


# ---------------------------------------------------------------- look & words
CLAUDE = '#D77757'      # Claude Code 吉祥物同色
EYE = '#000000'
KEY = '#010203'         # 透明色键

SIZES = [('迷你', 2.0), ('吉祥物原大（默认）', 2.5), ('稍大', 3.5), ('大', 5.0)]

W, H = 20, 14           # 小克窗口（细网格，1 细格 = 象限像素宽 = 半个象限像素高），刚好装下小克
OX, OY = 1, H - 10      # 小克左上角所在细网格（上方留 4 格给蹦跳和举手）

SNIPPETS = [
    ['def hello(name):', '    print(f"hi {name}")', '', 'hello("world")'],
    ['const add = (a, b) =>', '  a + b;', 'console.log(add(1, 2))'],
    ['for i in range(10):', '    if i % 2 == 0:', '        yield i'],
    ['git add .', 'git commit -m "fix"', 'git push'],
    ['SELECT name FROM user', 'WHERE active = 1', 'ORDER BY id;'],
    ['fn main() {', '    let x = 42;', '    println!("{x}");', '}'],
    ['# TODO: 修 bug', 'try:', '    run()', 'except Error:', '    retry()'],
    ['class Cat:', '    def meow(self):', '        return "喵"'],
    ['npm run build', '✓ built in 1.2s'],
    ['while (!done) {', '  think();', '  code();', '}'],
]
CODE_COLORS = {
    'kw': '#e8916f', 'str': '#9ec97f', 'cmt': '#8b8a85', 'plain': '#e8e6e1', 'ok': '#7fd18b',
}
GLYPHS = ['{ }', '</>', ';', '( )', '=>', '#', '01', '[ ]', '&&', '++']
GLYPH_COLORS = ['#e8916f', '#7fb6e8', '#9ec97f', '#c49be8', '#f2c46d']

GREET = ['开工啦！我来陪你～', '嗨！今天也一起加油吧', '小克已上线，准备干活！']
BACK = ['欢迎回来！继续冲～', '你回来啦！我刚刚可没偷懒']
POKE = ['嘿嘿～', '别戳啦，痒！', '我在认真干活呢', '要不要喝口水？', '你今天超棒的！',
        'Bug 退散！', '一起摸会儿鱼？（小声）', '我会一直陪着你的']
TYPING = ['这个 bug 交给我！', '又写了一行～', '编译通过啦！', '让我想想怎么写更优雅']
TYPE_HELLO = ['你好呀～在问什么呢？', '嗨！我在听～', '又来找 Claude 聊天啦', '想到什么好问题了？',
              '慢慢打，我等你～']
TYPE_HELLO_CODE = ['要写代码啦？我准备好了！', '嗨～这次要做什么？', '你说，我来敲！', '新需求来啦？']
DAZE = ['（发呆中…）', '让代码飞一会儿～', '盯——', '放空一下脑袋']
TYPE_WAKE = ['嗯？你在打字…早呀～', '啊！我醒了我醒了', '你好呀，刚眯了一会儿～']
READING = ['嗯…原来如此', '这本书好有意思', '翻页翻页～', '学到了学到了']


def code_color(line):
    s = line.strip()
    if s.startswith('#') or s.startswith('//'):
        return CODE_COLORS['cmt']
    if s.startswith('✓'):
        return CODE_COLORS['ok']
    first = s.split(' ')[0] if s else ''
    if first in ('def', 'class', 'const', 'for', 'if', 'fn', 'let', 'while', 'try:', 'except',
                 'return', 'SELECT', 'WHERE', 'ORDER', 'git', 'npm', 'yield'):
        return CODE_COLORS['kw']
    if '"' in s:
        return CODE_COLORS['str']
    return CODE_COLORS['plain']


# ---------------------------------------------------------------- watch Claude
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetAsyncKeyState.restype = ctypes.c_short
BOX_PAD = 8             # 输入框外框比里面的文字区高出多少（逻辑像素）
TYPE_KEYS = list(range(0x30, 0x5B)) + list(range(0x60, 0x70)) + [0x08, 0x0D, 0x20, 0xE5] + \
    list(range(0xBA, 0xC1)) + list(range(0xDB, 0xDF))
user32.GetAncestor.restype = wt.HWND
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]


def pid_exe(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return ''
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(h)
    return ''


def claude_windows():
    """Claude 桌面版的可见主窗口（终端里的 claude CLI 没有自己的窗口，不算）"""
    found, cache = [], {}

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in cache:
                cache[pid.value] = os.path.basename(pid_exe(pid.value)).lower() == 'claude.exe'
            if cache[pid.value]:
                found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def classify(urls):
    """根据 Claude 窗口里正在显示的页面判断是 Code 还是 Chat"""
    pages = [u.split(' ', 1)[1] for u in urls.split(' | ') if ' ' in u]
    main = [p for p in pages if p.startswith('https://claude.ai/') and '/artifact/' not in p]
    for p in main:
        path = p[len('https://claude.ai'):]
        if path.startswith('/code') or 'claude-code' in path or path.startswith('/epitaxy'):
            return 'code'
    if main:
        return 'chat'
    return 'code'   # 没有 claude.ai 网页、只有本地界面 = Code 标签页


def parse_usage(text):
    """把“用量：5 小时限额的 72%23:50 重置”这类文字拆成 [(名称, 百分比, 重置时间)]"""
    import re
    found = []
    for seg in text.split(';;'):
        m = re.search(r'(\d+)\s*%', seg)
        if not m:
            continue
        low = seg.lower()
        if '周' in seg or 'week' in low:
            name = '每周限额'
        elif '小时' in seg or 'hour' in low:
            h = re.search(r'(\d+)\s*(小时|-?\s*hour)', seg, re.I)
            name = '%s 小时限额' % (h.group(1) if h else '5')
        else:
            name = '限额'
        reset = seg[m.end():].strip(' ：:，,')
        if name not in [f[0] for f in found]:   # 同一种限额只报一次
            found.append((name, int(m.group(1)), reset))
    return found


class ClaudeWatch:
    """后台线程：每 1.5 秒看一眼 Claude 是关着、在前台用 Code、在前台用 Chat，还是在后台"""

    def __init__(self):
        self.mode = 'closed' if not claude_windows() else 'other'
        self.last_urls = None
        self.proc = None
        self.main = None        # Claude 主窗口句柄
        self.box_rel = None     # 输入框相对 Claude 窗口左上角的位置 (dx, dy, w, h)
        self.fg_claude = False  # Claude 是否在前台
        self.usage = []         # [(名称, 百分比, 重置时间)]，Claude 输入框旁的“用量”按钮
        self.usage_at = 0       # 上次读到用量的时间
        threading.Thread(target=self.run, daemon=True).start()

    @staticmethod
    def rect(hwnd):
        r = wt.RECT()
        if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return r.left, r.top, r.right, r.bottom

    def probe(self, hwnd):
        import subprocess
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                 os.path.join(APP_DIR, 'claude_probe.ps1')],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=0x08000000, text=True, encoding='utf-8', errors='replace', bufsize=1)
        self.proc.stdin.write('%d\n' % int(hwnd))
        self.proc.stdin.flush()
        return self.proc.stdout.readline().strip()

    def run(self):
        me = os.getpid()
        while True:
            try:
                wins = claude_windows()
                fgc = False
                if not wins:
                    mode = 'closed'
                    self.main = None
                else:
                    def area(h):
                        r = self.rect(h) or (0, 0, 0, 0)
                        return (r[2] - r[0]) * (r[3] - r[1])
                    main = max(wins, key=area)
                    if main != self.main:
                        self.main, self.box_rel = main, None
                    fg = user32.GetForegroundWindow()
                    root = user32.GetAncestor(fg, 3) if fg else None   # GA_ROOTOWNER
                    pid = wt.DWORD()
                    if fg:
                        user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
                    if pid.value == me:
                        mode = self.mode            # 正在点小克自己，保持原样
                        fgc = self.fg_claude
                    elif fg in wins or root in wins:
                        fgc = True
                        res = self.probe(self.main)
                        parts = res.split(' || ')
                        urls = parts[0]
                        box = parts[1] if len(parts) > 1 else ''
                        if len(parts) > 2 and urls != 'err':
                            self.usage = parse_usage(parts[2])
                            if self.usage:
                                self.usage_at = time.time()
                        if urls != self.last_urls:
                            log('Claude 页面: ' + (urls or '(无)'))
                            self.last_urls = urls
                        mode = classify(urls) if urls != 'err' else self.mode
                        wr = self.rect(self.main)
                        if box and wr:
                            v = [int(n) for n in box.split(',')]
                            x, y, w, h = v[:4]
                            mic = (v[4] - wr[0], v[5]) if len(v) >= 6 else None   # 麦克风按钮 (dx, 宽)
                            self.box_rel = (x - wr[0], y - wr[1], w, h, mic)
                        elif urls != 'err':
                            self.box_rel = None
                    else:
                        mode = 'other'
                if mode != self.mode:
                    log('模式: %s -> %s' % (self.mode, mode))
                self.mode = mode
                self.fg_claude = fgc
            except Exception:
                log('watch error: ' + traceback.format_exc())
            time.sleep(1.5)


# ---------------------------------------------------------------- the pet
class Pet:
    def __init__(self, show_now):
        self.cfg = load_cfg()
        self.inbox = queue.Queue()
        r = self.root = tk.Tk()
        r.title('小克')
        r.overrideredirect(True)
        r.config(bg=KEY)
        r.attributes('-transparentcolor', KEY)
        self.c = tk.Canvas(r, bg=KEY, highlightthickness=0, bd=0)
        self.c.pack()
        self.dpi = system_dpi() / 96.0
        # 气泡 / 代码窗口 / zzz 画在一个单独的、鼠标可穿透的浮层里，不占桌面
        ov = self.ov = tk.Toplevel(r)
        ov.overrideredirect(True)
        ov.config(bg=KEY)
        ov.attributes('-transparentcolor', KEY)
        self.ow, self.oh = int(300 * self.dpi), int(170 * self.dpi)
        self.oc = tk.Canvas(ov, bg=KEY, highlightthickness=0, bd=0, width=self.ow, height=self.oh)
        self.oc.pack()
        ov.withdraw()
        self.ov_shown = False
        self.ox = self.oy = 0

        self.state = 'hidden'
        self.st_t = 0
        self.st_dur = None
        self.t = 0
        self.x = self.y = 0.0
        self.vy = 0.0
        self.squash = 0
        self.hop = []
        self.blink = 0
        self.look = 0
        self.msg = ''
        self.msg_until = 0
        self.particles = []
        self.shown_once = False
        self.snooze_until = 0
        self.auto_sleep = False
        self.work_secs = 0
        self.fg = ''
        self.drag = None
        self.walk_to = 0
        self.ax = None          # 小克在输入框上沿的横向位置（相对输入框左端）
        self.rel_y = 0.0        # 跳进跳出时相对站立高度的偏移
        self.walk_hi = 0
        self.home_ax = None
        self.home_pos = 0
        self.ax_custom = False  # 被你拖到别处后就不再自动回麦克风上面
        self.walk_back = False
        self.owner = None
        self.last_key = 0
        self.last_greet = 0
        self.usage_lvl = {}
        self.poke_usage_at = 0     # 上次戳它报额度的时间
        self.flip = -1
        self.next_flip = 100
        self.new_code()

        self.apply_size()
        r.withdraw()

        self.c.bind('<ButtonPress-1>', self.on_press)
        self.c.bind('<B1-Motion>', self.on_motion)
        self.c.bind('<ButtonRelease-1>', self.on_release)
        self.c.bind('<Button-3>', self.on_menu)
        self.build_menu()

        self.manual_until = 0
        self.next_act = 0
        self.watch = ClaudeWatch()
        threading.Thread(target=self.server, daemon=True).start()
        r.after(50, self.loop)
        r.after(1500, self.monitor)
        if show_now:
            r.after(400, lambda: self.summon('greet'))

    # ------------------------------------------------ size & position
    def apply_size(self):
        old_s = getattr(self, 'S', None)
        self.S = max(2, int(self.cfg['pixel'] * self.dpi + 0.5))
        S = self.S
        self.ww, self.wh = W * S, H * S
        self.c.config(width=self.ww, height=self.wh)
        d = self.dpi
        self.f_msg = ('Microsoft YaHei UI', -int(12 * d))
        self.f_code = ('Consolas', -int(7 * d))
        self.f_small = ('Consolas', -int(9 * d), 'bold')
        self.f_big = ('Consolas', -int(11 * d), 'bold')
        if old_s and self.state != 'hidden':
            self.follow(force=True)

    def place(self):
        self.root.geometry('%dx%d+%d+%d' % (self.ww, self.wh, int(self.x), int(self.y)))
        l, t, r, b = work_area()
        ox = int(self.x + self.ww + 14 * self.dpi - self.ow)
        oy = int(self.y + self.wh - self.oh)
        self.ox, self.oy = max(l, ox), max(t, oy)
        self.ov.geometry('%dx%d+%d+%d' % (self.ow, self.oh, self.ox, self.oy))

    def overlay(self, show):
        if show and not self.ov_shown:
            self.ov.deiconify()
            self.attach(force=True)
            self.root.lift()
            try:  # 整个浮层鼠标穿透、不抢焦点、不进任务栏
                GWL_EXSTYLE = -20
                hwnd = user32.GetParent(self.ov.winfo_id()) or self.ov.winfo_id()
                st = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, st | 0x80000 | 0x20 | 0x80 | 0x08000000)
            except Exception:
                log('overlay style error: ' + traceback.format_exc())
        elif not show and self.ov_shown:
            self.ov.withdraw()
        self.ov_shown = show

    def perch(self):
        """小克站的地方：Claude 输入框的上沿；没找到输入框就站在 Claude 窗口顶上。返回 (左, 宽, 脚底 y)"""
        d = self.dpi
        wr = ClaudeWatch.rect(self.watch.main)
        if not wr:
            l, t, r, b = work_area()
            return l, r - l, b
        rel = self.watch.box_rel
        self.home_ax = None
        if rel:
            left, width = wr[0] + rel[0], rel[2]
            if rel[4]:                       # 麦克风按钮：站在它正上方（小克身体中心对准按钮中心）
                mic_l, mic_w = wr[0] + rel[4][0], rel[4][1]
                width = max(width, mic_l + mic_w + int(4 * d) - left)
                self.home_ax = mic_l + mic_w / 2 - left - 9 * self.S
            return left, width, wr[1] + rel[1] - int(BOX_PAD * d)
        return wr[0] + int(120 * d), (wr[2] - wr[0]) - int(240 * d), wr[1] + int(2 * d)

    def follow(self, force=False):
        """跟着 Claude 窗口 / 输入框走（窗口挪到哪，小克就跟到哪）"""
        left, width, feet = self.perch()
        self.walk_hi = hi = max(0, width - 18 * self.S)
        home = self.home_ax if self.home_ax is not None else hi * 0.95
        self.home_pos = min(max(home, 0), hi)
        if self.ax is None or (not self.ax_custom and self.state != 'walk'):
            self.ax = self.home_pos              # 默认待在麦克风上面
        self.ax = min(max(self.ax, 0), hi)
        x = left + self.ax - OX * self.S
        y = feet - self.wh + (self.rel_y if self.state in ('enter', 'exit') else 0)
        if force or int(x) != int(self.x) or int(y) != int(self.y):
            self.x, self.y = x, y
            self.place()

    def attach(self, force=False):
        """把小克挂在 Claude 窗口上：永远在 Claude 上面，但不挡别的程序；Claude 最小化它也跟着藏"""
        owner = self.watch.main
        if not owner or (owner == self.owner and not force):
            return
        self.owner = owner
        for w in (self.root, self.ov):
            try:
                user32.SetWindowLongPtrW(user32.GetAncestor(w.winfo_id(), 2), -8, owner)
            except Exception:
                log('attach error: ' + traceback.format_exc())

    # ------------------------------------------------ state machine
    def set_state(self, st, dur=None):
        self.state = st
        self.st_t = 0
        self.st_dur = dur
        if st == 'typing':
            self.new_code()
        elif st == 'reading':
            self.flip, self.next_flip = -1, random.randint(80, 140)
        elif st == 'walk':
            self.walk_to = random.uniform(0, self.walk_hi)
            self.walk_back = True

    def choose_next(self):
        mode = self.watch.mode
        if mode == 'code':                      # Code 时：主要敲代码，也爱发呆和思考
            st = random.choices(('typing', 'thinking', 'idle'), (6, 2, 2))[0]
            dur = {'typing': (400, 900), 'thinking': (120, 240), 'idle': (160, 320)}[st]
            self.set_state(st, random.randint(*dur))
            if st == 'idle' and random.random() < 0.4:
                self.say(random.choice(DAZE), 3)
        elif mode == 'chat':
            self.set_state('reading')
        else:
            self.set_state('sleep')
            self.next_act = time.time() + random.uniform(180, 420)

    def summon(self, kind='greet'):
        if self.state != 'hidden':
            self.say(random.choice(GREET if kind == 'greet' else BACK))
            return
        self.shown_once = True
        self.work_secs = 0
        self.state = 'enter'
        self.rel_y = 10 * self.S                 # 从输入框里蹦出来
        self.g = 0.9 * self.S
        self.vy = -math.sqrt(2 * self.g * (self.rel_y + 12 * self.S))
        self.follow(force=True)
        self.root.deiconify()
        self.attach(force=True)
        self.set_state('enter')
        self.greet_text = random.choice(GREET if kind == 'greet' else BACK)

    def leave(self, snooze=0):
        if self.state in ('hidden', 'exit'):
            return
        self.snooze_until = time.time() + snooze
        self.g = 0.9 * self.S
        self.vy = -math.sqrt(2 * self.g * 6 * self.S)
        self.rel_y = 0.0
        self.set_state('exit')

    def say(self, text, secs=4.0):
        self.msg = text
        self.msg_until = time.time() + secs

    def new_code(self):
        self.snip = random.choice(SNIPPETS)
        self.li = 0
        self.ci = 0
        self.code_lines = getattr(self, 'code_lines', [])[-6:]
        self.pause = 8
        self.typing_now = False

    # ------------------------------------------------ main loop
    def loop(self):
        try:
            while not self.inbox.empty():
                cmd = self.inbox.get_nowait()
                if cmd == 'show':
                    self.snooze_until = 0
                    self.summon('greet')
            if self.state != 'hidden':
                self.attach()
                self.step()
                if self.state not in ('hidden', 'enter', 'exit') and not (self.drag and self.drag['moved']):
                    self.follow()
                self.check_typing()
                if self.state != 'hidden':
                    self.render()
        except Exception:
            log('loop error: ' + traceback.format_exc())
        self.root.after(50, self.loop)

    def step(self):
        self.t += 1
        self.st_t += 1
        st = self.state
        S = self.S
        # 眨眼 & 张望
        if self.blink > 0:
            self.blink -= 1
        elif random.random() < 1 / 70:
            self.blink = 3
        if st == 'idle' and random.random() < 1 / 50:
            self.look = random.choice((-1, 0, 0, 1))
        if self.hop:
            self.hop.pop(0)
        if self.squash:
            self.squash -= 1
        if self.msg and time.time() > self.msg_until:
            self.msg = ''
        for p in self.particles:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['life'] -= 1
        self.particles = [p for p in self.particles if p['life'] > 0]

        if st == 'enter':
            self.rel_y += self.vy
            self.vy += self.g
            if self.vy > 0 and self.rel_y >= 0:
                self.rel_y = 0.0
                self.squash = 4
                self.say(self.greet_text, 4.5)
                self.set_state('greet', 60)
            self.follow()
            return
        elif st == 'exit':
            self.rel_y += self.vy
            self.vy += self.g
            self.follow()
            if self.rel_y > 12 * S:
                self.root.withdraw(); self.overlay(False)
                self.state = 'hidden'
                self.msg = ''
                self.particles = []
            return
        elif st == 'walk':
            d = self.walk_to - self.ax
            sp = max(1.0, S * 0.5)
            self.look = 1 if d > 0 else -1
            if abs(d) <= sp:
                if self.walk_back and not self.ax_custom:   # 散完步走回麦克风上面
                    self.walk_back = False
                    self.walk_to = self.home_pos
                    return
                self.choose_next()
                return
            self.ax += sp if d > 0 else -sp
        elif st == 'typing':
            self.step_typing()
        elif st == 'reading':
            self.look = (-1, 0, 1)[(self.st_t // 12) % 3]
            if self.flip >= 0:
                self.flip += 1
                if self.flip > 12:
                    self.flip = -1
                    self.next_flip = self.st_t + random.randint(90, 160)
            elif self.st_t >= self.next_flip:
                self.flip = 0
            if self.st_t == 200 and random.random() < 0.5:
                self.say(random.choice(READING))
        elif st == 'sleep':
            if self.st_t % 22 == 0:
                self.particles.append(dict(x=OX + 14, y=OY + 1, vx=0.25, vy=-0.4, life=40,
                                           text=random.choice('zZZ'), color='#8fb4ec', big=True))
        elif st == 'wake':
            if self.st_t == 1 and not self.msg:
                self.say('我…我没睡着！', 3)
        elif st == 'stretch':
            if self.st_t == 1:
                self.say('伸个懒腰～', 2.5)

        if self.st_dur is not None and self.st_t >= self.st_dur and st not in ('sleep', 'hidden'):
            self.choose_next()

    def step_typing(self):
        self.typing_now = False
        if self.pause > 0:
            self.pause -= 1
            return
        line = self.snip[self.li]
        if self.ci < len(line):
            if random.random() < 0.6:
                self.ci += 1
                self.typing_now = True
        else:
            self.code_lines.append(line)
            self.li += 1
            self.ci = 0
            self.pause = random.randint(3, 10)
            if self.li >= len(self.snip):
                self.code_lines.append('')
                if random.random() < 0.25:
                    self.say(random.choice(TYPING), 3)
                self.new_code()
                self.pause = 30
        if self.typing_now and random.random() < 0.08:
            self.particles.append(dict(x=OX + random.uniform(3, 12), y=OY + 3, vx=random.uniform(-0.1, 0.1),
                                       vy=-0.5, life=30, text=random.choice(GLYPHS),
                                       color=random.choice(GLYPH_COLORS)))

    def usage_text(self):
        lines = []
        for name, pct, reset in self.watch.usage:
            s = '%s已用 %d%%' % (name, pct)
            if reset:
                s += '，%s' % reset
            if pct >= 90:
                s = '注意！' + s
            lines.append(s)
        return '\n'.join(lines)

    def check_usage(self, now):
        """用量越过 50/75/90/100% 时主动提醒（平时要戳它才报）"""
        u = self.watch.usage
        if not u or now - self.watch.usage_at > 120 or self.watch.mode not in ('code', 'chat'):
            return
        urgent = False
        for name, pct, _ in u:
            lvl = max([t for t in (50, 75, 90, 100) if pct >= t], default=0)
            if lvl > self.usage_lvl.get(name, lvl):
                urgent = True
            self.usage_lvl[name] = lvl
        if urgent:                              # 平时戳它才报额度，只有越过 50/75/90/100% 才主动提醒
            self.say(self.usage_text(), 7)
            self.hop = [-1, -2, -2, -1, 0]

    def ask_usage(self):
        if self.state == 'hidden':
            return
        if self.watch.usage and time.time() - self.watch.usage_at < 600:
            self.say(self.usage_text(), 7)
        else:
            self.say('Claude 输入框旁边现在没显示用量，应该还挺充足～', 4)

    def check_typing(self):
        """你在 Claude 里一开始打字，小克就跟你打招呼"""
        if not self.watch.fg_claude or self.state in ('hidden', 'enter', 'exit'):
            return
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in TYPE_KEYS):
            return
        now = time.time()
        if now - self.last_key > 15 and now - self.last_greet > 25:
            self.last_greet = now
            self.hop = [-1, -2, -2, -1, 0]
            if self.state == 'sleep':
                self.auto_sleep = False
                self.set_state('wake', 30)
                self.say(random.choice(TYPE_WAKE), 3)
            else:
                self.say(random.choice(TYPE_HELLO_CODE if self.watch.mode == 'code' else TYPE_HELLO), 3)
        self.last_key = now

    # ------------------------------------------------ work monitor
    def monitor(self):
        try:
            self._monitor()
        except Exception:
            log('monitor error: ' + traceback.format_exc())
        self.root.after(1000, self.monitor)

    def _monitor(self):
        """跟着 Claude 走：Code → 敲代码，Chat → 看书，关掉 Claude → 离开，其他时候大多在睡觉"""
        now = time.time()
        idle = idle_seconds()
        cfg = self.cfg
        mode = self.watch.mode
        if self.state == 'hidden':
            if mode != 'closed' and now >= self.snooze_until:
                self.summon('back' if self.shown_once else 'greet')
            return
        if self.state in ('enter', 'exit'):
            return
        if self.t % 60 < 20:
            self.attach()
        if mode == 'closed':
            self.say('Claude 关掉啦，我也下班咯～', 2)
            self.leave()
            return
        if now < self.manual_until or self.state in ('greet', 'wake', 'stretch'):
            return
        want = {'code': 'typing', 'chat': 'reading'}.get(mode)
        if want and idle > cfg['sleep_after_min'] * 60:
            want = 'sleep'                      # 人走开了，小克也打个盹
        self.check_usage(now)
        if want == 'typing':                    # Code 时敲代码 / 发呆 / 思考轮着来
            if self.state not in ('typing', 'thinking', 'idle'):
                if self.state == 'sleep':
                    self.set_state('wake', 25)
                else:
                    self.choose_next()
        elif want:
            if self.state != want:
                if self.state == 'sleep' and want != 'sleep':
                    self.set_state('wake', 25)  # 先醒一下，醒完 choose_next 会切到 want
                else:
                    self.set_state(want)
        else:                                   # 用别的程序时：大部分时间睡觉，偶尔起来活动
            if self.state in ('typing', 'reading'):
                self.set_state('sleep')
                self.next_act = now + random.uniform(180, 420)
            elif self.state == 'sleep' and now >= self.next_act:
                self.next_act = now + random.uniform(180, 420)
                st, dur = random.choice((('stretch', 60), ('walk', None), ('thinking', 200), ('idle', 240)))
                self.set_state(st, dur)
        if idle < 60:
            self.work_secs += 1
            if self.work_secs >= cfg['break_remind_min'] * 60:
                self.work_secs = 0
                self.set_state('stretch', 60)
                self.say('已经连续工作 %d 分钟啦，起来活动一下、看看远处吧～' % cfg['break_remind_min'], 8)

    # ------------------------------------------------ drawing
    def px(self, x, y, w, h, color):
        S = self.S
        self.c.create_rectangle(round(x * S), round(y * S), round((x + w) * S), round((y + h) * S),
                                fill=color, width=0)

    def clawd(self, ox, oy, dy=0, eyes='open', look=0, arms=(0, 0), legs='stand'):
        C = CLAUDE
        # 腿（象限第 4 行：列 4、6、11、13）
        for i, lx in enumerate((4, 6, 11, 13)):
            top, bot = oy + 8 + dy, oy + 10
            if (legs == 'walkA' and i in (0, 2)) or (legs == 'walkB' and i in (1, 3)) or legs == 'tuck':
                bot -= 1
            if bot > top:
                self.px(ox + lx, top, 1, bot - top, C)
        # 身体（象限 3..14 列，0..3 行）
        self.px(ox + 3, oy + dy, 12, 8, C)
        # 手（象限第 2 行：列 1-2、15-16）
        self.px(ox + 1, oy + 4 + dy + arms[0], 2, 2, C)
        self.px(ox + 15, oy + 4 + dy + arms[1], 2, 2, C)
        # 眼睛（象限第 1 行：列 5、12 的缺口）
        for ex in (5, 12):
            x = ox + ex + look
            y = oy + dy
            if eyes == 'open':
                self.px(x, y + 2, 1, 2, EYE)
            elif eyes in ('blink', 'closed'):
                self.px(x, y + 3, 1, 1, EYE)
            elif eyes == 'up':
                self.px(x, y + 1, 1, 2, EYE)
            elif eyes == 'down':
                self.px(x, y + 3, 1, 2, EYE)
            elif eyes == 'wide':
                self.px(x, y + 1, 1, 3, EYE)

    def laptop(self, ox, oy):
        self.px(ox + 2, oy + 4, 14, 5, '#6f6e76')
        self.px(ox + 3, oy + 5, 12, 3, '#a9a8b1')
        self.px(ox + 8, oy + 6, 2, 1, '#d9d8de')
        self.px(ox + 0, oy + 9, 18, 1, '#4f4e55')

    def book(self, ox, oy):
        page, line = '#f6eedc', '#bdb19a'
        self.px(ox + 1, oy + 5, 16, 5, '#8a5634')
        self.px(ox + 2, oy + 5, 7, 4, page)
        self.px(ox + 9, oy + 5, 7, 4, page)
        self.px(ox + 8.7, oy + 5, 0.6, 4, '#d6c9ad')
        for i, ry in enumerate((5.8, 6.6, 7.4, 8.2)):
            self.px(ox + 2.8, oy + ry, (5.2, 4.6, 5.4, 3.6)[i], 0.35, line)
            self.px(ox + 9.8, oy + ry, (5.0, 5.4, 4.0, 5.2)[i], 0.35, line)
        f = self.flip
        if f >= 0:
            hi = '#fffaf0'
            if f < 4:
                self.px(ox + 9, oy + 4, 6, 4, hi)
            elif f < 8:
                self.px(ox + 8.4, oy + 1, 1.2, 8, hi)
                self.px(ox + 9.4, oy + 1, 0.3, 8, '#d6c9ad')
            else:
                self.px(ox + 3, oy + 4, 6, 4, hi)

    # ---- 浮层（像素坐标）：小克窗口左上角在浮层里的位置
    def fx(self, gx):
        return self.x - self.ox + gx * self.S

    def fy(self, gy):
        return self.y - self.oy + gy * self.S

    def rect(self, x0, y0, x1, y1, color):
        self.oc.create_rectangle(round(x0), round(y0), round(x1), round(y1), fill=color, width=0)

    def code_panel(self):
        """小克左边的迷你终端（宽 64、高 28 逻辑像素，只显示 2 行）"""
        d, oc = self.dpi, self.oc
        x1, y1 = self.fx(OX) - 2 * d, self.fy(H)
        x0, y0 = x1 - 64 * d, y1 - 28 * d
        self.rect(x0, y0, x1, y1, '#262624')
        self.rect(x0, y0, x1, y0 + 5 * d, '#3b3a37')
        for i, col in enumerate(('#ec6a5e', '#f4bf4f', '#61c554')):
            cx = x0 + (3 + i * 4) * d
            self.rect(cx, y0 + 1.5 * d, cx + 2 * d, y0 + 3.5 * d, col)
        line_h = 9 * d
        nmax = 2
        cur = self.snip[self.li][:self.ci] if self.li < len(self.snip) else ''
        lines = (self.code_lines + [cur])[-nmax:]
        maxc = max(8, int((x1 - x0 - 5 * d) / (7 * d * 0.55)))
        last = None
        for i, ln in enumerate(lines):
            last = oc.create_text(x0 + 3 * d, y0 + 6.5 * d + i * line_h, anchor='nw',
                                  text=ln[:maxc], fill=code_color(ln), font=self.f_code)
        if last is not None and (self.t // 6) % 2 == 0:
            bb = oc.bbox(last)
            cx = bb[2] + 1 if lines[-1] else x0 + 3 * d
            self.rect(cx, bb[1] + 1.5 * d, cx + 1.5 * d, bb[3] - d, CLAUDE)
        return y0

    def bubble(self, text, bottom, think=False):
        """bottom：气泡底边在浮层里的像素 y"""
        S, d, oc = self.S, self.dpi, self.oc
        b = max(1, int(d))
        pad = int(5 * d)
        right = self.fx(OX + 17)
        item = oc.create_text(0, 0, text=text, font=self.f_msg, fill='#2b2a28', anchor='se',
                              width=int(150 * d), justify='left')
        bb = oc.bbox(item)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        y1 = bottom - (8 * d if think else 6 * d)
        x1, x0, y0 = right, right - tw - 2 * pad, y1 - th - 2 * pad
        if x0 < 2:
            x1 += 2 - x0
            x0 = 2
        if y0 < 1:
            y1 += 1 - y0
            y0 = 1
        ink, fill = '#2b2a28', '#fffdf8'
        cr = 2 * b
        self.rect(x0 + cr, y0, x1 - cr, y1, ink)
        self.rect(x0, y0 + cr, x1, y1 - cr, ink)
        self.rect(x0 + cr, y0 + b, x1 - cr, y1 - b, fill)
        self.rect(x0 + b, y0 + cr, x1 - b, y1 - cr, fill)
        hx = self.fx(OX + 9)
        if think:
            for cx, cy, rr in ((hx - 4 * d, y1 + 3 * d, 2.5 * d), (hx - 1 * d, y1 + 6.5 * d, 1.5 * d)):
                oc.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=fill, outline=ink, width=b)
        else:
            tx = min(max(hx, x0 + 8 * d), x1 - 8 * d)
            oc.create_polygon(tx - 4 * d, y1 - b, tx + 3 * d, y1 - b, tx + 1 * d, y1 + 5 * d,
                              fill=fill, outline=ink, width=b)
            self.rect(tx - 4 * d + b, y1 - 2 * b, tx + 3 * d - b, y1 - b + 1, fill)
        oc.coords(item, x1 - pad, y1 - pad)
        oc.tag_raise(item)

    def render(self):
        c = self.c
        c.delete('all')
        st, k = self.state, self.st_t
        ox, oy = OX, OY
        if self.hop:
            oy += self.hop[0]
        dy, eyes, look, arms, legs = 0, 'open', self.look, (0, 0), 'stand'
        breath = -1 if (self.t % 36) < 12 else 0
        if self.blink:
            eyes = 'blink'

        if st == 'idle':
            dy = breath
        elif st in ('enter', 'exit'):
            arms, legs = (-3, -3), 'tuck'
            eyes = 'wide' if self.vy < 0 else 'open'
            look = 0
        elif st == 'greet':
            arms = (0, -2 if (k // 4) % 2 else -3)
            eyes = 'closed' if 15 < k < 40 else eyes
            dy = breath
            look = 0
        elif st == 'walk':
            legs = 'walkA' if (k // 4) % 2 else 'walkB'
            dy = -1 if (k // 4) % 2 else 0
            arms = (-1, 0) if (k // 4) % 2 else (0, -1)
        elif st == 'typing':
            look = 0
            if self.typing_now or self.pause == 0:
                arms = (-1, 0) if (self.t // 2) % 2 else (0, -1)
        elif st == 'reading':
            arms = (1, 1)
        elif st == 'thinking':
            eyes = 'up' if not self.blink else eyes
            look = -1 if (k // 30) % 2 else 1
            arms = (0, -1)
            dy = breath
        elif st == 'sleep':
            eyes = 'closed'
            dy = 1 if (self.t % 50) < 25 else 0
            look = 0
        elif st == 'wake':
            eyes, look = 'wide', 0
            arms = (-2, -2) if k < 15 else (0, 0)
        elif st == 'stretch':
            if 8 < k < 45:
                arms, dy, eyes = (-3, -3), -1, 'closed'
            else:
                arms = (-1, -1)
        if self.squash:
            dy = 1

        self.clawd(ox, oy, dy, eyes, look, arms, legs)
        if st == 'typing':
            self.laptop(ox, oy)
            self.code_panel()
        elif st == 'reading':
            self.book(ox, oy)
            self.px(ox + 1, oy + 5, 2, 2, CLAUDE)
            self.px(ox + 15, oy + 5, 2, 2, CLAUDE)

        # ---- 浮层：只有有东西要显示时才出现，且鼠标可穿透
        need = bool(self.msg or self.particles or st in ('typing', 'thinking'))
        self.overlay(need)
        oc = self.oc
        oc.delete('all')
        if not need:
            return
        top = self.fy(oy + dy)
        if st == 'typing':
            top = min(top, self.code_panel())
        for p in self.particles:
            oc.create_text(self.fx(p['x']), self.fy(p['y']), text=p['text'], fill=p['color'],
                           font=self.f_big if p.get('big') else self.f_small)
        if st == 'thinking':
            self.bubble('嗯' + '.' * (1 + (k // 8) % 3) + ' ' * (2 - (k // 8) % 3), top, think=True)
        elif self.msg:
            self.bubble(self.msg, top)

    # ------------------------------------------------ interaction
    def on_press(self, e):
        self.drag = dict(sx=e.x_root, sy=e.y_root, x=self.x, y=self.y, moved=False)

    def on_motion(self, e):
        if not self.drag or self.state in ('enter', 'exit'):
            return
        dx, dy = e.x_root - self.drag['sx'], e.y_root - self.drag['sy']
        if abs(dx) + abs(dy) > 4:
            self.drag['moved'] = True
        if self.drag['moved']:
            self.x, self.y = self.drag['x'] + dx, self.drag['y'] + dy
            self.place()

    def on_release(self, e):
        d, self.drag = self.drag, None
        if d and d['moved']:
            left, width, feet = self.perch()
            self.ax = self.x + OX * self.S - left   # 松手后落回输入框上沿
            self.ax_custom = True
            return
        if not d or self.state in ('enter', 'exit'):
            return
        self.poke()

    def poke(self):
        self.hop = [-1, -2, -3, -3, -2, -1, 0]
        self.particles.append(dict(x=OX + random.uniform(5, 12), y=OY - 1, vx=random.uniform(-0.1, 0.1),
                                   vy=-0.45, life=25, text='♥', color='#e0565b'))
        now = time.time()
        if self.state == 'sleep':
            self.auto_sleep = False
            self.set_state('wake', 40)
        if now - self.poke_usage_at >= 180:     # 3 分钟内第一次戳：告诉你额度；之后再戳就正常撒娇
            self.poke_usage_at = now
            self.ask_usage()
        elif self.state != 'wake':
            self.say(random.choice(POKE), 3)

    def do(self, st):
        if self.state == 'hidden':
            self.summon('greet')
            return
        self.auto_sleep = False
        self.manual_until = time.time() + 60    # 手动选的动作至少保持 1 分钟
        durs = {'typing': 1200, 'reading': 1200, 'thinking': 240, 'walk': None, 'stretch': 60,
                'sleep': None, 'idle': 400}
        self.set_state(st, durs[st])

    def build_menu(self):
        m = self.menu = tk.Menu(self.root, tearoff=0, font=('Microsoft YaHei UI', 10))
        for label, st in (('敲代码', 'typing'), ('翻书', 'reading'), ('思考', 'thinking'),
                          ('散步', 'walk'), ('伸懒腰', 'stretch'), ('睡觉', 'sleep'), ('发呆', 'idle')):
            m.add_command(label=label, command=lambda s=st: self.do(s))
        m.add_separator()
        self.size_var = tk.DoubleVar(value=self.cfg['pixel'])
        sm = tk.Menu(m, tearoff=0, font=('Microsoft YaHei UI', 10))
        for label, v in SIZES:
            sm.add_radiobutton(label=label, value=v, variable=self.size_var, command=self.change_size)
        m.add_cascade(label='大小', menu=sm)
        self.auto_var = tk.BooleanVar(value=os.path.exists(STARTUP_VBS))
        m.add_checkbutton(label='跟着 Claude 自动出现（开机自启）', variable=self.auto_var, command=self.toggle_auto)
        m.add_command(label='问问限额', command=self.ask_usage)
        m.add_command(label='回到麦克风上面', command=self.go_home)
        m.add_separator()
        m.add_command(label='躲起来（1 小时内不打扰）', command=lambda: self.leave(3600))
        m.add_command(label='退出', command=self.quit)

    def on_menu(self, e):
        self.auto_var.set(os.path.exists(STARTUP_VBS))
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def change_size(self):
        self.cfg['pixel'] = self.size_var.get()
        save_cfg(self.cfg)
        self.apply_size()

    def toggle_auto(self):
        try:
            set_autostart(self.auto_var.get())
            self.cfg['autostart'] = self.auto_var.get()
            save_cfg(self.cfg)
            self.say('好嘞，以后一打开 Claude 我就出现！' if self.auto_var.get() else '已取消开机自启', 3)
        except Exception:
            log('autostart error: ' + traceback.format_exc())
            self.say('设置开机自启失败了…', 3)

    def go_home(self):
        self.ax_custom = False
        self.follow(force=True)

    def quit(self):
        self.root.destroy()

    # ------------------------------------------------ single instance
    def server(self):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(('127.0.0.1', PORT))
            srv.listen(2)
            while True:
                conn, _ = srv.accept()
                with conn:
                    if conn.recv(16).startswith(b'show'):
                        self.inbox.put('show')
        except Exception:
            log('server error: ' + traceback.format_exc())


def already_running():
    try:
        with socket.create_connection(('127.0.0.1', PORT), timeout=0.5) as s:
            s.sendall(b'show' if '--show' in sys.argv else b'ping')
        return True
    except OSError:
        return False


if __name__ == '__main__':
    if already_running():
        sys.exit(0)
    pet = Pet(show_now='--show' in sys.argv)
    pet.root.mainloop()

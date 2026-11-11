"""
Hapax Mapper - map an MPC 3 project to the Squarp Hapax.

Workflow: new project on the MPC -> save -> MPC in Controller Mode -> open it here -> choose channels and the
32 parameters (8 on the pots) per plugin -> MAP -> MPC -> Copy to SD card -> play.

Double-click "Hapax Mapper.cmd" (or: pyw hapax_mapper.pyw ["path\\to\\project.xpj" [track#]]).
"""
import os, queue, shutil, sys, threading, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
import hapax_integration as hi
import mpc_map as mm

# ---- look: dark, flat, one accent (DAW style) ----------------------------------------------------------
BG, PANEL, PANEL2, LINE = '#17171a', '#1f1f23', '#29292e', '#34343b'
TEXT, MUTED, DIM = '#dcdce1', '#8a8a94', '#5c5c66'
ACCENT, ACCENT_DK, AMBER, GREEN, RED = '#ff7a1a', '#3a2412', '#e8b04a', '#6fcf8e', '#ff5d5d'
STRIPE, SEL, POT_BG, POT_FG = '#222227', '#6a3a14', '#2a1f16', '#ffd2b0'
THUMB, THUMB_HI = '#3d3d45', '#55555f'
POT_VALUES = ['—'] + [str(i) for i in range(1, 9)]

def _dpi_aware():
    try:
        import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

def _dark_titlebar(win):
    try:                                                    # Windows 10 20H1+ / 11: dark caption bar
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        v = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass

class App(tk.Tk):
    def __init__(self, initial=None):
        super().__init__()
        self.title('Hapax Mapper')
        self.s = self.winfo_fpixels('1i') / 96.0                     # display scale (1.0 at 100%)
        self.geometry(f'{self.px(1340)}x{self.px(860)}')
        self.minsize(self.px(1100), self.px(700))
        self.configure(bg=BG)
        self.analysis, self.selections, self.overrides = None, {}, {}
        self.cur_plugin, self.last_defs, self._ch_job = None, [], None
        self.mpc, self.sd = {}, []
        self.q = queue.Queue()
        self._style()
        self._build()
        self.after(50, lambda: _dark_titlebar(self))
        self.after(150, self._drain)
        self.after(300, self._poll_devices)
        if initial:
            self.path.set(initial); self.after(200, self.load)

    def px(self, v):
        return int(v * self.s)

    # ---------- styling ----------
    def _style(self):
        P = self.px
        self.f_ui = tkfont.Font(family='Segoe UI', size=10)
        self.f_small = tkfont.Font(family='Segoe UI', size=8, weight='bold')
        self.f_head = tkfont.Font(family='Segoe UI Semibold', size=12)
        self.f_btn = tkfont.Font(family='Segoe UI Semibold', size=10)
        self.f_brand = tkfont.Font(family='Segoe UI Black', size=14)
        self.f_mono = tkfont.Font(family='Consolas', size=10)
        self.f_log = tkfont.Font(family='Consolas', size=9)
        row = int(self.f_ui.metrics('linespace') * 1.8)
        st = ttk.Style(self); st.theme_use('clam')
        st.configure('.', background=BG, foreground=TEXT, fieldbackground=PANEL2, bordercolor=LINE,
                     lightcolor=PANEL, darkcolor=PANEL, troughcolor=PANEL, font=self.f_ui, focuscolor=PANEL2,
                     selectbackground=ACCENT, selectforeground='#1a1206')
        st.configure('TFrame', background=BG)
        st.configure('Panel.TFrame', background=PANEL)
        for name, kw in (('TLabel', {}), ('Panel.TLabel', {}),
                         ('Muted.TLabel', {'foreground': MUTED}),
                         ('Warn.TLabel', {'foreground': AMBER}),
                         ('Section.TLabel', {'foreground': MUTED, 'font': self.f_small}),
                         ('Head.TLabel', {'font': self.f_head}),
                         ('Brand.TLabel', {'font': self.f_brand}),
                         ('BrandAcc.TLabel', {'foreground': ACCENT, 'font': self.f_brand}),
                         ('Count.TLabel', {'foreground': MUTED, 'font': self.f_mono}),
                         ('Pill.TLabel', {'background': PANEL2, 'foreground': MUTED, 'font': self.f_small, 'padding': (P(9), P(4))}),
                         ('PillOn.TLabel', {'background': ACCENT_DK, 'foreground': ACCENT, 'font': self.f_small, 'padding': (P(9), P(4))})):
            st.configure(name, **{'background': PANEL, 'foreground': TEXT, **kw})
        st.configure('TButton', background=PANEL2, foreground=TEXT, borderwidth=0, focusthickness=0, relief='flat',
                     padding=(P(12), P(6)), font=self.f_btn)
        st.map('TButton', background=[('pressed', ACCENT_DK), ('active', LINE), ('disabled', PANEL)],
               foreground=[('disabled', DIM)])
        st.configure('Accent.TButton', background=ACCENT, foreground='#1a1206', padding=(P(18), P(6)))
        st.map('Accent.TButton', background=[('pressed', '#e2650c'), ('active', '#ff9445'), ('disabled', ACCENT_DK)],
               foreground=[('disabled', DIM)])
        st.configure('Ghost.TButton', background=PANEL, foreground=MUTED, padding=(P(8), P(6)))
        st.map('Ghost.TButton', background=[('pressed', ACCENT_DK), ('active', PANEL2)], foreground=[('active', TEXT)])
        st.configure('TEntry', fieldbackground=PANEL2, foreground=TEXT, insertcolor=ACCENT, borderwidth=0, padding=P(5))
        st.map('TEntry', lightcolor=[('focus', ACCENT)], bordercolor=[('focus', ACCENT)])
        for w in ('TSpinbox', 'TCombobox'):
            st.configure(w, fieldbackground=PANEL2, foreground=TEXT, background=PANEL2, arrowcolor=MUTED, borderwidth=0,
                         insertcolor=ACCENT, padding=P(4), arrowsize=P(12))
            st.map(w, background=[('active', LINE)], arrowcolor=[('active', ACCENT)], fieldbackground=[('readonly', PANEL2)],
                   foreground=[('readonly', TEXT)], selectbackground=[('readonly', PANEL2)], selectforeground=[('readonly', TEXT)])
        for k, v in (('background', PANEL2), ('foreground', TEXT), ('selectBackground', ACCENT),
                     ('selectForeground', '#1a1206'), ('borderWidth', 0)):
            self.option_add(f'*TCombobox*Listbox.{k}', v)
        self.option_add('*TCombobox*Listbox.font', self.f_mono)
        st.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=row,
                     borderwidth=0, relief='flat', font=self.f_ui)
        st.map('Treeview', background=[('selected', SEL)], foreground=[('selected', '#ffffff')])
        st.configure('Treeview.Heading', background=PANEL, foreground=DIM, font=self.f_small, borderwidth=0,
                     relief='flat', padding=(P(6), P(7)))
        st.map('Treeview.Heading', background=[('active', PANEL)], foreground=[('active', MUTED)])
        st.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        st.configure('Vertical.TScrollbar', background=THUMB, troughcolor=PANEL, bordercolor=PANEL, borderwidth=0,
                     lightcolor=THUMB, darkcolor=THUMB, arrowsize=P(8), gripcount=0)   # clam: arrowsize = thickness
        st.map('Vertical.TScrollbar', background=[('active', THUMB_HI)], lightcolor=[('active', THUMB_HI)],
               darkcolor=[('active', THUMB_HI)])
        st.layout('Vertical.TScrollbar', [('Vertical.Scrollbar.trough', {'children': [
            ('Vertical.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})], 'sticky': 'ns'})])
        st.configure('Sash', sashthickness=P(8), background=BG, gripcount=0)

    # ---------- layout ----------
    def _build(self):
        P = self.px
        head = ttk.Frame(self, style='Panel.TFrame', padding=(P(18), P(12), P(18), P(6))); head.pack(fill='x')
        ttk.Label(head, text='HAPAX', style='Brand.TLabel').pack(side='left')
        ttk.Label(head, text=' ⇄ ', style='BrandAcc.TLabel').pack(side='left')
        ttk.Label(head, text='MPC', style='Brand.TLabel').pack(side='left')
        ttk.Label(head, text='   mapper', style='Muted.TLabel').pack(side='left', pady=(P(5), 0))
        self.sd_pill = ttk.Label(head, text='SD  ○', style='Pill.TLabel'); self.sd_pill.pack(side='right')
        self.mpc_pill = ttk.Label(head, text='MPC  ○  not connected', style='Pill.TLabel')
        self.mpc_pill.pack(side='right', padx=P(8))

        proj = ttk.Frame(self, style='Panel.TFrame', padding=(P(18), P(6), P(18), P(14))); proj.pack(fill='x')
        ttk.Label(proj, text='PROJECT', style='Section.TLabel').pack(side='left', padx=(0, P(12)))
        self.path = tk.StringVar()
        pe = ttk.Entry(proj, textvariable=self.path, font=self.f_ui); pe.pack(side='left', fill='x', expand=True)
        pe.bind('<Return>', lambda e: self.load())
        ttk.Button(proj, text='Open…', command=self.browse).pack(side='left', padx=(P(8), 0))
        ttk.Button(proj, text='Reload', style='Ghost.TButton', command=self.load).pack(side='left', padx=(P(4), 0))

        main = ttk.PanedWindow(self, orient='horizontal'); main.pack(fill='both', expand=True, padx=P(10), pady=(P(10), P(4)))
        left = ttk.Frame(main, style='Panel.TFrame', padding=P(14)); right = ttk.Frame(main, style='Panel.TFrame', padding=P(14))
        main.add(left, weight=2); main.add(right, weight=3)

        # --- tracks ---
        ttk.Label(left, text='TRACKS', style='Section.TLabel').pack(anchor='w')
        self.track_info = ttk.Label(left, text='Open a project saved on the MPC', style='Head.TLabel')
        self.track_info.pack(anchor='w', pady=(P(2), P(10)))
        tf = ttk.Frame(left, style='Panel.TFrame'); tf.pack(fill='both', expand=True)
        cols = ('n', 'ch', 'track', 'plugin', 'status')
        self.tracks = ttk.Treeview(tf, columns=cols, show='headings', selectmode='browse')
        for c, w, t, a in (('n', 34, '#', 'center'), ('ch', 40, 'CH', 'center'), ('track', 150, 'MPC TRACK', 'w'),
                           ('plugin', 105, 'INSTRUMENT', 'w'), ('status', 160, 'HAPAX', 'w')):
            self.tracks.heading(c, text=t, anchor=a)
            self.tracks.column(c, width=P(w), minwidth=P(30), anchor=a, stretch=(c == 'track'))
        self.tracks.tag_configure('odd', background=STRIPE)
        self.tracks.tag_configure('hand', foreground=AMBER)
        sb = ttk.Scrollbar(tf, orient='vertical', command=self.tracks.yview); self.tracks.configure(yscrollcommand=sb.set)
        self.tracks.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        self.tracks.bind('<<TreeviewSelect>>', self.on_track)
        chrow = ttk.Frame(left, style='Panel.TFrame'); chrow.pack(fill='x', pady=(P(12), 0))
        ttk.Label(chrow, text='MIDI CH', style='Section.TLabel').pack(side='left')
        self.ch = tk.StringVar()
        sp = ttk.Spinbox(chrow, from_=1, to=16, width=3, textvariable=self.ch, font=self.f_mono, command=self._ch_later)
        sp.pack(side='left', padx=P(8)); sp.bind('<Return>', lambda e: self.set_channel())
        ttk.Label(chrow, text='drums → 10, others fill 1–16', style='Muted.TLabel').pack(side='left')

        # --- parameters ---
        top = ttk.Frame(right, style='Panel.TFrame'); top.pack(fill='x')
        ttk.Label(top, text='PARAMETERS', style='Section.TLabel').pack(side='left')
        self.count = ttk.Label(top, text='', style='Count.TLabel'); self.count.pack(side='right')
        self.phead = ttk.Label(right, text='Select an instrument track', style='Head.TLabel')
        self.phead.pack(anchor='w', pady=(P(2), 0))
        self.pnote = ttk.Label(right, text='', style='Muted.TLabel', wraplength=P(600), justify='left')
        self.pnote.pack(anchor='w', fill='x', pady=(P(2), P(10)))
        right.bind('<Configure>', lambda e: self.pnote.configure(wraplength=max(P(200), e.width - P(32))))
        pf = ttk.Frame(right, style='Panel.TFrame'); pf.pack(fill='both', expand=True)
        pcols = ('use', 'pot', 'cc', 'name', 'label', 'page')
        self.params = ttk.Treeview(pf, columns=pcols, show='headings', selectmode='browse')
        for c, w, t, a in (('use', 34, '', 'center'), ('pot', 48, 'POT', 'center'), ('cc', 48, 'CC', 'center'),
                           ('name', 220, 'MPC PARAMETER', 'w'), ('label', 200, 'NAME ON HAPAX', 'w'), ('page', 70, 'Q-LINK', 'center')):
            self.params.heading(c, text=t, anchor=a)
            self.params.column(c, width=P(w), minwidth=P(30), anchor=a, stretch=(c in ('name', 'label')))
        self.params.tag_configure('pot', background=POT_BG, foreground=POT_FG)
        self.params.tag_configure('off', foreground=DIM)
        sb2 = ttk.Scrollbar(pf, orient='vertical', command=self.params.yview); self.params.configure(yscrollcommand=sb2.set)
        self.params.pack(side='left', fill='both', expand=True); sb2.pack(side='right', fill='y')
        self.params.bind('<<TreeviewSelect>>', self.on_param)
        self.params.bind('<Double-1>', lambda e: self.toggle())
        self.params.bind('<space>', lambda e: self.toggle())
        ctl = ttk.Frame(right, style='Panel.TFrame'); ctl.pack(fill='x', pady=(P(12), 0))
        ttk.Button(ctl, text='On / Off', command=self.toggle).pack(side='left')
        ttk.Label(ctl, text='POT', style='Section.TLabel').pack(side='left', padx=(P(16), P(6)))
        self.pot = tk.StringVar(value='—')
        cb = ttk.Combobox(ctl, values=POT_VALUES, width=3, textvariable=self.pot, state='readonly', font=self.f_mono)
        cb.pack(side='left'); cb.bind('<<ComboboxSelected>>', lambda e: self.set_pot())
        ttk.Label(ctl, text='NAME', style='Section.TLabel').pack(side='left', padx=(P(16), P(6)))
        self.lbl = tk.StringVar()
        e = ttk.Entry(ctl, textvariable=self.lbl, width=24, font=self.f_ui); e.pack(side='left')
        e.bind('<Return>', lambda ev: self.rename()); e.bind('<FocusOut>', lambda ev: self.rename())
        ttk.Button(ctl, text='▲', style='Ghost.TButton', width=2, command=lambda: self.move(-1)).pack(side='left', padx=(P(16), 0))
        ttk.Button(ctl, text='▼', style='Ghost.TButton', width=2, command=lambda: self.move(1)).pack(side='left')
        ttk.Button(ctl, text='Reset', style='Ghost.TButton', command=self.reset).pack(side='right')

        # --- action bar + log ---
        bar = ttk.Frame(self, style='Panel.TFrame', padding=(P(18), P(12))); bar.pack(fill='x', padx=P(10), pady=(P(6), 0))
        ttk.Label(bar, text='SAVE AS', style='Section.TLabel').pack(side='left', padx=(0, P(10)))
        self.outname = tk.StringVar()
        ttk.Entry(bar, textvariable=self.outname, width=32, font=self.f_ui).pack(side='left')
        self.mapbtn = ttk.Button(bar, text='MAP  →  MPC', style='Accent.TButton', command=self.do_map)
        self.mapbtn.pack(side='left', padx=P(10))
        ttk.Button(bar, text='Copy to SD card', command=self.copy_sd).pack(side='left')
        ttk.Button(bar, text='Save choices', style='Ghost.TButton', command=self.save_choices).pack(side='right')
        self.logbox = tk.Text(self, height=5, bg=BG, fg=MUTED, insertbackground=ACCENT, relief='flat', bd=0, wrap='word',
                              font=self.f_log, padx=P(20), pady=P(8), highlightthickness=0, selectbackground=SEL)
        self.logbox.pack(fill='both')
        for tag, col in (('ok', GREEN), ('warn', AMBER), ('err', RED)):
            self.logbox.tag_configure(tag, foreground=col)

    # ---------- plumbing ----------
    def log(self, msg):
        self.q.put(msg)

    def _drain(self):
        try:
            while True:
                m = self.q.get_nowait()
                if callable(m):
                    m(); continue
                tag = ('err' if m.startswith(('ERROR', 'NOT WRITTEN')) else
                       'ok' if m.startswith(('DONE', 'Copied', 'Saved')) else
                       'warn' if ('NOT pre-learned' in m or 'by hand' in m or 'NOTE ' in m) else None)
                self.logbox.insert('end', m + '\n', tag); self.logbox.see('end')
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def _poll_devices(self):
        def scan():                                       # drive queries off the UI thread
            mpc = paths.mpc_drives()
            sd = [r for r in paths.removable_drives() if r not in mpc.values()]
            self.q.put(lambda: self._show_devices(mpc, sd))
        threading.Thread(target=scan, daemon=True).start()
        self.after(3000, self._poll_devices)

    def _show_devices(self, mpc, sd):
        self.mpc, self.sd = mpc, sd
        if mpc:
            txt = '  ·  '.join(f'{k.split()[1].upper()} {v[:2]}' for k, v in sorted(mpc.items()))
            self.mpc_pill.configure(text=f'MPC  ●  {txt}', style='PillOn.TLabel')
        else:
            self.mpc_pill.configure(text='MPC  ○  not connected', style='Pill.TLabel')
        self.sd_pill.configure(text=('SD  ●  ' + ' '.join(r[:2] for r in sd)) if sd else 'SD  ○',
                               style='PillOn.TLabel' if sd else 'Pill.TLabel')

    # ---------- project ----------
    def browse(self):
        start = paths.mpc_projects_dir() or os.path.join(paths.data_dir(), 'Reports')
        p = filedialog.askopenfilename(initialdir=start, filetypes=[('MPC project', '*.xpj')])
        if p:
            self.path.set(os.path.normpath(p)); self.outname.set(''); self.load()

    def load(self):
        p = self.path.get().strip().strip('"')
        if not os.path.isfile(p):
            messagebox.showerror('Hapax Mapper', f'Not a file:\n{p}'); return
        try:
            self.analysis = mm.analyze(p, self.overrides)
        except Exception as e:
            messagebox.showerror('Hapax Mapper', f'Could not read the project:\n{e}'); return
        for t in self.analysis['tracks']:
            if t['plugin'] and t['plugin'] not in self.selections:
                self.selections[t['plugin']] = [dict(r) for r in t['selection']]
        if not self.outname.get():
            self.outname.set(os.path.splitext(os.path.basename(p))[0] + ' HAPAX')
        n = len(self.analysis['tracks'])
        self.track_info.configure(text=f'{os.path.splitext(os.path.basename(p))[0]}   ·   {n} track{"s" if n != 1 else ""}')
        self.fill_tracks()
        self.log(f'Opened {p}')

    def track_status(self, t):
        if not t['plugin']:
            return 'vol · pan'
        n = len(self.selections.get(t['plugin'], []))
        return f'{n} params  ' + ('✓ learned' if t['trusted'] else '✎ by hand')

    def fill_tracks(self):
        sel = self.tracks.selection()
        self.tracks.delete(*self.tracks.get_children())
        for k, t in enumerate(self.analysis['tracks']):
            tags = (('odd',) if k % 2 else ()) + (('hand',) if t['plugin'] and not t['trusted'] else ())
            self.tracks.insert('', 'end', iid=str(t['n']), tags=tags,
                               values=(t['n'], t['channel'] or '—', t['track'], t['plugin'] or t['type'], self.track_status(t)))
        if sel and self.tracks.exists(sel[0]):
            self.tracks.selection_set(sel[0])

    def cur_track(self):
        s = self.tracks.selection()
        return next((t for t in self.analysis['tracks'] if str(t['n']) == s[0]), None) if s and self.analysis else None

    def on_track(self, _=None):
        t = self.cur_track()
        if not t:
            return
        self.ch.set(str(t['channel'] or ''))
        self.cur_plugin = t['plugin']
        if not t['plugin']:
            self.phead.configure(text=f'{t["track"]}   ·   CH {t["channel"]}')
            self.pnote.configure(text='Drum / keygroup track: Hapax pots 1–2 = Track Vol / Track Pan.', style='Muted.TLabel')
            self.params.delete(*self.params.get_children()); self.count.configure(text=''); return
        self.phead.configure(text=f'{t["plugin"]}   ·   CH {t["channel"]}   ·   track {t["n"]}')
        if t['trusted']:
            self.pnote.configure(text=f'Up to {hi.MAX_PARAMS} parameters. Pots 1–8 send CC 20–27, the rest get spare CCs '
                                      'for automation lanes. Double-click or Space turns a row on/off.', style='Muted.TLabel')
        else:
            self.pnote.configure(text='This plugin\'s saved settings can\'t be read reliably, so nothing is pre-learned: '
                                      'the names still go to the Hapax, and you MIDI-learn them once on the MPC.', style='Warn.TLabel')
        self.fill_params()

    # ---------- parameters ----------
    def rows(self):
        return self.selections.setdefault(self.cur_plugin, [])

    def fill_params(self, keep=None):
        t = self.cur_track()
        rows = hi.assign_ccs(self.rows())
        chosen = {r['index'] for r in rows}
        pos = {i: p for i, _, p in t['params']}
        self.params.delete(*self.params.get_children())
        for r in rows:
            self.params.insert('', 'end', iid=f'p{r["index"]}', tags=('pot',) if r.get('pot') else (),
                               values=('●', r['pot'] or '', r['cc'], r['name'], r['label'], pos.get(r['index'], '')))
        for i, n, p in t['params']:
            if i not in chosen:
                self.params.insert('', 'end', iid=f'p{i}', tags=('off',), values=('○', '', '', n, '', p))
        pots = sum(1 for r in rows if r.get('pot'))
        self.count.configure(text=f'{len(rows):>2} / {hi.MAX_PARAMS} PARAMS    {pots} / 8 POTS')
        if keep and self.params.exists(keep):
            self.params.selection_set(keep); self.params.see(keep)
        for tr in self.analysis['tracks']:
            if self.tracks.exists(str(tr['n'])):
                self.tracks.set(str(tr['n']), 'status', self.track_status(tr))

    def cur_param(self):
        s = self.params.selection()
        return int(s[0][1:]) if s else None

    def on_param(self, _=None):
        i = self.cur_param()
        if i is None or not self.cur_plugin:
            self.pot.set('—'); self.lbl.set(''); return
        r = next((x for x in self.rows() if x['index'] == i), None)
        self.pot.set(str(r['pot']) if r and r.get('pot') else '—')
        t = self.cur_track()
        self.lbl.set(r['label'] if r else hi.hapax_label(next((n for x, n, _ in t['params'] if x == i), '')))

    def toggle(self):
        i = self.cur_param()
        if i is None or not self.cur_plugin:
            return
        rows = self.rows()
        r = next((x for x in rows if x['index'] == i), None)
        if r:
            rows.remove(r)
        else:
            if len(rows) >= hi.MAX_PARAMS:
                messagebox.showinfo('Hapax Mapper', f'Already {hi.MAX_PARAMS} parameters - turn one off first.'); return
            name = next(n for x, n, _ in self.cur_track()['params'] if x == i)
            rows.append({'index': i, 'name': name, 'label': hi.hapax_label(name), 'pot': None})
        self.fill_params(keep=f'p{i}')

    def set_pot(self):
        i = self.cur_param()
        if i is None or not self.cur_plugin:
            return
        rows = self.rows()
        r = next((x for x in rows if x['index'] == i), None)
        if r is None:
            self.toggle(); r = next((x for x in rows if x['index'] == i), None)
            if r is None:
                return
        p = None if self.pot.get() == '—' else int(self.pot.get())
        if p:
            for x in rows:
                if x.get('pot') == p:
                    x['pot'] = None
        r['pot'] = p
        self.fill_params(keep=f'p{i}')

    def rename(self):
        i = self.cur_param()
        r = next((x for x in self.rows() if x['index'] == i), None) if i is not None and self.cur_plugin else None
        if r and hi.hapax_label(self.lbl.get()) != r['label']:
            r['label'] = hi.hapax_label(self.lbl.get()); self.fill_params(keep=f'p{i}')

    def move(self, d):
        i = self.cur_param(); rows = self.rows()
        k = next((n for n, x in enumerate(rows) if x['index'] == i), None)
        if k is None or not (0 <= k + d < len(rows)):
            return
        rows[k], rows[k + d] = rows[k + d], rows[k]
        self.fill_params(keep=f'p{i}')

    def reset(self):
        t = self.cur_track()
        if t and t['plugin']:
            self.selections[t['plugin']] = hi.default_selection(t['kind'], t['plugin'], t['params'])
            self.fill_params()

    def _ch_later(self):                                  # spinbox arrows: apply once the clicking stops
        if self._ch_job:
            self.after_cancel(self._ch_job)
        self._ch_job = self.after(450, self.set_channel)

    def set_channel(self):
        self._ch_job = None
        t = self.cur_track()
        if not t:
            return
        try:
            c = int(self.ch.get()); assert 1 <= c <= 16
        except (ValueError, AssertionError):
            messagebox.showerror('Hapax Mapper', 'Channel must be 1-16'); return
        if c == t['channel']:
            return
        self.overrides[t['n']] = c
        keep = str(t['n'])
        self.analysis = mm.analyze(self.analysis['path'], self.overrides)
        self.fill_tracks(); self.tracks.selection_set(keep)

    # ---------- actions ----------
    def save_choices(self, quiet=False):
        maps = hi.load_maps()
        for plug, rows in self.selections.items():
            maps[plug] = {'params': [{'index': r['index'], 'label': r['label'], 'pot': r.get('pot')} for r in rows]}
        hi.save_maps(maps)
        if not quiet:
            self.log(f'Saved parameter choices for {len(self.selections)} plugins → {hi.MAPS_FILE}')

    def do_map(self):
        if not self.analysis:
            return
        name = hi.hapax_label(self.outname.get()) if self.outname.get().strip() else None
        if not messagebox.askyesno('Hapax Mapper', f'Write a NEW project "{name}" next to\n{self.analysis["path"]}\n\n'
                                   'Your original project is not changed. Continue?'):
            return
        self.save_choices(quiet=True)
        self.mapbtn.state(['disabled'])
        sels = {p: [dict(r) for r in rows] for p, rows in self.selections.items()}

        def work():
            try:
                res = mm.map_project(self.analysis['path'], name, self.overrides, selections=sels, log=self.log)
                self.last_defs = res['defs']
                self.log(f'DONE  load "{res["name"]}" on the MPC  ·  {len(res["defs"])} Hapax files ready → Copy to SD card')
            except FileExistsError as e:
                self.log(f'NOT WRITTEN: {e}')
            except Exception:
                self.log('ERROR\n' + traceback.format_exc())
            finally:
                self.q.put(lambda: self.mapbtn.state(['!disabled']))
        threading.Thread(target=work, daemon=True).start()

    def copy_sd(self):
        if not self.last_defs:
            messagebox.showinfo('Hapax Mapper', 'Map a project first - this copies that project\'s Hapax files.'); return
        d = filedialog.askdirectory(initialdir=self.sd[0] if self.sd else os.path.expanduser('~'),
                                    title='Choose the Hapax SD card (its root or its HAPAX folder)')
        if not d:
            return
        dest = d if os.path.basename(os.path.normpath(d)).upper() == 'HAPAX' else os.path.join(d, 'HAPAX')
        exist = [f for f in self.last_defs if os.path.exists(os.path.join(dest, os.path.basename(f)))]
        msg = f'Copy {len(self.last_defs)} files to\n{dest}?'
        if exist:
            msg += f'\n\n{len(exist)} files with the same names are already there and will be replaced.'
        if not messagebox.askyesno('Hapax Mapper', msg):
            return
        os.makedirs(dest, exist_ok=True)
        for f in self.last_defs:
            shutil.copyfile(f, os.path.join(dest, os.path.basename(f)))
        self.log(f'Copied {len(self.last_defs)} Hapax files → {dest}. Eject the card, put it in the Hapax, load the definitions.')

if __name__ == '__main__':
    _dpi_aware()
    app = App(sys.argv[1] if len(sys.argv) > 1 else None)
    if len(sys.argv) > 2 and sys.argv[2].isdigit():          # optional: preselect a track number
        app.after(1200, lambda: (app.tracks.selection_set(sys.argv[2]), app.on_track()))
    app.mainloop()

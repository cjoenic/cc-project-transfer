"""Run with: py -3 app.py"""
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from transfer import (APP_NAMES, discover_roots, export_project, export_projects_to_folder,
                      import_project, inspect_package, list_projects, scan_project,
                      transfer_between_apps)
from ftp_transfer import FTPSettings
from ftp_ui import FTPWindow, FTPImportPanel

APP_TITLE = 'CC Project Transfer v2.0'


def show_startup_splash():
    """Show the bundled artwork for two seconds before opening the main window."""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    image_path = base / 'splash-v2.png'
    if not image_path.is_file():
        return
    splash = tk.Tk()
    splash.overrideredirect(True)
    image = tk.PhotoImage(master=splash, file=str(image_path))
    max_width = max(1, min(960, splash.winfo_screenwidth() - 80))
    scale = max(1, (image.width() + max_width - 1) // max_width)
    if scale > 1:
        image = image.subsample(scale, scale)
    width, height = image.width(), image.height()
    x = (splash.winfo_screenwidth() - width) // 2
    y = (splash.winfo_screenheight() - height) // 2
    splash.geometry(f'{width}x{height}+{x}+{y}')
    tk.Label(splash, image=image, borderwidth=0).pack()
    splash.image = image
    splash.after(2000, splash.destroy)
    splash.mainloop()


def size_text(size):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024:
            return f'{size:.1f} {unit}'
        size /= 1024


def export_filename(project_name):
    """Keep display names readable while producing a valid Windows filename."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(project_name)).strip(' .')
    if name.lower().endswith('.zip'):
        name = name[:-4].rstrip(' .')
    name = name[:150].rstrip(' .') or 'CapCut-project'
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL'} | {
        f'{prefix}{number}' for prefix in ('COM', 'LPT') for number in range(1, 10)
    }:
        name = '_' + name
    return name + '.zip'


def apply_theme(root):
    root.configure(background='#f3f5f7')
    root.option_add('*Font', '{Segoe UI} 9')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Segoe UI', 9), background='#f3f5f7', foreground='#182c38')
    style.configure('TFrame', background='#f3f5f7')
    style.configure('Card.TFrame', background='#ffffff')
    style.configure('TLabel', background='#f3f5f7')
    style.configure('Card.TLabel', background='#ffffff')
    style.configure('Muted.TLabel', foreground='#637583')
    style.configure('Hint.TLabel', background='#ffffff', foreground='#637583', font=('Segoe UI', 9))
    style.configure('Title.TLabel', font=('Segoe UI', 18, 'bold'))
    style.configure('Section.TLabel', background='#ffffff', font=('Segoe UI', 11, 'bold'))
    style.configure('Eyebrow.TLabel', foreground='#087f77', font=('Segoe UI', 9, 'bold'))
    style.configure('Badge.TLabel', background='#e0f2ed', foreground='#11695f', padding=(10, 5), font=('Segoe UI', 9, 'bold'))
    style.configure('TButton', background='#e9eef2', foreground='#203744', borderwidth=0,
                    padding=(10, 6), font=('Segoe UI', 9, 'bold'), focusthickness=2, focuscolor='#8cbdb7')
    style.map('TButton', background=[('disabled', '#eef1f4'), ('pressed', '#cddbe3'), ('active', '#dbe5eb')],
              foreground=[('disabled', '#95a1ab')])
    style.configure('Primary.TButton', background='#087f77', foreground='#ffffff', padding=(12, 8))
    style.map('Primary.TButton', background=[('disabled', '#d6e6e3'), ('pressed', '#055f59'), ('active', '#096d67')],
              foreground=[('disabled', '#738f8b'), ('!disabled', '#ffffff')])
    style.configure('TEntry', fieldbackground='#f8fafb', bordercolor='#d8e1e7', lightcolor='#d8e1e7',
                    darkcolor='#d8e1e7', padding=6)
    style.map('TEntry', bordercolor=[('focus', '#087f77')])
    # Image-backed indicators preserve ttk's native mouse, keyboard and variable behavior.
    def switch_image(selected, disabled=False):
        width, height = 46, 26
        image = tk.PhotoImage(master=root, width=width, height=height)
        track = '#b8ceca' if disabled and selected else '#dde3e8' if disabled else '#087f77' if selected else '#8999a6'
        knob = '#f2f5f7' if disabled else '#ffffff'
        def rgb(color):
            return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        colors = [rgb('#ffffff'), rgb(track), rgb(knob)]
        rows = []
        for y in range(height):
            row = []
            for x in range(width):
                samples = []
                for sy in range(3):
                    for sx in range(3):
                        px, py = x + (sx + .5) / 3, y + (sy + .5) / 3
                        center = min(33, max(13, px))
                        color = 1 if (px - center) ** 2 + (py - 13) ** 2 <= 12 ** 2 else 0
                        if (px - (33 if selected else 13)) ** 2 + (py - 13) ** 2 <= 9 ** 2:
                            color = 2
                        samples.append(colors[color])
                row.append('#' + ''.join(f'{round(sum(c[i] for c in samples) / 9):02x}' for i in range(3)))
            rows.append('{' + ' '.join(row) + '}')
        image.put(' '.join(rows))
        return image
    root.switch_images = [switch_image(False), switch_image(True), switch_image(False, True), switch_image(True, True)]
    off, on, disabled_off, disabled_on = root.switch_images
    style.element_create('Switch.indicator', 'image', off,
                         ('disabled', 'selected', disabled_on), ('disabled', disabled_off),
                         ('selected', on), sticky='w')
    style.layout('Switch.TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
        ('Switch.indicator', {'side': 'left', 'sticky': 'w'}),
        ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [
            ('Checkbutton.label', {'sticky': 'nswe'})]})]})])
    style.configure('Switch.TCheckbutton', background='#ffffff', padding=(0, 4),
                    focuscolor='#087f77', focusthickness=1)
    style.map('Switch.TCheckbutton', background=[('active', '#ffffff')],
              foreground=[('disabled', '#95a1ab')])
    style.configure('Treeview', background='#ffffff', fieldbackground='#ffffff', rowheight=32,
                    borderwidth=0, font=('Segoe UI', 9))
    style.configure('Local.Treeview', background='#ffffff', fieldbackground='#ffffff',
                    rowheight=38, borderwidth=0, font=('Segoe UI Symbol', 12))
    style.map('Local.Treeview', background=[('selected', '#dff3ee')],
              foreground=[('selected', '#075f57')])
    style.configure('Treeview.Heading', background='#f3f6f8', foreground='#637583',
                    font=('Segoe UI', 9, 'bold'), padding=(8, 7), relief='flat')
    style.map('Treeview', background=[('selected', '#dff3ee')], foreground=[('selected', '#075f57')])
    style.configure('Horizontal.TProgressbar', troughcolor='#e6ecef', background='#087f77',
                    borderwidth=0, lightcolor='#087f77', darkcolor='#087f77', thickness=4)


class ScrollPanel(ttk.Frame):
    """Scrollable settings with wheel and keyboard-focus support."""
    def __init__(self, parent):
        super().__init__(parent, style='Card.TFrame')
        self.canvas = tk.Canvas(self, background='#ffffff', highlightthickness=0, width=370, height=1)
        scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content = ttk.Frame(self.canvas, style='Card.TFrame', padding=(12, 10))
        self.content_id = self.canvas.create_window(0, 0, anchor='nw', window=self.content)
        self.content.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(self.content_id, width=event.width))
        self.bind_all('<MouseWheel>', self.on_wheel, add='+')
        self.bind_all('<FocusIn>', self.on_focus, add='+')

    def contains(self, widget):
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, 'master', None)
        return False

    def on_wheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        if self.contains(widget) and not isinstance(widget, tk.Text):
            self.canvas.yview_scroll(-int(event.delta / 120), 'units')
            return 'break'

    def on_focus(self, event):
        if not self.contains(event.widget):
            return
        self.update_idletasks()
        top = event.widget.winfo_rooty() - self.content.winfo_rooty()
        bottom = top + event.widget.winfo_height()
        visible_top = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        total = max(1, self.content.winfo_height())
        if top < visible_top:
            self.canvas.yview_moveto(max(0, top - 8) / total)
        elif bottom > visible_top + height:
            self.canvas.yview_moveto((bottom - height + 8) / total)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        width = min(960, self.winfo_screenwidth() - 80)
        height = min(620, self.winfo_screenheight() - 100)
        self.geometry(f'{width}x{height}+20+20')
        self.minsize(min(860, width), min(480, height))
        apply_theme(self)
        self.events = queue.Queue()
        self.busy = False
        self.external_busy = False
        self.projects = []
        self.checked_projects = set()
        self.scan = None
        self.scan_cache = {}
        self.config_file = ((Path(sys.executable).resolve().parent / 'CapCutProjectTransfer.settings.json')
                            if getattr(sys, 'frozen', False) else
                            Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CapCutProjectTransfer/settings.json')
        config = {}
        self.ftp_settings = FTPSettings()
        self.ftp_setup_prompted = False
        try:
            config = json.loads(self.config_file.read_text())
            if not isinstance(config, dict):
                config = {}
            self.ftp_setup_prompted = bool(config.get('ftp_setup_prompted', False))
            if self.ftp_setup_prompted:
                ftp_config = config.get('ftp', {})
                self.ftp_settings = FTPSettings(**{k: v for k, v in ftp_config.items()
                                                  if k in ('host', 'port', 'username', 'password', 'folder', 'ftps')})
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.drafts_roots = config.get('drafts_roots', {})
        if not isinstance(self.drafts_roots, dict):
            self.drafts_roots = {}
        if config.get('drafts_root') and not self.drafts_roots.get('capcut'):
            self.drafts_roots['capcut'] = config['drafts_root']
        active = config.get('active_app', 'capcut')
        if active not in APP_NAMES:
            active = 'capcut'
        self.active_app = tk.StringVar(value=active)
        self.editor_choice = tk.StringVar(value=APP_NAMES[active])
        candidates = discover_roots(self.drafts_roots.get(active), active)
        self.folder = tk.StringVar(value=str(candidates[0]) if candidates else '')
        self.include_media = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value=f'Choose your {APP_NAMES[active]} drafts folder to get started.')
        self.summary = tk.StringVar(value='Select a project to inspect its source media.')
        self.project_count = tk.StringVar(value='0 projects')
        self.package_name = tk.StringVar(value='Select a project')
        main = ttk.Frame(self, padding=12)
        main.pack(fill='both', expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        header = ttk.Frame(main)
        header.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        brand = ttk.Frame(header)
        brand.pack(side='left')
        
        ttk.Label(brand, text=APP_TITLE, style='Title.TLabel').pack(anchor='w', pady=(0, 2))
        ttk.Label(brand, text='Pack, share and restore CapCut and Jianying projects.', style='Muted.TLabel').pack(anchor='w')
        self.import_button = ttk.Button(header, text='Import package…', command=self.restore)
        self.import_button.pack(side='right', anchor='center')
        self.ftp_button = ttk.Button(header, text='FTP settings…', command=self.open_ftp)
        self.ftp_button.pack(side='right', padx=8)
        location = ttk.Frame(main, style='Card.TFrame', padding=12)
        location.grid(row=1, column=0, sticky='ew', pady=(0, 12))
        editor_line = ttk.Frame(location, style='Card.TFrame')
        editor_line.pack(fill='x', pady=(0, 7))
        ttk.Label(editor_line, text='Local editor:', style='Card.TLabel').pack(side='left', padx=(0, 8))
        self.editor_picker = ttk.Combobox(editor_line, textvariable=self.editor_choice,
                                          values=tuple(APP_NAMES.values()), state='readonly', width=12)
        self.editor_picker.pack(side='left')
        self.editor_picker.bind('<<ComboboxSelected>>', self.change_editor)
        line = ttk.Frame(location, style='Card.TFrame')
        line.pack(fill='x')
        self.folder_entry = ttk.Entry(line, textvariable=self.folder)
        self.folder_entry.pack(side='left', fill='x', expand=True)
        self.browse = ttk.Button(line, text='Browse…', command=self.choose_folder)
        self.browse.pack(side='left', padx=8)
        self.refresh_button = ttk.Button(line, text='Refresh', command=self.refresh)
        self.refresh_button.pack(side='left')
        body = ttk.Frame(main)
        body.grid(row=2, column=0, sticky='nsew')
        body.columnconfigure(0, weight=1, minsize=0)
        body.columnconfigure(1, weight=0, minsize=350)
        body.rowconfigure(0, weight=1, minsize=0)
        body.grid_propagate(False)
        self.library_tabs = ttk.Notebook(body)
        self.library_tabs.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        library = ttk.Frame(self.library_tabs, style='Card.TFrame', padding=10)
        self.library_tabs.add(library, text='Local projects')
        library_header = ttk.Frame(library, style='Card.TFrame')
        library_header.pack(fill='x', pady=(0, 8))
        ttk.Label(library_header, text='Your projects', style='Section.TLabel').pack(side='left')
        ttk.Label(library_header, textvariable=self.project_count, style='Badge.TLabel').pack(side='right')
        self.ftp_import_panel = FTPImportPanel(self.library_tabs, self)
        self.library_tabs.add(self.ftp_import_panel, text='Import from FTP')
        local_actions = ttk.Frame(library, style='Card.TFrame')
        local_actions.pack(side='bottom', fill='x', pady=(8, 0))
        self.delete_button = ttk.Button(local_actions, text='Move project to Recycle Bin…', command=self.delete_project)
        self.delete_button.pack(side='left')
        self.cross_button = ttk.Button(local_actions, text='Copy to Jianying…', command=self.cross_transfer)
        self.cross_button.pack(side='right')
        listing = ttk.Frame(library, style='Card.TFrame')
        listing.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(listing, columns=('selected', 'name', 'size', 'date'),
                                 show='headings', height=6, selectmode='extended', style='Local.Treeview')
        self.tree.tag_configure('checked', background='#dff3ee', foreground='#075f57')
        self.tree.heading('selected', text='Export')
        self.tree.heading('name', text='Project')
        self.tree.heading('size', text='Size')
        self.tree.heading('date', text='Last modified')
        self.tree.column('selected', width=68, minwidth=68, stretch=False, anchor='center')
        self.tree.column('name', width=190, minwidth=120)
        self.tree.column('size', width=80, minwidth=70, stretch=False)
        self.tree.column('date', width=125, minwidth=110, stretch=False)
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(listing, orient='vertical', command=self.tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.empty_label = ttk.Label(self.tree, text='Your projects will appear here.\nChoose your editor drafts folder above.',
                                     style='Hint.TLabel', justify='center')
        self.empty_label.place(relx=.5, rely=.45, anchor='center')
        self.tree.bind('<<TreeviewSelect>>', self.select_project)
        self.tree.bind('<Button-1>', self.click_project_checkbox)
        ttk.Label(library, text='Tick projects to export several at once. Click a project name to inspect it.', style='Hint.TLabel').pack(anchor='w', pady=(8, 0))
        export_panel = ttk.Frame(body, style='Card.TFrame')
        export_panel.grid(row=0, column=1, sticky='nsew')
        export_panel.pack_propagate(False)
        export_panel.configure(width=350)
        actions = ttk.Frame(export_panel, style='Card.TFrame', padding=(12, 6, 12, 10))
        actions.pack(side='bottom', fill='x')
        self.settings_panel = ScrollPanel(export_panel)
        self.settings_panel.pack(fill='both', expand=True)
        options = self.settings_panel.content
        ttk.Label(options, text='Prepare your package', style='Section.TLabel').pack(anchor='w')
        ttk.Label(options, text='EXPORT FILENAME', style='Hint.TLabel').pack(anchor='w', pady=(10, 3))
        tk.Label(options, textvariable=self.package_name, background='#ffffff', foreground='#182c38',
                  anchor='w', justify='left', font=('Segoe UI', 10, 'bold'), wraplength=295, height=2).pack(anchor='w', pady=(0, 6))
        self.check = ttk.Checkbutton(options, text='  Include source media files', style='Switch.TCheckbutton',
                                     variable=self.include_media, command=self.update_summary)
        self.check.pack(anchor='w')
        ttk.Label(options, text='Turn off to send media separately.', wraplength=295, style='Hint.TLabel').pack(anchor='w', pady=(1, 6))
        tk.Label(options, textvariable=self.summary, background='#ffffff', foreground='#637583',
                 font=('Segoe UI', 9), anchor='nw', justify='left', wraplength=295, height=4).pack(anchor='w', pady=(0, 6))
        self.media_button = ttk.Button(options, text='View media checklist', command=self.show_media)
        self.media_button.pack(anchor='w', pady=(0, 8))
        ttk.Label(options, text='Handoff notes', style='Card.TLabel').pack(anchor='w')
        notes_border = tk.Frame(options, background='#d8e1e7', padx=1, pady=1)
        notes_border.pack(fill='x', pady=(4, 6))
        self.notes = tk.Text(notes_border, height=2, width=28, font=('Segoe UI', 9),
                             relief='flat', borderwidth=0, background='#f8fafb', foreground='#203744',
                             insertbackground='#087f77', padx=8, pady=6, wrap='word')
        self.notes.pack(fill='both', expand=True)
        ttk.Label(actions, text='Recommended: save work and close the editor first.',
                  style='Hint.TLabel').pack(anchor='w')
        export_actions = ttk.Frame(actions, style='Card.TFrame')
        export_actions.pack(fill='x', pady=(6, 0))
        self.export_button = ttk.Button(export_actions, text='Export ZIP…', command=self.export)
        self.export_button.pack(side='left')
        self.ftp_export_button = ttk.Button(export_actions, text='Export to FTP  →', style='Primary.TButton', command=self.export_ftp)
        self.ftp_export_button.pack(side='right', fill='x', expand=True, padx=(8, 0))
        def switch_library_view(event=None):
            importing = self.library_tabs.select() == str(self.ftp_import_panel)
            self.library_tabs.grid_configure(columnspan=2 if importing else 1,
                                              padx=(0, 0) if importing else (0, 10))
            if importing:
                export_panel.grid_remove()
            else:
                export_panel.grid()
        self.library_tabs.bind('<<NotebookTabChanged>>', switch_library_view)
        self.bar = ttk.Progressbar(main, mode='indeterminate')
        self.bar.grid(row=3, column=0, sticky='ew', pady=(10, 0))
        footer = ttk.Frame(main)
        footer.grid(row=4, column=0, sticky='ew', pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        status_label = ttk.Label(footer, textvariable=self.status, style='Muted.TLabel', wraplength=750)
        status_label.grid(row=0, column=0, sticky='w')
        footer.bind('<Configure>', lambda event: status_label.configure(wraplength=max(200, event.width - 300)))
        self.credit = ttk.Label(footer, text=f'{APP_TITLE} - made by charles', style='Muted.TLabel', font=('Segoe UI', 8))
        self.credit.grid(row=0, column=1, sticky='se', padx=(16, 0))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)
        if self.folder.get():
            self.refresh()
        if not self.ftp_setup_prompted and '--smoke-test' not in sys.argv:
            self.after(250, self.prompt_ftp_setup)

    def prompt_ftp_setup(self):
        if self.ftp_setup_prompted:
            return
        self.ftp_setup_prompted = True
        try:
            self.save_settings()
        except OSError:
            pass
        if messagebox.askyesno('Set up FTP',
                'Would you like to set up an FTP server now?\n\n'
                'Choose No to skip. You can open FTP settings later.', parent=self):
            self.open_ftp()

    def choose_folder(self):
        folder = filedialog.askdirectory(title=f'Select {APP_NAMES[self.active_app.get()]} drafts folder (containing project folders)')
        if folder:
            self.folder.set(folder)
            self.refresh()

    def change_editor(self, event=None):
        target = next((key for key, name in APP_NAMES.items() if name == self.editor_choice.get()), None)
        if target is None or target == self.active_app.get() or self.busy or self.external_busy:
            return
        self.drafts_roots[self.active_app.get()] = self.folder.get()
        self.active_app.set(target)
        candidates = discover_roots(self.drafts_roots.get(target), target)
        self.folder.set(str(candidates[0]) if candidates else '')
        self.cross_button.configure(text=f'Copy to {APP_NAMES[self.other_editor()]}…')
        self.refresh()

    def other_editor(self):
        return 'jianying' if self.active_app.get() == 'capcut' else 'capcut'

    def save_settings(self):
        self.drafts_roots[self.active_app.get()] = self.folder.get()
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps({'drafts_root': self.drafts_roots.get('capcut', ''),
                                               'drafts_roots': self.drafts_roots,
                                               'active_app': self.active_app.get(),
                                               'ftp': self.ftp_settings.to_config(),
                                               'ftp_setup_prompted': self.ftp_setup_prompted}))

    def open_ftp(self, upload=None):
        if not self.busy and not self.external_busy:
            FTPWindow(self, upload)

    def export_ftp(self):
        items = self.selected_projects()
        if not items:
            messagebox.showinfo('Select projects', 'Select one or more projects to export to FTP.')
            return
        if not self.ftp_settings.configured():
            messagebox.showinfo('Set up FTP', 'Enter and save your FTP server details first.')
            self.open_ftp()
            return
        if self.ready():
            projects = [{**item, 'filename': export_filename(item['name']),
                         'source_app': self.active_app.get(),
                         'include_media': self.include_media.get(),
                         'notes': self.notes.get('1.0', 'end').strip()} for item in items]
            FTPWindow(self, mode='export', project=projects)

    def import_ftp(self):
        self.library_tabs.select(self.ftp_import_panel)

    def refresh(self):
        if self.busy or self.external_busy:
            return
        try:
            self.projects = list_projects(self.folder.get()) if self.folder.get() else []
            self.checked_projects.clear()
            self.tree.delete(*self.tree.get_children())
            self.scan = None
            self.scan_cache.clear()
            self.project_count.set(f'{len(self.projects)} projects')
            self.package_name.set('Select a project')
            if self.projects:
                self.empty_label.place_forget()
            else:
                self.empty_label.place(relx=.5, rely=.45, anchor='center')
            for i, item in enumerate(self.projects):
                self.tree.insert('', 'end', iid=str(i), values=('☐', item['name'], size_text(item['size']),
                                 datetime.fromtimestamp(item['modified']).strftime('%Y-%m-%d %H:%M')))
            settings_error = None
            try:
                self.save_settings()
            except OSError:
                settings_error = ' Settings could not be saved; place the app in a writable folder.'
            self.status.set(f'{len(self.projects)} {APP_NAMES[self.active_app.get()]} project(s) found. Editor compatibility needs verification.')
            if settings_error:
                self.status.set(self.status.get() + settings_error)
            self.update_summary()
        except Exception as error:
            messagebox.showerror('Could not read drafts folder', str(error))

    def selected(self):
        selected = self.selected_projects()
        return selected[0] if len(selected) == 1 else None

    def selected_projects(self):
        if self.checked_projects:
            return [self.projects[index] for index in sorted(self.checked_projects)]
        return [self.projects[int(item)] for item in self.tree.selection()]

    def click_project_checkbox(self, event):
        if self.busy or self.external_busy or self.tree.identify_column(event.x) != '#1':
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            return 'break'
        index = int(row)
        if index in self.checked_projects:
            self.checked_projects.remove(index)
            mark = '☐'
        else:
            self.checked_projects.add(index)
            mark = '☑'
        self.tree.set(row, 'selected', mark)
        self.tree.item(row, tags=('checked',) if index in self.checked_projects else ())
        self.scan = None
        checked = [self.projects[item] for item in sorted(self.checked_projects)]
        if checked:
            if len(checked) == 1:
                filename = export_filename(checked[0]['name'])
                self.package_name.set(filename if len(filename) <= 65 else filename[:58] + '….zip')
            else:
                self.package_name.set(f'{len(checked)} separate ZIP packages')
            self.update_checked_summary()
        else:
            self.package_name.set('Select a project')
            self.update_summary()
        return 'break'

    def update_checked_summary(self):
        checked = [self.projects[item] for item in sorted(self.checked_projects)]
        if not checked:
            return
        if not self.include_media.get():
            total = sum(item['size'] for item in checked)
            self.summary.set(f'{len(checked)} project(s) selected for export · '
                             f'{size_text(total)} total draft-folder size.\nSource media will be transferred separately.')
            self.status.set('Tick more projects to add them to this export batch.')
            return
        missing_scans = [item for item in checked if Path(item['path']).resolve() not in self.scan_cache]
        if missing_scans:
            self.summary.set(f'Calculating draft and source-media size for {len(checked)} project(s)…')
            if not self.busy:
                self.run(lambda: [scan_project(item['path']) for item in missing_scans], self.checked_scanned)
            return
        scans = [self.scan_cache[Path(item['path']).resolve()] for item in checked]
        total = sum(scan['project_size'] + sum(media['size'] or 0 for media in scan['media']
                                              if not media['internal']) for scan in scans)
        missing = sum(not media['exists'] for scan in scans for media in scan['media'])
        suffix = f' · {missing} missing media reference(s)' if missing else ''
        self.summary.set(f'{len(checked)} project(s) selected for export · '
                         f'{size_text(total)} including recognized source media{suffix}.')
        self.status.set('Selected export size includes draft folders and recognized external media.')

    def checked_scanned(self, results):
        for result in results:
            self.scan_cache[Path(result['project']).resolve()] = result
        self.update_checked_summary()

    def delete_project(self):
        from project_trash import recycle_project
        items = self.selected_projects()
        if len(items) != 1:
            messagebox.showinfo('Select one project', 'Select exactly one local project to move to the Recycle Bin.')
            return
        item = items[0]
        if not self.ready():
            return
        if not messagebox.askyesno('Move project to Recycle Bin',
                f"Move ‘{item['name']}’ and its project folder to the Windows Recycle Bin?\n\n"
                'Media stored outside the project folder will remain in place. You can restore the folder from the Recycle Bin.'):
            return
        root = self.folder.get()
        def recycled(result):
            self.refresh()
            self.status.set('Project moved to the Windows Recycle Bin. Restore it there if needed.')
        self.run(lambda: recycle_project(item['path'], root), recycled)

    def cross_transfer(self):
        items = self.selected_projects()
        if len(items) != 1:
            messagebox.showinfo('Select one project', 'Select exactly one project to copy to the other editor.')
            return
        if not self.ready():
            return
        source_app = self.active_app.get()
        target_app = self.other_editor()
        candidates = discover_roots(self.drafts_roots.get(target_app), target_app)
        if candidates:
            target_root = candidates[0]
        else:
            chosen = filedialog.askdirectory(title=f'Select {APP_NAMES[target_app]} drafts folder')
            if not chosen:
                return
            target_root = Path(chosen)
        if not target_root.is_dir():
            messagebox.showerror('Invalid drafts folder', 'Choose an existing destination drafts folder.')
            return
        item = items[0]
        if not messagebox.askyesno('Experimental cross-editor transfer',
                f"Copy ‘{item['name']}’ from {APP_NAMES[source_app]} to {APP_NAMES[target_app]}?\n\n"
                f'Destination: {target_root}\n\n'
                'The original draft stays untouched. The copied draft may not open or preserve every effect; '
                'test it in the destination editor after the transfer.'):
            return
        self.drafts_roots[target_app] = str(target_root)
        self.save_settings()
        def copied(result):
            folder, warnings = result
            messagebox.showinfo('Draft copied', f'Created: {folder}\n\n' + '\n\n'.join(warnings))
        self.run(lambda: transfer_between_apps(item['path'], target_root, source_app, target_app,
                                                self.progress), copied)

    def select_project(self, event=None):
        if self.busy or self.external_busy:
            return
        items = self.selected_projects()
        if self.checked_projects:
            self.scan = None
            self.package_name.set(export_filename(items[0]['name']) if len(items) == 1
                                  else f'{len(items)} separate ZIP packages')
            self.update_checked_summary()
            return
        if len(items) == 1:
            item = items[0]
            filename = export_filename(item['name'])
            self.package_name.set(filename if len(filename) <= 65 else filename[:58] + '….zip')
            self.scan = None
            self.run(lambda: scan_project(item['path']), self.scanned)
        elif items:
            self.scan = None
            self.package_name.set(f'{len(items)} separate ZIP packages')
            self.summary.set(f'{len(items)} projects selected · {size_text(sum(i["size"] for i in items))} total draft size.')
            self.status.set('Multiple projects selected. Each project will be exported as its own ZIP package.')
        else:
            self.scan = None
            self.package_name.set('Select a project')
            self.update_summary()

    def scanned(self, result):
        selected = self.selected_projects()
        if len(selected) != 1 or Path(selected[0]['path']).resolve() != Path(result['project']).resolve():
            return
        self.scan = result
        self.scan_cache[Path(result['project']).resolve()] = result
        self.update_summary()
        self.status.set('Project inspected. Media detection covers absolute paths with recognized file extensions.')

    def update_summary(self):
        if self.checked_projects:
            self.update_checked_summary()
            return
        if not self.scan:
            selected = self.selected_projects()
            if len(selected) > 1:
                self.summary.set(f'{len(selected)} projects selected · '
                                 f'{size_text(sum(item["size"] for item in selected))} total draft size.')
                return
            self.summary.set('Select a project to inspect its source media.')
            return
        scan = self.scan
        missing = sum(not m['exists'] for m in scan['media'])
        if self.include_media.get():
            size = scan['project_size'] + sum(m['size'] or 0 for m in scan['media'] if not m['internal'])
        else:
            from transfer import MEDIA_EXTENSIONS
            size = sum(p.stat().st_size for p in scan['files'] if p.suffix.lower() not in MEDIA_EXTENSIONS)
        text = f"{len(scan['media'])} media references · {missing} missing\n{size_text(size)} before compression."
        if not self.include_media.get():
            text += f'\nSend media separately and relink in {APP_NAMES[self.active_app.get()]}.'
        if not scan['readable_timeline'] or scan['unreadable']:
            text += '\nUnreadable draft: use project-only export.'
        self.summary.set(text)

    def ready(self):
        if self.busy or self.external_busy:
            messagebox.showinfo('Operation in progress', 'Wait for the current operation to finish.')
            return False
        return not self.busy

    def export(self):
        items = self.selected_projects()
        if not items:
            messagebox.showinfo('Select projects', 'Select one or more projects to export.')
            return
        if not self.ready():
            return
        include = self.include_media.get()
        notes = self.notes.get('1.0', 'end').strip()
        source_app = self.active_app.get()
        if len(items) == 1:
            item = items[0]
            destination = filedialog.asksaveasfilename(title='Save a new transfer package', defaultextension='.zip', filetypes=[('ZIP package', '*.zip')], initialfile=export_filename(item['name']))
            if destination:
                self.run(lambda: export_project(item['path'], destination, include, notes,
                                                self.progress, source_app=source_app),
                         lambda result: messagebox.showinfo('Package created', f'Saved to:\n{destination}'))
            return
        destination = filedialog.askdirectory(title=f'Choose a folder for {len(items)} project ZIP packages')
        if destination:
            exports = [{**item, 'source_app': source_app} for item in items]
            self.run(lambda: export_projects_to_folder(exports, destination, include, notes,
                                                       lambda item: export_filename(item['name']), self.progress),
                     lambda outputs: messagebox.showinfo('Projects exported',
                         f'{len(outputs)} ZIP packages were saved to:\n{destination}'))

    def restore(self, filename=None):
        if not self.ready():
            return
        if not self.folder.get() or not Path(self.folder.get()).is_dir():
            messagebox.showinfo('Select drafts folder', 'Choose an existing destination drafts folder first.')
            return
        filename = filename or filedialog.askopenfilename(title='Open transfer package', filetypes=[('ZIP package', '*.zip')])
        if not filename:
            return
        root = self.folder.get()
        target_app = self.active_app.get()
        def preview(manifest):
            mode = 'Source media included' if manifest['include_media'] else 'Source media transferred separately; relinking required'
            source_name = APP_NAMES[manifest.get('source_app', 'capcut')]
            destination_name = APP_NAMES[target_app]
            cross_note = '\nExperimental cross-editor transfer; editability is not verified.' if source_name != destination_name else ''
            if messagebox.askokcancel('Import package', f"{manifest['project_name']}\n{source_name} → {destination_name}\n{mode}\nUnpacked: {size_text(manifest['unpacked_size'])}\n\nNotes: {str(manifest.get('notes', ''))[:2000]}\n\nRestore into a new folder?{cross_note}"):
                self.run(lambda: import_project(filename, root, self.progress,
                                                target_app=target_app), self.restored)
        self.run(lambda: inspect_package(filename), preview)

    def restored(self, result):
        folder, warnings = result
        self.refresh()
        if warnings:
            self.status.set('Files copied with warnings. Check the draft in the destination editor.')
            messagebox.showwarning('Files copied — review warnings', f'{folder}\n\n' + '\n\n'.join(warnings))
        else:
            messagebox.showinfo('Project files restored', str(folder))

    def show_media(self):
        items = self.selected_projects()
        if not items or self.busy:
            return
        missing = [item for item in items if Path(item['path']).resolve() not in self.scan_cache]
        if missing:
            self.run(lambda: [scan_project(item['path']) for item in missing],
                     lambda results: self.media_scanned(results, items))
            return
        self.open_media_checklist(items)

    def media_scanned(self, results, items):
        for result in results:
            self.scan_cache[Path(result['project']).resolve()] = result
        self.update_summary()
        self.open_media_checklist(items)

    def open_media_checklist(self, items):
        window = tk.Toplevel(self)
        window.title('Source media checklist')
        window.geometry('850x400')
        text = tk.Text(window, wrap='word', padx=12, pady=12)
        text.pack(fill='both', expand=True)
        for index, project in enumerate(items):
            scan = self.scan_cache[Path(project['path']).resolve()]
            if index:
                text.insert('end', '\n')
            text.insert('end', f"{project['name']}\n{'─' * 48}\n")
            for media in scan['media']:
                text.insert('end', f"{'OK' if media['exists'] else 'MISSING'}  {media['original_path']}\n")
            if not scan['media']:
                text.insert('end', 'No recognized absolute media references found.\n')
        text.configure(state='disabled')

    def progress(self, message):
        self.events.put(('progress', message))

    def run(self, job, callback):
        if self.external_busy:
            return
        self.busy = True
        self.status.set('Working…')
        self.bar.start()
        for widget in (self.browse, self.refresh_button, self.export_button, self.import_button, self.media_button, self.folder_entry, self.check, self.ftp_button, self.ftp_export_button, self.delete_button, self.cross_button, self.editor_picker):
            widget.configure(state='disabled')
        self.tree.bind('<<TreeviewSelect>>', lambda event: None)
        self.tree.bind('<Button-1>', lambda event: 'break')
        self.tree.bind('<Key>', lambda event: 'break')
        def work():
            try:
                self.events.put(('done', (job(), callback)))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            # Bound processing so large archives cannot starve the UI event loop.
            for _ in range(100):
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    self.status.set(value)
                    continue
                self.busy = False
                self.bar.stop()
                for widget in (self.browse, self.refresh_button, self.export_button, self.import_button, self.media_button, self.folder_entry, self.check, self.ftp_button, self.ftp_export_button, self.delete_button, self.cross_button):
                    widget.configure(state='normal')
                self.editor_picker.configure(state='readonly')
                self.tree.unbind('<Button-1>')
                self.tree.unbind('<Key>')
                self.tree.bind('<<TreeviewSelect>>', self.select_project)
                self.tree.bind('<Button-1>', self.click_project_checkbox)
                if kind == 'error':
                    self.status.set('Operation failed. See the error details.')
                    messagebox.showerror('Transfer failed', value)
                else:
                    self.status.set('Done.')
                    result, callback = value
                    callback(result)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def close(self):
        if self.busy or self.external_busy:
            messagebox.showinfo('Transfer in progress', 'Wait for the current operation to finish before closing.')
        else:
            self.destroy()


def main():
    if '--recycle-smoke-test' in sys.argv:
        import tempfile
        from project_trash import recycle_project
        base = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent / 'build'
        with tempfile.TemporaryDirectory(prefix='recycle-check-', dir=base) as temporary:
            root = Path(temporary).resolve()
            assert root.is_relative_to(base)
            project = root / 'Disposable recycling test'
            project.mkdir()
            (project / 'draft_content.json').write_text('{}')
            recycle_project(project, root)
            assert not project.exists()
    elif '--smoke-test' in sys.argv:
        # Exercise the packaged GUI without reading or modifying real draft settings.
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            drafts = Path(temporary) / 'CapCut/User Data/Projects/com.lveditor.draft'
            source_media = Path(temporary) / 'source-video.mp4'
            source_media.write_bytes(b'm' * 23)
            for name, size in (('Smoke One', 11), ('Smoke Two', 17)):
                project = drafts / name
                project.mkdir(parents=True)
                (project / 'draft_content.json').write_text(json.dumps({'path': str(source_media)}))
                (project / 'payload.bin').write_bytes(b'x' * size)
            with patch.dict(os.environ, {'LOCALAPPDATA': temporary}), patch('sys.frozen', False, create=True):
                window = App()
                window.withdraw()
                window.update()
                assert len(window.tree.get_children()) == 2
                assert all(window.tree.set(item, 'size') for item in window.tree.get_children())
                window.tree.selection_set(window.tree.get_children())
                window.select_project()
                assert window.package_name.get() == '2 separate ZIP packages'
                window.checked_projects.update((0, 1))
                for row in ('0', '1'):
                    window.tree.set(row, 'selected', '☑')
                    window.tree.item(row, tags=('checked',))
                window.scan_cache = {Path(item['path']).resolve(): scan_project(item['path'])
                                     for item in window.projects}
                window.update_checked_summary()
                assert 'including recognized source media' in window.summary.get()
                assert window.checked_projects == {0, 1}
                assert window.tree.set('0', 'selected') == '☑'
                assert window.tree.item('0', 'tags') == ('checked',)
                window.show_media()
                checklist = next(child for child in window.winfo_children()
                                 if isinstance(child, tk.Toplevel))
                checklist_text = next(child for child in checklist.winfo_children()
                                      if isinstance(child, tk.Text)).get('1.0', 'end')
                assert 'Smoke One' in checklist_text and 'Smoke Two' in checklist_text
                assert checklist_text.count(str(source_media)) == 2
                checklist.destroy()
                window.check.invoke()
                assert not window.include_media.get()
                assert 'total draft-folder size' in window.summary.get()
                window.deiconify()
                window.update()
                window.library_tabs.select(window.ftp_import_panel)
                window.update()
                assert not window.ftp_import_panel.connected
                assert window.ftp_import_panel.files.cget('style') == 'Offline.Treeview'
                ftp_window = FTPWindow(window)
                ftp_window.update()
                row = ftp_window.files.insert('', 'end', values=('Display check.zip', '1 MB'))
                ftp_window.update()
                x, y, width, height = ftp_window.files.bbox(row)
                # A hidden/background release check may be covered by another desktop window.
                assert ftp_window.files.winfo_ismapped() and width > 0 and height > 0
                assert ftp_window.files.master.winfo_class() == 'TFrame'
                assert ftp_window.controls[2].cget('show')
                assert ftp_window.controls[3].cget('show')
                assert not ftp_window.tls.get()
                ftp_window.close()
                window.library_tabs.select(0)
                window.geometry('860x480')
                window.update()
                assert window.export_button.winfo_ismapped()
                assert window.export_button.winfo_rooty() + window.export_button.winfo_height() <= window.winfo_rooty() + window.winfo_height()
                jianying_drafts = Path(temporary) / 'JianyingPro/User Data/Projects/com.lveditor.draft'
                jianying_project = jianying_drafts / 'Jianying Smoke'
                jianying_project.mkdir(parents=True)
                (jianying_project / 'draft_content.json').write_text('{}')
                window.editor_choice.set('Jianying')
                window.change_editor()
                assert window.active_app.get() == 'jianying'
                assert window.folder.get() == str(jianying_drafts)
                assert len(window.projects) == 1
                assert window.cross_button.cget('text') == 'Copy to CapCut…'
                with patch.object(window.ftp_import_panel, 'package_selection', return_value=('row', 'draft.zip')), \
                     patch.object(window.ftp_import_panel, 'start',
                                  side_effect=lambda job, callback: job(window.ftp_settings)), \
                     patch('ftp_ui.import_from_ftp') as ftp_import:
                    window.ftp_import_panel.import_selected()
                    assert ftp_import.call_args.kwargs['target_app'] == 'jianying'
                    assert Path(ftp_import.call_args.args[2]) == jianying_drafts
                window.editor_choice.set('CapCut')
                window.change_editor()
                assert window.folder.get() == str(drafts)
                settings_file = window.config_file
                window.destroy()
                settings_file.write_text(json.dumps({'drafts_root': str(drafts),
                    'ftp': {'host': 'old-shared.example', 'port': 2121, 'folder': ''}}))
                migrated = App()
                assert not migrated.ftp_settings.configured()
                assert migrated.ftp_settings.host == ''
                with patch.object(messagebox, 'askyesno', return_value=False):
                    migrated.prompt_ftp_setup()
                assert migrated.ftp_setup_prompted
                migrated.ftp_settings = FTPSettings(host='private.example', port=2121,
                    username='user-one', password='secret-one', folder='/projects', ftps=True)
                migrated.ftp_setup_prompted = True
                migrated.save_settings()
                migrated.destroy()
                reloaded = App()
                assert reloaded.ftp_settings == FTPSettings(host='private.example', port=2121,
                    username='user-one', password='secret-one', folder='/projects', ftps=True)
                reloaded.destroy()
    else:
        show_startup_splash()
        App().mainloop()


if __name__ == '__main__':
    if '--smoke-test' in sys.argv:
        try:
            main()
        except Exception:
            import traceback
            target = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent / 'build'
            (target / 'startup-check-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
            raise SystemExit(1)
    else:
        main()

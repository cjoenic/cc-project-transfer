"""Modal FTP browser; all network work runs off the Tk event thread."""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from transfer import TransferError

from ftp_transfer import (FTPSettings, Cancelled, download_package, list_packages, upload_package,
                          export_to_ftp, import_from_ftp, rename_package, delete_package, remote_name,
                          TransferProgress, format_bytes, package_display, export_many_to_ftp)


def configure_package_columns(tree):
    for key, title, width in (('name', 'Project', 210), ('date', 'Date', 190),
                               ('uuid', 'UUID', 115), ('size', 'Size', 80)):
        tree.heading(key, text=title)
        tree.column(key, width=width, minwidth=80, stretch=key == 'name')


def package_values(item):
    name, date, identifier = package_display(item['name'], item.get('modified'))
    return name, date, identifier, format_bytes(item['size'])


class FTPWindow(tk.Toplevel):
    def __init__(self, app, upload=None, mode='settings', project=None):
        super().__init__(app)
        self.app = app
        self.upload = upload
        self.mode = mode
        self.project = project
        title = {'settings': 'FTP settings & files', 'import': 'Import from FTP', 'export': 'Export project to FTP'}[mode]
        self.title(title)
        width, height = (520, 360) if mode == 'export' else (720, 570)
        self.geometry(f'{width}x{height}+{max(0, (self.winfo_screenwidth()-width)//2)}+{max(0, (self.winfo_screenheight()-height)//2)}')
        self.minsize(480, 320) if mode == 'export' else self.minsize(660, 500)
        self.transient(app)
        self.grab_set()
        self.busy = False
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.cancelled.pause_event = threading.Event()
        self.cancelled.paused_seconds = 0
        self.controls = []
        self.variables = {}
        self.listed_settings = None
        self.package_records = {}
        self.transfer_details = tk.StringVar(value='')
        main = ttk.Frame(self, padding=16)
        main.pack(fill='both', expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)
        ttk.Label(main, text=title, style='Title.TLabel').grid(row=0, column=0, sticky='w')
        fields = ttk.Frame(main)
        fields.grid(row=1, column=0, sticky='ew', pady=10)
        fields.columnconfigure(1, weight=1)
        fields.columnconfigure(3, weight=1)
        for i, (key, title) in enumerate((('host', 'Host'), ('port', 'Port'), ('username', 'Username'), ('password', 'Password'), ('folder', 'Remote folder'))):
            row, col = divmod(i, 2)
            variable = tk.StringVar(value=str(getattr(app.ftp_settings, key)))
            self.variables[key] = variable
            ttk.Label(fields, text=title).grid(row=row, column=col * 2, sticky='w', padx=(0, 8), pady=4)
            entry = ttk.Entry(fields, textvariable=variable, show='•' if key in ('username', 'password') else '', width=20)
            entry.grid(row=row, column=col * 2 + 1, sticky='ew', padx=(0, 12), pady=4)
            self.controls.append(entry)
        self.tls = tk.BooleanVar(value=app.ftp_settings.ftps)
        toggle = ttk.Checkbutton(fields, text='Enable FTPS (explicit TLS)', variable=self.tls)
        toggle.grid(row=2, column=2, columnspan=2, sticky='w')
        self.controls.append(toggle)
        if mode != 'settings':
            fields.grid_remove()
        hint = ('Leave Remote folder blank to use the login folder. Saved credentials are stored in the local config file.' if mode == 'settings' else
                'Select a shared project and import it directly into your selected drafts folder.' if mode == 'import' else
                'Your project is packaged and uploaded automatically. No local ZIP to manage.')
        if mode != 'export':
            ttk.Label(main, text=hint, style='Muted.TLabel', wraplength=610).grid(row=2, column=0, sticky='w', pady=10)
        actions = ttk.Frame(main)
        actions.grid(row=3, column=0, sticky='ew', pady=10)
        commands = (('Save settings', self.save), ('Connect / refresh', self.refresh), ('Upload ZIP…', self.send), ('Download…', self.download))
        if mode == 'import':
            commands = (('Refresh projects', self.refresh), ('Import selected project', self.import_selected))
        elif mode == 'export':
            commands = ()
        primary_actions = ttk.Frame(actions)
        primary_actions.pack(fill='x')
        for title, callback in commands:
            button = ttk.Button(primary_actions, text=title, command=callback)
            button.pack(side='left', padx=(0, 6))
            self.controls.append(button)
        if mode != 'export':
            package_actions = ttk.Frame(actions)
            package_actions.pack(fill='x', pady=(6, 0))
            for title, callback in (('Rename package…', self.rename_selected), ('Delete package…', self.delete_selected)):
                button = ttk.Button(package_actions, text=title, command=callback)
                button.pack(side='left', padx=(0, 6))
                self.controls.append(button)
        listing = ttk.Frame(main)
        listing.grid(row=4, column=0, sticky='nsew')
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        self.files = ttk.Treeview(listing, columns=('name', 'date', 'uuid', 'size'), show='headings', selectmode='browse', height=6)
        configure_package_columns(self.files)
        listing.grid_propagate(False)
        self.files.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(listing, command=self.files.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.files.configure(yscrollcommand=scroll.set)
        if mode == 'export':
            listing.grid_remove()
            actions.grid_remove()
            self.result_icon = tk.Label(main, text='↑', font=('Segoe UI Symbol', 38),
                                        background='#f3f5f7', foreground='#087f77')
            self.result_icon.grid(row=4, column=0)
        self.status = tk.StringVar(value='Enter your FTP server details. Enable FTPS if your server requires it.')
        status_area = ttk.Frame(main)
        status_area.grid(row=5, column=0, sticky='ew', pady=8)
        status_label = ttk.Label(status_area, textvariable=self.status, wraplength=440 if mode == 'export' else 610)
        status_label.pack(anchor='w')
        details_label = ttk.Label(status_area, textvariable=self.transfer_details, wraplength=440 if mode == 'export' else 610)
        details_label.pack(anchor='w')
        status_area.bind('<Configure>', lambda event: [label.configure(wraplength=max(250, event.width)) for label in (status_label, details_label)])
        self.bar = ttk.Progressbar(main, mode='indeterminate')
        self.bar.grid(row=6, column=0, sticky='ew')
        transfer_actions = ttk.Frame(main)
        transfer_actions.grid(row=7, column=0, sticky='e', pady=(8, 0))
        self.pause_button = ttk.Button(transfer_actions, text='Pause', command=self.toggle_pause, state='disabled')
        self.pause_button.pack(side='left', padx=(0, 6))
        self.cancel_button = ttk.Button(transfer_actions, text='Cancel transfer', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.timer = self.after(100, self.poll)
        if upload:
            self.after_idle(self.send)
        elif mode == 'import':
            self.after_idle(self.refresh)
        elif mode == 'export':
            self.after_idle(self.export_direct)

    def export_direct(self):
        projects = self.project if isinstance(self.project, list) else [self.project]
        include = projects[0]['include_media']
        notes = projects[0]['notes']
        self.start(lambda s: export_many_to_ftp(s, projects, include, notes,
                                                self.progress, self.cancelled),
                   lambda names: self.status.set(f'{len(names)} project(s) uploaded successfully.'))

    def import_selected(self):
        selection = self.package_selection()
        if not selection:
            return
        _, name = selection
        root = self.app.folder.get()
        if not root or not Path(root).is_dir():
            messagebox.showinfo('Prepare to import', 'Select a valid drafts folder in the main window first.', parent=self)
            return
        def imported(result):
            if not getattr(self, 'embedded', False):
                self.close()
            self.app.restored(result)
            if getattr(self, 'embedded', False):
                self.status.set('Files copied with warnings. Check the draft in the destination editor.'
                                if result[1] else 'Project imported into your drafts folder.')
        target_app = self.app.active_app.get()
        self.start(lambda s: import_from_ftp(s, name, root, self.progress, self.cancelled,
                                             target_app=target_app), imported)

    def settings(self):
        values = {key: variable.get() for key, variable in self.variables.items()}
        values['port'] = int(values['port'])
        settings = FTPSettings(**values, ftps=self.tls.get())
        if not settings.configured():
            raise ValueError('Enter a host, port (1–65535), username and password.')
        return settings

    def save(self):
        try:
            self.app.ftp_settings = self.settings()
            self.app.ftp_setup_prompted = True
            self.app.save_settings()
            self.status.set('FTP settings saved on this computer.')
        except (ValueError, OSError) as error:
            messagebox.showerror('Settings', str(error), parent=self)

    def start(self, operation, done):
        if self.busy:
            return
        try:
            settings = self.settings()
        except ValueError as error:
            messagebox.showerror('Settings', str(error), parent=self)
            return
        self.app.ftp_settings = settings
        self.busy = True
        self.cancelled.clear()
        if hasattr(self.cancelled, 'pause_event'):
            self.cancelled.pause_event.clear()
            self.cancelled.paused_seconds = 0
            self.pause_button.configure(state='normal', text='Pause')
        self.transfer_details.set('')
        self.status.set('Connecting…')
        for control in self.controls:
            control.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.bar.configure(mode='indeterminate', value=0)
        self.bar.start()
        def work():
            try:
                result = operation(settings)
                self.events.put(('done', (result, done)))
            except Cancelled:
                self.events.put(('cancelled', None))
            except TransferError as error:
                text = str(error)
                for secret in (settings.password, settings.username):
                    if secret:
                        text = text.replace(secret, '[hidden]')
                self.events.put(('error', text))
            except Exception:
                # Server responses can echo authentication arguments. Do not surface them.
                self.events.put(('error', None))
        threading.Thread(target=work, daemon=True).start()

    def progress(self, text):
        self.events.put(('progress', text))

    def refresh(self):
        def fetch(settings):
            return settings, list_packages(settings, self.cancelled)
        def show(result):
            self.listed_settings, items = result
            self.files.delete(*self.files.get_children())
            self.package_records.clear()
            for item in items:
                row = self.files.insert('', 'end', values=package_values(item))
                self.package_records[row] = dict(item)
            children = self.files.get_children()
            if children:
                self.files.selection_set(children[0])
                self.files.focus(children[0])
                self.files.see(children[0])
            self.status.set(f'{len(items)} ZIP package(s) found.')
            if getattr(self, 'embedded', False):
                self.connected = True
        self.start(fetch, show)

    def package_selection(self):
        selected = self.files.selection()
        if not selected:
            messagebox.showinfo('Select a package', 'Select a remote ZIP package first.', parent=self)
            return None
        try:
            if self.settings() != self.listed_settings:
                raise ValueError()
        except ValueError:
            messagebox.showinfo('Refresh required', 'Refresh the list after changing connection settings.', parent=self)
            return None
        record = self.package_records.get(selected[0])
        if record is None:
            return None
        return selected[0], record['name']

    def rename_selected(self):
        selection = self.package_selection()
        if not selection:
            return
        item, old_name = selection
        name = simpledialog.askstring('Rename FTP package', 'New package name:', initialvalue=old_name, parent=self)
        if name is None:
            return
        name = name.strip()
        if not name:
            return
        if not name.lower().endswith('.zip'):
            name += '.zip'
        try:
            remote_name(name)
        except TransferError as error:
            messagebox.showerror('Invalid filename', str(error), parent=self)
            return
        def renamed(new_name):
            record = self.package_records[item]
            record['name'] = new_name
            self.files.item(item, values=package_values(record))
            self.status.set(f'Renamed to {new_name}.')
        self.start(lambda s: rename_package(s, old_name, name, self.cancelled), renamed)

    def delete_selected(self):
        selection = self.package_selection()
        if not selection:
            return
        item, name = selection
        if not messagebox.askyesno('Permanently delete FTP package',
                f'Delete this package from the FTP server?\n\n{name}\n\n'
                'This permanently removes the server ZIP. FTP has no Recycle Bin. Local projects are unaffected.',
                parent=self, default='no', icon='warning'):
            return
        def deleted(result):
            self.files.delete(item)
            self.package_records.pop(item, None)
            self.status.set(f'Package deleted. {len(self.files.get_children())} package(s) remaining.')
        self.start(lambda s: delete_package(s, name, self.cancelled), deleted)

    def send(self):
        filename = self.upload or filedialog.askopenfilename(parent=self, title='Select package to upload', filetypes=[('ZIP package', '*.zip')])
        if not filename:
            return
        self.start(lambda s: upload_package(s, filename, self.progress, self.cancelled),
                   lambda name: self.status.set(f'Uploaded as {name}'))

    def download(self):
        selection = self.package_selection()
        if not selection:
            return
        _, name = selection
        destination = filedialog.asksaveasfilename(parent=self, title='Save downloaded package', initialfile=name, defaultextension='.zip', filetypes=[('ZIP package', '*.zip')])
        if not destination:
            return
        if Path(destination).exists():
            messagebox.showinfo('Download', 'Choose a new filename; existing files are not overwritten.', parent=self)
            return
        def downloaded(path):
            self.status.set('Download verified and saved.')
            if messagebox.askyesno('Download complete', 'Import the downloaded package now?', parent=self):
                self.close()
                self.app.restore(str(path))
        self.start(lambda s: download_package(s, name, destination, self.progress, self.cancelled), downloaded)

    def cancel(self):
        self.cancelled.set()
        self.status.set('Cancelling… waiting for the current network operation (15-second socket timeout).')

    def toggle_pause(self):
        if not self.busy:
            return
        pause = self.cancelled.pause_event
        if pause.is_set():
            pause.clear()
            self.pause_button.configure(text='Pause')
            self.status.set('Resuming transfer…')
        else:
            pause.set()
            self.pause_button.configure(text='Resume')
            self.status.set('Paused. Resume to continue; long pauses may time out on the server.')

    def show_result(self, kind):
        if hasattr(self, 'result_icon'):
            symbol, color = {'done': ('✓', '#168047'), 'error': ('✕', '#ce3030'),
                             'cancelled': ('—', '#637583')}[kind]
            self.result_icon.configure(text=symbol, foreground=color)

    def poll(self):
        try:
            for _ in range(100):
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    if not self.cancelled.is_set() and not getattr(self.cancelled, 'pause_event', threading.Event()).is_set():
                        if isinstance(value, TransferProgress):
                            self.transfer_details.set(str(value))
                            self.status.set('Transferring package…')
                            if value.total is not None:
                                self.bar.stop()
                                self.bar.configure(mode='determinate', maximum=max(1, value.total), value=value.done)
                        else:
                            self.status.set(value)
                    continue
                self.busy = False
                if getattr(self, 'embedded', False):
                    self.app.external_busy = False
                self.bar.stop()
                self.cancel_button.configure(state='disabled')
                if hasattr(self, 'pause_button'):
                    self.pause_button.configure(state='disabled', text='Pause')
                    self.cancelled.pause_event.clear()
                if not getattr(self, 'embedded', False):
                    self.show_result(kind)
                for control in self.controls:
                    control.configure(state='normal')
                if kind == 'done':
                    result, done = value
                    done(result)
                    if not self.winfo_exists():
                        return
                elif kind == 'cancelled':
                    self.status.set('Cancelled. Partial local downloads were removed.')
                else:
                    self.status.set(value or 'Operation failed. Check server settings, permissions, disk space and package validity.')
                if getattr(self, 'embedded', False):
                    if kind == 'error':
                        self.connected = False
                    self.operation_finished()
        except queue.Empty:
            pass
        self.timer = self.after(100, self.poll)

    def close(self):
        if self.busy:
            self.cancel()
            return
        self.after_cancel(self.timer)
        self.grab_release()
        self.destroy()


class FTPImportPanel(ttk.Frame):
    """Inline, explicitly connected browser. Idle state keeps no network socket open."""
    embedded = True
    progress = FTPWindow.progress
    poll = FTPWindow.poll
    refresh = FTPWindow.refresh
    import_selected = FTPWindow.import_selected
    package_selection = FTPWindow.package_selection
    rename_selected = FTPWindow.rename_selected
    delete_selected = FTPWindow.delete_selected
    cancel = FTPWindow.cancel

    def __init__(self, parent, app):
        super().__init__(parent, padding=10, style='Card.TFrame')
        self.app = app
        self.busy = False
        self.connected = False
        self.disconnect_pending = False
        self.listed_settings = None
        self.package_records = {}
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.status = tk.StringVar(value='Disconnected. Click Connect to load shared projects.')
        self.transfer_details = tk.StringVar(value='')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        buttons = ttk.Frame(self, style='Card.TFrame')
        buttons.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        self.connect_button = ttk.Button(buttons, text='Connect', command=self.toggle_connection)
        self.connect_button.pack(side='left')
        self.refresh_button = ttk.Button(buttons, text='Refresh', command=self.refresh)
        self.refresh_button.pack(side='left', padx=5)
        self.import_button = ttk.Button(buttons, text='Import selected', command=self.import_selected)
        self.import_button.pack(side='left')
        management = ttk.Frame(self, style='Card.TFrame')
        management.grid(row=1, column=0, sticky='ew', pady=(0, 6))
        self.rename_button = ttk.Button(management, text='Rename…', command=self.rename_selected)
        self.rename_button.pack(side='left')
        self.delete_button = ttk.Button(management, text='Delete…', command=self.delete_selected)
        self.delete_button.pack(side='left', padx=5)
        ttk.Label(management, text='Save work and close the editor before importing.',
                  style='Hint.TLabel').pack(side='right')
        self.controls = [self.refresh_button, self.import_button, self.rename_button, self.delete_button]
        listing = ttk.Frame(self)
        listing.grid(row=2, column=0, sticky='nsew')
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        listing.grid_propagate(False)
        self.files = ttk.Treeview(listing, columns=('name', 'date', 'uuid', 'size'), show='headings', selectmode='browse')
        configure_package_columns(self.files)
        self.files.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(listing, command=self.files.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.files.configure(yscrollcommand=scrollbar.set)
        style = ttk.Style(self)
        style.configure('Offline.Treeview', background='#e9edf0', fieldbackground='#e9edf0', foreground='#87949f')
        self.status_label = ttk.Label(self, textvariable=self.status, style='Hint.TLabel', wraplength=320)
        self.status_label.grid(row=3, column=0, sticky='ew', pady=(6, 0))
        self.details_label = ttk.Label(self, textvariable=self.transfer_details, style='Hint.TLabel', wraplength=320)
        self.details_label.grid(row=4, column=0, sticky='ew', pady=(4, 0))
        self.bind('<Configure>', lambda event: self.resize_labels(event.width))
        progress_track = ttk.Frame(self, height=5)
        progress_track.grid(row=5, column=0, sticky='ew', pady=(4, 0))
        progress_track.grid_propagate(False)
        self.bar = ttk.Progressbar(progress_track, mode='indeterminate')
        self.bar.place(x=0, y=0, relwidth=1, height=5)
        self.cancel_button = ttk.Button(buttons, text='Cancel transfer', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='right')
        self.sync_controls()
        self.timer = self.after(100, self.poll)

    def resize_labels(self, width):
        for label in (self.status_label, self.details_label):
            label.configure(wraplength=max(180, width - 24))

    def settings(self):
        return self.app.ftp_settings

    def toggle_connection(self):
        if self.connected or self.busy:
            self.disconnect_pending = True
            if self.busy:
                self.cancel()
            else:
                self.operation_finished()
        else:
            if not self.app.ftp_settings.configured():
                self.status.set('Set up your FTP server details first.')
                self.app.open_ftp()
                return
            self.refresh()

    def start(self, operation, done):
        if self.busy or self.app.busy:
            return
        self.app.external_busy = True
        FTPWindow.start(self, operation, done)
        if not self.busy:
            self.app.external_busy = False
        self.sync_controls()

    def operation_finished(self):
        if self.disconnect_pending:
            self.connected = False
            self.disconnect_pending = False
            self.status.set('Disconnected.')
            self.transfer_details.set('')
        if not self.connected:
            self.files.delete(*self.files.get_children())
            self.package_records.clear()
            self.listed_settings = None
        self.sync_controls()

    def sync_controls(self):
        enabled = self.connected and not self.busy
        self.connect_button.configure(text='Disconnect' if self.connected or self.busy else 'Connect')
        for button in self.controls:
            button.configure(state='normal' if enabled else 'disabled')
        self.files.configure(style='Treeview' if enabled else 'Offline.Treeview', selectmode='browse' if enabled else 'none')
        if enabled:
            self.files.unbind('<Button-1>')
            self.files.unbind('<Key>')
        else:
            self.files.bind('<Button-1>', lambda event: 'break')
            self.files.bind('<Key>', lambda event: 'break')

    def close(self):
        self.toggle_connection()

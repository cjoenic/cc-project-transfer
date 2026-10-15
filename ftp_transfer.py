"""FTP/explicit FTPS package transport; credentials never appear in status messages."""
import ftplib
import os
import shutil
import ssl
import socket
import re
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from transfer import TransferError, inspect_package, safe_member


def format_bytes(value):
    if value is None:
        return 'Unknown'
    number = float(value)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if number < 1024 or unit == 'TB':
            return f'{number:.0f} {unit}' if unit == 'B' else f'{number:.1f} {unit}'
        number /= 1024


def package_display(name, modified=None):
    """Presentation only: never use these values as remote paths."""
    stem = name[:-4] if name.lower().endswith('.zip') else name
    match = re.fullmatch(r'(.+)-(\d{8}-\d{6})-([0-9a-f]{12})', stem, re.IGNORECASE)
    if match:
        try:
            date = datetime.strptime(match[2], '%Y%m%d-%H%M%S')
            return match[1], date.strftime('%Y-%m-%d %H:%M:%S'), match[3]
        except ValueError:
            pass
    try:
        date = datetime.strptime(str(modified).split('.')[0], '%Y%m%d%H%M%S')
        return stem, date.strftime('%Y-%m-%d %H:%M:%S UTC'), '—'
    except ValueError:
        return stem, '—', '—'


class TransferProgress(str):
    """A readable message plus structured values for a determinate progress bar."""
    def __new__(cls, direction, filename, done, total, elapsed):
        speed = done / max(elapsed, .001) if done else 0
        remaining = max(0, total - done) / speed if total is not None and speed else None
        eta = 'calculating' if remaining is None else f'{int(remaining) // 60:02d}:{int(remaining) % 60:02d}'
        text = (f'{direction}: {filename}\n{format_bytes(done)} / {format_bytes(total)}'
                f' · {format_bytes(speed)}/s · ETA {eta}')
        result = super().__new__(cls, text)
        result.done, result.total, result.speed, result.eta = done, total, speed, remaining
        return result


def export_to_ftp(settings, project, package_name, include_media=True, notes='',
                  progress=lambda message: None, cancel=None, source_app='capcut'):
    from transfer import export_project
    remote_name(package_name)
    def report(message):
        check_cancel(cancel)
        progress(message)
    with tempfile.TemporaryDirectory(prefix='cc-ftp-export-') as temporary:
        package = Path(temporary) / package_name
        report('Preparing project for FTP…')
        export_project(project, package, include_media, notes, report, source_app=source_app)
        check_cancel(cancel)
        return upload_package(settings, package, report, cancel)


def export_many_to_ftp(settings, projects, include_media=True, notes='',
                       progress=lambda message: None, cancel=None):
    uploaded = []
    try:
        for index, project in enumerate(projects, 1):
            check_cancel(cancel)
            progress(f'Project {index}/{len(projects)}: preparing {project["name"]}…')
            uploaded.append(export_to_ftp(settings, project['path'], project['filename'],
                                           include_media, notes, progress, cancel,
                                           source_app=project.get('source_app', 'capcut')))
        return uploaded
    except Exception:
        # Keep batch semantics: attempt to remove packages uploaded earlier in this batch.
        for name in uploaded:
            try:
                delete_package(settings, name)
            except Exception:
                pass
        raise


def import_from_ftp(settings, name, drafts_root, progress=lambda message: None, cancel=None,
                    target_app='capcut'):
    from transfer import import_project
    def report(message):
        check_cancel(cancel)
        progress(message)
    with tempfile.TemporaryDirectory(prefix='cc-ftp-import-') as temporary:
        package = Path(temporary) / 'package.zip'
        download_package(settings, name, package, report, cancel)
        check_cancel(cancel)
        return import_project(package, drafts_root, report, target_app=target_app)


@dataclass
class FTPSettings:
    host: str = ''
    port: int = 21
    username: str = field(default='', repr=False)
    password: str = field(default='', repr=False)
    folder: str = ''
    ftps: bool = False

    def configured(self):
        return bool(self.host.strip() and self.username.strip() and self.password and
                    isinstance(self.port, int) and 1 <= self.port <= 65535)

    def to_config(self):
        return {key: getattr(self, key) for key in
                ('host', 'port', 'username', 'password', 'folder', 'ftps')}


class Cancelled(TransferError):
    pass


def check_cancel(cancel):
    if cancel and cancel.is_set():
        raise Cancelled('FTP operation cancelled.')
    pause = getattr(cancel, 'pause_event', None)
    if pause is not None and pause.is_set():
        started = time.monotonic()
        try:
            while pause.is_set():
                if cancel.wait(.1):
                    raise Cancelled('FTP operation cancelled.')
        finally:
            cancel.paused_seconds = getattr(cancel, 'paused_seconds', 0) + time.monotonic() - started


def transfer_elapsed(started, cancel, previous_pauses=0):
    return max(.001, time.monotonic() - started -
               (getattr(cancel, 'paused_seconds', 0) - previous_pauses))


def remote_name(name):
    safe_member(name)
    if '/' in name or not name.lower().endswith('.zip'):
        raise TransferError('Select a ZIP filename without directory components.')
    return name


def rename_package(settings, old_name, new_name, cancel=None):
    remote_name(old_name)
    remote_name(new_name)
    if old_name == new_name:
        return new_name
    check_cancel(cancel)
    with connection(settings) as ftp:
        # Include directories and non-package entries in the collision check.
        existing = {PurePosixPath(name).name.casefold() for name in ftp.nlst()}
        if new_name.casefold() in existing:
            raise TransferError('That remote name already exists. Choose a different name.')
        check_cancel(cancel)
        ftp.rename(old_name, new_name)
    return new_name


def delete_package(settings, name, cancel=None):
    remote_name(name)
    check_cancel(cancel)
    with connection(settings) as ftp:
        check_cancel(cancel)
        ftp.delete(name)
    return name


@contextmanager
def connection(settings):
    for value in (settings.host, settings.username, settings.password, settings.folder):
        if any(c in value for c in ('\r', '\n', '\x00')):
            raise TransferError('Connection settings contain invalid characters.')
    if not settings.configured():
        raise TransferError('Set up the FTP host, port, username and password in FTP settings first.')
    ftp = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=15) if settings.ftps else ftplib.FTP(timeout=15)
    stage = 'connecting'
    try:
        ftp.connect(settings.host, settings.port)
        stage = 'logging in'
        ftp.login(settings.username, settings.password)
        if settings.ftps:
            ftp.prot_p()
        ftp.set_pasv(True)
        stage = 'selecting the remote folder'
        if settings.folder.strip():
            ftp.cwd(settings.folder)
        stage = 'transferring or listing files'
        yield ftp
    except (TransferError, FileExistsError):
        raise
    except ssl.SSLError:
        raise TransferError('FTPS certificate or TLS negotiation failed. No fallback to plain FTP was attempted.') from None
    except socket.gaierror:
        raise TransferError('FTP hostname could not be resolved. Check the host and DNS connection.') from None
    except TimeoutError:
        raise TransferError(f'FTP timed out while {stage}. Check connectivity and passive-mode ports.') from None
    except ftplib.all_errors as error:
        code = str(error)[:3]
        reason = {'530': 'Login was rejected. Check the credentials.',
                  '550': 'File or folder unavailable, or access denied.',
                  '553': 'The server could not create the file. Check the remote folder and write permissions.',
                  '425': 'The server could not open the data connection. Check passive-mode ports.',
                  '426': 'The server interrupted the data transfer.'}.get(code, 'Check server permissions and connectivity.')
        label = f' (server code {code})' if code.isdigit() else ''
        raise TransferError(f'FTP failed while {stage}{label}. {reason}') from None
    finally:
        ftp.close()


def list_packages(settings, cancel=None):
    check_cancel(cancel)
    with connection(settings) as ftp:
        try:
            entries = list(ftp.mlsd(facts=['type', 'size', 'modify']))
        except ftplib.error_perm as error:
            if str(error)[:3] not in ('500', '501', '502', '504'):
                raise
            entries = [(name, {}) for name in ftp.nlst()]
        result = []
        for name, facts in entries:
            check_cancel(cancel)
            if facts.get('type') not in (None, 'file'):
                continue
            try:
                remote_name(name)
            except TransferError:
                continue
            size = facts.get('size', '')
            size = int(size) if str(size).isdigit() else None
            if size is None:
                # NLST only returns names. Some servers reject OPTS MLST, so ask SIZE separately.
                ftp.voidcmd('TYPE I')
                try:
                    size = ftp.size(name)
                except ftplib.error_perm:
                    size = None
            modified = facts.get('modify')
            if not modified:
                try:
                    reply = ftp.sendcmd('MDTM ' + name)
                    if reply.startswith('213 '):
                        modified = reply[4:].strip()
                except ftplib.error_perm:
                    pass
            result.append({'name': name, 'size': size, 'modified': modified})
        return sorted(result, key=lambda item: item['name'].casefold())


def verify_package(path, cancel=None):
    import hashlib
    manifest = inspect_package(path)
    with zipfile.ZipFile(path) as archive:
        for item in manifest['files']:
            h = hashlib.sha256()
            with archive.open(item['path']) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    check_cancel(cancel)
                    h.update(block)
            if h.hexdigest() != item['sha256']:
                raise TransferError('Package checksum verification failed.')
    return manifest


def upload_package(settings, path, progress=lambda message: None, cancel=None):
    path = Path(path)
    progress('Checking package before upload…')
    verify_package(path, cancel)
    remote_name(path.name)
    # Unique names prevent one teammate's upload from replacing another's package.
    name = f'{path.stem[:120]}-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:12]}.zip'
    pending = '.' + name + '.uploading'
    total = path.stat().st_size
    sent = 0
    last = 0
    started = 0
    previous_pauses = 0
    def advanced(block):
        nonlocal sent, last
        check_cancel(cancel)
        sent += len(block)
        if time.monotonic() - last > .2 or sent == total:
            progress(TransferProgress('Uploading', path.name, sent, total, transfer_elapsed(started, cancel, previous_pauses)))
            last = time.monotonic()
    with connection(settings) as ftp:
        try:
            check_cancel(cancel)
            started = time.monotonic()
            previous_pauses = getattr(cancel, 'paused_seconds', 0)
            progress(TransferProgress('Uploading', path.name, 0, total, 0))
            with path.open('rb') as stream:
                ftp.storbinary('STOR ' + pending, stream, 256 * 1024, advanced)
            check_cancel(cancel)
            ftp.rename(pending, name)
        except Exception:
            # A failed transfer may desynchronize the control channel. Clean up on a fresh connection.
            ftp.close()
            try:
                with connection(settings) as cleanup:
                    cleanup.delete(pending)
            except Exception:
                pass
            raise
    return name


def download_package(settings, name, destination, progress=lambda message: None, cancel=None):
    remote_name(name)
    destination = Path(destination).resolve()
    if destination.exists():
        raise TransferError('Destination exists. Choose a new filename.')
    if not destination.parent.is_dir():
        raise TransferError('Choose an existing download folder.')
    fd, temporary = tempfile.mkstemp(prefix='.ftp-', suffix='.part', dir=destination.parent)
    received = 0
    last = 0
    try:
        with os.fdopen(fd, 'wb') as stream, connection(settings) as ftp:
            check_cancel(cancel)
            ftp.voidcmd('TYPE I')
            try:
                total = ftp.size(name)
            except ftplib.error_perm:
                total = None
            free = shutil.disk_usage(destination.parent).free - 64 * 1024 * 1024
            if total is not None and total > free:
                raise TransferError('Not enough space for this download.')
            started = time.monotonic()
            previous_pauses = getattr(cancel, 'paused_seconds', 0)
            progress(TransferProgress('Downloading', name, 0, total, 0))
            def advanced(block):
                nonlocal received, last
                check_cancel(cancel)
                received += len(block)
                if received > free:
                    raise TransferError('Download exceeds available disk space.')
                stream.write(block)
                if time.monotonic() - last > .2 or received == total:
                    progress(TransferProgress('Downloading', name, received, total, transfer_elapsed(started, cancel, previous_pauses)))
                    last = time.monotonic()
            ftp.retrbinary('RETR ' + name, advanced, 256 * 1024)
            if total is not None and received != total:
                raise TransferError('Download size does not match the server file.')
            progress(TransferProgress('Downloading', name, received, total, transfer_elapsed(started, cancel, previous_pauses)))
        progress('Verifying downloaded package…')
        verify_package(temporary, cancel)
        check_cancel(cancel)
        if destination.exists():
            raise TransferError('Destination exists. Choose a new filename.')
        Path(temporary).rename(destination)
        return destination
    finally:
        Path(temporary).unlink(missing_ok=True)

"""Local CapCut and Jianying project packages. No source projects are modified."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

FORMAT_VERSION = 1
APP_NAMES = {'capcut': 'CapCut', 'jianying': 'Jianying'}
MEDIA_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v', '.mts',
                    '.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg', '.wma',
                    '.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif',
                    '.tiff', '.heic', '.svg', '.srt', '.ass', '.ttf', '.otf'}


class TransferError(Exception):
    pass


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def is_project(path):
    path = Path(path)
    return path.is_dir() and any((path / name).is_file() for name in
                                ('draft_content.json', 'draft_info.json', 'draft_meta_info.json'))


def discover_roots(saved=None, app='capcut'):
    if app not in APP_NAMES:
        raise TransferError('Unknown editor.')
    candidates = [Path(saved)] if saved else []
    local = os.environ.get('LOCALAPPDATA')
    if local:
        if app == 'capcut':
            candidates.append(Path(local) / 'CapCut/User Data/Projects/com.lveditor.draft')
        else:
            candidates.extend((Path(local) / 'JianyingPro/User Data/Projects/com.lveditor.draft',
                               Path(local) / 'JianyingPro/UserData/Projects/com.lveditor.draft'))
    return list(dict.fromkeys(p for p in candidates if p.is_dir()))


def list_projects(root):
    result = []
    for folder in Path(root).iterdir():
        if not is_project(folder) or folder.name.startswith('.transfer-'):
            continue
        name = folder.name
        try:
            name = read_json(folder / 'draft_meta_info.json').get('draft_name') or name
        except (OSError, ValueError, AttributeError):
            pass
        size = 0
        for current, dirs, files in os.walk(folder, followlinks=False):
            for filename in files:
                try:
                    size += (Path(current) / filename).stat(follow_symlinks=False).st_size
                except OSError:
                    pass
        result.append({'path': folder, 'name': str(name), 'modified': folder.stat().st_mtime,
                       'size': size})
    return sorted(result, key=lambda p: p['modified'], reverse=True)


def export_projects_to_folder(projects, destination, include_media=True, notes='',
                              filename_for=lambda item: item['name'] + '.zip', progress=None):
    """Export one ZIP per project and publish them only after the whole batch succeeds."""
    progress = progress or (lambda message: None)
    destination = Path(destination).resolve()
    if not destination.is_dir():
        raise TransferError('Choose an existing destination folder.')
    outputs = []
    used = set()
    for item in projects:
        base = filename_for(item)
        stem, suffix = Path(base).stem, Path(base).suffix or '.zip'
        candidate, number = base, 2
        while candidate.casefold() in used:
            candidate = f'{stem} ({number}){suffix}'
            number += 1
        used.add(candidate.casefold())
        output = destination / candidate
        if output.exists():
            raise TransferError(f'Destination already contains {candidate}. Choose another folder or rename it.')
        outputs.append(output)
    with tempfile.TemporaryDirectory(prefix='.cc-export-', dir=destination) as temporary:
        staged = []
        for index, (item, output) in enumerate(zip(projects, outputs), 1):
            progress(f'Project {index}/{len(projects)}: {item["name"]}')
            package = Path(temporary) / output.name
            export_project(item['path'], package, include_media, notes,
                           lambda message, i=index: progress(f'Project {i}/{len(projects)} · {message}'),
                           source_app=item.get('source_app', 'capcut'))
            staged.append(package)
        # Destinations were checked before packaging; recheck before making any visible.
        if any(output.exists() for output in outputs):
            raise TransferError('A destination file appeared during export. No batch files were published.')
        published = []
        try:
            for package, output in zip(staged, outputs):
                package.rename(output)
                published.append(output)
        except Exception:
            # Roll back only files created by this batch.
            for output in published:
                output.unlink(missing_ok=True)
            raise
    return outputs


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def project_files(project):
    files = []
    for folder, dirs, names in os.walk(project, followlinks=False):
        for name in dirs + names:
            path = Path(folder) / name
            attrs = getattr(path.lstat(), 'st_file_attributes', 0)
            if path.is_symlink() or attrs & 0x400:
                raise TransferError(f'Linked files or folders are not supported: {path}')
        files.extend(Path(folder) / name for name in names)
    return sorted(files)


def scan_project(project):
    project = Path(project).resolve()
    if not is_project(project):
        raise TransferError('This folder does not look like a supported editor project.')
    files = project_files(project)
    media = {}
    unreadable = []
    timelines = 0
    for path in files:
        if path.suffix.lower() != '.json':
            continue
        if path.name == 'draft_biz_config.json' and path.stat().st_size == 0:
            continue
        try:
            data = read_json(path)
        except (OSError, ValueError, UnicodeError):
            unreadable.append(str(path.relative_to(project)))
            continue
        if path.name in ('draft_content.json', 'draft_info.json'):
            timelines += 1
        for value in strings(data):
            if '://' in value or '\x00' in value:
                continue
            candidate = Path(value)
            if candidate.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            if not (candidate.is_absolute() or PureWindowsPath(value).is_absolute()):
                continue
            if value in media:
                continue
            exists = candidate.is_file()
            media[value] = {'original_path': value, 'exists': exists,
                            'size': candidate.stat().st_size if exists else None,
                            'internal': candidate.resolve().is_relative_to(project) if exists else False}
    return {'project': project, 'files': files, 'media': list(media.values()),
            'unreadable': unreadable, 'readable_timeline': timelines > 0,
            'project_size': sum(p.stat().st_size for p in files)}


def export_project(project, destination, include_media=True, notes='', progress=None,
                   source_app='capcut'):
    if source_app not in APP_NAMES:
        raise TransferError('Unknown source editor.')
    progress = progress or (lambda message: None)
    project = Path(project).resolve()
    destination = Path(destination).resolve()
    if destination.is_relative_to(project):
        raise TransferError('Save the ZIP outside the project folder.')
    if destination.exists():
        raise TransferError('That destination already exists. Choose a new filename.')
    progress('Scanning project…')
    scan = scan_project(project)
    if include_media:
        if not scan['readable_timeline'] or scan['unreadable']:
            raise TransferError('Automatic media collection needs readable project JSON. '
                                'Use project-only export for this draft format.')
        missing = [m for m in scan['media'] if not m['exists']]
        if missing:
            raise TransferError(f'{len(missing)} referenced media file(s) are missing. '
                                'Restore them or uncheck Include source media files.')
    entries = [(p, 'project/' + p.relative_to(project).as_posix()) for p in scan['files']]
    # Project-only exports omit recognized source-media files even when stored in the draft.
    if not include_media:
        entries = [(p, name) for p, name in entries if p.suffix.lower() not in MEDIA_EXTENSIONS]
    mapping = {}
    seen = {}
    for item in scan['media']:
        if not include_media:
            continue
        source = Path(item['original_path']).resolve()
        if item['internal']:
            archive_path = 'project/' + source.relative_to(project).as_posix()
        else:
            key = os.path.normcase(str(source))
            if key not in seen:
                archive_path = f'media/{len(seen):04d}/{source.name}'
                if source.is_symlink():
                    raise TransferError(f'Linked media is not supported: {source}')
                entries.append((source, archive_path))
                seen[key] = archive_path
            archive_path = seen[key]
        mapping[item['original_path']] = archive_path
    checklist = list(scan['media'])
    referenced = {os.path.normcase(str(Path(m['original_path']).resolve())) for m in checklist}
    for p in scan['files']:
        if p.suffix.lower() in MEDIA_EXTENSIONS and os.path.normcase(str(p)) not in referenced:
            checklist.append({'original_path': str(p), 'exists': True, 'size': p.stat().st_size,
                              'internal': True})
    manifest = {'format': 'capcut-project-transfer', 'version': FORMAT_VERSION,
                'source_app': source_app,
                'project_name': project.name, 'source_project_path': str(project),
                'include_media': include_media, 'notes': notes, 'media': checklist,
                'media_mapping': mapping, 'unreadable_json': scan['unreadable'], 'files': []}
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.transfer-', suffix='.zip', dir=destination.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as archive:
            for index, (source, name) in enumerate(entries):
                progress(f'Packing {index + 1}/{len(entries)}: {source.name}')
                h = hashlib.sha256()
                size = 0
                before = source.stat()
                with source.open('rb') as stream, archive.open(name, 'w', force_zip64=True) as target:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        target.write(block)
                        h.update(block)
                        size += len(block)
                after = source.stat()
                if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                    raise TransferError('A source file changed during export. Close the editor and try again.')
                manifest['files'].append({'path': name, 'size': size, 'sha256': h.hexdigest()})
            archive.writestr('manifest.json', json.dumps(manifest, indent=2, ensure_ascii=False))
            lines = ['Media checklist', 'Included: ' + str(include_media), '',
                     'Original paths may identify the sender’s Windows account or folders.', '']
            lines.extend(f"{m['original_path']} | {m['size']} bytes | "
                         f"{'available' if m['exists'] else 'MISSING'}" for m in checklist)
            archive.writestr('MEDIA_CHECKLIST.txt', '\n'.join(lines))
        # Windows rename refuses to overwrite an existing destination.
        if destination.exists():
            raise TransferError('Destination appeared during export. Choose a new filename.')
        Path(temporary).rename(destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return manifest


def safe_member(name):
    path = PurePosixPath(name)
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{p}{n}' for p in ('COM', 'LPT') for n in range(1, 10)}
    if (not name or '\\' in name or path.is_absolute() or
            any(p in ('', '.', '..') or ':' in p or p.endswith((' ', '.')) or
                p.split('.')[0].upper() in reserved or any(ord(c) < 32 for c in p)
                or any(c in '<>"|?*' for c in p) for p in name.split('/'))):
        raise TransferError(f'Unsafe archive path: {name}')
    return path


def inspect_package(filename):
    with zipfile.ZipFile(filename) as archive:
        infos = archive.infolist()
        if len(infos) > 100000:
            raise TransferError('Too many files in package.')
        names = set()
        for info in infos:
            safe_member(info.filename)
            key = info.filename.casefold()
            if key in names or stat.S_ISLNK(info.external_attr >> 16):
                raise TransferError('Duplicate names or symbolic links in package.')
            names.add(key)
        if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size > 16 * 1024 * 1024:
            raise TransferError('Missing or oversized package manifest.')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 'capcut-project-transfer' or manifest.get('version') != FORMAT_VERSION:
            raise TransferError('Unsupported package format or version.')
        if manifest.get('source_app', 'capcut') not in APP_NAMES:
            raise TransferError('Unknown source editor in package.')
        expected = {'manifest.json', 'MEDIA_CHECKLIST.txt'}
        for item in manifest['files']:
            name = item['path']
            safe_member(name)
            if not name.startswith(('project/', 'media/')) or name in expected:
                raise TransferError('Invalid manifest file entry.')
            expected.add(name)
            if archive.getinfo(name).file_size != item['size'] or item['size'] < 0:
                raise TransferError('File size does not match manifest.')
        if expected != {i.filename for i in infos}:
            raise TransferError('Unexpected or missing package files.')
        if not any(n in expected for n in ('project/draft_content.json', 'project/draft_info.json',
                                           'project/draft_meta_info.json')):
            raise TransferError('Package has no recognizable project.')
        manifest['unpacked_size'] = sum(i.file_size for i in infos)
        return manifest


def rewrite(value, mappings):
    if isinstance(value, dict):
        return {k: rewrite(v, mappings) for k, v in value.items()}
    if isinstance(value, list):
        return [rewrite(v, mappings) for v in value]
    if isinstance(value, str):
        normalized = value.replace('\\', '/').rstrip('/')
        for source, target in mappings:
            source = source.replace('\\', '/').rstrip('/')
            if normalized.casefold() == source.casefold():
                return str(target)
            if normalized.casefold().startswith(source.casefold() + '/'):
                return str(target / normalized[len(source) + 1:])
    return value


def import_project(filename, drafts_root, progress=None, target_app='capcut'):
    progress = progress or (lambda message: None)
    if target_app not in APP_NAMES:
        raise TransferError('Unknown destination editor.')
    manifest = inspect_package(filename)
    root = Path(drafts_root).resolve()
    if not root.is_dir():
        raise TransferError(f'Select an existing {APP_NAMES[target_app]} drafts folder first.')
    if manifest['unpacked_size'] + 100 * 1024 * 1024 > shutil.disk_usage(root).free:
        raise TransferError('Not enough free disk space to restore this package.')
    final = root / ('Transferred-' + uuid.uuid4().hex)
    media_folder = '_transfer_media_' + uuid.uuid4().hex
    if any(i['path'].split('/')[1].casefold() == media_folder.casefold() for i in manifest['files']):
        raise TransferError('Generated media directory conflicts with package contents. Try again.')
    stage = Path(tempfile.mkdtemp(prefix='.transfer-', dir=root))
    warnings = []
    unreadable_paths = []
    try:
        with zipfile.ZipFile(filename) as archive:
            for index, item in enumerate(manifest['files']):
                name = item['path']
                relative = name[len('project/'):] if name.startswith('project/') else media_folder + '/' + name[len('media/'):]
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                progress(f'Restoring {index + 1}/{len(manifest["files"])}: {target.name}')
                with archive.open(name) as source, target.open('xb') as stream:
                    shutil.copyfileobj(source, stream, 1024 * 1024)
                if digest(target) != item['sha256']:
                    raise TransferError(f'Checksum failed: {name}')
        mappings = []
        for original, packaged in manifest.get('media_mapping', {}).items():
            safe_member(packaged)
            if packaged not in {i['path'] for i in manifest['files']}:
                raise TransferError('Invalid media mapping.')
            relative = packaged[len('project/'):] if packaged.startswith('project/') else media_folder + '/' + packaged[len('media/'):]
            mappings.append((original, final / relative))
        source_root = manifest.get('source_project_path')
        if not isinstance(source_root, str) or not source_root.strip() or not (Path(source_root).is_absolute() or PureWindowsPath(source_root).is_absolute()):
            raise TransferError('Invalid source project path.')
        mappings.append((source_root, final))
        mappings.sort(key=lambda pair: len(pair[0]), reverse=True)
        for path in stage.rglob('*.json'):
            if media_folder in path.relative_to(stage).parts:
                continue
            if path.name == 'draft_biz_config.json' and path.stat().st_size == 0:
                continue
            try:
                original = read_json(path)
            except (ValueError, UnicodeError):
                unreadable_paths.append(path.relative_to(stage).as_posix())
                continue
            updated = rewrite(original, mappings)
            if updated != original:
                path.write_text(json.dumps(updated, ensure_ascii=False), encoding='utf-8')
        if unreadable_paths:
            critical = any(Path(name).name in ('draft_content.json', 'draft_info.json', 'draft_meta_info.json')
                           for name in unreadable_paths)
            if critical and manifest.get('source_app', 'capcut') != target_app:
                raise TransferError('Cross-editor transfer is unavailable: the draft timeline or metadata '
                                    'is not readable JSON (it may be encoded or protected). No project was restored. '
                                    'Use the original editor to open or export a transferable draft.')
            warnings.append('Some draft files are not readable JSON (they may be encoded or protected). '
                            'They were copied unchanged; automatic media relinking was not possible for these files:\n' +
                            '\n'.join(unreadable_paths) +
                            '\nThis is a file copy, not a verified playable project. Check it in the original editor.')
        stage.rename(final)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    if not manifest['include_media']:
        warnings.append(f'Media was transferred separately. Copy your source files and relink them in {APP_NAMES[target_app]}.')
    source_app = manifest.get('source_app', 'capcut')
    if source_app != target_app:
        warnings.append(f'Experimental {APP_NAMES[source_app]} → {APP_NAMES[target_app]} transfer: '
                        'the draft may not open or keep every effect editable. Verify it in the destination editor.')
    warnings.append(f'{APP_NAMES[target_app]} compatibility is not verified. If the project is absent from its home screen, '
                    'this version may require project registration. Existing editor indexes and project IDs were not changed.')
    return final, warnings


def transfer_between_apps(project, drafts_root, source_app, target_app, progress=None):
    """Copy through the validated package format; leave the source draft untouched."""
    if source_app not in APP_NAMES or target_app not in APP_NAMES or source_app == target_app:
        raise TransferError('Choose two different supported editors.')
    project = Path(project).resolve()
    root = Path(drafts_root).resolve()
    if not root.is_dir() or project.is_relative_to(root) or root.is_relative_to(project):
        raise TransferError('Choose the other editor’s drafts folder as the destination.')
    with tempfile.TemporaryDirectory(prefix='cc-cross-transfer-') as temporary:
        package = Path(temporary) / 'project.zip'
        export_project(project, package, include_media=True, progress=progress,
                       source_app=source_app)
        return import_project(package, root, progress, target_app=target_app)

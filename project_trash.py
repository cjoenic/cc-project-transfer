"""Recycle only a verified, direct child project of the selected drafts folder."""
import os
from pathlib import Path

from transfer import TransferError, is_project


def validate_project(project, drafts_root):
    original = Path(project).absolute()
    root = Path(drafts_root).resolve(strict=True)
    path = original.resolve(strict=True)
    if path == root or path.parent != root or not is_project(path):
        raise TransferError('Only a project directly inside the selected drafts folder can be recycled.')
    if original.is_symlink() or getattr(original.lstat(), 'st_file_attributes', 0) & 0x400:
        raise TransferError('Linked project folders cannot be recycled by this app.')
    return path


def _recycle(path):
    import pythoncom
    from win32com.shell import shell, shellcon
    from win32com.server.exception import COMException
    from send2trash.win.IFileOperationProgressSink import FileOperationProgressSink

    class RecycleOnlySink(FileOperationProgressSink):
        def PreDeleteItem(self, flags, item):
            if not flags & shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE:
                # Returning an HRESULT alone may be ignored by the Python COM wrapper.
                raise COMException(desc='Permanent deletion is disabled.', scode=-2147467260)
            return 0

    pythoncom.CoInitialize()
    try:
        operation = pythoncom.CoCreateInstance(shell.CLSID_FileOperation, None,
                                               pythoncom.CLSCTX_ALL, shell.IID_IFileOperation)
        operation.SetOperationFlags(shellcon.FOF_NOCONFIRMATION | shellcon.FOF_NOERRORUI |
                                    shellcon.FOF_SILENT | shellcon.FOFX_EARLYFAILURE |
                                    0x20000000 | 0x00080000)
        sink = pythoncom.WrapObject(RecycleOnlySink(), shell.IID_IFileOperationProgressSink)
        item = shell.SHCreateItemFromParsingName(str(path), None, shell.IID_IShellItem)
        operation.DeleteItem(item, sink)
        result = operation.PerformOperations()
        if result or operation.GetAnyOperationsAborted():
            raise TransferError('Windows could not recycle this project. No permanent-delete fallback was attempted.')
    finally:
        pythoncom.CoUninitialize()


def recycle_project(project, drafts_root):
    path = validate_project(project, drafts_root)
    if os.name != 'nt':
        raise TransferError('The Windows Recycle Bin is only available on Windows.')
    try:
        _recycle(path)
    except TransferError:
        raise
    except Exception as error:
        raise TransferError('Windows could not move the project to the Recycle Bin. Check that CapCut is closed and the drive supports recycling.') from error
    if path.exists():
        raise TransferError('The project is still in place. Windows did not complete recycling.')
    return path

# logic/managers/project/project_file_ops.py
"""
Файлові операції менеджера проектів:
  new_file, open_file, rename, delete_file
  clipboard (cut/copy/paste), copy_numbering (_unique_path)
"""
from __future__ import annotations
import logging
import shutil
from pathlib import Path
from typing import Optional

from PyQt5.QtCore    import QCoreApplication, QModelIndex, Qt
from PyQt5.QtWidgets import QMenu, QMessageBox

from .project_constants import STYLE_MENU

logger = logging.getLogger(__name__)


def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


# ---------------------------------------------------------------------------
# Контекстне меню дерева файлів
# ---------------------------------------------------------------------------

def build_project_tree_context_menu(manager, pos) -> None:
    """Побудувати і показати контекстне меню для _project_tree."""
    if manager._current_project is None:
        return

    proxy_index = manager._project_tree.indexAt(pos)
    path: Optional[Path] = None
    index = proxy_index
    if proxy_index.isValid():
        src_index = manager._tree_proxy.mapToSource(proxy_index)
        fp = manager._fs_model.filePath(src_index)
        if fp:
            path = Path(fp)

    menu = QMenu(manager._project_tree)
    menu.setStyleSheet(STYLE_MENU)

    menu.addAction(_tr("New file")).triggered.connect(
        lambda: on_new_file(manager, path))
    menu.addSeparator()

    if path is not None:
        if path.is_file():
            menu.addAction(_tr("Open (read only)")).triggered.connect(
                lambda: on_open_file(manager, path, read_only=True))
            menu.addAction(_tr("Open (edit)")).triggered.connect(
                lambda: on_open_file(manager, path, read_only=False))
            menu.addSeparator()

        menu.addAction(_tr("Rename")).triggered.connect(
            lambda: on_rename(manager, path, index))
        menu.addAction(_tr("Delete")).triggered.connect(
            lambda: on_delete_file(manager, path))
        menu.addSeparator()

        menu.addAction(_tr("Cut")).triggered.connect(
            lambda: clipboard_op(manager, path, cut=True))
        menu.addAction(_tr("Copy")).triggered.connect(
            lambda: clipboard_op(manager, path, cut=False))

    clipboard_src = getattr(manager, "_clipboard_path", None)
    if clipboard_src is not None:
        if path is not None:
            menu.addSeparator()
        cut_label   = _tr("(excised)") if getattr(manager, "_clipboard_cut", False) else _tr("(copy)")
        paste_label = f"{_tr('Paste')}  [{clipboard_src.name}]  {cut_label}"
        menu.addAction(paste_label).triggered.connect(
            lambda: on_paste(manager, path))

    menu.exec_(manager._project_tree.viewport().mapToGlobal(pos))


# ---------------------------------------------------------------------------
# Файлові операції
# ---------------------------------------------------------------------------

def on_new_file(manager, context_path: Optional[Path]) -> None:
    """Створити новий файл у проекті через QInputDialog."""
    parent_dir = (
        context_path.parent if context_path and context_path.is_file()
        else (context_path if context_path and context_path.is_dir()
              else manager._current_project)
    )
    from PyQt5.QtWidgets import QInputDialog
    name, ok = QInputDialog.getText(
        manager._w("tree_view_project"),
        _tr("New file"), _tr("Name file:")
    )
    if not ok or not name.strip():
        return
    dest = unique_path(parent_dir / name.strip())
    try:
        dest.touch()
    except Exception as exc:
        show_error(manager, _tr(f"Error creating file: {exc}"))


def on_open_file(manager, path: Path, read_only: bool) -> None:
    """Відкрити файл у редакторі коду."""
    em = getattr(manager, "_editor_manager", None)
    if em is not None:
        em.load_file(str(path), read_only=read_only)
        return
    cb = getattr(manager, "_open_file_callback", None)
    if cb:
        cb(str(path), read_only)
    else:
        logger.warning("on_open_file: немає editor_manager і callback")


def on_rename(manager, path: Path, index: QModelIndex) -> None:
    """Перейменувати файл/папку через inline-редагування у дереві."""
    manager._project_tree.edit(index)


def on_delete_file(manager, path: Path) -> None:
    """Видалити файл або папку після підтвердження."""
    reply = QMessageBox.question(
        manager._w("tree_view_project"),
        _tr("Delete file"),
        _tr(f'Delete "{path.name}"?'),
        QMessageBox.Yes | QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        em = getattr(manager, "_editor_manager", None)
        if em is not None and em._current_file == str(path):
            em.clear_editor()
    except Exception as exc:
        show_error(manager, _tr(f"Deletion error: {exc}"))


# ---------------------------------------------------------------------------
# Буфер обміну (cut/copy/paste)
# ---------------------------------------------------------------------------

def clipboard_op(manager, path: Path, cut: bool) -> None:
    """Запам'ятати файл/папку для вставки."""
    manager._clipboard_path = path.resolve()
    manager._clipboard_cut  = cut
    logger.debug("%s: %s", "Вирізано" if cut else "Скопійовано",
                 manager._clipboard_path)


def on_paste(manager, context_path: Optional[Path]) -> None:
    """
    Вставити зі збереженого буфера.
    Папка призначення: клік на папку → в неї; на файл → батьківська; порожнє → корінь.
    Copy Numbering при конфліктах імен.
    """
    src = getattr(manager, "_clipboard_path", None)
    if src is None or not src.exists():
        show_error(manager, _tr("Clipboard is empty or file no longer exists."))
        manager._clipboard_path = None
        return

    if context_path is None:
        dest_dir = manager._current_project
    elif context_path.is_dir():
        dest_dir = context_path
    else:
        dest_dir = context_path.parent

    base_dest = dest_dir / src.name
    if base_dest == src:
        if manager._clipboard_cut:
            show_error(manager, _tr("Source and destination are the same."))
            return

    dest = base_dest if manager._clipboard_cut else unique_path(base_dest)

    try:
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
    except Exception as exc:
        show_error(manager, _tr(f"Paste error: {exc}"))
        return

    if manager._clipboard_cut:
        try:
            if src.is_dir():
                shutil.rmtree(src)
            else:
                src.unlink()
        except Exception as exc:
            show_error(manager, _tr(
                f"File copied, but failed to delete original: {exc}"))
        manager._clipboard_path = None
        manager._clipboard_cut  = False

    logger.debug("Вставлено: %s → %s", src, dest)


# ---------------------------------------------------------------------------
# Copy Numbering
# ---------------------------------------------------------------------------

def unique_path(dest: Path) -> Path:
    """
    Повернути унікальний шлях (Copy Numbering).
    file.txt → file (2).txt → file (3).txt → …
    """
    if not dest.exists():
        return dest
    name   = dest.name
    parent = dest.parent
    if dest.is_dir() or "." not in name:
        stem, ext = name, ""
    else:
        dot_idx = name.index(".")
        stem    = name[:dot_idx]
        ext     = name[dot_idx:]
    counter = 2
    while True:
        candidate = parent / f"{stem} ({counter}){ext}"
        if not candidate.exists():
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# Хелпер
# ---------------------------------------------------------------------------

def show_error(manager, message: str) -> None:
    QMessageBox.critical(
        manager._w("tree_view_project"),
        _tr("Error"), message
    )

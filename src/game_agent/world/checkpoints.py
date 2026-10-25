"""版本化检查点文件发布；不依赖 World、NPC 或模型。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from collections.abc import Callable, Mapping


VERSION = 1


def _write_json(path: Path, value: dict) -> None:
    with path.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def _digest(path: Path) -> str:
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        return digest.hexdigest()


def _member(directory: Path, relative: str) -> Path:
    path = (directory / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(directory.resolve()):
        raise ValueError('检查点文件路径越界')
    return path


def publish(root: str, state: dict,
            databases: Mapping[str, Callable[[str], None]]) -> str:
    """导出所有库后发布单代；发布前失败不改变 LATEST。"""
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    generation = uuid.uuid4().hex
    staging = base / f'.pending-{generation}'
    final = base / generation
    pointer = base / f'.LATEST-{generation}'
    staging.mkdir()
    try:
        files = {}
        for relative, export in databases.items():
            destination = _member(staging, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            export(str(destination))
            with destination.open('rb') as stream:
                os.fsync(stream.fileno())
            files[relative] = _digest(destination)
        _write_json(staging / 'manifest.json', {
            'version': VERSION, 'generation': generation, 'files': files, 'state': state})
        os.replace(staging, final)
        _write_json(pointer, {'generation': generation})
        os.replace(pointer, base / 'LATEST')
        return generation
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        pointer.unlink(missing_ok=True)


def read(root: str) -> tuple[Path, dict]:
    base = Path(root).resolve()
    generation = json.loads((base / 'LATEST').read_text())['generation']
    if not isinstance(generation, str) or len(generation) != 32 or any(
            char not in '0123456789abcdef' for char in generation):
        raise ValueError('无效检查点代号')
    directory = _member(base, generation)
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('version') != VERSION or manifest.get('generation') != generation:
        raise ValueError('检查点版本或代号不匹配')
    files = manifest['files']
    expected = {'world.db', *(npc['file'] for npc in manifest['state']['npcs'])}
    if set(files) != expected:
        raise ValueError('检查点数据库清单不完整')
    for relative, checksum in files.items():
        path = _member(directory, relative)
        if not path.is_file() or _digest(path) != checksum:
            raise ValueError(f'检查点文件校验失败: {relative}')
    return directory, manifest


def materialize(directory: Path, manifest: dict, destination: str) -> Path:
    """只恢复到新目录，检查点原文件不被当作实时数据库打开。"""
    target = Path(destination).resolve()
    if target.exists():
        raise FileExistsError(f'恢复目录已存在: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f'.restore-{uuid.uuid4().hex}'
    staging.mkdir()
    try:
        for relative, checksum in manifest['files'].items():
            source = _member(directory, relative)
            out = _member(staging, relative)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, out)
            if _digest(out) != checksum:
                raise ValueError(f'恢复文件校验失败: {relative}')
        # 不替换已有运行目录；新目录直到所有文件就绪才可见。
        if target.exists():
            raise FileExistsError(str(target))
        os.rename(staging, target)
        return target
    finally:
        shutil.rmtree(staging, ignore_errors=True)

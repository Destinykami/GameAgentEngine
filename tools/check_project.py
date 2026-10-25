"""统一离线验收：测试、前端构建/数据与独立 wheel 安装。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def run(command, *, cwd=ROOT, env=None):
    print('检查：' + ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)


def installed_package_check():
    uv = shutil.which('uv')
    if uv is None:
        raise RuntimeError('需要本地 uv 和缓存的构建依赖以进行离线 wheel 检查')
    with tempfile.TemporaryDirectory(prefix='gameagent-package-check-') as temporary:
        base = Path(temporary)
        wheels = base / 'wheels'
        run([uv, 'build', '--wheel', '--offline', '--out-dir', wheels])
        wheel, = wheels.glob('*.whl')
        source = ROOT / 'src'
        expected = {str(path.relative_to(source)): path.read_bytes()
                    for path in (source / 'game_agent').rglob('*.py')}
        with zipfile.ZipFile(wheel) as archive:
            actual = {name: archive.read(name) for name in archive.namelist() if name.endswith('.py')}
        if actual != expected:
            raise AssertionError('wheel 源码与当前 src 不一致')
        environment = base / 'venv'
        run([uv, 'venv', '--offline', '--python', sys.executable, environment], cwd=base)
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        run([uv, 'pip', 'install', '--python', python, '--no-index', '--no-deps', wheel], cwd=base)
        smoke = base / 'smoke.py'
        smoke.write_text('''
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

def deny(*args, **kwargs):
    raise AssertionError('独立安装检查不允许网络')
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.getaddrinfo = deny
import game_agent
from game_agent import World, Location, NPC, HashEmbedder
from game_agent.evaluation.metrics import percentile
from game_agent.runners.replay.terminal import render_step
assert Path(game_agent.__file__).is_relative_to(Path(sys.prefix))
model = SimpleNamespace(score_importance=lambda *args: 5)
base = Path(sys.argv[1])
w = World('检查', [Location('L', 0, 0)], path=str(base / 'live/world.db'))
try:
    npc = w.add_npc('A', {}, model, embedder=HashEmbedder(), data_dir=str(base / 'live'))
    npc.observe('关系观察', 1, 'P')
    npc.observe('关系观察', 2)
    assert npc.memory_count() == 2
    w.advance(2)
    w.save_checkpoint(str(base / 'checkpoints'))
finally:
    w.close()
r = World.from_checkpoint(str(base / 'checkpoints'), str(base / 'resumed'), model)
try:
    assert r.clock == 2 and r.npc('A').memory_count() == 2
finally:
    r.close()
print('独立 wheel 安装、记忆隔离、检查点保存恢复及正式导入通过')
''', encoding='utf-8')
        run([python, '-I', smoke, base], cwd=base)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-frontend', action='store_true', help='仅执行后端及安装检查')
    parser.add_argument('--skip-package', action='store_true', help='跳过独立 wheel 安装检查')
    parser.add_argument('--e2e', action='store_true', help='追加浏览器回放检查（需本地 Chromium）')
    args = parser.parse_args()
    if args.e2e and args.skip_frontend:
        parser.error('--e2e 不能和 --skip-frontend 联用')
    run([sys.executable, '-m', 'pytest', 'tests/', '-q'])
    if not args.skip_frontend:
        npm = shutil.which('npm')
        if npm is None:
            raise RuntimeError('未找到 npm，请将 Node.js 安装目录加入 PATH')
        env = dict(os.environ)
        env['PATH'] = str(Path(npm).parent) + os.pathsep + env.get('PATH', '')
        for task in ['test', 'build', 'validate'] + (['e2e'] if args.e2e else []):
            run([npm, 'run', task], cwd=ROOT / 'visualization', env=env)
    if not args.skip_package:
        installed_package_check()
    print('所选离线验收全部通过。', flush=True)


if __name__ == '__main__':
    main()

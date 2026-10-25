"""在独立 pytest 进程确认默认跳过和外网拦截，测试本身不联网。"""
from pathlib import Path
import subprocess
import sys


def run_pytest(tmp_path, code):
    policy = Path(__file__).with_name('conftest.py').read_text()
    (tmp_path / 'conftest.py').write_text(policy)
    (tmp_path / 'test_policy.py').write_text(code)
    return subprocess.run([sys.executable, '-m', 'pytest', '-q', '--confcutdir', str(tmp_path), str(tmp_path)],
                          cwd=tmp_path, capture_output=True, text=True)


def test_default_online_skip_happens_before_fixture_network_probe(tmp_path):
    result = run_pytest(tmp_path, '''
import pytest
@pytest.fixture
def probe():
    raise RuntimeError('must not probe')
@pytest.mark.online
def test_online(probe):
    assert False
''')
    assert result.returncode == 0 and '1 skipped' in result.stdout


def test_swallowed_external_network_attempt_still_fails(tmp_path):
    result = run_pytest(tmp_path, '''
import socket
def test_accidental_probe():
    try:
        socket.getaddrinfo('external.invalid', 443)
    except Exception:
        pass
''')
    assert result.returncode != 0 and '离线测试曾尝试外部网络' in result.stdout


def test_loopback_server_is_allowed(tmp_path):
    result = run_pytest(tmp_path, '''
import socket
def test_local_socket():
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        server.listen()
        with socket.create_connection(server.getsockname()) as client:
            connection, _ = server.accept()
            connection.close()
''')
    assert result.returncode == 0, result.stdout

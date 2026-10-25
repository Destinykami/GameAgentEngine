"""默认离线：在线探针显式开启，外部网络访问必须可见。"""
import ipaddress
import socket

import pytest


def pytest_addoption(parser):
    parser.addoption('--online', action='store_true', help='显式启用真实端点探针')


def pytest_collection_modifyitems(config, items):
    if not config.getoption('--online'):
        for item in items:
            if item.get_closest_marker('online'):
                item.add_marker(pytest.mark.skip(reason='真实探针默认关闭；需显式 --online'))


def _loopback(host):
    if isinstance(host, bytes):
        host = host.decode('ascii', errors='replace')
    if host in (None, '', 'localhost'):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def offline_network_guard(request, monkeypatch):
    if request.node.get_closest_marker('online') and request.config.getoption('--online'):
        yield
        return
    attempts = []
    def check(host):
        if not _loopback(host):
            attempts.append(str(host))
            raise AssertionError(f'离线测试禁止外部网络: {host}')
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo
    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check(address[0])
        return connect(sock, address)
    def guarded_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check(address[0])
        return connect_ex(sock, address)
    def guarded_dns(host, *args, **kwargs):
        check(host)
        return getaddrinfo(host, *args, **kwargs)
    monkeypatch.setattr(socket.socket, 'connect', guarded_connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', guarded_connect_ex)
    monkeypatch.setattr(socket, 'getaddrinfo', guarded_dns)
    yield
    if attempts:
        pytest.fail('离线测试曾尝试外部网络: ' + ', '.join(attempts))

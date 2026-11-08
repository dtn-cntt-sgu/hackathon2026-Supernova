"""Isolated benchmark server with enforced local-only sockets, never production entrypoint."""
import ipaddress
import os
import socket


def is_loopback(host):
    if isinstance(host,bytes):
        try:host=host.decode('ascii')
        except UnicodeDecodeError:return False
    if host == 'localhost':return True
    try:return ipaddress.ip_address(host).is_loopback
    except (ValueError,TypeError):return False


def restrict_network():
    original_connect=socket.socket.connect
    original_connect_ex=socket.socket.connect_ex
    original_resolve=socket.getaddrinfo
    def connect(sock,address):
        if isinstance(address,tuple) and not is_loopback(address[0]):raise OSError('External network disabled in benchmark server')
        return original_connect(sock,address)
    def connect_ex(sock,address):
        if isinstance(address,tuple) and not is_loopback(address[0]):return 101
        return original_connect_ex(sock,address)
    def resolve(host,*args,**kwargs):
        if not is_loopback(host):raise OSError('External DNS disabled in benchmark server')
        return original_resolve(host,*args,**kwargs)
    socket.socket.connect=connect
    socket.socket.connect_ex=connect_ex
    socket.getaddrinfo=resolve


if __name__=='__main__':
    restrict_network()
    import uvicorn
    uvicorn.run('backend.app.main:app',host='127.0.0.1',port=int(os.environ['SAFEPATH_BENCHMARK_PORT']),loop='asyncio',log_level='warning')

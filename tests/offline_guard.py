"""Default test boundary: synthetic configuration, no external DNS or sockets."""
import ipaddress
import os
import sys
from urllib.parse import urlparse


def install():
    if getattr(sys, '_factory_offline_tests', False):return
    sys._factory_offline_tests = True
    # Do not inherit Windows system proxies into an allegedly offline child.
    # Explicit environment-proxy routing remains testable without using a real proxy.
    import urllib.request
    urllib.request.getproxies=urllib.request.getproxies_environment
    urllib.request.proxy_bypass=urllib.request.proxy_bypass_environment
    def local(host):
        if isinstance(host, bytes):host=host.decode('ascii',errors='replace')
        if host in (None,'','localhost'):return True
        try:return ipaddress.ip_address(str(host).strip('[]')).is_loopback
        except ValueError:return False
    def audit(event,args):
        if event in {'socket.getaddrinfo','socket.gethostbyname'}:
            host=args[0]
            try:ipaddress.ip_address(str(host).strip('[]'))
            except ValueError:
                if not local(host):raise OSError('External DNS disabled by production test isolation')
        elif event in {'socket.gethostbyaddr','socket.getnameinfo'}:
            host=args[0][0] if isinstance(args[0],tuple) else args[0]
            if not local(host):raise OSError('External reverse DNS disabled by production test isolation')
        elif event=='urllib.Request':
            if not local(urlparse(args[0]).hostname):raise OSError('External urllib request disabled by test isolation')
        elif event in {'socket.connect','socket.sendto'}:
            address=args[-1]
            if isinstance(address,tuple):
                if not local(address[0]):raise OSError('External network disabled by production test isolation')
                for key,value in os.environ.items():
                    if key.lower() not in {'http_proxy','https_proxy','all_proxy'}:continue
                    proxy=urlparse(value)
                    if proxy.hostname and local(proxy.hostname) and proxy.port==address[1]:
                        raise OSError('Live loopback proxy disabled by production test isolation')
    sys.addaudithook(audit)

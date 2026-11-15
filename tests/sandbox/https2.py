import socket,ssl,threading
c=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); c.load_cert_chain('c.pem','k.pem')
l=socket.socket(); l.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); l.bind(('0.0.0.0',443)); l.listen(64)
def h(s):
    try:
        t=c.wrap_socket(s,server_side=True)
        while True:
            d=t.recv(65536)
            if not d: break
            t.send(d[:10])
    except Exception: pass
def plain(port):
    p = socket.socket(); p.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); p.bind(('0.0.0.0', port)); p.listen(16)
    while True:
        c, _ = p.accept()
        threading.Thread(target=lambda c=c: [c.recv(65536) for _ in iter(int, 1)], daemon=True).start()
threading.Thread(target=plain, args=(4444,), daemon=True).start()  # "hacking tool" port for the suspicious-port check
threading.Thread(target=plain, args=(80,), daemon=True).start()    # plain HTTP for data-type checks
def counter(port):  # reads until the client is done sending, then replies with how many bytes arrived
    p = socket.socket(); p.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); p.bind(('0.0.0.0', port)); p.listen(16)
    def one(c):
        n = 0
        try:
            while True:
                d = c.recv(65536)
                if not d: break
                n += len(d)
            c.sendall(str(n).encode()); c.shutdown(socket.SHUT_WR)
        except Exception: pass
        c.close()
    while True:
        c, _ = p.accept(); threading.Thread(target=one, args=(c,), daemon=True).start()
threading.Thread(target=counter, args=(4445,), daemon=True).start()  # upload-then-close check
while True: threading.Thread(target=h,args=(l.accept()[0],),daemon=True).start()

import socket
M={'ads.doubleclick.net':'142.250.65.78','www.google-analytics.com':'142.250.65.78','www.youtube.com':'142.250.65.78',
   'connect.facebook.net':'157.240.1.35','bidder.criteo.com':'185.235.84.1','static.hotjar.com':'52.84.150.1',
   'api.anthropic.com':'160.79.104.10','sb.scorecardresearch.com':'23.55.161.1'}
import threading
def answer(q):
    i=12; labels=[]
    while q[i]: labels.append(q[i+1:i+1+q[i]].decode()); i+=q[i]+1
    ip=M.get('.'.join(labels).lower(),'203.0.113.9')
    return q[:2]+b'\x81\x80'+q[4:6]+b'\x00\x01\x00\x00\x00\x00'+q[12:i+5]+b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04'+socket.inet_aton(ip)
def tcp():  # DNS over TCP (used for large answers)
    t=socket.socket(); t.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); t.bind(('0.0.0.0',53)); t.listen(8)
    while True:
        c,_=t.accept()
        try:
            n=int.from_bytes(c.recv(2),'big'); q=c.recv(n); r=answer(q); c.send(len(r).to_bytes(2,'big')+r)
        except Exception: pass
        c.close()
threading.Thread(target=tcp,daemon=True).start()
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(('0.0.0.0',53))
while True:
    q,a=s.recvfrom(512); i=12; labels=[]
    while q[i]: labels.append(q[i+1:i+1+q[i]].decode()); i+=q[i]+1
    ip=M.get('.'.join(labels).lower(),'203.0.113.9')
    s.sendto(q[:2]+b'\x81\x80'+q[4:6]+b'\x00\x01\x00\x00\x00\x00'+q[12:i+5]+b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04'+socket.inet_aton(ip),a)

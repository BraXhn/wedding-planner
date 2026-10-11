import socketserver, sys
OUT = sys.argv[1]
class H(socketserver.StreamRequestHandler):
    def handle(self):
        w = lambda s: self.wfile.write((s + "\r\n").encode())
        w("220 fake ESMTP")
        data_mode, buf, rcpt = False, [], []
        while True:
            line = self.rfile.readline()
            if not line: return
            s = line.decode("utf-8", "replace").rstrip("\r\n")
            if data_mode:
                if s == ".":
                    data_mode = False
                    with open(OUT, "a") as f: f.write("RCPT:" + ",".join(rcpt) + "\n" + "\n".join(buf) + "\n=====\n")
                    buf, rcpt = [], []; w("250 OK")
                else: buf.append(s[1:] if s.startswith("..") else s)
                continue
            cmd = s[:4].upper()
            if cmd in ("EHLO", "HELO"): w("250-fake"); w("250 8BITMIME")
            elif cmd == "MAIL": w("250 OK")
            elif cmd == "RCPT": rcpt.append(s.split(":",1)[1].strip()); w("250 OK")
            elif cmd == "DATA": data_mode = True; w("354 go")
            elif cmd == "QUIT": w("221 bye"); return
            else: w("250 OK")
class T(socketserver.ThreadingMixIn, socketserver.TCPServer): allow_reuse_address = True
T(("127.0.0.1", 2525), H).serve_forever()

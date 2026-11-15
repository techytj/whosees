"""Reference reader for .wtgeo files (see build_geo.py for the format)."""
import bisect, ipaddress, mmap, struct, sys
from array import array

NONE = 0xFFFFFFFF


class WtGeo:
    def __init__(self, path):
        f = open(path, "rb")
        m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        if m[:8] != b"WTGEO1\0\0":
            raise ValueError("not a wtgeo file")
        c = struct.unpack_from("<8I", m, 8)
        o = 40
        self.m = m
        self.str_off, o = o, o + c[0]
        self.loc_off, o = o, o + 16 * c[1]
        self.v4c, o = self._table(o, c[2], 4)
        self.v6c, o = self._table(o, c[3], 8)
        self.asn_off, o = o, o + 8 * c[4]
        self.v4a, o = self._table(o, c[5], 4)
        self.v6a, o = self._table(o, c[6], 8)

    def _table(self, o, n, w):
        starts = array("I" if w == 4 else "Q")
        starts.frombytes(self.m[o:o + n * w])
        idx = array("I")
        idx.frombytes(self.m[o + n * w:o + n * w + 4 * n])
        end = o + n * w + 4 * n
        return (starts, idx), end + (-end % 8)

    def _s(self, off):
        e = self.m.find(b"\0", self.str_off + off)
        return self.m[self.str_off + off:e].decode()

    @staticmethod
    def _find(tbl, key):
        starts, idx = tbl
        i = bisect.bisect_right(starts, key) - 1
        return NONE if i < 0 else idx[i]

    def lookup(self, ip):
        a = ipaddress.ip_address(ip)
        key = int(a) if a.version == 4 else int(a) >> 64
        ct, at = (self.v4c, self.v4a) if a.version == 4 else (self.v6c, self.v6a)
        out = {}
        li = self._find(ct, key)
        if li != NONE:
            cc, lat, lon, _, city, region = struct.unpack_from("<2shhHII", self.m, self.loc_off + 16 * li)
            out.update(country=cc.decode(), lat=lat / 100, lon=lon / 100,
                       city=self._s(city), region=self._s(region))
        ai = self._find(at, key)
        if ai != NONE:
            n, org = struct.unpack_from("<II", self.m, self.asn_off + 8 * ai)
            out.update(asn=n, org=self._s(org))
        return out


if __name__ == "__main__":
    g = WtGeo(sys.argv[1])
    for ip in sys.argv[2:]:
        print(ip, g.lookup(ip))

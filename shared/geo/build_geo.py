#!/usr/bin/env python3
"""Convert DB-IP City Lite + ASN Lite CSVs into one compact offline file (wtgeo).

Usage: build_geo.py dbip-city-lite.csv.gz dbip-asn-lite.csv.gz out.wtgeo

Format (little-endian), all sections 4-byte aligned:
  header:   b"WTGEO1\\0\\0", u32 counts[8] =
            n_strings_bytes, n_locs, n_v4city, n_v6city, n_asns, n_v4asn, n_v6asn, reserved
  strings:  UTF-8 blob, each entry NUL-terminated (offset 0 = "")
  locs:     n_locs * { char cc[2]; i16 lat*100; i16 lon*100; u16 pad; u32 city_off; u32 region_off }  (16 B)
  v4city:   n_v4city * u32 start  then  n_v4city * u32 loc_index   (0xFFFFFFFF = unknown)
  v6city:   n_v6city * u64 start (top 64 bits) then n_v6city * u32 loc_index
  asns:     n_asns * { u32 asn; u32 org_off }
  v4asn / v6asn: same layout as v4city / v6city, index into asns

Lookup = binary search for the last start <= ip. Adjacent ranges that map
to the same record are merged; gaps become explicit "unknown" ranges.
Data: DB-IP.com Lite, CC BY 4.0 (attribution required in the app).
"""
import csv, gzip, io, ipaddress, struct, sys

NONE = 0xFFFFFFFF


class Strings:
    def __init__(self):
        self.buf = bytearray(b"\0")
        self.idx = {"": 0}

    def add(self, s):
        if s not in self.idx:
            self.idx[s] = len(self.buf)
            self.buf += s.encode() + b"\0"
        return self.idx[s]


def ip_ints(a, b):
    x, y = ipaddress.ip_address(a), ipaddress.ip_address(b)
    if x.version == 4:
        return 4, int(x), int(y)
    return 6, int(x) >> 64, int(y) >> 64


def ranges(rows, keyfn):
    """rows -> {4: [(start, idx)], 6: [...]}, merged with gap filling."""
    out = {4: [], 6: []}
    nxt = {4: 0, 6: 0}
    for row in rows:
        v, s, e = ip_ints(row[0], row[1])
        k = keyfn(row)
        lst = out[v]
        if s > nxt[v]:
            if not lst or lst[-1][1] != NONE:
                lst.append((nxt[v], NONE))
        elif s < nxt[v]:  # overlapping /64-truncated v6 ranges: keep first
            if v == 6:
                if e < nxt[v]:
                    continue
                s = nxt[v]
            else:
                raise SystemExit(f"unsorted input at {row[0]}")
        if not lst or lst[-1][1] != k:
            lst.append((s, k))
        nxt[v] = e + 1
    return out


def read(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        yield from csv.reader(f)


def main(city_path, asn_path, out_path):
    st = Strings()
    locs, loc_idx = [], {}

    def city_key(r):
        cc = r[3] if len(r[3]) == 2 and r[3] != "ZZ" else ""
        if not cc:
            return NONE
        lat, lon = round(float(r[6]) * 100), round(float(r[7]) * 100)
        key = (cc, r[4], r[5], lat, lon)
        if key not in loc_idx:
            loc_idx[key] = len(locs)
            locs.append(key)
        return loc_idx[key]

    city = ranges(read(city_path), city_key)

    asns, asn_idx = [], {}

    def asn_key(r):
        key = (int(r[2]), r[3])
        if key not in asn_idx:
            asn_idx[key] = len(asns)
            asns.append(key)
        return asn_idx[key]

    asn = ranges(read(asn_path), asn_key)

    loc_bin = bytearray()
    for cc, region, cty, lat, lon in locs:
        loc_bin += struct.pack("<2shhHII", cc.encode(), lat, lon, 0, st.add(cty), st.add(region))
    asn_bin = bytearray()
    for n, org in asns:
        asn_bin += struct.pack("<II", n, st.add(org))
    while len(st.buf) % 8:
        st.buf += b"\0"

    def table(lst, wide):
        fmt = "<Q" if wide else "<I"
        b = bytearray(b"".join(struct.pack(fmt, s) for s, _ in lst))
        b += b"".join(struct.pack("<I", i) for _, i in lst)
        while len(b) % 8:
            b += b"\0"
        return b

    with open(out_path, "wb") as f:
        f.write(b"WTGEO1\0\0")
        f.write(struct.pack("<8I", len(st.buf), len(locs), len(city[4]), len(city[6]),
                            len(asns), len(asn[4]), len(asn[6]), 0))
        for part in (st.buf, loc_bin, table(city[4], False), table(city[6], True),
                     asn_bin, table(asn[4], False), table(asn[6], True)):
            f.write(part)
    print(f"locs={len(locs)} v4city={len(city[4])} v6city={len(city[6])} "
          f"asns={len(asns)} v4asn={len(asn[4])} v6asn={len(asn[6])} strings={len(st.buf)}")


if __name__ == "__main__":
    main(*sys.argv[1:4])

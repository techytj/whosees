//! Reader for the shared .wtgeo file (format documented in shared/geo/build_geo.py).

use memmap2::Mmap;
use std::fs::File;
use std::net::IpAddr;
use std::path::Path;

const NONE: u32 = u32::MAX;

#[derive(Clone, Debug, serde::Serialize, Default)]
pub struct GeoInfo {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub country: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub region: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub city: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lat: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lon: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub asn: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub org: Option<String>,
}

struct Table {
    starts: usize,
    idx: usize,
    n: usize,
    wide: bool,
}

pub struct Geo {
    m: Mmap,
    strings: usize,
    locs: usize,
    nlocs: usize,
    asns: usize,
    v4c: Table,
    v6c: Table,
    v4a: Table,
    v6a: Table,
}

impl Geo {
    pub fn open(path: &Path) -> std::io::Result<Geo> {
        let f = File::open(path)?;
        let m = unsafe { Mmap::map(&f)? };
        if m.len() < 40 || &m[..8] != b"WTGEO1\0\0" {
            return Err(std::io::Error::other("not a wtgeo file"));
        }
        let c: Vec<usize> = (0..8).map(|i| u32le(&m, 8 + i * 4) as usize).collect();
        let mut o = 40;
        let strings = o;
        o += c[0];
        let locs = o;
        o += 16 * c[1];
        let table = |o: &mut usize, n: usize, wide: bool| {
            let w = if wide { 8 } else { 4 };
            let t = Table { starts: *o, idx: *o + n * w, n, wide };
            *o += n * w + 4 * n;
            *o += (8 - *o % 8) % 8;
            t
        };
        let v4c = table(&mut o, c[2], false);
        let v6c = table(&mut o, c[3], true);
        let asns = o;
        o += 8 * c[4];
        let v4a = table(&mut o, c[5], false);
        let v6a = table(&mut o, c[6], true);
        if o > m.len() {
            return Err(std::io::Error::other("truncated wtgeo file"));
        }
        Ok(Geo { m, strings, locs, nlocs: c[1], asns, v4c, v6c, v4a, v6a })
    }

    fn find(&self, t: &Table, key: u64) -> u32 {
        let start = |i: usize| -> u64 {
            if t.wide { u64le(&self.m, t.starts + i * 8) } else { u32le(&self.m, t.starts + i * 4) as u64 }
        };
        // last index with start <= key
        let (mut lo, mut hi) = (0usize, t.n);
        while lo < hi {
            let mid = (lo + hi) / 2;
            if start(mid) <= key { lo = mid + 1 } else { hi = mid }
        }
        if lo == 0 { NONE } else { u32le(&self.m, t.idx + (lo - 1) * 4) }
    }

    fn string(&self, off: u32) -> Option<String> {
        let s = self.strings + off as usize;
        let end = self.m[s..].iter().position(|&b| b == 0)? + s;
        if end == s { None } else { Some(String::from_utf8_lossy(&self.m[s..end]).into_owned()) }
    }

    pub fn lookup(&self, ip: IpAddr) -> GeoInfo {
        let (key, ct, at) = match ip {
            IpAddr::V4(a) => (u32::from(a) as u64, &self.v4c, &self.v4a),
            IpAddr::V6(a) => match a.to_ipv4_mapped() {
                Some(v4) => (u32::from(v4) as u64, &self.v4c, &self.v4a),
                None => ((u128::from(a) >> 64) as u64, &self.v6c, &self.v6a),
            },
        };
        let mut g = GeoInfo::default();
        let li = self.find(ct, key);
        if li != NONE {
            let o = self.locs + 16 * li as usize;
            g.country = Some(String::from_utf8_lossy(&self.m[o..o + 2]).into_owned());
            g.lat = Some(i16le(&self.m, o + 2) as f32 / 100.0);
            g.lon = Some(i16le(&self.m, o + 4) as f32 / 100.0);
            g.city = self.string(u32le(&self.m, o + 8));
            g.region = self.string(u32le(&self.m, o + 12));
        }
        let ai = self.find(at, key);
        if ai != NONE {
            let o = self.asns + 8 * ai as usize;
            g.asn = Some(u32le(&self.m, o));
            g.org = self.string(u32le(&self.m, o + 4));
        }
        g
    }
}

#[derive(serde::Serialize)]
pub struct City { pub city: String, pub region: String, pub country: String, pub lat: f32, pub lon: f32 }

impl Geo {
    /// City-name search over the location table (for picking "home" without any online lookup).
    pub fn find_cities(&self, query: &str, limit: usize) -> Vec<City> {
        let q = query.trim().to_lowercase();
        if q.is_empty() { return vec![]; }
        let n = self.nlocs;
        let mut seen = std::collections::HashSet::new();
        let mut hits: Vec<(u8, City)> = Vec::new();
        for i in 0..n {
            let o = self.locs + 16 * i;
            let Some(city) = self.string(u32le(&self.m, o + 8)) else { continue };
            let base = city.split(" (").next().unwrap_or(&city).to_string();
            let lb = base.to_lowercase();
            let rank = if lb == q { 0 } else if lb.starts_with(&q) { 1 } else { continue };
            let region = self.string(u32le(&self.m, o + 12)).unwrap_or_default();
            let cc = String::from_utf8_lossy(&self.m[o..o + 2]).into_owned();
            if !seen.insert((lb.clone(), region.clone(), cc.clone())) { continue; }
            hits.push((rank, City { city: base, region, country: cc,
                lat: i16le(&self.m, o + 2) as f32 / 100.0, lon: i16le(&self.m, o + 4) as f32 / 100.0 }));
        }
        hits.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.city.len().cmp(&b.1.city.len())));
        hits.into_iter().take(limit).map(|h| h.1).collect()
    }
}

impl Geo {
    /// All address ranges located in a country (for blocking a whole country). Adjacent ranges merged.
    #[cfg_attr(windows, allow(dead_code))]
    pub fn country_ranges(&self, cc: &str) -> Vec<(IpAddr, IpAddr)> {
        let cc = cc.as_bytes();
        let mut out: Vec<(IpAddr, IpAddr)> = Vec::new();
        for (t, wide) in [(&self.v4c, false), (&self.v6c, true)] {
            let start = |i: usize| -> u64 { if wide { u64le(&self.m, t.starts + i * 8) } else { u32le(&self.m, t.starts + i * 4) as u64 } };
            let mut cur: Option<(u64, u64)> = None;
            for i in 0..t.n {
                let li = u32le(&self.m, t.idx + i * 4);
                let hit = li != NONE && {
                    let o = self.locs + 16 * li as usize;
                    &self.m[o..o + 2] == cc
                };
                let s = start(i);
                let e = if i + 1 < t.n { start(i + 1) - 1 } else if wide { u64::MAX } else { u32::MAX as u64 };
                match (hit, cur) {
                    (true, Some((a, b))) if b + 1 == s => cur = Some((a, e)),
                    (true, c) => { if let Some(r) = c { out.push(to_ip(r, wide)); } cur = Some((s, e)); }
                    (false, Some(r)) => { out.push(to_ip(r, wide)); cur = None; }
                    _ => {}
                }
            }
            if let Some(r) = cur { out.push(to_ip(r, wide)); }
        }
        out
    }
}

#[cfg_attr(windows, allow(dead_code))]
fn to_ip((a, b): (u64, u64), wide: bool) -> (IpAddr, IpAddr) {
    if wide {
        (IpAddr::V6(std::net::Ipv6Addr::from((a as u128) << 64)), IpAddr::V6(std::net::Ipv6Addr::from(((b as u128) << 64) | (u64::MAX as u128))))
    } else {
        (IpAddr::V4(std::net::Ipv4Addr::from(a as u32)), IpAddr::V4(std::net::Ipv4Addr::from(b as u32)))
    }
}

fn u32le(m: &[u8], o: usize) -> u32 { u32::from_le_bytes(m[o..o + 4].try_into().unwrap()) }
fn u64le(m: &[u8], o: usize) -> u64 { u64::from_le_bytes(m[o..o + 8].try_into().unwrap()) }
fn i16le(m: &[u8], o: usize) -> i16 { i16::from_le_bytes(m[o..o + 2].try_into().unwrap()) }

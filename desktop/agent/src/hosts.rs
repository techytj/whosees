//! Hostname -> (category, owner, service) using shared/categories/domains.json.

use std::collections::HashMap;
use std::path::Path;

#[derive(Clone, Debug, serde::Serialize)]
pub struct HostInfo { pub category: String, pub owner: String, pub service: String }

#[derive(Default)]
pub struct Hosts { map: HashMap<String, HostInfo> }

impl Hosts {
    pub fn load(path: &Path) -> std::io::Result<Hosts> {
        let v: serde_json::Value = serde_json::from_slice(&std::fs::read(path)?).map_err(std::io::Error::other)?;
        let mut map = HashMap::new();
        if let Some(d) = v.get("domains").and_then(|d| d.as_object()) {
            for (k, e) in d {
                let a = e.as_array().map(|a| a.iter().map(|x| x.as_str().unwrap_or("").to_string()).collect::<Vec<_>>()).unwrap_or_default();
                if a.len() == 3 {
                    map.insert(k.clone(), HostInfo { category: a[0].clone(), owner: a[1].clone(), service: a[2].clone() });
                }
            }
        }
        Ok(Hosts { map })
    }

    /// Longest-suffix match: "stats.g.doubleclick.net" -> "doubleclick.net".
    pub fn lookup(&self, host: &str) -> Option<&HostInfo> {
        let mut h = host.trim_end_matches('.');
        loop {
            if let Some(i) = self.map.get(h) { return Some(i); }
            match h.find('.') { Some(p) => h = &h[p + 1..], None => return None }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn suffix_match() {
        let mut h = Hosts::default();
        h.map.insert("doubleclick.net".into(), HostInfo { category: "ads".into(), owner: "Google".into(), service: "DoubleClick".into() });
        assert_eq!(h.lookup("stats.g.doubleclick.net").unwrap().category, "ads");
        assert!(h.lookup("notdoubleclick.net").is_none());
        assert!(h.lookup("example.com").is_none());
    }
}

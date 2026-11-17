use anyhow::{anyhow, Context as _};
use aya_build::{Package, Toolchain};

fn main() -> anyhow::Result<()> {
    let md = cargo_metadata::MetadataCommand::new()
        .no_deps()
        .exec()
        .context("cargo metadata")?;
    let pkg = md
        .packages
        .into_iter()
        .find(|p| p.name.as_str() == "sslcap-ebpf")
        .ok_or_else(|| anyhow!("sslcap-ebpf not found"))?;
    let root = pkg
        .manifest_path
        .parent()
        .ok_or_else(|| anyhow!("no parent"))?
        .as_str();
    aya_build::build_ebpf(
        [Package { name: pkg.name.as_str(), root_dir: root, ..Default::default() }],
        Toolchain::default(),
    )
}

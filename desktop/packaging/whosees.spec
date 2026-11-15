# Fedora package built from electron-builder's linux-unpacked output (see build-rpm.sh).
Name:           whosees
Version:        %{wt_version}
Release:        1%{?dist}
Summary:        See where your computer's data is going, live on a map
License:        GPL-3.0-or-later AND CC-BY-4.0 AND CC-BY-SA-4.0 AND ODbL-1.0
URL:            https://github.com/techytj/whosees
Requires:       polkit nftables iproute
AutoReqProv:    no
%global debug_package %{nil}
%global __strip /bin/true

%description
WhoSees shows, live on an offline world map, which apps on this computer send data
to which companies and cities, labels trackers and ads, and can block them.
It only runs while you are looking.

%install
mkdir -p %{buildroot}/opt/WhoSees %{buildroot}%{_datadir}/polkit-1/actions %{buildroot}%{_bindir} %{buildroot}%{_datadir}/applications %{buildroot}%{_datadir}/icons/hicolor/512x512/apps
cp -a %{wt_src}/. %{buildroot}/opt/WhoSees/
ln -s /opt/WhoSees/wiretrace %{buildroot}%{_bindir}/whosees
install -m644 %{wt_policy} %{buildroot}%{_datadir}/polkit-1/actions/io.github.techytj.whosees.policy
install -m644 %{wt_icon} %{buildroot}%{_datadir}/icons/hicolor/512x512/apps/whosees.png
cat > %{buildroot}%{_datadir}/applications/whosees.desktop <<DESK
[Desktop Entry]
Name=WhoSees
Comment=See where your data is going, live on a map
Exec=/opt/WhoSees/wiretrace %U
Icon=whosees
Terminal=false
Type=Application
Categories=Network;Monitor;
StartupWMClass=WhoSees
DESK

%files
/opt/WhoSees
%{_bindir}/whosees
%{_datadir}/applications/whosees.desktop
%{_datadir}/icons/hicolor/512x512/apps/whosees.png
%{_datadir}/polkit-1/actions/io.github.techytj.whosees.policy

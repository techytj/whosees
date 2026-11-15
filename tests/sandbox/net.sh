#!/usr/bin/env bash
# Private test network (run inside `unshare -rn`, no sudo needed):
#   this namespace = "the computer" (10.99.0.1), a child namespace = "the internet" (10.99.0.2 + public-looking IPs)
#   with a fake DNS server and an HTTPS echo server. Then runs: python3 tests.py
set -u
here="$(cd "$(dirname "$0")" && pwd)"; work="$(mktemp -d)"; cd "$work"
openssl req -x509 -newkey rsa:2048 -nodes -keyout k.pem -out c.pem -days 1 -subj /CN=test >/dev/null 2>&1
cp "$here/dns2.py" "$here/https2.py" .
ip link set lo up
unshare -n sleep 600 & CH=$!
timeout 1 tail -f /dev/null
ip link add wta type veth peer name wtb; ip link set wtb netns $CH
ip addr add 10.99.0.1/24 dev wta; ip link set wta up; ip route add default via 10.99.0.2
nsenter -t $CH -n sh -c 'ip link set lo up; ip addr add 10.99.0.2/24 dev wtb; for a in 142.250.65.78 157.240.1.35 185.235.84.1 52.84.150.1 160.79.104.10 23.55.161.1 203.0.113.9 45.155.205.233; do ip addr add $a/32 dev wtb; done; ip link set wtb up'
nsenter -t $CH -n python3 -I dns2.py & D=$!
nsenter -t $CH -n python3 -I https2.py & H=$!
timeout 1 tail -f /dev/null
python3 -I "${TESTPY:-$here/tests.py}" "$@"; rc=$?
kill $D $H $CH 2>/dev/null; rm -rf "$work"
exit $rc

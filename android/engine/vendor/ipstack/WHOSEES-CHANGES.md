# Changes made by WhoSees to ipstack 1.0.1

This is ipstack 1.0.1 (https://github.com/narrowlink/ipstack, Apache-2.0) with fixes to TCP handling in
`src/stream/tcp.rs`, marked `[WhoSees patch]`:

1. A FIN that arrives together with the app's last data no longer drops that data.
2. TCP half-close: when the app finishes sending, the reader gets end-of-stream but the connection stays
   open for the reply; `poll_shutdown` sends our FIN later (from CLOSE_WAIT too).
3. All in-order received data is passed on at once (it was capped at 8 KB per incoming packet).
4. `poll_shutdown` is woken when the app acknowledges our last data, instead of waiting indefinitely.

Covered by tests/sandbox/engine.py ("upload then close: every byte reaches the server").

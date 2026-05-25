"""End-to-end test: host code talks to the mock MCU over a TCP socket.

Exercises the full happy path:
  - identify chunking + zlib decompress + parse
  - 64-bit clock seed via get_uptime
  - 8 priming get_clock samples
  - regression starts producing sensible frequency estimates
"""

import asyncio

import pytest

from proto.handshake import connect
from proto.transport import StreamTransport
from tests import mock_mcu


async def _spawn_mock(port):
    server = await asyncio.start_server(mock_mcu._serve_client, "127.0.0.1", port)
    return server


@pytest.mark.asyncio
async def test_full_handshake_against_mock():
    port = 5556
    server = await _spawn_mock(port)
    try:
        # Give the server a tick to fully bind
        await asyncio.sleep(0.01)
        transport = await StreamTransport.connect_tcp("127.0.0.1", port)
        queue, clocksync = await connect(transport)
        try:
            # Data dictionary was loaded
            assert (
                queue.msgparser.messages_by_name["config_pwm_out"].msgformat.startswith(
                    "config_pwm_out"
                )
            )
            # Clock sync produced a reasonable frequency estimate
            assert clocksync.mcu_freq == 72000000.0
            est_freq = clocksync.clock_est[2]
            assert 0.5 * clocksync.mcu_freq < est_freq < 1.5 * clocksync.mcu_freq
            # We can issue arbitrary commands now
            queue.send("allocate_oids count=4")
            params = await asyncio.wait_for(
                queue.send_with_response("get_config", "config"), timeout=1.0
            )
            assert params["#name"] == "config"
        finally:
            await clocksync.stop()
            await queue.stop()
            await transport.close()
    finally:
        server.close()
        await server.wait_closed()

"""Private local socket, theme event listener and service lifetime."""
import asyncio
import fcntl
import json
import logging
import os
import signal
from light_config import SOCKET, STATE, THEME
from light_service import LightService
from theme_watch import ThemeWatch
from lock_watch import LockWatch
from shutdown_watch import ShutdownWatch


async def main():
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'control.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        service = LightService()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        async def handle(reader, writer):
            try:
                data = await asyncio.wait_for(reader.readline(), 3)
                request = json.loads(data)
                result = service.command(request['action'], request.get('value'))
            except Exception as error:
                result = service.snapshot(False) | {'message': str(error) or 'Unable to update the light.'}
            writer.write((json.dumps(result) + '\n').encode())
            try:
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        SOCKET.parent.mkdir(parents=True, exist_ok=True)
        SOCKET.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(handle, path=str(SOCKET), limit=8192)
        SOCKET.chmod(0o600)
        watcher = ThemeWatch(THEME, service.theme_changed)
        locks, shutdown = LockWatch(service), ShutdownWatch(service)
        service.power_settings_changed = lambda: (locks.update(), shutdown.changed.set())
        listeners = [asyncio.create_task(locks.run()), asyncio.create_task(shutdown.run())]
        try:
            await asyncio.wait_for(locks.ready.wait(), 3)
        except TimeoutError:
            pass
        runner = asyncio.create_task(service.run())
        runner.add_done_callback(lambda _: stop.set())
        service.publish()
        try:
            await stop.wait()
        finally:
            watcher.close()
            server.close()
            await server.wait_closed()
            runner.cancel()
            for listener in listeners:
                listener.cancel()
            for task in service.tasks:
                task.cancel()
            await asyncio.gather(runner, *listeners, *service.tasks, return_exceptions=True)
            await service.radio.disconnect()
            SOCKET.unlink(missing_ok=True)
            service.stage = 'offline'
            service.publish('Light controls are stopped.')
        if not runner.cancelled() and runner.exception():
            raise runner.exception()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    asyncio.run(main())

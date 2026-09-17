import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from backend import Backend
from types import SimpleNamespace as NS
from prepare_screen import prepare_screen
from protocol import CHARACTERISTIC, DeviceInfo, NotificationParser


class InitClient:
    def __init__(self, driver=1, slots=0):
        self.driver, self.slots = driver, slots
        self.writes = []
        self.stopped = False
    async def start_notify(self, uuid, callback):
        self.callback = callback
    async def stop_notify(self, uuid):
        self.stopped = True
    async def write_gatt_char(self, uuid, payload, response):
        self.writes.append((uuid, payload, response))
        self.callback(None, bytes([1, 2, 3, 4, 5, 6, 7, self.driver, 0, 0]))
        self.callback(None, b'mtu=244 rle=1')
        self.callback(None, f'slots={self.slots} 0 -1'.encode())
        self.callback(None, b'sid=test-secret')


class PrepareTests(unittest.IsolatedAsyncioTestCase):
    async def test_initializes_existing_driver_and_redacts_sid(self):
        client, logs, hashes = InitClient(), [], []
        info, parser = await prepare_screen(client, 'v1.10-om6626', logs.append, lambda sid: hashes.append(sid) or True)
        self.assertEqual(client.writes, [(CHARACTERISTIC, b'\x01', True)])
        self.assertTrue(info.supported)
        self.assertEqual(hashes, ['test-secret'])
        self.assertNotIn('test-secret', '\n'.join(logs))
        self.assertFalse(client.stopped)

    async def test_rejected_validation_cleans_up_notifications(self):
        client = InitClient()
        with self.assertRaisesRegex(RuntimeError, '校验未通过'):
            await prepare_screen(client, 'test', lambda _: None, lambda sid: False)
        self.assertTrue(client.stopped)
        self.assertEqual(len(client.writes), 1)

    async def test_slot_and_unknown_driver_block_image_preparation(self):
        for client in (InitClient(driver=0x99),):
            with self.assertRaises(RuntimeError):
                await prepare_screen(client, 'test', lambda _: None, lambda sid: self.fail('Unexpected validation'))
            self.assertTrue(client.stopped)
            self.assertEqual(len(client.writes), 1)

    def test_text_before_config_does_not_hide_driver(self):
        info = DeviceInfo()
        parser = NotificationParser(info)
        parser.feed(b'mtu=244 rle=1')
        parser.feed(bytes([1, 2, 3, 4, 5, 6, 7, 4, 0, 0]))
        self.assertEqual(info.driver, 4)
        self.assertTrue(info.configuration_received)


class BackendPrepareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_gate_opens_only_after_success_and_relocks_on_disconnect(self):
        backend = Backend()
        client = InitClient()
        client.is_connected = True
        async def disconnect():
            client.is_connected = False
        client.disconnect = disconnect
        backend.client = client
        try:
            with patch('backend.verify_device', return_value=True):
                backend.submit(backend.prepare_display()).result(timeout=3)
                self.assertTrue(backend.authorized)
                self.assertFalse(backend.read_only)
                backend.submit(backend.prepare_display()).result(timeout=3)
                self.assertEqual(len(client.writes), 1)
            backend.submit(backend.disconnect()).result(timeout=3)
            self.assertTrue(backend.read_only)
            self.assertFalse(backend.authorized)
        finally:
            backend.close()


if __name__ == '__main__':
    unittest.main()

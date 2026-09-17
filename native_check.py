"""Packaging diagnostic: scans BLE and reads SMTC thumbnails. No device writes/network."""
import asyncio
import json
from pathlib import Path


async def run(path):
    results = {}
    try:
        from bleak import BleakScanner
        from protocol import TARGET
        found = await BleakScanner.discover(timeout=7, return_adv=True)
        results['ble_scan_ok'] = True
        results['ble_advertisers'] = len(found)
        results['target_found'] = any((a.local_name or d.name) == TARGET for d, a in found.values())
    except Exception as e:
        results['ble_error'] = str(e)
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        from winrt.windows.storage.streams import Buffer, InputStreamOptions
        manager = await Manager.request_async()
        results['media_api_ok'] = True
        results['media'] = []
        for session in manager.get_sessions():
            p = await session.try_get_media_properties_async()
            item = {'source': session.source_app_user_model_id, 'has_title': bool(p.title)}
            if p.thumbnail:
                stream = await p.thumbnail.open_read_async()
                try:
                    data = await stream.read_async(Buffer(stream.size), stream.size, InputStreamOptions.NONE)
                    item['cover_bytes'] = len(bytes(memoryview(data)))
                finally:
                    stream.close()
            results['media'].append(item)
    except Exception as e:
        results['media_error'] = str(e)
    Path(path).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')

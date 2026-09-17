"""Compatibility entrypoint for the read-only UUID capture/GATT connection tool."""
from ble_connection import main
if __name__ == '__main__':
    raise SystemExit(main())

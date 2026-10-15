"""Private local asset store; replace this interface for S3 deployment."""
import os
import uuid
from pathlib import Path

ROOT = Path(os.environ.get('LIVESTOCK_STATE', '~/.local/share/idli-bridge/livestock')).expanduser()

class AssetStore:
    def __init__(self, root=None):
        self.root = Path(root or ROOT / 'assets')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    def put(self, data, media_type):
        extension = {'audio/ogg': '.ogg', 'image/jpeg': '.jpg', 'image/png': '.png'}.get(media_type, '.bin')
        key = uuid.uuid4().hex + extension
        path = self.root / key
        path.write_bytes(data)
        path.chmod(0o600)
        return {'storage_uri': key, 'media_type': media_type, 'size': len(data)}
    def get(self, key):
        if Path(key).name != key or not key:
            raise ValueError('Invalid asset')
        path = self.root / key
        if not path.is_file():
            raise FileNotFoundError(key)
        return path

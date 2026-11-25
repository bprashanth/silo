"""Tests for deployment/team/install.py and Cloudflare Access routing for embed/rerank."""
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'core'))

from deployment.team import install as team_install
from lib import muse


GOOGLE_JSON = json.dumps({
    'installed': {'client_id': 'gid-123', 'client_secret': 'gsec-456'}
}).encode()
MUSE_JSON = json.dumps({
    'url': 'https://silo.idli.cc',
    'client_id': 'cf-id-abc',
    'client_secret': 'cf-sec-xyz',
}).encode()


class TeamInstallAndRoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    def _make_tar_config(self, path: Path, prefix='creds/'):
        with tarfile.open(path, 'w:gz') as tf:
            for name, data in (('io_oauth_client_gcp.json', GOOGLE_JSON), ('muse-access.json', MUSE_JSON)):
                info = tarfile.TarInfo(name=prefix + name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))

    def _make_zip_config(self, path: Path):
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('io_oauth_client_gcp.json', GOOGLE_JSON)
            zf.writestr('muse-access.json', MUSE_JSON)

    def test_install_from_tarball_and_custom_sandbox_path(self):
        cfg_tar = self.root / 'team-cfg.tar.gz'
        self._make_tar_config(cfg_tar)
        sbx = self.root / 'my-custom-sbx'
        os.environ['XDG_CONFIG_HOME'] = str(self.root / 'xdg-cfg')
        os.environ['XDG_DATA_HOME'] = str(self.root / 'xdg-data')

        launcher = team_install.main([
            '--account', 'Tester@Example.org',
            '--config', str(cfg_tar),
            '--sandbox_path', str(sbx),
            '--skip-venv',
        ])
        self.assertTrue(launcher.is_file())
        text = launcher.read_text()
        self.assertIn(f'IDLI_SANDBOX=${{IDLI_SANDBOX:-{sbx.resolve()}}}', text)
        self.assertIn('IDLI_CHIPS=${IDLI_CHIPS:-0}', text)
        self.assertIn('IDLI_JUDGE=${IDLI_JUDGE:-nine_compressed}', text)
        self.assertTrue((self.root / 'xdg-cfg/silo/io_oauth_client_gcp.json').is_file())
        self.assertTrue((self.root / 'xdg-data/silo/config/muse-access.json').is_file())

    def test_install_from_zip_config(self):
        cfg_zip = self.root / 'team-cfg.zip'
        self._make_zip_config(cfg_zip)
        found = team_install.extract_config_bundle(cfg_zip)
        self.assertEqual(set(found), {'io_oauth_client_gcp.json', 'muse-access.json'})

    def test_rejects_path_traversal_in_config_bundle(self):
        bad_zip = self.root / 'bad.zip'
        with zipfile.ZipFile(bad_zip, 'w') as zf:
            zf.writestr('../io_oauth_client_gcp.json', GOOGLE_JSON)
            zf.writestr('muse-access.json', MUSE_JSON)
        with self.assertRaises(SystemExit):
            team_install.extract_config_bundle(bad_zip)

    def test_embed_and_rerank_use_cf_access_headers_when_muse_access_present(self):
        idli_home = self.root / 'idli-home'
        (idli_home / 'config').mkdir(parents=True)
        (idli_home / 'config/muse-access.json').write_bytes(MUSE_JSON)
        os.environ['IDLI_HOME'] = str(idli_home)
        os.environ.pop('IDLI_EMBED_URL', None)
        os.environ.pop('IDLI_RERANK_URL', None)

        ebase, ehdrs = muse.embed_upstream()
        rbase, rhdrs = muse.rerank_upstream()
        self.assertEqual(ebase, 'https://silo.idli.cc')
        self.assertEqual(rbase, 'https://silo.idli.cc')
        self.assertEqual(ehdrs.get('CF-Access-Client-Id'), 'cf-id-abc')
        self.assertEqual(rhdrs.get('CF-Access-Client-Secret'), 'cf-sec-xyz')

        # Explicit local override drops CF headers
        os.environ['IDLI_EMBED_URL'] = 'http://127.0.0.1:8293'
        ebase2, ehdrs2 = muse.embed_upstream()
        self.assertEqual(ebase2, 'http://127.0.0.1:8293')
        self.assertEqual(ehdrs2, {})


if __name__ == '__main__':
    unittest.main()

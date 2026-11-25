"""Tests for repo-local, idempotent deployment/team/install.py and CF Access routing."""
import io
import json
import os
import subprocess
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
SILO_JSON_NO_URL = json.dumps({
    'client_id': 'cf-id-abc.access',
    'client_secret': 'cf-sec-xyz',
    'model': 'idli-9b',
}).encode()


class TeamInstallAndRoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fake_repo = self.root / 'repo'
        (self.fake_repo / 'core').mkdir(parents=True)
        self.old_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    def _make_tar_config(self, path: Path, access_name='silo.json', prefix='creds/'):
        with tarfile.open(path, 'w:gz') as tf:
            for name, data in (('io_oauth_client_gcp.json', GOOGLE_JSON), (access_name, SILO_JSON_NO_URL)):
                info = tarfile.TarInfo(name=prefix + name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))

    def test_repo_local_install_idempotent_and_fails_when_account_unset(self):
        cfg_tar = self.root / 'silo-team-config.tar.gz'
        self._make_tar_config(cfg_tar)

        # 1. Install without --account -> writes repo-local .env, bin/idli, .silo/
        launcher = team_install.main([
            '--root', str(self.fake_repo),
            '--config', str(cfg_tar),
            '--skip-venv',
        ])
        self.assertEqual(launcher, self.fake_repo / 'bin' / 'idli')
        self.assertTrue((self.fake_repo / '.env').is_file())
        self.assertTrue((self.fake_repo / '.silo/config/io_oauth_client_gcp.json').is_file())
        silo_saved = json.loads((self.fake_repo / '.silo/config/silo.json').read_text())
        self.assertEqual(silo_saved['url'], 'https://silo.idli.cc')
        self.assertEqual(silo_saved['client_id'], 'cf-id-abc.access')

        # 2. Running ./bin/idli without IDLI_GOOGLE_ACCOUNT set MUST fail fast with exit code 2
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith('IDLI_')}
        proc = subprocess.run([str(launcher), 'size'], env=clean_env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('IDLI_GOOGLE_ACCOUNT is not set', proc.stderr)

        # 3. Re-running with --account and custom --sandbox_path is idempotent and updates .env cleanly
        custom_sbx = self.root / 'my-sbx'
        team_install.main([
            '--root', str(self.fake_repo),
            '--account', 'Tester@Example.org',
            '--sandbox_path', str(custom_sbx),
            '--skip-venv',
        ])
        env_vals = team_install.parse_existing_env(self.fake_repo / '.env')
        self.assertEqual(env_vals['IDLI_GOOGLE_ACCOUNT'], 'tester@example.org')
        self.assertEqual(env_vals['IDLI_SANDBOX'], str(custom_sbx.resolve()))
        self.assertEqual(env_vals['IDLI_CHIPS'], '0')
        self.assertEqual(env_vals['IDLI_JUDGE'], 'nine_compressed')

        # 4. Re-running again with NO flags preserves existing account & sandbox in .env
        team_install.main(['--root', str(self.fake_repo), '--skip-venv'])
        env_vals2 = team_install.parse_existing_env(self.fake_repo / '.env')
        self.assertEqual(env_vals2['IDLI_GOOGLE_ACCOUNT'], 'tester@example.org')
        self.assertEqual(env_vals2['IDLI_SANDBOX'], str(custom_sbx.resolve()))

    def test_zip_config_and_path_traversal_rejection(self):
        good_zip = self.root / 'good.zip'
        with zipfile.ZipFile(good_zip, 'w') as zf:
            zf.writestr('io_oauth_client_gcp.json', GOOGLE_JSON)
            zf.writestr('silo.json', SILO_JSON_NO_URL)
        g_raw, a_raw, a_name = team_install.extract_config_bundle(good_zip)
        self.assertEqual(a_name, 'silo.json')
        self.assertTrue(g_raw and a_raw)

        bad_zip = self.root / 'bad.zip'
        with zipfile.ZipFile(bad_zip, 'w') as zf:
            zf.writestr('../io_oauth_client_gcp.json', GOOGLE_JSON)
            zf.writestr('silo.json', SILO_JSON_NO_URL)
        with self.assertRaises(SystemExit):
            team_install.extract_config_bundle(bad_zip)

    def test_muse_reads_silo_json_without_url_and_sends_cf_headers(self):
        silo_home = self.root / 'silo-home'
        (silo_home / 'config').mkdir(parents=True)
        (silo_home / 'config/silo.json').write_bytes(SILO_JSON_NO_URL)
        os.environ['IDLI_HOME'] = str(silo_home)
        os.environ.pop('IDLI_EMBED_URL', None)
        os.environ.pop('IDLI_RERANK_URL', None)
        os.environ.pop('MUSE_URL', None)

        self.assertEqual(muse.base_url(), 'https://silo.idli.cc')
        ebase, ehdrs = muse.embed_upstream()
        rbase, rhdrs = muse.rerank_upstream()
        self.assertEqual(ebase, 'https://silo.idli.cc')
        self.assertEqual(rbase, 'https://silo.idli.cc')
        self.assertEqual(ehdrs.get('CF-Access-Client-Id'), 'cf-id-abc.access')
        self.assertEqual(rhdrs.get('CF-Access-Client-Secret'), 'cf-sec-xyz')

        os.environ['IDLI_EMBED_URL'] = 'http://127.0.0.1:8293'
        ebase2, ehdrs2 = muse.embed_upstream()
        self.assertEqual(ebase2, 'http://127.0.0.1:8293')
        self.assertEqual(ehdrs2, {})


if __name__ == '__main__':
    unittest.main()

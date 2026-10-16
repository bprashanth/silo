"""Telegram transport retry behavior, without network calls."""
import http.client
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
import urllib.error

spec=importlib.util.spec_from_file_location('livestock_bridge_test',Path(__file__).resolve().parents[1]/'transport.py')
bridge=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

class Delivery(unittest.TestCase):
    def test_transient_disconnect_retries(self):
        send=Mock(side_effect=[http.client.RemoteDisconnected(),{'ok':True}])
        with patch.object(bridge.time,'sleep'):
            self.assertEqual(bridge.transport_retry(send),{'ok':True})
        self.assertEqual(send.call_count,2)
    def test_permission_denied_does_not_retry(self):
        send=Mock(side_effect=urllib.error.HTTPError('redacted',403,'Forbidden',{},None))
        with patch.object(bridge.time,'sleep'):
            with self.assertRaises(urllib.error.HTTPError): bridge.transport_retry(send)
        self.assertEqual(send.call_count,1)
    def test_retry_is_bounded(self):
        send=Mock(side_effect=http.client.RemoteDisconnected())
        with patch.object(bridge.time,'sleep'):
            with self.assertRaises(http.client.RemoteDisconnected): bridge.transport_retry(send)
        self.assertEqual(send.call_count,3)

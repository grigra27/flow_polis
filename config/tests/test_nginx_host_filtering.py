"""
H-01 (docs/prod-health-audit-2026-09-24.md): nginx must drop every Host other
than polis.insflow.ru (www, bare IP, scanners) before it reaches Django.

Static checks of nginx/default.conf — the real behaviour was verified against
a throwaway nginx container on the production network (see the audit doc).
"""

import re
import unittest
from pathlib import Path

NGINX_CONFIG = Path(__file__).resolve().parent.parent.parent / "nginx" / "default.conf"


def _server_blocks(config):
    """Split top-level `server { ... }` blocks, respecting nested braces."""
    blocks = []
    for match in re.finditer(r"^server\s*\{", config, re.MULTILINE):
        depth = 0
        for i in range(match.end() - 1, len(config)):
            if config[i] == "{":
                depth += 1
            elif config[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(config[match.start() : i + 1])
                    break
    return blocks


class NginxHostFilteringTest(unittest.TestCase):
    def setUp(self):
        self.blocks = _server_blocks(NGINX_CONFIG.read_text())

    def _default_block(self, port):
        found = [
            b
            for b in self.blocks
            if re.search(rf"listen\s+{port}\b[^;]*default_server", b)
        ]
        self.assertEqual(len(found), 1, f"expected one default_server on {port}")
        return found[0]

    def test_http_default_server_drops_unknown_hosts(self):
        block = self._default_block(80)
        self.assertIn("server_name _;", block)
        self.assertRegex(block, r"location / \{\s*return 444;")

    def test_http_default_server_keeps_acme_for_www_renewal(self):
        # www.polis.insflow.ru is still in the certificate SAN.
        block = self._default_block(80)
        self.assertIn("location /.well-known/acme-challenge/", block)
        self.assertIn("root /var/www/certbot;", block)

    def test_http_default_server_keeps_docker_healthcheck(self):
        # docker-compose.prod.yml: wget http://localhost/health/ (Host: localhost)
        block = self._default_block(80)
        self.assertRegex(block, r"location = /health/ \{[^}]*return 200")

    def test_https_default_server_rejects_handshake(self):
        block = self._default_block(443)
        self.assertIn("ssl_reject_handshake on;", block)
        self.assertIn("return 444;", block)
        self.assertNotIn("proxy_pass", block)

    def test_application_served_only_for_canonical_domain(self):
        proxied = [b for b in self.blocks if "proxy_pass" in b]
        self.assertEqual(len(proxied), 1)
        self.assertRegex(proxied[0], r"server_name polis\.insflow\.ru;")
        self.assertNotIn("default_server", proxied[0])
        self.assertNotIn("www.", proxied[0])


if __name__ == "__main__":
    unittest.main()

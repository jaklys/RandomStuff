#!/usr/bin/env python3
"""Tests for chuck_remote_release.py"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.deploy.chuck_remote_release import (
    ReleaseConfig,
    discover_config_files,
    parse_config_env,
    config_file_relative,
    execute_release,
    ARTIFACT_ROOTS,
)


class TestDiscoverConfigFiles(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.recipes_dir = Path(self.temp_dir) / "Recipes" / "20230428"
        self.recipes_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_finds_matching_configs(self):
        config1 = {"env": "EMEA-PROD-A", "hostname": "host1", "versions": {}, "actions": []}
        config2 = {"env": "APAC-PROD-A", "hostname": "host2", "versions": {}, "actions": []}
        (self.recipes_dir / "FIAT~EMEA-PROD-A#CHG123.config").write_text(json.dumps(config1))
        (self.recipes_dir / "FIAT~APAC-PROD-A#CHG123.config").write_text(json.dumps(config2))
        # Different CR - should not be found
        (self.recipes_dir / "FIAT~EMEA-PROD-A#CHG999.config").write_text(json.dumps(config1))

        result = discover_config_files(self.temp_dir, "20230428", "CHG123")

        self.assertEqual(len(result), 2)
        names = {p.name for p in result}
        self.assertEqual(names, {"FIAT~EMEA-PROD-A#CHG123.config", "FIAT~APAC-PROD-A#CHG123.config"})

    def test_raises_on_missing_directory(self):
        with self.assertRaises(FileNotFoundError):
            discover_config_files(self.temp_dir, "99999999", "CHG123")

    def test_raises_on_no_matching_files(self):
        with self.assertRaises(FileNotFoundError):
            discover_config_files(self.temp_dir, "20230428", "CHG_NONEXISTENT")


class TestParseConfigEnv(unittest.TestCase):
    def test_extracts_env(self):
        with tempfile.NamedTemporaryFile(suffix=".config", mode="w", delete=False) as f:
            json.dump({"env": "EMEA-PROD-A", "hostname": "h1"}, f)
            tmp = Path(f.name)
        self.assertEqual(parse_config_env(tmp), "EMEA-PROD-A")
        tmp.unlink()

    def test_raises_on_missing_env(self):
        with tempfile.NamedTemporaryFile(suffix=".config", mode="w", delete=False) as f:
            json.dump({"hostname": "h1"}, f)
            tmp = Path(f.name)
        with self.assertRaises(ValueError):
            parse_config_env(tmp)
        tmp.unlink()


class TestConfigFileRelative(unittest.TestCase):
    def test_builds_relative_path(self):
        config = Path("tmp") / "Artifacts" / "Recipes" / "20230428" / "FIAT~ENV#CR.config"
        result = config_file_relative(config, str(Path("tmp") / "Artifacts"))
        self.assertEqual(result, str(Path("Recipes") / "20230428" / "FIAT~ENV#CR.config"))

    def test_works_with_any_prefix(self):
        config = Path("any") / "path" / "Recipes" / "20230428" / "FIAT~ENV#CR.config"
        result = config_file_relative(config, "completely/different")
        self.assertEqual(result, str(Path("Recipes") / "20230428" / "FIAT~ENV#CR.config"))


class TestExecuteRelease(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.recipes_dir = Path(self.temp_dir) / "Recipes" / "20230428"
        self.recipes_dir.mkdir(parents=True)

        config_data = {"env": "EMEA-UAT2-A", "hostname": "fiat-emeauat2-a1", "versions": {}, "actions": []}
        (self.recipes_dir / "FIAT~EMEA-UAT2-A#CHG123.config").write_text(json.dumps(config_data))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("scripts.deploy.chuck_remote_release._http_post_json")
    @patch("scripts.deploy.chuck_remote_release.get_deployment_hosts")
    def test_successful_release(self, mock_hosts, mock_http):
        mock_hosts.return_value = {"fiat-emeauat2-a1": "server1.intranet.barcapint.com"}
        mock_http.return_value = (200, {"ok": True, "duration_seconds": 120})

        cfg = ReleaseConfig(
            cr_number="CHG123",
            release_date="20230428",
            release_region="emea",
            art_root=self.temp_dir,
            chuck_working_dir="C:\\Chuck",
            agent_port=6301,
            agent_scheme="https",
            timeout_seconds=3600,
            bam_token="test-token",
        )

        result = execute_release(cfg)

        self.assertEqual(result, 0)
        mock_http.assert_called_once()
        call_args = mock_http.call_args
        self.assertIn("/release", call_args[0][0])
        payload = call_args[0][1]
        self.assertIn("config_file", payload)
        self.assertIn("art_root", payload)
        self.assertEqual(payload["art_root"], self.temp_dir)

    @patch("scripts.deploy.chuck_remote_release._http_post_json")
    @patch("scripts.deploy.chuck_remote_release.get_deployment_hosts")
    def test_failed_release(self, mock_hosts, mock_http):
        mock_hosts.return_value = {"fiat-emeauat2-a1": "server1.intranet.barcapint.com"}
        mock_http.return_value = (500, {"ok": False, "error": "chuck failed", "returncode": 1})

        cfg = ReleaseConfig(
            cr_number="CHG123",
            release_date="20230428",
            release_region="emea",
            art_root=self.temp_dir,
            chuck_working_dir="C:\\Chuck",
            agent_port=6301,
            agent_scheme="https",
            timeout_seconds=3600,
            bam_token="test-token",
        )

        result = execute_release(cfg)

        self.assertEqual(result, 1)

    @patch("scripts.deploy.chuck_remote_release.get_deployment_hosts")
    def test_skips_unknown_env(self, mock_hosts):
        mock_hosts.side_effect = ValueError("Environment key 'EMEA-UAT2-A' not found")

        cfg = ReleaseConfig(
            cr_number="CHG123",
            release_date="20230428",
            release_region="emea",
            art_root=self.temp_dir,
            chuck_working_dir="C:\\Chuck",
            agent_port=6301,
            agent_scheme="https",
            timeout_seconds=3600,
            bam_token="test-token",
        )

        # Should not raise, just skip with warning and return success (no failures)
        result = execute_release(cfg)
        self.assertEqual(result, 0)


class TestArtifactRoots(unittest.TestCase):
    def test_regions_defined(self):
        self.assertIn("apac", ARTIFACT_ROOTS)
        self.assertIn("emea", ARTIFACT_ROOTS)
        self.assertIn("dfs-apac", ARTIFACT_ROOTS["apac"])
        self.assertIn("dfs-emea", ARTIFACT_ROOTS["emea"])


if __name__ == "__main__":
    unittest.main()





def config_file_relative(config_path: Path, art_root: str) -> str:
    """Compute config_file path relative to art_root (what chuck release expects).

    Structure is always: {art_root}/Recipes/{date}/{filename}
    Result:              Recipes/{date}/{filename}
    """
    return str(Path("Recipes") / config_path.parent.name / config_path.name)
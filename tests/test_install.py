import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('install_user',Path(__file__).resolve().parents[1]/'scripts/install-user.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def test_install_preserves_profile_and_handles_spaces_and_specifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)/'example user';source=home/'RGB project%'
            profile=home/'.config/asus-rgb/profile.json'
            profile.parent.mkdir(parents=True);profile.write_text('{"mode":"static"}')
            unit=installer.install(home,source,Path('/usr/bin/python3'))
            self.assertEqual(profile.read_text(),'{"mode":"static"}')
            text=unit.read_text()
            self.assertIn('WorkingDirectory='+str(source).replace('%','%%')+'\n',text)
            self.assertIn('WantedBy=default.target',text)
            launcher=home/'.local/bin/asus-rgb'
            self.assertTrue(launcher.stat().st_mode & 0o111)
            self.assertIn(' -m asus_rgb.cli "$@"',launcher.read_text())

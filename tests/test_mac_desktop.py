"""Acciones de macOS. La lógica es portable, así que se comprueba en cualquier SO."""
import plistlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'voice-backend'))
import mac_desktop


def make_bundle(root: Path, folder_name: str, display_name: str | None) -> Path:
    bundle = root / f'{folder_name}.app'
    (bundle / 'Contents').mkdir(parents=True)
    if display_name is not None:
        with (bundle / 'Contents' / 'Info.plist').open('wb') as handle:
            plistlib.dump({'CFBundleDisplayName': display_name}, handle)
    return bundle


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_display_name_wins_over_folder_name(self):
        make_bundle(self.root, 'Music', 'Música')
        make_bundle(self.root, 'Visual Studio Code', None)  # sin Info.plist
        with mock.patch.object(mac_desktop, 'APP_DIRECTORIES', (str(self.root),)):
            found = dict(mac_desktop.discover_apps())
        self.assertIn('Música', found)
        self.assertIn('Visual Studio Code', found)
        self.assertTrue(found['Música'].endswith('Music.app'))

    def test_non_bundles_and_missing_directories_are_ignored(self):
        (self.root / 'notas.txt').write_text('x', encoding='utf-8')
        with mock.patch.object(mac_desktop, 'APP_DIRECTORIES',
                               (str(self.root), '/ruta/que/no/existe')):
            self.assertEqual(mac_desktop.discover_apps(), [])


class LaunchTests(unittest.TestCase):
    def test_every_launch_avoids_the_shell(self):
        cases = [
            (mac_desktop.launch, ('/Applications/Music.app',),
             ['open', '-a', '/Applications/Music.app']),
            (mac_desktop.open_file_with, ('/Applications/Code.app', '/Users/w/Desktop/sitio'),
             ['open', '-a', '/Applications/Code.app', '/Users/w/Desktop/sitio']),
            (mac_desktop.open_path, ('/Users/w/Desktop/a.html',),
             ['open', '/Users/w/Desktop/a.html']),
            (mac_desktop.open_deep_link, ('musics://music.apple.com/x',),
             ['open', 'musics://music.apple.com/x']),
        ]
        for function, args, expected in cases:
            with self.subTest(function=function.__name__):
                with mock.patch.object(mac_desktop.subprocess, 'Popen') as popen:
                    function(*args)
                self.assertEqual(popen.call_args.args[0], expected)
                self.assertIs(popen.call_args.kwargs['shell'], False)


class AppleScriptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []

        async def fake(script, *args, timeout_s=mac_desktop.OSASCRIPT_TIMEOUT_S):
            self.calls.append((script, args))
            return self.result

        self.result = (0, 'OK: Reproducir')
        patcher = mock.patch.object(mac_desktop, '_osascript', fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_control_name_travels_as_argument_not_as_script_text(self):
        ok, detail, available = await mac_desktop.click_control('Music', ['Reproducir', 'Play'])
        script, args = self.calls[0]
        self.assertTrue(ok)
        self.assertEqual(detail, 'Reproducir')
        self.assertEqual(args, ('Music', 'Reproducir', 'Play'))
        # Nada del texto pedido se interpola en el script.
        self.assertNotIn('Reproducir', script)

    async def test_missing_control_returns_the_real_names(self):
        self.result = (0, 'NOTFOUND: Aleatorio, Descargar')
        ok, _, available = await mac_desktop.click_control('Music', ['Reproducir'])
        self.assertFalse(ok)
        self.assertEqual(available, ['Aleatorio', 'Descargar'])

    async def test_accessibility_denial_is_explained(self):
        self.result = (1, 'System Events got an error: osascript is not allowed assistive access.')
        ok, detail, _ = await mac_desktop.click_control('Music', ['Reproducir'])
        self.assertFalse(ok)
        self.assertIn('Accesibilidad', detail)

    async def test_plain_key_uses_a_key_code(self):
        self.result = (0, '')
        await mac_desktop.press_key('enter')
        _, args = self.calls[0]
        self.assertEqual(args, ('36',))

    async def test_ctrl_shortcut_becomes_command_on_macos(self):
        self.result = (0, '')
        await mac_desktop.press_key('ctrl+c')
        _, args = self.calls[0]
        self.assertEqual(args, ('c', 'command down'))

    async def test_media_control_talks_to_music_directly(self):
        self.result = (0, '')
        self.assertTrue(await mac_desktop.media_control('pausar'))
        script, _ = self.calls[0]
        self.assertIn('pause', script)
        self.assertFalse(await mac_desktop.media_control('formatear'))


if __name__ == '__main__':
    unittest.main()

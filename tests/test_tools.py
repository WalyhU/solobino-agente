import asyncio
from pathlib import Path
import shutil
import tempfile
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'voice-backend'))

with mock.patch.dict(sys.modules, {'pyautogui': mock.MagicMock()}):
    import agentic_control
    import music_search
    import tools
    import ui_automation
    from tools import ToolError, ToolRunner, validate


class AppResolutionTests(unittest.TestCase):
    """El nombre del modelo solo selecciona una entrada ya descubierta en el PC."""

    def setUp(self):
        self.entry = agentic_control.AppEntry('Calculadora', 'appid', 'App!Calc', True)
        patcher = mock.patch.object(tools, 'app_index', autospec=True)
        self.index = patcher.start()
        self.addCleanup(patcher.stop)
        self.index.suggestions.return_value = ['Calculadora', 'Google Chrome']

    def test_unknown_app_is_rejected_with_suggestions(self):
        self.index.resolve.return_value = None
        with self.assertRaisesRegex(ToolError, 'Google Chrome'):
            validate('open_application', {'app_name': 'notepad & echo owned'})

    def test_resolved_entry_replaces_the_model_text(self):
        self.index.resolve.return_value = self.entry
        result = validate('open_application', {'app_name': ' calculadora '})
        self.index.resolve.assert_called_once_with('calculadora')
        self.assertEqual(result, {'entry': self.entry})

    def test_unknown_tool_and_bad_arguments(self):
        with self.assertRaises(ToolError):
            validate('delete_everything', {})
        with self.assertRaises(ToolError):
            validate('type_text', 'no soy un objeto')
        with self.assertRaises(ToolError):
            validate('type_text', {'text': '   '})
        with self.assertRaises(ToolError):
            validate('type_text', {'text': 'x' * (tools.MAX_TEXT_CHARS + 1)})

    def test_url_scheme_is_enforced(self):
        with self.assertRaises(ToolError):
            validate('open_url', {'url': 'file:///C:/Windows/System32'})
        with self.assertRaises(ToolError):
            validate('open_url', {'url': 'javascript:alert(1)'})
        self.assertEqual(validate('open_url', {'url': 'https://ollama.com'}),
                         {'url': 'https://ollama.com'})

    def test_only_allowlisted_keys(self):
        with self.assertRaises(ToolError):
            validate('press_key', {'key': 'ctrl+alt+delete'})
        self.assertEqual(validate('press_key', {'key': 'CTRL + C'}), {'key': 'ctrl+c'})


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_arguments_never_reach_the_controller(self):
        controller = mock.Mock(spec=agentic_control.PCController)
        with mock.patch.object(tools.app_index, 'resolve', return_value=None),              mock.patch.object(tools.app_index, 'suggestions', return_value=['Calculadora']):
            result = await ToolRunner(controller).run('open_application', {'app_name': 'rm -rf'})
        self.assertTrue(result.startswith('Error:'))
        controller.execute_command.assert_not_called()

    async def test_controller_failure_becomes_text_for_the_model(self):
        entry = agentic_control.AppEntry('Spotify', 'path', r'C:\spotify.exe', True)
        controller = mock.Mock(spec=agentic_control.PCController)
        controller.execute_command.side_effect = FileNotFoundError('no instalada')
        with mock.patch.object(tools.app_index, 'resolve', return_value=entry):
            result = await ToolRunner(controller).run('open_application', {'app_name': 'spotify'})
        self.assertIn('FileNotFoundError', result)

    async def test_successful_call_forwards_the_indexed_entry(self):
        entry = agentic_control.AppEntry('Calculadora', 'appid', 'App!Calc', True)
        controller = mock.Mock(spec=agentic_control.PCController)
        controller.execute_command.return_value = 'Abrí Calculadora.'
        with mock.patch.object(tools.app_index, 'resolve', return_value=entry):
            result = await ToolRunner(controller).run('open_application', {'app_name': 'calculadora'})
        controller.execute_command.assert_called_once_with('open_application', {'entry': entry})
        self.assertEqual(result, 'Abrí Calculadora.')


class ControllerTests(unittest.TestCase):
    def test_start_menu_app_is_launched_without_a_shell(self):
        entry = agentic_control.AppEntry(
            'Calculadora', 'appid', 'Microsoft.WindowsCalculator_8wekyb3d8bbwe!App', True)
        with mock.patch.object(agentic_control, 'pyautogui', mock.MagicMock()), \
             mock.patch.object(agentic_control.os, 'name', 'nt'), \
             mock.patch.object(agentic_control.subprocess, 'Popen') as popen:
            agentic_control.PCController().execute_command(
                'open_application', {'entry': entry})
        args, kwargs = popen.call_args
        self.assertEqual(args[0],
                         ['explorer.exe', 'shell:AppsFolder' + chr(92) + entry.target])
        self.assertIs(kwargs['shell'], False)

    def test_executable_entry_uses_startfile(self):
        entry = agentic_control.AppEntry('Code', 'path', 'E:\\code.cmd', False)
        with mock.patch.object(agentic_control, 'pyautogui', mock.MagicMock()), \
             mock.patch.object(agentic_control.os, 'name', 'nt'), \
             mock.patch.object(agentic_control.os, 'startfile', create=True) as startfile:
            agentic_control.PCController().execute_command(
                'open_application', {'entry': entry})
        startfile.assert_called_once_with(entry.target)


class MusicAndUiValidationTests(unittest.TestCase):
    def test_music_scope_is_constrained(self):
        with self.assertRaises(ToolError):
            validate('play_music', {'query': 'Bruno Mars', 'scope': 'todo'})
        self.assertEqual(validate('play_music', {'query': ' Bruno Mars ', 'scope': 'LATEST_ALBUM'}),
                         {'query': 'Bruno Mars', 'scope': 'latest_album'})

    def test_media_action_is_constrained(self):
        with self.assertRaises(ToolError):
            validate('media_control', {'action': 'formatear disco'})
        self.assertEqual(validate('media_control', {'action': 'Pausar'}), {'action': 'pausar'})

    def test_control_name_is_bounded(self):
        with self.assertRaises(ToolError):
            validate('click_in_app', {'app_name': 'Word', 'control_name': 'x' * 61})
        self.assertEqual(validate('click_in_app', {'app_name': ' Word ', 'control_name': 'Guardar'}),
                         {'app_name': 'Word', 'control_name': 'Guardar'})


class MusicPlaybackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.release = music_search.Release(
            label='The Romantic', artist='Bruno Mars', release_date='2026-02-27',
            web_url='https://music.apple.com/gt/album/the-romantic/1866732792')
        self.controller = mock.Mock(spec=agentic_control.PCController)
        self.runner = ToolRunner(self.controller, http=mock.Mock())

    async def test_album_is_opened_in_the_app_and_played(self):
        clicked = ui_automation.ClickResult(True, 'Reproducir', [])
        with mock.patch.object(tools, 'find_release', return_value=self.release),              mock.patch.object(ui_automation, 'click_control', return_value=clicked) as click:
            result = await self.runner.run('play_music', {'query': 'Bruno Mars',
                                                          'scope': 'latest_album'})
        self.controller.open_deep_link.assert_called_once_with(self.release.app_url)
        self.assertTrue(self.release.app_url.startswith('musics://'))
        self.assertEqual(click.call_args.args[0], 'AppleMusic')
        self.assertIn('Reproduciendo', result)
        self.assertIn('The Romantic', result)

    async def test_unknown_release_is_reported_without_opening_anything(self):
        with mock.patch.object(tools, 'find_release', return_value=None):
            result = await self.runner.run('play_music', {'query': 'zzz', 'scope': 'album'})
        self.controller.open_deep_link.assert_not_called()
        self.assertTrue(result.startswith('Error:'))

    async def test_play_button_missing_is_reported_honestly(self):
        clicked = ui_automation.ClickResult(False, 'no encontre ese control', ['Aleatorio'])
        with mock.patch.object(tools, 'find_release', return_value=self.release),              mock.patch.object(ui_automation, 'click_control', return_value=clicked):
            result = await self.runner.run('play_music', {'query': 'Bruno Mars',
                                                          'scope': 'latest_album'})
        self.assertIn('no pude darle a reproducir', result)

    async def test_media_control_falls_back_to_the_media_key(self):
        clicked = ui_automation.ClickResult(False, 'la aplicacion no tiene una ventana abierta', [])
        with mock.patch.object(ui_automation, 'click_control', return_value=clicked):
            result = await self.runner.run('media_control', {'action': 'siguiente'})
        self.controller.press_media_key.assert_called_once_with('nexttrack')
        self.assertIn('tecla multimedia', result)

    async def test_click_in_app_lists_real_controls_when_missing(self):
        clicked = ui_automation.ClickResult(False, 'no encontre ese control',
                                            ['Guardar', 'Cancelar'])
        with mock.patch.object(ui_automation, 'click_control', return_value=clicked):
            result = await self.runner.run('click_in_app', {'app_name': 'Word',
                                                            'control_name': 'Publicar'})
        self.assertIn('Guardar, Cancelar', result)



class OpenWithTests(unittest.IsolatedAsyncioTestCase):
    """Una orden = una ventana, y con la aplicación pedida."""

    def setUp(self):
        self.controller = mock.Mock(spec=agentic_control.PCController)
        self.runner = ToolRunner(self.controller, http=mock.Mock())
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.file = self.folder / 'index.html'
        self.file.write_text('<h1>x</h1>', encoding='utf-8')

    async def test_folder_is_opened_with_the_editor_executable(self):
        entry = agentic_control.AppEntry('Visual Studio Code', 'appid',
                                         'Microsoft.VisualStudioCode', True,
                                         'E:/Programs/Code.exe')
        with mock.patch.object(tools.app_index, 'resolve', return_value=entry):
            result = await self.runner.run('open_file_with',
                                           {'app_name': 'vscode', 'path': str(self.folder)})
        self.controller.open_file_with.assert_called_once_with(entry, str(self.folder))
        self.controller.open_path.assert_not_called()
        self.assertIn('carpeta', result)

    async def test_app_without_executable_is_refused_instead_of_opening_twice(self):
        entry = agentic_control.AppEntry('Calculadora', 'appid', 'App!Calc', True, None)
        with mock.patch.object(tools.app_index, 'resolve', return_value=entry):
            result = await self.runner.run('open_file_with',
                                           {'app_name': 'calculadora', 'path': str(self.file)})
        self.controller.open_file_with.assert_not_called()
        self.controller.open_path.assert_not_called()
        self.assertIn('open_path', result)

    async def test_open_path_uses_the_default_program(self):
        result = await self.runner.run('open_path', {'path': str(self.file)})
        self.controller.open_path.assert_called_once_with(str(self.file))
        self.assertIn('index.html', result)

    async def test_missing_path_is_rejected(self):
        result = await self.runner.run('open_path', {'path': str(self.folder / 'no.html')})
        self.controller.open_path.assert_not_called()
        self.assertTrue(result.startswith('Error:'))


class ControllerOpenTests(unittest.TestCase):
    def test_single_process_is_started_with_the_path_as_argument(self):
        entry = agentic_control.AppEntry('Visual Studio Code', 'appid',
                                         'Microsoft.VisualStudioCode', True,
                                         'E:/Programs/Code.exe')
        with mock.patch.object(agentic_control, 'pyautogui', mock.MagicMock()),              mock.patch.object(agentic_control.os, 'name', 'nt'),              mock.patch.object(agentic_control.os, 'startfile', create=True) as startfile,              mock.patch.object(agentic_control.subprocess, 'Popen') as popen:
            agentic_control.PCController().open_file_with(entry, 'C:/Users/x/Desktop/sitio')
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ['E:/Programs/Code.exe', 'C:/Users/x/Desktop/sitio'])
        # Ni AppID ni programa predeterminado: eso abría una segunda ventana.
        startfile.assert_not_called()



if __name__ == '__main__':
    unittest.main()

"""Desktop settings migration and recording constraints, without real I/O."""
import json
import unittest
from unittest.mock import Mock, patch
from dictate import config, settings_window, apitest
from dictate.app import DictateApp
from dictate.prozor_akcije import ProzorAkcije


class CompactDesktop(unittest.TestCase):
    def load(self, saved):
        path = Mock()
        path.exists.return_value = True
        path.read_text.return_value = json.dumps(saved)
        with patch.object(config, 'CONFIG_PATH', path):
            return config.load()

    def test_existing_preferences_cannot_reenable_removed_features(self):
        cfg = self.load(dict(mode='hold', continuous=False,
                             continuous_max_seconds=3600, gemini_live_max_seconds=120,
                             live_preview=False, gemini_live_insert=True,
                             live_diagnostics=True, utisaj_zvuk=True,
                             pauziraj_plejer=True, save_clipboard=True,
                             rezervni_snimak=True, polish_paragraphs=True,
                             polish_bullets=True, polish_dedupe=True, text_style='written',
                             groq_api_key='test', openai_api_key='test'))
        self.assertEqual(cfg['transcription_provider'], 'gemini_live')
        self.assertEqual(cfg['mode'], 'toggle')
        self.assertTrue(cfg['continuous'])
        self.assertTrue(cfg['live_preview'])
        for key in ('gemini_live_insert', 'live_diagnostics', 'utisaj_zvuk',
                    'pauziraj_plejer', 'save_clipboard', 'rezervni_snimak'):
            self.assertFalse(cfg[key], key)
        self.assertFalse(config.ai_obrada(cfg))
        self.assertNotIn('groq_api_key', cfg)
        self.assertNotIn('openai_api_key', cfg)

    def test_both_services_stop_at_ten_minutes(self):
        for provider in ('google', 'gemini_live'):
            app = DictateApp.__new__(DictateApp)
            app.cfg = self.load(dict(compact_desktop_v1=True,
                                     transcription_provider=provider))
            self.assertEqual(app._limit_seconds(), 600)
            # Oba servisa prikazuju prepis u okviru i lepe ga tek na Stop.
            self.assertTrue(app.cfg['live_preview'])

    def test_explicit_google_choice_survives_restart(self):
        cfg = self.load(dict(compact_desktop_v1=True, transcription_provider='google'))
        self.assertEqual(cfg['transcription_provider'], 'google')
        self.assertTrue(cfg['live_preview'])
        self.assertEqual(set(settings_window.PROVIDER_TITLES), {'google', 'gemini_live'})

    def test_escape_clears_every_kind_of_mouse_binding(self):
        app = DictateApp.__new__(DictateApp)
        app.cfg = dict(mouse_button=3, mouse_key_vk=79, mouse_swipe='back')
        app.listener = Mock()
        app._mouse_learning = True
        with patch.object(config, 'save'):
            ProzorAkcije._dugme_misa_snimljeno(app, None, None)
        self.assertFalse(app._mouse_learning)
        app.listener.iskljuci_dugme.assert_called_once()
        for key in ('mouse_button', 'mouse_key_vk', 'mouse_swipe'):
            self.assertIsNone(app.cfg[key])
        self.assertEqual(settings_window.mouse_button_title(app.cfg), 'Record mouse button')

    def test_key_check_only_contacts_gemini(self):
        with patch.object(apitest, '_get', return_value={'models': []}) as get:
            self.assertEqual(apitest.check_gemini({'polish_api_key': 'test'}),
                             'Gemini: API key works')
        get.assert_called_once()
        self.assertTrue(get.call_args.args[0].startswith('https://generativelanguage.googleapis.com/'))


class SettingsLayout(unittest.TestCase):
    def test_compact_window_builds_for_both_services(self):
        import AppKit
        from types import SimpleNamespace
        AppKit.NSApplication.sharedApplication()
        for provider in ('google', 'gemini_live'):
            cfg = config.desktop_policy(dict(config.DEFAULTS))
            cfg['transcription_provider'] = provider
            config.desktop_policy(cfg)
            app = SimpleNamespace(
                cfg=cfg, upis=SimpleNamespace(istorija=lambda: [f"Test dictation {i}" for i in range(10)]),
                _recorded_seconds=lambda: 0, mis_status='', _recorder=None,
                _starting=False, _azur_status='',
                azur_dugme_stanje=lambda: ('Check for updates', False),
            )
            with patch.object(settings_window.audio, 'refresh_devices'), \
                 patch.object(settings_window.audio, 'input_devices', return_value=[]), \
                 patch.object(settings_window.audio, 'microphone_granted', return_value=True), \
                 patch.object(settings_window.hotkey, 'accessibility_granted', return_value=True):
                ui = settings_window.SettingsWindow(app)
                ui.pripremi()
                self.assertEqual(len(ui.pages), 1)
                self.assertLess(ui.WIDTH, 280)
                self.assertLess(ui.document.bounds().size.height, 700)
                self.assertEqual(ui.window.title(), 'Speech to Text')
                self.assertEqual(set(ui.controls), {
                    'input_device',
                    'transcription_provider', 'polish_api_key',
                    'lowercase', 'ascii_diacritics',
                    'abbreviations', 'start_at_login',
                })
                self.assertEqual(ui.api_key_row.isHidden(), provider == 'google')
                self.assertEqual(ui.mouse_button.title(), 'Record mouse button')
                first_rows = [row.view for row in ui.pages[0].rows[:4]]
                self.assertEqual([str(view.identifier()) for view in first_rows],
                                 ['lowercase', 'ascii_diacritics',
                                  'abbreviations', 'start_at_login'])
                self.assertFalse(ui.history_scroll.hasVerticalScroller())
                first = ui.history_buttons[0].frame()
                self.assertEqual(first.origin.x, settings_window.HISTORY_PADDING)
                self.assertEqual(first.origin.y, settings_window.HISTORY_PADDING)
                self.assertGreater(ui.history_document.frame().size.height,
                                   ui.history_scroll.contentSize().height)
                self.assertTrue(ui.mouse_button.isBordered())
                self.assertEqual(ui.mouse_button.cell().alignment(), AppKit.NSTextAlignmentLeft)
                for control in (ui.mouse_button, ui.history_buttons[0]):
                    paragraph = control.attributedTitle().attribute_atIndex_effectiveRange_(
                        AppKit.NSParagraphStyleAttributeName, 0, None)[0]
                    self.assertEqual(paragraph.alignment(), AppKit.NSTextAlignmentLeft)
                mouse_style = ui.mouse_button.attributedTitle().attribute_atIndex_effectiveRange_(
                    AppKit.NSParagraphStyleAttributeName, 0, None)[0]
                self.assertGreater(mouse_style.firstLineHeadIndent(), 0)
                self.assertGreater(ui.mouse_button.bounds().size.width, 160)
                self.assertNotIn("w", settings_window._Prozor.PRECICE)
                self.assertFalse(hasattr(ui.delegate, "aplikacijaNijeAktivna_"))
                self.assertTrue(bool(
                    ui.window.styleMask() & AppKit.NSWindowStyleMaskClosable
                ))
                ids = [str(row.view.identifier() or "") for row in ui.pages[0].rows
                       if row.view is not None]
                self.assertNotIn("mouse_learn", ids)
                self.assertIs(ui.pages[0].rows[-1].view, ui.mouse_button.superview())
                self.assertIs(ui.mouse_button.superview(), ui.quit_button.superview())
                self.assertLess(
                    ui.mouse_button.frame().origin.x,
                    ui.quit_button.frame().origin.x,
                )
                self.assertGreater(
                    ui.mouse_button.superview().frame().origin.y,
                    ui.controls["input_device"].frame().origin.y,
                )
                self.assertGreater(
                    ui.mouse_button.frame().size.width,
                    ui.quit_button.frame().size.width,
                )
                self.assertNotIn("update", ids)
                self.assertIsNone(getattr(ui, "version_label", None))
                ui.window.close()


class IndependentRulesAndKeyCheck(unittest.TestCase):
    def test_section_is_always_on_and_grave_is_off(self):
        cfg = config.desktop_policy(dict(config.DEFAULTS, hotkey_section=False,
                                         hotkey_grave=True, samo_zarezi=True))
        self.assertTrue(cfg['hotkey_section'])
        self.assertFalse(cfg['hotkey_grave'])
        self.assertFalse(cfg['samo_zarezi'])

    def test_punctuation_changes_no_other_rule(self):
        import AppKit
        app = DictateApp.__new__(DictateApp)
        app.cfg = dict(lowercase=True, ascii_diacritics=True, abbreviations=False)
        app._settings_window_ui = None
        sender = Mock()
        sender.identifier.return_value = 'strip_punctuation'
        for enabled in (True, False):
            sender.state.return_value = (AppKit.NSControlStateValueOn if enabled
                                         else AppKit.NSControlStateValueOff)
            with patch.object(config, 'save'):
                app.settingsCheckbox_(sender)
            self.assertEqual(app.cfg['strip_punctuation'], enabled)
            self.assertFalse(app.cfg['samo_zarezi'])
            self.assertTrue(app.cfg['lowercase'])
            self.assertTrue(app.cfg['ascii_diacritics'])
            self.assertFalse(app.cfg['abbreviations'])

    def test_mouse_key_is_identified_as_mouse(self):
        self.assertEqual(settings_window.mouse_button_title({'mouse_key_vk': 79}),
                         'Mouse: F18')

    def test_old_key_response_cannot_override_new_key_result(self):
        from types import SimpleNamespace
        app = DictateApp.__new__(DictateApp)
        app.cfg = {'polish_api_key': 'old-test-key'}
        app._settings_window_ui = None
        app._procitaj_kljuceve_iz_polja = lambda: None
        app._api_check_running = False
        app._api_check_result = None
        work = []
        def thread(target, daemon):
            return SimpleNamespace(start=lambda: work.append(target))
        def check(cfg):
            return ('Gemini: API key works' if cfg['polish_api_key'] == 'new-test-key'
                    else 'Gemini: HTTP 403')
        with patch('dictate.prozor_akcije.threading.Thread', side_effect=thread), \
             patch.object(apitest, 'check_gemini', side_effect=check):
            app._check_api_keys(None)
            app.cfg['polish_api_key'] = 'new-test-key'
            app._check_api_keys(None)
            work[1]()
            app._consume_api_check()
            work[0]()
            app._consume_api_check()
        self.assertEqual(app._api_check_status, 'Gemini: API key works')
        self.assertFalse(app._api_check_running)


class MenuWhileRecording(unittest.TestCase):
    def test_status_click_only_toggles_settings_even_during_start_or_recording(self):
        from dictate.app import _StatusClickDelegate
        for recording, starting in ((None, 0), (Mock(), 0), (None, 1)):
            app = Mock()
            app._recorder = recording
            app._starting = starting
            delegate = _StatusClickDelegate.alloc().initWithApp_(app)
            delegate.clicked_(None)
            app._toggle_settings.assert_called_once_with()
            app._stop_from_menu.assert_not_called()
            app._on_stop.assert_not_called()
            self.assertIs(app._recorder, recording)


class NoMenuBarCounter(unittest.TestCase):
    def test_status_item_is_hidden(self):
        app = DictateApp.__new__(DictateApp)
        item = Mock()
        app._nsapp = Mock(nsstatusitem=item)
        app._status_click_set = False
        app._configure_status_click()
        item.setVisible_.assert_called_once_with(False)
        self.assertTrue(app._status_click_set)

    def test_old_recording_timer_preference_cannot_restore_counter(self):
        cfg = config.desktop_policy(dict(config.DEFAULTS, show_overlay=True))
        self.assertFalse(cfg['show_overlay'])


class AutomaticUpdates(unittest.TestCase):
    def test_update_waits_for_audio_and_pending_text_and_attempts_each_release_once(self):
        import time
        from types import SimpleNamespace
        app = DictateApp.__new__(DictateApp)
        app.cfg = {'update_check': True}
        app._azur_restart = False
        app._azur_radi = False
        app._azur_proveren_u = time.time()
        app._azur_izdanje = SimpleNamespace(oznaka='test-release')
        app.azur_dostupno = lambda: True
        app._azur_klik = Mock()
        app._starting = False
        app.upis = Mock()
        app.upis.na_cekanju.return_value = 0
        app._recorder = Mock()
        app._tick_azuriranje()
        app._azur_klik.assert_not_called()
        app._recorder = None
        app.upis.na_cekanju.return_value = 1
        app._tick_azuriranje()
        app._azur_klik.assert_not_called()
        app.upis.na_cekanju.return_value = 0
        app._tick_azuriranje()
        app._tick_azuriranje()
        app._azur_klik.assert_called_once_with()

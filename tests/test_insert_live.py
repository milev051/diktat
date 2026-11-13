"""Privremeni tekst menja samo sopstveni rep, pa potvrda ne duplira reci."""

import unittest
from unittest.mock import patch

from dictate import insert


class LiveField(unittest.TestCase):
    def setUp(self):
        target = patch.object(insert, "_agent_desk_active", return_value=False)
        target.start()
        self.addCleanup(target.stop)

    def tearDown(self):
        insert._live_field = None
        insert._live_preview_blocked = False
        insert._zadrzi_prikaz = False

    def test_revizija_i_potvrda_u_istom_polju(self):
        element = object()
        field = {"value": "Početak: "}

        def set_value(_element, value):
            field["value"] = value
            return True

        with patch.object(insert, "_focused_plain_field", return_value=element), \
             patch.object(insert, "_ax_value", side_effect=lambda _: field["value"]), \
             patch.object(insert, "_ax_set", side_effect=set_value):
            self.assertTrue(insert.preview_live("zdrav"))
            self.assertTrue(insert.preview_live("zdravo"))
            insert.insert_live("Zdravo ")
            insert.finish_live()
        self.assertEqual(field["value"], "Početak: Zdravo ")

    def test_rucna_izmena_ispred_privremenog_repa_ostaje(self):
        self.assertEqual(
            insert._replace_live_suffix("Ispravljeno zdravo", "zdravo", "Zdravo "),
            "Ispravljeno Zdravo ",
        )
        self.assertIsNone(insert._replace_live_suffix("zdravo!", "zdravo", "Zdravo "))

    def test_stop_ne_brise_vec_vidjen_rep(self):
        element = object()
        field = {"value": "Početak: zdravo"}
        insert._live_field = (element, "zdravo")
        insert.zadrzi_prikaz()
        with patch.object(insert, "_ax_value", side_effect=lambda _: field["value"]), \
             patch.object(insert, "_ax_set", side_effect=lambda _e, value: field.update(value=value) or True):
            insert.finish_live()
        self.assertEqual(field["value"], "Početak: zdravo")
        self.assertFalse(insert.ima_prikaz())

    def test_ostatak_ne_duplira_i_cuva_prikaz_ako_tok_padne(self):
        self.assertEqual(insert.ostatak_prepisa("danas je", "danas je lep"), "lep")
        self.assertEqual(insert.ostatak_prepisa("danas je lep", ""), "")
        self.assertEqual(insert.ostatak_prepisa("danas je lep", "danas je"), "")
        self.assertEqual(insert.ostatak_prepisa("", "danas je"), "danas je")
        self.assertEqual(insert.ostatak_prepisa("danas je lepo", "Danas je lepo."), "")
        self.assertEqual(insert.ostatak_prepisa("danas je lep", "danas je lepo"), "")

    def test_rucno_izmenjen_privremeni_rep_se_ne_duplira(self):
        element = object()
        insert._live_field = (element, "zdravo")
        with patch.object(insert, "_focused_plain_field", return_value=element), \
             patch.object(insert, "_ax_value", return_value="zdravo!"), \
             patch.object(insert, "_type_unicode") as type_text:
            insert.insert_live("Zdravo ")
            type_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class AgentDeskInput(unittest.TestCase):
    def setUp(self):
        target = patch.object(insert, "_input_snapshot", return_value=None)
        target.start()
        self.addCleanup(target.stop)

    def test_aktivni_bundle_se_prepoznaje(self):
        with patch.object(insert.AppKit, "NSWorkspace") as workspace:
            app = workspace.sharedWorkspace.return_value.frontmostApplication.return_value
            app.bundleIdentifier.return_value = "local.agent-desk.launcher"
            self.assertTrue(insert._agent_desk_active())
            app.bundleIdentifier.return_value = "com.apple.TextEdit"
            self.assertFalse(insert._agent_desk_active())

    def test_auto_u_agent_desku_koristi_sistemsko_lepljenje(self):
        with patch.object(insert, "_agent_desk_active", return_value=True), \
             patch.object(insert, "_paste") as paste, \
             patch.object(insert, "_type_unicode") as type_text:
            insert.insert("tekst za Agent Desk", restore_clipboard=False)
            paste.assert_called_once_with("tekst za Agent Desk", restore_clipboard=False)
            type_text.assert_not_called()

    def test_ostale_aplikacije_zadrzavaju_obican_upis(self):
        with patch.object(insert, "_agent_desk_active", return_value=False), \
             patch.object(insert, "_paste") as paste, \
             patch.object(insert, "_type_unicode") as type_text:
            insert.insert("običan tekst")
            type_text.assert_called_once_with("običan tekst")
            paste.assert_not_called()

    def test_clipboard_only_ne_lepi_ni_u_agent_desku(self):
        with patch.object(insert, "_agent_desk_active", return_value=True), \
             patch.object(insert, "set_clipboard") as copy, \
             patch.object(insert, "_paste") as paste:
            insert.insert("samo kopija", method="clipboard_only")
            copy.assert_called_once_with("samo kopija")
            paste.assert_not_called()

    def test_agent_desk_ne_dobija_privremene_ax_izmene(self):
        with patch.object(insert, "_agent_desk_active", return_value=True), \
             patch.object(insert.AX, "AXUIElementCreateSystemWide") as root:
            self.assertIsNone(insert._focused_plain_field())
            root.assert_not_called()

    def test_live_potvrda_ide_preko_paste_bez_pomeranja_kursora(self):
        with patch.object(insert, "_agent_desk_active", return_value=True), \
             patch.object(insert, "_paste") as paste, \
             patch.object(insert, "_type_unicode") as type_text:
            insert.insert_live("potvrđen tekst ")
            paste.assert_called_once_with("potvrđen tekst ")
            type_text.assert_not_called()


class Delivery(unittest.TestCase):
    def test_necitljiv_ax_ne_sprecava_lepljenje_i_ne_kopira_rezervu(self):
        from unittest.mock import Mock
        action = Mock()
        with patch.object(insert, "_input_snapshot", return_value=None), \
             patch.object(insert, "set_clipboard") as copy:
            self.assertTrue(insert._deliver("tekst", action))
        action.assert_called_once_with()
        copy.assert_not_called()

    def test_zakasnela_ax_potvrda_ne_pravi_drugi_unos(self):
        from unittest.mock import Mock
        action = Mock()
        with patch.object(insert, "_input_snapshot", return_value=(object(), "pre")), \
             patch.object(insert, "_remaining", side_effect=["tekst", ""]), \
             patch.object(insert.time, "sleep"), \
             patch.object(insert, "set_clipboard") as copy:
            self.assertTrue(insert._deliver("tekst", action))
        action.assert_called_once_with()
        copy.assert_not_called()

    def test_neuspeh_ne_puni_clipboard(self):
        from unittest.mock import Mock
        action = Mock()
        with patch.object(insert, "_input_snapshot", return_value=(object(), "pre")), \
             patch.object(insert, "_remaining", return_value="tekst"), \
             patch.object(insert.time, "monotonic", side_effect=[0, 1]), \
             patch.object(insert, "set_clipboard") as copy:
            self.assertFalse(insert._deliver("tekst", action))
        action.assert_called_once_with()
        copy.assert_not_called()

    def test_zasticeno_polje_ne_prima_diktat(self):
        from unittest.mock import Mock
        action = Mock()
        with patch.object(insert, "_input_snapshot", return_value=insert._SECURE_INPUT):
            self.assertFalse(insert._deliver("tekst", action))
        action.assert_not_called()

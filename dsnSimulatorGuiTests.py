"""Tkinter integration checks. Requires working Tk; no hardware verification."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from dsnSimulator import SimulatorWindow


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = SimulatorWindow(self.root)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/"gui-recording.jsonl"

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def test_start_pause_stale_resume_stop(self):
        self.app.start_button.invoke()
        self.app.model.generate(100); self.app.model.publish()
        self.app.pause.set(True); self.app.pause_input()
        self.app.model.last_live_publication -= 200_000_000
        self.app.refresh()
        self.assertIn("STALE",self.app.fields["Status / validity"].get())
        self.app.pause.set(False);self.app.pause_input()
        self.app.model.generate(12);self.app.model.publish();self.app.refresh()
        self.assertIn("VALID",self.app.fields["Status / validity"].get())
        self.app.stop()
        self.assertFalse(self.app.model.running)

    def test_record_open_play_pause_stop_controls(self):
        self.app.start()
        with patch('dsnSimulator.filedialog.asksaveasfilename',return_value=str(self.path)):
            self.app.file_buttons['Start Recording…'].invoke()
        expected=[]
        for code in (0,150,255):
            self.app.model.generate(code);expected.append(self.app.model.publish())
        self.app.file_buttons['Stop Recording'].invoke();self.app.stop()
        with patch('dsnSimulator.filedialog.askopenfilename',return_value=str(self.path)):
            self.app.file_buttons['Open Recording…'].invoke()
        self.assertEqual(self.app.mode.get(),'Replay')
        self.app.file_buttons['Play'].invoke()
        self.assertEqual(self.app.model.replay_next(),expected[0])
        self.app.file_buttons['Pause Replay'].invoke()
        self.assertTrue(self.app.model.replay_paused)
        self.app.file_buttons['Play'].invoke()
        self.assertEqual(self.app.model.replay_next(),expected[1])
        self.app.refresh()
        self.assertIn('REPLAY',self.app.fields['Mode / source'].get())
        self.assertIn('N/A in Replay',self.app.fields['Sample age'].get())
        self.app.file_buttons['Stop Replay'].invoke()
        self.assertFalse(self.app.model.running)

    def test_mode_slider_and_unavailable_hardware(self):
        self.app.value.set(255);self.app.slider_changed()
        self.assertIn('255',self.app.slider_label.cget('text'))
        self.app.start();self.app.refresh()
        self.assertTrue(all(b.instate(['disabled']) for b in self.app.mode_buttons))
        self.app.stop();self.app.mode.set('Replay');self.app.change_mode()
        self.assertEqual(self.app.model.mode,'Replay')
        self.assertTrue(self.app.start_button.instate(['disabled']))
        radio_parent=self.app.mode_buttons[0].master
        hardware=[b for b in radio_parent.winfo_children() if 'Live Hardware' in b.cget('text')]
        self.assertEqual(len(hardware),1)
        self.assertTrue(hardware[0].instate(['disabled']))

    def test_settings_control_fits_window_and_dialog_opens(self):
        self.root.after_cancel(self.app.tick_job)
        self.app.tick_job = None
        self.root.deiconify();self.root.update_idletasks()
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        buttons=[w for w in descendants(self.root)
                 if w.winfo_class()=='TButton' and w.cget('text')=='Settings…']
        self.assertEqual(len(buttons),1)
        button=buttons[0]
        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),
                             self.root.winfo_rooty()+self.root.winfo_height())
        button.invoke();self.root.update_idletasks()
        dialogs=[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)]
        self.assertEqual(len(dialogs),1)
        self.assertIn('TBD',dialogs[0].title())


if __name__=='__main__':
    unittest.main(verbosity=2)

from pathlib import Path
from queue import Queue
from threading import Lock, Thread
from typing import Callable, cast
from vosk import KaldiRecognizer, Model
from PySide6.QtWidgets import QMainWindow, QApplication, QFileDialog, QInputDialog
import sys
import re
import librosa
import json
import sounddevice as sd

try:
    from ui_mainwindow import Ui_MainWindow
except ImportError:
    print('Failed to load generated file for main window. You may need to generate it with "./manage.ps1 compile-ui".')
    exit(1)

Fraction = float
QUEUE_END = b'\0'


class Player:
    def __init__(
        self,
        filepath: str,
        on_next: Callable[[Fraction], None],
    ):
        self._data, self._rate = librosa.load(filepath)
        self.duration_seconds = librosa.get_duration(
            y=self._data,
            sr=self._rate
        )
        self._output_stream = sd.OutputStream(
            samplerate=self._rate,
            device=sd.default.device[1],
            channels=1,
            callback=self._on_chunk_requested
        )
        self._on_next = on_next
        self._finished = False
        self._data_pointer = 0
        self._data_pointer_lock = Lock()

    def _on_chunk_requested(self, outdata, frames, time, status):
        if self.end:
            return
        with self._data_pointer_lock:
            chunk_size = min(
                len(outdata[:, 0]),
                len(self._data) - self._data_pointer
            )
            chunk = self._data[self._data_pointer:self._data_pointer+chunk_size]
            outdata[:chunk_size, 0] = chunk
            self._data_pointer += chunk_size
            self._on_next(self.fraction)

    def play(self):
        if self.end:
            self._output_stream.abort()
            with self._data_pointer_lock:
                self._data_pointer = 0
        if not self.playing:
            self._output_stream.start()

    def stop(self):
        if self.playing:
            self._output_stream.abort()

    def set_seconds(self, value: int):
        assert value >= 0
        with self._data_pointer_lock:
            self._data_pointer = min(value * self._rate, len(self._data))
            self._on_next(self.fraction)

    def add_seconds(self, value: int):
        with self._data_pointer_lock:
            self._data_pointer += value * self._rate
            if value > 0:
                self._data_pointer = min(self._data_pointer, len(self._data))
            else:
                self._data_pointer = max(self._data_pointer, 0)
            self._on_next(self.fraction)

    @property
    def playing(self):
        return self._output_stream.active

    @property
    def end(self):
        return self._data_pointer >= len(self._data)

    @property
    def fraction(self):
        return self._data_pointer / len(self._data)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.setup_file_selection_page()
        self.setup_main_page()

    def setup_file_selection_page(self):
        self.file_selection_dialog = QFileDialog(self)
        self.file_selection_dialog.setFileMode(
            QFileDialog.FileMode.ExistingFile
        )
        self.file_selection_dialog.setNameFilter('*.mp3')
        self.file_selection_dialog.accepted.connect(
            self.on_file_selection_dialog_accepted
        )
        self.ui.fileSelectionButton.clicked.connect(
            self.file_selection_dialog.exec
        )
        self.ui.fileGoButton.clicked.connect(
            self.on_file_go_button_clicked
        )

    def setup_main_page(self):
        self.main_jump_dialog = QInputDialog(self)
        self.main_jump_dialog.accepted.connect(
            self.on_main_jump_dialog_accepted
        )
        self.ui.mainPlayButton.clicked.connect(
            self.on_main_play_action_triggered
        )
        self.ui.mainStopButton.clicked.connect(
            self.on_main_stop_action_triggered
        )
        self.ui.mainJumpButton.clicked.connect(
            self.main_jump_dialog.exec
        )
        self.ui.mainLeftButton.clicked.connect(
            self.on_main_backward_action_triggered
        )
        self.ui.mainRightButton.clicked.connect(
            self.on_main_forward_action_triggered
        )
        self.ui.mainBackButton.clicked.connect(
            self.on_main_back_button_clicked
        )
        device_info = cast(dict, sd.query_devices(sd.default.device[0]))
        samplerate = device_info["default_samplerate"]
        self.input_stream_queue = Queue()
        self.input_stream = sd.RawInputStream(
            samplerate=samplerate,
            blocksize=8000,
            device=sd.default.device[0],
            dtype="int16",
            channels=1,
            callback=self.on_chunk_recorded
        )
        self.kaldi = KaldiRecognizer(Model(lang='ru'), samplerate)

    def on_file_selection_dialog_accepted(self):
        path = self.file_selection_dialog.selectedFiles()[0]
        self.ui.fileSelectionLabel.setText('Processing...')
        self.ui.fileSelectionButton.setEnabled(False)
        self.player = cast(Player, None)

        def thread():
            try:
                self.player = Player(path, self.on_next)
            except Exception as e:
                self.ui.fileSelectionButton.setEnabled(True)
                self.ui.fileSelectionLabel.setStyleSheet('color: red')
                self.ui.fileSelectionLabel.setText('Invalid file!')
                return
            self.ui.fileSelectionButton.setEnabled(True)
            self.ui.fileSelectionLabel.setStyleSheet('')
            self.ui.fileSelectionLabel.setText(f'File is {Path(path).name}.')
            self.ui.fileGoButton.setEnabled(True)

        Thread(target=thread, daemon=True).start()

    def on_file_go_button_clicked(self):
        self.ui.stackedWidget.setCurrentIndex(1)

        def thread():
            self.on_next(self.player.fraction)
            self.input_stream.start()
            while True:
                data = self.input_stream_queue.get()
                if data == QUEUE_END:
                    self.kaldi.Reset()
                    return
                if self.kaldi.AcceptWaveform(data):
                    text = json.loads(self.kaldi.Result())['text']
                    if text == 'пуск':
                        self.on_main_play_action_triggered()
                    elif text == 'стоп':
                        self.on_main_stop_action_triggered()
                    elif text == 'вперёд':
                        self.on_main_forward_action_triggered()
                    elif text == 'назад':
                        self.on_main_backward_action_triggered()

        Thread(target=thread, daemon=True).start()

    def on_main_jump_dialog_accepted(self):
        value = self.main_jump_dialog.textValue()
        m = re.fullmatch(r'(\d+):([0-5]?\d)', value)
        if m is None:
            return
        seconds = int(m.group(1)) * 60 + int(m.group(2))
        self.player.set_seconds(seconds)

    def on_main_play_action_triggered(self):
        self.player.play()

    def on_main_stop_action_triggered(self):
        self.player.stop()

    def on_main_backward_action_triggered(self):
        self.player.add_seconds(-10)

    def on_main_forward_action_triggered(self):
        self.player.add_seconds(10)

    def on_main_back_button_clicked(self):
        self.player.stop()
        self.input_stream.abort()
        self.input_stream_queue.put(QUEUE_END)
        self.ui.stackedWidget.setCurrentIndex(0)

    def on_chunk_recorded(self, indata, frames, time, status):
        self.input_stream_queue.put(bytes(indata))

    def on_next(self, fraction: Fraction):
        total_minutes, total_seconds = divmod(
            int(self.player.duration_seconds),
            60
        )
        minutes, seconds = divmod(
            int(self.player.duration_seconds * fraction),
            60
        )
        self.ui.mainStampLabel.setText(
            f'{minutes}:{seconds:02d}/{total_minutes}:{total_seconds:02d}'
        )
        self.ui.mainProgressBar.setValue(int(fraction * 100))


app = QApplication(sys.argv)
window = MainWindow()
window.show()
app.exec()

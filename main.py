from pathlib import Path
from queue import Queue
from threading import Thread
from typing import cast
from vosk import KaldiRecognizer, Model
from PySide6.QtCore import QTimer, QThread, SIGNAL, SLOT, Signal, Slot
from PySide6.QtWidgets import QMainWindow, QApplication, QFileDialog
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
import sys
import json
import sounddevice as sd

try:
    from ui_mainwindow import Ui_MainWindow
except ImportError:
    print('Failed to load generated file for main window. You may need to generate it with "./manage.ps1 compile-ui".')
    exit(1)


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
        self.file_selection_dialog.setNameFilter('*.mp4')
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
        self.fullscreen = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.render_timestamp_label)
        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.ui.player)
        self.player.setAudioOutput(QAudioOutput(self))
        self.ui.mainPlayButton.clicked.connect(
            self.on_main_play_action_triggered
        )
        self.ui.mainStopButton.clicked.connect(
            self.on_main_stop_action_triggered
        )
        self.ui.mainLeftButton.clicked.connect(
            self.on_main_backward_action_triggered
        )
        self.ui.mainRightButton.clicked.connect(
            self.on_main_forward_action_triggered
        )
        self.text_recorded.connect(self.on_text_recorded)
        device_info = cast(dict, sd.query_devices(sd.default.device[0]))
        samplerate = device_info['default_samplerate']
        self.input_stream_queue = Queue()
        self.input_stream = sd.RawInputStream(
            samplerate=samplerate,
            blocksize=8000,
            device=sd.default.device[0],
            dtype='int16',
            channels=1,
            callback=self.on_chunk_recorded
        )
        self.kaldi = KaldiRecognizer(Model(lang='ru'), samplerate)

    def on_file_selection_dialog_accepted(self):
        file = self.file_selection_dialog.selectedFiles()[0]
        self.player.setSource(file)
        self.ui.fileSelectionLabel.setText(f'File is "{Path(file).name}".')
        self.ui.fileGoButton.setEnabled(True)

    def on_file_go_button_clicked(self):
        self.timer.start(500)
        self.ui.stackedWidget.setCurrentIndex(1)

        def thread():
            self.input_stream.start()
            while True:
                data = self.input_stream_queue.get()
                if self.kaldi.AcceptWaveform(data):
                    text = json.loads(self.kaldi.Result())['text']
                    self.text_recorded.emit(text)

        Thread(target=thread, daemon=True).start()

    def on_main_play_action_triggered(self):
        self.player.play()

    def on_main_stop_action_triggered(self):
        self.player.pause()

    def on_main_backward_action_triggered(self):
        self.player.pause()
        self.player.setPosition(self.player.position() - 10_000)
        self.player.play()

    def on_main_forward_action_triggered(self):
        self.player.pause()
        self.player.setPosition(self.player.position() + 10_000)
        self.player.play()

    def on_chunk_recorded(self, indata, frames, time, status):
        self.input_stream_queue.put(bytes(indata))

    text_recorded = Signal(str)

    def on_text_recorded(self, text):
        if text == 'пуск':
            self.on_main_play_action_triggered()
        elif text == 'стоп':
            self.on_main_stop_action_triggered()
        elif text == 'вперёд':
            self.on_main_forward_action_triggered()
        elif text == 'назад':
            self.on_main_backward_action_triggered()
        elif text == 'экран':
            self.fullscreen = not self.fullscreen
            self.ui.player.setFullScreen(self.fullscreen)

    def render_timestamp_label(self):
        minutes, seconds = divmod(
            int(self.player.position() / 1000),
            60
        )
        total_minutes, total_seconds = divmod(
            int(self.player.duration() / 1000),
            60
        )
        self.ui.mainStampLabel.setText(
            f'{minutes}:{seconds:02d}/{total_minutes}:{total_seconds:02d}'
        )
        fraction = self.player.position() / self.player.duration()
        self.ui.mainProgressBar.setValue(int(fraction * 100))


app = QApplication(sys.argv)
window = MainWindow()
window.show()
app.exec()

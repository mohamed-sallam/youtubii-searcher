import json
import os
import sys
import threading
import time
import webbrowser
from time import gmtime
from time import strftime

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QMessageBox,
                             QVBoxLayout, QWidget,
                             QCompleter)
from pytube import Playlist, YouTube
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (FluentWindow, BodyLabel, setTheme, Theme,
                            ProgressBar, CheckBox, ComboBox, SearchLineEdit,
                            LineEdit, PrimaryPushButton, TextEdit)
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound

# Set environment variables for high-DPI display settings
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
os.environ['QT_SCALE_FACTOR'] = '1'
os.environ['QT_SCREEN_SCALE_FACTORS'] = '1'

# Define directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, 'cache')
SUBTITLES_DIR = os.path.join(CACHE_DIR, 'subtitles')
PLAYLISTS_DIR = os.path.join(CACHE_DIR, 'playlists')
TRANSLATIONS_DIR = os.path.join(BASE_DIR, 'translations')

# Create directories if they do not exist
os.makedirs(SUBTITLES_DIR, exist_ok=True)
os.makedirs(PLAYLISTS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(TRANSLATIONS_DIR, exist_ok=True)


class ClickableTextEdit(TextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.link = None
        self.setMouseTracking(True)

    def mousePressEvent(self, e) -> None:
        self.link = self.anchorAt(e.pos())
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if self.link == self.anchorAt(e.pos()) and self.link.startswith('http'):
            webbrowser.open(self.link)
            self.link = None
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e) -> None:
        cursor_shape = Qt.PointingHandCursor if self.anchorAt(
            e.pos()).startswith('http') else Qt.IBeamCursor
        if self.cursor().shape() != cursor_shape:
            self.viewport().setCursor(cursor_shape)
        super().mouseMoveEvent(e)


class SubtitleSearcherApp(FluentWindow):
    subtitles_loading = pyqtSignal()
    progress_updated = pyqtSignal(int)
    subtitles_loaded = pyqtSignal()
    subtitles_failed = pyqtSignal(list)

    def __init__(self) -> None:
        super().__init__()

        self.current_language = 'en'
        self.translations = {}

        self.setWindowTitle(self.translate("YouTube Searcher"))
        self.setGeometry(100, 100, 600, 500)

        # Create widgets
        self.playlist_url_label = BodyLabel(self.translate("Playlist URLs:"))
        self.playlist_url_entry = TextEdit()  # Change to TextEdit

        self.lang_label = BodyLabel(self.translate("Language (e.g., en, ar):"))
        self.lang_entry = LineEdit()

        self.cache_checkbox = CheckBox(self.translate("Cache subtitles"))
        self.use_cache_checkbox = CheckBox(
            self.translate("Use cached subtitles, if any"))

        self.load_button = PrimaryPushButton(self.translate("Load Subtitles"))
        self.load_button.clicked.connect(self.load_subtitles)

        self.progress_label = BodyLabel(self.translate("Loading subtitles..."))
        self.progress_label.setVisible(False)
        self.progress_bar = ProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setVisible(False)

        self.search_label = BodyLabel(self.translate("Search Term:"))
        self.search_entry = SearchLineEdit()
        self.search_entry.setCompleter(QCompleter())
        self.search_entry.setDisabled(True)
        self.search_entry.textChanged.connect(self.update_suggestions)
        self.search_entry.searchSignal.connect(self.search_subtitles)
        self.search_entry.returnPressed.connect(self.search_subtitles)

        self.results_text = ClickableTextEdit()
        self.results_text.setReadOnly(True)

        # Language selector
        self.language_selector = ComboBox()
        self.language_selector.addItem(text="English", userData="en")
        self.language_selector.addItem(text="العربية", userData="ar")
        self.language_selector.currentIndexChanged.connect(self.change_language)

        # Layout setup
        layout = QVBoxLayout()
        layout.addWidget(self.language_selector)
        layout.addWidget(self.playlist_url_label)
        layout.addWidget(self.playlist_url_entry)
        layout.addWidget(self.lang_label)
        layout.addWidget(self.lang_entry)
        layout.addWidget(self.cache_checkbox)
        layout.addWidget(self.use_cache_checkbox)
        layout.addWidget(self.load_button)
        layout.addWidget(self.progress_label, alignment=Qt.AlignCenter)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.search_label)
        layout.addWidget(self.search_entry)
        layout.addWidget(self.results_text)

        # Initialize translations
        self.load_translations()

        container = QWidget()
        container.setObjectName("home")
        container.setLayout(layout)
        self.addSubInterface(interface=container,
                             icon=FIF.HOME,
                             text=self.translate("Home"))

        self.subtitles = {}
        self.video_titles = {}
        self.failed_videos = []  # List to store failed videos

        self.subtitles_loading.connect(self.on_subtitles_loading)
        self.progress_updated.connect(self.on_progress_updated)
        self.subtitles_loaded.connect(self.on_subtitles_loaded)
        self.subtitles_failed.connect(
            self.on_subtitles_failed)  # Connect the new signal
        self.create_about_tab()

    def create_about_tab(self):
        about_text = self.translate("""
            <h2>About</h2>
            <p>This application was developed by <strong><a style="color:#3f84e4" href="https://github.com/mohamed-sallam">Mohamed Sallam</a></strong>.</p>
            <p>Repository: <a style="color:#3f84e4" href="https://github.com/mohamed-sallam/youtubii-searcher">YouTubii Searcher</a></p>
            <p>This application was developed with the assistance of <strong>ChatGPT</strong> by OpenAI.</p>
            <p>License: <strong>GPL-3.0</strong></p>
            <p>© 2024 Mohamed Sallam</p>
            <br>
            <h2>عن البرنامج</h2>
            <p>تم تطوير هذا التطبيق بواسطة <strong><a style="color:#3f84e4" href="https://github.com/mohamed-sallam">محمد سلّام</a></strong>.</p>
            <p>المستودع: <a style="color:#3f84e4" href="https://github.com/mohamed-sallam/youtubii-searcher">الباحث اليوتيوبي</a></p>
            <p>تم تطوير هذا التطبيق بمساعدة <strong>ChatGPT</strong> بواسطة OpenAI.</p>
            <p>الترخيص: <strong>GPL-3.0</strong></p>
            <p>© 2024 محمد سلّام</p>
            """)

        about_text_edit = ClickableTextEdit()
        about_text_edit.setReadOnly(True)
        about_text_edit.setHtml(about_text)
        about_text_edit.setStyleSheet("border: none;")
        about_text_edit.setAlignment(Qt.AlignLeft)

        about_container = QWidget()
        about_container.setObjectName("about")
        about_layout = QVBoxLayout()
        about_layout.addWidget(about_text_edit)
        about_container.setLayout(about_layout)

        self.addSubInterface(interface=about_container,
                             icon=FIF.INFO,
                             text=self.translate("About"))

    def load_translations(self):
        self.translations = {}
        for file in os.listdir(TRANSLATIONS_DIR):
            if file.endswith('.json'):
                with open(os.path.join(TRANSLATIONS_DIR, file), 'r',
                          encoding='utf-8') as f:
                    lang_code = file.split('.')[0]
                    self.translations[lang_code] = json.load(f)

        self.current_language = 'en'
        self.apply_translation()

    def apply_translation(self):
        self.setWindowTitle(self.translate("YouTube Subtitle Searcher"))
        self.playlist_url_label.setText(self.translate("Playlist URLs:"))
        self.lang_label.setText(self.translate("Language (e.g., en, ar):"))
        self.cache_checkbox.setText(self.translate("Cache subtitles"))
        self.use_cache_checkbox.setText(
            self.translate("Use cached subtitles, if any"))
        self.load_button.setText(self.translate("Load Subtitles"))
        self.progress_label.setText(self.translate("Loading subtitles..."))
        self.search_label.setText(self.translate("Search Term:"))

        if self.current_language == 'ar':
            self.setLayoutDirection(Qt.RightToLeft)
            self.results_text.setLayoutDirection(Qt.RightToLeft)
        else:
            self.setLayoutDirection(Qt.LeftToRight)
            self.results_text.setLayoutDirection(Qt.LeftToRight)

    def translate(self, text):
        return self.translations.get(self.current_language, {}).get(text, text)

    def change_language(self):
        self.current_language = self.language_selector.currentData()
        self.apply_translation()

    def fetch_subtitles_for_video(
            self, video_id: str, lang: str, retries: int = 2
    ):
        cache_filename = os.path.join(SUBTITLES_DIR, f"{video_id}_{lang}.json")
        if os.path.exists(cache_filename):
            with open(cache_filename, 'r', encoding='utf-8') as file:
                return json.load(file)

        attempt = 0
        while attempt < retries:
            try:
                transcript = YouTubeTranscriptApi.get_transcript(
                    video_id, languages=[lang]
                )
                if self.cache_checkbox.isChecked():
                    with open(cache_filename, 'w', encoding='utf-8') as file:
                        json.dump(transcript, file)
                return transcript
            except NoTranscriptFound:
                return []
            except Exception as _:
                if attempt < retries - 1:
                    time.sleep(1)
                    attempt += 1
                else:
                    return None

    def load_subtitles(self):
        playlist_urls = self.playlist_url_entry.toPlainText().splitlines()
        lang = self.lang_entry.text()
        if not playlist_urls:
            QMessageBox.warning(self, self.translate("Warning"),
                                self.translate(
                                    "Please enter at least one playlist URL or video link."))
            return
        if not lang:
            QMessageBox.warning(self, self.translate("Warning"),
                                self.translate("Please enter a language code."))
            return

        self.progress_label.setText(self.translate("Loading subtitles..."))
        self.progress_bar.setValue(0)
        self.search_entry.setDisabled(True)

        threading.Thread(target=self._load_subtitles_thread,
                         args=(playlist_urls, lang)).start()

    def _load_subtitles_thread(self, playlist_urls: list, lang: str):
        self.subtitles_loading.emit()

        self.subtitles = {}
        self.video_titles = {}
        self.failed_videos = []  # Reset the list of failed videos
        total_videos = 0

        for url in playlist_urls:
            if 'list=' in url:
                # Process playlist
                playlist_id = url.split('list=')[-1]
                cache_filename = os.path.join(PLAYLISTS_DIR,
                                              f"{playlist_id}.json")

                # Check for cached playlist
                if self.use_cache_checkbox.isChecked() and os.path.exists(
                        cache_filename):
                    with open(cache_filename, 'r', encoding='utf-8') as file:
                        cached_playlist = json.load(file)
                        self.video_titles.update(cached_playlist)
                else:
                    playlist = Playlist(url)
                    self.progress_label.setText(
                        self.translate(
                            "Loading subtitles... (counting videos)"))
                    self.video_titles.update(
                        {video.video_id: video.title for video in
                         playlist.videos})

                    if self.cache_checkbox.isChecked():
                        with open(cache_filename, 'w',
                                  encoding='utf-8') as file:
                            json.dump(self.video_titles, file)
            else:
                video_id = url.split('v=')[-1].split('&')[0]
                self.video_titles[video_id] = YouTube(url).title

            total_videos = len(self.video_titles)

        for i, (video_id, title) in enumerate(self.video_titles.items()):
            transcript = self.fetch_subtitles_for_video(video_id, lang)
            if transcript is not None:
                self.subtitles[video_id] = transcript
            else:
                self.failed_videos.append((title, video_id))
            progress = int((i + 1) / total_videos * 100)
            self.progress_updated.emit(progress)

        self.subtitles_loaded.emit()
        self.subtitles_failed.emit(self.failed_videos)  # Emit the failed videos

    def on_progress_updated(self, prog: int):
        self.progress_bar.setValue(prog)
        self.progress_label.setText(
            self.translate("Loading subtitles...") + f"({int(prog)}%)")

    def on_subtitles_loading(self):
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)

    def on_subtitles_loaded(self):
        self.progress_label.setText(self.translate("Subtitles loaded."))
        self.progress_label.setStyleSheet("color: #00ca4a")
        self.progress_bar.setVisible(False)
        self.search_entry.setDisabled(False)

    def on_subtitles_failed(self, failed_videos: list) -> None:
        if failed_videos:
            message = self.translate(
                "Failed to fetch subtitles for the following videos:\n")
            for title, video_id in failed_videos:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                message += f'{title} - {video_url}\n'
            QMessageBox.warning(self, self.translate("Warning"), message)

    def update_suggestions(self):
        complete_list = []
        search_term = self.search_entry.text()
        if search_term:
            suggestions = set()
            for transcript in self.subtitles.values():
                for entry in transcript:
                    suggestions.update(entry['text'].split())

            complete_list.clear()
            for suggestion in sorted(suggestions):
                if search_term.lower() in suggestion.lower():
                    complete_list.append(suggestion)
        else:
            complete_list.clear()
        self.search_entry.setCompleter(QCompleter(complete_list))

    def search_subtitles(self):
        search_term = self.search_entry.text()
        if search_term:
            results = {}
            for video_id, transcript in self.subtitles.items():
                matches = [entry for entry in transcript if
                           search_term.lower() in entry['text'].lower()]
                if matches:
                    results[video_id] = matches

            self.results_text.clear()
            for video_id, matches in results.items():
                title = self.video_titles.get(video_id,
                                              self.translate("Unknown Title"))
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                self.results_text.append(
                    f'🎬 <a style="color:#3f84e4" href="{video_url}">'
                    f'{title}</a>')
                for match in matches:
                    timestamp_url = f"https://www.youtube.com/watch?v=" \
                                    f"{video_id}&t={int(match['start'])}s"
                    self.results_text.append(
                        f'<a style="color:#3f84e4" href="{timestamp_url}">'
                        f'{strftime("%H:%M:%S", gmtime(match["start"]))}</a> - {match["text"]}')
                self.results_text.append("<br>")
        else:
            self.results_text.clear()

    def show_error(self, message):
        self.progress_label.setText(self.translate("Error"))
        self.progress_label.setStyleSheet("color: #e5002d")
        self.progress_bar.setVisible(False)
        self.search_entry.setDisabled(False)
        QMessageBox.critical(self, self.translate("Error"),
                             self.translate(message))


if __name__ == "__main__":
    setTheme(Theme.AUTO)
    app = QApplication(sys.argv)
    window = SubtitleSearcherApp()
    window.show()
    sys.exit(app.exec_())

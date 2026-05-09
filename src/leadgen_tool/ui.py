from __future__ import annotations

import os
import sys
import json
import math
import time
from datetime import date, datetime
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote_plus, unquote, urlencode

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot, QUrl, QSize, QTimer
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QMenu,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QRadioButton,
    QHeaderView,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from leadgen_tool.config import (
    US_STATES,
    AppConfig,
    default_output_directory,
    load_config,
    save_config,
)
from leadgen_tool.logging import configure_logging
from leadgen_tool.field_reports import (
    export_leads_pdf,
    print_call_sheet,
    print_leads,
    print_mapped_leads,
    print_route_sheet,
    export_scripts_pdf,
    print_scripts,
)
from leadgen_tool.mapping import (
    build_route_text,
    filter_map_leads,
    geocode_start_address,
    plan_route,
)
from leadgen_tool.exporter import export_csv
from leadgen_tool.models import EXPORT_HEADERS, Lead
from leadgen_tool.runner import RunSummary, run_lead_generation
from leadgen_tool.sales_scripts import SALES_SCRIPTS
from leadgen_tool.storage import (
    delete_route,
    delete_preset,
    load_route,
    load_presets,
    load_routes,
    list_saved_progress,
    load_progress_snapshot,
    load_saved_leads,
    load_suppressed_businesses,
    save_suppressed_business,
    restore_suppressed_business,
    clear_suppressed_businesses,
    suppression_match_for_lead_in_entries,
    save_route,
    save_leads_in_app,
    save_progress_snapshot,
    save_preset,
)


TABLE_HEADERS = ["Save", "Stop #"] + EXPORT_HEADERS
SIMPLE_TABLE_HEADERS = {
    "Save",
    "Stop #",
    "Business Name",
    "Full Address",
    "Phone",
    "Status",
    "Action Priority",
    "Recommended Visit Window",
    "Quick Notes",
}
FIELD_STATUS_OPTIONS = [
    "New",
    "Called",
    "No Answer",
    "Left Voicemail",
    "Door Knocked",
    "Interested",
    "Follow Up",
    "Not Interested",
    "Customer",
    "Bad Lead",
]
CONTACT_ATTEMPT_STATUSES = {
    "Called",
    "No Answer",
    "Left Voicemail",
    "Door Knocked",
}
FOLLOWUP_CARD_ACTIONS = [
    ("Called", "Called"),
    ("No Answer", "No Answer"),
    ("Left Voicemail", "Left Voicemail"),
    ("Door Knocked", "Door Knocked"),
    ("Interested", "Interested"),
    ("Follow Up", "Follow Up"),
    ("Not Interested", "Not Interested"),
]


def _asset_path(relative_path: str) -> str:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return str(base_path / relative_path)


class LeadGenerationWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, config: AppConfig, cities: list[str], output_folder: str) -> None:
        super().__init__()
        self.config = config
        self.cities = cities
        self.output_folder = output_folder

    @Slot()
    def run(self) -> None:
        try:
            summary = run_lead_generation(
                self.config,
                self.cities,
                output_directory=self.output_folder,
                progress=self.progress.emit,
                save_settings=True,
            )
        except Exception as exc:
            self.failed.emit(_friendly_error(exc))
            return

        self.finished.emit(summary)


class PersistentCheckMenu(QMenu):
    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        action = self.activeAction()
        if action and action.isCheckable():
            action.setChecked(not action.isChecked())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        startup_started = time.perf_counter()
        super().__init__()
        self.config = load_config()
        self.logger = configure_logging()
        self.logger.info("RouteForge startup: begin")
        self.latest_output_path: Path | None = None
        self.worker_thread: QThread | None = None
        self.worker: LeadGenerationWorker | None = None
        self.keyword_actions: list[QAction] = []
        self.presets: dict[str, dict[str, object]] = {}
        self.routes: dict[str, dict[str, object]] = {}
        self.original_leads: list[Lead] = []
        self.current_leads: list[Lead] = []
        self.route_leads: list[Lead] = []
        self.route_current_index = 0
        self.route_completed_count = 0
        self.current_progress_save_name: str | None = None
        self.dark_mode = False
        self.simple_mode = True
        self.current_step = 1
        self.map_dirty = True
        self.map_tab_index = -1
        self.route_tab_index = 2
        self.followups_tab_index = 3
        self.hidden_tab_index = 4
        self.scripts_tab_index = 5
        self._last_map_signature: tuple[object, ...] | None = None
        self._map_list_leads: list[Lead] = []
        self._pending_map_focus_key = ""
        self.simple_keyword_actions: list[QAction] = []
        self.results_hint_compact = False
        self._hidden_filter_message = ""
        self._script_widgets: dict[str, QPlainTextEdit] = {}
        self._followups_loaded = False
        self._followups_dirty = True
        self._hidden_loaded = False
        self._hidden_dirty = True
        self._map_view_ready = False
        self._map_dirty_when_opened = True
        self._tracker_save_pending = False
        self._tracker_save_timer = QTimer(self)
        self._tracker_save_timer.setSingleShot(True)
        self._tracker_save_timer.timeout.connect(self._flush_tracker_state)

        self.setWindowTitle("RouteForge")
        self.setWindowIcon(QIcon(_asset_path("assets/routeforge.png")))
        self.resize(1320, 900)
        self.logger.info("RouteForge startup: state ready in %.2fs", time.perf_counter() - startup_started)
        self._build_menu_bar()
        self.logger.info("RouteForge startup: menu ready in %.2fs", time.perf_counter() - startup_started)
        self._build_ui()
        self.logger.info("RouteForge startup: ui shell ready in %.2fs", time.perf_counter() - startup_started)
        self._load_config_values()
        self.logger.info("RouteForge startup: config loaded in %.2fs", time.perf_counter() - startup_started)
        self._refresh_market_preview()
        self._update_action_states()
        self._show_onboarding_if_needed()
        self.logger.info("RouteForge startup: shown in %.2fs", time.perf_counter() - startup_started)

    def _build_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu("File")

        open_previous_action = QAction("Open Previous Save...", self)
        open_previous_action.setShortcut("Ctrl+O")
        open_previous_action.setStatusTip("Open a named RouteForge progress save.")
        open_previous_action.triggered.connect(self._open_previous_save_dialog)
        file_menu.addAction(open_previous_action)

        quick_save_action = QAction("Save", self)
        quick_save_action.setShortcut("Ctrl+S")
        quick_save_action.setStatusTip("Save this RouteForge progress file.")
        quick_save_action.triggered.connect(self._save_progress)
        file_menu.addAction(quick_save_action)

        save_as_action = QAction("Save As...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.setStatusTip("Save this work as a named progress file.")
        save_as_action.triggered.connect(self._save_progress_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        save_preset_action = QAction("Save Area", self)
        save_preset_action.setStatusTip("Save the current work area settings.")
        save_preset_action.triggered.connect(self._save_preset_dialog)
        file_menu.addAction(save_preset_action)

        load_preset_action = QAction("Load Saved Area", self)
        load_preset_action.setStatusTip("Load the selected saved area into the app.")
        load_preset_action.triggered.connect(self._apply_selected_preset)
        file_menu.addAction(load_preset_action)

        file_menu.addSeparator()

        save_route_action = QAction("Save Today's Route", self)
        save_route_action.setStatusTip("Save the current route so you can reopen it later.")
        save_route_action.triggered.connect(self._save_route_dialog)
        file_menu.addAction(save_route_action)

        load_route_action = QAction("Open Saved Route", self)
        load_route_action.setStatusTip("Open a previously saved route.")
        load_route_action.triggered.connect(self._load_selected_route)
        file_menu.addAction(load_route_action)

        delete_route_action = QAction("Delete Saved Route", self)
        delete_route_action.setStatusTip("Delete the selected saved route.")
        delete_route_action.triggered.connect(self._delete_selected_route)
        file_menu.addAction(delete_route_action)

        file_menu.addSeparator()

        print_action = QAction("Print Businesses", self)
        print_action.setStatusTip("Print the current business list.")
        print_action.triggered.connect(self._print_leads)
        file_menu.addAction(print_action)

        print_route_action = QAction("Print Door-Knocking Sheet", self)
        print_route_action.setStatusTip("Print the current route as a field sheet.")
        print_route_action.triggered.connect(self._export_route_sheet)
        file_menu.addAction(print_route_action)

        print_call_action = QAction("Print Call List", self)
        print_call_action.setStatusTip("Print businesses with phone numbers.")
        print_call_action.triggered.connect(self._print_call_sheet)
        file_menu.addAction(print_call_action)

        export_csv_action = QAction("Export CSV", self)
        export_csv_action.setStatusTip("Export selected businesses as CSV.")
        export_csv_action.triggered.connect(self._export_checked_csv)
        file_menu.addAction(export_csv_action)

        export_pdf_action = QAction("Export Businesses as PDF", self)
        export_pdf_action.setStatusTip("Save the current business list as a PDF.")
        export_pdf_action.triggered.connect(self._export_leads_pdf)
        file_menu.addAction(export_pdf_action)

        export_map_pdf_action = QAction("Export Route Order as PDF", self)
        export_map_pdf_action.setStatusTip("Save the route order as a PDF.")
        export_map_pdf_action.triggered.connect(self._export_map_pdf)
        file_menu.addAction(export_map_pdf_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit Application", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.setStatusTip("Close RouteForge.")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _build_ui(self) -> None:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(22, 18, 22, 18)
        outer_layout.setSpacing(14)

        title = QLabel("RouteForge")
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel(
            "Plan your route. Knock more doors. Close more deals."
        )
        subtitle.setObjectName("Subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer_layout.addWidget(title)
        outer_layout.addWidget(subtitle)

        top_actions = QHBoxLayout()
        top_actions.setSpacing(10)
        self.help_button = QPushButton("Help")
        self.help_button.setToolTip("Show the quick daily workflow.")
        self.help_button.clicked.connect(lambda: self._show_help())
        top_actions.addStretch()
        top_actions.addWidget(self.help_button)
        outer_layout.addLayout(top_actions)

        self.workflow_labels: list[QPushButton] = []
        workflow_row = QHBoxLayout()
        workflow_row.setSpacing(8)
        for step_number, step_text in enumerate(
            [
                "1 Choose location",
                "2 Find businesses",
                "3 Pick stops",
                "4 Build route",
                "5 Print/start",
            ],
            start=1,
        ):
            step_label = QPushButton(step_text)
            step_label.setObjectName("WorkflowStep")
            step_label.setCursor(Qt.CursorShape.PointingHandCursor)
            step_label.setFlat(True)
            step_label.setProperty("active", step_number == 1)
            step_label.clicked.connect(
                lambda _checked=False, step=step_number: self._go_to_workflow_step(step)
            )
            self.workflow_labels.append(step_label)
            workflow_row.addWidget(step_label)
        self.workflow_widget = QWidget()
        self.workflow_widget.setLayout(workflow_row)
        outer_layout.addWidget(self.workflow_widget)

        self.smart_banner = QFrame()
        self.smart_banner.setObjectName("SmartBanner")
        self.smart_banner_layout = QVBoxLayout(self.smart_banner)
        self.smart_banner_layout.setContentsMargins(0, 0, 0, 0)
        self.smart_banner_layout.setSpacing(8)
        outer_layout.addWidget(self.smart_banner)

        self.main_tabs = QTabWidget()
        self.main_tabs.setDocumentMode(True)
        self.main_tabs.currentChanged.connect(self._on_tab_changed)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("MainSplitter")
        splitter.setChildrenCollapsible(False)

        settings_widget = QWidget()
        root_layout = QVBoxLayout(settings_widget)
        root_layout.setContentsMargins(2, 2, 2, 2)
        root_layout.setSpacing(14)

        market_group = QGroupBox("Work Area")
        market_layout = QGridLayout(market_group)
        market_layout.setHorizontalSpacing(14)
        market_layout.setVerticalSpacing(12)

        self.state_combo = QComboBox()
        self.state_combo.addItems(US_STATES)
        self.state_combo.setToolTip("Choose the US state where you want to find businesses.")
        self.state_combo.currentTextChanged.connect(self._refresh_market_preview)

        self.cities_input = QLineEdit()
        self.cities_input.setPlaceholderText("Livonia, Novi, Northville")
        self.cities_input.setToolTip("Enter one or more cities separated by commas.")
        self.cities_input.textChanged.connect(self._on_cities_changed)

        self.radius_combo = QComboBox()
        self.radius_combo.addItems(["City only", "Nearby cities"])
        self.radius_combo.setToolTip(
            "City only keeps results inside the city. Nearby cities widens the search for local businesses."
        )

        self.all_cities_radio = QRadioButton()
        self.one_city_radio = QRadioButton()
        self.all_cities_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.all_cities_radio)
        self.mode_group.addButton(self.one_city_radio)
        self.all_cities_radio.toggled.connect(self._on_mode_changed)
        self.one_city_radio.toggled.connect(self._on_mode_changed)
        self._update_run_mode_labels()

        self.single_city_combo = QComboBox()
        self.single_city_combo.setToolTip("Choose one city from your city list.")
        self.single_city_combo.setEditable(True)
        self.single_city_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.single_city_combo.lineEdit().setPlaceholderText("Type or choose one city")
        self.single_city_combo.setEnabled(False)
        self.single_city_combo.currentTextChanged.connect(self._refresh_market_preview)

        self.keyword_button = QToolButton()
        self.keyword_button.setText("Business Types")
        self.keyword_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.keyword_button.setToolTip(
            "Choose the business types to look for. Leave it alone to use the normal daily mix."
        )
        self.keyword_menu = PersistentCheckMenu(self.keyword_button)
        self.keyword_button.setMenu(self.keyword_menu)

        self.keyword_summary = QLabel("No keywords selected")
        self.keyword_summary.setObjectName("KeywordSummary")
        self.keyword_summary.setWordWrap(True)

        self.custom_keywords_input = QLineEdit()
        self.custom_keywords_input.setPlaceholderText("Optional extras, comma-separated")
        self.custom_keywords_input.setToolTip("Advanced: add extra business types separated by commas.")
        self.custom_keywords_input.textChanged.connect(self._refresh_keyword_summary)

        self.output_input = QLineEdit()
        self.output_input.setToolTip("CSV files will be saved in this folder.")
        self.output_button = QPushButton("Choose Folder")
        self.output_button.clicked.connect(self._choose_output_folder)

        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("Load a saved market preset.")
        self.preset_combo.setMinimumWidth(240)
        self.save_preset_button = QPushButton("Save Preset")
        self.save_preset_button.clicked.connect(self._save_preset_dialog)
        self.load_preset_button = QPushButton("Load Preset")
        self.load_preset_button.clicked.connect(self._apply_selected_preset)
        self.delete_preset_button = QPushButton("Delete Preset")
        self.delete_preset_button.clicked.connect(self._delete_selected_preset)

        self.state_label = QLabel("State")
        self.cities_label = QLabel("Cities")
        market_layout.addWidget(self.state_label, 0, 0)
        market_layout.addWidget(self.state_combo, 0, 1, 1, 2)
        market_layout.addWidget(self.cities_label, 1, 0)
        market_layout.addWidget(self.cities_input, 1, 1, 1, 2)
        self.radius_label = QLabel("Radius")
        market_layout.addWidget(self.radius_label, 2, 0)
        market_layout.addWidget(self.radius_combo, 2, 1, 1, 2)
        self.keyword_label = QLabel("Business Types")
        market_layout.addWidget(self.keyword_label, 3, 0)
        market_layout.addWidget(self.keyword_button, 3, 1)
        market_layout.addWidget(self.keyword_summary, 3, 2)
        self.run_mode_label = QLabel("Run Mode")
        self.single_city_label = QLabel("Single City")
        self.custom_keywords_label = QLabel("Custom Keywords")
        self.output_folder_label = QLabel("Output Folder")
        self.presets_label = QLabel("Saved Areas")
        market_layout.addWidget(self.run_mode_label, 4, 0)
        market_layout.addWidget(self.all_cities_radio, 4, 1)
        market_layout.addWidget(self.one_city_radio, 4, 2)
        market_layout.addWidget(self.single_city_label, 5, 0)
        market_layout.addWidget(self.single_city_combo, 5, 1, 1, 2)
        market_layout.addWidget(self.custom_keywords_label, 6, 0)
        market_layout.addWidget(self.custom_keywords_input, 6, 1, 1, 2)
        market_layout.addWidget(self.output_folder_label, 7, 0)
        market_layout.addWidget(self.output_input, 7, 1)
        market_layout.addWidget(self.output_button, 7, 2)
        market_layout.addWidget(self.presets_label, 8, 0)
        market_layout.addWidget(self.preset_combo, 8, 1)
        preset_actions = QHBoxLayout()
        preset_actions.setSpacing(8)
        preset_actions.addWidget(self.save_preset_button)
        preset_actions.addWidget(self.load_preset_button)
        preset_actions.addWidget(self.delete_preset_button)
        preset_actions.addStretch()
        market_layout.addLayout(preset_actions, 8, 2)
        self.advanced_market_widgets = [
            self.state_label,
            self.cities_label,
            self.run_mode_label,
            self.all_cities_radio,
            self.one_city_radio,
            self.single_city_label,
            self.single_city_combo,
            self.custom_keywords_label,
            self.custom_keywords_input,
            self.output_folder_label,
            self.output_input,
            self.output_button,
            self.presets_label,
            self.preset_combo,
            self.save_preset_button,
            self.load_preset_button,
            self.delete_preset_button,
        ]

        self.simple_start_card = QFrame()
        self.simple_start_card.setObjectName("SimpleStartCard")
        simple_layout = QVBoxLayout(self.simple_start_card)
        simple_layout.setContentsMargins(28, 24, 28, 24)
        simple_layout.setSpacing(16)
        self.simple_start_title = QLabel("Where are you working today?")
        self.simple_start_title.setObjectName("SimpleStartTitle")
        self.simple_start_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.simple_start_subtitle = QLabel("Enter a city and we'll build a route of businesses you can call or visit today.")
        self.simple_start_subtitle.setObjectName("SimpleStartSubtitle")
        self.simple_start_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.simple_start_subtitle.setWordWrap(True)
        simple_layout.addWidget(self.simple_start_title)
        simple_layout.addWidget(self.simple_start_subtitle)

        simple_fields = QGridLayout()
        simple_fields.setHorizontalSpacing(12)
        simple_fields.setVerticalSpacing(10)
        self.simple_city_input = QLineEdit()
        self.simple_city_input.setPlaceholderText("City, e.g. Livonia")
        self.simple_city_input.setToolTip("Type the city you want to work today.")
        self.simple_state_combo = QComboBox()
        self.simple_state_combo.addItems(US_STATES)
        self.simple_state_combo.setToolTip("Choose the state for today's route.")
        self.simple_radius_combo = QComboBox()
        self.simple_radius_combo.addItems(["City only", "Nearby cities"])
        self.simple_radius_combo.setToolTip("City only keeps the route focused. Nearby cities widens the search.")
        simple_fields.addWidget(QLabel("City"), 0, 0)
        simple_fields.addWidget(self.simple_city_input, 0, 1, 1, 2)
        simple_fields.addWidget(QLabel("State"), 1, 0)
        simple_fields.addWidget(self.simple_state_combo, 1, 1)
        simple_fields.addWidget(self.simple_radius_combo, 1, 2)
        simple_layout.addLayout(simple_fields)

        simple_category_label = QLabel("Business types")
        simple_category_label.setObjectName("SimpleSectionLabel")
        simple_layout.addWidget(simple_category_label)
        self.simple_category_summary = QLabel("Daily mix selected")
        self.simple_category_summary.setObjectName("SimpleCategorySummary")
        self.simple_category_summary.setWordWrap(True)
        self.simple_hide_suppressed_checkbox = QCheckBox("Hide businesses I already worked / rejected")
        self.simple_hide_suppressed_checkbox.setChecked(True)
        self.simple_hide_suppressed_checkbox.setToolTip(
            "Keep businesses marked Do Not Show Again, Already Worked, Bad Lead, or Not Interested out of new results."
        )
        self.simple_hide_suppressed_checkbox.toggled.connect(self._on_suppression_filter_toggled)
        self.simple_keyword_button = QToolButton()
        self.simple_keyword_button.setText("Business Types")
        self.simple_keyword_button.setObjectName("BusinessTypeDropdown")
        self.simple_keyword_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.simple_keyword_button.setToolTip("Choose the business types to include before finding businesses.")
        self.simple_keyword_menu = PersistentCheckMenu(self.simple_keyword_button)
        self.simple_keyword_button.setMenu(self.simple_keyword_menu)
        simple_layout.addWidget(self.simple_keyword_button, 0, Qt.AlignmentFlag.AlignCenter)
        simple_layout.addWidget(self.simple_category_summary)
        simple_layout.addWidget(self.simple_hide_suppressed_checkbox)

        self.simple_generate_button = QPushButton("Find Today's Businesses")
        self.simple_generate_button.setObjectName("PrimaryButton")
        self.simple_generate_button.setToolTip("Find today's best local businesses.")
        self.simple_generate_button.clicked.connect(self._start_simple_run)
        simple_layout.addWidget(self.simple_generate_button, 0, Qt.AlignmentFlag.AlignCenter)

        root_layout.addWidget(self.simple_start_card)

        self.start_address_frame = QFrame()
        self.start_address_frame.setObjectName("StartAddressFrame")
        start_address_layout = QHBoxLayout(self.start_address_frame)
        start_address_layout.setContentsMargins(14, 10, 14, 10)
        start_address_layout.setSpacing(10)
        start_address_label = QLabel("Start address")
        start_address_label.setObjectName("StartAddressLabel")
        self.start_address_input = QLineEdit()
        self.start_address_input.setPlaceholderText("Optional, e.g. 123 Main St, Livonia")
        self.start_address_input.setToolTip(
            "Where you will start driving from. Used for route order and Google Maps directions."
        )
        start_address_layout.addWidget(start_address_label)
        start_address_layout.addWidget(self.start_address_input, 1)
        root_layout.addWidget(self.start_address_frame)

        root_layout.addWidget(market_group)
        self.market_group = market_group

        self.market_preview = QLabel()
        self.market_preview.setObjectName("MarketPreview")
        root_layout.addWidget(self.market_preview)

        action_row = QHBoxLayout()
        self.run_button = QPushButton("Find Businesses")
        self.run_button.setObjectName("PrimaryButton")
        self.run_button.setToolTip("Search the selected city and load the best businesses into the list.")
        self.run_button.clicked.connect(self._start_run)
        self.hide_suppressed_checkbox = QCheckBox("Hide worked/rejected")
        self.hide_suppressed_checkbox.setChecked(True)
        self.hide_suppressed_checkbox.setToolTip(
            "Hide businesses previously marked Already Worked, Do Not Show Again, Bad Lead, or Not Interested."
        )
        self.hide_suppressed_checkbox.toggled.connect(self._on_suppression_filter_toggled)
        self.build_my_day_button = QPushButton("Build My Day")
        self.build_my_day_button.setObjectName("HeroButton")
        self.build_my_day_button.setMinimumHeight(44)
        self.build_my_day_button.setToolTip(
            "Automatically pick the strongest 20-30 businesses, order them for driving, and show today's route."
        )
        self.build_my_day_button.clicked.connect(self._build_my_day)
        self.build_my_day_button.setEnabled(False)
        self.route_button = QPushButton("Build My Route")
        self.route_button.setObjectName("PrimaryButton")
        self.route_button.setToolTip("Create today's stop order from the selected businesses.")
        self.route_button.clicked.connect(self._build_route_plan)
        self.route_button.setEnabled(False)
        self.open_google_route_button = QPushButton("Open in Google Maps")
        self.open_google_route_button.setObjectName("PrimaryButton")
        self.open_google_route_button.setToolTip("Open the full driving route in Google Maps.")
        self.open_google_route_button.clicked.connect(self._start_route)
        self.open_google_route_button.setEnabled(False)
        self.export_route_button = QPushButton("Print Door-Knocking Sheet")
        self.export_route_button.setToolTip("Print a clean field sheet with stop number, business, address, phone, and notes.")
        self.export_route_button.clicked.connect(self._export_route_sheet)
        self.export_route_button.setEnabled(False)
        self.print_call_sheet_button = QPushButton("Print Call List")
        self.print_call_sheet_button.setToolTip("Print only businesses with phone numbers for quick calling.")
        self.print_call_sheet_button.clicked.connect(self._print_call_sheet)
        self.print_call_sheet_button.setEnabled(False)
        self.start_route_button = QPushButton("Today's Route")
        self.start_route_button.setToolTip("Return to the field route screen.")
        self.start_route_button.clicked.connect(self._show_route_mode)
        self.start_route_button.setEnabled(False)
        self.open_csv_button = QPushButton("Open Exported CSV")
        self.open_csv_button.setToolTip("Open the latest full data CSV created by Find Businesses.")
        self.open_csv_button.setEnabled(False)
        self.open_csv_button.clicked.connect(self._open_latest_csv)
        self.export_checked_button = QPushButton("Export CSV")
        self.export_checked_button.setToolTip("Optional backup export with all selected business data.")
        self.export_checked_button.setEnabled(False)
        self.export_checked_button.clicked.connect(self._export_checked_csv)
        self.dark_mode_button = QPushButton("Dark Mode")
        self.dark_mode_button.setCheckable(True)
        self.dark_mode_button.toggled.connect(self._set_dark_mode)
        action_row.addWidget(self.run_button)
        action_row.addWidget(self.hide_suppressed_checkbox)
        action_row.addWidget(self.build_my_day_button)
        action_row.addWidget(self.route_button)
        action_row.addWidget(self.open_google_route_button)
        action_row.addWidget(self.export_route_button)
        action_row.addWidget(self.print_call_sheet_button)
        action_row.addWidget(self.start_route_button)
        action_row.addWidget(self.open_csv_button)
        action_row.addWidget(self.export_checked_button)
        action_row.addWidget(self.dark_mode_button)
        action_row.addStretch()
        root_layout.addLayout(action_row)
        self.advanced_action_widgets = [
            self.dark_mode_button,
        ]

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)
        self.progress_log = QPlainTextEdit()
        self.progress_log.setReadOnly(True)
        self.progress_log.setPlaceholderText("Progress updates will appear here.")
        progress_layout.addWidget(self.progress_log)
        content_row.addWidget(progress_group, 2)

        summary_group = QGroupBox("Today's Summary")
        summary_layout = QVBoxLayout(summary_group)
        self.total_label = _summary_label("Businesses found", "0")
        self.duplicates_label = _summary_label("Duplicates removed", "0")
        self.tier1_label = _summary_label("Best stops", "0")
        self.incomplete_address_label = _summary_label("Incomplete addresses excluded", "0")
        self.city_mismatch_label = _summary_label("Out-of-city businesses excluded", "0")
        self.state_mismatch_label = _summary_label("Out-of-state businesses excluded", "0")
        self.strip_clusters_label = _summary_label("Strip mall clusters", "0")
        self.high_confidence_plazas_label = _summary_label("High-confidence plazas", "0")
        self.low_value_filtered_label = _summary_label("Low-value businesses filtered", "0")
        self.output_label = QLabel("Output file location\nNot created yet")
        self.output_label.setWordWrap(True)
        self.output_label.setObjectName("OutputLocation")
        for widget in (
            self.total_label,
            self.duplicates_label,
            self.tier1_label,
            self.incomplete_address_label,
            self.city_mismatch_label,
            self.state_mismatch_label,
            self.strip_clusters_label,
            self.high_confidence_plazas_label,
            self.low_value_filtered_label,
            self.output_label,
        ):
            summary_layout.addWidget(widget)
        summary_layout.addStretch()
        content_row.addWidget(summary_group, 1)

        root_layout.addLayout(content_row, 1)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setWidget(settings_widget)
        settings_scroll.setMinimumHeight(180)

        results_group = QGroupBox("Business List")
        results_layout = QVBoxLayout(results_group)
        results_layout.setContentsMargins(14, 18, 14, 14)
        results_layout.setSpacing(10)
        self.results_hint = QLabel(
            "Enter a city and find businesses to start."
        )
        self.results_hint.setObjectName("ResultsHint")
        self.results_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selection_bar = QFrame()
        self.selection_bar.setObjectName("SelectionBar")
        selection_bar_layout = QHBoxLayout(self.selection_bar)
        selection_bar_layout.setContentsMargins(14, 10, 14, 10)
        selection_bar_layout.setSpacing(10)
        self.selected_count_label = QLabel("0 stops selected for today")
        self.selected_count_label.setObjectName("SelectedCount")
        self.selection_build_route_button = QPushButton("Build My Route")
        self.selection_build_route_button.setObjectName("PrimaryButton")
        self.selection_build_route_button.clicked.connect(self._build_route_plan)
        self.clear_selection_button = QPushButton("Clear Selection")
        self.clear_selection_button.clicked.connect(self._clear_selection)
        selection_bar_layout.addWidget(self.selected_count_label, 1)
        selection_bar_layout.addWidget(self.selection_build_route_button)
        selection_bar_layout.addWidget(self.clear_selection_button)
        self.selection_bar.hide()
        tracker_row = QHBoxLayout()
        tracker_row.setSpacing(8)
        self.mark_called_button = QPushButton("Mark Called")
        self.mark_called_button.clicked.connect(lambda: self._mark_checked_outcome("Called"))
        self.mark_door_knocked_button = QPushButton("Mark Door Knocked")
        self.mark_door_knocked_button.clicked.connect(
            lambda: self._mark_checked_outcome("Door Knocked")
        )
        self.mark_interested_button = QPushButton("Mark Interested")
        self.mark_interested_button.clicked.connect(lambda: self._mark_checked_outcome("Interested"))
        self.mark_follow_up_button = QPushButton("Mark Follow Up")
        self.mark_follow_up_button.clicked.connect(lambda: self._mark_checked_outcome("Follow Up"))
        self.mark_not_interested_button = QPushButton("Mark Not Interested")
        self.mark_not_interested_button.clicked.connect(
            lambda: self._mark_checked_outcome("Not Interested")
        )
        self.already_worked_button = QPushButton("Already Worked")
        self.already_worked_button.clicked.connect(lambda: self._suppress_selected_business("Already Worked"))
        self.do_not_show_button = QPushButton("Do Not Show Again")
        self.do_not_show_button.clicked.connect(lambda: self._suppress_selected_business("Do Not Show Again"))
        self.bad_lead_button = QPushButton("Bad Lead")
        self.bad_lead_button.clicked.connect(lambda: self._suppress_selected_business("Bad Lead"))
        self.set_follow_up_button = QPushButton("Set Follow-Up Date")
        self.set_follow_up_button.clicked.connect(self._set_follow_up_for_checked)
        self.secondary_step3_widgets = [
            self.mark_called_button,
            self.mark_door_knocked_button,
            self.mark_interested_button,
            self.mark_follow_up_button,
            self.mark_not_interested_button,
            self.set_follow_up_button,
        ]
        self.tracker_action_widgets = [
            self.mark_called_button,
            self.mark_door_knocked_button,
            self.mark_interested_button,
            self.mark_follow_up_button,
            self.mark_not_interested_button,
            self.already_worked_button,
            self.do_not_show_button,
            self.bad_lead_button,
            self.set_follow_up_button,
        ]
        for button in self.tracker_action_widgets:
            button.setEnabled(False)
            tracker_row.addWidget(button)
        tracker_row.addStretch()
        self.generation_progress = QProgressBar()
        self.generation_progress.setObjectName("GenerationProgress")
        self.generation_progress.setRange(0, 0)
        self.generation_progress.setTextVisible(False)
        self.generation_progress.setToolTip("Business search is running. This bar moves while the app is working.")
        self.generation_progress.hide()
        self.lead_card_list = QListWidget()
        self.lead_card_list.setObjectName("LeadCardList")
        self.lead_card_list.setWordWrap(True)
        self.lead_card_list.setSpacing(10)
        self.lead_card_list.setMinimumHeight(430)
        self.lead_card_list.setToolTip("Click a business to select or unselect it. Double-click to show phone, email, hours, website, and notes.")
        self.lead_card_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.lead_card_list.itemChanged.connect(self._on_lead_card_changed)
        self.lead_card_list.itemClicked.connect(self._toggle_lead_card_checked)
        self.lead_card_list.itemDoubleClicked.connect(self._toggle_lead_card_details)
        self.lead_card_list.itemSelectionChanged.connect(self._on_lead_card_selection_changed)
        self.lead_card_list.hide()
        table_tools = QHBoxLayout()
        table_tools.setSpacing(8)
        self.scroll_left_button = QPushButton("<< Columns")
        self.scroll_right_button = QPushButton("Columns >>")
        self.column_scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.column_scrollbar.setToolTip("Move sideways through the business list columns.")
        self.scroll_left_button.clicked.connect(lambda: self._scroll_columns(-420))
        self.scroll_right_button.clicked.connect(lambda: self._scroll_columns(420))
        table_tools.addWidget(self.scroll_left_button)
        table_tools.addWidget(self.column_scrollbar, 1)
        table_tools.addWidget(self.scroll_right_button)
        self.results_table = QTableWidget(0, len(TABLE_HEADERS))
        self.results_table.setHorizontalHeaderLabels(
            [
                "Select"
                if header == "Save"
                else "Priority"
                if header == "Action Priority"
                else "Address"
                if header == "Full Address"
                else "Visit Window"
                if header == "Recommended Visit Window"
                else header
                for header in TABLE_HEADERS
            ]
        )
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.verticalHeader().setDefaultSectionSize(44)
        self.results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.results_table.horizontalHeader().setStretchLastSection(False)
        self.results_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.results_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.results_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.results_table.horizontalScrollBar().setSingleStep(24)
        self.results_table.setWordWrap(False)
        self.results_table.setMinimumHeight(360)
        self.results_table.itemChanged.connect(lambda _item: self._update_action_states())
        self.results_table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._set_default_table_widths()
        self._wire_column_scrollbar()
        self.results_table.setToolTip("Review the businesses before opening the CSV.")
        results_layout.addWidget(self.results_hint)
        results_layout.addWidget(self.selection_bar)
        results_layout.addLayout(tracker_row)
        results_layout.addWidget(self.generation_progress)
        results_layout.addWidget(self.lead_card_list)
        results_layout.addLayout(table_tools)
        results_layout.addWidget(self.results_table)
        self.table_tools_widgets = [
            self.scroll_left_button,
            self.column_scrollbar,
            self.scroll_right_button,
        ]
        self.results_table.hide()

        setup_tab = QWidget()
        setup_tab_layout = QVBoxLayout(setup_tab)
        setup_tab_layout.setContentsMargins(0, 0, 0, 0)
        setup_tab_layout.addWidget(settings_scroll)
        self.main_tabs.addTab(setup_tab, "Setup")

        businesses_tab = QWidget()
        businesses_tab_layout = QVBoxLayout(businesses_tab)
        businesses_tab_layout.setContentsMargins(0, 0, 0, 0)
        businesses_tab_layout.addWidget(results_group)
        self.main_tabs.addTab(businesses_tab, "Businesses")

        map_tab = QWidget()
        map_tab_layout = QVBoxLayout(map_tab)
        map_tab_layout.setContentsMargins(0, 0, 0, 0)
        map_controls = QHBoxLayout()
        self.map_filter_combo = QComboBox()
        self.map_filter_combo.addItems(["All Businesses", "Tier 1 Only", "Checked Businesses"])
        self.map_filter_combo.setToolTip("Choose which businesses appear in the route list.")
        self.map_filter_combo.currentIndexChanged.connect(self._refresh_map_view)
        self.route_combo = QComboBox()
        self.route_combo.setToolTip("Open a saved route for today's field work.")
        self.route_combo.setMinimumWidth(240)
        self.map_refresh_button = QPushButton("Refresh List")
        self.map_refresh_button.clicked.connect(self._force_refresh_map_view)
        self.save_route_button = QPushButton("Save Today's Route")
        self.save_route_button.clicked.connect(self._save_route_dialog)
        self.load_route_button = QPushButton("Open Route")
        self.load_route_button.clicked.connect(self._load_selected_route)
        self.delete_route_button = QPushButton("Delete Route")
        self.delete_route_button.clicked.connect(self._delete_selected_route)
        self.map_route_button = QPushButton("Build My Route")
        self.map_route_button.setToolTip("Create an efficient driving route from the selected stops.")
        self.map_route_button.clicked.connect(self._build_route_plan)
        self.map_open_google_button = QPushButton("Open Full Route in Google Maps")
        self.map_open_google_button.setObjectName("PrimaryButton")
        self.map_open_google_button.setToolTip("Open the current route in Google Maps for driving directions.")
        self.map_open_google_button.clicked.connect(self._start_route)
        self.print_mapped_button = QPushButton("Print Route Order")
        self.print_mapped_button.setToolTip("Print businesses shown in the route list with stop number, phone, best time, and status.")
        self.print_mapped_button.clicked.connect(self._print_mapped_leads)
        self.map_call_sheet_button = QPushButton("Print Call List")
        self.map_call_sheet_button.setToolTip("Print a phone-first call list for businesses with numbers.")
        self.map_call_sheet_button.clicked.connect(self._print_call_sheet)
        self.export_map_button = QPushButton("Export Route Order PDF")
        self.export_map_button.clicked.connect(self._export_map_pdf)
        self.map_filter_label = QLabel("Business Filter")
        self.saved_routes_label = QLabel("Saved Routes")
        map_controls.addWidget(self.map_filter_label)
        map_controls.addWidget(self.map_filter_combo)
        map_controls.addWidget(self.saved_routes_label)
        map_controls.addWidget(self.route_combo)
        map_controls.addWidget(self.map_refresh_button)
        map_controls.addWidget(self.map_route_button)
        map_controls.addWidget(self.map_open_google_button)
        map_controls.addWidget(self.print_mapped_button)
        map_controls.addWidget(self.map_call_sheet_button)
        map_controls.addWidget(self.save_route_button)
        map_controls.addWidget(self.load_route_button)
        map_controls.addWidget(self.delete_route_button)
        map_controls.addWidget(self.export_map_button)
        map_controls.addStretch()
        map_tab_layout.addLayout(map_controls)
        self.advanced_map_widgets = [
            self.saved_routes_label,
            self.route_combo,
            self.save_route_button,
            self.load_route_button,
            self.delete_route_button,
            self.export_map_button,
        ]

        route_group = QGroupBox("Google Maps Route")
        route_layout = QVBoxLayout(route_group)
        route_note = QLabel(
            "RouteForge keeps your stop list and route order here. Use Google Maps for driving directions."
        )
        route_note.setObjectName("RoutePreviewNote")
        route_note.setWordWrap(True)
        route_layout.addWidget(route_note)
        self.map_lead_list = QListWidget()
        self.map_lead_list.setObjectName("MapLeadList")
        self.map_lead_list.setToolTip("Businesses included in the current route or filter.")
        self.map_lead_list.setWordWrap(True)
        self.map_lead_list.setSpacing(6)
        self.map_lead_list.itemClicked.connect(self._focus_map_lead_item)
        route_layout.addWidget(QLabel("Businesses in Route"))
        route_layout.addWidget(self.map_lead_list, 2)
        self.route_summary = QPlainTextEdit()
        self.route_summary.setReadOnly(True)
        self.route_summary.setPlaceholderText("Build a route to see a simple field order here.")
        route_layout.addWidget(QLabel("Route Order"))
        route_layout.addWidget(self.route_summary, 1)
        map_tab_layout.addWidget(route_group, 1)

        self._route_order_widget = map_tab

        route_mode_tab = QWidget()
        route_mode_layout = QVBoxLayout(route_mode_tab)
        route_mode_layout.setContentsMargins(12, 12, 12, 12)
        route_mode_layout.setSpacing(16)

        route_mode_top = QHBoxLayout()
        self.route_mode_progress = QLabel("0 of 0 completed")
        self.route_mode_progress.setObjectName("RouteProgress")
        self.route_mode_progress.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        route_mode_title = QLabel("Today's Route")
        route_mode_title.setObjectName("RouteModeTitle")
        route_mode_top.addWidget(route_mode_title)
        route_mode_top.addStretch()
        route_mode_top.addWidget(self.route_mode_progress)
        route_mode_layout.addLayout(route_mode_top)

        self.current_stop_card = QFrame()
        self.current_stop_card.setObjectName("CurrentStopCard")
        self.current_stop_card.setMaximumHeight(340)
        current_stop_layout = QVBoxLayout(self.current_stop_card)
        current_stop_layout.setContentsMargins(18, 14, 18, 14)
        current_stop_layout.setSpacing(6)
        self.current_stop_badge = QLabel("Stop 1")
        self.current_stop_badge.setObjectName("StopBadge")
        self.current_stop_name = QLabel("Build today's route to see the first stop.")
        self.current_stop_name.setObjectName("CurrentStopName")
        self.current_stop_name.setWordWrap(True)
        self.current_stop_address = QLabel("")
        self.current_stop_address.setObjectName("CurrentStopAddress")
        self.current_stop_address.setWordWrap(True)
        self.current_stop_reason = QLabel("")
        self.current_stop_reason.setObjectName("CurrentStopReason")
        self.current_stop_reason.setWordWrap(True)
        self.current_stop_window = QLabel("")
        self.current_stop_window.setObjectName("CurrentStopWindow")
        current_stop_layout.addWidget(self.current_stop_badge, 0, Qt.AlignmentFlag.AlignLeft)
        current_stop_layout.addWidget(self.current_stop_name)
        current_stop_layout.addWidget(self.current_stop_address)

        route_actions = QHBoxLayout()
        route_actions.setSpacing(10)
        self.route_open_maps_button = QPushButton("Open Full Route in Google Maps")
        self.route_open_maps_button.setObjectName("PrimaryButton")
        self.route_open_maps_button.setToolTip(
            "Open the full route in Google Maps for driving directions."
        )
        self.route_open_maps_button.clicked.connect(self._start_route)
        self.route_stop_maps_button = QPushButton("Open Stop in Google Maps")
        self.route_stop_maps_button.setToolTip("Open only the current stop in Google Maps.")
        self.route_stop_maps_button.clicked.connect(self._open_current_stop_maps)
        self.current_stop_phone = QLabel("")
        self.current_stop_phone.setObjectName("CurrentStopMeta")
        self.current_stop_phone.setWordWrap(True)
        self.current_stop_status = QLabel("")
        self.current_stop_status.setObjectName("CurrentStopMeta")
        self.current_stop_status.setWordWrap(True)
        self.current_stop_notes = QLabel("")
        self.current_stop_notes.setObjectName("CurrentStopMeta")
        self.current_stop_notes.setWordWrap(True)
        current_stop_layout.addWidget(self.current_stop_phone)
        current_stop_layout.addWidget(self.current_stop_status)
        current_stop_layout.addWidget(self.current_stop_window)
        current_stop_layout.addWidget(self.current_stop_notes)
        current_stop_layout.addWidget(self.current_stop_reason)

        self.route_mark_called_button = QPushButton("Mark Called")
        self.route_mark_called_button.clicked.connect(self._mark_current_stop_called)
        self.route_mark_door_knocked_button = QPushButton("Mark Door Knocked")
        self.route_mark_door_knocked_button.clicked.connect(self._mark_current_stop_door_knocked)
        self.route_mark_interested_button = QPushButton("Mark Interested")
        self.route_mark_interested_button.clicked.connect(self._mark_current_stop_interested)
        self.route_set_followup_button = QPushButton("Set Follow-Up")
        self.route_set_followup_button.clicked.connect(self._set_current_stop_followup)
        self.route_done_button = QPushButton("Mark Done")
        self.route_done_button.clicked.connect(self._mark_current_stop_done)
        self.route_skip_button = QPushButton("Skip")
        self.route_skip_button.clicked.connect(self._skip_current_stop)
        for button in (
            self.route_open_maps_button,
            self.route_stop_maps_button,
            self.route_mark_called_button,
            self.route_mark_door_knocked_button,
            self.route_mark_interested_button,
            self.route_set_followup_button,
            self.route_done_button,
            self.route_skip_button,
        ):
            button.setMinimumHeight(38)
            route_actions.addWidget(button)
        route_actions.addStretch()
        current_stop_layout.addLayout(route_actions)
        route_mode_layout.addWidget(self.current_stop_card, 0)

        upcoming_group = QGroupBox("Upcoming Stops")
        upcoming_group.setMinimumHeight(420)
        upcoming_layout = QVBoxLayout(upcoming_group)
        self.upcoming_stops_list = QListWidget()
        self.upcoming_stops_list.setObjectName("UpcomingStopsList")
        self.upcoming_stops_list.setWordWrap(True)
        self.upcoming_stops_list.setSpacing(10)
        upcoming_layout.addWidget(self.upcoming_stops_list)
        route_mode_layout.addWidget(upcoming_group, 2)

        self.main_tabs.addTab(route_mode_tab, "Today's Route")
        self.main_tabs.addTab(self._build_followups_tab(), "Follow-Ups")
        self.main_tabs.addTab(self._build_hidden_businesses_tab(), "Hidden Businesses")
        self.main_tabs.addTab(self._build_scripts_tab(), "Scripts")

        outer_layout.addWidget(self.main_tabs, 1)
        self.setCentralWidget(outer)
        self.setStyleSheet(LIGHT_STYLES)
        self._set_simple_mode(False)
        self.followup_summary_label.setText("Open this tab to load saved follow-ups.")
        self.hidden_businesses_list.addItem("Open this tab to load hidden businesses.")

    def _build_followups_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        controls = QHBoxLayout()
        self.followup_search_input = QLineEdit()
        self.followup_search_input.setPlaceholderText("Search business, address, or phone")
        self.followup_search_input.textChanged.connect(self._refresh_followups_tab)
        self.followup_status_filter = QComboBox()
        self.followup_status_filter.addItems(["Filter by Status"] + FIELD_STATUS_OPTIONS)
        self.followup_status_filter.currentTextChanged.connect(self._refresh_followups_tab)
        self.followup_city_filter = QComboBox()
        self.followup_city_filter.addItem("Filter by City")
        self.followup_city_filter.currentTextChanged.connect(self._refresh_followups_tab)
        self.followup_quick_filter = QComboBox()
        self.followup_quick_filter.addItems(
            [
                "Filter by Type",
                "Follow-Up Due",
                "Interested",
                "Not Contacted",
                "Has Phone",
                "Called",
                "Door Knocked",
                "Not Interested / Archived",
            ]
        )
        self.followup_quick_filter.currentTextChanged.connect(self._refresh_followups_tab)
        for widget in (
            self.followup_search_input,
            self.followup_status_filter,
            self.followup_city_filter,
            self.followup_quick_filter,
        ):
            controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)

        filter_help = QLabel(
            "Use filters to narrow the list. Use the buttons on each business card to update progress."
        )
        filter_help.setObjectName("FollowUpHelp")
        filter_help.setWordWrap(True)
        layout.addWidget(filter_help)

        self.followup_summary_label = QLabel("Saved businesses will appear here after you find businesses or save progress.")
        self.followup_summary_label.setObjectName("ResultsHint")
        self.followup_summary_label.setWordWrap(True)
        layout.addWidget(self.followup_summary_label)

        self.followup_scroll = QScrollArea()
        self.followup_scroll.setWidgetResizable(True)
        self.followup_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.followup_cards_widget = QWidget()
        self.followup_cards_layout = QVBoxLayout(self.followup_cards_widget)
        self.followup_cards_layout.setContentsMargins(2, 2, 2, 2)
        self.followup_cards_layout.setSpacing(12)
        self.followup_scroll.setWidget(self.followup_cards_widget)
        layout.addWidget(self.followup_scroll, 1)
        return tab

    def _build_scripts_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)
        intro = QLabel(
            "Practical scripts for door knocking, calling, follow-ups, and objections.\n"
            "Customize these scripts for your service, pricing, and market."
        )
        intro.setObjectName("ResultsHint")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        scripts_actions = QHBoxLayout()
        self.print_all_scripts_button = QPushButton("Print All Scripts")
        self.print_all_scripts_button.clicked.connect(self._print_all_scripts)
        self.print_selected_script_button = QPushButton("Print Selected Script")
        self.print_selected_script_button.clicked.connect(self._print_selected_script)
        self.export_scripts_pdf_button = QPushButton("Export Scripts as PDF")
        self.export_scripts_pdf_button.clicked.connect(self._export_scripts_pdf)
        scripts_actions.addWidget(self.print_all_scripts_button)
        scripts_actions.addWidget(self.print_selected_script_button)
        scripts_actions.addWidget(self.export_scripts_pdf_button)
        scripts_actions.addStretch()
        outer.addLayout(scripts_actions)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        scripts_layout = QVBoxLayout(content)
        scripts_layout.setSpacing(12)
        current_category = ""
        for script_index, script in enumerate(SALES_SCRIPTS):
            category = script.get("category", "Scripts")
            if category != current_category:
                category_label = QLabel(category)
                category_label.setObjectName("ScriptCategory")
                scripts_layout.addWidget(category_label)
                current_category = category
            card = QFrame()
            card.setObjectName("ScriptCard")
            card_layout = QVBoxLayout(card)
            title = QLabel(script["title"])
            title.setObjectName("ScriptTitle")
            use_case = QLabel(script["use_case"])
            use_case.setObjectName("ScriptUseCase")
            use_case.setWordWrap(True)
            text = QPlainTextEdit(script["text"])
            text.setReadOnly(True)
            text.setMinimumHeight(130)
            copy_button = QPushButton("Copy Script")
            copy_button.clicked.connect(
                lambda _checked=False, script_text=script["text"]: self._copy_script(script_text)
            )
            print_button = QPushButton("Print This Script")
            print_button.clicked.connect(
                lambda _checked=False, index=script_index: self._print_script_by_index(index)
            )
            card_layout.addWidget(title)
            card_layout.addWidget(use_case)
            card_layout.addWidget(text)
            card_layout.addWidget(copy_button, 0, Qt.AlignmentFlag.AlignRight)
            card_layout.addWidget(print_button, 0, Qt.AlignmentFlag.AlignRight)
            scripts_layout.addWidget(card)
            self._script_widgets[str(script_index)] = text
        scripts_layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        return tab

    def _copy_script(self, script_text: str) -> None:
        QApplication.clipboard().setText(script_text)
        self._toast("Script copied.")

    def _build_hidden_businesses_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        intro = QLabel(
            "Businesses hidden here are not deleted. They stay out of future searches until you restore them."
        )
        intro.setObjectName("ResultsHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        self.hidden_search_input = QLineEdit()
        self.hidden_search_input.setPlaceholderText("Search hidden businesses")
        self.hidden_search_input.textChanged.connect(self._refresh_hidden_businesses_tab)
        self.restore_hidden_button = QPushButton("Restore Selected")
        self.restore_hidden_button.clicked.connect(self._restore_selected_hidden_business)
        self.clear_hidden_button = QPushButton("Clear Hidden List")
        self.clear_hidden_button.clicked.connect(self._clear_hidden_businesses)
        controls.addWidget(self.hidden_search_input, 1)
        controls.addWidget(self.restore_hidden_button)
        controls.addWidget(self.clear_hidden_button)
        layout.addLayout(controls)

        self.hidden_businesses_list = QListWidget()
        self.hidden_businesses_list.setWordWrap(True)
        self.hidden_businesses_list.setSpacing(8)
        layout.addWidget(self.hidden_businesses_list, 1)
        return tab

    def _print_all_scripts(self) -> None:
        if print_scripts(self, SALES_SCRIPTS, "Preview Sales Scripts"):
            self._toast("Script preview opened.")

    def _print_selected_script(self) -> None:
        script = self._current_script_from_focus()
        if script is None:
            QMessageBox.information(self, "No script selected", "Click inside a script first, then print the selected script.")
            return
        if print_scripts(self, [script], "Preview Selected Script"):
            self._toast("Script preview opened.")

    def _print_script_by_index(self, index: int) -> None:
        if 0 <= index < len(SALES_SCRIPTS):
            print_scripts(self, [SALES_SCRIPTS[index]], "Preview Selected Script")

    def _export_scripts_pdf(self) -> None:
        selected_file, _ = QFileDialog.getSaveFileName(
            self,
            "Export Scripts as PDF",
            str(default_output_directory() / "routeforge_sales_scripts.pdf"),
            "PDF Files (*.pdf)",
        )
        if not selected_file:
            return
        export_scripts_pdf(SALES_SCRIPTS, selected_file)
        self._toast("Scripts PDF exported.")

    def _current_script_from_focus(self) -> dict[str, str] | None:
        focused = QApplication.focusWidget()
        for index_text, widget in self._script_widgets.items():
            if widget is focused:
                return SALES_SCRIPTS[int(index_text)]
        return None

    def _on_suppression_filter_toggled(self, checked: bool) -> None:
        for checkbox_name in ("hide_suppressed_checkbox", "simple_hide_suppressed_checkbox"):
            checkbox = getattr(self, checkbox_name, None)
            if isinstance(checkbox, QCheckBox) and checkbox.isChecked() != checked:
                checkbox.blockSignals(True)
                checkbox.setChecked(checked)
                checkbox.blockSignals(False)
        if self.original_leads or self.current_leads:
            self._reload_current_leads_view()

    def _hide_suppressed_enabled(self) -> bool:
        checkbox = getattr(self, "hide_suppressed_checkbox", None)
        return not isinstance(checkbox, QCheckBox) or checkbox.isChecked()

    def _apply_suppression_filter(self, leads: list[Lead]) -> list[Lead]:
        started = time.perf_counter()
        suppressed_entries = load_suppressed_businesses()
        hidden_count = 0
        visible: list[Lead] = []
        for lead in leads:
            match = suppression_match_for_lead_in_entries(lead, suppressed_entries)
            if match is None:
                visible.append(lead)
                continue
            marked_lead = replace(
                lead,
                is_suppressed=True,
                suppression_reason=str(match.get("reason", "Hidden")),
                suppression_date=str(match.get("date_hidden", "")),
            )
            if self._hide_suppressed_enabled():
                hidden_count += 1
                continue
            visible.append(marked_lead)
        if hidden_count:
            self._hidden_filter_message = (
                f"{hidden_count} businesses hidden because they were already worked or rejected."
            )
            self._append_progress(self._hidden_filter_message)
        else:
            self._hidden_filter_message = ""
        self.logger.info(
            "Suppression filter checked %s leads against %s hidden businesses in %.2fs",
            len(leads),
            len(suppressed_entries),
            time.perf_counter() - started,
        )
        return visible

    def _reload_current_leads_view(self) -> None:
        source_leads = self.original_leads or self.current_leads
        visible_leads = self._apply_suppression_filter(source_leads)
        summary = RunSummary(
            total_raw_leads=len(source_leads),
            total_leads=len(visible_leads),
            duplicates_removed=0,
            tier1_leads=sum(1 for lead in visible_leads if lead.priority_tier == "Tier 1"),
            output_path=self.latest_output_path or default_output_directory() / "routeforge_current.csv",
            leads=list(visible_leads),
        )
        self._populate_results_table(summary, update_original=False)

    def _refresh_hidden_businesses_tab(self, force: bool = False) -> None:
        if not hasattr(self, "hidden_businesses_list"):
            return
        if (
            not force
            and hasattr(self, "main_tabs")
            and self.main_tabs.currentIndex() != self.hidden_tab_index
        ):
            self._hidden_dirty = True
            return
        started = time.perf_counter()
        self.logger.info("Hidden Businesses refresh started")
        self._hidden_loaded = True
        self._hidden_dirty = False
        query = self.hidden_search_input.text().strip().lower() if hasattr(self, "hidden_search_input") else ""
        self.hidden_businesses_list.clear()
        for entry in load_suppressed_businesses():
            text = (
                f"{entry.get('business_name', 'Unnamed business')}\n"
                f"{entry.get('address', '')}\n"
                f"Phone: {entry.get('phone', '') or 'Not listed'} | "
                f"Hidden: {entry.get('reason', 'Hidden')} on {entry.get('date_hidden', '')}"
            )
            if query and query not in text.lower():
                continue
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setSizeHint(QSize(0, 78))
            self.hidden_businesses_list.addItem(item)
        self.logger.info("Hidden Businesses refresh finished in %.2fs", time.perf_counter() - started)

    def _restore_selected_hidden_business(self) -> None:
        item = self.hidden_businesses_list.currentItem()
        if item is None:
            QMessageBox.information(self, "No business selected", "Select a hidden business to restore.")
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(entry, dict):
            restore_suppressed_business(entry)
        self._refresh_hidden_businesses_tab()
        self._toast("Business restored.")

    def _clear_hidden_businesses(self) -> None:
        if QMessageBox.question(
            self,
            "Clear hidden businesses?",
            "This will unhide every hidden business. It will not delete saved progress. Continue?",
        ) != QMessageBox.StandardButton.Yes:
            return
        clear_suppressed_businesses()
        self._refresh_hidden_businesses_tab()
        self._toast("Hidden list cleared.")

    def _suppress_business(self, lead: Lead, reason: str) -> None:
        lead.status = reason if reason in FIELD_STATUS_OPTIONS else lead.status
        lead.is_suppressed = True
        lead.suppression_reason = reason
        lead.suppression_date = date.today().isoformat()
        if reason == "Already Worked":
            lead.status = "Customer"
        elif reason == "Do Not Show Again":
            lead.status = "Not Interested"
        elif reason == "Bad Lead":
            lead.status = "Bad Lead"
        save_suppressed_business(lead, reason)
        save_leads_in_app([lead])
        self._sync_lead_to_original_state(lead)
        if self._hide_suppressed_enabled():
            self.route_leads = [item for item in self.route_leads if _lead_key(item) != _lead_key(lead)]
            self._reload_current_leads_view()
        else:
            self._sync_lead_to_current_state(lead)
            self._populate_lead_cards(self.current_leads)
        self._refresh_hidden_businesses_tab()
        self._refresh_followups_tab()
        self._mark_map_dirty()
        self._refresh_map_view()
        self._update_action_states()
        self._toast("Hidden from future searches.")

    def _sync_lead_to_original_state(self, updated_lead: Lead) -> None:
        if not self.original_leads:
            return
        updated_key = _lead_key(updated_lead)
        self.original_leads = [
            replace(
                lead,
                status=updated_lead.status,
                notes=updated_lead.notes,
                last_contacted=updated_lead.last_contacted,
                next_follow_up_date=updated_lead.next_follow_up_date,
                contact_attempts=updated_lead.contact_attempts,
                contact_history=updated_lead.contact_history,
                contact_method_history=updated_lead.contact_method_history,
                route_stop_number=updated_lead.route_stop_number,
                is_suppressed=updated_lead.is_suppressed,
                suppression_reason=updated_lead.suppression_reason,
                suppression_date=updated_lead.suppression_date,
            )
            if _lead_key(lead) == updated_key
            else lead
            for lead in self.original_leads
        ]

    def _sync_original_from_current_view(self) -> None:
        if not self.current_leads:
            return
        if not self.original_leads:
            self.original_leads = list(self.current_leads)
            return
        current_by_key = {_lead_key(lead): lead for lead in self.current_leads}
        self.original_leads = [
            current_by_key.get(_lead_key(lead), lead)
            for lead in self.original_leads
        ]

    def _suppress_business_by_key(self, lead_key: str, reason: str) -> None:
        lead = self._lead_for_key(lead_key)
        if lead is None:
            QMessageBox.information(self, "Business not found", "This business could not be found.")
            return
        self._suppress_business(lead, reason)

    def _suppress_selected_business(self, reason: str) -> None:
        leads = self._checked_current_leads()
        if not leads and self.lead_card_list.currentItem() is not None:
            row_index = self.lead_card_list.currentItem().data(Qt.ItemDataRole.UserRole)
            if isinstance(row_index, int) and 0 <= row_index < len(self.current_leads):
                leads = [self.current_leads[row_index]]
        if not leads and self.results_table.currentRow() >= 0:
            row_index = self.results_table.currentRow()
            if 0 <= row_index < len(self.current_leads):
                leads = [self.current_leads[row_index]]
        if not leads:
            QMessageBox.information(self, "No business selected", "Select a business first.")
            return
        for lead in list(leads):
            self._suppress_business(lead, reason)

    def _clear_layout(self, layout: QVBoxLayout | QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _make_banner_row(
        self,
        message: str,
        actions: list[tuple[str, object]],
        priority: str = "ready",
    ) -> QFrame:
        row = QFrame()
        row.setObjectName("SmartBannerRow")
        row.setProperty("priority", priority)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 12, 16, 12)
        row_layout.setSpacing(10)
        label = QLabel(message)
        label.setObjectName("SmartBannerText")
        label.setWordWrap(True)
        row_layout.addWidget(label, 1)
        for label_text, handler in actions:
            button = QPushButton(label_text)
            button.setObjectName("SmartBannerButton")
            button.clicked.connect(handler)  # type: ignore[arg-type]
            row_layout.addWidget(button)
        row.style().unpolish(row)
        row.style().polish(row)
        return row

    def _refresh_smart_banner(self) -> None:
        if not hasattr(self, "smart_banner_layout"):
            return
        self._clear_layout(self.smart_banner_layout)

        due_count = self._due_followup_count(include_saved=self._followups_loaded)
        if due_count:
            self.smart_banner_layout.addWidget(
                self._make_banner_row(
                    f"You have {due_count} follow-up{'s' if due_count != 1 else ''} due today.",
                    [("View Follow-Ups", self._view_followups)],
                    priority="followup",
                )
            )

        if self.route_leads:
            stop_count = len(self.route_leads)
            self.smart_banner_layout.addWidget(
                self._make_banner_row(
                    f"You have {stop_count} stop{'s' if stop_count != 1 else ''} ready for today.",
                    [
                        ("Continue Route", self._show_route_mode),
                        ("Print Door-Knocking Sheet", self._export_route_sheet),
                        ("Open in Google Maps", self._start_route),
                    ],
                    priority="ready",
                )
            )
            return

        if self.current_leads:
            business_count = len(self.current_leads)
            self.smart_banner_layout.addWidget(
                self._make_banner_row(
                    f"You have {business_count} business{'es' if business_count != 1 else ''} ready. Build your route.",
                    [("Build My Day", self._build_my_day)],
                    priority="ready",
                )
            )
            return

        if self._saved_progress_exists_lightweight():
            self.smart_banner_layout.addWidget(
                self._make_banner_row(
                    "You have previous RouteForge saves available.",
                    [("Open Previous Save", self._open_previous_save_dialog)],
                    priority="ready",
                )
            )
            return

        if not due_count:
            self.smart_banner_layout.addWidget(
                self._make_banner_row(
                    "Let's find businesses to work today.",
                    [("Find Businesses", self._banner_find_businesses)],
                    priority="ready",
                )
            )

    def _banner_find_businesses(self) -> None:
        if self.simple_mode:
            self._start_simple_run()
            return
        self._start_run()

    def _view_followups(self) -> None:
        if self.main_tabs.currentIndex() == self.followups_tab_index:
            self._refresh_followups_tab(force=True)
            return
        self.main_tabs.setCurrentIndex(self.followups_tab_index)

    def _saved_progress_exists_lightweight(self) -> bool:
        try:
            return bool(list_saved_progress())
        except OSError:
            return False

    def _due_followup_count(self, include_saved: bool = True) -> int:
        indexed: dict[str, Lead] = {}
        saved_leads = load_saved_leads() if include_saved else []
        for lead in saved_leads + list(self.current_leads):
            indexed[_lead_key(lead)] = lead
        return sum(1 for lead in indexed.values() if _followup_due(lead))

    def _refresh_followups_tab(self, force: bool = False) -> None:
        if not hasattr(self, "followup_cards_layout"):
            return
        if (
            not force
            and hasattr(self, "main_tabs")
            and self.main_tabs.currentIndex() != self.followups_tab_index
        ):
            self._followups_dirty = True
            return
        started = time.perf_counter()
        self.logger.info("Follow-Ups refresh started")
        self._followups_loaded = True
        self._followups_dirty = False

        scroll_value = (
            self.followup_scroll.verticalScrollBar().value()
            if hasattr(self, "followup_scroll")
            else 0
        )
        lead_index: dict[tuple[str, str], Lead] = {}
        for lead in load_saved_leads() + list(self.current_leads):
            lead_index[(lead.business_name.strip().lower(), lead.full_address.strip().lower())] = lead
        leads = list(lead_index.values())

        current_city = self.followup_city_filter.currentText()
        cities = sorted({lead.city for lead in leads if lead.city})
        self.followup_city_filter.blockSignals(True)
        self.followup_city_filter.clear()
        self.followup_city_filter.addItem("Filter by City")
        self.followup_city_filter.addItems(cities)
        if current_city in ["Filter by City"] + cities:
            self.followup_city_filter.setCurrentText(current_city)
        self.followup_city_filter.blockSignals(False)

        query = self.followup_search_input.text().strip().lower()
        status_filter = self.followup_status_filter.currentText()
        city_filter = self.followup_city_filter.currentText()
        quick_filter = self.followup_quick_filter.currentText()

        filtered = []
        for lead in leads:
            haystack = " ".join(
                [lead.business_name, lead.full_address, lead.phone, lead.email]
            ).lower()
            if query and query not in haystack:
                continue
            if status_filter != "Filter by Status" and (lead.status or "New") != status_filter:
                continue
            if city_filter != "Filter by City" and lead.city != city_filter:
                continue
            if quick_filter == "Follow-Up Due" and not _followup_due(lead):
                continue
            if quick_filter == "Interested" and (lead.status or "") != "Interested":
                continue
            if quick_filter == "Not Contacted" and lead.last_contacted:
                continue
            if quick_filter == "Has Phone" and not lead.phone.strip():
                continue
            if quick_filter == "Called" and "called" not in _history_text(lead).lower() and lead.status != "Called":
                continue
            if quick_filter == "Door Knocked" and "door knocked" not in _history_text(lead).lower() and lead.status != "Door Knocked":
                continue
            if quick_filter == "Not Interested / Archived" and lead.status not in {"Not Interested", "Bad Lead", "Customer"}:
                continue
            filtered.append(lead)

        filtered.sort(key=_followup_sort_key)
        today = date.today()
        overdue = sum(1 for lead in leads if _lead_followup_date(lead) and _lead_followup_date(lead) < today)
        due_today = sum(1 for lead in leads if _lead_followup_date(lead) == today)
        interested = sum(1 for lead in leads if lead.status == "Interested")
        self.followup_summary_label.setText(
            f"{len(leads)} saved/tracked businesses. {overdue} overdue. {due_today} due today. {interested} interested."
        )

        self._clear_layout(self.followup_cards_layout)
        if not filtered:
            empty = QLabel("No follow-ups due yet.")
            empty.setObjectName("ResultsHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.followup_cards_layout.addWidget(empty)
            self.followup_cards_layout.addStretch()
            self.logger.info("Follow-Ups refresh finished in %.2fs", time.perf_counter() - started)
            return

        visible = filtered[:200]
        if len(filtered) > len(visible):
            notice = QLabel(
                f"Showing the first {len(visible)} matches. Use search or filters to narrow the list."
            )
            notice.setObjectName("FollowUpHelp")
            notice.setWordWrap(True)
            self.followup_cards_layout.addWidget(notice)

        current_group = ""
        for lead in visible:
            group = _followup_group_label(lead)
            if group != current_group:
                group_label = QLabel(group)
                group_label.setObjectName("FollowUpGroupLabel")
                self.followup_cards_layout.addWidget(group_label)
                current_group = group
            self.followup_cards_layout.addWidget(self._build_followup_card(lead))
        self.followup_cards_layout.addStretch()
        self.followup_scroll.verticalScrollBar().setValue(scroll_value)
        self.logger.info("Follow-Ups refresh finished in %.2fs", time.perf_counter() - started)

    def _build_followup_card(self, lead: Lead) -> QFrame:
        lead_key = _lead_key(lead)
        card = QFrame()
        card.setObjectName("FollowUpCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        name = QLabel(lead.business_name or "Unnamed business")
        name.setObjectName("FollowUpBusinessName")
        name.setWordWrap(True)
        address = QLabel(lead.full_address or "No address available")
        address.setObjectName("FollowUpMeta")
        address.setWordWrap(True)
        phone = QLabel(f"Phone: {lead.phone or 'No phone'}")
        phone.setObjectName("FollowUpMeta")
        card_layout.addWidget(name)
        card_layout.addWidget(address)
        card_layout.addWidget(phone)

        status_row = QHBoxLayout()
        status_label = QLabel("Status:")
        status_combo = QComboBox()
        status_combo.addItems(FIELD_STATUS_OPTIONS)
        if status_combo.findText(lead.status or "New") < 0:
            status_combo.addItem(lead.status or "New")
        status_combo.setCurrentText(lead.status or "New")
        status_combo.currentTextChanged.connect(
            lambda status, key=lead_key: self._update_followup_business(key, status=status)
        )
        followup_text = lead.next_follow_up_date or "Follow-up needed: no date set" if lead.status == "Follow Up" else lead.next_follow_up_date or "Not set"
        followup_label = QLabel(f"Follow-up Date: {followup_text}")
        followup_label.setObjectName("FollowUpMeta")
        set_date_button = QPushButton("Set Date")
        set_date_button.clicked.connect(
            lambda _checked=False, key=lead_key: self._set_followup_date_for_business(key)
        )
        status_row.addWidget(status_label)
        status_row.addWidget(status_combo)
        status_row.addSpacing(16)
        status_row.addWidget(followup_label)
        status_row.addWidget(set_date_button)
        status_row.addStretch()
        card_layout.addLayout(status_row)

        metric_row = QHBoxLayout()
        metric_row.addWidget(QLabel(f"Last Contacted: {lead.last_contacted or 'Not contacted'}"))
        metric_row.addSpacing(16)
        metric_row.addWidget(QLabel(f"Attempts: {lead.contact_attempts}"))
        metric_row.addStretch()
        card_layout.addLayout(metric_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        for button_text, status in FOLLOWUP_CARD_ACTIONS:
            button = QPushButton(button_text)
            button.clicked.connect(
                lambda _checked=False, key=lead_key, value=status: self._followup_action_clicked(key, value)
            )
            action_row.addWidget(button)
        for button_text, reason in (
            ("Already Worked", "Already Worked"),
            ("Do Not Show Again", "Do Not Show Again"),
            ("Bad Lead", "Bad Lead"),
        ):
            button = QPushButton(button_text)
            button.clicked.connect(
                lambda _checked=False, key=lead_key, value=reason: self._suppress_business_by_key(key, value)
            )
            action_row.addWidget(button)
        action_row.addStretch()
        card_layout.addLayout(action_row)

        notes_label = QLabel("Notes:")
        notes_box = QPlainTextEdit(lead.notes or "")
        notes_box.setObjectName("FollowUpNotes")
        notes_box.setPlaceholderText("Add quick notes from the call or visit.")
        notes_box.setMinimumHeight(58)
        notes_box.setMaximumHeight(86)
        save_notes_button = QPushButton("Save Notes")
        save_notes_button.clicked.connect(
            lambda _checked=False, key=lead_key, box=notes_box: self._update_followup_business(
                key,
                notes=box.toPlainText().strip(),
                add_history=False,
            )
        )
        card_layout.addWidget(notes_label)
        card_layout.addWidget(notes_box)
        card_layout.addWidget(save_notes_button, 0, Qt.AlignmentFlag.AlignRight)
        return card

    def _followup_action_clicked(self, lead_key: str, status: str) -> None:
        followup_date = None
        if status == "Follow Up":
            followup_date = self._prompt_follow_up_date()
        self._update_followup_business(lead_key, status=status, followup_date=followup_date)
        if status == "Follow Up" and not followup_date:
            self._toast("Follow-up needed: no date set.")

    def _set_followup_date_for_business(self, lead_key: str) -> None:
        followup_date = self._prompt_follow_up_date()
        if not followup_date:
            return
        self._update_followup_business(
            lead_key,
            followup_date=followup_date,
            history_message=f"Follow up scheduled for {followup_date}",
        )
        self._toast("Follow-up date saved.")

    def _update_followup_business(
        self,
        lead_key: str,
        status: str | None = None,
        followup_date: str | None = None,
        notes: str | None = None,
        add_history: bool = True,
        history_message: str | None = None,
    ) -> None:
        lead = self._lead_for_key(lead_key)
        if lead is None:
            QMessageBox.information(
                self,
                "Business not found",
                "This business could not be found in saved progress.",
            )
            return

        today = date.today().isoformat()
        if status is not None:
            lead.status = status
            if status != "New":
                lead.last_contacted = today
            if status in CONTACT_ATTEMPT_STATUSES:
                lead.contact_attempts += 1
            if status == "Follow Up" and followup_date is None:
                followup_date = self._prompt_follow_up_date()
        if followup_date is not None:
            lead.next_follow_up_date = followup_date
        if notes is not None:
            lead.notes = notes

        if add_history and (status is not None or followup_date is not None or history_message):
            history = lead.contact_history or []
            if history_message:
                entry = f"{today} - {history_message}"
            elif status == "Follow Up" and not lead.next_follow_up_date:
                entry = f"{today} - Follow Up - follow-up needed: no date set"
            elif status == "Follow Up" and lead.next_follow_up_date:
                entry = f"{today} - Follow Up scheduled for {lead.next_follow_up_date}"
            elif status:
                entry = f"{today} - {status}"
            else:
                entry = f"{today} - Follow up scheduled for {lead.next_follow_up_date}"
            history.append(entry)
            lead.contact_history = history[-20:]

            if status:
                method_history = lead.contact_method_history or []
                method_history.append(f"{today} - {status}")
                lead.contact_method_history = method_history[-20:]

        self._sync_lead_to_current_state(lead)
        save_leads_in_app([lead])
        self._populate_lead_cards(self.current_leads)
        self._mark_map_dirty()
        self._refresh_map_view()
        self._refresh_followups_tab()
        self._update_action_states()
        if status:
            self._toast(f"{lead.business_name or 'Business'} marked {status.lower()}.")

    def _lead_for_key(self, lead_key: str) -> Lead | None:
        for lead in self.current_leads:
            if _lead_key(lead) == lead_key:
                return lead
        for lead in load_saved_leads():
            if _lead_key(lead) == lead_key:
                return lead
        return None

    def _sync_lead_to_current_state(self, updated: Lead) -> None:
        key = _lead_key(updated)
        for lead in self.current_leads:
            if _lead_key(lead) == key:
                _copy_tracking_fields(updated, lead)
        for lead in self.route_leads:
            if _lead_key(lead) == key:
                _copy_tracking_fields(updated, lead)
        row_index = self._row_index_for_lead_key(key)
        if row_index >= 0:
            self._sync_table_row_from_lead(row_index, updated)

    def _row_index_for_lead_key(self, lead_key: str) -> int:
        if not hasattr(self, "results_table"):
            return -1
        for row_index in range(self.results_table.rowCount()):
            row_key = "|".join(
                (
                    self._table_text(row_index, self._table_column("Business Name")).strip().lower(),
                    self._table_text(row_index, self._table_column("Full Address")).strip().lower(),
                )
            )
            if row_key == lead_key:
                return row_index
        return -1

    def _sync_table_row_from_lead(self, row_index: int, lead: Lead) -> None:
        self.results_table.blockSignals(True)
        try:
            self._set_table_cell_text(row_index, "Status", lead.status or "New")
            status_widget = self.results_table.cellWidget(row_index, self._table_column("Status"))
            if isinstance(status_widget, QComboBox):
                status_widget.blockSignals(True)
                if status_widget.findText(lead.status or "New") < 0:
                    status_widget.addItem(lead.status or "New")
                status_widget.setCurrentText(lead.status or "New")
                status_widget.blockSignals(False)
            self._set_table_cell_text(row_index, "Notes", lead.notes or "")
            self._set_table_cell_text(row_index, "Last Contacted", lead.last_contacted or "")
            self._set_table_cell_text(row_index, "Next Follow-Up Date", lead.next_follow_up_date or "")
            self._set_table_cell_text(row_index, "Contact Attempts", str(lead.contact_attempts))
            self._set_table_cell_text(
                row_index,
                "Contact History Summary",
                "; ".join(lead.contact_history or []),
            )
            self._set_table_cell_text(
                row_index,
                "Contact Method History",
                "; ".join(lead.contact_method_history or []),
            )
            self._set_table_cell_text(row_index, "Hidden / Suppressed", "Yes" if lead.is_suppressed else "No")
            self._set_table_cell_text(row_index, "Hidden Reason", lead.suppression_reason or "")
        finally:
            self.results_table.blockSignals(False)

    def _set_default_table_widths(self) -> None:
        widths = {
            "Save": 64,
            "Stop #": 72,
            "Action Priority": 130,
            "Priority Tier": 100,
            "Business Name": 260,
            "Full Address": 340,
            "Phone": 140,
            "Lead Reason": 360,
            "Quick Notes": 320,
            "Category": 160,
            "City": 130,
            "Website": 240,
            "Email": 220,
            "Google Maps URL": 260,
            "Is Strip Mall": 110,
            "Same Address Count": 150,
            "Is Chain": 90,
            "Property Manager Lead": 150,
            "New / Pre-Opening Lead": 160,
            "Construction Opportunity": 170,
            "Hours of Operation": 190,
            "Recommended Visit Window": 180,
            "Status": 150,
            "Notes": 180,
            "Date Added": 120,
            "Last Contacted": 130,
            "Next Follow-Up Date": 150,
            "Contact Attempts": 130,
            "Contact History Summary": 320,
            "Contact Method History": 220,
            "Route Stop #": 110,
            "Source Keywords": 260,
        }
        for column_index, header in enumerate(TABLE_HEADERS):
            self.results_table.setColumnWidth(column_index, widths.get(header, 140))

    def _wire_column_scrollbar(self) -> None:
        table_scrollbar = self.results_table.horizontalScrollBar()
        table_scrollbar.rangeChanged.connect(self._sync_column_scrollbar_range)
        table_scrollbar.valueChanged.connect(self.column_scrollbar.setValue)
        self.column_scrollbar.valueChanged.connect(table_scrollbar.setValue)
        self._sync_column_scrollbar_range(
            table_scrollbar.minimum(),
            table_scrollbar.maximum(),
        )

    def _sync_column_scrollbar_range(self, minimum: int, maximum: int) -> None:
        self.column_scrollbar.setRange(minimum, maximum)
        self.column_scrollbar.setPageStep(self.results_table.viewport().width())
        self.column_scrollbar.setSingleStep(24)

    def _scroll_columns(self, delta: int) -> None:
        scrollbar = self.results_table.horizontalScrollBar()
        scrollbar.setValue(scrollbar.value() + delta)

    def _load_config_values(self) -> None:
        state_index = self.state_combo.findText(self.config.state)
        if state_index < 0:
            state_index = self.state_combo.findText("Michigan")
        self.state_combo.setCurrentIndex(state_index if state_index >= 0 else 0)
        self.cities_input.setText("")
        self.radius_combo.setCurrentText(
            "Nearby cities" if self.config.include_nearby_cities else "City only"
        )
        self.simple_state_combo.setCurrentIndex(state_index if state_index >= 0 else 0)
        self.simple_city_input.setText("")
        self.simple_radius_combo.setCurrentText(self.radius_combo.currentText())
        self.start_address_input.setText("")
        self._build_keyword_menu(self.config.search_keywords, checked_keywords=[])
        self._build_simple_keyword_menu(self.config.search_keywords, checked_keywords=self.config.search_keywords)
        self.custom_keywords_input.setText("")
        output_directory = self.config.output_directory
        if output_directory == "output":
            output_directory = default_output_directory()
        self.output_input.setText(output_directory)
        self._load_presets()
        self._load_routes()
        self._sync_single_city_choices()

    def _build_keyword_menu(
        self,
        keywords: list[str],
        checked_keywords: list[str] | None = None,
    ) -> None:
        self.keyword_menu.clear()
        self.keyword_actions = []
        checked_set = {keyword.lower().strip() for keyword in (checked_keywords or [])}
        for keyword in keywords:
            action = QAction(keyword, self.keyword_menu)
            action.setCheckable(True)
            action.setChecked(keyword.lower().strip() in checked_set)
            action.changed.connect(self._refresh_keyword_summary)
            self.keyword_menu.addAction(action)
            self.keyword_actions.append(action)

        if self.keyword_actions:
            self.keyword_menu.addSeparator()

        select_all_action = QAction("Select All", self.keyword_menu)
        clear_action = QAction("Clear All", self.keyword_menu)
        select_all_action.triggered.connect(lambda: self._set_all_keywords_checked(True))
        clear_action.triggered.connect(lambda: self._set_all_keywords_checked(False))
        self.keyword_menu.addAction(select_all_action)
        self.keyword_menu.addAction(clear_action)
        self._refresh_keyword_summary()

    def _build_simple_keyword_menu(
        self,
        keywords: list[str],
        checked_keywords: list[str] | None = None,
    ) -> None:
        self.simple_keyword_menu.clear()
        self.simple_keyword_actions = []
        checked_set = {keyword.lower().strip() for keyword in (checked_keywords or [])}
        for keyword in keywords:
            action = QAction(keyword, self.simple_keyword_menu)
            action.setCheckable(True)
            action.setChecked(keyword.lower().strip() in checked_set)
            action.changed.connect(self._refresh_simple_category_summary)
            self.simple_keyword_menu.addAction(action)
            self.simple_keyword_actions.append(action)

        if self.simple_keyword_actions:
            self.simple_keyword_menu.addSeparator()

        select_all_action = QAction("Select All", self.simple_keyword_menu)
        clear_action = QAction("Clear All", self.simple_keyword_menu)
        select_all_action.triggered.connect(lambda: self._set_simple_keywords_checked(True))
        clear_action.triggered.connect(lambda: self._set_simple_keywords_checked(False))
        self.simple_keyword_menu.addAction(select_all_action)
        self.simple_keyword_menu.addAction(clear_action)
        self._refresh_simple_category_summary()

    def _set_simple_keywords_checked(self, checked: bool) -> None:
        for action in self.simple_keyword_actions:
            action.setChecked(checked)
        self._refresh_simple_category_summary()

    def _set_all_keywords_checked(self, checked: bool) -> None:
        for action in self.keyword_actions:
            action.setChecked(checked)
        self._refresh_keyword_summary()

    def _selected_keywords(self) -> list[str]:
        selected = [action.text() for action in self.keyword_actions if action.isChecked()]
        selected.extend(_split_csv_text(self.custom_keywords_input.text()))
        seen: set[str] = set()
        deduped: list[str] = []
        for keyword in selected:
            key = keyword.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(keyword)
        return deduped

    def _selected_simple_category_keywords(self) -> list[str]:
        return [action.text() for action in self.simple_keyword_actions if action.isChecked()]

    def _apply_simple_category_filters(self) -> None:
        selected = {keyword.lower() for keyword in self._selected_simple_category_keywords()}
        if not selected:
            for action in self.keyword_actions:
                action.setChecked(False)
            return
        for action in self.keyword_actions:
            action.setChecked(action.text().lower() in selected)
        self._refresh_keyword_summary()

    def _refresh_simple_category_summary(self) -> None:
        if not hasattr(self, "simple_category_summary"):
            return
        labels = [action.text() for action in self.simple_keyword_actions if action.isChecked()]
        if not labels:
            self.simple_category_summary.setText("No business types selected. Choose at least one before finding businesses.")
            self.simple_keyword_button.setText("Choose Business Types")
            return
        preview = ", ".join(labels[:6])
        if len(labels) > 6:
            preview = f"{preview}, +{len(labels) - 6} more"
        self.simple_category_summary.setText(f"Searching {len(labels)} types: {preview}")
        self.simple_keyword_button.setText(f"{len(labels)} Business Types")

    def _refresh_keyword_summary(self) -> None:
        selected = self._selected_keywords()
        if not selected:
            self.keyword_summary.setText("Default daily mix")
            self.keyword_button.setText("Business Types")
            return

        preview = ", ".join(selected[:6])
        if len(selected) > 6:
            preview = f"{preview}, +{len(selected) - 6} more"
        self.keyword_summary.setText(preview)
        self.keyword_button.setText(f"{len(selected)} Types Selected")

    def _on_cities_changed(self) -> None:
        self._sync_single_city_choices()
        self._refresh_market_preview()

    def _on_mode_changed(self) -> None:
        self.single_city_combo.setEnabled(self.one_city_radio.isChecked())
        self._update_run_mode_labels()
        self._refresh_market_preview()

    def _update_run_mode_labels(self) -> None:
        all_marker = "[X]" if self.all_cities_radio.isChecked() else "[ ]"
        one_marker = "[X]" if self.one_city_radio.isChecked() else "[ ]"
        self.all_cities_radio.setText(f"{all_marker} Run all listed cities")
        self.one_city_radio.setText(f"{one_marker} Run one city")

    def _sync_single_city_choices(self) -> None:
        current = self.single_city_combo.currentText()
        self.single_city_combo.blockSignals(True)
        self.single_city_combo.clear()
        city_options = self._all_entered_cities() or self.config.cities
        self.single_city_combo.addItems(city_options)
        if current:
            index = self.single_city_combo.findText(current)
            if index >= 0:
                self.single_city_combo.setCurrentIndex(index)
            else:
                self.single_city_combo.setEditText(current)
        elif city_options:
            self.single_city_combo.setCurrentIndex(0)
        self.single_city_combo.blockSignals(False)

    def _refresh_market_preview(self) -> None:
        cities = self._selected_cities()
        city_text = ", ".join(cities) if cities else "No cities selected"
        self.market_preview.setText(
            f"Selected market: {self.state_combo.currentText()} | Cities: {city_text}"
        )

    def _load_presets(self) -> None:
        self.presets = load_presets()
        current = self.preset_combo.currentText().strip()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("Saved presets")
        for name in sorted(self.presets):
            self.preset_combo.addItem(name)
        if current and self.preset_combo.findText(current) >= 0:
            self.preset_combo.setCurrentText(current)
        else:
            self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _load_routes(self) -> None:
        self.routes = load_routes()
        current = self.route_combo.currentText().strip() if hasattr(self, "route_combo") else ""
        self.route_combo.blockSignals(True)
        self.route_combo.clear()
        self.route_combo.addItem("Saved routes")
        for name in sorted(self.routes):
            self.route_combo.addItem(name)
        if current and self.route_combo.findText(current) >= 0:
            self.route_combo.setCurrentText(current)
        else:
            self.route_combo.setCurrentIndex(0)
        self.route_combo.blockSignals(False)

    def _save_preset_dialog(self) -> None:
        suggested_name = f"{self.state_combo.currentText()} market"
        preset_name, accepted = QInputDialog.getText(
            self,
            "Save preset",
            "Preset name:",
            text=suggested_name,
        )
        preset_name = preset_name.strip()
        if not accepted or not preset_name:
            return

        payload = self._current_preset_payload()
        save_preset(preset_name, payload)
        self._load_presets()
        self.preset_combo.setCurrentText(preset_name)
        self._append_progress(f"Saved preset '{preset_name}'.")
        QMessageBox.information(
            self,
            "Preset saved",
            f"Saved preset '{preset_name}' for later use.",
        )

    def _apply_selected_preset(self) -> None:
        preset_name = self.preset_combo.currentText().strip()
        if not preset_name or preset_name == "Saved presets":
            QMessageBox.information(
                self,
                "Choose a preset",
                "Choose a saved preset first.",
            )
            return

        preset = self.presets.get(preset_name)
        if not preset:
            self._load_presets()
            QMessageBox.warning(
                self,
                "Preset not found",
                f"Could not find preset '{preset_name}'.",
            )
            return

        self._apply_preset(preset)
        self._append_progress(f"Loaded preset '{preset_name}'.")

    def _delete_selected_preset(self) -> None:
        preset_name = self.preset_combo.currentText().strip()
        if not preset_name or preset_name == "Saved presets":
            QMessageBox.information(
                self,
                "Choose a preset",
                "Choose a saved preset to delete.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Delete preset",
            f"Delete preset '{preset_name}'?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        delete_preset(preset_name)
        self._load_presets()
        self._append_progress(f"Deleted preset '{preset_name}'.")

    def _save_route_dialog(self) -> None:
        route_leads = self.route_leads or self._active_map_leads()
        if not route_leads:
            QMessageBox.information(self, "No route", "Build or filter a route before saving it.")
            return

        suggested_name = f"Today's Route {datetime.now().strftime('%Y-%m-%d')}"
        route_name, accepted = QInputDialog.getText(
            self,
            "Save today's route",
            "Route name:",
            text=suggested_name,
        )
        route_name = route_name.strip()
        if not accepted or not route_name:
            return

        save_route(route_name, route_leads)
        self._load_routes()
        self.route_combo.setCurrentText(route_name)
        self._append_progress(f"Saved route '{route_name}' with {len(route_leads)} leads.")
        QMessageBox.information(
            self,
            "Route saved",
            f"Saved route '{route_name}' with {len(route_leads)} leads.",
        )

    def _load_selected_route(self) -> None:
        route_name = self.route_combo.currentText().strip() if hasattr(self, "route_combo") else ""
        if not route_name or route_name == "Saved routes":
            QMessageBox.information(self, "Choose a route", "Choose a saved route first.")
            return

        leads = load_route(route_name)
        if not leads:
            self._load_routes()
            QMessageBox.warning(self, "Route not found", f"Could not find route '{route_name}'.")
            return

        summary = RunSummary(
            total_raw_leads=len(leads),
            total_leads=len(leads),
            duplicates_removed=0,
            tier1_leads=sum(1 for lead in leads if lead.priority_tier == "Tier 1"),
            output_path=self.latest_output_path or Path(""),
            leads=leads,
        )
        self._populate_results_table(summary)
        self.route_leads = plan_route(leads)
        self.route_current_index = 0
        self.route_completed_count = 0
        for row_index in range(self.results_table.rowCount()):
            item = self.results_table.item(row_index, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked)
        self._populate_lead_cards(self.current_leads)
        self.route_summary.setPlainText(build_route_text(self.route_leads))
        self.output_label.setText(f"Output file location\nSaved route: {route_name}")
        self.results_hint.setText(
            f"Loaded saved route '{route_name}'. Checked rows stay ready for field updates and export."
        )
        self.results_table.show()
        self._set_workflow_step(4)
        self._refresh_route_mode()
        self._update_action_states()
        self._refresh_map_view()
        self._show_route_mode()
        self._append_progress(f"Loaded route '{route_name}' with {len(leads)} leads.")

    def _delete_selected_route(self) -> None:
        route_name = self.route_combo.currentText().strip() if hasattr(self, "route_combo") else ""
        if not route_name or route_name == "Saved routes":
            QMessageBox.information(self, "Choose a route", "Choose a saved route to delete.")
            return

        answer = QMessageBox.question(
            self,
            "Delete route",
            f"Delete saved route '{route_name}'?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        delete_route(route_name)
        self._load_routes()
        self._append_progress(f"Deleted route '{route_name}'.")

    def _current_preset_payload(self) -> dict[str, object]:
        return {
            "state": self.state_combo.currentText(),
            "cities": self._all_entered_cities(),
            "search_keywords": self._selected_keywords(),
            "custom_keywords": self.custom_keywords_input.text().strip(),
            "output_directory": self.output_input.text().strip(),
            "run_mode": "one_city" if self.one_city_radio.isChecked() else "all_cities",
            "single_city": self.single_city_combo.currentText().strip(),
            "radius": self.radius_combo.currentText(),
        }

    def _apply_preset(self, preset: dict[str, object]) -> None:
        state = str(preset.get("state") or self.config.state)
        state_index = self.state_combo.findText(state)
        if state_index >= 0:
            self.state_combo.setCurrentIndex(state_index)

        cities = [str(city).strip() for city in preset.get("cities", []) if str(city).strip()]
        self.cities_input.setText(", ".join(cities))

        keywords = [str(keyword).strip() for keyword in preset.get("search_keywords", []) if str(keyword).strip()]
        if keywords:
            self._build_keyword_menu(self.config.search_keywords, checked_keywords=keywords)
            self._build_simple_keyword_menu(self.config.search_keywords, checked_keywords=keywords)
        else:
            self._build_keyword_menu(self.config.search_keywords, checked_keywords=[])
            self._build_simple_keyword_menu(self.config.search_keywords, checked_keywords=self.config.search_keywords)

        self.custom_keywords_input.setText(str(preset.get("custom_keywords", "")).strip())
        self.radius_combo.setCurrentText(str(preset.get("radius") or self.radius_combo.currentText()))
        self.output_input.setText(
            str(preset.get("output_directory") or self.output_input.text()).strip()
        )

        run_mode = str(preset.get("run_mode") or "all_cities")
        self.one_city_radio.setChecked(run_mode == "one_city")
        self.all_cities_radio.setChecked(run_mode != "one_city")
        self._sync_single_city_choices()

        single_city = str(preset.get("single_city", "")).strip()
        if single_city:
            self.single_city_combo.setEditText(single_city)
        self._refresh_market_preview()

    def _choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose where CSV files should be saved",
            self.output_input.text() or str(Path.cwd()),
        )
        if folder:
            self.output_input.setText(folder)

    def _start_run(self) -> None:
        cities = self._selected_cities()
        if not cities:
            if self.one_city_radio.isChecked():
                message = "Type one city in the Single City box before running."
            else:
                message = "Enter at least one city in the Cities box before running."
            QMessageBox.warning(self, "Add a city", message)
            return

        output_folder = self.output_input.text().strip() or "output"
        entered_cities = self._all_entered_cities()
        saved_city_options = entered_cities or self.config.cities
        for city in cities:
            if city and city.lower() not in {saved_city.lower() for saved_city in saved_city_options}:
                saved_city_options.append(city)

        config = replace(
            self.config,
            state=self.state_combo.currentText(),
            cities=saved_city_options,
            search_keywords=self._selected_keywords(),
            include_nearby_cities=self.radius_combo.currentText() == "Nearby cities",
            output_directory=output_folder,
        )
        self.config = config
        save_config(config)

        self.run_button.setEnabled(False)
        self.simple_generate_button.setEnabled(False)
        self.current_leads = []
        self.original_leads = []
        self.route_leads = []
        self.open_csv_button.setEnabled(False)
        self.export_checked_button.setEnabled(False)
        self.build_my_day_button.setEnabled(False)
        self.route_button.setEnabled(False)
        self.open_google_route_button.setEnabled(False)
        self.export_route_button.setEnabled(False)
        self.print_call_sheet_button.setEnabled(False)
        self.start_route_button.setEnabled(False)
        if hasattr(self, "map_route_button"):
            self.map_route_button.setEnabled(False)
        self._set_workflow_step(2)
        self.main_tabs.setCurrentIndex(1)
        self._set_results_hint_compact(False)
        self.results_hint.setText("Generating leads. Results will appear here when the run finishes.")
        self.simple_start_card.hide()
        self.results_table.hide()
        self.lead_card_list.hide()
        self.lead_card_list.clear()
        self.selection_bar.hide()
        self.results_hint.show()
        self.generation_progress.show()
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(0)
        self._set_default_table_widths()
        self.results_table.setSortingEnabled(True)
        self.progress_log.clear()
        self._append_progress("Preparing your business search...")

        self.worker_thread = QThread(self)
        self.worker = LeadGenerationWorker(config, cities, output_folder)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._append_progress)
        self.worker.finished.connect(self._finish_run)
        self.worker.failed.connect(self._fail_run)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    def _start_simple_run(self) -> None:
        city = self.simple_city_input.text().strip()
        if not city:
            QMessageBox.information(self, "Add a city", "Enter the city you want to work today.")
            return
        if not self._selected_simple_category_keywords():
            QMessageBox.information(self, "Choose business types", "Select at least one business type before finding businesses.")
            return
        self.state_combo.setCurrentText(self.simple_state_combo.currentText())
        self.cities_input.setText(city)
        self.radius_combo.setCurrentText(self.simple_radius_combo.currentText())
        self._apply_simple_category_filters()
        self.all_cities_radio.setChecked(True)
        self._start_run()

    @Slot(str)
    def _append_progress(self, message: str) -> None:
        self.progress_log.appendPlainText(message)

    @Slot(object)
    def _finish_run(self, summary: RunSummary) -> None:
        self.generation_progress.hide()
        try:
            self.latest_output_path = summary.output_path
            self.total_label.setText(f"Businesses found\n{summary.total_leads}")
            self.duplicates_label.setText(f"Duplicates removed\n{summary.duplicates_removed}")
            self.tier1_label.setText(f"Tier 1 leads\n{summary.tier1_leads}")
            self.incomplete_address_label.setText(
                f"Incomplete addresses excluded\n{summary.excluded_incomplete_address}"
            )
            self.city_mismatch_label.setText(
                f"Out-of-city leads excluded\n{summary.excluded_city_mismatch}"
            )
            self.state_mismatch_label.setText(
                f"Out-of-state leads excluded\n{summary.excluded_state_mismatch}"
            )
            self.strip_clusters_label.setText(
                f"Strip mall clusters\n{summary.strip_mall_clusters}"
            )
            self.high_confidence_plazas_label.setText(
                f"High-confidence plazas\n{summary.high_confidence_plazas}"
            )
            self.low_value_filtered_label.setText(
                f"Low-value leads filtered\n{summary.excluded_low_value_category}"
            )
            self.output_label.setText(f"Output file location\n{summary.output_path}")
            self._populate_results_table(summary)
            self._save_tracker_state()
            self._refresh_followups_tab()
            self._set_results_hint_compact(True)
            hidden_note = f" {self._hidden_filter_message}" if self._hidden_filter_message else ""
            self.results_hint.setText(
                f"{len(self.current_leads)} businesses ready.{hidden_note} Click Build My Day for a field route. "
                "Some businesses may have incomplete address/contact data. Review before visiting. "
                "Missing emails are normal. Phone, address, and route order matter most for field sales."
            )
            city_text = ", ".join(self._selected_cities()) or self.state_combo.currentText()
            self._append_progress(f"{len(self.current_leads)} businesses ready in {city_text}.")
            self._toast(f"{len(self.current_leads)} businesses ready in {city_text}.")
            self._set_workflow_step(3 if self.current_leads else 1)
            self.main_tabs.setCurrentIndex(1 if self.current_leads else 0)
            self._update_action_states()
        except Exception as exc:
            self.logger.exception("Could not display generated leads")
            self._append_progress(
                "The CSV was created, but the in-app table could not be displayed."
            )
            QMessageBox.warning(
                self,
                "CSV saved",
                (
                    "The CSV was created, but the business list could not be displayed "
                    f"inside the app.\n\nSaved file:\n{summary.output_path}\n\n{exc}"
                ),
            )
            self.open_csv_button.setEnabled(True)
        finally:
            self.run_button.setEnabled(True)
            self.simple_generate_button.setEnabled(True)
            self.simple_start_card.setVisible(self.simple_mode)
            self._update_action_states()

    @Slot(str)
    def _fail_run(self, message: str) -> None:
        self.generation_progress.hide()
        self._append_progress(message)
        self.run_button.setEnabled(True)
        self.simple_generate_button.setEnabled(True)
        self.simple_start_card.setVisible(self.simple_mode)
        self._set_workflow_step(1)
        self._update_action_states()
        QMessageBox.warning(self, "Business search stopped", message)

    @Slot()
    def _cleanup_worker(self) -> None:
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        if self.worker_thread:
            self.worker_thread.deleteLater()
            self.worker_thread = None

    def _open_latest_csv(self) -> None:
        if self.latest_output_path and self.latest_output_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.latest_output_path)))

    def _save_checked_in_app(self) -> None:
        leads = self._leads_from_table(checked_only=True)
        if not leads:
            QMessageBox.information(self, "No businesses selected", "Select at least one business to save.")
            return

        saved_path = save_leads_in_app(leads)
        self._refresh_followups_tab()
        self._append_progress(f"Saved {len(leads)} selected businesses inside the app.")
        QMessageBox.information(
            self,
            "Progress saved",
            f"Saved {len(leads)} businesses for later.\n\nStorage file:\n{saved_path}",
        )

    def _progress_leads_for_save(self) -> list[Lead]:
        if self.current_leads:
            return list(self.current_leads)
        table_leads = self._leads_from_table(checked_only=False)
        if table_leads:
            return table_leads
        return list(self.route_leads)

    def _save_progress(self) -> None:
        if self.current_progress_save_name:
            self._save_progress_named(self.current_progress_save_name, show_message=True)
            return
        self._save_progress_as()

    def _save_progress_as(self) -> None:
        leads = self._progress_leads_for_save()
        if not leads and not self.route_leads:
            QMessageBox.information(
                self,
                "Nothing to save yet",
                "Find businesses or build a route before saving progress.",
            )
            return
        default_name = self.current_progress_save_name or f"RouteForge {date.today().isoformat()}"
        name, ok = QInputDialog.getText(
            self,
            "Save progress as",
            "Name this save:",
            text=default_name,
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.information(self, "Name required", "Enter a short name for this save.")
            return
        self._save_progress_named(name, show_message=True)

    def _save_progress_named(self, name: str, show_message: bool = False) -> None:
        leads = self._progress_leads_for_save()
        if not leads and not self.route_leads:
            QMessageBox.information(
                self,
                "Nothing to save yet",
                "Find businesses or build a route before saving progress.",
            )
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            saved_path = save_progress_snapshot(
                name,
                leads,
                self.route_leads,
                self.route_current_index,
                self.route_completed_count,
            )
            save_leads_in_app(leads)
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", f"RouteForge could not save this progress.\n\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.current_progress_save_name = name
        self._append_progress(f"Saved progress '{name}'.")
        self._toast(f"Saved '{name}'.")
        if show_message:
            QMessageBox.information(
                self,
                "Progress saved",
                f"Saved '{name}' for later.\n\nSave file:\n{saved_path}",
            )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._tracker_save_timer.isActive():
            self._tracker_save_timer.stop()
        if self._tracker_save_pending:
            self._flush_tracker_state()
        super().closeEvent(event)

    def _open_previous_save_dialog(self) -> None:
        saves = list_saved_progress()
        if not saves:
            QMessageBox.information(
                self,
                "No previous saves",
                "No named saves were found yet. Use File > Save As to create one.",
            )
            return
        labels = []
        for name, meta in saves.items():
            saved_at = str(meta.get("saved_at") or "unknown time")
            lead_count = meta.get("lead_count", 0)
            labels.append(f"{name}  ({lead_count} businesses, {saved_at})")
        selected, ok = QInputDialog.getItem(
            self,
            "Open previous save",
            "Choose a RouteForge save:",
            labels,
            0,
            False,
        )
        if not ok or not selected:
            return
        save_name = selected.split("  (", 1)[0]
        self.statusBar().showMessage("Loading saved progress...")
        QApplication.processEvents()
        try:
            snapshot = load_progress_snapshot(save_name)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Could not open save", f"RouteForge could not open that save.\n\n{exc}")
            return
        self._load_progress_snapshot(snapshot, fallback_name=save_name)

    def _load_progress_snapshot(self, snapshot: dict[str, object], fallback_name: str = "") -> None:
        leads = list(snapshot.get("leads") or [])
        route_leads = list(snapshot.get("route_leads") or [])
        if not leads and route_leads:
            leads = list(route_leads)
        if not leads:
            QMessageBox.information(self, "No businesses found", "That save did not contain any businesses.")
            return

        summary = RunSummary(
            total_raw_leads=len(leads),
            total_leads=len(leads),
            duplicates_removed=0,
            tier1_leads=sum(1 for lead in leads if lead.priority_tier == "Tier 1"),
            output_path=self.latest_output_path or Path(""),
            leads=leads,
        )
        self._populate_results_table(summary)
        self.route_leads = route_leads
        self.route_current_index = min(
            int(snapshot.get("route_current_index") or 0),
            max(len(self.route_leads) - 1, 0),
        )
        self.route_completed_count = min(
            int(snapshot.get("route_completed_count") or 0),
            len(self.route_leads),
        )
        route_keys = {_lead_key(lead) for lead in self.route_leads}
        for row_index, lead in enumerate(self.current_leads):
            item = self.results_table.item(row_index, 0)
            if item and _lead_key(lead) in route_keys:
                item.setCheckState(Qt.CheckState.Checked)
        self._populate_lead_cards(self.current_leads)
        self.route_summary.setPlainText(
            build_route_text(self.route_leads)
            if self.route_leads
            else "Build a route to see a simple field order here."
        )
        self.current_progress_save_name = str(snapshot.get("name") or fallback_name or "").strip() or None
        self.output_label.setText(
            f"Output file location\nSaved progress: {self.current_progress_save_name or 'Previous save'}"
        )
        self.results_hint.setText(
            f"Loaded {len(leads)} businesses from '{self.current_progress_save_name or 'previous save'}'."
        )
        self.main_tabs.setCurrentIndex(self.route_tab_index if self.route_leads else 1)
        self._set_workflow_step(5 if self.route_leads else 3)
        self._set_results_hint_compact(True)
        self.lead_card_list.setVisible(self.simple_mode and bool(self.current_leads))
        self.results_table.setVisible(not self.simple_mode and bool(self.current_leads))
        self.selection_bar.setVisible(self.simple_mode and bool(self.current_leads))
        self._refresh_route_mode()
        self._refresh_followups_tab()
        self._mark_map_dirty()
        self._refresh_map_view()
        self._update_action_states()
        self._append_progress(f"Opened save '{self.current_progress_save_name or fallback_name}' with {len(leads)} businesses.")
        self._toast(f"Opened {len(leads)} businesses.")

    def _apply_status_to_checked(self, status: str) -> None:
        rows = self._checked_row_indexes()
        if not rows:
            QMessageBox.information(
                self,
                "No businesses selected",
                "Select at least one business before updating field status.",
            )
            return

        today = datetime.now().strftime("%Y-%m-%d")
        for row_index in rows:
            status_item = self.results_table.item(row_index, self._table_column("Status"))
            last_contacted_item = self.results_table.item(
                row_index, self._table_column("Last Contacted")
            )
            notes_item = self.results_table.item(row_index, self._table_column("Notes"))
            if status_item:
                status_item.setText(status)
            if last_contacted_item and status != "New":
                last_contacted_item.setText(today)
            if notes_item and status == "Interested" and not notes_item.text().strip():
                notes_item.setText("Interested. Follow up with quote/details.")
            if notes_item and status == "Follow Up" and not notes_item.text().strip():
                notes_item.setText("Follow up needed.")

        self.current_leads = self._leads_from_table(checked_only=False)
        self._sync_original_from_current_view()
        self.route_leads = [
            lead
            for lead in self.current_leads
            if any(
                lead.business_name == route_lead.business_name
                and lead.full_address == route_lead.full_address
                for route_lead in self.route_leads
            )
        ]
        self._refresh_map_view()
        self._append_progress(f"Updated {len(rows)} selected businesses to '{status}'.")
        self._update_action_states()
        self._toast(f"{len(rows)} lead(s) marked {status.lower()}.")

    def _mark_checked_outcome(self, status: str) -> None:
        rows = self._checked_row_indexes()
        if not rows:
            QMessageBox.information(
                self,
                "No businesses selected",
                "Select one or more businesses before marking an outcome.",
            )
            return

        followup_date = ""
        if status == "Follow Up":
            followup_date = self._prompt_follow_up_date()
            if not followup_date:
                return

        self._update_tracker_rows(rows, status, followup_date=followup_date)
        self._toast(f"{len(rows)} lead(s) marked {status.lower()}.")

    def _set_follow_up_for_checked(self) -> None:
        rows = self._checked_row_indexes()
        if not rows:
            QMessageBox.information(
                self,
                "No businesses selected",
                "Select one or more businesses before setting a follow-up date.",
            )
            return
        followup_date = self._prompt_follow_up_date()
        if not followup_date:
            return
        self._update_tracker_rows(rows, "Follow Up", followup_date=followup_date)
        self._toast(f"Follow-up date set for {len(rows)} lead(s).")

    def _prompt_follow_up_date(self) -> str:
        default_date = date.today().isoformat()
        value, ok = QInputDialog.getText(
            self,
            "Set follow-up date",
            "Enter follow-up date as YYYY-MM-DD:",
            text=default_date,
        )
        if not ok:
            return ""
        value = value.strip()
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            QMessageBox.warning(
                self,
                "Use YYYY-MM-DD",
                "Please enter the follow-up date like 2026-05-06.",
            )
            return ""
        return value

    def _update_tracker_rows(
        self,
        rows: list[int],
        status: str,
        followup_date: str = "",
    ) -> None:
        today = date.today().isoformat()
        increments_attempt = status in {"Called", "Door Knocked"}
        self.results_table.blockSignals(True)
        for row_index in rows:
            self._set_table_cell_text(row_index, "Status", status)
            status_widget = self.results_table.cellWidget(row_index, self._table_column("Status"))
            if isinstance(status_widget, QComboBox):
                status_widget.blockSignals(True)
                status_widget.setCurrentText(status)
                status_widget.blockSignals(False)
            if status != "New":
                self._set_table_cell_text(row_index, "Last Contacted", today)
            if followup_date:
                self._set_table_cell_text(row_index, "Next Follow-Up Date", followup_date)
            attempts = _safe_int(
                self._table_text(row_index, self._table_column("Contact Attempts")),
                0,
            )
            if increments_attempt:
                attempts += 1
                self._set_table_cell_text(row_index, "Contact Attempts", str(attempts))
            history = _split_history_text(
                self._table_text(row_index, self._table_column("Contact History Summary"))
            )
            history_note = f"{today} - {status}"
            if followup_date:
                history_note = f"{today} - Follow up scheduled for {followup_date}"
            history.append(history_note)
            self._set_table_cell_text(
                row_index,
                "Contact History Summary",
                "; ".join(history[-20:]),
            )
            if status in {"Called", "Door Knocked", "Interested", "Follow Up", "Not Interested"}:
                method_history = _split_history_text(
                    self._table_text(row_index, self._table_column("Contact Method History"))
                )
                method_history.append(f"{today} - {status}")
                self._set_table_cell_text(
                    row_index,
                    "Contact Method History",
                    "; ".join(method_history[-20:]),
                )
        self.results_table.blockSignals(False)

        self.current_leads = self._leads_from_table(checked_only=False)
        self._sync_original_from_current_view()
        self.route_leads = [
            self._matching_current_lead(route_lead) or route_lead
            for route_lead in self.route_leads
        ]
        self._populate_lead_cards(self.current_leads)
        self._save_tracker_state()
        self._refresh_followups_tab()
        self._mark_map_dirty()
        self._refresh_map_view()
        self._update_action_states()

    def _matching_current_lead(self, lead: Lead) -> Lead | None:
        key = _lead_key(lead)
        for current in self.current_leads:
            if _lead_key(current) == key:
                return current
        return None

    def _set_table_cell_text(self, row_index: int, header: str, text: str) -> None:
        column_index = self._table_column(header)
        item = self.results_table.item(row_index, column_index)
        if item is None:
            item = QTableWidgetItem("")
            self.results_table.setItem(row_index, column_index, item)
        item.setText(text)

    def _save_tracker_state(self) -> None:
        if not self.current_leads:
            return
        self._tracker_save_pending = True
        self._tracker_save_timer.start(750)

    def _flush_tracker_state(self) -> None:
        if not self._tracker_save_pending or not self.current_leads:
            return
        self._tracker_save_pending = False
        try:
            save_leads_in_app(self.current_leads)
            if self.current_progress_save_name:
                save_progress_snapshot(
                    self.current_progress_save_name,
                    self.current_leads,
                    self.route_leads,
                    self.route_current_index,
                    self.route_completed_count,
                )
        except OSError as exc:
            self._append_progress(f"Could not save tracker state: {exc}")

    def _export_checked_csv(self) -> None:
        leads = self._leads_from_table(checked_only=True)
        if not leads:
            QMessageBox.information(self, "No businesses selected", "Select at least one business to export.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = Path(self.output_input.text().strip() or default_output_directory())
        default_file = default_path / f"checked_leads_{timestamp}.csv"
        selected_file, _ = QFileDialog.getSaveFileName(
            self,
            "Export selected businesses to CSV",
            str(default_file),
            "CSV Files (*.csv)",
        )
        if not selected_file:
            return

        saved_path = export_csv(leads, selected_file)
        self.latest_output_path = saved_path
        self.open_csv_button.setEnabled(True)
        self.output_label.setText(f"Output file location\n{saved_path}")
        self._append_progress(f"Exported {len(leads)} selected businesses to {saved_path}.")
        self._toast("Export complete.")
        QMessageBox.information(self, "Export complete", f"Full data export saved:\n{saved_path}")

    def _print_leads(self) -> None:
        leads = self._active_map_leads()
        if not leads:
            QMessageBox.information(self, "No businesses", "There are no businesses to print yet.")
            return
        if print_leads(self, leads, "RouteForge"):
            self._append_progress(f"Opened print preview for {len(leads)} businesses.")

    def _print_mapped_leads(self) -> None:
        leads = self.route_leads or self._active_map_leads()
        if not leads:
            QMessageBox.information(self, "No route order", "There are no businesses in the route order to print yet.")
            return
        if print_mapped_leads(self, leads):
            self._append_progress(f"Opened route order printout for {len(leads)} businesses.")
            self._toast("Print preview opened.")

    def _print_call_sheet(self) -> None:
        source_leads = self.route_leads or self._checked_current_leads() or self.current_leads
        leads = [lead for lead in source_leads if lead.phone.strip()]
        if not leads:
            QMessageBox.information(
                self,
                "No phone numbers",
                "No selected leads have phone numbers yet. Generate or select more leads first.",
            )
            return
        if print_call_sheet(self, leads):
            self._append_progress(f"Opened call list preview with {len(leads)} phone numbers.")
            self._toast("Print preview opened.")

    def _export_leads_pdf(self) -> None:
        leads = self._active_map_leads()
        if not leads:
            QMessageBox.information(self, "No businesses", "There are no businesses to export yet.")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = Path(self.output_input.text().strip() or default_output_directory())
        selected_file, _ = QFileDialog.getSaveFileName(
            self,
            "Export leads as PDF",
            str(default_path / f"field_leads_{timestamp}.pdf"),
            "PDF Files (*.pdf)",
        )
        if not selected_file:
            return
        saved_path = export_leads_pdf(
            leads,
            selected_file,
            "RouteForge",
        )
        self._append_progress(f"Saved lead PDF to {saved_path}.")
        QMessageBox.information(self, "PDF saved", f"Saved lead PDF to:\n{saved_path}")

    def _export_map_pdf(self) -> None:
        leads = self._active_map_leads()
        if not leads:
            QMessageBox.information(self, "No businesses", "There are no businesses in the route list to export.")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = Path(self.output_input.text().strip() or default_output_directory())
        selected_file, _ = QFileDialog.getSaveFileName(
            self,
            "Export route order as PDF",
            str(default_path / f"route_order_{timestamp}.pdf"),
            "PDF Files (*.pdf)",
        )
        if not selected_file:
            return
        saved_path = export_leads_pdf(leads, selected_file, "RouteForge Route Order")
        self._on_map_pdf_exported(str(saved_path))

    def _on_map_pdf_exported(self, path: str) -> None:
        self._append_progress(f"Saved route order PDF to {path}.")
        QMessageBox.information(self, "Route order PDF saved", f"Saved route order PDF to:\n{path}")

    def _build_route_plan(self) -> None:
        if not self.current_leads:
            self.route_summary.setPlainText("No route available yet.")
            QMessageBox.information(
                self,
                "No businesses yet",
                "Find businesses before building a route.",
            )
            return
        leads = self._checked_current_leads()
        if not leads:
            QMessageBox.information(
                self,
                "No businesses selected",
                "No businesses selected. Click businesses in the list or use Build My Day.",
            )
            return
        start_address = self._route_start_address()
        start_location = None
        if start_address:
            self._toast("Checking the start address for route order...")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                start_location = geocode_start_address(
                    start_address,
                    self.state_combo.currentText(),
                )
            finally:
                QApplication.restoreOverrideCursor()
            if start_location is None:
                self._toast("Start address could not be located. Route optimized between selected stops.")
        self.route_leads = plan_route(leads, start_location=start_location)
        self.route_current_index = 0
        self.route_completed_count = 0
        self._assign_route_stop_numbers()
        self.current_leads = self._leads_from_table(checked_only=False)
        self._sync_original_from_current_view()
        self._save_tracker_state()
        self._refresh_followups_tab()
        self.route_summary.setPlainText(build_route_text(self.route_leads))
        estimate = self._route_time_estimate_text(self.route_leads)
        self.route_summary.appendPlainText(f"\n{estimate}")
        self._set_workflow_step(4)
        start_note = f" from {start_address}" if start_address and start_location else ""
        self._append_progress(
            f"Efficient driving route created with {len(self.route_leads)} stops{start_note}. {estimate}"
        )
        self._toast(f"Efficient route created. {estimate}")
        self._refresh_route_mode()
        self._show_route_mode()
        self._mark_map_dirty()
        self._refresh_map_view()
        self._update_action_states()

    def _build_my_day(self) -> None:
        if not self.current_leads:
            QMessageBox.information(
                self,
                "No businesses yet",
                "Find businesses first, then Build My Day will choose the best stops.",
            )
            return

        ranked: list[tuple[int, int, Lead]] = []
        for row_index, lead in enumerate(self.current_leads):
            score = _build_my_day_score(lead)
            if score <= -9000:
                continue
            ranked.append((score, row_index, lead))
        ranked.sort(key=lambda item: item[0], reverse=True)

        if not ranked:
            QMessageBox.information(
                self,
                "No usable leads",
                "No usable leads are available. Check statuses or generate a fresh list.",
            )
            return

        target_count = min(30, len(ranked))
        if len(ranked) > 20:
            target_count = max(20, target_count)
        selected_rows = {row_index for _score, row_index, _lead in ranked[:target_count]}

        self.results_table.blockSignals(True)
        self.lead_card_list.blockSignals(True)
        for row_index in range(self.results_table.rowCount()):
            save_item = self.results_table.item(row_index, 0)
            if save_item:
                save_item.setCheckState(
                    Qt.CheckState.Checked
                    if row_index in selected_rows
                    else Qt.CheckState.Unchecked
                )
        self.results_table.blockSignals(False)
        self.lead_card_list.blockSignals(False)

        selected_leads = [lead for _score, _row, lead in ranked[:target_count]]
        start_address = self._route_start_address()
        start_location = None
        if start_address:
            self._toast("Checking the start address for route order...")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                start_location = geocode_start_address(
                    start_address,
                    self.state_combo.currentText(),
                )
            finally:
                QApplication.restoreOverrideCursor()
            if start_location is None:
                self._toast("Start address could not be located. Route optimized between selected stops.")

        self.route_leads = plan_route(selected_leads, start_location=start_location)
        self.route_current_index = 0
        self.route_completed_count = 0
        self._assign_route_stop_numbers()
        self.current_leads = self._leads_from_table(checked_only=False)
        self._sync_original_from_current_view()
        self._save_tracker_state()
        self._refresh_followups_tab()
        self._populate_lead_cards(self.current_leads)
        self.route_summary.setPlainText(build_route_text(self.route_leads))
        estimate = self._route_time_estimate_text(self.route_leads)
        self.route_summary.appendPlainText(f"\n{estimate}")
        self._refresh_route_mode()
        self._mark_map_dirty()
        self._refresh_map_view()
        self._show_route_mode()

        phone_count = sum(1 for lead in self.route_leads if lead.phone.strip())
        mapped_count = sum(
            1
            for lead in self.route_leads
            if lead.latitude is not None and lead.longitude is not None
        )
        plaza_count = sum(
            1
            for lead in self.route_leads
            if lead.is_strip_mall or lead.same_address_count >= 3
        )
        summary = (
            f"Built a {len(self.route_leads)}-stop route. "
            f"{phone_count} have phone numbers. "
            f"{mapped_count} are mapped. "
            f"{plaza_count} are plaza/strip mall stops. "
            f"{estimate}"
        )
        self.results_hint.setText(summary)
        self._append_progress(summary)
        self._toast(summary)
        self._update_action_states()

    def _clear_selection(self) -> None:
        if not hasattr(self, "results_table"):
            return
        self.results_table.blockSignals(True)
        self.lead_card_list.blockSignals(True)
        for row_index in range(self.results_table.rowCount()):
            save_item = self.results_table.item(row_index, 0)
            if save_item:
                save_item.setCheckState(Qt.CheckState.Unchecked)
        for item_index in range(self.lead_card_list.count()):
            card_item = self.lead_card_list.item(item_index)
            card_item.setCheckState(Qt.CheckState.Unchecked)
            card_item.setData(Qt.ItemDataRole.UserRole + 2, False)
        self.results_table.blockSignals(False)
        self.lead_card_list.blockSignals(False)
        self._populate_lead_cards(self.current_leads)
        self._update_action_states()
        self._toast("Selection cleared.")

    def _route_time_estimate_text(self, leads: list[Lead]) -> str:
        if not leads:
            return "Estimated time: ~0m"
        stop_minutes = len(leads) * 7
        drive_minutes = 0
        previous: Lead | None = None
        for lead in leads:
            if previous is not None:
                distance = _distance_miles(previous, lead)
                if distance is not None:
                    drive_minutes += max(3, round((distance / 25) * 60))
            previous = lead
        if drive_minutes == 0 and len(leads) > 1:
            drive_minutes = (len(leads) - 1) * 5
        total_minutes = max(1, stop_minutes + drive_minutes)
        hours, minutes = divmod(total_minutes, 60)
        if hours:
            return f"Estimated time: ~{hours}h {minutes:02d}m"
        return f"Estimated time: ~{minutes}m"

    def _active_map_leads(self) -> list[Lead]:
        mode = self.map_filter_combo.currentText() if hasattr(self, "map_filter_combo") else "All Businesses"
        if mode == "Checked Businesses":
            return self._checked_current_leads()
        if mode == "Tier 1 Only":
            return filter_map_leads(self.current_leads, "tier1")
        return list(self.current_leads)

    def _checked_current_leads(self) -> list[Lead]:
        selected_keys: set[tuple[str, str]] = set()
        for row_index in self._checked_row_indexes():
            business_name = self._table_text(row_index, self._table_column("Business Name"))
            full_address = self._table_text(row_index, self._table_column("Full Address"))
            selected_keys.add((business_name.strip().lower(), full_address.strip().lower()))

        return [
            lead
            for lead in self.current_leads
            if (lead.business_name.strip().lower(), lead.full_address.strip().lower()) in selected_keys
        ]

    def _assign_route_stop_numbers(self) -> None:
        if not hasattr(self, "results_table"):
            return
        try:
            stop_column = self._table_column("Stop #")
        except ValueError:
            return
        route_index = {
            _lead_key(lead): str(index)
            for index, lead in enumerate(self.route_leads, start=1)
        }
        for index, lead in enumerate(self.route_leads, start=1):
            lead.route_stop_number = str(index)
        self.results_table.blockSignals(True)
        for row_index in range(self.results_table.rowCount()):
            lead_key = "|".join(
                (
                    self._table_text(row_index, self._table_column("Business Name")).strip().lower(),
                    self._table_text(row_index, self._table_column("Full Address")).strip().lower(),
                )
            )
            item = self.results_table.item(row_index, stop_column)
            if item is None:
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.results_table.setItem(row_index, stop_column, item)
            item.setText(route_index.get(lead_key, ""))
            try:
                route_column = self._table_column("Route Stop #")
                route_item = self.results_table.item(row_index, route_column)
                if route_item is None:
                    route_item = QTableWidgetItem("")
                    route_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    route_item.setFlags(route_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.results_table.setItem(row_index, route_column, route_item)
                route_item.setText(route_index.get(lead_key, ""))
            except ValueError:
                pass
        self.results_table.blockSignals(False)

    def _stop_number_for_row(self, row_index: int) -> str:
        try:
            return self._table_text(row_index, self._table_column("Stop #"))
        except ValueError:
            return ""

    def _route_stop_number_for_lead(self, lead: Lead) -> str:
        key = _lead_key(lead)
        for index, route_lead in enumerate(self.route_leads, start=1):
            if _lead_key(route_lead) == key:
                return str(index)
        return ""

    def _checked_row_indexes(self) -> list[int]:
        rows: list[int] = []
        if (
            hasattr(self, "lead_card_list")
            and self.simple_mode
            and self.lead_card_list.isVisible()
        ):
            for item_index in range(self.lead_card_list.count()):
                item = self.lead_card_list.item(item_index)
                row_index = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(row_index, int) and item.checkState() == Qt.CheckState.Checked:
                    rows.append(row_index)
            return rows
        for row_index in range(self.results_table.rowCount()):
            save_item = self.results_table.item(row_index, 0)
            if save_item and save_item.checkState() == Qt.CheckState.Checked:
                rows.append(row_index)
        return rows

    def _refresh_map_view(self) -> None:
        if not hasattr(self, "map_lead_list"):
            return
        if (
            hasattr(self, "main_tabs")
            and self.main_tabs.currentIndex() != self.map_tab_index
        ):
            self.map_dirty = True
            self._map_dirty_when_opened = True
            return

        leads = self._active_map_leads()
        signature = self._map_signature(leads)
        if not self.map_dirty and signature == self._last_map_signature:
            return

        if hasattr(self, "route_summary") and not self.route_leads:
            self.route_summary.setPlainText(build_route_text(leads) or "Build a route to see the stop order here.")
        self._populate_map_lead_list(self.route_leads or leads)
        self._last_map_signature = signature
        self.map_dirty = False

    def _populate_map_lead_list(self, leads: list[Lead]) -> None:
        listed_leads = list(leads)
        self._map_list_leads = listed_leads
        self.map_lead_list.clear()
        if not listed_leads:
            item = QListWidgetItem("No businesses in the route list yet.")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.map_lead_list.addItem(item)
            return

        for index, lead in enumerate(listed_leads, start=1):
            phone = lead.phone or "No phone listed"
            stop_number = self._route_stop_number_for_lead(lead) or str(index)
            best_time = lead.recommended_visit_window or "Anytime today"
            status = lead.status or "New"
            text = (
                f"Stop {stop_number}: {lead.business_name}\n"
                f"{lead.full_address}\n"
                f"Phone: {phone}\n"
                f"{lead.priority_tier or lead.action_priority} | {best_time} | {status}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setSizeHint(QSize(0, 104))
            item.setToolTip("Business in the current route list.")
            self.map_lead_list.addItem(item)

    def _focus_map_lead_item(self, item: QListWidgetItem) -> None:
        return

    def _on_map_url_changed(self, url: QUrl) -> None:
        fragment = url.fragment()
        if not fragment.startswith("lead="):
            return
        lead_key = unquote(fragment.removeprefix("lead="))
        self._highlight_lead_card_by_key(lead_key)

    def _highlight_lead_card_by_key(self, lead_key: str) -> None:
        if not lead_key:
            return
        for item_index in range(self.lead_card_list.count()):
            item = self.lead_card_list.item(item_index)
            row_index = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(row_index, int) or row_index >= len(self.current_leads):
                continue
            if _lead_key(self.current_leads[row_index]) == lead_key:
                self.lead_card_list.setCurrentItem(item)
                self.lead_card_list.scrollToItem(item)
                return

    def _apply_pending_map_focus(self) -> None:
        return

    def _mark_map_dirty(self) -> None:
        self.map_dirty = True

    def _force_refresh_map_view(self) -> None:
        self._mark_map_dirty()
        self._refresh_map_view()

    def _on_tab_changed(self, index: int) -> None:
        if index == 0:
            self._set_workflow_step(1)
        elif index == 1:
            self._set_workflow_step(3 if self.current_leads else 2)
        elif index == self.route_tab_index:
            self._set_workflow_step(5 if self.route_leads else 4)
        elif index == self.followups_tab_index:
            self._refresh_followups_tab(force=True)
        elif index == self.hidden_tab_index:
            self._refresh_hidden_businesses_tab(force=True)

    def _ensure_map_view_ready(self) -> None:
        self._map_view_ready = True
        return

    def _map_signature(self, leads: list[Lead]) -> tuple[object, ...]:
        lead_keys = tuple(
            (
                lead.business_name,
                lead.full_address,
                lead.priority_tier,
                lead.status,
                lead.recommended_visit_window,
                round(lead.latitude, 5) if lead.latitude is not None else None,
                round(lead.longitude, 5) if lead.longitude is not None else None,
            )
            for lead in leads
        )
        route_keys = tuple(
            (
                lead.business_name,
                lead.full_address,
                lead.priority_tier,
                round(lead.latitude, 5) if lead.latitude is not None else None,
                round(lead.longitude, 5) if lead.longitude is not None else None,
            )
            for lead in self.route_leads
        )
        mode = self.map_filter_combo.currentText() if hasattr(self, "map_filter_combo") else "All Businesses"
        return (self.dark_mode, mode, lead_keys, route_keys)

    def _set_dark_mode(self, enabled: bool) -> None:
        self.dark_mode = enabled
        self.dark_mode_button.setText("Light Mode" if enabled else "Dark Mode")
        self.setStyleSheet(DARK_STYLES if enabled else LIGHT_STYLES)
        self._apply_table_row_colors()
        self._mark_map_dirty()
        self._refresh_map_view()

    def _populate_results_table(self, summary: RunSummary, update_original: bool = True) -> None:
        if update_original:
            self.original_leads = self._with_saved_tracking(summary.leads)
        leads = self._apply_suppression_filter(list(self.original_leads if self.original_leads else summary.leads))
        self.current_leads = list(leads)
        self.route_leads = []
        self.route_current_index = 0
        self.route_completed_count = 0
        self._mark_map_dirty()
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(len(leads))
        for row_index, lead in enumerate(leads):
            export_row = lead.export_row()
            save_item = QTableWidgetItem("")
            selected_by_default = False
            save_item.setCheckState(
                Qt.CheckState.Checked if selected_by_default else Qt.CheckState.Unchecked
            )
            save_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            save_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            self.results_table.setItem(row_index, 0, save_item)

            stop_item = QTableWidgetItem("")
            stop_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stop_item.setFlags(stop_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.results_table.setItem(row_index, 1, stop_item)

            for column_index, header in enumerate(EXPORT_HEADERS, start=2):
                if header == "Status":
                    item = QTableWidgetItem(export_row[header] or "New")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.results_table.setItem(row_index, column_index, item)
                    combo = QComboBox()
                    combo.addItems(FIELD_STATUS_OPTIONS)
                    status_value = export_row[header] or "New"
                    if combo.findText(status_value) < 0:
                        combo.addItem(status_value)
                    combo.setCurrentText(status_value)
                    combo.currentTextChanged.connect(self._on_status_combo_changed)
                    self.results_table.setCellWidget(row_index, column_index, combo)
                    continue
                item = QTableWidgetItem(export_row[header])
                if header in {
                    "Action Priority",
                    "Same Address Count",
                    "Is Strip Mall",
                    "Is Chain",
                    "Property Manager Lead",
                    "New / Pre-Opening Lead",
                    "Construction Opportunity",
                    "Priority Tier",
                }:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if header not in {"Status", "Notes", "Last Contacted", "Recommended Visit Window"}:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.results_table.setItem(row_index, column_index, item)
        self._set_default_table_widths()
        self._apply_table_row_colors()
        self.results_table.setSortingEnabled(True)
        self._populate_lead_cards(leads)
        self._apply_table_mode()
        if leads:
            self._set_results_hint_compact(True)
            self.simple_start_card.setVisible(self.simple_mode)
            self.lead_card_list.setVisible(self.simple_mode)
            self.results_table.setVisible(not self.simple_mode)
            self.results_hint.show()
            self.selection_bar.setVisible(self.simple_mode)
            self.generation_progress.hide()
            if self._hidden_filter_message:
                self.results_hint.setText(
                    f"{len(leads)} businesses ready. {self._hidden_filter_message}"
                )
        else:
            self._set_results_hint_compact(False)
            self.results_table.hide()
            self.lead_card_list.hide()
            self.selection_bar.hide()
            self.generation_progress.hide()
            self.results_hint.setText("No businesses found yet. Try a nearby city or broaden the business types.")
        if hasattr(self, "map_lead_list"):
            self._populate_map_lead_list(self.current_leads)
        self.route_summary.setPlainText("Build a route to see a simple field order here.")
        self._refresh_route_mode()
        self._refresh_map_view()
        self._update_action_states()

    def _with_saved_tracking(self, leads: list[Lead]) -> list[Lead]:
        saved = {
            _lead_key(lead): lead
            for lead in load_saved_leads()
        }
        tracked: list[Lead] = []
        for lead in leads:
            previous = saved.get(_lead_key(lead))
            if previous is None:
                tracked.append(lead)
                continue
            tracked.append(
                replace(
                    lead,
                    status=previous.status or lead.status,
                    notes=previous.notes or lead.notes,
                    last_contacted=previous.last_contacted or lead.last_contacted,
                    next_follow_up_date=previous.next_follow_up_date or lead.next_follow_up_date,
                    contact_attempts=max(previous.contact_attempts, lead.contact_attempts),
                    contact_history=previous.contact_history or lead.contact_history,
                    contact_method_history=previous.contact_method_history
                    or lead.contact_method_history,
                    route_stop_number=previous.route_stop_number or lead.route_stop_number,
                    is_suppressed=previous.is_suppressed or lead.is_suppressed,
                    suppression_reason=previous.suppression_reason or lead.suppression_reason,
                    suppression_date=previous.suppression_date or lead.suppression_date,
                    date_added=previous.date_added or lead.date_added,
                )
            )
        return tracked

    def _set_results_hint_compact(self, compact: bool) -> None:
        if not hasattr(self, "results_hint"):
            return
        self.results_hint_compact = compact
        self.results_hint.setProperty("compact", compact)
        self.results_hint.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            if compact
            else Qt.AlignmentFlag.AlignCenter
        )
        self.results_hint.setMaximumHeight(44 if compact else 16777215)
        self.results_hint.style().unpolish(self.results_hint)
        self.results_hint.style().polish(self.results_hint)

    def _populate_lead_cards(self, leads: list[Lead]) -> None:
        self.lead_card_list.blockSignals(True)
        self.lead_card_list.clear()
        for row_index, lead in enumerate(leads):
            selected = False
            save_item = self.results_table.item(row_index, 0)
            if save_item:
                selected = save_item.checkState() == Qt.CheckState.Checked
            item = QListWidgetItem(self._lead_card_display_text(row_index, lead, selected, expanded=False))
            item.setData(Qt.ItemDataRole.UserRole, row_index)
            item.setData(Qt.ItemDataRole.UserRole + 1, False)
            item.setData(Qt.ItemDataRole.UserRole + 2, selected)
            item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setSizeHint(QSize(0, 142))
            self.lead_card_list.addItem(item)
        self.lead_card_list.blockSignals(False)

    def _on_lead_card_changed(self, item: QListWidgetItem) -> None:
        row_index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_index, int):
            return
        save_item = self.results_table.item(row_index, 0)
        if save_item:
            save_item.setCheckState(item.checkState())
        selected = item.checkState() == Qt.CheckState.Checked
        item.setData(Qt.ItemDataRole.UserRole + 2, selected)
        if 0 <= row_index < len(self.current_leads):
            expanded = bool(item.data(Qt.ItemDataRole.UserRole + 1))
            item.setText(self._lead_card_display_text(row_index, self.current_leads[row_index], selected, expanded))
        self._update_action_states()

    def _toggle_lead_card_checked(self, item: QListWidgetItem) -> None:
        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            was_checked = bool(item.data(Qt.ItemDataRole.UserRole + 2))
            is_checked = item.checkState() == Qt.CheckState.Checked
            if was_checked == is_checked:
                item.setCheckState(
                    Qt.CheckState.Unchecked
                    if is_checked
                    else Qt.CheckState.Checked
                )
        self._on_lead_card_selection_changed()

    def _toggle_lead_card_details(self, item: QListWidgetItem) -> None:
        row_index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_index, int) or row_index >= len(self.current_leads):
            return
        expanded = not bool(item.data(Qt.ItemDataRole.UserRole + 1))
        item.setData(Qt.ItemDataRole.UserRole + 1, expanded)
        selected = item.checkState() == Qt.CheckState.Checked
        item.setText(
            self._lead_card_display_text(row_index, self.current_leads[row_index], selected, expanded)
        )
        item.setSizeHint(QSize(0, 318 if expanded else 142))

    def _lead_card_display_text(self, row_index: int, lead: Lead, selected: bool, expanded: bool) -> str:
        text = _lead_card_text(
            lead,
            expanded=expanded,
            stop_number=self._stop_number_for_row(row_index),
        )
        return f"SELECTED\n{text}" if selected else text

    def _on_lead_card_selection_changed(self) -> None:
        item = self.lead_card_list.currentItem()
        if item is None:
            return
        row_index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_index, int):
            return
        self._focus_map_by_row(row_index)

    def _focus_map_by_row(self, row_index: int) -> None:
        return

    def _apply_table_row_colors(self) -> None:
        for row_index in range(self.results_table.rowCount()):
            tier_item = self.results_table.item(row_index, self._table_column("Priority Tier"))
            priority_tier = tier_item.text() if tier_item else ""
            color = self._tier_color(priority_tier)
            for column_index in range(self.results_table.columnCount()):
                item = self.results_table.item(row_index, column_index)
                if item:
                    item.setBackground(color)

    def _tier_color(self, priority_tier: str) -> QColor:
        if self.dark_mode:
            if priority_tier == "Tier 1":
                return QColor("#19392f")
            if priority_tier == "Tier 2":
                return QColor("#183044")
            return QColor("#1d252b")

        if priority_tier == "Tier 1":
            return QColor("#ecf7f3")
        if priority_tier == "Tier 2":
            return QColor("#fffbe8")
        return QColor("#ffffff")

    def _on_status_combo_changed(self, status: str) -> None:
        combo = self.sender()
        if not isinstance(combo, QComboBox):
            return

        status_column = self._table_column("Status")
        row_index = -1
        for current_row in range(self.results_table.rowCount()):
            if self.results_table.cellWidget(current_row, status_column) is combo:
                row_index = current_row
                break
        if row_index < 0:
            return

        status_item = self.results_table.item(row_index, status_column)
        if status_item:
            status_item.setText(status)

        if status == "Follow Up" and not self._table_text(
            row_index, self._table_column("Next Follow-Up Date")
        ):
            followup_date = self._prompt_follow_up_date()
            if followup_date:
                self._set_table_cell_text(row_index, "Next Follow-Up Date", followup_date)

        if status != "New":
            today = datetime.now().strftime("%Y-%m-%d")
            last_contacted_item = self.results_table.item(
                row_index, self._table_column("Last Contacted")
            )
            if last_contacted_item:
                last_contacted_item.setText(today)
            if status in {"Called", "Door Knocked"}:
                attempts = _safe_int(
                    self._table_text(row_index, self._table_column("Contact Attempts")),
                    0,
                )
                self._set_table_cell_text(row_index, "Contact Attempts", str(attempts + 1))
            history = _split_history_text(
                self._table_text(row_index, self._table_column("Contact History Summary"))
            )
            history.append(f"{today} - {status}")
            self._set_table_cell_text(
                row_index,
                "Contact History Summary",
                "; ".join(history[-20:]),
            )
            method_history = _split_history_text(
                self._table_text(row_index, self._table_column("Contact Method History"))
            )
            method_history.append(f"{today} - {status}")
            self._set_table_cell_text(
                row_index,
                "Contact Method History",
                "; ".join(method_history[-20:]),
            )

        self.current_leads = self._leads_from_table(checked_only=False)
        self._sync_original_from_current_view()
        self._save_tracker_state()
        self._refresh_followups_tab()
        self._populate_lead_cards(self.current_leads)
        self._mark_map_dirty()
        self._refresh_map_view()
        self._update_action_states()
        if status != "New":
            self._toast(f"Lead marked {status.lower()}.")

    def _table_column(self, header: str) -> int:
        return TABLE_HEADERS.index(header)

    def _leads_from_table(self, checked_only: bool) -> list[Lead]:
        leads: list[Lead] = []
        current_index = {
            (
                lead.business_name.strip().lower(),
                lead.full_address.strip().lower(),
            ): lead
            for lead in self.current_leads
        }
        for row_index in range(self.results_table.rowCount()):
            save_item = self.results_table.item(row_index, 0)
            if checked_only and (
                not save_item or save_item.checkState() != Qt.CheckState.Checked
            ):
                continue

            row = {
                header: self._table_text(row_index, self._table_column(header))
                for header in EXPORT_HEADERS
            }
            lead_key = (
                row["Business Name"].strip().lower(),
                row["Full Address"].strip().lower(),
            )
            base_lead = current_index.get(lead_key)
            if base_lead is not None:
                leads.append(
                    replace(
                        base_lead,
                        business_name=row["Business Name"],
                        category=row["Category"],
                        city=row["City"],
                        full_address=row["Full Address"],
                        website=row["Website"],
                        phone=row["Phone"],
                        email=row["Email"],
                        google_maps_url=row["Google Maps URL"],
                        is_strip_mall=row["Is Strip Mall"] == "Yes",
                        same_address_count=_safe_int(row["Same Address Count"], 1),
                        is_chain=row["Is Chain"] == "Yes",
                        is_property_manager_lead=row["Property Manager Lead"] == "Yes",
                        is_new_pre_opening_lead=row["New / Pre-Opening Lead"] == "Yes",
                        is_construction_opportunity=row["Construction Opportunity"] == "Yes",
                        hours_of_operation=row["Hours of Operation"],
                        recommended_visit_window=row["Recommended Visit Window"],
                        action_priority=row.get("Action Priority", "Optional"),
                        priority_tier=row["Priority Tier"] or "Tier 3",
                        status=row["Status"] or "New",
                        notes=row["Notes"],
                        date_added=row["Date Added"],
                        last_contacted=row["Last Contacted"],
                        next_follow_up_date=row.get("Next Follow-Up Date", ""),
                        contact_attempts=_safe_int(row.get("Contact Attempts", ""), 0),
                        contact_history=_split_history_text(
                            row.get("Contact History Summary", "")
                        )
                        or base_lead.contact_history
                        or [],
                        contact_method_history=_split_history_text(
                            row.get("Contact Method History", "")
                        )
                        or base_lead.contact_method_history
                        or [],
                        route_stop_number=row.get("Route Stop #", ""),
                        is_suppressed=row.get("Hidden / Suppressed", "") == "Yes",
                        suppression_reason=row.get("Hidden Reason", ""),
                        lead_reason=row.get("Lead Reason", ""),
                        quick_notes=row.get("Quick Notes", ""),
                        source_keywords=_split_csv_text(row.get("Source Keywords", "")),
                    )
                )
                continue

            leads.append(
                Lead(
                    business_name=row["Business Name"],
                    category=row["Category"],
                    city=row["City"],
                    full_address=row["Full Address"],
                    website=row["Website"],
                    phone=row["Phone"],
                    email=row["Email"],
                    google_maps_url=row["Google Maps URL"],
                    is_strip_mall=row["Is Strip Mall"] == "Yes",
                    same_address_count=_safe_int(row["Same Address Count"], 1),
                    is_chain=row["Is Chain"] == "Yes",
                    is_property_manager_lead=row["Property Manager Lead"] == "Yes",
                    is_new_pre_opening_lead=row["New / Pre-Opening Lead"] == "Yes",
                    is_construction_opportunity=row["Construction Opportunity"] == "Yes",
                    hours_of_operation=row["Hours of Operation"],
                    recommended_visit_window=row["Recommended Visit Window"],
                    action_priority=row.get("Action Priority", "Optional"),
                    priority_tier=row["Priority Tier"] or "Tier 3",
                    status=row["Status"] or "New",
                    notes=row["Notes"],
                    date_added=row["Date Added"],
                    last_contacted=row["Last Contacted"],
                    next_follow_up_date=row.get("Next Follow-Up Date", ""),
                    contact_attempts=_safe_int(row.get("Contact Attempts", ""), 0),
                    contact_history=_split_history_text(row.get("Contact History Summary", "")),
                    contact_method_history=_split_history_text(row.get("Contact Method History", "")),
                    route_stop_number=row.get("Route Stop #", ""),
                    is_suppressed=row.get("Hidden / Suppressed", "") == "Yes",
                    suppression_reason=row.get("Hidden Reason", ""),
                    lead_reason=row.get("Lead Reason", ""),
                    quick_notes=row.get("Quick Notes", ""),
                    source_keywords=_split_csv_text(row.get("Source Keywords", "")),
                )
            )
        return leads

    def _table_text(self, row_index: int, column_index: int) -> str:
        widget = self.results_table.cellWidget(row_index, column_index)
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        item = self.results_table.item(row_index, column_index)
        return item.text().strip() if item else ""

    def _all_entered_cities(self) -> list[str]:
        return _split_csv_text(self.cities_input.text())

    def _selected_cities(self) -> list[str]:
        if self.one_city_radio.isChecked():
            city = self.single_city_combo.currentText().strip()
            return [city] if city else []
        return self._all_entered_cities()

    def _set_workflow_step(self, step: int) -> None:
        self.current_step = max(1, min(step, 5))
        if not hasattr(self, "workflow_labels"):
            return
        for index, label in enumerate(self.workflow_labels, start=1):
            label.setProperty("active", index == self.current_step)
            label.setProperty("complete", index < self.current_step)
            label.style().unpolish(label)
            label.style().polish(label)

    def _go_to_workflow_step(self, step: int) -> None:
        step = max(1, min(step, 5))
        if step == 1:
            self.main_tabs.setCurrentIndex(0)
            if hasattr(self, "simple_city_input"):
                self.simple_city_input.setFocus()
        elif step in {2, 3}:
            self.main_tabs.setCurrentIndex(1)
            if step == 3 and hasattr(self, "lead_card_list"):
                self.lead_card_list.setFocus()
                if hasattr(self, "selection_bar"):
                    self.selection_bar.setVisible(bool(self.current_leads))
        else:
            self.main_tabs.setCurrentIndex(self.route_tab_index)
        self._set_workflow_step(step)

    def _set_simple_mode(self, advanced_enabled: bool) -> None:
        self.simple_mode = not advanced_enabled
        if hasattr(self, "mode_button"):
            self.mode_button.setText("Simple Mode" if advanced_enabled else "Advanced Mode")
        if hasattr(self, "workflow_widget"):
            self.workflow_widget.setVisible(True)
        if hasattr(self, "market_group"):
            self.market_group.setVisible(advanced_enabled)
        if hasattr(self, "market_preview"):
            self.market_preview.setVisible(advanced_enabled)
        if hasattr(self, "simple_start_card"):
            self.simple_start_card.setVisible(self.simple_mode)
        if hasattr(self, "start_address_frame"):
            self.start_address_frame.setVisible(True)
        if hasattr(self, "run_button"):
            self.run_button.setVisible(advanced_enabled)
        for widget in getattr(self, "advanced_market_widgets", []):
            widget.setVisible(advanced_enabled)
        for widget in getattr(self, "advanced_action_widgets", []):
            widget.setVisible(advanced_enabled)
        for widget in getattr(self, "table_tools_widgets", []):
            widget.setVisible(advanced_enabled)
        for widget in getattr(self, "advanced_map_widgets", []):
            widget.setVisible(advanced_enabled)
        if hasattr(self, "main_tabs"):
            self.main_tabs.tabBar().setVisible(True)
        self.progress_log.parentWidget().setVisible(advanced_enabled)
        self.total_label.parentWidget().setVisible(advanced_enabled)
        self._apply_table_mode()
        self._update_action_states()
        self._toast("Advanced tools shown." if advanced_enabled else "Simple Mode is on.")

    def _apply_table_mode(self) -> None:
        if not hasattr(self, "results_table"):
            return
        for column_index, header in enumerate(TABLE_HEADERS):
            self.results_table.setColumnHidden(
                column_index,
                self.simple_mode and header not in SIMPLE_TABLE_HEADERS,
            )
        has_rows = self.results_table.rowCount() > 0
        self.lead_card_list.setVisible(self.simple_mode and has_rows)
        if hasattr(self, "selection_bar"):
            self.selection_bar.setVisible(self.simple_mode and has_rows)
        self.results_table.setVisible((not self.simple_mode) and has_rows)
        if self.simple_mode:
            self.results_table.horizontalScrollBar().setValue(0)

    def _update_action_states(self) -> None:
        has_leads = bool(self.current_leads)
        checked_count = len(self._checked_row_indexes()) if hasattr(self, "results_table") else 0
        has_selected_stops = checked_count > 0
        has_route = bool(self.route_leads)
        if hasattr(self, "selection_bar"):
            self.selected_count_label.setText(
                f"{checked_count} stop{'s' if checked_count != 1 else ''} selected for today"
            )
            self.selection_bar.setVisible(self.simple_mode and has_leads)
            self.selection_build_route_button.setEnabled(has_selected_stops)
            self.clear_selection_button.setEnabled(has_selected_stops)
        self.build_my_day_button.setEnabled(has_leads)
        self.route_button.setEnabled(has_leads and has_selected_stops)
        if hasattr(self, "open_google_route_button"):
            self.open_google_route_button.setEnabled(has_route)
        self.export_route_button.setEnabled(has_route)
        self.print_call_sheet_button.setEnabled(has_leads)
        self.start_route_button.setEnabled(has_route)
        if self.simple_mode:
            self.build_my_day_button.setVisible(has_leads)
            self.route_button.setVisible(False)
            if hasattr(self, "open_google_route_button"):
                self.open_google_route_button.setVisible(False)
            self.export_route_button.setVisible(False)
            self.print_call_sheet_button.setVisible(False)
            self.start_route_button.setVisible(False)
        else:
            self.build_my_day_button.setVisible(True)
            self.route_button.setVisible(False)
            if hasattr(self, "open_google_route_button"):
                self.open_google_route_button.setVisible(False)
            self.export_route_button.setVisible(False)
            self.print_call_sheet_button.setVisible(False)
            self.start_route_button.setVisible(False)
        if hasattr(self, "map_route_button"):
            self.map_route_button.setEnabled(has_leads and has_selected_stops)
        if hasattr(self, "map_open_google_button"):
            self.map_open_google_button.setEnabled(has_route)
        if hasattr(self, "map_call_sheet_button"):
            self.map_call_sheet_button.setEnabled(has_leads)
        for button in getattr(self, "tracker_action_widgets", []):
            button.setEnabled(has_leads and has_selected_stops)
            button.setVisible((not self.simple_mode) and has_leads)
        for button in getattr(self, "secondary_step3_widgets", []):
            button.setVisible((not self.simple_mode) and has_leads)
        self.open_csv_button.setEnabled(self.latest_output_path is not None)
        self.export_checked_button.setEnabled(has_leads and has_selected_stops)
        self.open_csv_button.setVisible(False)
        self.export_checked_button.setVisible(False)
        self._refresh_smart_banner()

    def _show_onboarding_if_needed(self) -> None:
        marker = default_output_directory()
        try:
            onboarding_marker = Path(marker).parent / ".routeforge_selection_intro_seen"
            if onboarding_marker.exists():
                return
            onboarding_marker.parent.mkdir(parents=True, exist_ok=True)
            QMessageBox.information(
                self,
                "RouteForge quick tip",
                (
                    "Click businesses to select them.\n"
                    "Then click Build My Day to create your route.\n"
                    "Use Today's Route to work through stops."
                ),
            )
            onboarding_marker.write_text("seen\n", encoding="utf-8")
        except OSError:
            pass

    def _show_help(self, title: str = "How to use this app") -> None:
        QMessageBox.information(
            self,
            title,
            (
                "1. Enter a city and choose the state.\n"
                "2. Optional: add the address where you will start driving from.\n"
                "3. Click Find Businesses.\n"
                "4. Click Build My Day to select the best stops and build today's route.\n"
                "5. Start the driving route, print the door-knocking sheet, or print the call list."
            ),
        )

    def _toast(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)

    def _select_top_leads(self) -> None:
        if not self.current_leads:
            QMessageBox.information(
                self,
                "No businesses yet",
                "Enter a city and click Find Businesses before picking stops.",
            )
            return
        selected = 0
        self.results_table.blockSignals(True)
        self.lead_card_list.blockSignals(True)
        for row_index in range(self.results_table.rowCount()):
            tier = self._table_text(row_index, self._table_column("Priority Tier"))
            priority = self._table_text(row_index, self._table_column("Action Priority"))
            checked = tier == "Tier 1" or priority in {"High", "Highest", "Must Visit"}
            if not checked and selected < 10:
                checked = True
            item = self.results_table.item(row_index, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                if checked:
                    selected += 1
        for item_index in range(self.lead_card_list.count()):
            card_item = self.lead_card_list.item(item_index)
            row_index = card_item.data(Qt.ItemDataRole.UserRole)
            table_item = self.results_table.item(row_index, 0) if isinstance(row_index, int) else None
            card_item.setCheckState(
                table_item.checkState() if table_item else Qt.CheckState.Unchecked
            )
        self.results_table.blockSignals(False)
        self.lead_card_list.blockSignals(False)
        self._populate_lead_cards(self.current_leads)
        self.lead_card_list.setVisible(self.simple_mode and bool(self.current_leads))
        self.selection_bar.setVisible(self.simple_mode and bool(self.current_leads))
        if selected and self.lead_card_list.count():
            self.lead_card_list.scrollToItem(self.lead_card_list.item(0))
            self.lead_card_list.setCurrentRow(0)
        self._set_workflow_step(3)
        self.results_hint.setText(
            f"{selected} top leads selected. Build Selected Route is ready."
        )
        self._update_action_states()
        self._toast(f"{selected} top leads selected.")

    def _export_route_sheet(self) -> None:
        if not self.route_leads:
            QMessageBox.information(
                self,
                "No route yet",
                "Build a route before printing the door-knocking sheet.",
            )
            return
        if not print_route_sheet(self, self.route_leads):
            return
        self._set_workflow_step(5)
        self._append_progress(f"Opened door-knocking sheet preview with {len(self.route_leads)} stops.")
        self._toast("Print preview opened.")

    def _start_route(self) -> None:
        if not self.route_leads:
            QMessageBox.information(self, "No route yet", "Build a route before opening Google Maps.")
            return
        url = self._route_maps_url()
        if not url:
            QMessageBox.information(self, "No addresses", "This route does not have enough addresses for Maps.")
            return
        QDesktopServices.openUrl(QUrl.fromUserInput(url))
        self._set_workflow_step(5)
        self._toast("Opening route in Google Maps.")

    def _show_route_mode(self) -> None:
        if not self.route_leads:
            QMessageBox.information(self, "No route yet", "Build today's route first.")
            return
        self._refresh_route_mode()
        self.main_tabs.setCurrentIndex(self.route_tab_index)
        self._set_workflow_step(5)

    def _current_route_stop(self) -> Lead | None:
        if not self.route_leads:
            return None
        if self.route_current_index >= len(self.route_leads):
            return None
        return self.route_leads[self.route_current_index]

    def _refresh_route_mode(self) -> None:
        if not hasattr(self, "current_stop_name"):
            return

        total = len(self.route_leads)
        completed = min(self.route_completed_count, total)
        self.route_mode_progress.setText(f"{completed} of {total} completed")
        lead = self._current_route_stop()

        route_active = lead is not None
        for button in (
            self.route_open_maps_button,
            self.route_stop_maps_button,
            self.route_mark_called_button,
            self.route_mark_door_knocked_button,
            self.route_mark_interested_button,
            self.route_set_followup_button,
            self.route_done_button,
            self.route_skip_button,
        ):
            button.setEnabled(route_active)

        self.upcoming_stops_list.clear()
        if lead is None:
            self.current_stop_badge.setText("Route complete")
            self.current_stop_name.setText("Today's route is finished.")
            self.current_stop_address.setText("Print the door-knocking sheet or choose another workflow step.")
            self.current_stop_reason.setText("")
            self.current_stop_window.setText("")
            self.current_stop_phone.setText("")
            self.current_stop_status.setText("")
            self.current_stop_notes.setText("")
            return

        best_stop = lead.priority_tier == "Tier 1" or lead.action_priority == "Hit First"
        self.current_stop_badge.setText(
            f"Stop {self.route_current_index + 1}" + ("  |  Best Stop" if best_stop else "")
        )
        self.current_stop_name.setText(lead.business_name or "Unnamed business")
        self.current_stop_address.setText(lead.full_address or "No address available")
        self.current_stop_reason.setText(f"Lead reason: {_short_lead_reason(lead)}")
        self.current_stop_window.setText(
            f"Best time: {lead.recommended_visit_window or 'Anytime today'}"
        )
        self.current_stop_phone.setText(f"Phone: {lead.phone or 'No phone listed'}")
        self.current_stop_status.setText(f"Status: {lead.status or 'New'}")
        notes_lines = [line.strip() for line in (lead.notes or lead.quick_notes or "").splitlines() if line.strip()]
        notes_preview = " / ".join(notes_lines[:2]) if notes_lines else "None yet"
        self.current_stop_notes.setText(f"Notes: {notes_preview}")

        upcoming = self.route_leads[self.route_current_index + 1 :]
        if not upcoming:
            item = QListWidgetItem("No more upcoming stops.")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.upcoming_stops_list.addItem(item)
            return

        for offset, upcoming_lead in enumerate(upcoming, start=self.route_current_index + 2):
            phone = upcoming_lead.phone or "No phone"
            status = upcoming_lead.status or "New"
            best = "  |  Best Stop" if (
                upcoming_lead.priority_tier == "Tier 1" or upcoming_lead.action_priority == "Hit First"
            ) else ""
            text = (
                f"STOP {offset}{best}  |  {upcoming_lead.business_name or 'Unnamed business'}\n"
                f"{upcoming_lead.full_address or 'No address available'}\n"
                f"Phone: {phone}  |  Status: {status}"
            )
            item = QListWidgetItem(text)
            item.setSizeHint(QSize(0, 98))
            self.upcoming_stops_list.addItem(item)

    def _open_current_stop_maps(self) -> None:
        lead = self._current_route_stop()
        if lead is None:
            return
        query = quote_plus(lead.full_address or lead.business_name)
        if query:
            QDesktopServices.openUrl(
                QUrl.fromUserInput(f"https://www.google.com/maps/search/?api=1&query={query}")
            )

    def _route_start_address(self) -> str:
        if not hasattr(self, "start_address_input"):
            return ""
        return self.start_address_input.text().strip()

    def _route_maps_url(self, start_index: int = 0) -> str:
        remaining = [
            lead
            for lead in self.route_leads[start_index:]
            if lead.full_address or lead.business_name
        ]
        if not remaining:
            return ""
        if len(remaining) == 1:
            params = {
                "api": "1",
                "travelmode": "driving",
                "destination": remaining[0].full_address or remaining[0].business_name,
            }
            start_address = self._route_start_address()
            if start_index == 0 and start_address:
                params["origin"] = start_address
            return f"https://www.google.com/maps/dir/?{urlencode(params)}"

        start_address = self._route_start_address()
        destination = remaining[-1].full_address or remaining[-1].business_name
        waypoint_leads = remaining[:-1]
        params = {
            "api": "1",
            "travelmode": "driving",
            "destination": destination,
            "waypoints": "|".join(
                lead.full_address or lead.business_name for lead in waypoint_leads
            ),
        }
        if start_index == 0 and start_address:
            params["origin"] = start_address
        return f"https://www.google.com/maps/dir/?{urlencode(params, safe='|,')}"

    def _mark_current_stop_called(self) -> None:
        self._update_current_stop_status("Called", "Marked called.")

    def _mark_current_stop_door_knocked(self) -> None:
        self._update_current_stop_status("Door Knocked", "Marked door knocked.")

    def _mark_current_stop_interested(self) -> None:
        self._update_current_stop_status("Interested", "Marked interested.")

    def _set_current_stop_followup(self) -> None:
        followup_date = self._prompt_follow_up_date()
        if not followup_date:
            return
        self._update_current_stop_status(
            "Follow Up",
            "Follow-up set.",
            followup_date=followup_date,
        )

    def _update_current_stop_status(self, status: str, message: str, followup_date: str = "") -> None:
        lead = self._current_route_stop()
        if lead is None:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        lead.status = status
        lead.last_contacted = today
        if followup_date:
            lead.next_follow_up_date = followup_date
        if status in {"Called", "Door Knocked"}:
            lead.contact_attempts += 1
        history = lead.contact_history or []
        history.append(
            f"{today} - Follow up scheduled for {followup_date}"
            if followup_date
            else f"{today} - {status}"
        )
        lead.contact_history = history[-20:]
        method_history = lead.contact_method_history or []
        method_history.append(f"{today} - {status}")
        lead.contact_method_history = method_history[-20:]
        self._sync_route_status_to_table(lead, status, followup_date=followup_date)
        self.current_leads = self._leads_from_table(checked_only=False)
        self._sync_lead_to_original_state(lead)
        self._save_tracker_state()
        self._refresh_followups_tab()
        self._refresh_route_mode()
        self._update_action_states()
        self._toast(message)

    def _mark_current_stop_done(self) -> None:
        self._move_to_next_route_stop("Moved to next stop.")

    def _skip_current_stop(self) -> None:
        self._move_to_next_route_stop("Skipped stop.")

    def _move_to_next_route_stop(self, message: str) -> None:
        lead = self._current_route_stop()
        if lead is None:
            return
        self.route_completed_count = min(self.route_completed_count + 1, len(self.route_leads))
        self.route_current_index += 1
        self._save_tracker_state()
        self._refresh_followups_tab()
        self._refresh_route_mode()
        self._update_action_states()
        self._toast(message)

    def _sync_route_status_to_table(self, lead: Lead, status: str, followup_date: str = "") -> None:
        status_column = self._table_column("Status")
        last_contacted_column = self._table_column("Last Contacted")
        today = datetime.now().strftime("%Y-%m-%d")
        for row_index in range(self.results_table.rowCount()):
            business_name = self._table_text(row_index, self._table_column("Business Name"))
            full_address = self._table_text(row_index, self._table_column("Full Address"))
            if (
                business_name.strip().lower() == lead.business_name.strip().lower()
                and full_address.strip().lower() == lead.full_address.strip().lower()
            ):
                status_item = self.results_table.item(row_index, status_column)
                if status_item:
                    status_item.setText(status)
                status_combo = self.results_table.cellWidget(row_index, status_column)
                if isinstance(status_combo, QComboBox):
                    status_combo.blockSignals(True)
                    status_combo.setCurrentText(status)
                    status_combo.blockSignals(False)
                last_contacted_item = self.results_table.item(row_index, last_contacted_column)
                if last_contacted_item:
                    last_contacted_item.setText(today)
                if followup_date:
                    self._set_table_cell_text(row_index, "Next Follow-Up Date", followup_date)
                if status in {"Called", "Door Knocked"}:
                    attempts = _safe_int(
                        self._table_text(row_index, self._table_column("Contact Attempts")),
                        0,
                    )
                    self._set_table_cell_text(row_index, "Contact Attempts", str(attempts + 1))
                history = _split_history_text(
                    self._table_text(row_index, self._table_column("Contact History Summary"))
                )
                history.append(
                    f"{today} - Follow up scheduled for {followup_date}"
                    if followup_date
                    else f"{today} - {status}"
                )
                self._set_table_cell_text(
                    row_index,
                    "Contact History Summary",
                    "; ".join(history[-20:]),
                )
                method_history = _split_history_text(
                    self._table_text(row_index, self._table_column("Contact Method History"))
                )
                method_history.append(f"{today} - {status}")
                self._set_table_cell_text(
                    row_index,
                    "Contact Method History",
                    "; ".join(method_history[-20:]),
                )
                return


def _summary_label(title: str, value: str) -> QLabel:
    label = QLabel(f"{title}\n{value}")
    label.setFrameShape(QFrame.StyledPanel)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    label.setObjectName("SummaryTile")
    return label


def _short_lead_reason(lead: Lead) -> str:
    if lead.is_strip_mall and lead.same_address_count > 1:
        return f"{lead.same_address_count}-store plaza"
    if lead.quick_notes:
        return lead.quick_notes
    if lead.lead_reason:
        reason = lead.lead_reason.strip()
        return reason if len(reason) <= 90 else f"{reason[:87]}..."
    if lead.category:
        return f"{lead.category} prospect"
    return "Good field prospect"


def _distance_miles(first: Lead, second: Lead) -> float | None:
    if (
        first.latitude is None
        or first.longitude is None
        or second.latitude is None
        or second.longitude is None
    ):
        return None
    radius_miles = 3958.8
    lat1 = math.radians(float(first.latitude))
    lat2 = math.radians(float(second.latitude))
    dlat = lat2 - lat1
    dlon = math.radians(float(second.longitude) - float(first.longitude))
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return radius_miles * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _lead_card_text(lead: Lead, expanded: bool = False, stop_number: str = "") -> str:
    visit_window = lead.recommended_visit_window or "Anytime today"
    reason = _short_lead_reason(lead)
    score = _lead_score_label(lead)
    phone = lead.phone or "No phone listed"
    email = lead.email or "Not found"
    status = lead.status or "New"
    badges = _lead_quality_badges(lead)
    hidden_line = (
        f"Hidden from future searches: {lead.suppression_reason}\n"
        if lead.is_suppressed
        else ""
    )
    stop_line = f"STOP {stop_number} | " if stop_number else ""
    best_stop_line = (
        "Best Stop\n" if lead.priority_tier == "Tier 1" or lead.action_priority == "Hit First" else ""
    )
    summary = (
        f"{stop_line}{score}\n"
        f"{best_stop_line}"
        f"{lead.business_name or 'Unnamed business'}\n"
        f"{lead.full_address or 'No address available'}\n"
        f"Phone: {phone}   |   Visit: {visit_window}   |   Status: {status}\n"
        f"{hidden_line}"
        f"{badges}\n"
        f"Reason: {reason}\n"
        "Double-click for details"
    )
    if not expanded:
        return summary
    details = [
        "",
        "Details",
        f"Phone: {phone}",
        f"Email: {email}",
        f"Hours: {lead.hours_of_operation or 'Not listed'}",
        f"Website: {lead.website or 'Not listed'}",
        f"Last Contacted: {lead.last_contacted or 'Not contacted'}",
        f"Next Follow-Up: {lead.next_follow_up_date or 'Not set'}",
        f"Attempts: {lead.contact_attempts}",
        f"History: {_history_text(lead) or 'No contact history yet'}",
        f"Notes: {lead.notes or lead.quick_notes or ''}",
        f"Why this tier: {_lead_score_details(lead)}",
    ]
    return f"{summary}\n" + "\n".join(details)


def _lead_quality_badges(lead: Lead) -> str:
    badges: list[str] = []
    if lead.priority_tier == "Tier 1" or lead.action_priority == "Hit First":
        badges.append("Best Stop")
    badges.append("Phone" if lead.phone.strip() else "No phone")
    if lead.website.strip():
        badges.append("Website")
    if lead.email.strip():
        badges.append("Email")
    badges.append(
        "Full Address"
        if lead.address_quality == "full_street_address" and lead.full_address.strip()
        else "Address incomplete"
    )
    if lead.latitude is not None and lead.longitude is not None:
        badges.append("Mapped")
    if lead.is_strip_mall or lead.same_address_count >= 3:
        badges.append("Plaza")
    return " | ".join(badges)


def _lead_score_label(lead: Lead) -> str:
    tier = lead.priority_tier or "Tier 3"
    numeric_score = lead.lead_quality_score
    if numeric_score <= 0:
        numeric_score = 20
        if lead.is_strip_mall:
            numeric_score += 30
        if lead.same_address_count >= 3:
            numeric_score += 20
        if lead.is_chain:
            numeric_score += 8
        if lead.phone:
            numeric_score += 6
        if lead.website:
            numeric_score += 4
        if lead.is_property_manager_lead:
            numeric_score += 12
        if lead.is_new_pre_opening_lead or lead.is_construction_opportunity:
            numeric_score += 10
        numeric_score = min(numeric_score, 100)
    priority = lead.action_priority or "Lead"
    return f"{tier} | Score {numeric_score} | {priority}"


def _lead_score_details(lead: Lead) -> str:
    reasons: list[str] = []
    if lead.is_strip_mall or lead.same_address_count >= 3:
        reasons.append(f"{lead.same_address_count}-store plaza/cluster")
    if lead.category_value in {"high", "very_high"}:
        reasons.append("strong business category")
    if lead.address_quality == "full_street_address":
        reasons.append("full street address")
    if lead.keyword_match_count:
        reasons.append(f"{lead.keyword_match_count} keyword match{'es' if lead.keyword_match_count != 1 else ''}")
    if lead.is_chain:
        reasons.append("chain or repeat-location signal")
    if lead.is_property_manager_lead:
        reasons.append("property manager signal")
    if lead.is_new_pre_opening_lead or lead.is_construction_opportunity:
        reasons.append("new/construction signal")
    if not reasons:
        reasons.append("basic category and location fit")
    return "; ".join(reasons)


def _build_my_day_score(lead: Lead) -> int:
    if lead.is_suppressed:
        return -10000
    status = (lead.status or "New").strip().lower()
    if status in {"not interested", "bad lead", "customer"}:
        return -10000

    score = lead.lead_quality_score or 0
    if lead.phone.strip():
        score += 30
    if lead.address_quality == "full_street_address" and lead.full_address.strip():
        score += 24
    elif lead.full_address.strip():
        score += 8
    if lead.priority_tier == "Tier 1":
        score += 35
    elif lead.priority_tier == "Tier 2":
        score += 15
    priority = (lead.action_priority or "").lower()
    if any(token in priority for token in ("hit first", "must", "highest", "high")):
        score += 25
    if lead.is_strip_mall or lead.same_address_count >= 3:
        score += 25
    if lead.recommended_visit_window.strip():
        score += 10
    if lead.latitude is not None and lead.longitude is not None:
        score += 18
    if status == "interested":
        score += 50
    elif status == "follow up":
        score += 35
    elif status in {"called", "no answer", "left voicemail"}:
        score += 5
    if lead.website.strip():
        score += 4
    if lead.email.strip():
        score += 2
    return score


def _lead_key(lead: Lead) -> str:
    return f"{lead.business_name.strip().lower()}|{lead.full_address.strip().lower()}"


def _copy_tracking_fields(source: Lead, destination: Lead) -> None:
    destination.status = source.status
    destination.notes = source.notes
    destination.last_contacted = source.last_contacted
    destination.next_follow_up_date = source.next_follow_up_date
    destination.contact_attempts = source.contact_attempts
    destination.contact_history = list(source.contact_history or [])
    destination.contact_method_history = list(source.contact_method_history or [])
    destination.route_stop_number = source.route_stop_number
    destination.is_suppressed = source.is_suppressed
    destination.suppression_reason = source.suppression_reason
    destination.suppression_date = source.suppression_date


def _js_string(value: str) -> str:
    return json.dumps(value)


def _split_csv_text(value: str) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            items.append(item)
    return items


def _split_history_text(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def _history_text(lead: Lead) -> str:
    return "; ".join(lead.contact_history or [])


def _lead_followup_date(lead: Lead) -> date | None:
    if not lead.next_follow_up_date:
        return None
    try:
        return datetime.strptime(lead.next_follow_up_date, "%Y-%m-%d").date()
    except ValueError:
        return None


def _followup_due(lead: Lead) -> bool:
    followup = _lead_followup_date(lead)
    return followup is not None and followup <= date.today()


def _followup_sort_key(lead: Lead) -> tuple[int, int, str]:
    today = date.today()
    followup = _lead_followup_date(lead)
    if lead.status in {"Not Interested", "Bad Lead", "Customer"}:
        bucket = 5
    elif followup is not None and followup < today:
        bucket = 0
    elif followup == today:
        bucket = 1
    elif lead.status == "Interested":
        bucket = 2
    elif followup is not None:
        bucket = 3
    else:
        bucket = 4
    try:
        added = datetime.strptime(lead.date_added, "%Y-%m-%d").date().toordinal()
    except ValueError:
        added = 0
    return (bucket, -added, lead.business_name.lower())


def _followup_group_label(lead: Lead) -> str:
    today = date.today()
    followup = _lead_followup_date(lead)
    if lead.status in {"Not Interested", "Bad Lead", "Customer"}:
        return "Not Interested / Archived"
    if followup is not None and followup < today:
        return "Overdue"
    if followup == today:
        return "Due Today"
    if lead.status == "Interested":
        return "Interested"
    if followup is not None:
        return "Upcoming"
    return "Newest / Not Contacted"


def _friendly_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return "Something went wrong while generating leads. Please try again."
    return message


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


LIGHT_STYLES = """
QWidget {
    background: #F8FAFC;
    color: #111827;
    font-family: Segoe UI, Arial, sans-serif;
    font-size: 14px;
}
QLabel#Title {
    font-size: 28px;
    font-weight: 700;
    color: #22C55E;
}
QLabel#Subtitle, QLabel#MarketPreview, QLabel#ResultsHint, QLabel#KeywordSummary {
    color: #6B7280;
}
QLabel#ResultsHint {
    background: #ffffff;
    border: 1px dashed #b8c7d6;
    border-radius: 8px;
    padding: 22px;
    font-size: 16px;
}
QLabel#ResultsHint[compact="true"] {
    background: #F9FAFB;
    border: 1px solid #dce6ef;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 700;
}
QFrame#SmartBanner {
    background: transparent;
    border: 0;
}
QFrame#SmartBannerRow {
    background: #F0FDF4;
    border: 1px solid #BBF7D0;
    border-left: 6px solid #22C55E;
    border-radius: 8px;
}
QFrame#SmartBannerRow[priority="followup"] {
    background: #FFF7ED;
    border: 1px solid #FDBA74;
    border-left: 6px solid #F97316;
}
QLabel#SmartBannerText {
    color: #111827;
    font-size: 16px;
    font-weight: 800;
}
QLabel#FollowUpHelp {
    color: #6B7280;
    font-weight: 700;
}
QLabel#RoutePreviewNote {
    color: #6B7280;
    font-weight: 700;
    padding: 4px 2px 8px 2px;
}
QLabel#FollowUpGroupLabel {
    color: #111827;
    font-size: 16px;
    font-weight: 900;
    padding: 8px 2px 2px 2px;
}
QFrame#FollowUpCard {
    background: #ffffff;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
}
QLabel#FollowUpBusinessName {
    color: #111827;
    font-size: 18px;
    font-weight: 900;
}
QLabel#FollowUpMeta {
    color: #6B7280;
    font-weight: 700;
}
QPlainTextEdit#FollowUpNotes {
    background: #F9FAFB;
}
QPushButton#SmartBannerButton {
    background: #ffffff;
    border: 1px solid #CBD5E1;
    color: #2563EB;
    font-weight: 800;
}
QPushButton#SmartBannerButton:hover {
    background: #EFF6FF;
}
QLabel#SelectedCount {
    background: transparent;
    color: #14532D;
    border: 0;
    border-radius: 8px;
    padding: 4px;
    font-weight: 800;
    font-size: 16px;
}
QFrame#SelectionBar {
    background: #DCFCE7;
    border: 2px solid #22C55E;
    border-radius: 8px;
}
QFrame#SimpleStartCard {
    background: #ffffff;
    border: 1px solid #dce6ef;
    border-radius: 8px;
}
QFrame#SimpleStartCard QLineEdit, QFrame#SimpleStartCard QComboBox, QFrame#SimpleStartCard QToolButton {
    min-height: 26px;
}
QLabel#SimpleStartTitle {
    color: #111827;
    font-size: 24px;
    font-weight: 800;
}
QLabel#SimpleStartSubtitle {
    color: #6B7280;
    font-size: 15px;
}
QLabel#SimpleSectionLabel {
    color: #111827;
    font-weight: 800;
}
QLabel#SimpleCategorySummary {
    color: #6B7280;
    font-size: 13px;
}
QCheckBox#CategoryToggle {
    background: #F9FAFB;
    border: 1px solid #dce6ef;
    border-radius: 8px;
    padding: 8px 10px;
    color: #111827;
    font-weight: 700;
}
QCheckBox#CategoryToggle:checked {
    background: #DCFCE7;
    border-color: #22C55E;
    color: #22C55E;
}
QFrame#StartAddressFrame {
    background: #ffffff;
    border: 1px solid #dce6ef;
    border-radius: 8px;
}
QFrame#ScriptCard {
    background: #ffffff;
    border: 1px solid #dce6ef;
    border-radius: 8px;
}
QLabel#ScriptTitle {
    color: #111827;
    font-size: 18px;
    font-weight: 800;
}
QLabel#ScriptCategory {
    color: #2563EB;
    font-size: 20px;
    font-weight: 800;
}
QLabel#ScriptUseCase {
    color: #6B7280;
}
QLabel#StartAddressLabel {
    color: #111827;
    font-weight: 800;
}
QLabel#WorkflowStep, QPushButton#WorkflowStep {
    background: #ffffff;
    color: #506172;
    border: 1px solid #d8e2ec;
    border-radius: 8px;
    padding: 10px 12px;
    font-weight: 700;
}
QLabel#WorkflowStep[active="true"], QPushButton#WorkflowStep[active="true"] {
    background: #22C55E;
    color: #ffffff;
    border-color: #22C55E;
}
QLabel#WorkflowStep[complete="true"], QPushButton#WorkflowStep[complete="true"] {
    background: #DCFCE7;
    color: #22C55E;
    border-color: #BBF7D0;
}
QPushButton#WorkflowStep:hover {
    border-color: #22C55E;
}
QLabel#RouteModeTitle {
    color: #111827;
    font-size: 20px;
    font-weight: 800;
}
QSplitter::handle {
    background: transparent;
    border-radius: 3px;
}
QSplitter::handle:vertical {
    height: 0px;
}
QSplitter::handle:horizontal {
    width: 0px;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #dce6ef;
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px;
    font-weight: 600;
    color: #22C55E;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QListWidget, QToolButton {
    background: #ffffff;
    border: 1px solid #c8d6e3;
    border-radius: 6px;
}
QWebEngineView {
    background: #ffffff;
    border: 1px solid #dce6ef;
    border-radius: 8px;
}
QLineEdit, QComboBox, QPlainTextEdit, QToolButton {
    padding: 8px;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QListWidget:focus {
    border-color: #22C55E;
}
QToolButton {
    font-weight: 600;
    color: #22C55E;
}
QToolButton#BusinessTypeDropdown {
    min-width: 220px;
    font-weight: 800;
}
QMenu {
    background: #ffffff;
    border: 1px solid #c8d6e3;
    padding: 6px;
}
QMenu::item {
    padding: 7px 28px 7px 24px;
}
QMenu::item:selected {
    background: #DCFCE7;
}
QTabWidget::pane {
    border: 1px solid #dce6ef;
    border-radius: 8px;
    background: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: #e8eef5;
    color: #425466;
    border: 1px solid #d6e1ea;
    padding: 10px 18px;
    min-width: 120px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
    font-weight: 700;
}
QTabBar::tab:selected {
    background: #22C55E;
    color: #ffffff;
    border-color: #22C55E;
}
QTabBar::tab:hover:!selected {
    background: #d9e8f5;
}
QHeaderView::section {
    background: #22C55E;
    color: #ffffff;
    border: 0;
    border-right: 1px solid #86EFAC;
    border-bottom: 1px solid #86EFAC;
    padding: 10px;
    font-weight: 700;
}
QTableWidget {
    gridline-color: #edf2f7;
    alternate-background-color: #F9FAFB;
    selection-background-color: #DCFCE7;
    selection-color: #111827;
}
QProgressBar#GenerationProgress {
    background: #DCFCE7;
    border: 1px solid #BBF7D0;
    border-radius: 6px;
    min-height: 12px;
    max-height: 12px;
}
QProgressBar#GenerationProgress::chunk {
    background: #22C55E;
    border-radius: 5px;
}
QListWidget#MapLeadList {
    padding: 8px;
    outline: 0;
}
QListWidget#MapLeadList::item {
    background: #ffffff;
    border: 1px solid #dce6ef;
    border-radius: 6px;
    padding: 8px;
}
QListWidget#MapLeadList::item:hover {
    background: #f0fbff;
    border-color: #22C55E;
}
QListWidget#MapLeadList::item:selected {
    background: #22C55E;
    color: #ffffff;
    border-color: #22C55E;
}
QListWidget#LeadCardList {
    background: transparent;
    border: 0;
    padding: 0;
    outline: 0;
    font-size: 16px;
}
QListWidget#LeadCardList::item {
    background: #ffffff;
    border: 1px solid #dce6ef;
    border-radius: 8px;
    padding: 18px;
}
QListWidget#LeadCardList::item:hover {
    background: #f0fbff;
    border-color: #BBF7D0;
}
QListWidget#LeadCardList::item:checked {
    background: #DCFCE7;
    color: #111827;
    border: 3px solid #16A34A;
}
QListWidget#LeadCardList::item:selected {
    background: #BBF7D0;
    color: #111827;
    border: 3px solid #16A34A;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #bfd0df;
    border-radius: 6px;
    padding: 10px 16px;
    font-weight: 600;
    color: #2563EB;
}
QPushButton:hover {
    background: #EFF6FF;
}
QPushButton:disabled {
    color: #9aa9b6;
    background: #eef3f7;
}
QPushButton#PrimaryButton {
    background: #22C55E;
    border-color: #22C55E;
    color: #ffffff;
}
QPushButton#PrimaryButton:hover {
    background: #16A34A;
}
QPushButton#HeroButton {
    background: #22C55E;
    border-color: #16A34A;
    color: #ffffff;
    font-size: 16px;
    font-weight: 900;
    padding: 13px 22px;
}
QPushButton#HeroButton:hover {
    background: #16A34A;
}
QFrame#CurrentStopCard {
    background: #ffffff;
    border: 1px solid #dce6ef;
    border-radius: 8px;
}
QLabel#StopBadge {
    background: #FED7AA;
    color: #111827;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 800;
}
QLabel#CurrentStopName {
    color: #22C55E;
    font-size: 23px;
    font-weight: 800;
}
QLabel#CurrentStopAddress {
    color: #111827;
    font-size: 15px;
}
QLabel#CurrentStopReason, QLabel#CurrentStopWindow, QLabel#RouteProgress {
    color: #6B7280;
    font-size: 14px;
    font-weight: 600;
}
QLabel#CurrentStopMeta {
    color: #111827;
    font-size: 14px;
    font-weight: 700;
}
QListWidget#UpcomingStopsList {
    background: #ffffff;
    border: 1px solid #dbe7f2;
    border-radius: 10px;
    padding: 8px;
}
QListWidget#UpcomingStopsList::item {
    background: #ffffff;
    border: 1px solid #c9d8e6;
    border-radius: 8px;
    padding: 12px;
}
QListWidget#UpcomingStopsList::item:selected {
    background: #DCFCE7;
    color: #111827;
    border-color: #BBF7D0;
}
QLabel#SummaryTile, QLabel#OutputLocation {
    background: #ffffff;
    border: 1px solid #dce6ef;
    border-radius: 8px;
    padding: 14px;
    line-height: 1.4;
}
"""


DARK_STYLES = """
QWidget {
    background: #0F172A;
    color: #f2e9dc;
    font-family: Segoe UI, Arial, sans-serif;
    font-size: 14px;
}
QLabel#Title {
    font-size: 30px;
    font-weight: 700;
    color: #22C55E;
}
QLabel#Subtitle, QLabel#MarketPreview, QLabel#ResultsHint, QLabel#KeywordSummary {
    color: #c3d3df;
}
QLabel#ResultsHint {
    background: #1F2937;
    border: 1px dashed #374151;
    border-radius: 8px;
    padding: 22px;
    font-size: 16px;
}
QLabel#ResultsHint[compact="true"] {
    background: #111827;
    border: 1px solid #374151;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 700;
}
QFrame#SmartBanner {
    background: transparent;
    border: 0;
}
QFrame#SmartBannerRow {
    background: #14532D;
    border: 1px solid #86EFAC;
    border-left: 6px solid #22C55E;
    border-radius: 8px;
}
QFrame#SmartBannerRow[priority="followup"] {
    background: #431407;
    border: 1px solid #F97316;
    border-left: 6px solid #F97316;
}
QLabel#SmartBannerText {
    color: #F8FAFC;
    font-size: 16px;
    font-weight: 800;
}
QLabel#FollowUpHelp {
    color: #D1D5DB;
    font-weight: 700;
}
QLabel#RoutePreviewNote {
    color: #D1D5DB;
    font-weight: 700;
    padding: 4px 2px 8px 2px;
}
QLabel#FollowUpGroupLabel {
    color: #F8FAFC;
    font-size: 16px;
    font-weight: 900;
    padding: 8px 2px 2px 2px;
}
QFrame#FollowUpCard {
    background: #1F2937;
    border: 1px solid #374151;
    border-radius: 8px;
}
QLabel#FollowUpBusinessName {
    color: #F8FAFC;
    font-size: 18px;
    font-weight: 900;
}
QLabel#FollowUpMeta {
    color: #D1D5DB;
    font-weight: 700;
}
QPlainTextEdit#FollowUpNotes {
    background: #111827;
}
QPushButton#SmartBannerButton {
    background: #1F2937;
    border: 1px solid #4B5563;
    color: #86EFAC;
    font-weight: 800;
}
QPushButton#SmartBannerButton:hover {
    background: #111827;
}
QFrame#SimpleStartCard {
    background: #1F2937;
    border: 1px solid #374151;
    border-radius: 8px;
}
QFrame#SimpleStartCard QLineEdit, QFrame#SimpleStartCard QComboBox, QFrame#SimpleStartCard QToolButton {
    min-height: 26px;
}
QLabel#SimpleStartTitle {
    color: #f2e9dc;
    font-size: 24px;
    font-weight: 800;
}
QLabel#SimpleStartSubtitle {
    color: #c3d3df;
    font-size: 15px;
}
QLabel#SimpleSectionLabel {
    color: #f2e9dc;
    font-weight: 800;
}
QLabel#SimpleCategorySummary {
    color: #c3d3df;
    font-size: 13px;
}
QCheckBox#CategoryToggle {
    background: #111827;
    border: 1px solid #374151;
    border-radius: 8px;
    padding: 8px 10px;
    color: #f2e9dc;
    font-weight: 700;
}
QCheckBox#CategoryToggle:checked {
    background: #14532D;
    border-color: #86EFAC;
    color: #22C55E;
}
QFrame#StartAddressFrame {
    background: #1F2937;
    border: 1px solid #374151;
    border-radius: 8px;
}
QFrame#ScriptCard {
    background: #1F2937;
    border: 1px solid #374151;
    border-radius: 8px;
}
QLabel#ScriptTitle {
    color: #f2e9dc;
    font-size: 18px;
    font-weight: 800;
}
QLabel#ScriptCategory {
    color: #22C55E;
    font-size: 20px;
    font-weight: 800;
}
QLabel#ScriptUseCase {
    color: #c3d3df;
}
QLabel#StartAddressLabel {
    color: #f2e9dc;
    font-weight: 800;
}
QLabel#SelectedCount {
    background: transparent;
    color: #DCFCE7;
    border: 0;
    border-radius: 8px;
    padding: 4px;
    font-weight: 800;
    font-size: 16px;
}
QFrame#SelectionBar {
    background: #14532D;
    border: 2px solid #86EFAC;
    border-radius: 8px;
}
QSplitter::handle {
    background: transparent;
    border-radius: 3px;
}
QSplitter::handle:vertical {
    height: 0px;
}
QSplitter::handle:horizontal {
    width: 0px;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QGroupBox {
    background: #1F2937;
    border: 1px solid #374151;
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px;
    font-weight: 600;
    color: #22C55E;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QListWidget, QToolButton {
    background: #111827;
    color: #f2e9dc;
    border: 1px solid #374151;
    border-radius: 6px;
}
QWebEngineView {
    background: #1F2937;
    border: 1px solid #374151;
    border-radius: 8px;
}
QLineEdit, QComboBox, QPlainTextEdit, QToolButton {
    padding: 8px;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QListWidget:focus {
    border-color: #86EFAC;
}
QToolButton {
    font-weight: 600;
    color: #22C55E;
}
QToolButton#BusinessTypeDropdown {
    min-width: 220px;
    font-weight: 800;
}
QMenu {
    background: #1F2937;
    color: #f2e9dc;
    border: 1px solid #374151;
    padding: 6px;
}
QMenu::item {
    padding: 7px 28px 7px 24px;
}
QMenu::item:selected {
    background: #14532D;
}
QTabWidget::pane {
    border: 1px solid #374151;
    border-radius: 8px;
    background: #1F2937;
    top: -1px;
}
QTabBar::tab {
    background: #152331;
    color: #c3d3df;
    border: 1px solid #374151;
    padding: 10px 18px;
    min-width: 120px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
    font-weight: 700;
}
QTabBar::tab:selected {
    background: #22C55E;
    color: #ffffff;
    border-color: #86EFAC;
}
QTabBar::tab:hover:!selected {
    background: #183044;
}
QHeaderView::section {
    background: #22C55E;
    color: #ffffff;
    border: 0;
    border-right: 1px solid #86EFAC;
    border-bottom: 1px solid #86EFAC;
    padding: 8px;
    font-weight: 700;
}
QTableWidget {
    gridline-color: #263a4b;
    alternate-background-color: #191e25;
    selection-background-color: #14532D;
    selection-color: #ffffff;
}
QProgressBar#GenerationProgress {
    background: #152331;
    border: 1px solid #374151;
    border-radius: 6px;
    min-height: 12px;
    max-height: 12px;
}
QProgressBar#GenerationProgress::chunk {
    background: #22C55E;
    border-radius: 5px;
}
QListWidget#MapLeadList {
    padding: 8px;
    outline: 0;
}
QListWidget#MapLeadList::item {
    background: #191e25;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 8px;
}
QListWidget#MapLeadList::item:hover {
    background: #183044;
    border-color: #86EFAC;
}
QListWidget#MapLeadList::item:selected {
    background: #22C55E;
    color: #ffffff;
    border-color: #86EFAC;
}
QListWidget#LeadCardList {
    background: transparent;
    border: 0;
    padding: 0;
    outline: 0;
    font-size: 16px;
}
QListWidget#LeadCardList::item {
    background: #1F2937;
    border: 1px solid #374151;
    border-radius: 8px;
    padding: 18px;
}
QListWidget#LeadCardList::item:hover {
    background: #183044;
    border-color: #86EFAC;
}
QListWidget#LeadCardList::item:checked {
    background: #14532D;
    color: #ffffff;
    border: 3px solid #86EFAC;
}
QListWidget#LeadCardList::item:selected {
    background: #14532D;
    color: #ffffff;
    border: 3px solid #86EFAC;
}
QPushButton {
    background: #152331;
    color: #f2e9dc;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 10px 16px;
    font-weight: 600;
}
QPushButton:hover {
    background: #183044;
}
QPushButton:disabled {
    color: #7d91a1;
    background: #1F2937;
}
QPushButton#PrimaryButton {
    background: #22C55E;
    border-color: #86EFAC;
    color: #ffffff;
}
QPushButton#PrimaryButton:hover {
    background: #16A34A;
}
QPushButton#HeroButton {
    background: #22C55E;
    border-color: #86EFAC;
    color: #ffffff;
    font-size: 16px;
    font-weight: 900;
    padding: 13px 22px;
}
QPushButton#HeroButton:hover {
    background: #16A34A;
}
QFrame#CurrentStopCard {
    background: #1F2937;
    border: 1px solid #86EFAC;
    border-radius: 8px;
}
QLabel#StopBadge {
    background: #FED7AA;
    color: #111827;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 800;
}
QLabel#CurrentStopName {
    color: #22C55E;
    font-size: 23px;
    font-weight: 800;
}
QLabel#CurrentStopAddress {
    color: #f2e9dc;
    font-size: 15px;
}
QLabel#CurrentStopReason, QLabel#CurrentStopWindow, QLabel#RouteProgress {
    color: #c3d3df;
    font-size: 14px;
    font-weight: 600;
}
QLabel#CurrentStopMeta {
    color: #f2e9dc;
    font-size: 14px;
    font-weight: 700;
}
QListWidget#UpcomingStopsList {
    background: #1F2937;
    border: 1px solid #374151;
    border-radius: 10px;
    padding: 8px;
}
QListWidget#UpcomingStopsList::item {
    background: #111827;
    border: 1px solid #4B5563;
    border-radius: 8px;
    padding: 12px;
}
QListWidget#UpcomingStopsList::item:selected {
    background: #14532D;
    color: #f2e9dc;
    border-color: #86EFAC;
}
QLabel#SummaryTile, QLabel#OutputLocation {
    background: #1F2937;
    border: 1px solid #374151;
    border-radius: 8px;
    padding: 14px;
    line-height: 1.4;
}
"""


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())


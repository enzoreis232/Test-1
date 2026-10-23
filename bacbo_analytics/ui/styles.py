"""Tema e identidade visual compartilhados pela aplicação desktop."""

STYLESHEET = """
QWidget { background: #0e1118; color: #e8edf7; font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 12px; }
QMainWindow, QDialog { background: #0e1118; }
QLabel { background: transparent; }
QFrame#card, QFrame#panel { background: #171c28; border: 1px solid #252d3e; border-radius: 12px; }
QFrame#sidebar { background: #121722; border-right: 1px solid #252d3e; }
QLabel#brand { font-size: 19px; font-weight: 800; letter-spacing: 1px; }
QLabel#eyebrow { color: #8292ae; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#heading { font-size: 27px; font-weight: 700; }
QLabel#sectionTitle { font-size: 14px; font-weight: 600; }
QLabel#muted { color: #91a0b9; }
QLabel#status { color: #58d8b1; background: #18352e; padding: 7px 12px; border-radius: 12px; }
QLabel#badge { color: #83b3ff; background: #20304c; padding: 5px 10px; border-radius: 9px; font-weight: 600; }
QLabel#warning { color: #eac986; background: #302a1e; border-radius: 8px; padding: 10px; }
QPushButton { border: 1px solid #303a4e; border-radius: 8px; background: #212a3b; padding: 9px 13px; font-weight: 600; }
QPushButton:hover { background: #2c3850; border-color: #4d6386; }
QPushButton:pressed { background: #182334; }
QPushButton:disabled { color: #637088; border-color: #252d3e; background: #191f2c; }
QPushButton#primary { background: #3478ed; border: 1px solid #4089ff; color: white; }
QPushButton#primary:hover { background: #4388ff; }
QPushButton#danger { color: #ff8293; }
QPushButton#nav { text-align: left; padding: 11px 14px; background: transparent; border: none; color: #9baac3; }
QPushButton#nav:checked { background: #20304c; color: #a7c9ff; border-left: 3px solid #4b91ff; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #171d29; color: #94a3bd; padding: 10px 16px; margin-right: 4px; border-radius: 6px; }
QTabBar::tab:selected { color: #e8edf7; background: #283650; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit { background: #101621; border: 1px solid #33405a; border-radius: 6px; padding: 7px; selection-background-color: #3478ed; }
QSpinBox, QDoubleSpinBox { min-height: 22px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #182131; selection-background-color: #294c7e; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #465978; border-radius: 4px; background: #101621; }
QCheckBox::indicator:checked { background: #4089ff; }
QTableWidget, QTableView { background: #141a25; alternate-background-color: #192130; border: 1px solid #2a3448; border-radius: 8px; gridline-color: #252f42; selection-background-color: #284a78; }
QHeaderView::section { background: #1c2637; color: #99abc6; border: none; padding: 10px; font-weight: 600; }
QTableWidget::item { padding: 7px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #101621; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #34415a; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QSplitter::handle { background: #252d3e; height: 2px; }
QProgressBar { border: none; background: #252f42; border-radius: 4px; height: 7px; text-align: center; }
QProgressBar::chunk { border-radius: 4px; background: #4b91ff; }
QToolTip { background: #26334b; color: #e8edf7; border: 1px solid #405477; padding: 5px; }
QStatusBar { background: #101621; color: #8797b1; }
QGroupBox { border: 1px solid #2e394e; border-radius: 8px; margin-top: 14px; padding: 14px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; color: #acc5ed; }
"""

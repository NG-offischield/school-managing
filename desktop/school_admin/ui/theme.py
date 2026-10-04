"""Light, professional look (Qt style sheet). Colours stay neutral: the
school's own branding belongs to its official documents, not to this tool."""

PRIMARY = "#173B73"

STYLE = f"""
QWidget {{ font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 10pt; color: #1f2933; }}
QMainWindow, #page {{ background: #f5f7fa; }}
#sidebar {{ background: {PRIMARY}; border: none; }}
#sidebar QListWidget {{ background: transparent; border: none; color: #e4ebf5; outline: none; }}
#sidebar QListWidget::item {{ padding: 8px 14px; border-radius: 4px; margin: 1px 6px; }}
#sidebar QListWidget::item:selected {{ background: rgba(255,255,255,0.18); color: white; }}
#sidebar QListWidget::item:disabled {{ color: rgba(228,235,245,0.45); }}
#brand {{ color: white; font-size: 13pt; font-weight: 600; padding: 16px 14px 8px 14px; }}
#header {{ background: white; border-bottom: 1px solid #dde3ea; }}
#pageTitle {{ font-size: 15pt; font-weight: 600; }}
#muted {{ color: #66788a; }}
#card {{ background: white; border: 1px solid #dde3ea; border-radius: 8px; }}
#cardValue {{ font-size: 18pt; font-weight: 600; color: {PRIMARY}; }}
#cardError {{ color: #a15c07; }}
#banner[kind="error"] {{ background: #fdecea; color: #8a1c13; border-radius: 6px; padding: 8px; }}
#banner[kind="warning"] {{ background: #fff4e5; color: #7a4a00; border-radius: 6px; padding: 8px; }}
#banner[kind="success"] {{ background: #e7f6ec; color: #1e6b35; border-radius: 6px; padding: 8px; }}
#banner[kind="info"] {{ background: #e8f0fb; color: #173b73; border-radius: 6px; padding: 8px; }}
QPushButton {{ padding: 6px 14px; border-radius: 5px; border: 1px solid #c8d1dc; background: white; }}
QPushButton:hover {{ background: #eef2f7; }}
QPushButton:disabled {{ color: #9aa7b4; }}
QPushButton#primary {{ background: {PRIMARY}; color: white; border: none; }}
QPushButton#primary:disabled {{ background: #8496b3; }}
QLineEdit, QComboBox, QPlainTextEdit {{ padding: 5px; border: 1px solid #c8d1dc; border-radius: 5px;
    background: white; }}
QTableView {{ background: white; border: 1px solid #dde3ea; gridline-color: #eef2f7;
    selection-background-color: #dbe6f6; selection-color: #1f2933; }}
QHeaderView::section {{ background: #eef2f7; padding: 6px; border: none; font-weight: 600; }}
"""

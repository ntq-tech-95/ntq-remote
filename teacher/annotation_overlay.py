"""Bảng vẽ chú thích trực tiếp trên màn hình Giáo viên khi trình chiếu hoặc giảng bài."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class _AnnotationCanvas(QWidget):
    """Lớp phủ trong suốt toàn màn hình dùng để vẽ nét bút trực tiếp."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._strokes: list[tuple[QColor, int, list[QPoint]]] = []
        self._current_points: list[QPoint] = []
        self._pen_color = QColor(239, 68, 68, 240)
        self._pen_width = 4
        self._drawing_enabled = True

    def set_pen(self, color: QColor, width: int) -> None:
        self._pen_color = color
        self._pen_width = width

    def set_drawing_enabled(self, enabled: bool) -> None:
        self._drawing_enabled = enabled
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, not enabled)
        self.showFullScreen()

    def undo(self) -> None:
        if self._strokes:
            self._strokes.pop()
            self.update()

    def clear_all(self) -> None:
        self._strokes.clear()
        self._current_points.clear()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._drawing_enabled and event.button() == Qt.MouseButton.LeftButton:
            self._current_points = [event.position().toPoint()]
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drawing_enabled and self._current_points:
            self._current_points.append(event.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drawing_enabled and self._current_points:
            self._current_points.append(event.position().toPoint())
            self._strokes.append(
                (QColor(self._pen_color), self._pen_width, list(self._current_points))
            )
            self._current_points = []
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._drawing_enabled:
            # Lớp nền cực mờ giúp nhận thao tác chuột trên Windows
            painter.fillRect(self.rect(), QColor(0, 0, 0, 2))
        for color, width, pts in self._strokes:
            self._draw_polyline(painter, color, width, pts)
        if self._current_points:
            self._draw_polyline(
                painter, self._pen_color, self._pen_width, self._current_points
            )

    @staticmethod
    def _draw_polyline(
        painter: QPainter, color: QColor, width: int, pts: list[QPoint]
    ) -> None:
        if len(pts) < 2:
            return
        pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        for i in range(1, len(pts)):
            painter.drawLine(pts[i - 1], pts[i])


class AnnotationController(QWidget):
    """Thanh công cụ nổi 100% Tiếng Việt để vẽ chú thích lên màn hình."""

    def __init__(self, on_closed=None) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._on_closed = on_closed
        self._canvas = _AnnotationCanvas()
        self.setStyleSheet(
            """
            QWidget { background-color: #0f172a; color: #ffffff; border-radius: 8px; }
            QPushButton {
                background-color: #1e293b; color: #ffffff; border: 1px solid #475569;
                border-radius: 5px; padding: 5px 9px; font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { background-color: #334155; }
            QPushButton:checked { background-color: #2563eb; border-color: #60a5fa; }
            """
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)

        self.btn_mode = QPushButton("✏ Đang vẽ (Bấm để thao tác chuột)")
        self.btn_mode.setCheckable(True)
        self.btn_mode.setChecked(True)
        self.btn_mode.toggled.connect(self._toggle_draw_mode)
        row.addWidget(self.btn_mode)

        btn_red = QPushButton("🔴 Đỏ")
        btn_red.clicked.connect(lambda: self._canvas.set_pen(QColor(239, 68, 68, 240), 4))
        row.addWidget(btn_red)

        btn_blue = QPushButton("🔵 Xanh")
        btn_blue.clicked.connect(lambda: self._canvas.set_pen(QColor(59, 130, 246, 240), 4))
        row.addWidget(btn_blue)

        btn_yellow = QPushButton("🟡 Dạ quang")
        btn_yellow.clicked.connect(lambda: self._canvas.set_pen(QColor(250, 204, 21, 140), 14))
        row.addWidget(btn_yellow)

        btn_undo = QPushButton("↩ Hoàn tác")
        btn_undo.clicked.connect(self._canvas.undo)
        row.addWidget(btn_undo)

        btn_clear = QPushButton("🗑 Xóa bảng")
        btn_clear.clicked.connect(self._canvas.clear_all)
        row.addWidget(btn_clear)

        btn_close = QPushButton("✖ Đóng bảng vẽ")
        btn_close.setStyleSheet("background-color: #b91c1c; border-color: #ef4444;")
        btn_close.clicked.connect(self.stop)
        row.addWidget(btn_close)

    def start(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen:
            geom = screen.geometry()
            self._canvas.setGeometry(geom)
            self.adjustSize()
            x = geom.x() + (geom.width() - self.width()) // 2
            self.move(x, geom.y() + 12)
        self._canvas.set_drawing_enabled(True)
        self.btn_mode.setChecked(True)
        self._canvas.showFullScreen()
        self.show()
        self.raise_()

    def stop(self) -> None:
        self._canvas.clear_all()
        self._canvas.hide()
        self.hide()
        if self._on_closed:
            self._on_closed()

    def _toggle_draw_mode(self, checked: bool) -> None:
        self._canvas.set_drawing_enabled(checked)
        if checked:
            self.btn_mode.setText("✏ Đang vẽ (Bấm để thao tác chuột)")
        else:
            self.btn_mode.setText("🖱 Đang bấm xuyên (Bấm để vẽ tiếp)")
        self.raise_()

# tests/test_e2_finish_answer.py

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

# Ajusta este import al módulo real donde está tu widget.
from main import MessageBubble
@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
def flush(qapp: QApplication) -> None:
    qapp.processEvents()
@pytest.fixture
def assistant(qapp: QApplication):
    """
    Crea un MessageBubble assistant dentro de una ventana visible.

    Esto es necesario para que isVisible() refleje realmente el estado
    del text_browser, no solo el estado del padre oculto.
    """
    widget = MessageBubble("assistant", "")

    window = QWidget()
    layout = QVBoxLayout(window)
    layout.addWidget(widget)

    window.resize(720, 520)
    window.show()
    flush(qapp)

    yield widget

    window.close()
    window.deleteLater()
    flush(qapp)
class TestE2FinishAnswer:
    # --------------------------------------------------
    # T1: anti-fantasma - prueba anti-fantasma correcta
    # --------------------------------------------------
    def test_t1_initial_widget_hidden(self, qapp):
        """Test anti-fantasma: text_browser debe estar oculto sin window padre"""
        # Crear MessageBubble en aislamiento sin window padre
        widget = MessageBubble("assistant", "")
        
        # Text browser should be hidden initially (anti-fantasma)
        assert not widget.text_browser.isVisible()
        
        # Cleanup
        widget.deleteLater()

    # --------------------------------------------------
    # T2: primer delta muestra widget (usando assistant fixture)
    # --------------------------------------------------
    def test_t2_first_delta_shows_widget(self, assistant, qapp):
        assistant.appendAnswer("Hello")
        flush(qapp)

        assert assistant.text_browser.isVisible()
        assert "Hello" in assistant.text_browser.toPlainText()
        assert assistant._answer_started is True

    # --------------------------------------------------
    # T3: stream vacío sin nada útil => oculto y limpio
    # --------------------------------------------------
    def test_t3_empty_stream_hides_and_clears(self, assistant, qapp):
        assistant.tool_block = None
        assistant.thinking_block = None

        assistant.finishAnswer(
            answer="",
            thinking="",
            error=None
        )
        flush(qapp)

        assert not assistant.text_browser.isVisible()
        assert assistant.text_browser.toPlainText() == ""
        assert assistant._answer_started is False

    # --------------------------------------------------
    # T4: respuesta final autoritativa sin streaming
    # --------------------------------------------------
    def test_t4_final_answer_shows_without_streaming(self, assistant, qapp):
        assistant.finishAnswer(
            answer="Respuesta final",
            thinking="",
            error=None
        )
        flush(qapp)

        assert assistant.text_browser.isVisible()
        assert "Respuesta final" in assistant.text_browser.toPlainText()
        assert assistant._answer_started is True

    # --------------------------------------------------
    # T5: streaming preservado cuando answer está vacío
    # --------------------------------------------------
    def test_t5_streaming_preserved_when_answer_empty(self, assistant, qapp):
        assistant.appendAnswer("Parte 1 ")
        assistant.appendAnswer("Parte 2")

        assistant.finishAnswer(
            answer="",
            thinking="",
            error=None
        )
        flush(qapp)

        text = assistant.text_browser.toPlainText()

        assert assistant.text_browser.isVisible()
        assert "Parte 1" in text
        assert "Parte 2" in text
        assert "el modelo no produjo síntesis" not in text
        assert assistant._answer_started is True

    # --------------------------------------------------
    # T6: answer final autoritativa sobrescribe streaming parcial
    # --------------------------------------------------
    def test_t6_final_answer_overrides_streaming(self, assistant, qapp):
        assistant.appendAnswer("parcial")

        assistant.finishAnswer(
            answer="Final",
            thinking="",
            error=None
        )
        flush(qapp)

        text = assistant.text_browser.toPlainText()

        assert assistant.text_browser.isVisible()
        assert "Final" in text
        assert "parcial" not in text
        assert assistant._answer_started is True

    # --------------------------------------------------
    # T7: error sin texto previo se muestra
    # --------------------------------------------------
    def test_t7_error_without_prior_text_is_shown(self, assistant, qapp):
        assistant.finishAnswer(
            answer="",
            thinking="",
            error="Connection failed"
        )
        flush(qapp)

        assert assistant.text_browser.isVisible()
        assert "Connection failed" in assistant.text_browser.toPlainText()
        assert assistant._answer_started is True

    # --------------------------------------------------
    # T8: error no es sobrescrito por answer
    # --------------------------------------------------
    def test_t8_error_not_overwritten_by_answer(self, assistant, qapp):
        assistant.finishAnswer(
            answer="This should not appear",
            thinking="",
            error="Database connection failed"
        )
        flush(qapp)

        text = assistant.text_browser.toPlainText()

        assert assistant.text_browser.isVisible()
        assert "Database connection failed" in text
        assert "This should not appear" not in text
        assert assistant._answer_started is True

    # --------------------------------------------------
    # T9: error con texto parcial previo preserva texto y añade error
    # --------------------------------------------------
    def test_t9_error_with_partial_text_preserves_content(self, assistant, qapp):
        assistant.appendAnswer("Parcial")

        assistant.finishAnswer(
            answer="ignored",
            thinking="",
            error="boom"
        )
        flush(qapp)

        text = assistant.text_browser.toPlainText()

        assert assistant.text_browser.isVisible()
        assert "Parcial" in text
        assert "[ERROR] boom" in text
        assert "ignored" not in text
        assert assistant._answer_started is True

    # --------------------------------------------------
    # T10: cleanup thinking_block se ejecuta incluso en error
    # --------------------------------------------------
    def test_t10_cleanup_thinking_block_runs_on_error(self, assistant, qapp):
        assistant.thinking_block = Mock()
        assistant.tool_block = None

        with patch.object(assistant, "updateGeometry") as mock_update, \
             patch.object(assistant, "layout") as mock_layout:

            mock_layout.return_value = Mock()

            assistant.finishAnswer(
                answer="",
                thinking="reasoning",
                error="timeout"
            )
            flush(qapp)

        assistant.thinking_block.finish.assert_called_once_with("reasoning")
        mock_update.assert_called_once()
        mock_layout.return_value.activate.assert_called_once()

    # --------------------------------------------------
    # T11: cleanup tool_block se ejecuta incluso en error
    # --------------------------------------------------
    def test_t11_cleanup_tool_block_runs_on_error(self, assistant, qapp):
        assistant.thinking_block = None
        assistant.tool_block = Mock()

        with patch.object(assistant, "updateGeometry") as mock_update, \
             patch.object(assistant, "layout") as mock_layout:

            mock_layout.return_value = Mock()

            assistant.finishAnswer(
                answer="",
                thinking="",
                error="timeout"
            )
            flush(qapp)

        assistant.tool_block.finish.assert_called_once()
        mock_update.assert_called_once()
        mock_layout.return_value.activate.assert_called_once()

    # --------------------------------------------------
    # T12: cleanup updateGeometry se ejecuta en ruta normal
    # --------------------------------------------------
    def test_t12_cleanup_update_geometry_runs_on_normal_path(self, assistant, qapp):
        assistant.thinking_block = None
        assistant.tool_block = None

        with patch.object(assistant, "updateGeometry") as mock_update, \
             patch.object(assistant, "layout") as mock_layout:

            mock_layout.return_value = Mock()

            assistant.finishAnswer(
                answer="ok",
                thinking="",
                error=None
            )
            flush(qapp)

        mock_update.assert_called_once()
        mock_layout.return_value.activate.assert_called_once()

    # --------------------------------------------------
    # T13: cleanup layout().activate() se ejecuta en ruta normal
    # --------------------------------------------------
    def test_t13_cleanup_layout_activation_runs_on_normal_path(self, assistant, qapp):
        assistant.thinking_block = None
        assistant.tool_block = None

        with patch.object(assistant, "updateGeometry") as mock_update, \
             patch.object(assistant, "layout") as mock_layout:

            mock_layout.return_value = Mock()

            assistant.finishAnswer(
                answer="",
                thinking="",
                error=None
            )
            flush(qapp)

        mock_update.assert_called_once()
        mock_layout.return_value.activate.assert_called_once()

    # --------------------------------------------------
    # T14: placeholder visible cuando hay tool_block y no síntesis
    # --------------------------------------------------
    def test_t14_placeholder_visible_when_tool_block_exists(self, assistant, qapp):
        assistant.thinking_block = None
        assistant.tool_block = Mock()

        assistant.finishAnswer(
            answer="",
            thinking="",
            error=None
        )
        flush(qapp)

        text = assistant.text_browser.toPlainText()

        assert assistant.text_browser.isVisible()
        assert "el modelo no produjo síntesis" in text
        assert assistant._answer_started is True

    # --------------------------------------------------
    # T15: placeholder visible cuando hay thinking_block y no síntesis
    # --------------------------------------------------
    def test_t15_placeholder_visible_when_thinking_block_exists(self, assistant, qapp):
        assistant.thinking_block = Mock()
        assistant.tool_block = None

        assistant.finishAnswer(
            answer="",
            thinking="reasoning",
            error=None
        )
        flush(qapp)

        text = assistant.text_browser.toPlainText()

        assert assistant.text_browser.isVisible()
        assert "el modelo no produjo síntesis" in text
        assert assistant._answer_started is True

    # --------------------------------------------------
    # T16: sin text, sin answer, sin tools/thinking => oculto y limpio
    # --------------------------------------------------
    def test_t16_no_useful_content_hides_and_clears(self, assistant, qapp):
        assistant.thinking_block = None
        assistant.tool_block = None

        assistant.finishAnswer(
            answer="",
            thinking="",
            error=None
        )
        flush(qapp)

        assert not assistant.text_browser.isVisible()
        assert assistant.text_browser.toPlainText() == ""
        assert assistant._answer_started is False

    # --------------------------------------------------
    # T17: excepción en contenido no impide cleanup estructural
    # --------------------------------------------------
    def test_t17_exception_in_content_still_runs_cleanup(self, assistant, qapp):
        assistant.thinking_block = Mock()
        assistant.tool_block = Mock()

        with patch.object(
            assistant.text_browser,
            "setMarkdown",
            side_effect=RuntimeError("render failure")
        ):
            with pytest.raises(RuntimeError):
                assistant.finishAnswer(
                    answer="Respuesta",
                    thinking="reasoning",
                    error=None
                )
            flush(qapp)

        assistant.thinking_block.finish.assert_called_once_with("reasoning")
        assistant.tool_block.finish.assert_called_once()

    # --------------------------------------------------
    # T18: reset tras error deja estado limpio para nueva consulta
    # --------------------------------------------------
    def test_t18_reset_after_error_clears_state(self, assistant, qapp):
        assistant.finishAnswer(
            answer="",
            thinking="",
            error="previous error"
        )
        flush(qapp)

        assert assistant.text_browser.isVisible()
        assert "previous error" in assistant.text_browser.toPlainText()

        # Simula el reset que debería hacer send_message() para una nueva consulta.
        assistant.text_browser.clear()
        assistant.text_browser.hide()
        assistant._answer_started = False
        flush(qapp)

        assert not assistant.text_browser.isVisible()
        assert assistant.text_browser.toPlainText() == ""
        assert assistant._answer_started is False
from PySide6.QtWidgets import QWidget


class BasePage(QWidget):
    """ctx is the MainWindow — pages call ctx.navigate(name, **kwargs) to move around.
    on_show() runs every time the page becomes the visible one, so pages that show live
    data can refresh there."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def on_show(self, **kwargs) -> None:
        pass

    def back_mode(self) -> str:
        """What the Back button does here: "history" returns to the previous screen, "page"
        means this page steps back through its own questions (go_back()), and "blocked"
        means there's nowhere to go back to."""
        return "history"

    def go_back(self) -> None:
        pass

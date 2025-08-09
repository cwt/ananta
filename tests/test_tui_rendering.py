from ananta.tui import ListBoxWithScrollBar
import urwid
import pytest

# Mark all tests in this file as TUI tests
pytestmark = pytest.mark.tui


class TestListBoxWithScrollBar:
    def test_render_with_scrollbar(self):
        """Test that the scrollbar is rendered when the content is larger than the view."""
        # Setup a real walker and listbox
        widgets = [urwid.Text(f"Line {i}") for i in range(20)]
        walker = urwid.SimpleFocusListWalker(widgets)
        listbox = ListBoxWithScrollBar(walker)

        # Render in a size smaller than the content
        canvas = listbox.render((80, 10))

        # Check that the scrollbar is present
        scrollbar_text = listbox._scrollbar.text
        assert "█" in scrollbar_text
        assert "░" in scrollbar_text

    def test_render_no_scrollbar(self):
        """Test that no scrollbar is rendered when the content fits within the view."""
        widgets = [urwid.Text(f"Line {i}") for i in range(5)]
        walker = urwid.SimpleFocusListWalker(widgets)
        listbox = ListBoxWithScrollBar(walker)

        # Render in a size larger than the content
        listbox.render((80, 10))
        assert listbox._scrollbar.text == ""

    def test_keypress_forwarding(self):
        """Test that keypresses are forwarded to the internal ListBox."""
        widgets = [urwid.Text(f"Line {i}") for i in range(10)]
        walker = urwid.SimpleFocusListWalker(widgets)
        listbox = ListBoxWithScrollBar(walker)

        # Check that the focus changes on 'down' keypress
        initial_focus = walker.focus
        listbox.keypress((80, 5), "down")
        assert walker.focus > initial_focus

    def test_mouse_event_scrolling(self):
        """Test that mouse scroll events are handled."""
        widgets = [urwid.Text(f"Line {i}") for i in range(20)]
        walker = urwid.SimpleFocusListWalker(widgets)
        listbox = ListBoxWithScrollBar(walker)
        walker.set_focus(10)

        # Scroll up
        listbox.mouse_event((80, 10), "mouse press", 4, 0, 0, True)
        assert walker.focus < 10

        # Scroll down
        walker.set_focus(10)
        listbox.mouse_event((80, 10), "mouse press", 5, 0, 0, True)
        assert walker.focus > 10

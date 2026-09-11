import unittest

from sales_agents import keys


class DecodeTests(unittest.TestCase):
    def test_arrow_keys(self):
        self.assertEqual(keys.decode("\x1b[A"), "up")
        self.assertEqual(keys.decode("\x1b[B"), "down")
        self.assertEqual(keys.decode("\x1b[C"), "right")
        self.assertEqual(keys.decode("\x1b[D"), "left")

    def test_paging_and_jumping(self):
        self.assertEqual(keys.decode("\x1b[5~"), "pgup")
        self.assertEqual(keys.decode("\x1b[6~"), "pgdn")
        self.assertEqual(keys.decode("\x1b[H"), "home")
        self.assertEqual(keys.decode("\x1b[F"), "end")

    def test_enter_and_tab(self):
        self.assertEqual(keys.decode("\r"), "enter")
        self.assertEqual(keys.decode("\n"), "enter")
        self.assertEqual(keys.decode("\t"), "tab")

    def test_escape_alone(self):
        self.assertEqual(keys.decode("\x1b"), "esc")

    def test_interrupt_and_eof(self):
        self.assertEqual(keys.decode("\x03"), "ctrl-c")
        self.assertEqual(keys.decode("\x04"), "ctrl-d")

    def test_plain_characters_pass_through_lowercased(self):
        self.assertEqual(keys.decode("q"), "q")
        self.assertEqual(keys.decode("Q"), "q")
        self.assertEqual(keys.decode(" "), "space")

    def test_unknown_sequence_is_ignored(self):
        self.assertEqual(keys.decode("\x1b[999Z"), "")


def feeder(data: bytes):
    """A byte reader plus the "more waiting?" check, over a fixed buffer."""
    pending = list(data[i : i + 1] for i in range(len(data)))

    def read_byte():
        return pending.pop(0) if pending else b""

    def has_more(timeout):
        return bool(pending)

    return read_byte, has_more


class ReadKeyTests(unittest.TestCase):
    def test_reassembles_an_escape_sequence_arriving_byte_by_byte(self):
        self.assertEqual(keys.read_key(*feeder(b"\x1b[B")), "down")
        self.assertEqual(keys.read_key(*feeder(b"\x1b[6~")), "pgdn")

    def test_a_lone_escape_is_escape(self):
        self.assertEqual(keys.read_key(*feeder(b"\x1b")), "esc")

    def test_plain_key(self):
        self.assertEqual(keys.read_key(*feeder(b"q")), "q")

    def test_end_of_input_reads_as_ctrl_d(self):
        self.assertEqual(keys.read_key(*feeder(b"")), "ctrl-d")

    def test_unknown_escape_sequence_is_ignored_rather_than_quitting(self):
        self.assertEqual(keys.read_key(*feeder(b"\x1b[29Z")), "")

    def test_stops_at_the_first_complete_sequence(self):
        read_byte, has_more = feeder(b"\x1b[Bq")
        self.assertEqual(keys.read_key(read_byte, has_more), "down")
        self.assertEqual(keys.read_key(read_byte, has_more), "q")


if __name__ == "__main__":
    unittest.main()

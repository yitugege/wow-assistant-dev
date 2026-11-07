"""自动选怪原生包边界测试；不调用游戏或按键 API。"""

import unittest

from wowbuddy.auto_target import AutoTargetPacket, PACKET_BASE, parse_auto_target


def packet(key: int, state: int = 1, ack: int = 0, sequence: int = 1) -> int:
    return PACKET_BASE + key * 8192 + state * 1024 + ack * 32 + sequence


class AutoTargetTests(unittest.TestCase):
    def test_fixed_native_vectors(self):
        self.assertEqual(
            parse_auto_target(0xD02443), AutoTargetPacket(1, 1, 2, 3, "F6")
        )
        self.assertEqual(
            parse_auto_target(0xDA33FF), AutoTargetPacket(81, 4, 31, 31, "ALT-END")
        )

    def test_modifier_group_boundaries(self):
        expected = {1: "F6", 27: "END", 28: "CTRL-F6", 54: "CTRL-END",
                    55: "ALT-F6", 81: "ALT-END", 19: "\\"}
        for index, key in expected.items():
            with self.subTest(index=index):
                self.assertEqual(parse_auto_target(packet(index)).key, key)

    def test_native_index_limit_is_not_lua_limit(self):
        for index in (0, 82, 127, 128):
            with self.subTest(index=index):
                self.assertIsNone(parse_auto_target(packet(index)))
        self.assertIsNotNone(parse_auto_target(packet(81)))

    def test_state_zero_and_unknown_are_valid_packets(self):
        # 有效格式不等于发键许可；0 和 4 都必须保留。
        for state in range(5):
            with self.subTest(state=state):
                self.assertEqual(parse_auto_target(packet(1, state)).state, state)
        for state in (5, 6, 7):
            self.assertIsNone(parse_auto_target(packet(1, state)))

    def test_sequence_zero_invalid_ack_and_sequence_edges(self):
        for ack in (0, 1, 30, 31):
            self.assertIsNone(parse_auto_target(packet(1, ack=ack, sequence=0)))
            for seq in (1, 31):
                decoded = parse_auto_target(packet(1, ack=ack, sequence=seq))
                self.assertEqual((decoded.ack, decoded.sequence), (ack, seq))

    def test_fractional_input_matches_native_truncation(self):
        raw = packet(28, 2, 7, 19)
        self.assertEqual(parse_auto_target(raw + 0.75), parse_auto_target(raw))
        self.assertIsNone(parse_auto_target(PACKET_BASE - 0.1))

    def test_malformed_and_out_of_range(self):
        for value in (None, "13631489", True, False, [], {}, float("nan"),
                      float("inf"), -float("inf"), -1, 0, PACKET_BASE - 1,
                      PACKET_BASE, 1e100, 2**128):
            with self.subTest(value=repr(value)):
                self.assertIsNone(parse_auto_target(value))


if __name__ == "__main__":
    unittest.main()

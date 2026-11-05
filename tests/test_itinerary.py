import unittest
from datetime import datetime

from travelphotos.itinerary import parse_itinerary, parse_line_chat, summarize_chat


class ItineraryTests(unittest.TestCase):
    def test_days_and_arrows(self):
        stops = parse_itinerary(
            "第一天：桃園機場 → 新千歲機場 → 小樽運河\n"
            "\n"
            "Day 2\n"
            "- 富良野\n"
            "- 美瑛、青池\n"
            "第3天\n"
            "1. 札幌 -> 機場\n"
        )
        self.assertEqual(
            [(s.index, s.day, s.name) for s in stops],
            [
                (1, 1, "桃園機場"),
                (2, 1, "新千歲機場"),
                (3, 1, "小樽運河"),
                (4, 2, "富良野"),
                (5, 2, "美瑛"),
                (6, 2, "青池"),
                (7, 3, "札幌"),
                (8, 3, "機場"),
            ],
        )

    def test_date_headers_count_days(self):
        stops = parse_itinerary("10/15（日）\n故宮\n10/16\n九份")
        self.assertEqual([(s.day, s.name) for s in stops], [(1, "故宮"), (2, "九份")])

    def test_empty(self):
        self.assertEqual(parse_itinerary(""), [])


class LineChatTests(unittest.TestCase):
    CHAT = (
        "[LINE] 北海道團的聊天記錄\n"
        "儲存日期：2024/05/10 21:00\n"
        "\n"
        "2024/05/01（三）\n"
        "上午09:15\t王導遊\t[照片]\n"
        "上午09:16\t王導遊\t大家早安\n"
        "下午01:05\t小美\t[影片]\n"
        "2024/05/02（四）\n"
        "12:30 AM\tBob\t[Photo]\n"
        "08:00\t小美\t[相簿] 第二天\n"
    )

    def test_media_messages(self):
        msgs = parse_line_chat(self.CHAT)
        self.assertEqual(
            [(m.time, m.kind) for m in msgs],
            [
                (datetime(2024, 5, 1, 9, 15), "photo"),
                (datetime(2024, 5, 1, 13, 5), "video"),
                (datetime(2024, 5, 2, 0, 30), "photo"),
                (datetime(2024, 5, 2, 8, 0), "album"),
            ],
        )
        self.assertEqual(msgs[0].sender, "王導遊")

    def test_summary(self):
        summary = summarize_chat(parse_line_chat(self.CHAT))
        self.assertEqual(summary[0]["date"], "2024-05-01")
        self.assertEqual(summary[0]["count"], 2)
        self.assertEqual((summary[0]["first"], summary[0]["last"]), ("09:15", "13:05"))
        self.assertEqual(summary[1]["albums"], 1)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

import numpy as np

from app import ocr, settings


class UnreadPatrolTests(unittest.TestCase):
    def test_unread_badge_rows_only_uses_right_strip(self):
        img = np.zeros((140, 220, 3), dtype=np.uint8)
        # 真正的未读红点：靠会话列表右侧。
        img[50:60, 190:200] = [240, 70, 70]
        # 红色头像/图标：靠左，不能算未读。
        img[85:105, 15:35] = [245, 60, 60]
        rows = ocr.unread_badge_rows(img)
        self.assertEqual(len(rows), 1)
        self.assertTrue(50 <= rows[0] <= 59)

    def test_read_unread_chats_maps_badge_to_nearby_title(self):
        full = np.zeros((180, 260, 3), dtype=np.uint8)
        panel_x0 = 200
        y_start = 20
        # sidebar 相对 y=60，绝对 y=80
        full[76:86, 185:195] = [240, 70, 70]

        fake_result = [[
            [[70, 45], [120, 45], [120, 62], [70, 62]],
            "张三",
            0.99,
        ]]
        with patch("app.ocr._engine", return_value=lambda *a, **k: (fake_result, None)):
            items = ocr.read_unread_chats(full, panel_x0, y_start)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][0], "张三")
        self.assertTrue(76 <= items[0][2] <= 85)

    def test_auto_send_whitelist_is_exact_match(self):
        values = {
            "auto_send": True,
            "auto_send_whitelist": ["张三", "测试群"],
        }
        with patch("app.settings._read", side_effect=lambda name, default=None: values.get(name, default)):
            self.assertTrue(settings.auto_send_allowed("张三"))
            self.assertTrue(settings.auto_send_allowed("测试群"))
            self.assertFalse(settings.auto_send_allowed("张三的群"))
            self.assertFalse(settings.auto_send_allowed("测试"))


if __name__ == "__main__":
    unittest.main()

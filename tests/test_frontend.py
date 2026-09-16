"""前端脚本的静态检查，以及页面里引用的资源是否都存在。

这些脚本在 file:// 或本机服务下直接运行，没有构建步骤；
一个语法错误会让整页失效，所以用 node --check 做最小但必要的一道闸。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "需要 Node 做语法检查")
class ScriptSyntaxTest(unittest.TestCase):
    def test_webapp_scripts_parse(self):
        for path in sorted((ROOT / "webapp").glob("*.js")):
            result = subprocess.run([NODE, "--check", str(path)], capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0,
                             f"{path.name} 语法错误：{result.stderr.decode('utf-8', 'replace')[:400]}")

    def test_asset_scripts_parse(self):
        for path in sorted((ROOT / "assets").glob("*.js")):
            result = subprocess.run([NODE, "--check", str(path)], capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0,
                             f"{path.name} 语法错误：{result.stderr.decode('utf-8', 'replace')[:400]}")


class PageReferenceTest(unittest.TestCase):
    """页面里引用的本地文件必须真实存在，避免打开后白屏。"""

    def _references(self, html: str) -> list[str]:
        found = re.findall(r'(?:src|href)="([^"#?]+)"', html)
        return [value for value in found
                if not value.startswith(("http", "mailto:", "data:", "#", "javascript:"))]

    def test_generated_pages_have_assets(self):
        output = ROOT / "output"
        if not (output / "index.html").exists():
            self.skipTest("尚未生成页面")
        for name in ("index.html", "全部生词_完整版.html", "复现词汇.html", "背词练习.html"):
            page = output / name
            html = page.read_text(encoding="utf-8")
            for reference in self._references(html):
                target = (page.parent / reference).resolve()
                self.assertTrue(target.exists(), f"{name} 引用了不存在的文件：{reference}")

    def test_webapp_pages_have_assets(self):
        webapp = ROOT / "webapp"
        for page in sorted(webapp.glob("*.html")):
            html = page.read_text(encoding="utf-8")
            for reference in self._references(html):
                target = (page.parent / reference).resolve()
                self.assertTrue(target.exists(), f"{page.name} 引用了不存在的文件：{reference}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

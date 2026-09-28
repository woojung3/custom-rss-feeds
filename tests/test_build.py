import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import build

NOW = '2026-09-28T12:00:00+00:00'
URL = 'https://gall.dcinside.com/board/lists/?id=comic_new6&exception_mode=recommend'
ROW = '''<table><tr class="ub-content us-post" data-no="12" data-type="icon_txt">
<td class="gall_subject">general</td><td class="gall_tit"><a href="/board/view/?id=comic_new6&no=12&page=1">A &amp; B</a><a class="reply_numbox">[42]</a></td>
<td class="gall_date" title="2026-09-28 16:00:00">16:00</td></tr></table>'''
ITEM = {'id': 'https://example.com/1', 'link': 'https://example.com/1', 'title': 'A & B', 'summary': '<script>bad</script>', 'date': NOW}


class Tests(unittest.TestCase):
    def test_dc_title_date_canonical_link(self):
        item = build.parse_dc(ROW, URL)[0]
        self.assertEqual(item['title'], 'A & B')
        self.assertEqual(item['date'], '2026-09-28T07:00:00+00:00')
        self.assertEqual(item['link'], 'https://gall.dcinside.com/board/view/?id=comic_new6&no=12')

    def test_empty_blocked_and_notices_fail(self):
        for data in ('', '<html>Access denied</html>', ROW.replace('icon_txt', 'icon_notice')):
            with self.assertRaises(ValueError):
                build.parse_dc(data, URL)

    def test_wrong_board_fails(self):
        with self.assertRaises(ValueError):
            build.parse_dc(ROW.replace('id=comic_new6', 'id=other'), URL)

    def test_rss_validation(self):
        with self.assertRaises(ValueError):
            build.parse_rss(b'<rss><channel/></rss>')
        with self.assertRaises(ValueError):
            build.parse_rss(b'<rss><channel><item><title>x</title><link>javascript:bad</link></item></channel></rss>')
        items = build.parse_rss(b'<rss><channel><item><title>x</title><link>https://example.com/</link></item></channel></rss>')
        self.assertEqual(len(items), 1)

    def test_merge_stable_date_and_no_duplicates(self):
        undated = dict(ITEM, date=None)
        self.assertEqual(build.merge([ITEM], [undated], '2026-09-29T12:00:00+00:00'), [ITEM])

    def test_feed_emoji_and_stable_guid(self):
        source = json.loads(Path('sources.json').read_text())[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'feed.xml'
            build.write_feed(path, source, [ITEM], NOW, 'https://example.com')
            item = ET.parse(path).find('./channel/item')
            self.assertEqual(item.findtext('title'), source['emoji'] + ' A & B')
            self.assertEqual(item.findtext('guid'), ITEM['id'])
            self.assertNotIn('<script>', item.findtext('description'))

    def test_recommend_filters(self):
        sources = json.loads(Path('sources.json').read_text())
        for source in sources:
            if source['kind'] == 'dc' and source['id'] != 'dcbest':
                self.assertIn('exception_mode=recommend', source['url'])

    def test_pagination_keeps_filter_and_stops_at_known(self):
        source = {'kind': 'dc', 'url': URL}
        with patch('build.fetch', return_value=ROW) as fetch:
            items, warning = build.collect(source, build.parse_dc(ROW, URL))
        self.assertEqual(len(items), 1)
        self.assertIsNone(warning)
        self.assertIn('exception_mode=recommend', fetch.call_args.args[0])

    def test_failure_preserves_feed_and_other_sources_publish(self):
        sources = json.loads(Path('sources.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with patch('build.collect', return_value=([ITEM], None)):
                self.assertFalse(build.build(output, 'https://example.com'))
            original = (output / 'feeds/dcbest.xml').read_bytes()
            old_state = json.loads((output / 'state.json').read_text())
            def collect(source, previous):
                if source['id'] == 'dcbest':
                    raise ValueError('Blocked')
                return [dict(ITEM, title='Updated')], None
            with patch('build.collect', side_effect=collect):
                self.assertTrue(build.build(output, 'https://example.com'))
            self.assertEqual((output / 'feeds/dcbest.xml').read_bytes(), original)
            state = json.loads((output / 'state.json').read_text())
            self.assertEqual(state['dcbest']['last_success'], old_state['dcbest']['last_success'])
            self.assertIn('Blocked', state['dcbest']['error'])
            self.assertEqual(state[sources[1]['id']]['items'][0]['title'], 'Updated')
            self.assertEqual(len(ET.parse(output / 'subscriptions.opml').findall('./body/outline')), 7)


if __name__ == '__main__':
    unittest.main()

import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('opus_content', Path(__file__).resolve().parents[1]/'nonebot_plugin_mortis_analysis/opus.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OpusContentTests(unittest.TestCase):
    def test_null_modules_and_text_only_dynamic(self):
        data = {'item': {'basic': {'title':'动态标题'}, 'modules': [
            {'module_content':None}, None, {'module_content': {'paragraphs': [
                {'text': {'nodes':[{'word':{'words':'第一段'}}, {'word':None,'rich':{'text':'表情'}}]}, 'pic':None},
                {'text': {'nodes':[{'word':{'words':'第二段'}}]}, 'pic':None},
            ]}}]}}
        self.assertEqual(MODULE.parse_opus_content(data), ('动态标题','第一段表情\n第二段',[]))

    def test_image_only_and_mixed_paragraph_order(self):
        data = {'item': {'basic':None, 'modules':[{'module_content':{'paragraphs':[
            {'text':None, 'pic':{'pics':[{'url':'//i0.hdslb.com/one.jpg'}, {'url':'https://i0.hdslb.com/one.jpg'}, {'url':'javascript:invalid'}]}},
            None, {'text':{'nodes':[None, {'word':None,'rich':None}]}},
            {'text':None, 'pic':{'pics':['https://i0.hdslb.com/two.jpg']}},
        ]}}]}}
        self.assertEqual(MODULE.parse_opus_content(data), ('哔哩哔哩动态','',[
            'https://i0.hdslb.com/one.jpg','https://i0.hdslb.com/two.jpg']))

    def test_empty_and_invalid_response(self):
        self.assertEqual(MODULE.parse_opus_content({'item':{'modules':None}}), ('哔哩哔哩动态','',[]))
        for data in (None,{}, {'item':None}):
            with self.assertRaises(ValueError):
                MODULE.parse_opus_content(data)


if __name__ == '__main__':
    unittest.main()

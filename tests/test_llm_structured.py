"""Structured generation never repairs or accepts incomplete model responses."""
import unittest
from unittest.mock import Mock, patch

from navigator import llm


SCHEMA = {'type':'object','properties':{'ok':{'type':'boolean'}},
          'required':['ok'],'additionalProperties':False}


class StructuredModelTests(unittest.TestCase):
    def response(self, content='{"ok":true}', finish='stop'):
        reply=Mock()
        reply.json.return_value={'choices':[{'message':{'content':content},'finish_reason':finish}]}
        return reply

    def test_schema_reaches_endpoint_and_finished_reply_is_parsed(self):
        with patch.object(llm.config,'LLM_ENABLED',True), patch.object(llm.config,'LLM_BASE_URL','https://example.test/v1'), \
             patch('navigator.llm.httpx.post',return_value=self.response()) as post:
            self.assertEqual(llm.chat_json('system','payload',json_schema=SCHEMA,model='report-model'),{'ok':True})
        request=post.call_args.kwargs['json']
        self.assertEqual(request['response_format']['json_schema']['schema'],SCHEMA)
        self.assertTrue(request['response_format']['json_schema']['strict'])
        self.assertEqual(request['model'],'report-model')

    def test_even_parseable_truncated_output_is_rejected(self):
        with patch.object(llm.config,'LLM_ENABLED',True), patch.object(llm.config,'LLM_BASE_URL','https://example.test/v1'), \
             patch('navigator.llm.httpx.post',return_value=self.response(finish='length')):
            with self.assertRaises(llm.InvalidModelResponse):
                llm.chat_json('system','payload',json_schema=SCHEMA)

    def test_structured_json_never_salvages_or_rewrites_malformed_content(self):
        for raw in ('{"ok":true}}','{"ok":true}{"ok":false}',
                    '{"ok":true,"ok":false}','{"ok":NaN}','[{"ok":true}]',
                    '<think>ignore</think>{"ok":true}','{"ok":'):
            with self.subTest(raw=raw),patch('navigator.llm.chat',return_value=raw),self.assertRaises(llm.InvalidModelResponse):
                llm.chat_json('system','payload',json_schema=SCHEMA)

    def test_legacy_calls_keep_their_request_contract(self):
        with patch.object(llm.config,'LLM_ENABLED',True), patch.object(llm.config,'LLM_BASE_URL','https://example.test/v1'), \
             patch('navigator.llm.httpx.post',return_value=self.response('```json\n{"ok":true}\n```')) as post:
            self.assertEqual(llm.chat_json('system','payload'),{'ok':True})
        self.assertNotIn('response_format',post.call_args.kwargs['json'])


if __name__=='__main__': unittest.main()

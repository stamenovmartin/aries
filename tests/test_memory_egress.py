"""Synthetic memory inference transport tests; never call a real model."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
import threading
import unittest
from unittest.mock import patch
import urllib.error

from tests._bootstrap import bootstrap
bootstrap('aries-memory-egress')
from aries.workspace.memory import embedding,calibration,extraction,local_transport


@contextmanager
def server(redirect=None):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):self.respond()
        def do_POST(self):self.respond()
        def respond(self):
            body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            calls.append({'path':self.path,'body':body.decode()})
            if redirect:
                code,url=redirect
                self.send_response(code);self.send_header('Location',url);self.end_headers()
                return
            payload=json.dumps({'models':[{'name':'bge-m3'}],'embeddings':[[1,0]],
                'logprobs':[{'token':'APPEND','logprob':0,'top_logprobs':[]}]}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(payload)))
            self.end_headers();self.wfile.write(payload)
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=http.serve_forever,kwargs={'poll_interval':.01},daemon=True)
    thread.start()
    try:yield f'http://127.0.0.1:{http.server_port}',calls
    finally:http.shutdown();http.server_close();thread.join()


class MemoryEgressTests(unittest.TestCase):
    def test_remote_and_ambiguous_addresses_fail_before_transport(self):
        urls=['http://nonlocal.invalid','http://192.168.1.1:11434','http://localhost:11434',
              'https://127.0.0.1','file:///tmp/model','http://127.0.0.1@nonlocal.invalid',
              'http://user:password@127.0.0.1','http://127.0.0.1?host=remote',
              'http://127.0.0.1#remote','http://2130706433','http://[2001:db8::1]']
        with patch.object(local_transport.urllib.request,'build_opener') as transport:
            for url in urls:
                with self.subTest(url=url):
                    with self.assertRaises(embedding.EmbedderUnavailable):
                        embedding.OllamaEmbedder(endpoint=url)
                    with self.assertRaises(calibration.ModelUnavailable):
                        extraction.Cascade(endpoint=url).decide('synthetic canary',[])
            transport.assert_not_called()

    def test_actual_loopback_calls_ignore_proxy_environment(self):
        with server() as (proxy,proxy_calls),server() as (endpoint,calls):
            with patch.dict(os.environ,{'http_proxy':proxy,'HTTP_PROXY':proxy,
                'https_proxy':proxy,'HTTPS_PROXY':proxy,'all_proxy':proxy,'ALL_PROXY':proxy,
                'no_proxy':'','NO_PROXY':''}):
                model=embedding.OllamaEmbedder(endpoint=endpoint+'/')
                vector=model.encode(['synthetic memory canary'],kind='passage')
                verdict,_=extraction.Cascade(endpoint=endpoint+'/').decide('synthetic preference',[])
            self.assertEqual(vector.tolist(),[[1.,0.]])
            self.assertEqual(verdict.action,'APPEND')
            self.assertEqual([c['path'] for c in calls],['/api/tags','/api/embed','/api/generate'])
            self.assertIn('synthetic memory canary',calls[1]['body'])
            self.assertEqual(proxy_calls,[])

    def test_redirects_never_reach_second_server(self):
        with server() as (destination,leaks):
            for code in [301,302,303,307,308]:
                with self.subTest(code=code),server((code,destination+'/sink')) as (endpoint,calls):
                    with self.assertRaises(embedding.EmbedderUnavailable):
                        embedding.OllamaEmbedder(endpoint=endpoint)
                    with self.assertRaises(calibration.ModelUnavailable):
                        calibration.classify('synthetic canary',['APPEND'],endpoint=endpoint,model='fixture')
                    self.assertEqual(len(calls),2)
            self.assertEqual(leaks,[])

    def test_embedding_post_redirect_and_endpoint_mutation_blocked(self):
        with server() as (endpoint,_):model=embedding.OllamaEmbedder(endpoint=endpoint)
        with server() as (destination,leaks),server((302,destination+'/sink')) as (redirect,calls):
            model._endpoint=redirect
            with self.assertRaises(embedding.EmbedderUnavailable):model.encode(['synthetic canary'],kind='query')
            self.assertEqual(len(calls),1)
            self.assertEqual(leaks,[])
        model._endpoint='http://nonlocal.invalid'
        with patch.object(local_transport.urllib.request,'build_opener') as transport:
            with self.assertRaises(embedding.EmbedderUnavailable):model.encode(['synthetic canary'],kind='query')
            transport.assert_not_called()

    def test_cascade_retains_explicit_local_model_fallback(self):
        cascade=extraction.Cascade(endpoint='http://nonlocal.invalid')
        with patch.object(local_transport.urllib.request,'build_opener') as transport:
            verdict=cascade.run('My favorite color is green.',[('fixture',.9,'My favorite color is blue.')],lang='en')
            transport.assert_not_called()
        self.assertEqual(verdict.stage,'novelty')
        self.assertIn('no local model',verdict.reason)


if __name__=='__main__':unittest.main()

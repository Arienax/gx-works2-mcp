"""Exercise the real error panel and download; ONLY the model output is fixed."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from web_generation_e2e import Server, Provider, open_page, REQUIREMENT
from model_provider import TextDelta
from playwright.async_api import async_playwright, expect

class BrokenProvider(Provider):
    def stream(self, request):
        self.calls += 1
        yield TextDelta('{"rungs": [PRIVATE_BROKEN_RESPONSE')

async def run(web_dist, report):
    records=[]
    with tempfile.TemporaryDirectory(prefix='gx-diagnostic-ui-') as tmp:
        os.environ['GX_DELIVERY_EVIDENCE_DIR']=str(report.parent)
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch()
            try:
                for policy in ('legacy','adaptive'):
                    os.environ['GXWORKS_CONTEXT_POLICY']=policy
                    provider=BrokenProvider()
                    with Server(Path(tmp)/policy,web_dist,provider) as server:
                        pid=server.project('Diagnostic '+policy)
                        server.service.store.set_confirmed_spec(pid,{'summary':REQUIREMENT,'io_table':[],'parameters':[]})
                        context,page,errors=await open_page(browser,server,pid)
                        try:
                            await page.get_by_role('button',name='按已确认规格生成程序',exact=True).click()
                            link=page.get_by_role('link',name='下载错误诊断日志',exact=True)
                            await expect(link).to_be_visible(timeout=30000)
                            async with page.expect_download() as event:
                                await link.click()
                            download=await event.value
                            target=Path(tmp)/(policy+'-diagnostics.zip')
                            await download.save_as(str(target))
                            with zipfile.ZipFile(target) as archive:
                                summary=json.loads(archive.read('summary.json'))
                                data=archive.read('diagnostics.jsonl').decode()
                                assert summary['capture_status']=='captured'
                                assert 'response_rejected' in data and 'workflow_exception' in data
                                assert 'PRIVATE_BROKEN_RESPONSE' not in data
                            assert provider.calls==1
                            assert server.service.projects.project(pid)['version_count']==0
                            assert not errors,errors
                            await page.screenshot(path=str(report.parent/('diagnostics-'+policy+'.png')),full_page=True)
                            records.append({'policy':policy,'error_panel':True,'downloaded_zip':True,
                                'metadata_only':True,'no_additional_model_call':True,'no_accepted_version':True})
                        finally:
                            await context.close()
            finally:
                await browser.close()
    report.write_text(json.dumps({'ok':True,'cases':records,'model_transport':'fixed_invalid_reply',
        'live_model_called':False,'native_gx_called':False},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--web-dist',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    asyncio.run(run(args.web_dist.resolve(),args.report.resolve()))

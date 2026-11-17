import hashlib
from bugfix_contracts.defect_batch import RawDefect
from bugfix_agent1.defect_batch.source_quality import build_source_document, assess_input_quality

def test_original_unicode_and_business_fields():
    raw = RawDefect(defectId='D', title='界面', description='前置条件：中文\n测试数据：90°\n问题：https://example.test/replay', metadata={'测试环境':'Windows','当前处理人':'secret'})
    source = build_source_document(raw)
    assert source.description == raw.description
    assert source.sha256 == hashlib.sha256(raw.description.encode()).hexdigest()
    assert source.fields == {'测试环境':'Windows'}
    for section in source.sections:
        assert source.description[section.start:section.end] == section.text

def test_missing_expectation_is_uncertain():
    quality = assess_input_quality(build_source_document(RawDefect(defectId='D',title='T')), 'broken', '')
    assert quality.expectedOrigin == 'absent'
    assert quality.expectedRelevance == 'uncertain'


def test_csv_business_columns_and_original_whitespace_survive_pipeline(tmp_path):
    import csv
    from bugfix_agent1.defect_batch.run import run_defect_batch_prepare
    source=tmp_path/'input.csv'
    original='  前置条件：在线\n实际结果：没有错误提示\n预期结果：显示错误原因  '
    with source.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['defectId','title','describle','DESCRIPTION','测试环境','产品型号'])
        writer.writeheader()
        writer.writerow({'defectId':'D','title':'保存失败但没有错误提示','describle':'',
                         'DESCRIPTION':original,'测试环境':'  Windows  ','产品型号':'M'})
    batch=run_defect_batch_prepare(product_line='p',posture='alpha',source=source)
    doc=batch.tickets[0].sourceDocument
    assert doc.description==original
    assert doc.fields['测试环境']=='  Windows  ' and doc.fields['产品型号']=='M'
    assert doc.sha256==hashlib.sha256(original.encode('utf-8')).hexdigest()

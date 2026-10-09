import csv

from core.batch_pipeline import inspect_table, stream_coordinate_conversion


def test_stream_coordinate_conversion(tmp_path):
    source = tmp_path / 'input.csv'
    target = tmp_path / 'output.csv'
    with open(source, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['点位名称', '源经度', '源纬度'])
        for index in range(10_000):
            writer.writerow([f'P{index}', 108.3 + index / 10_000_000, 22.8])
    info = inspect_table(source)
    assert info['count'] == 10_000
    result = stream_coordinate_conversion(source, target, 'WGS84', 'GCJ-02')
    assert result['success'] == 10_000
    assert len(result['preview']) == 500
    assert inspect_table(target)['count'] == 10_000

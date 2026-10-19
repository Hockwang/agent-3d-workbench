from .conftest import write_box_stl


def test_oversized_part_has_structured_dimensions_in_response_and_state(studio_env, tmp_path):
    client = studio_env['client']
    mesh = write_box_stl(tmp_path, 'large_shell', (300, 150, 300))
    status, _ = client.post('/api/load', {'files': [str(mesh)]})
    assert status == 200
    status, _ = client.post('/api/orient', {'strategy': 'upright'})
    assert status == 200
    status, response = client.post('/api/arrange', {'mode': 'auto'})
    assert status == 400
    assert response['error']['code'] == 'part_too_large'
    assert response['part'] == 'large_shell'
    assert sorted(response['dims_mm']) == [150, 300, 300]
    assert response['available_mm'] == [246, 246, 245]
    _, state = client.get('/api/state')
    assert state['last_error']['payload']['part'] == 'large_shell'
    assert state['last_error']['payload']['available_mm'] == [246, 246, 245]

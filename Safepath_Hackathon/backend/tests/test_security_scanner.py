from scripts import security_and_redaction_check as scanner


def test_manifest_path_is_configuration_and_suspected_secret_is_redacted(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scanner, "ROOT_DIR", tmp_path)
    example = tmp_path / '.env.example'
    example.write_text('OSRM_GRAPH_MANIFEST_PATH=data/osrm/graph-manifest.json\nAUTH_SECRET=\n')
    assert scanner.check_env_example()
    secret = 'unapproved_credential_0123456789012345'
    example.write_text('AUTH_SECRET=' + secret + '\n')
    assert not scanner.check_env_example()
    output = capsys.readouterr().out
    assert secret not in output
    assert 'AUTH_SECRET' in output

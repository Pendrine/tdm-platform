def test_smoke_import():
    import tdm_platform.app_meta as app_meta
    assert app_meta.APP_VERSION

import py
import pickle

def setglobals(request):
    oldconfig = py.test.config 
    print("setting py.test.config to None")
    py.test.config = None
    def resetglobals():
        py.builtin.print_("setting py.test.config to", oldconfig)
        py.test.config = oldconfig
    request.addfinalizer(resetglobals)

def pytest_funcarg__testdir(request):
    setglobals(request)
    return request.getfuncargvalue("testdir")

class ImmutablePickleTransport:
    def __init__(self, request):
        from xdist.mypickle import ImmutablePickler
        self.p1 = ImmutablePickler(uneven=0)
        self.p2 = ImmutablePickler(uneven=1)
        setglobals(request)

    def p1_to_p2(self, obj):
        return self.p2.loads(self.p1.dumps(obj))

    def p2_to_p1(self, obj):
        return self.p1.loads(self.p2.dumps(obj))

    def unifyconfig(self, config):
        p2config = self.p1_to_p2(config)
        p2config._initafterpickle(config.topdir)
        return p2config

pytest_funcarg__pickletransport = ImmutablePickleTransport

class TestImmutablePickling:
    def test_pickle_config(self, testdir, pickletransport):
        config1 = testdir.parseconfig()
        assert config1.topdir == testdir.tmpdir
        testdir.chdir()
        p2config = pickletransport.p1_to_p2(config1)
        assert p2config.topdir.realpath() == config1.topdir.realpath()
        config_back = pickletransport.p2_to_p1(p2config)
        assert config_back is config1

    def test_pickle_modcol(self, testdir, pickletransport):
        modcol1 = testdir.getmodulecol("def test_one(): pass")
        modcol2a = pickletransport.p1_to_p2(modcol1)
        modcol2b = pickletransport.p1_to_p2(modcol1)
        assert modcol2a is modcol2b

        modcol1_back = pickletransport.p2_to_p1(modcol2a)
        assert modcol1_back

    def test_pickle_func(self, testdir, pickletransport):
        modcol1 = testdir.getmodulecol("def test_one(): pass")
        item = modcol1.collect_by_name("test_one")
        testdir.chdir()
        item2a = pickletransport.p1_to_p2(item)
        assert item is not item2a # of course
        assert item2a.name == item.name
        modback = pickletransport.p2_to_p1(item2a.parent)
        assert modback is modcol1


class TestConfigPickling:
    def test_config_getstate_setstate(self, testdir):
        from py.impl.test.config import Config
        testdir.makepyfile(__init__="", conftest="x=1; y=2")
        hello = testdir.makepyfile(hello="")
        tmp = testdir.tmpdir
        testdir.chdir()
        config1 = testdir.parseconfig(hello)
        config2 = Config()
        config2.__setstate__(config1.__getstate__())
        assert config2.topdir == py.path.local()
        config2_relpaths = [py.path.local(x).relto(config2.topdir) 
                                for x in config2.args]
        config1_relpaths = [py.path.local(x).relto(config1.topdir) 
                                for x in config1.args]

        assert config2_relpaths == config1_relpaths
        for name, value in config1.option.__dict__.items():
            assert getattr(config2.option, name) == value
        assert config2.getvalue("x") == 1

    def test_config_pickling_customoption(self, testdir):
        testdir.makeconftest("""
            def pytest_addoption(parser):
                group = parser.getgroup("testing group")
                group.addoption('-G', '--glong', action="store", default=42, 
                    type="int", dest="gdest", help="g value.")
        """)
        config = testdir.parseconfig("-G", "11")
        assert config.option.gdest == 11
        repr = config.__getstate__()

        config = testdir.Config()
        py.test.raises(AttributeError, "config.option.gdest")

        config2 = testdir.Config()
        config2.__setstate__(repr) 
        assert config2.option.gdest == 11

    def test_config_pickling_and_conftest_deprecated(self, testdir):
        tmp = testdir.tmpdir.ensure("w1", "w2", dir=1)
        tmp.ensure("__init__.py")
        tmp.join("conftest.py").write(py.code.Source("""
            def pytest_addoption(parser):
                group = parser.getgroup("testing group")
                group.addoption('-G', '--glong', action="store", default=42, 
                    type="int", dest="gdest", help="g value.")
        """))
        config = testdir.parseconfig(tmp, "-G", "11")
        assert config.option.gdest == 11
        repr = config.__getstate__()

        config = testdir.Config()
        py.test.raises(AttributeError, "config.option.gdest")

        config2 = testdir.Config()
        config2.__setstate__(repr) 
        assert config2.option.gdest == 11
       
        option = config2.addoptions("testing group", 
                config2.Option('-G', '--glong', action="store", default=42,
                       type="int", dest="gdest", help="g value."))
        assert option.gdest == 11

    def test_config_picklability(self, testdir):
        config = testdir.parseconfig()
        s = pickle.dumps(config)
        newconfig = pickle.loads(s)
        assert hasattr(newconfig, "topdir")
        assert newconfig.topdir == py.path.local()

    def test_collector_implicit_config_pickling(self, testdir):
        tmpdir = testdir.tmpdir
        testdir.chdir()
        testdir.makepyfile(hello="def test_x(): pass")
        config = testdir.parseconfig(tmpdir)
        col = config.getnode(config.topdir)
        io = py.io.BytesIO()
        pickler = pickle.Pickler(io)
        pickler.dump(col)
        io.seek(0) 
        unpickler = pickle.Unpickler(io)
        col2 = unpickler.load()
        assert col2.name == col.name 
        assert col2.listnames() == col.listnames()

    def test_config_and_collector_pickling(self, testdir):
        tmpdir = testdir.tmpdir
        dir1 = tmpdir.ensure("somedir", dir=1)
        config = testdir.parseconfig()
        col = config.getnode(config.topdir)
        col1 = col.join(dir1.basename)
        assert col1.parent is col 
        io = py.io.BytesIO()
        pickler = pickle.Pickler(io)
        pickler.dump(col)
        pickler.dump(col1)
        pickler.dump(col)
        io.seek(0) 
        unpickler = pickle.Unpickler(io)
        topdir = tmpdir.ensure("newtopdir", dir=1)
        topdir.ensure("somedir", dir=1)
        old = topdir.chdir()
        try:
            newcol = unpickler.load()
            newcol2 = unpickler.load()
            newcol3 = unpickler.load()
            assert newcol2.config is newcol.config
            assert newcol2.parent == newcol 
            assert newcol2.config.topdir.realpath() == topdir.realpath()
            assert newcol.fspath.realpath() == topdir.realpath()
            assert newcol2.fspath.basename == dir1.basename
            assert newcol2.fspath.relto(newcol2.config.topdir)
        finally:
            old.chdir() 

def test_config__setstate__wired_correctly_in_childprocess(testdir):
    execnet = py.test.importorskip("execnet")
    from xdist.mypickle import PickleChannel
    gw = execnet.makegateway()
    channel = gw.remote_exec("""
        import py
        from xdist.mypickle import PickleChannel
        channel = PickleChannel(channel)
        config = channel.receive()
        assert py.test.config == config 
    """)
    channel = PickleChannel(channel)
    config = testdir.parseconfig()
    channel.send(config)
    channel.waitclose() # this will potentially raise 
    gw.exit()

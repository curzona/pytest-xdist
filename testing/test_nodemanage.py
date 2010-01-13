import py
from xdist.nodemanage import NodeManager

class pytest_funcarg__mysetup:
    def __init__(self, request):
        basetemp = request.config.mktemp(
            "mysetup-%s" % request.function.__name__, 
            numbered=True)
        self.source = basetemp.mkdir("source")
        self.dest = basetemp.mkdir("dest")
        request.getfuncargvalue("_pytest")

class TestNodeManager:
    @py.test.mark.xfail
    def test_rsync_roots_no_roots(self, testdir, mysetup):
        mysetup.source.ensure("dir1", "file1").write("hello")
        config = testdir.reparseconfig([source])
        nodemanager = NodeManager(config, ["popen//chdir=%s" % mysetup.dest])
        assert nodemanager.config.topdir == source == config.topdir
        nodemanager.rsync_roots()
        p, = nodemanager.gwmanager.multi_exec("import os ; channel.send(os.getcwd())").receive_each()
        p = py.path.local(p)
        py.builtin.print_("remote curdir", p)
        assert p == mysetup.dest.join(config.topdir.basename)
        assert p.join("dir1").check()
        assert p.join("dir1", "file1").check()

    def test_popen_nodes_are_ready(self, testdir):
        nodemanager = NodeManager(testdir.parseconfig(
            "--tx", "3*popen"))
        
        nodemanager.setup_nodes([].append)
        nodemanager.wait_nodesready(timeout=10.0)

    def test_popen_rsync_subdir(self, testdir, mysetup):
        source, dest = mysetup.source, mysetup.dest 
        dir1 = mysetup.source.mkdir("dir1")
        dir2 = dir1.mkdir("dir2")
        dir2.ensure("hello")
        for rsyncroot in (dir1, source):
            dest.remove()
            nodemanager = NodeManager(testdir.parseconfig(
                "--tx", "popen//chdir=%s" % dest,
                "--rsyncdir", rsyncroot,
                source, 
            ))
            assert nodemanager.config.topdir == source
            nodemanager.rsync_roots() 
            if rsyncroot == source:
                dest = dest.join("source")
            assert dest.join("dir1").check()
            assert dest.join("dir1", "dir2").check()
            assert dest.join("dir1", "dir2", 'hello').check()
            nodemanager.gwmanager.exit()

    def test_init_rsync_roots(self, testdir, mysetup):
        source, dest = mysetup.source, mysetup.dest
        dir2 = source.ensure("dir1", "dir2", dir=1)
        source.ensure("dir1", "somefile", dir=1)
        dir2.ensure("hello")
        source.ensure("bogusdir", "file")
        source.join("conftest.py").write(py.code.Source("""
            rsyncdirs = ['dir1/dir2']
        """))
        session = testdir.reparseconfig([source]).initsession()
        nodemanager = NodeManager(session.config, ["popen//chdir=%s" % dest])
        nodemanager.rsync_roots()
        assert dest.join("dir2").check()
        assert not dest.join("dir1").check()
        assert not dest.join("bogus").check()

    def test_rsyncignore(self, testdir, mysetup):
        source, dest = mysetup.source, mysetup.dest
        dir2 = source.ensure("dir1", "dir2", dir=1)
        dir5 = source.ensure("dir5", "dir6", "bogus")
        dirf = source.ensure("dir5", "file")
        dir2.ensure("hello")
        source.join("conftest.py").write(py.code.Source("""
            rsyncdirs = ['dir1', 'dir5']
            rsyncignore = ['dir1/dir2', 'dir5/dir6']
        """))
        session = testdir.reparseconfig([source]).initsession()
        nodemanager = NodeManager(session.config,
                         ["popen//chdir=%s" % dest])
        nodemanager.rsync_roots()
        assert dest.join("dir1").check()
        assert not dest.join("dir1", "dir2").check()
        assert dest.join("dir5","file").check()
        assert not dest.join("dir6").check()

    def test_optimise_popen(self, testdir, mysetup):
        source, dest = mysetup.source, mysetup.dest
        specs = ["popen"] * 3
        source.join("conftest.py").write("rsyncdirs = ['a']")
        source.ensure('a', dir=1)
        config = testdir.reparseconfig([source])
        nodemanager = NodeManager(config, specs)
        nodemanager.rsync_roots()
        for gwspec in nodemanager.gwmanager.specs:
            assert gwspec._samefilesystem()
            assert not gwspec.chdir

    def test_setup_DEBUG(self, mysetup, testdir):
        source = mysetup.source
        specs = ["popen"] * 2
        source.join("conftest.py").write("rsyncdirs = ['a']")
        source.ensure('a', dir=1)
        config = testdir.reparseconfig([source, '--debug'])
        assert config.option.debug
        nodemanager = NodeManager(config, specs)
        reprec = testdir.getreportrecorder(config).hookrecorder
        nodemanager.setup_nodes(putevent=[].append)
        for spec in nodemanager.gwmanager.specs:
            l = reprec.getcalls("pytest_trace")
            assert l 
        nodemanager.teardown_nodes()

    def test_ssh_setup_nodes(self, specssh, testdir):
        testdir.makepyfile(__init__="", test_x="""
            def test_one():
                pass
        """)
        reprec = testdir.inline_run("-d", "--rsyncdir=%s" % testdir.tmpdir, 
                "--tx", specssh, testdir.tmpdir)
        rep, = reprec.getreports("pytest_runtest_logreport")
        assert rep.passed 


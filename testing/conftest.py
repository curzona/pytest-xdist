import py
import execnet

pytest_plugins = "pytester"
option_report = 'skipped'
    
#rsyncdirs = ['.', '../xdist', py.path.local(execnet.__file__).dirpath()]

def pytest_addoption(parser):
    parser.addoption('--gx', 
       action="append", dest="gspecs", default=None,
       help=("add a global test environment, XSpec-syntax. "))

def pytest_funcarg__specssh(request):
    return getspecssh(request.config)
def getgspecs(config):
    return [execnet.XSpec(spec)
                for spec in config.getvalueorskip("gspecs")]

# configuration information for tests 
def getgspecs(config):
    return [execnet.XSpec(spec) 
                for spec in config.getvalueorskip("gspecs")]

def getspecssh(config):
    xspecs = getgspecs(config)
    for spec in xspecs:
        if spec.ssh:
            if not py.path.local.sysfind("ssh"):
                py.test.skip("command not found: ssh")
            return spec
    py.test.skip("need '--gx ssh=...'")

def getsocketspec(config):
    xspecs = getgspecs(config)
    for spec in xspecs:
        if spec.socket:
            return spec
    py.test.skip("need '--gx socket=...'")


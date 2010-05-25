import py
from py._test import session 
from xdist.nodemanage import NodeManager
queue = py.builtin._tryimport('queue', 'Queue')

debug_file = None # open('/tmp/loop.log', 'w')
def debug(*args):
    if debug_file is not None:
        s = " ".join(map(str, args))
        debug_file.write(s+"\n")
        debug_file.flush()

class LoopState(object):
    def __init__(self, dsession, colitems):
        self.dsession = dsession
        self.colitems = colitems
        self.exitstatus = None 
        # loopstate.dowork is False after reschedule events 
        # because otherwise we might very busily loop 
        # waiting for a host to become ready.  
        self.dowork = True
        self.shuttingdown = False
        self.testsfailed = 0

    def __repr__(self):
        return "<LoopState exitstatus=%r shuttingdown=%r len(colitems)=%d>" % (
            self.exitstatus, self.shuttingdown, len(self.colitems))

    def pytest_runtest_logreport(self, report):
        if report.item in self.dsession.item2nodes:
            if report.when != "teardown": # otherwise we already managed it
                self.dsession.removeitem(report.item, report.node)
        if report.failed:
            self.testsfailed += 1

    def pytest_collectreport(self, report):
        if report.passed:
            self.colitems.extend(report.result)

    def pytest_testnodeready(self, node):
        self.dsession.addnode(node)

    def pytest_testnodedown(self, node, error=None):
        pending = self.dsession.removenode(node)
        if pending:
            if error:
                crashitem = pending[0]
                debug("determined crashitem", crashitem)
                self.dsession.handle_crashitem(crashitem, node)
                # XXX recovery handling for "each"? 
                # currently pending items are not retried 
                if self.dsession.config.option.dist == "load":
                    self.colitems.extend(pending[1:])

    def pytest_rescheduleitems(self, items):
        self.colitems[:] = items + self.colitems
        for pending in self.dsession.node2pending.values():
            if pending:
                self.dowork = False # avoid busywait, nodes still have work

class DSession(session.Session):
    """ 
        Session drives the collection and running of tests
        and generates test events for reporters. 
    """ 
    LOAD_THRESHOLD_NEWITEMS = 5
    ITEM_CHUNKSIZE = 10

    def __init__(self, config):
        self.queue = queue.Queue()
        self.node2pending = {}
        self.item2nodes = {}
        super(DSession, self).__init__(config=config)
        try:
            self.terminal = config.pluginmanager.getplugin("terminalreporter")
        except KeyError:
            self.terminal = None
        self._nodesready = py.std.threading.Event()

    def report_line(self, line):
        if self.terminal:
            self.terminal.write_line(line)

    def pytest_gwmanage_rsyncstart(self, source, gateways):
        targets = ",".join([gw.id for gw in gateways])
        msg = "[%s] rsyncing: %s" %(targets, source)
        self.report_line(msg)

    #def pytest_gwmanage_rsyncfinish(self, source, gateways):
    #    targets = ", ".join(["[%s]" % gw.id for gw in gateways])
    #    self.write_line("rsyncfinish: %s -> %s" %(source, targets))

    def main(self, colitems):
        self.sessionstarts()
        self.setup()
        allitems = self.collect_all_items(colitems)
        exitstatus = self.loop(allitems)
        self.teardown()
        self.sessionfinishes(exitstatus=exitstatus) 
        return exitstatus

    def collect_all_items(self, colitems):
        self.report_line("[master] starting full item collection ...")
        allitems = list(self.collect(colitems))
        self.report_line("[master] collected %d items" %(len(allitems)))
        return allitems

    def loop_once(self, loopstate):
        if loopstate.shuttingdown:
            return self.loop_once_shutdown(loopstate)
        colitems = loopstate.colitems 
        if self._nodesready.isSet() and loopstate.dowork and colitems:
            self.triggertesting(loopstate.colitems) 
            colitems[:] = []
        # we use a timeout here so that control-C gets through 
        while 1:
            try:
                eventcall = self.queue.get(timeout=2.0)
                break
            except queue.Empty:
                continue
        loopstate.dowork = True 
          
        callname, args, kwargs = eventcall
        if callname is not None:
            call = getattr(self.config.hook, callname)
            assert not args
            call(**kwargs)

        # termination conditions
        maxfail = self.config.getvalue("maxfail")
        if (not self.node2pending or 
            (loopstate.testsfailed and maxfail and 
             loopstate.testsfailed >= maxfail) or 
            (not self.item2nodes and not colitems and not self.queue.qsize())):
            if maxfail and loopstate.testsfailed >= maxfail:
                raise self.Interrupted("stopping after %d failures" % (
                    loopstate.testsfailed))
            self.triggershutdown()
            loopstate.shuttingdown = True
            if not self.node2pending:
                loopstate.exitstatus = session.EXIT_NOHOSTS
                
    def loop_once_shutdown(self, loopstate):
        # once we are in shutdown mode we dont send 
        # events other than HostDown upstream 
        eventname, args, kwargs = self.queue.get()
        if eventname == "pytest_testnodedown":
            self.config.hook.pytest_testnodedown(**kwargs)
            self.removenode(kwargs['node'])
        elif eventname == "pytest_runtest_logreport":
            # might be some teardown report
            self.config.hook.pytest_runtest_logreport(**kwargs)
        elif eventname == "pytest_internalerror":
            self.config.hook.pytest_internalerror(**kwargs)
            loopstate.exitstatus = session.EXIT_INTERNALERROR
        elif eventname == "pytest__teardown_final_logerror":
            self.config.hook.pytest__teardown_final_logerror(**kwargs)
            loopstate.exitstatus = session.EXIT_TESTSFAILED
        if not self.node2pending:
            # finished
            if loopstate.testsfailed:
                loopstate.exitstatus = session.EXIT_TESTSFAILED
            else:
                loopstate.exitstatus = session.EXIT_OK
        #self.config.pluginmanager.unregister(loopstate)

    def _initloopstate(self, colitems):
        loopstate = LoopState(self, colitems)
        self.config.pluginmanager.register(loopstate)
        return loopstate

    def loop(self, colitems):
        try:
            loopstate = self._initloopstate(colitems)
            loopstate.dowork = False # first receive at least one HostUp events
            while 1:
                self.loop_once(loopstate)
                if loopstate.exitstatus is not None:
                    exitstatus = loopstate.exitstatus
                    break 
        except KeyboardInterrupt:
            excinfo = py.code.ExceptionInfo()
            self.config.hook.pytest_keyboard_interrupt(excinfo=excinfo)
            exitstatus = session.EXIT_INTERRUPTED
        except:
            self.config.pluginmanager.notify_exception()
            exitstatus = session.EXIT_INTERNALERROR
        self.config.pluginmanager.unregister(loopstate)
        if exitstatus == 0 and self._testsfailed:
            exitstatus = session.EXIT_TESTSFAILED
        return exitstatus

    def triggershutdown(self):
        for node in self.node2pending:
            node.shutdown()

    def addnode(self, node):
        assert node not in self.node2pending
        self.node2pending[node] = []
        if (not hasattr(self, 'nodemanager') or 
          len(self.node2pending) == len(self.nodemanager.gwmanager.group)):
            self._nodesready.set()

    def removenode(self, node):
        try:
            pending = self.node2pending.pop(node)
        except KeyError:
            # this happens if we didn't receive a testnodeready event yet
            return []
        for item in pending:
            l = self.item2nodes[item]
            l.remove(node)
            if not l:
                del self.item2nodes[item]
        return pending

    def triggertesting(self, colitems):
        # for now we don't allow sending collectors 
        for next in colitems:
            assert isinstance(next, py.test.collect.Item), next
        senditems = list(colitems)
        if self.config.option.dist == "each":
            self.senditems_each(senditems)
        else:
            # XXX assert self.config.option.dist == "load"
            self.senditems_load(senditems)

    def queueevent(self, eventname, **kwargs):
        self.queue.put((eventname, (), kwargs)) 

    def senditems_each(self, tosend):
        if not tosend:
            return 
        for node, pending in self.node2pending.items():
            node.sendlist(tosend)
            pending.extend(tosend)
            for item in tosend:
                nodes = self.item2nodes.setdefault(item, [])
                assert node not in nodes
                nodes.append(node)
                item.ihook.pytest_itemstart(item=item, node=node)
        tosend[:] = []

    def senditems_load(self, tosend):
        if not tosend:
            return 
        available = []
        for node, pending in self.node2pending.items():
            if len(pending) < self.LOAD_THRESHOLD_NEWITEMS:
                available.append((node, pending))
        num_available = len(available)
        max_one_round = num_available * self.ITEM_CHUNKSIZE -1
        if num_available:
            for i, item in enumerate(tosend):
                nodeindex = i % num_available
                node, pending = available[nodeindex]
                node.send(item)
                self.item2nodes.setdefault(item, []).append(node)
                item.ihook.pytest_itemstart(item=item, node=node)
                pending.append(item)
                if i >= max_one_round:
                    break
            del tosend[:i+1]
        if tosend:
            # we have some left, give it to the main loop
            self.queueevent("pytest_rescheduleitems", items=tosend)

    def removeitem(self, item, node):
        if item not in self.item2nodes:
            raise AssertionError(item, self.item2nodes)
        nodes = self.item2nodes[item]
        if node in nodes: # the node might have gone down already
            nodes.remove(node)
        if not nodes:
            del self.item2nodes[item]
        pending = self.node2pending[node]
        pending.remove(item)

    def handle_crashitem(self, item, node):
        runner = item.config.pluginmanager.getplugin("runner") 
        info = "!!! Node %r crashed during running of test %r" %(node, item)
        rep = runner.ItemTestReport(item=item, excinfo=info, when="???")
        rep.node = node
        item.ihook.pytest_runtest_logreport(report=rep)

    def setup(self):
        """ setup any neccessary resources ahead of the test run. """
        self.nodemanager = NodeManager(self.config)
        self.nodemanager.setup_nodes(putevent=self.queue.put)

    def teardown(self):
        """ teardown any resources after a test run. """ 
        self.nodemanager.teardown_nodes()

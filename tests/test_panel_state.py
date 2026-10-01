"""Execute the actual panel's pure JavaScript state/queue functions without a UI."""
from pathlib import Path
import shutil
import subprocess
import unittest


class PanelStateTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is needed for the QML JavaScript regression check')
    def test_out_of_order_output_and_stale_snapshots(self):
        source = (Path(__file__).resolve().parents[1] / 'Panel.qml').read_text()
        functions = []
        for name in ('accept', 'startNext', 'finishAction'):
            start = source.index('  function ' + name + '(')
            body = source.index('{', start)
            depth, end = 1, body + 1
            while depth:
                depth += (source[end] == '{') - (source[end] == '}')
                end += 1
            functions.append(source[start:end].replace('function ' + name, 'root.' + name + ' = function', 1))
        program = '''
const assert = require('node:assert/strict');
const scheduled = [];
const Qt = {callLater: f => scheduled.push(f)};
const control = {running: false, command: []};
const root = {snapshot:{instance:10,revision:3,mode:'steady',roles:[]},
 initialized:true,installFailed:false,setupVisible:false,preferencesVisible:false,cursor:0,
 awaitingConfirm:false,returnToControlsOnReady:false,localError:'',activeAction:'',
 pendingActions:[],controlScript:'/isolated/control.sh',outputFinished:false,
 processFinished:false,processOutput:'',processCode:0};
with(root) { FUNCTIONS }
const state = (instance, revision, mode) => JSON.stringify({instance,revision,mode,roles:[],ok:true});
root.accept(state(10,2,'cycle'));
assert.equal(root.snapshot.mode,'steady');
root.accept(state(11,1,'steady'));
root.accept(state(10,999,'cycle'));
assert.equal(root.snapshot.instance,11);
assert.equal(root.snapshot.mode,'steady');
for (const first of ['outputFinished','processFinished']) {
 root.activeAction=''; control.running=false; scheduled.length=0;
 root.pendingActions=[{action:'status'},{action:'mode',value:'steady'}];
 root.startNext();
 assert.equal(root.activeAction,'status');
 root.processOutput=state(10,1000,'cycle');
 control.running=false;
 root[first]=true;
 root.finishAction(); root.startNext();
 assert.equal(root.activeAction,'status');
 assert.equal(scheduled.length,0);
 root.outputFinished=true; root.processFinished=true;
 root.finishAction(); root.finishAction();
 assert.equal(root.snapshot.mode,'steady');
 assert.equal(scheduled.length,1);
 scheduled.shift()();
 assert.equal(root.activeAction,'mode');
 assert.deepEqual(control.command,['bash','/isolated/control.sh','mode','steady']);
}
'''.replace('FUNCTIONS', '\n'.join(functions))
        result = subprocess.run([shutil.which('node'), '-e', program], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

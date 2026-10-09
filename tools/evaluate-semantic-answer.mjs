import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { inspectReport, finalizeReport } from '../evals/semantic/report_gate.mjs';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const directory = path.join(root,'evals/semantic');
const require = createRequire(import.meta.url);
const { python } = require('../evals/semantic/bridge.cjs');

export function cleanEnvironment(temp, options, inherited = process.env) {
  const env = {
    PATH: inherited.PATH, HOME: temp, TMPDIR: temp, LANG:'C.UTF-8',
    LITELLM_LOCAL_MODEL_COST_MAP:'True', DOTENV_CONFIG_PATH:path.join(temp,'empty.env'),
    PROMPTFOO_CONFIG_DIR:path.join(temp,'promptfoo'), PROMPTFOO_DISABLE_TELEMETRY:'1',
    PROMPTFOO_DISABLE_UPDATE:'1', PROMPTFOO_DISABLE_SHARING:'1',
    PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION:'1', PROMPTFOO_CACHE_ENABLED:'false',
    DSC_ANSWER_MODE:options.mode,
  };
  for (const name of ['SOCKET','PORT','DATABASE','USER']) {
    const key = `DSC_TEST_POSTGRES_${name}`;
    if (inherited[key]) env[key] = inherited[key];
  }
  if (options.profile) env.DSC_ANSWER_PROFILE = options.profile;
  if (options.variant) env.DSC_ANSWER_VARIANT = options.variant;
  return env;
}
function command(args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath,args,options);
    let stderr = '';
    child.stdout.on('data',() => {}); // promptfoo table/raw text stays private
    child.stderr.on('data',chunk => { if (stderr.length < 4096) stderr += chunk; });
    child.once('error',reject);
    child.once('exit',code => resolve({code}));
  });
}
export async function main(argv = process.argv.slice(2)) {
  let temp;
  let output;
  let stage = "configuration";
  try {
    const options = {mode:'fixture',runs:3};
    for (let i = 0; i < argv.length; i++) {
      const name = argv[i];
      if (name === '--execute-local-model') options.execute = true;
      else {
        if (!['--mode','--runs','--profile','--output','--fixture-variant'].includes(name) || !argv[i+1]) throw new Error('arguments');
        const value = argv[++i];
        if (name === '--mode') options.mode = value;
        if (name === '--runs') options.runs = Number(value);
        if (name === '--profile') options.profile = path.resolve(value);
        if (name === '--output') output = path.resolve(value);
        if (name === '--fixture-variant') options.variant = value;
      }
    }
    if (!['fixture','local_model'].includes(options.mode) || !Number.isSafeInteger(options.runs) || options.runs < 1) throw new Error('arguments');
    if (options.mode === 'local_model' && (!options.execute || !options.profile)) {
      process.stdout.write('{"status":"NOT RUN","reason":"explicit execution and profile required"}\n');
      return 3;
    }
    if (options.mode === 'fixture' && (options.profile || options.execute)) throw new Error('fixture-profile');
    if (options.variant && (options.mode !== 'fixture' || !['forbidden','missing','error'].includes(options.variant))) throw new Error('fixture-variant');
    const pkg = require('../evals/semantic/node_modules/promptfoo/package.json');
    if (pkg.version !== '0.117.2') throw new Error('promptfoo-version');
    stage = "manifest";
    const manifest = python({operation:'manifest',mode:options.mode,profile:options.profile});
    const identity = Object.fromEntries(Object.entries(manifest).filter(([key]) => !['schema_version','commit','case_version','promptfoo_version'].includes(key)));
    temp = fs.mkdtempSync(path.join(os.tmpdir(),'core-answer-'));
    fs.chmodSync(temp,0o700);
    fs.writeFileSync(path.join(temp,'empty.env'),'');
    const env = cleanEnvironment(temp,options);
    const runs = [];
    for (let n = 1; n <= options.runs; n++) {
      const raw = path.join(temp,`run-${n}.json`);
      stage = "promptfoo-export";
      const result = await command([
        '--require',path.join(directory,'network_guard.cjs'),
        path.join(directory,'node_modules/promptfoo/dist/src/main.js'),'eval',
        '--config',path.join(directory,'config.cjs'),'--no-cache','--no-progress-bar',
        '--env-file',path.join(temp,'empty.env'),'--output',raw,
      ],{cwd:temp,env,stdio:['ignore','pipe','pipe']});
      // Assertion failures can be quality failures; execution errors cannot.
      if (![0,100].includes(result.code) || !fs.existsSync(raw)) throw new Error('promptfoo-export');
      stage = "report-gate";
      runs.push(inspectReport(JSON.parse(fs.readFileSync(raw,'utf8')),{mode:options.mode,identity}));
      process.stderr.write(`answer ${options.mode} run ${n}: ${runs.at(-1).passed ? 'PASS' : 'FAIL'} (${runs.at(-1).cases.length} cases)\n`);
    }
    const report = finalizeReport(manifest,runs,options.runs);
    const encoded = JSON.stringify(report,null,2)+'\n';
    if (output) fs.writeFileSync(output,encoded,{mode:0o600});
    else process.stdout.write(encoded);
    return report.passed ? 0 : 1;
  } catch (error) {
    // Reasons are structural identifiers only; never print raw SDK or promptfoo text.
    const reason = /^[a-z-]+$/.test(error?.message || '') ? error.message : 'inconsistent-data';
    process.stderr.write(`回答評価 FAIL (${stage}: ${reason})。\n`);
    return 1;
  } finally {
    if (temp) fs.rmSync(temp,{recursive:true,force:true});
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await main();
